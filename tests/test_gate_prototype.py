"""rc25 — tests de FAISABILITÉ du vérificateur indépendant (conception/rc25-gate-prototype), pas de la production.

Ils montrent, dans un dossier temporaire et avec des clés jetables générées ici, que l'architecture proposée (CONCEPTION-GARDE-CONFIANCE-RC25.md) tient ses promesses :
signature du manifeste, chaîne de confiance, instantané privé exécuté (pas de TOCTOU après copie), environnement reconstruit, binaire statique insensible à LD_PRELOAD.
La clé publique de confiance est figée à la construction (-ldflags -X) vers un dossier temporaire du test, jamais /etc.
Ignorés sans root, go, openssl ou gcc. Rien n'est installé, aucun /etc /opt /root réel.
"""
import hashlib, json, os, shutil, signal, stat, subprocess, tempfile, time, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, 'conception', 'rc25-gate-prototype')
NEEDS = all(shutil.which(t) for t in ('go', 'openssl', 'gcc')) and os.geteuid() == 0

ENTRY = '''#!/bin/bash
sleep "${1:-0}"
. "$(dirname "$0")/helper.sh"
echo "ENTRY-OK flags=$- BASH_ENV=${BASH_ENV-<vide>} LD_PRELOAD=${LD_PRELOAD-<vide>} helper=${helper_loaded-vide} script=$0"
'''
HOSTILE_SO = r'''#include <stdio.h>
#include <stdlib.h>
__attribute__((constructor)) static void init(void){ const char*m=getenv("MK"); if(!m) return; FILE*f=fopen(m,"a"); if(f){fputs("preload\n",f); fclose(f);} }
'''
# L'état des signaux n'est PAS lu dans /proc/$$/status du script : bash (même non interactif, cf. initialize_shell_signals) ignore
# lui-même SIGQUIT au démarrage, ce qui masquerait ce qu'il a reçu de l'exec. Il le rétablit en revanche à sa valeur d'origine avant
# d'exécuter un programme : la sonde se termine donc par `exec` d'un exécutable natif qui lit /proc/self/status avant toute autre action.
# Le témoin (même enchaînement, sans vérificateur) prouve que cette chaîne transmet fidèlement dispositions ignorées et masque.
PROBE = '''#!/bin/bash
echo "cwd=$(pwd -P)"
echo "umask=$(umask)"
for n in "$@"; do if { : >&"$n"; } 2>/dev/null; then echo "fd$n=open"; else echo "fd$n=closed"; fi; done
while read -r k v; do case $k in SigIgn:) echo "bash-SigIgn=$v";; esac; done < /proc/$$/status
echo "PROBE-STDERR" >&2
exec "$(dirname "$0")/sigstate"
'''
SIGSTATE_C = r'''#include <stdio.h>
#include <string.h>
int main(void){ char l[256]; FILE*f=fopen("/proc/self/status","r"); if(!f) return 99;
  while(fgets(l,sizeof l,f)) if(!strncmp(l,"SigIgn:",7)||!strncmp(l,"SigBlk:",7)) fputs(l,stdout);
  return fclose(f)?99:0; }
'''
HOSTILE_SIGNALS = (signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, signal.SIGPIPE, signal.SIGALRM, signal.SIGTERM, signal.SIGUSR1, signal.SIGTSTP)


def sigmask(line):
    return int(line.split(':', 1)[1], 16)


