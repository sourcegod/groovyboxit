#!/usr/bin/env bash
# Tests en trois niveaux (Phase 8 étape 17b1, docs/DESIGN.md § Phase 8 étape 17a T5).
#
#   tools/tests.sh basique [fichiers ou motifs pytest…]
#       les tests liés à la modification ; sans argument : les derniers en échec
#       (--lf), sinon rien.  À chaque petite modification.
#   tools/tests.sh intermediaire [options pytest…]
#       toute la suite sauf les marques slow, audio et gui.  À chaque étape.
#   tools/tests.sh avance [options pytest…]
#       toute la suite, avec le garde-fou des tests lents non marqués.
#       Avant chaque commit et à chaque clôture.
#
# Raccourcis : b, i, a.  Les options supplémentaires sont passées à pytest
# (par exemple -x pour s'arrêter au premier échec).
# Intermédiaire et Avancé tournent en parallèle sur tous les cœurs
# (pytest-xdist, Phase 8 étape 17c1) ; TESTS_SERIE=1 force la série ; sans
# pytest-xdist installé, la série est prise d'office.
set -u
cd "$(dirname "$0")/.." || exit 2

usage() {
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
}

# options du parallèle : vide en série
parallele=()
if [ "${TESTS_SERIE:-0}" != "1" ] && python3 -c "import xdist" 2>/dev/null; then
    parallele=(-n auto --dist worksteal)
fi

niveau="${1:-}"
[ $# -gt 0 ] && shift

case "$niveau" in
    basique|b)
        if [ $# -gt 0 ]; then
            exec python3 -m pytest -q "$@"
        fi
        # derniers échecs qui existent encore (le cache de pytest garde aussi
        # ceux de tests renommés ou supprimés : --lf relancerait alors tout)
        mapfile -t echecs < <(python3 - <<'PY'
import json, subprocess, sys
try:
    failed = json.load(open(".pytest_cache/v/cache/lastfailed"))
except (OSError, ValueError):
    failed = {}
if failed:
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q",
                          "-p", "no:cacheprovider"], capture_output=True, text=True).stdout
    known = {l.strip() for l in out.splitlines() if "::" in l}
    for nid in failed:
        if nid in known:
            print(nid)
PY
)
        if [ ${#echecs[@]} -eq 0 ]; then
            echo "Aucun test en échec à relancer : donner des fichiers de tests,"
            echo "par exemple  tools/tests.sh basique tests/test_song.py"
            exit 0
        fi
        exec python3 -m pytest -q "${echecs[@]}"
        ;;
    intermediaire|intermédiaire|i)
        exec python3 -m pytest -q "${parallele[@]}" -m "not slow and not audio and not gui" "$@"
        ;;
    avance|avancé|a)
        exec python3 -m pytest -q "${parallele[@]}" --slow-guard "$@"
        ;;
    *)
        usage
        exit 2
        ;;
esac
