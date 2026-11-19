// PROTOTYPE DE FAISABILITÉ — NE FAIT PARTIE D'AUCUNE PROCÉDURE, n'est appelé par aucun script, n'est installé nulle part.
// Vérificateur statique indépendant : signature Ed25519 du manifeste, chaîne de confiance, empreintes des octets copiés,
// instantané privé exécuté, environnement reconstruit. Prototype uniquement : anti-retour arrière, verrouillage et journalisation
// de production ne sont pas implémentés.
// Construire : CGO_ENABLED=0 go build -trimpath -ldflags "-X main.trustedKeyPath=/chemin/absolu/cle.raw" -o tb-gate-proto .
// usage: gate-proto <manifest.json> <manifest.sig> <snapshot-root> -- <entry> [args...]
// Linux amd64/arm64 uniquement (numéros d'appels système et constantes de signaux codés en dur ci-dessous).
package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"unsafe"
)

// trustedKeyPath est la seule clé publique acceptée. Fixée à l'édition de liens (-ldflags -X), jamais lue depuis les arguments
// ni l'environnement : l'appelant ne peut pas fournir sa propre clé avec un manifeste qu'il aurait signé lui-même.
var trustedKeyPath = "/etc/tb-gate/manifest-ed25519.pub"

type File struct {
	Path   string
	Sha256 string
}
type Manifest struct {
	Version int
	Dir     string
	Files   []File
}

func die(f string, a ...any) { fmt.Fprintf(os.Stderr, "REFUS: "+f+"\n", a...); os.Exit(3) }

// relPath accepte uniquement des chemins relatifs canoniques, sans composant vide, "." ou "..".
// Le prototype tourne sous Linux : les antislashs sont refusés pour éviter les chemins ambigus.
func relPath(p string) bool {
	if p == "" || strings.IndexByte(p, 0) >= 0 || strings.ContainsRune(p, '\\') || filepath.IsAbs(p) || filepath.Clean(p) != p {
		return false
	}
	for _, c := range strings.Split(p, "/") {
		if c == "" || c == "." || c == ".." {
			return false
		}
	}
	return true
}

func absPath(p string) bool {
	return strings.IndexByte(p, 0) < 0 && filepath.IsAbs(p) && filepath.Clean(p) == p
}

// chaîne de confiance : chaque composant, de / au fichier, est root, non lien symbolique,
// non modifiable par groupe/autres (sticky toléré pour les ANCÊTRES). Retourne le lstat du dernier composant, pour que l'appelant
// puisse le comparer au descripteur qu'il ouvre ensuite.
func chain(p string) syscall.Stat_t {
	if !absPath(p) {
		die("chemin absolu non canonique %s", p)
	}
	cur := "/"
	parts := strings.Split(strings.Trim(p, "/"), "/")
	var final syscall.Stat_t
	check := func(path string, last bool) {
		var st syscall.Stat_t
		if err := syscall.Lstat(path, &st); err != nil {
			die("lstat %s: %v", path, err)
		}
		if st.Mode&syscall.S_IFMT == syscall.S_IFLNK {
			die("%s est un lien symbolique", path)
		}
		if st.Uid != 0 {
			die("%s n'appartient pas à root", path)
		}
		if st.Mode&0o022 != 0 && !(st.Mode&syscall.S_ISVTX != 0 && !last) {
			die("%s modifiable par groupe/autres", path)
		}
		final = st
	}
	check(cur, false)
	for i, c := range parts {
		cur = filepath.Join(cur, c)
		check(cur, i == len(parts)-1)
	}
	return final
}

// Bornes de lecture : une entrée du manifeste ne peut pas faire lire un volume arbitraire (fichier énorme, périphérique infini).
const (
	maxKeySig   = 4 << 10  // clé publique (32 octets) et signature (64 octets)
	maxManifest = 1 << 20  // manifeste signé
	maxFile     = 16 << 20 // un fichier de la procédure
	maxTotal    = 64 << 20 // somme des fichiers copiés dans l'instantané
)

