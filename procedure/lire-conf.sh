# shellcheck shell=bash
# Lecture SÛRE d'un fichier de configuration (prod.conf, staging.conf…) : le fichier n'est JAMAIS exécuté (ni « source », ni « . »), il est lu comme des DONNÉES,
# validé ligne par ligne, et ses valeurs ne sont affectées qu'après validation de TOUT le fichier (tout ou rien). Fichier à « sourcer » : ne contient que des fonctions.
# Format accepté (celui de prod.conf / staging.conf) : lignes vides, commentaires (« # … »), et CLÉ=valeur où
#   - CLÉ fait partie de la liste fermée ci-dessous (toute autre clé — PATH, BASH_ENV, CONFIRM_PROD, LD_PRELOAD… — est refusée) et n'apparaît qu'une fois ;
#   - valeur = caractères  A-Z a-z 0-9 _ . / : @ % + , -  uniquement (ni espace, ni guillemet, ni $ ` ; & | ( ) < > * ? [ ] { } \ ni retour chariot) ; elle peut être vide.
# Aucun utilitaire externe n'est appelé ici : seulement des mots-clés et commandes internes de bash (un PATH piégé n'a donc aucune prise).
# Environnement : hors « bash -p », refus si l'environnement initial du processus (/proc/self/environ, lu sans aucune commande) porte une fonction exportée
# (BASH_FUNC_…) ou BASH_ENV. Seuls des mots-clés bash sont utilisés ici : une fonction masquant « builtin », « declare », « readlink »… ne peut pas fausser ce test.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
LIRE_CONF_KEYS=" ROOT PROJECT CONTAINER IMAGE URL BACKUP_BASE SOURCE_APP SOURCE_REQ RC_IMAGE COMPOSE_TEMPLATE "
lire_conf() { # $1 = fichier ; $2 = préfixe des variables créées (vide = ROOT, PROJECT…). Retour 0 = tout le fichier est valide et affecté ; 1 = refus (message sur stderr)
  local file=${1-} prefix=${2-} content line k v n=0 seen=" " keys=() vals=() i
  if [[ ! -f $file || ! -r $file ]]; then echo "ARRÊT : configuration illisible : ${file:-<vide>}" >&2; return 1; fi
  content=$(< "$file") || { echo "ARRÊT : configuration illisible : $file" >&2; return 1; }          # une seule lecture : ce qui est validé est exactement ce qui est affecté
  while IFS= read -r line || [[ -n $line ]]; do
    n=$((n + 1))
    [[ $line =~ ^[[:space:]]*(#.*)?$ ]] && continue
    if [[ $line =~ ^([A-Z][A-Z0-9_]*)=([A-Za-z0-9_./:@%+,-]*)$ ]]; then k=${BASH_REMATCH[1]}; v=${BASH_REMATCH[2]}
    else echo "ARRÊT : $file ligne $n refusée (format CLÉ=valeur attendu, valeur sans espace ni caractère spécial ; une configuration est lue comme des données, jamais exécutée)" >&2; return 1; fi
    if [[ $LIRE_CONF_KEYS != *" $k "* ]]; then echo "ARRÊT : $file ligne $n : clé « $k » inconnue (clés admises :$LIRE_CONF_KEYS)" >&2; return 1; fi
    if [[ $seen == *" $k "* ]]; then echo "ARRÊT : $file ligne $n : clé « $k » définie deux fois" >&2; return 1; fi
    seen+="$k "; keys+=("$k"); vals+=("$v")
  done <<<"$content"
  for k in $LIRE_CONF_KEYS; do unset -v "${prefix}${k}"; done                                           # rien n'est hérité de l'environnement
  for i in "${!keys[@]}"; do printf -v "${prefix}${keys[$i]}" '%s' "${vals[$i]}"; done
}
