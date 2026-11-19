#!/usr/bin/env python3
"""Superviseur de la session de nuit RC14.

Lance Claude Code en mode non interactif (`claude -p`, sortie stream-json), attend sa fin, CLASSE la cause de l'arrêt,
sauvegarde l'état dans le fichier de reprise, puis décide :

  fin_normale        -> pas de relance (une seule relance si le marqueur TERMINE est absent : la mission n'est pas déclarée finie)
  quota              -> attente de la prochaine fenêtre (23:20 Asia/Makassar ou heure de reprise lue sans ambiguïté), puis relance ;
                        ensuite un nouvel essai toutes les RETRY_MIN minutes, au plus MAX_QUOTA_WAITS fois
  transitoire        -> serveur surchargé (« not your usage limit », 529, overloaded) : nouvel essai après TRANSIENT_MIN minutes, au plus MAX_TRANSIENT fois
  erreur_technique   -> AUCUNE relance (authentification, configuration, plantage) : documenté, le superviseur s'arrête
  arret_volontaire   -> fichier STOP ou signal reçu : arrêt propre, aucune relance

Garde-fous : MAX_LAUNCHES lancements au total, heure limite (DEADLINE_WITA du lendemain matin), aucune boucle serrée.
Le superviseur ne contourne aucune limite : il attend la réinitialisation, il ne change ni de compte ni de clé.
Variables de test (jamais utilisées la nuit) : CLAUDE_BIN, SUP_STATE_DIR, SUP_CONT, SUP_TIME_SCALE, SUP_RESET_IN_S, SUP_DEADLINE_IN_S.
"""
import datetime as dt, json, os, re, signal, subprocess, sys, time
from zoneinfo import ZoneInfo

W = '/root/time-billing-v9-rc10-20261004'
WITA = ZoneInfo('Asia/Makassar')
E = os.environ.get
CLAUDE_BIN = E('CLAUDE_BIN', '/root/.local/bin/claude')
STATE = E('SUP_STATE_DIR', W + '/nuit')
LOGS = STATE + '/logs'
CONT = E('SUP_CONT', '/root/time-billing-v9/CONTINUATION-RC14.md')
MODEL = E('SUP_MODEL', 'opus')
SETTINGS = W + '/nuit/settings-nuit.json'
MAX_LAUNCHES = int(E('SUP_MAX_LAUNCHES', '10'))
MAX_QUOTA_WAITS = int(E('SUP_MAX_QUOTA_WAITS', '8'))
MAX_TRANSIENT = int(E('SUP_MAX_TRANSIENT', '3'))
MAX_NO_MARKER = 1
RETRY_MIN, TRANSIENT_MIN = 30, 10
RESET_WITA, DEADLINE_WITA = (23, 20), (9, 0)
SCALE = float(E('SUP_TIME_SCALE', '1'))          # tests : 60 => une minute dure une seconde

QUOTA_RE = re.compile(r'usage limit reached|hit your (usage )?limit|weekly usage limit|usage credit limit|limit will reset|'
                      r'(5-hour|session|daily|weekly|opus|sonnet|fable) limit reached|out of (extra )?usage', re.I)
TRANSIENT_RE = re.compile(r'not your usage limit|overloaded|\b529\b|temporarily limiting|econnreset|etimedout|socket hang up|network error', re.I)
TECH_RE = re.compile(r'\b401\b|invalid api key|please run /login|credit balance|not logged in|authentication', re.I)

child = None
stop_requested = False


def now():
    return dt.datetime.now(dt.timezone.utc)


def log(msg):
    line = f'{now().astimezone(WITA):%Y-%m-%d %H:%M:%S} WITA | {msg}'
    print(line, flush=True)
    with open(LOGS + '/superviseur.log', 'a') as f: f.write(line + '\n')


def save_state(**kw):
    p = STATE + '/ETAT-SUPERVISEUR.json'
    try: st = json.load(open(p))
    except Exception: st = {}
    st.update(kw, updated=now().isoformat(timespec='seconds'))
    tmp = p + '.tmp'; json.dump(st, open(tmp, 'w'), indent=2, ensure_ascii=False); os.replace(tmp, p)
    return st


def next_reset(after):
    """Prochaine réinitialisation déclarée par l'utilisateur : 23:20 Asia/Makassar."""
    if E('SUP_RESET_IN_S'): return after + dt.timedelta(seconds=float(E('SUP_RESET_IN_S')) / SCALE)
    loc = after.astimezone(WITA)
    r = loc.replace(hour=RESET_WITA[0], minute=RESET_WITA[1], second=0, microsecond=0)
    if r <= loc: r += dt.timedelta(days=1)
    return r.astimezone(dt.timezone.utc)


def parsed_reset(text):
    """Heure de reprise lue dans le message SEULEMENT si elle est non ambiguë (époque Unix ou date ISO avec UTC). Sinon None."""
    m = re.search(r'\|(\d{10})\b', text)
    if m: return dt.datetime.fromtimestamp(int(m.group(1)), dt.timezone.utc)
    m = re.search(r'(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2})?\s*(UTC|Z)', text)
    if m: return dt.datetime.fromisoformat(f'{m.group(1)}T{m.group(2)}:00+00:00')
    return None