// readAll lit au plus max octets d'un fichier régulier. O_NONBLOCK évite qu'un tube nommé bloque l'ouverture (sans effet sur un fichier
// régulier). Le fichier ouvert est ensuite contrôlé par fstat, sur le descripteur et non sur le chemin : type régulier, même
// périphérique/inode que le lstat de chain() (un fichier échangé entre le contrôle et l'ouverture est refusé), propriétaire root et
// non modifiable par groupe/autres ; puis la lecture est bornée même si le fichier grossit. Tout écart = refus.
// Limite résiduelle : chain() valide les ANCÊTRES par chemin (lstat), pas par descripteur (pas de openat composant par composant) et
// O_NOFOLLOW ne couvre que le dernier composant. Un ancêtre échangé entre chain() et open() n'est pas détecté en soi : seul le
// fichier finalement ouvert est contrôlé (identité, propriétaire, mode). Les ancêtres étant tous à root et non modifiables par
// groupe/autres (sticky : seul root peut renommer ses entrées), cet échange exige d'être root ; les fichiers de la procédure sont en outre épinglés par leur SHA-256, mais pas la clé
// publique, la signature ni le manifeste (ce dernier est authentifié par la signature, donc par la clé de confiance).
func readAll(path string, max int64) []byte {
	pre := chain(path)
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC|syscall.O_NONBLOCK, 0)
	if err != nil {
		die("open %s: %v", path, err)
	}
	f := os.NewFile(uintptr(fd), path)
	defer f.Close()
	var st syscall.Stat_t
	if err := syscall.Fstat(fd, &st); err != nil {
		die("fstat %s: %v", path, err)
	}
	if st.Mode&syscall.S_IFMT != syscall.S_IFREG {
		die("%s n'est pas un fichier régulier", path)
	}
	if st.Dev != pre.Dev || st.Ino != pre.Ino {
		die("%s a changé entre le contrôle et l'ouverture", path)
	}
	if st.Uid != 0 {
		die("%s n'appartient pas à root (descripteur ouvert)", path)
	}
	if st.Mode&0o022 != 0 {
		die("%s modifiable par groupe/autres (descripteur ouvert)", path)
	}
	if st.Size > max {
		die("%s dépasse %d octets", path, max)
	}
	b, err := io.ReadAll(io.LimitReader(f, max+1))
	if err != nil {
		die("lecture %s: %v", path, err)
	}
	if int64(len(b)) > max {
		die("%s dépasse %d octets", path, max)
	}
	return b
}

// manifestKeys liste, par contexte (clé parente ; "" pour la racine), les seules clés admises dans un objet.
// Un objet rencontré dans un autre contexte est refusé.
var manifestKeys = map[string][]string{
	"":      {"Version", "Dir", "Files"},
	"Files": {"Path", "Sha256"},
}

// strictKeys parcourt le manifeste jeton par jeton AVANT tout décodage structuré : encoding/json associe les clés aux champs
// sans tenir compte de la casse (repli Unicode compris, ex. « ſha256 » pour « Sha256 ») et retient la dernière occurrence
// d'une clé répétée. Chaque clé doit donc être exactement l'une des clés attendues et n'apparaître qu'une fois par objet.
func strictKeys(d *json.Decoder, ctx string) error {
	t, err := d.Token()
	if err != nil {
		return err
	}
	switch t {
	case json.Delim('{'):
		allowed, ok := manifestKeys[ctx]
		if !ok {
			return fmt.Errorf("objet inattendu sous %q", ctx)
		}
		seen := map[string]bool{}
		for d.More() {
			kt, err := d.Token()
			if err != nil {
				return err
			}
			k := kt.(string)
			exact, folded := false, false
			for _, a := range allowed {
				exact = exact || k == a
				folded = folded || strings.EqualFold(k, a)
			}
			switch {
			case !exact && folded:
				return fmt.Errorf("clé de casse différente: %q", k)
			case !exact:
				return fmt.Errorf("clé inattendue: %q", k)
			case seen[k]:
				return fmt.Errorf("clé dupliquée: %q", k)
			}
			seen[k] = true
			if err := strictKeys(d, k); err != nil {
				return err
			}
		}
		_, err = d.Token()
		return err
	case json.Delim('['):
		for d.More() {
			if err := strictKeys(d, ctx); err != nil {
				return err
			}
		}
		_, err = d.Token()
		return err
	}
	return nil
}

