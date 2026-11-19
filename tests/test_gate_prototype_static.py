"""rc25 — garde-fous STATIQUES du prototype de vérificateur (conception/rc25-gate-prototype), exécutables sans go, openssl, gcc ni root.

tests/test_gate_prototype.py prouve le comportement mais est entièrement ignoré là où la chaîne Go manque. Ces tests lisent seulement
main.go / go.mod / README.md (commentaires retirés) et refusent toute régression structurelle des invariants de confiance et de contexte
d'exécution : clé de confiance figée à la construction, aucune entrée tirée de l'environnement, lectures bornées et sans suivi de lien,
signature vérifiée avant décodage, environnement et signaux réinitialisés juste avant l'exec. Ils ne remplacent pas les tests dynamiques.
"""
import os, re, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, 'conception', 'rc25-gate-prototype')


def strip_go_comments(src):
    """Retire commentaires // et /* */ en respectant chaînes "…", `…` et runes '…' (un « // » dans une chaîne n'est pas un commentaire)."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith('//', i):
            j = src.find('\n', i); i = n if j < 0 else j
        elif src.startswith('/*', i):
            j = src.find('*/', i + 2); i = n if j < 0 else j + 2; out.append(' ')
        elif c in '"\'':
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == '\\' else 1
            out.append(src[i:j + 1]); i = j + 1
        elif c == '`':
            j = src.find('`', i + 1); j = n - 1 if j < 0 else j
            out.append(src[i:j + 1]); i = j + 1
        else:
            out.append(c); i += 1
    return ''.join(out)


def func_body(code, name):
    """Corps (accolades comprises) de `func name(` ; les accolades des chaînes sont rares ici et absentes des fonctions visées."""
    m = re.search(r'^func ' + re.escape(name) + r'\(', code, re.M)
    if not m: raise AssertionError('fonction %s introuvable' % name)
    i = code.index('{', m.end()); depth = 0
    for j in range(i, len(code)):
        depth += {'{': 1, '}': -1}.get(code[j], 0)
        if depth == 0: return code[i:j + 1]
    raise AssertionError('accolades non équilibrées dans %s' % name)


def top_level_args(code, start):
    """Arguments de l'appel dont la parenthèse ouvrante est à `start`, découpés aux virgules de premier niveau."""
    depth, args, cur = 0, [], ''
    for ch in code[start:]:
        if ch in '([{':
            depth += 1
            if depth == 1: continue
        elif ch in ')]}':
            depth -= 1
            if depth == 0: args.append(cur.strip()); return [a for a in args if a]
        elif ch == ',' and depth == 1:
            args.append(cur.strip()); cur = ''; continue
        cur += ch
    raise AssertionError('appel non terminé')


class GatePrototypeStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(SRC, 'main.go'), encoding='utf-8') as f: cls.raw = f.read()
        cls.code = strip_go_comments(cls.raw)
        cls.main = func_body(cls.code, 'main')
        m = re.search(r'^import \(\n(.*?)^\)', cls.code, re.M | re.S)
        cls.imports = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()

    def test_comment_stripper_keeps_strings_and_drops_comments(self):
        s = strip_go_comments('a := "x//y" // os.Getenv\nb := `/*z*/` /* os.Environ() */ c := \'"\'')
        self.assertIn('"x//y"', s); self.assertIn('`/*z*/`', s); self.assertNotIn('Getenv', s); self.assertNotIn('Environ', s); self.assertIn('\'"\'', s)

    # ---- confiance : la clé publique est figée à la construction, rien n'est tiré de l'appelant hors argv -----------------------------------
    def test_trusted_key_path_is_a_link_time_string_assigned_nowhere_else(self):
        self.assertRegex(self.code, r'(?m)^var trustedKeyPath = "/[^"]+"$', '-ldflags -X exige une variable string de paquet initialisée par une constante')
        self.assertEqual(len(re.findall(r'\btrustedKeyPath\s*(?::?=|\+=)', self.code)), 1, 'trustedKeyPath ne doit être affecté qu\'à sa déclaration')
        self.assertIn('-X main.trustedKeyPath=', self.raw, 'la commande de construction documentée doit figer la clé')

    def test_no_input_is_taken_from_the_environment_flags_or_path_lookup(self):
        for bad in ('os.Getenv', 'os.LookupEnv', 'os.Environ', 'syscall.Getenv', 'syscall.Environ', 'exec.LookPath', 'os.Executable'):
            self.assertNotIn(bad, self.code)
        for pkg in ('flag', 'os/exec', 'net', 'net/http', 'plugin', 'os/user'):
            self.assertNotIn(pkg, self.imports)

    def test_go_module_has_no_third_party_dependency(self):
        with open(os.path.join(SRC, 'go.mod'), encoding='utf-8') as f: mod = f.read()
        self.assertNotRegex(mod, r'(?m)^\s*(require|replace)\b', 'le vérificateur ne doit dépendre que de la bibliothèque standard')
        self.assertFalse(os.path.exists(os.path.join(SRC, 'vendor')))
        self.assertTrue(all(i.split('/')[0].find('.') < 0 for i in self.imports), self.imports)

    # ---- chemins et lectures : chaîne de confiance, sans lien, bornées --------------------------------------------------------------------
    def test_every_open_refuses_symlinks_and_inherited_descriptors(self):
        opens = [m.start() for m in re.finditer(r'\bsyscall\.Open\(', self.code)]
        self.assertTrue(opens)
        for p in opens:
            flags = top_level_args(self.code, self.code.index('(', p))[1]
            self.assertIn('O_NOFOLLOW', flags); self.assertIn('O_CLOEXEC', flags); self.assertNotRegex(flags, r'O_(WRONLY|RDWR|CREAT|TRUNC)')
        for bad in ('os.Open(', 'os.OpenFile(', 'os.ReadFile(', 'ioutil.ReadFile('):
            self.assertNotIn(bad, self.code, 'toute lecture passe par readAll (chaîne de confiance + bornes)')

    def test_read_all_checks_chain_then_descriptor_and_every_call_is_bounded(self):
        body = func_body(self.code, 'readAll')
        order = [body.find(t) for t in ('chain(path)', 'syscall.Open(', 'syscall.Fstat(', 'S_IFREG', 'pre.Ino', 'st.Uid', '0o022', 'io.LimitReader(f, max+1)')]
        self.assertNotIn(-1, order, order); self.assertEqual(order, sorted(order), 'ordre chain → open → fstat → contrôles → lecture bornée')
        calls = [m.start() for m in re.finditer(r'\breadAll\(', self.code) if not self.code[max(0, m.start() - 5):m.start()].endswith('func ')]
        self.assertGreaterEqual(len(calls), 4)
        for p in calls:
            args = top_level_args(self.code, self.code.index('(', p))
            self.assertEqual(len(args), 2, args); self.assertRegex(args[1], r'max(KeySig|Manifest|File|Total)', 'borne explicite attendue : ' + args[1])

    def test_snapshot_root_and_manifest_paths_are_validated_before_use(self):
        m = self.main
        for before, after in (('decodeManifest(mb)', 'relPath(entry)'), ('relPath(entry)', 'chain(root)'), ('chain(root)', 'os.MkdirTemp(root')):
            self.assertLess(m.index(before), m.index(after), '%s doit précéder %s' % (before, after))
        dm = func_body(self.code, 'decodeManifest')
        for t in ('strictKeys(', 'DisallowUnknownFields()', 'absPath(m.Dir)', 'relPath(f.Path)', 'seen[f.Path]', 'sha256.Size'):
            self.assertIn(t, dm)

    # ---- signature : vérifiée sur les octets bruts, avant tout décodage -----------------------------------------------------------------
    def test_signature_is_verified_on_raw_bytes_before_decoding(self):
        m = self.main
        self.assertRegex(m, r'ed25519\.Verify\(ed25519\.PublicKey\(key\), mb, sig\)')
        self.assertLess(m.index('ed25519.PublicKeySize'), m.index('ed25519.Verify('))
        self.assertLess(m.index('ed25519.Verify('), m.index('decodeManifest(mb)'))
        self.assertEqual(self.code.count('decodeManifest('), 2, 'une définition, un seul appel (après vérification)')
        self.assertEqual(self.code.count('json.Unmarshal'), 0)

    # ---- contexte d'exécution : umask, environnement fixe, signaux et descripteurs juste avant l'exec -------------------------------------
    def test_umask_is_fixed_before_any_file_is_read_or_created(self):
        m = self.main
        self.assertIn('syscall.Umask(0o077)', m)
        self.assertLess(m.index('syscall.Umask(0o077)'), min(m.index('readAll('), m.index('os.MkdirTemp(')))

    def test_exec_uses_absolute_interpreter_privileged_mode_and_a_literal_environment(self):
        m = self.main
        self.assertEqual(self.code.count('syscall.Exec('), 1)
        args = top_level_args(m, m.index('(', m.index('syscall.Exec(')))
        self.assertEqual(args, ['"/bin/bash"', 'argv', 'env'])
        env = re.search(r'\benv := \[\]string\{([^}]*)\}', m)
        self.assertTrue(env, 'environnement construit littéralement')
        items = [x.strip() for x in env.group(1).split(',') if x.strip()]
        self.assertTrue(items and all(re.fullmatch(r'"[A-Z_]+=[^"$]*"', x) for x in items), items)
        names = [x.strip('"').split('=')[0] for x in items]
        self.assertEqual(len(names), len(set(names)))
        for bad in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'BASH_ENV', 'ENV', 'IFS', 'SHELLOPTS', 'BASHOPTS', 'PS4'): self.assertNotIn(bad, names)
        self.assertRegex(dict(x.strip('"').split('=', 1) for x in items)['PATH'], r'^(/[a-z/]+)(:/[a-z/]+)*$')
        self.assertEqual(len(re.findall(r'\benv\s*(?:=|\+=|= append)', m)), 0, 'env ne doit pas être complété après sa construction')
        self.assertRegex(m, r'argv := append\(\[\]string\{"/bin/bash", "-p", filepath\.Join\(snap, ')

    def test_signals_and_descriptors_are_reset_on_the_locked_thread_right_before_exec(self):
        m = self.main
        idx = [m.index(t) for t in ('os.Chdir(snap)', 'runtime.LockOSThread()', 'resetSignals()', 'cloexecInherited()', 'syscall.Exec(')]
        self.assertEqual(idx, sorted(idx))
        between = m[idx[1]:idx[4]]
        self.assertNotRegex(between, r'\bgo\s+\w|UnlockOSThread', 'aucune goroutine ni déverrouillage entre le reset des signaux et l\'exec')
        rs = func_body(self.code, 'resetSignals')
        self.assertIn('SYS_RT_SIGACTION', rs); self.assertIn('SYS_RT_SIGPROCMASK', rs); self.assertRegex(rs, r's <= 64')

    def test_refusals_exit_with_a_dedicated_status(self):
        self.assertRegex(self.code, r'func die\(f string, a \.\.\.any\) \{ fmt\.Fprintf\(os\.Stderr, "REFUS: "\+f\+"\\n", a\.\.\.\); os\.Exit\(3\) \}')
        self.assertEqual(len(re.findall(r'\bos\.Exit\(', self.code)), 1, 'seul die() termine le processus (code 3 = refus)')
        self.assertNotIn('panic(', self.code); self.assertNotIn('recover(', self.code)


if __name__ == '__main__':
    unittest.main()
