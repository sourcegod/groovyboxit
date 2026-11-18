#!/usr/bin/env bash
# Tests en trois niveaux (Phase 8 étape 17b1, docs/DESIGN.md § Phase 8 étape 17a T5).
#
#   tools/tests.sh basique [fichiers ou motifs pytest…]
#       les tests liés à la modification ; sans argument : les derniers en échec
#       (--lf), sinon rien.  À chaque petite modification.
#   tools/tests.sh intermediaire [options pytest…]
#       toute la suite sauf les marques slow, audio et gui.  À chaque étape.
#   tools/tests.sh avance [options pytest…]
#       toute la suite, avec le garde-fou des tests lents non marqués, en deux
#       passages : A tout sauf audio, puis B les tests audio seuls.
#       Avant chaque commit et à chaque clôture.
#
# Raccourcis : b, i, a.  Les options supplémentaires sont passées à pytest
# (par exemple -x pour s'arrêter au premier échec).
# Intermédiaire et Avancé tournent en parallèle, un processus par cœur
# PHYSIQUE (pytest-xdist, Phase 8 étapes 17c1, 17d2) ; les tests audio (temps
# réel) ne sont jamais mêlés aux autres : ils échouaient au hasard quand les
# tests qui calculent prenaient la machine.  TESTS_SERIE=1 force la série ;
# sans pytest-xdist installé, la série est prise d'office.
set -u
cd "$(dirname "$0")/.." || exit 2

usage() {
    sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
}

# Cœurs physiques (les fils de l'hyperthreading partagent un cœur : 4 processus
# allaient aussi vite que 8, avec deux fois moins de travail, 17d2)
coeurs=$(python3 - <<'PY'
import os
try:
    ids = set()
    phys = core = None
    for line in open("/proc/cpuinfo"):
        key, _, val = line.partition(":")
        key = key.strip()
        if key == "physical id":
            phys = val.strip()
        elif key == "core id":
            core = val.strip()
        elif not line.strip() and core is not None:
            ids.add((phys, core))
            phys = core = None
    if core is not None:
        ids.add((phys, core))
    print(len(ids) or os.cpu_count() or 1)
except OSError:
    print(os.cpu_count() or 1)
PY
)

# options du parallèle : vide en série
parallele=()
if [ "${TESTS_SERIE:-0}" != "1" ] && python3 -c "import xdist" 2>/dev/null; then
    parallele=(-n "$coeurs" --dist worksteal)
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
        if [ ${#parallele[@]} -eq 0 ]; then         # série : un seul passage
            exec python3 -m pytest -q --slow-guard "$@"
        fi
        echo "=== Avancé, passage A : tout sauf audio, en parallèle ($coeurs processus) ==="
        python3 -m pytest -q "${parallele[@]}" --slow-guard -m "not audio" "$@"
        code_a=$?
        [ $code_a -eq 5 ] && code_a=0               # 5 : aucun test choisi (-k…)
        echo "=== Avancé, passage B : tests audio (temps réel), entre eux ==="
        python3 -m pytest -q "${parallele[@]}" --slow-guard -m "audio" "$@"
        code_b=$?
        [ $code_b -eq 5 ] && code_b=0
        if [ $code_a -ne 0 ] || [ $code_b -ne 0 ]; then
            echo "Avancé : ÉCHEC (passage A : code $code_a ; passage B : code $code_b)"
            exit $(( code_a != 0 ? code_a : code_b ))
        fi
        echo "Avancé : tout passe (passages A et B : code 0)"
        exit 0
        ;;
    *)
        usage
        exit 2
        ;;
esac