@unittest.skipUnless(NEEDS, 'faisabilité : exige root, go, openssl et gcc')
class GatePrototype(unittest.TestCase):
    @classmethod
    def go_build(cls, out, key_path):
        return subprocess.run(['go', 'build', '-trimpath', '-ldflags', '-X main.trustedKeyPath=' + key_path, '-o', out, '.'], cwd=SRC, capture_output=True, text=True,
                              env=dict(os.environ, CGO_ENABLED='0', GOFLAGS='-mod=mod', GOCACHE=os.path.join(cls.build, 'gocache'), HOME=cls.build))

    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.mkdtemp(prefix='tbgate-build-')
        cls.bin = os.path.join(cls.build, 'tb-gate-proto')
        cls.keydir = os.path.join(cls.build, 'trusted-key')                                                         # chemin figé dans le binaire, réécrit à chaque setUp
        cls.pub = os.path.join(cls.keydir, 'pub.raw')
        r = cls.go_build(cls.bin, cls.pub)
        if r.returncode != 0: raise unittest.SkipTest('go build impossible : ' + r.stderr[-300:])
        cls.so = os.path.join(cls.build, 'pre.so')
        with open(os.path.join(cls.build, 'pre.c'), 'w') as f: f.write(HOSTILE_SO)
        subprocess.run(['gcc', '-shared', '-fPIC', '-o', cls.so, os.path.join(cls.build, 'pre.c')], check=True)
        cls.sigstate = os.path.join(cls.build, 'sigstate')
        with open(os.path.join(cls.build, 'sigstate.c'), 'w') as f: f.write(SIGSTATE_C)
        subprocess.run(['gcc', '-o', cls.sigstate, os.path.join(cls.build, 'sigstate.c')], check=True)

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.build, ignore_errors=True)

    def setUp(self):
        self.td = tempfile.mkdtemp(prefix='tbgate-'); t = self.td
        self.rel, self.trust, self.snap = (os.path.join(t, d) for d in ('rel', 'trust', 'snap'))
        for d, m in ((self.rel, 0o755), (self.trust, 0o755), (self.snap, 0o700)): os.makedirs(d); os.chmod(d, m)
        os.chmod(t, 0o755)
        self.write('entry.sh', ENTRY); self.write('helper.sh', 'helper_loaded=1\n')
        self.priv = os.path.join(t, 'priv.pem')                                                                   # clé JETABLE : seule la partie publique va dans `keydir`
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', self.priv], check=True, capture_output=True)
        os.makedirs(self.keydir, exist_ok=True); os.chmod(self.keydir, 0o755)
        open(self.pub, 'wb').write(self.raw_pub(self.priv)); os.chmod(self.pub, 0o644)
        self.manifest = os.path.join(self.trust, 'manifest.json'); self.sig = os.path.join(self.trust, 'manifest.sig'); self.sign()

    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)

    @staticmethod
    def raw_pub(priv):
        return subprocess.run(['openssl', 'pkey', '-in', priv, '-pubout', '-outform', 'DER'], check=True, capture_output=True).stdout[-32:]

    def new_key(self, name):
        p = os.path.join(self.td, name)
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', p], check=True, capture_output=True)
        return p

    def write(self, name, text):
        p = os.path.join(self.rel, name); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').write(text); os.chmod(p, 0o644)

    def sign_manifest(self, manifest, key=None):
        open(self.manifest, 'w').write(json.dumps(manifest, sort_keys=True)); os.chmod(self.manifest, 0o644)
        subprocess.run(['openssl', 'pkeyutl', '-sign', '-inkey', key or self.priv, '-rawin', '-in', self.manifest, '-out', self.sig], check=True, capture_output=True)
        os.chmod(self.sig, 0o644)

    def sign(self, key=None):
        files = []
        for base, _, names in os.walk(self.rel):
            for n in sorted(names):
                full = os.path.join(base, n)
                rel = os.path.relpath(full, self.rel).replace(os.sep, '/')
                files.append({'Path': rel, 'Sha256': hashlib.sha256(open(full, 'rb').read()).hexdigest()})
        files.sort(key=lambda item: item['Path'])
        self.sign_manifest({'Version': 1, 'Dir': self.rel, 'Files': files}, key=key)

    def gate(self, env=None, snap=None, entry='entry.sh', args=(), **kw):
        e = dict(os.environ); e.update(env or {})
        return subprocess.run([self.bin, self.manifest, self.sig, snap or self.snap, '--', entry, *args], capture_output=True, text=True, env=e, cwd=self.td, **kw)

    def sign_raw(self, text):
        """Signe un texte JSON tel quel (clés dupliquées, casse, échappements) : json.dumps ne peut pas les produire."""
        open(self.manifest, 'w', encoding='utf-8').write(text); os.chmod(self.manifest, 0o644)
        subprocess.run(['openssl', 'pkeyutl', '-sign', '-inkey', self.priv, '-rawin', '-in', self.manifest, '-out', self.sig], check=True, capture_output=True)
        os.chmod(self.sig, 0o644)

    def digest(self, name):
        return hashlib.sha256(open(os.path.join(self.rel, name), 'rb').read()).hexdigest()

    def refused(self, r, text=None):
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr); self.assertIn('REFUS', r.stderr)
        if text: self.assertIn(text, r.stderr)
        self.assertEqual(r.stdout, '', 'rien ne doit s\'exécuter')

    # ---- succès et environnement ---------------------------------------------------------------------------------------------------------------
    def test_valid_release_runs_in_privileged_mode_from_a_private_snapshot(self):
        r = self.gate(); self.assertEqual(r.returncode, 0, r.stderr); self.assertIn('ENTRY-OK flags=hpB', r.stdout)
        self.assertIn('helper=1', r.stdout); self.assertIn(self.snap, r.stdout); self.assertNotIn(self.rel, r.stdout)

    def test_hostile_caller_environment_has_no_effect_not_even_ld_preload(self):
        mk = os.path.join(self.td, 'MK'); benv = os.path.join(self.td, 'benv.sh'); open(benv, 'w').write(f'echo benv >> "{mk}"\n')
        r = self.gate(env={'LD_PRELOAD': self.so, 'MK': mk, 'BASH_ENV': benv, 'SHELLOPTS': 'xtrace', 'PS4': f'$(echo ps4 >> {mk})+ ', 'BASH_FUNC_dirname%%': f'() {{ echo fn >> {mk}; }}'})
        self.assertEqual(r.returncode, 0, r.stderr); self.assertFalse(os.path.exists(mk), 'le vérificateur statique a laissé s\'exécuter du code de l\'environnement')
        self.assertIn('BASH_ENV=<vide>', r.stdout); self.assertIn('LD_PRELOAD=<vide>', r.stdout)

    def test_env_i_alone_does_not_stop_ld_preload_but_the_static_gate_does(self):
        """Fait observé : `env -i … bash -p` lancé dans un environnement qui porte LD_PRELOAD charge la bibliothèque dans `env` lui-même (binaire dynamique)."""
        mk = os.path.join(self.td, 'MK'); script = os.path.join(self.td, 's.sh'); open(script, 'w').write('#!/bin/bash\n:\n')
        subprocess.run(['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', '/bin/bash', '-p', script], env=dict(os.environ, LD_PRELOAD=self.so, MK=mk), capture_output=True)
        self.assertTrue(os.path.exists(mk), 'env -i n\'a pas empêché le préchargement dans `env` (limite démontrée)')
        os.remove(mk); self.assertEqual(self.gate(env={'LD_PRELOAD': self.so, 'MK': mk}).returncode, 0); self.assertFalse(os.path.exists(mk))

    # ---- intégrité : signature, empreintes, chaîne de confiance ---------------------------------------------------------------------------------
    def test_modified_script_modified_manifest_and_foreign_signature_are_refused(self):
        self.write('entry.sh', ENTRY + '# altéré\n'); self.refused(self.gate(), 'empreinte')
        self.write('entry.sh', ENTRY); self.assertEqual(self.gate().returncode, 0)
        m = open(self.manifest).read(); open(self.manifest, 'w').write(m.replace('"Version": 1', '"Version": 2')); self.refused(self.gate(), 'signature')
        self.sign(); other = self.new_key('other.pem')
        self.sign(key=other); self.refused(self.gate(), 'signature')

    # ---- A1 : clé publique figée à la construction -----------------------------------------------------------------------------------------------
    def test_caller_supplied_public_key_is_never_used(self):
        """Un appelant qui signe lui-même un manifeste et fournit sa clé publique (ancien argument) est refusé avant toute lecture."""
        attacker = self.new_key('attacker.pem'); apub = os.path.join(self.trust, 'attacker.raw')
        open(apub, 'wb').write(self.raw_pub(attacker)); os.chmod(apub, 0o644)
        self.sign(key=attacker)
        r = subprocess.run([self.bin, self.manifest, self.sig, apub, self.snap, '--', 'entry.sh'], capture_output=True, text=True, cwd=self.td)
        self.refused(r, 'usage')
        self.refused(self.gate(args=[apub]), 'signature')                                                           # la clé en argument de la procédure n'y change rien
        self.assertEqual(os.listdir(self.snap), [], 'aucun instantané ne doit être créé')

    def test_missing_trusted_key_fails_closed(self):
        os.remove(self.pub); self.refused(self.gate(), 'lstat')

    def test_relative_build_time_key_path_is_refused(self):
        rel_bin = os.path.join(self.td, 'gate-relkey')
        r = self.go_build(rel_bin, 'pub.raw'); self.assertEqual(r.returncode, 0, r.stderr)
        shutil.copy(self.pub, os.path.join(self.td, 'pub.raw'))                                                  # même présente dans le cwd, une clé relative est refusée
        r = subprocess.run([rel_bin, self.manifest, self.sig, self.snap, '--', 'entry.sh'], capture_output=True, text=True, cwd=self.td)
        self.refused(r, 'clé publique de confiance')

    def test_untrusted_chain_is_refused(self):
        cases = {'dossier des scripts modifiable par tous': lambda: os.chmod(self.rel, 0o777),
                 'fichier modifiable par le groupe': lambda: os.chmod(os.path.join(self.rel, 'helper.sh'), 0o664),
                 'fichier d\'un autre propriétaire': lambda: os.chown(os.path.join(self.rel, 'helper.sh'), 12345, 12345),
                 'clé publique modifiable par tous': lambda: os.chmod(self.pub, 0o666),
                 'dossier de la clé modifiable par tous': lambda: os.chmod(self.keydir, 0o777),
                 'dossier du manifeste modifiable par tous': lambda: os.chmod(self.trust, 0o777)}
        for label, prep in cases.items():
            with self.subTest(label):
                self.tearDown(); self.setUp(); prep(); self.refused(self.gate())
        self.tearDown(); self.setUp()
        os.rename(os.path.join(self.rel, 'helper.sh'), os.path.join(self.td, 'real-helper.sh')); os.symlink(os.path.join(self.td, 'real-helper.sh'), os.path.join(self.rel, 'helper.sh'))
        self.refused(self.gate(), 'lien symbolique')

    def test_parent_directory_writable_by_others_is_refused_but_a_sticky_ancestor_is_tolerated(self):
        parent = os.path.join(self.td, 'open'); os.makedirs(parent); os.chmod(parent, 0o777)
        moved = os.path.join(parent, 'rel'); shutil.copytree(self.rel, moved); self.rel = moved
        for n in os.listdir(moved): os.chmod(os.path.join(moved, n), 0o644)
        os.chmod(moved, 0o755); self.sign(); self.refused(self.gate(), 'modifiable')
        os.chmod(parent, 0o1777); self.assertEqual(self.gate().returncode, 0)                                      # sticky (ex. /tmp) : tolérée pour un ancêtre

    def test_missing_snapshot_root_or_unreadable_inputs_fail_closed(self):
        self.refused(self.gate(snap=os.path.join(self.td, 'absent')))
        os.remove(self.sig); self.refused(self.gate())

    def test_signed_manifest_rejects_traversal_and_duplicate_paths(self):
        digest = hashlib.sha256(open(os.path.join(self.rel, 'entry.sh'), 'rb').read()).hexdigest()
        self.sign_manifest({'Version': 1, 'Dir': self.rel + '\x00suffix', 'Files': [
            {'Path': 'entry.sh', 'Sha256': digest},
        ]})
        self.refused(self.gate(), 'Dir doit être un chemin absolu canonique')
        self.sign_manifest({'Version': 1, 'Dir': self.rel, 'Files': [
            {'Path': 'entry.sh\x00suffix', 'Sha256': digest},
        ]})
        self.refused(self.gate(), 'chemin de fichier non canonique')
        self.sign_manifest({'Version': 1, 'Dir': self.rel, 'Files': [
            {'Path': 'entry.sh', 'Sha256': digest},
            {'Path': '../outside.sh', 'Sha256': digest},
        ]})
        self.refused(self.gate(), 'chemin de fichier non canonique')
        self.sign_manifest({'Version': 1, 'Dir': self.rel, 'Files': [
            {'Path': 'entry.sh', 'Sha256': digest},
            {'Path': 'entry.sh', 'Sha256': digest},
        ]})
        self.refused(self.gate(), 'dupliqué')

    def test_relative_or_non_canonical_dir_and_absolute_or_non_canonical_paths_are_refused(self):
        digest = self.digest('entry.sh')
        for d in ('rel', os.path.relpath(self.rel, '/'), self.rel + '/', self.rel + '/.', self.rel + '//', os.path.join(self.rel, '..', 'rel'), ''):
            with self.subTest(Dir=d):
                self.sign_manifest({'Version': 1, 'Dir': d, 'Files': [{'Path': 'entry.sh', 'Sha256': digest}]})
                self.refused(self.gate(), 'Dir doit être un chemin absolu canonique')
        for p in (os.path.join(self.rel, 'entry.sh'), '/etc/passwd', './entry.sh', 'sub//x.sh', 'sub/../entry.sh', 'entry.sh/', 'sub\\entry.sh', '', '.', '..'):
            with self.subTest(Path=p):
                self.sign_manifest({'Version': 1, 'Dir': self.rel, 'Files': [{'Path': 'entry.sh', 'Sha256': digest}, {'Path': p, 'Sha256': digest}]})
                self.refused(self.gate(), 'chemin de fichier non canonique')

    def test_entry_must_be_listed_in_signed_manifest(self):
        digest = hashlib.sha256(open(os.path.join(self.rel, 'helper.sh'), 'rb').read()).hexdigest()
        self.sign_manifest({'Version': 1, 'Dir': self.rel, 'Files': [
            {'Path': 'helper.sh', 'Sha256': digest},
        ]})
        self.refused(self.gate(), 'entrée absente')

    def test_nested_files_are_copied_into_snapshot_and_can_run(self):
        self.write('procedure/entry.sh', ENTRY.replace('helper.sh', 'helper.sh'))
        self.write('procedure/helper.sh', 'helper_loaded=1\n')
        self.sign()
        r = self.gate(entry='procedure/entry.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('helper=1', r.stdout)
        self.assertIn(self.snap, r.stdout)
        self.assertNotIn(self.rel, r.stdout)

    def test_unknown_manifest_fields_and_unsupported_versions_are_refused(self):
        self.sign_manifest({'Version': 9, 'Dir': self.rel, 'Files': [
            {'Path': 'entry.sh', 'Sha256': hashlib.sha256(open(os.path.join(self.rel, 'entry.sh'), 'rb').read()).hexdigest()},
        ]})
        self.refused(self.gate(), 'version de manifeste')
        self.sign_manifest({'Version': 1, 'Dir': self.rel, 'Unexpected': True, 'Files': [
            {'Path': 'entry.sh', 'Sha256': hashlib.sha256(open(os.path.join(self.rel, 'entry.sh'), 'rb').read()).hexdigest()},
        ]})
        self.refused(self.gate(), 'manifeste')

    # ---- lectures bornées et fichiers réguliers --------------------------------------------------------------------------------------------------
    def sparse(self, name, size):
        p = os.path.join(self.rel, name)
        with open(p, 'wb') as f: f.truncate(size)
        os.chmod(p, 0o644)

    def test_oversized_manifest_is_refused_before_signature_check(self):
        self.sign_raw(' ' * ((1 << 20) + 1)); self.refused(self.gate(), 'dépasse')

    def test_oversized_source_file_is_refused(self):
        self.sparse('big.bin', (16 << 20) + 1); self.sign()
        self.refused(self.gate(), 'dépasse')

    def test_total_size_of_copied_files_is_bounded(self):
        for i in range(5): self.sparse(f'part{i}.bin', 15 << 20)                                                   # chacun sous la limite, 75 Mio au total
        self.sign(); self.refused(self.gate(), 'dépasse')

    def test_oversized_signature_and_trusted_key_are_refused(self):
        for label, attr in (('signature', 'sig'), ('clé publique de confiance', 'pub')):
            with self.subTest(label):
                self.tearDown(); self.setUp()                                                                       # signature, manifeste et clé valides à chaque cas
                self.assertEqual(self.gate().returncode, 0, 'témoin : la configuration saine doit passer')
                path = getattr(self, attr)
                with open(path, 'wb') as f: f.write(b'x' * ((4 << 10) + 1))                                         # seule l'entrée testée est trop grande
                r = self.gate(); self.refused(r, 'dépasse'); self.assertIn(path, r.stderr, 'le refus doit nommer l\'entrée trop grande')
    def test_non_regular_manifest_signature_and_trusted_key_are_refused_without_blocking(self):
        self.addCleanup(lambda: os.path.lexists(self.pub) and os.remove(self.pub))                                  # la clé est partagée : la remettre en fichier avant le setUp suivant
        for label, attr in (('manifeste', 'manifest'), ('signature', 'sig'), ('clé publique de confiance', 'pub')):  # la clé en dernier : setUp la réécrit
            with self.subTest(label):
                self.tearDown(); self.setUp(); path = getattr(self, attr)
                os.remove(path); os.mkfifo(path, 0o644)
                r = self.gate(timeout=20); self.refused(r, 'fichier régulier'); self.assertIn(path, r.stderr)

    def test_non_regular_sources_are_refused_without_blocking(self):
        helper = os.path.join(self.rel, 'helper.sh')
        os.remove(helper); os.mkfifo(helper, 0o644)                                                                # tube sans écrivain : open() bloquerait
        files = [{'Path': n, 'Sha256': self.digest(n) if n == 'entry.sh' else '0' * 64} for n in ('entry.sh', 'helper.sh')]
        self.sign_manifest({'Version': 1, 'Dir': self.rel, 'Files': files})
        self.refused(self.gate(timeout=20), 'fichier régulier')
        os.remove(helper)
        try: os.mknod(helper, 0o644 | stat.S_IFCHR, os.makedev(1, 5))                                              # /dev/zero : lecture sans fin
        except OSError as e: self.skipTest(f'mknod impossible : {e}')
        self.refused(self.gate(timeout=20), 'fichier régulier')
        os.remove(helper); os.mkdir(helper); os.chmod(helper, 0o755)
        self.refused(self.gate(timeout=20), 'fichier régulier')

    # ---- lectures bornées : courses déterministes (strace), O_NONBLOCK, bornes exactes, fichiers menteurs sur leur taille -------------------------
    def traced_gate(self, trace, inject, path, mutate, wait=1.0, after_open=None, rlimit_as=None):
        """Lance le vérificateur sous strace en retardant un appel système sur `path`, applique `mutate()` pendant le retard, rend (rc, stdout, stderr, journal)."""
        if not shutil.which('strace'): self.skipTest('strace absent : course non déterministe sans lui')
        log = os.path.join(self.td, 'strace.log')
        cmd = ['strace', '-f', '-o', log, '-e', 'trace=' + trace, '-P', path, '-e', 'inject=' + inject, self.bin, self.manifest, self.sig, self.snap, '--', 'entry.sh']
        def limits():
            if rlimit_as: import resource; resource.setrlimit(resource.RLIMIT_AS, (rlimit_as, rlimit_as))
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.td, preexec_fn=limits)
        deadline = time.time() + 15
        while after_open and time.time() < deadline:                                                                  # attend que l'ouverture ait eu lieu (le retard suit)
            if os.path.exists(log) and after_open in open(log).read(): break
            time.sleep(0.05)
        time.sleep(wait); mutate()
        try: out, err = p.communicate(timeout=60)
        except subprocess.TimeoutExpired: p.kill(); p.communicate(); self.fail('le vérificateur ne se termine pas')
        text = open(log).read() if os.path.exists(log) else ''
        if 'Operation not permitted' in err and 'ptrace' in err: self.skipTest('ptrace interdit dans cet environnement : ' + err[-200:])
        return p.returncode, out, err, text

    def test_trusted_key_replaced_between_check_and_open_is_refused(self):
        """Course lstat -> open sur la clé de confiance (non épinglée par SHA-256) : remplacée par une clé d'attaquant qui a signé le manifeste."""
        attacker = self.new_key('attacker.pem'); apub = os.path.join(self.keydir, 'attacker.raw')
        open(apub, 'wb').write(self.raw_pub(attacker)); os.chmod(apub, 0o644); self.sign(key=attacker)
        self.refused(self.gate(), 'signature')                                                                      # témoin : sans course, la clé d'attaquant est inopérante
        rc, out, err, _ = self.traced_gate('openat', 'openat:delay_enter=3s', self.pub, lambda: os.rename(apub, self.pub))
        self.assertEqual(rc, 3, out + err); self.assertIn('a changé entre le contrôle et l\'ouverture', err); self.assertEqual(out, '', 'rien ne doit s\'exécuter')

    def test_trusted_key_made_writable_between_check_and_open_is_refused(self):
        """Même inode, mode modifié entre le lstat et l'ouverture : seul le fstat du descripteur le voit."""
        self.assertEqual(self.gate().returncode, 0, 'témoin')
        rc, out, err, _ = self.traced_gate('openat', 'openat:delay_enter=3s', self.pub, lambda: os.chmod(self.pub, 0o666))
        self.assertEqual(rc, 3, out + err); self.assertIn('modifiable par groupe/autres (descripteur ouvert)', err); self.assertEqual(out, '')

    def test_trusted_key_chowned_between_check_and_open_is_refused(self):
        self.addCleanup(lambda: os.path.lexists(self.pub) and os.chown(self.pub, 0, 0))                             # la clé est partagée entre les tests : la rendre à root
        self.assertEqual(self.gate().returncode, 0, 'témoin')
        rc, out, err, _ = self.traced_gate('openat', 'openat:delay_enter=3s', self.pub, lambda: os.chown(self.pub, 12345, 12345))
        self.assertEqual(rc, 3, out + err); self.assertIn('n\'appartient pas à root (descripteur ouvert)', err); self.assertEqual(out, '')

    def test_source_file_replaced_by_identical_content_between_check_and_open_is_refused(self):
        """Course lstat -> open sur un fichier de la procédure : remplaçant au MÊME contenu (même SHA-256), seul le contrôle d'inode sur le descripteur le voit."""
        helper = os.path.join(self.rel, 'helper.sh'); twin = os.path.join(self.rel, '.twin')
        shutil.copy2(helper, twin); os.chmod(twin, 0o644)
        self.assertEqual(self.gate().returncode, 0, 'témoin : le fichier en trop hors manifeste ne gêne pas')
        rc, out, err, _ = self.traced_gate('openat', 'openat:delay_enter=3s', helper, lambda: os.rename(twin, helper))
        self.assertEqual(rc, 3, out + err); self.assertIn('a changé entre le contrôle et l\'ouverture', err); self.assertEqual(out, '', 'rien ne doit s\'exécuter')

    def test_source_file_swapped_for_a_symlink_between_check_and_open_is_refused(self):
        """Le dernier composant devient un lien symbolique (vers un contenu identique) pendant la course : O_NOFOLLOW refuse l'ouverture."""
        helper = os.path.join(self.rel, 'helper.sh'); real = os.path.join(self.td, 'real-helper.sh'); link = os.path.join(self.rel, '.link')
        shutil.copy2(helper, real); os.chmod(real, 0o644); os.symlink(real, link)
        rc, out, err, _ = self.traced_gate('openat', 'openat:delay_enter=3s', helper, lambda: os.rename(link, helper))
        self.assertEqual(rc, 3, out + err); self.assertIn('REFUS: open', err); self.assertEqual(out, '')

    def test_open_and_read_errors_on_a_source_file_fail_closed(self):
        """Erreurs injectées par strace (EACCES à l'ouverture, EIO à la lecture) : refus, rien n'est exécuté."""
        helper = os.path.join(self.rel, 'helper.sh')
        for inject, text in (('openat:error=EACCES', 'REFUS: open'), ('read:error=EIO', 'REFUS: lecture')):
            with self.subTest(inject):
                rc, out, err, _ = self.traced_gate(inject.split(':')[0], inject, helper, lambda: None, wait=0)
                self.assertEqual(rc, 3, out + err); self.assertIn(text, err); self.assertEqual(out, '')

    def test_file_growing_during_read_is_cut_at_the_limit_not_loaded_in_memory(self):
        """Taille 1 octet au fstat, puis 3 Gio (creux) pendant le retard de la 1re lecture : la lecture doit rester bornée (RLIMIT_AS 1 Gio : un ReadAll non borné meurt)."""
        self.write('big.bin', 'x'); big = os.path.join(self.rel, 'big.bin')
        files = [{'Path': n, 'Sha256': '0' * 64} for n in ('big.bin',)] + [{'Path': n, 'Sha256': self.digest(n)} for n in ('entry.sh', 'helper.sh')]
        self.sign_manifest({'Version': 1, 'Dir': self.rel, 'Files': files})
        rc, out, err, _ = self.traced_gate('openat,read', 'read:delay_enter=4s:when=1', big, lambda: os.truncate(big, 3 << 30), after_open='big.bin', wait=1.0, rlimit_as=1 << 30)
        self.assertEqual(rc, 3, f'rc={rc} (2 = mémoire épuisée / panique non bornée)\n{out}{err[-600:]}'); self.assertIn('dépasse', err); self.assertEqual(out, '')

    def test_oversized_regular_file_is_refused_without_reading_it(self):
        self.sparse('big.bin', (16 << 20) + 1)
        files = [{'Path': 'big.bin', 'Sha256': '0' * 64}] + [{'Path': n, 'Sha256': self.digest(n)} for n in ('entry.sh', 'helper.sh')]
        self.sign_manifest({'Version': 1, 'Dir': self.rel, 'Files': files})
        rc, out, err, log = self.traced_gate('openat,read', 'read:delay_enter=1ms', os.path.join(self.rel, 'big.bin'), lambda: None, wait=0)
        self.assertEqual(rc, 3, out + err); self.assertIn('dépasse', err); self.assertIn('big.bin', log, 'le fichier doit avoir été ouvert')
        self.assertNotRegex(log, r'\bread\(', 'un fichier trop gros selon fstat ne doit pas être lu')

    def test_fifo_without_writer_is_refused_promptly_instead_of_blocking(self):
        """Assertion déterministe (pas un délai de sous-processus) : O_NONBLOCK doit empêcher le blocage de open() sur un tube sans écrivain."""
        self.addCleanup(lambda: os.path.lexists(self.pub) and os.remove(self.pub))                                  # la clé est partagée : la remettre en fichier avant le setUp suivant
        for label, attr in (('manifeste', 'manifest'), ('signature', 'sig'), ('clé publique de confiance', 'pub')):
            with self.subTest(label):
                self.tearDown(); self.setUp(); path = getattr(self, attr); os.remove(path); os.mkfifo(path, 0o644)
                t0 = time.time()
                p = subprocess.Popen([self.bin, self.manifest, self.sig, self.snap, '--', 'entry.sh'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.td)
                try: out, err = p.communicate(timeout=10)
                except subprocess.TimeoutExpired: p.kill(); p.communicate(); self.fail(f'{label} : le vérificateur est resté bloqué sur open() du tube (O_NONBLOCK absent ?)')
                self.assertLess(time.time() - t0, 5); self.assertEqual(p.returncode, 3, out + err); self.assertIn('fichier régulier', err); self.assertIn(path, err)

    def test_limits_are_inclusive_at_the_exact_boundary(self):
        """Exactement à la limite : accepté (16 Mio un fichier, 1 Mio le manifeste, 4 Kio la signature -> refus de signature, pas de 'dépasse')."""
        self.sparse('exact.bin', 16 << 20)
        h = hashlib.sha256(); h.update(bytes(1 << 20) * 16)
        files = [{'Path': 'exact.bin', 'Sha256': h.hexdigest()}] + [{'Path': n, 'Sha256': self.digest(n)} for n in ('entry.sh', 'helper.sh')]
        self.sign_manifest({'Version': 1, 'Dir': self.rel, 'Files': files})
        r = self.gate(); self.assertEqual(r.returncode, 0, r.stderr)
        m = json.dumps({'Version': 1, 'Dir': self.rel, 'Files': files[1:]}, sort_keys=True)
        self.sign_raw(m + ' ' * ((1 << 20) - len(m)))                                                                # manifeste d'exactement 1 Mio (espaces finaux)
        r = self.gate(); self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.sig, 'ab') as f: f.write(b'\0' * ((4 << 10) - os.path.getsize(self.sig)))                    # signature d'exactement 4 Kio : refusée pour la signature
        r = self.gate(); self.refused(r, 'signature'); self.assertNotIn('dépasse', r.stderr)

    def test_cumulative_limit_is_inclusive_at_exactly_64_mib_and_refused_one_byte_beyond(self):
        small = sum(os.path.getsize(os.path.join(self.rel, n)) for n in ('entry.sh', 'helper.sh'))
        sizes = [16 << 20, 16 << 20, 16 << 20, (16 << 20) - small]                                                    # total exact = 64 Mio avec entry.sh et helper.sh
        def release(sizes):
            for n in os.listdir(self.rel):
                if n.startswith('part'): os.remove(os.path.join(self.rel, n))
            for i, s in enumerate(sizes): self.sparse(f'part{i}.bin', s)
            self.sign()
        release(sizes); r = self.gate(); self.assertEqual(r.returncode, 0, r.stderr)
        release(sizes[:3] + [sizes[3] + 1]); self.refused(self.gate(), 'dépasse')

    def test_manifest_larger_than_limit_but_reported_empty_by_fstat_is_cut(self):
        """Fichier régulier dont st_size vaut 0 mais dont le contenu dépasse la limite (/proc) : la borne de lecture, pas fstat, doit refuser."""
        p = '/proc/kallsyms'
        try: ok = os.stat(p).st_size == 0 and len(open(p, 'rb').read(1 << 21)) > (1 << 20)
        except OSError: ok = False
        if not ok: self.skipTest('/proc/kallsyms indisponible ou trop petit')
        r = subprocess.run([self.bin, p, self.sig, self.snap, '--', 'entry.sh'], capture_output=True, text=True, cwd=self.td)
        self.refused(r, 'dépasse')

    # ---- A3 : clés JSON dupliquées ou de casse différente, refusées avant le décodage structuré ---------------------------------------------------
    def test_duplicate_or_case_variant_json_keys_are_refused(self):
        e, h, d = self.digest('entry.sh'), self.digest('helper.sh'), json.dumps(self.rel)
        files = f'[{{"Path": "entry.sh", "Sha256": "{e}"}}, {{"Path": "helper.sh", "Sha256": "{h}"}}]'
        self.sign_raw(f'{{"Version": 1, "Dir": {d}, "Files": {files}}}'); self.assertEqual(self.gate().returncode, 0)  # témoin : le JSON brut est accepté
        other = json.dumps(os.path.join(self.td, 'ailleurs'))
        cases = {
            'Dir dupliqué (le dernier gagnerait)': (f'{{"Version": 1, "Dir": {d}, "Dir": {other}, "Files": {files}}}', 'dupliquée'),
            'Version dupliquée': (f'{{"Version": 2, "Version": 1, "Dir": {d}, "Files": {files}}}', 'dupliquée'),
            'dir en minuscules en plus de Dir': (f'{{"Version": 1, "Dir": {d}, "dir": {other}, "Files": {files}}}', 'casse différente'),
            'clé seule de casse différente': (f'{{"version": 1, "Dir": {d}, "Files": {files}}}', 'casse différente'),
            'repli Unicode (ſ long) dans un fichier': (f'{{"Version": 1, "Dir": {d}, "Files": [{{"Path": "entry.sh", "Sha256": "{e}", "ſha256": "{"0" * 64}"}}]}}', 'casse différente'),
            'Path dupliqué dans un fichier': (f'{{"Version": 1, "Dir": {d}, "Files": [{{"Path": "helper.sh", "Path": "entry.sh", "Sha256": "{e}"}}]}}', 'dupliquée'),
            'doublon masqué par un échappement': (f'{{"Version": 1, "Dir": {d}, "\\u0044ir": {other}, "Files": {files}}}', 'dupliquée'),
            'objet imbriqué inattendu': (f'{{"Version": 1, "Dir": {d}, "Files": [{{"Path": {{"x": 1}}, "Sha256": "{e}"}}]}}', 'objet inattendu'),
        }
        for label, (text, msg) in cases.items():
            with self.subTest(label):
                self.sign_raw(text); r = self.gate(); self.refused(r, msg); self.assertIn('manifeste', r.stderr)
        self.assertEqual(len(os.listdir(self.snap)), 1, 'seul le témoin a créé un instantané')

    # ---- A2 : état de processus reconstruit avant exec ---------------------------------------------------------------------------------------------
    def test_exec_runs_from_snapshot_with_fixed_umask_no_inherited_fds_and_default_signals(self):
        self.write('probe.sh', PROBE)
        shutil.copy(self.sigstate, os.path.join(self.rel, 'sigstate')); os.chmod(os.path.join(self.rel, 'sigstate'), 0o755)  # signé et copié dans l'instantané
        self.sign()
        leak = os.open(os.path.join(self.td, 'secret'), os.O_RDWR | os.O_CREAT, 0o600); high = os.dup2(leak, 200)
        try:
            def hostile():
                os.umask(0)
                for s in HOSTILE_SIGNALS: signal.signal(s, signal.SIG_IGN)
                signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR2, signal.SIGTERM})
            control = subprocess.run(['/bin/bash', os.path.join(self.rel, 'probe.sh'), str(leak), str(high)], capture_output=True, text=True,
                                     pass_fds=(leak, high), preexec_fn=hostile, cwd=self.td)                     # témoin : sans le vérificateur tout est hérité
            self.assertIn(f'fd{leak}=open', control.stdout); self.assertIn('fd200=open', control.stdout); self.assertIn('umask=0000', control.stdout)
            r = self.gate(entry='probe.sh', args=[str(leak), str(high)], pass_fds=(leak, high), preexec_fn=hostile)
        finally:
            os.close(leak); os.close(high)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn('PROBE-STDERR', r.stderr)
        out = dict(line.split('=', 1) for line in r.stdout.splitlines() if '=' in line)
        self.assertTrue(out['cwd'].startswith(os.path.join(self.snap, 'snap-')), out['cwd'])
        self.assertEqual(os.path.dirname(out['cwd']), self.snap)
        self.assertEqual(out['umask'], '0077')
        self.assertEqual(out[f'fd{leak}'], 'closed'); self.assertEqual(out['fd200'], 'closed')
        lines = {l.split(':')[0]: sigmask(l) for l in r.stdout.splitlines() if l.startswith('Sig')}
        ctl = {l.split(':')[0]: sigmask(l) for l in control.stdout.splitlines() if l.startswith('Sig')}
        for state in (lines, ctl): self.assertEqual(set(state), {'SigIgn', 'SigBlk'}, r.stdout + control.stdout)    # mesuré par sigstate, pas par bash
        for s in HOSTILE_SIGNALS:
            bit = 1 << (s - 1)
            self.assertTrue(ctl['SigIgn'] & bit, f'témoin : {s!r} devrait être ignoré sans le vérificateur')
            self.assertFalse(lines['SigIgn'] & bit, f'{s!r} reste ignoré après le vérificateur (bash lui-même : SigIgn={out["bash-SigIgn"]})')
        for s in (signal.SIGUSR2, signal.SIGTERM):
            self.assertTrue(ctl['SigBlk'] & (1 << (s - 1)), f'témoin : {s!r} devrait être bloqué')
            self.assertFalse(lines['SigBlk'] & (1 << (s - 1)), f'{s!r} reste bloqué après le vérificateur')

    def test_stdout_and_stderr_still_reach_the_caller(self):
        r = self.gate(); self.assertEqual(r.returncode, 0, r.stderr); self.assertIn('ENTRY-OK', r.stdout)
        self.write('err.sh', '#!/bin/bash\necho vers-stderr >&2\nexit 7\n'); self.sign()
        r = self.gate(entry='err.sh'); self.assertEqual(r.returncode, 7); self.assertEqual(r.stderr, 'vers-stderr\n')

    # ---- TOCTOU --------------------------------------------------------------------------------------------------------------------------------
    def test_replacing_the_source_while_the_script_runs_has_no_effect(self):
        """Le script lit helper.sh APRÈS une pause ; pendant la pause un racer (root) remplace la SOURCE. L'instantané, lui, est celui qui a été vérifié."""
        marker = os.path.join(self.td, 'PWNED')
        p = subprocess.Popen([self.bin, self.manifest, self.sig, self.snap, '--', 'entry.sh', '1.5'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env=dict(os.environ), cwd=self.td)
        time.sleep(0.6); open(os.path.join(self.rel, 'helper.sh'), 'w').write(f'helper_loaded=PIRATE; touch "{marker}"\n')
        out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, err); self.assertIn('helper=1', out); self.assertFalse(os.path.exists(marker))


if __name__ == '__main__':
    unittest.main()