func decodeManifest(b []byte) Manifest {
	ks := json.NewDecoder(bytes.NewReader(b))
	if err := strictKeys(ks, ""); err != nil {
		die("manifeste: %v", err)
	}
	if _, err := ks.Token(); err != io.EOF {
		die("contenu supplémentaire dans le manifeste")
	}
	var m Manifest
	d := json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	if err := d.Decode(&m); err != nil {
		die("manifeste: %v", err)
	}
	var extra any
	if err := d.Decode(&extra); err != io.EOF {
		die("contenu supplémentaire dans le manifeste")
	}
	if m.Version != 1 {
		die("version de manifeste non prise en charge: %d", m.Version)
	}
	if !absPath(m.Dir) {
		die("Dir doit être un chemin absolu canonique")
	}
	if len(m.Files) == 0 {
		die("manifeste sans fichiers")
	}
	seen := make(map[string]bool, len(m.Files))
	for _, f := range m.Files {
		if !relPath(f.Path) {
			die("chemin de fichier non canonique: %q", f.Path)
		}
		if seen[f.Path] {
			die("chemin dupliqué dans le manifeste: %s", f.Path)
		}
		seen[f.Path] = true
		h, err := hex.DecodeString(f.Sha256)
		if err != nil || len(h) != sha256.Size || strings.ToLower(f.Sha256) != f.Sha256 {
			die("SHA-256 invalide pour %s", f.Path)
		}
	}
	return m
}

// resetSignals remet chaque signal à SIG_DFL et vide le masque du fil courant : un appelant qui ignore ou bloque
// SIGTERM, SIGHUP, SIGALRM… ne transmet pas cet état à la procédure (dispositions ignorées et masque survivent à execve).
// Une struct sigaction noyau entièrement nulle vaut SIG_DFL sans drapeau ni masque. À appeler juste avant l'exec, fil verrouillé.
func resetSignals() {
	var act [4]uint64
	for s := 1; s <= 64; s++ {
		if s == int(syscall.SIGKILL) || s == int(syscall.SIGSTOP) {
			continue
		}
		if _, _, e := syscall.RawSyscall6(syscall.SYS_RT_SIGACTION, uintptr(s), uintptr(unsafe.Pointer(&act)), 0, 8, 0, 0); e != 0 {
			die("réinitialisation du signal %d: %v", s, e)
		}
	}
	const sigSetmask = 2
	var empty uint64
	if _, _, e := syscall.RawSyscall6(syscall.SYS_RT_SIGPROCMASK, sigSetmask, uintptr(unsafe.Pointer(&empty)), 0, 8, 0, 0); e != 0 {
		die("réinitialisation du masque de signaux: %v", e)
	}
}

// cloexecInherited marque FD_CLOEXEC tous les descripteurs au-delà de 2 : ceux hérités de l'appelant ne franchissent pas
// l'exec, ceux du runtime Go restent valides jusqu'à l'exec ; stdin/stdout/stderr sont conservés tels quels.
// close_range(CLOSE_RANGE_CLOEXEC) (Linux >= 5.11), sinon parcours de /proc/self/fd ; échec = refus.
func cloexecInherited() {
	const sysCloseRange, closeRangeCloexec = 436, 4
	if _, _, e := syscall.RawSyscall(sysCloseRange, 3, uintptr(^uint32(0)), closeRangeCloexec); e == 0 {
		return
	}
	ents, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		die("descripteurs hérités: %v", err)
	}
	for _, e := range ents {
		var fd int
		if _, err := fmt.Sscanf(e.Name(), "%d", &fd); err != nil {
			die("descripteurs hérités: %q", e.Name())
		}
		if fd <= 2 {
			continue
		}
		if _, _, errno := syscall.RawSyscall(syscall.SYS_FCNTL, uintptr(fd), syscall.F_SETFD, syscall.FD_CLOEXEC); errno != 0 && errno != syscall.EBADF {
			die("descripteur hérité %d: %v", fd, errno)
		}
	}
}