def sleep_until(t, why):
    log(f'attente jusqu\'à {t.astimezone(WITA):%d.%m %H:%M} WITA ({why})')
    save_state(status='attente', next_attempt=t.isoformat(timespec='seconds'), waiting_for=why)
    while now() < t:
        if stop_requested or os.path.exists(STATE + '/STOP'): return False
        time.sleep(min(30.0, max(0.2, (t - now()).total_seconds())))
    return True


def git(*a):
    try: return subprocess.run(['git', '-C', W, *a], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as e: return f'(git indisponible : {e})'


def snapshot(n, outcome, detail, next_t=None):
    """Section ajoutée au fichier de reprise à chaque arrêt, indépendamment de Claude (qui peut ne plus pouvoir écrire)."""
    os.makedirs(os.path.dirname(CONT), exist_ok=True)
    status = git('status', '--short')
    sec = [f'\n\n## Arrêt automatique n° {n} — {now().astimezone(WITA):%Y-%m-%d %H:%M} WITA (écrit par le superviseur)',
           f'* Cause classée : **{outcome}**', f'* Détail : {detail[:600]}',
           f'* Branche : `{git("branch", "--show-current")}` — dernier commit : `{git("log", "-1", "--format=%h %s")}`',
           f'* Modifications non commitées : {"aucune" if not status else ""}']
    if status: sec.append('```\n' + status[:3000] + '\n```')
    if next_t: sec.append(f'* Prochaine tentative prévue : {next_t.astimezone(WITA):%d.%m %H:%M} WITA')
    with open(CONT, 'a') as f: f.write('\n'.join(sec) + '\n')


def prompt(first, last_outcome):
    if first:
        return (f'Lis {W}/nuit/MISSION-NUIT-RC14.md puis {W}/nuit/HANDOFF-NUIT-RC14.md et exécute la mission de nuit de façon autonome, '
                'cycle par cycle, jusqu\'à la condition d\'arrêt. Personne ne répondra avant demain : ne pose pas de question, '
                f'documente les blocages dans RAPPORT-NUIT-RC14.md. Tiens à jour {CONT} après chaque cycle.')
    return (f'REPRISE de la mission de nuit RC14 (arrêt précédent : {last_outcome}). Ne te fie pas à l\'historique : lis d\'abord {CONT} '
            f'(état, dernière tâche, tâche suivante, sections « Arrêt automatique » en fin de fichier), puis {W}/nuit/MISSION-NUIT-RC14.md '
            f'et {W}/nuit/HANDOFF-NUIT-RC14.md. Vérifie `git status` : des modifications non commitées peuvent venir de la session interrompue ; '
            'relis-les, termine-les ou annule-les proprement (jamais reset --hard). Puis poursuis au point indiqué jusqu\'à la condition d\'arrêt.')


def run_claude(n, text):
    global child
    out, err = f'{LOGS}/claude-{n:02d}.jsonl', f'{LOGS}/claude-{n:02d}.err'
    env = {'HOME': '/root', 'USER': 'root', 'LANG': 'C.UTF-8', 'TERM': 'dumb', 'CLAUDE_CONFIG_DIR': '/root/.claude-account2',
           'PATH': '/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'}
    env.update({k: v for k, v in os.environ.items() if k.startswith('FAUX_')})   # tests uniquement (faux claude)
    cmd = [CLAUDE_BIN, '-p', text, '--model', MODEL, '--settings', SETTINGS, '--permission-mode', 'acceptEdits', '--output-format', 'stream-json', '--verbose']
    log(f'lancement n° {n} ({os.path.basename(CLAUDE_BIN)}) -> {out}')
    with open(out, 'w') as fo, open(err, 'w') as fe:
        child = subprocess.Popen(cmd, cwd=W, env=env, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL, start_new_session=True)
        save_state(status='claude en cours', pid=child.pid, launch=n, log=out)
        rc = child.wait(); child = None
    result = None
    for line in open(out, errors='replace'):
        try: ev = json.loads(line)
        except Exception: continue
        if ev.get('type') == 'result': result = ev
    errtail = open(err, errors='replace').read()[-4000:]
    return rc, result, errtail


def classify(rc, result, errtail):
    if stop_requested: return 'arret_volontaire', 'signal reçu'
    rtext = (result or {}).get('result') or ''
    sub = (result or {}).get('subtype', '')
    text = f'{rtext}\n{errtail}'
    detail = (rtext or errtail or f'code de sortie {rc}').strip().replace('\n', ' ')
    if TRANSIENT_RE.search(text): return 'transitoire', detail
    if QUOTA_RE.search(text): return 'quota', detail
    if TECH_RE.search(text): return 'erreur_technique', detail
    if result and not result.get('is_error') and sub == 'success' and rc == 0: return 'fin_normale', detail
    return 'erreur_technique', f'code {rc}, sous-type {sub or "aucun résultat"} : {detail}'


def on_signal(sig, _):
    global stop_requested
    stop_requested = True
    log(f'signal {signal.Signals(sig).name} reçu : arrêt volontaire demandé')
    if child and child.poll() is None:
        try: os.killpg(child.pid, signal.SIGINT)
        except Exception: pass


def main():
    os.makedirs(LOGS, exist_ok=True)
    signal.signal(signal.SIGTERM, on_signal); signal.signal(signal.SIGINT, on_signal); signal.signal(signal.SIGHUP, signal.SIG_IGN)
    start = now()
    if E('SUP_DEADLINE_IN_S'): deadline = start + dt.timedelta(seconds=float(E('SUP_DEADLINE_IN_S')) / SCALE)
    else:
        loc = start.astimezone(WITA); d = loc.replace(hour=DEADLINE_WITA[0], minute=DEADLINE_WITA[1], second=0, microsecond=0)
        if d <= loc: d += dt.timedelta(days=1)
        deadline = d.astimezone(dt.timezone.utc)
    save_state(status='démarré', pid_superviseur=os.getpid(), started=start.isoformat(timespec='seconds'), deadline=deadline.isoformat(timespec='seconds'),
               launches=0, quota_waits=0, transient=0, no_marker=0, last_outcome=None, history=[])
    log(f'superviseur démarré (pid {os.getpid()}), heure limite {deadline.astimezone(WITA):%d.%m %H:%M} WITA, au plus {MAX_LAUNCHES} lancements')
    n = quota = transient = no_marker = 0; last = None; history = []
    while True:
        why_stop = None
        if stop_requested or os.path.exists(STATE + '/STOP'): why_stop = 'arrêt volontaire (fichier STOP ou signal)'
        elif os.path.exists(STATE + '/TERMINE'): why_stop = 'mission déclarée terminée (marqueur TERMINE)'
        elif now() >= deadline: why_stop = 'heure limite atteinte'
        elif n >= MAX_LAUNCHES: why_stop = f'nombre maximal de lancements atteint ({MAX_LAUNCHES})'
        if why_stop:
            log(f'fin du superviseur : {why_stop}'); save_state(status='terminé', reason=why_stop); return 0
        n += 1
        rc, result, errtail = run_claude(n, prompt(n == 1, last))
        outcome, detail = classify(rc, result, errtail)
        cost = (result or {}).get('total_cost_usd'); turns = (result or {}).get('num_turns')
        history.append({'n': n, 'outcome': outcome, 'rc': rc, 'turns': turns, 'at': now().isoformat(timespec='seconds')})
        log(f'lancement n° {n} terminé : {outcome} (code {rc}, tours {turns}) — {detail[:200]}')
        last = outcome; nxt = None
        if outcome == 'quota':
            quota += 1
            if quota > MAX_QUOTA_WAITS:
                snapshot(n, outcome, detail); save_state(status='terminé', reason='quota toujours indisponible après le nombre maximal d\'essais', history=history)
                log('quota toujours indisponible : arrêt sans nouvelle tentative'); return 0
            pr = parsed_reset(detail)
            nxt = next_reset(now()) if quota == 1 else now() + dt.timedelta(minutes=RETRY_MIN / SCALE)
            if pr and now() < pr < nxt: nxt = pr
            if nxt > deadline:
                snapshot(n, outcome, detail); save_state(status='terminé', reason='prochaine fenêtre de quota après l\'heure limite', history=history)
                log('la prochaine fenêtre de quota dépasse l\'heure limite : arrêt'); return 0
            snapshot(n, outcome, detail, nxt); save_state(last_outcome=outcome, launches=n, quota_waits=quota, history=history)
            if not sleep_until(nxt, 'réinitialisation du quota' if quota == 1 else f'nouvel essai quota n° {quota}'): continue
        elif outcome == 'transitoire':
            transient += 1
            if transient > MAX_TRANSIENT:
                snapshot(n, outcome, detail); save_state(status='terminé', reason='erreurs transitoires répétées', history=history)
                log('erreurs transitoires répétées : arrêt'); return 0
            nxt = now() + dt.timedelta(minutes=TRANSIENT_MIN / SCALE)
            snapshot(n, outcome, detail, nxt); save_state(last_outcome=outcome, launches=n, transient=transient, history=history)
            if not sleep_until(nxt, 'serveur surchargé'): continue
        elif outcome == 'fin_normale':
            if os.path.exists(STATE + '/TERMINE') or no_marker >= MAX_NO_MARKER:
                snapshot(n, outcome, detail); save_state(status='terminé', reason='fin normale de Claude', history=history)
                log('fin normale : pas de relance'); return 0
            no_marker += 1
            snapshot(n, outcome, 'fin normale SANS marqueur TERMINE : une seule relance de vérification'); save_state(last_outcome=outcome, launches=n, no_marker=no_marker, history=history)
            log('fin normale sans marqueur TERMINE : une relance unique pour vérifier la condition d\'arrêt')
        else:   # erreur_technique ou arret_volontaire : jamais de relance
            snapshot(n, outcome, detail); save_state(status='terminé', reason=outcome, history=history)
            log(f'{outcome} : aucune relance automatique'); return 0


if __name__ == '__main__':
    sys.exit(main())