func main() {
	if runtime.GOOS != "linux" || (runtime.GOARCH != "amd64" && runtime.GOARCH != "arm64") {
		die("plateforme non prise en charge: %s/%s", runtime.GOOS, runtime.GOARCH)
	}
	// umask fixe dès le début : ni l'instantané ni les fichiers créés par la procédure ne dépendent de celui de l'appelant.
	syscall.Umask(0o077)
	if !absPath(trustedKeyPath) {
		die("chemin de la clé publique de confiance invalide à la construction: %q", trustedKeyPath)
	}
	if len(os.Args) < 6 || os.Args[4] != "--" {
		die("usage")
	}
	mpath, spath, root, entry, args := os.Args[1], os.Args[2], os.Args[3], os.Args[5], os.Args[6:]
	mb, sig, key := readAll(mpath, maxManifest), readAll(spath, maxKeySig), readAll(trustedKeyPath, maxKeySig)
	if len(key) != ed25519.PublicKeySize {
		die("clé publique invalide")
	}
	if !ed25519.Verify(ed25519.PublicKey(key), mb, sig) {
		die("signature du manifeste invalide")
	}
	m := decodeManifest(mb)
	if !relPath(entry) {
		die("chemin d'entrée non canonique: %q", entry)
	}
	listed := false
	for _, f := range m.Files {
		if f.Path == entry {
			listed = true
			break
		}
	}
	if !listed {
		die("entrée absente du manifeste: %s", entry)
	}

	chain(root)
	snap, err := os.MkdirTemp(root, "snap-")
	if err != nil {
		die("snapshot: %v", err)
	}
	var total int64
	for _, f := range m.Files {
		b := readAll(filepath.Join(m.Dir, filepath.FromSlash(f.Path)), min(maxFile, maxTotal-total))
		total += int64(len(b))
		h := sha256.Sum256(b)
		if hex.EncodeToString(h[:]) != f.Sha256 {
			die("empreinte différente pour %s", f.Path)
		}
		dst := filepath.Join(snap, filepath.FromSlash(f.Path))
		if err := os.MkdirAll(filepath.Dir(dst), 0o700); err != nil {
			die("création du dossier snapshot pour %s: %v", f.Path, err)
		}
		if err := os.WriteFile(dst, b, 0o500); err != nil {
			die("copie: %v", err)
		}
	}
	// Les sous-répertoires doivent rester traversables par le processus mais non modifiables.
	var dirs []string
	if err := filepath.Walk(snap, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			dirs = append(dirs, p)
		}
		return nil
	}); err != nil {
		die("vérification du snapshot: %v", err)
	}
	for i := len(dirs) - 1; i >= 0; i-- {
		if err := os.Chmod(dirs[i], 0o500); err != nil {
			die("protection du snapshot: %v", err)
		}
	}
	if err := os.Chdir(snap); err != nil {
		die("chdir vers le snapshot: %v", err)
	}
	env := []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LANG=C.UTF-8", "HOME=/root", "TB_GATE=1"}
	argv := append([]string{"/bin/bash", "-p", filepath.Join(snap, filepath.FromSlash(entry))}, args...)
	// Le masque de signaux est propre au fil : resetSignals et execve doivent s'exécuter sur le même fil.
	runtime.LockOSThread()
	resetSignals()
	cloexecInherited()
	if err := syscall.Exec("/bin/bash", argv, env); err != nil {
		die("exec: %v", err)
	}
}
