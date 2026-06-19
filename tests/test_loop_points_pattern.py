#python3
"""
    File: tests/test_loop_points_pattern.py
    Tests unitaires des champs de boucle sur Pattern :
    valeurs initiales, to_dict, from_dict, round-trip JSON.
    Date: Fri, 20/06/2026
    Author: Coolbrother
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern


# ---------------------------------------------------------------------------
# Valeurs initiales
# ---------------------------------------------------------------------------

def test_loop_start_default():
    p = Pattern()
    assert p._loop_start is None
    print("  _loop_start par défaut = None : OK")


def test_loop_end_default():
    p = Pattern()
    assert p._loop_end is None
    print("  _loop_end par défaut = None : OK")


def test_loop_count_default():
    p = Pattern()
    assert p._loop_count == 0
    print("  _loop_count par défaut = 0 : OK")


def test_looping_default():
    p = Pattern()
    assert p._looping is True
    print("  _looping par défaut = True : OK")


# ---------------------------------------------------------------------------
# to_dict — présence des champs
# ---------------------------------------------------------------------------

def test_to_dict_contains_loop_start():
    p = Pattern()
    d = p.to_dict()
    assert "loop_start" in d
    print("  to_dict contient 'loop_start' : OK")


def test_to_dict_contains_loop_end():
    p = Pattern()
    d = p.to_dict()
    assert "loop_end" in d
    print("  to_dict contient 'loop_end' : OK")


def test_to_dict_contains_loop_count():
    p = Pattern()
    d = p.to_dict()
    assert "loop_count" in d
    print("  to_dict contient 'loop_count' : OK")


def test_to_dict_contains_looping():
    p = Pattern()
    d = p.to_dict()
    assert "looping" in d
    print("  to_dict contient 'looping' : OK")


def test_to_dict_default_values():
    p = Pattern()
    d = p.to_dict()
    assert d["loop_start"] is None
    assert d["loop_end"]   is None
    assert d["loop_count"] == 0
    assert d["looping"]    is True
    print("  to_dict valeurs par défaut : OK")


def test_to_dict_custom_values():
    p = Pattern()
    p._loop_start = 4
    p._loop_end   = 11
    p._loop_count = 3
    p._looping    = False
    d = p.to_dict()
    assert d["loop_start"] == 4
    assert d["loop_end"]   == 11
    assert d["loop_count"] == 3
    assert d["looping"]    is False
    print("  to_dict valeurs personnalisées : OK")


# ---------------------------------------------------------------------------
# from_dict — restauration des champs
# ---------------------------------------------------------------------------

def _base_dict(**overrides):
    """Dict minimal valide pour from_dict() (inclut curpattern)."""
    d = Pattern().to_dict()
    d.update(overrides)
    return d


def test_from_dict_restores_loop_start():
    p = Pattern()
    p.from_dict(_base_dict(loop_start=8))
    assert p._loop_start == 8
    print("  from_dict restaure loop_start=8 : OK")


def test_from_dict_restores_loop_end():
    p = Pattern()
    p.from_dict(_base_dict(loop_end=15))
    assert p._loop_end == 15
    print("  from_dict restaure loop_end=15 : OK")


def test_from_dict_restores_loop_count():
    p = Pattern()
    p.from_dict(_base_dict(loop_count=5))
    assert p._loop_count == 5
    print("  from_dict restaure loop_count=5 : OK")


def test_from_dict_restores_looping_false():
    p = Pattern()
    p.from_dict(_base_dict(looping=False))
    assert p._looping is False
    print("  from_dict restaure looping=False : OK")


def test_from_dict_loop_start_zero_is_stored():
    """loop_start=0 est une valeur explicite (pas None)."""
    p = Pattern()
    p.from_dict(_base_dict(loop_start=0))
    assert p._loop_start == 0
    print("  from_dict loop_start=0 conservé (pas None) : OK")


def test_from_dict_loop_end_zero_is_stored():
    p = Pattern()
    p.from_dict(_base_dict(loop_end=0))
    assert p._loop_end == 0
    print("  from_dict loop_end=0 conservé : OK")


# ---------------------------------------------------------------------------
# Compatibilité ascendante — preset sans champs boucle
# ---------------------------------------------------------------------------

def _base_dict_no_loop():
    """Dict valide sans les clés loop_*, simule un vieux preset."""
    d = Pattern().to_dict()
    for k in ("loop_start", "loop_end", "loop_count", "looping"):
        d.pop(k, None)
    return d


def test_from_dict_missing_loop_start_defaults_none():
    p = Pattern()
    p.from_dict(_base_dict_no_loop())
    assert p._loop_start is None
    print("  from_dict sans loop_start → None : OK")


def test_from_dict_missing_loop_end_defaults_none():
    p = Pattern()
    p.from_dict(_base_dict_no_loop())
    assert p._loop_end is None
    print("  from_dict sans loop_end → None : OK")


def test_from_dict_missing_loop_count_defaults_zero():
    p = Pattern()
    p.from_dict(_base_dict_no_loop())
    assert p._loop_count == 0
    print("  from_dict sans loop_count → 0 : OK")


def test_from_dict_missing_looping_defaults_true():
    p = Pattern()
    p.from_dict(_base_dict_no_loop())
    assert p._looping is True
    print("  from_dict sans looping → True : OK")


# ---------------------------------------------------------------------------
# Round-trip complet via to_dict / from_dict
# ---------------------------------------------------------------------------

def test_roundtrip_defaults():
    src = Pattern()
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._loop_start == src._loop_start
    assert dst._loop_end   == src._loop_end
    assert dst._loop_count == src._loop_count
    assert dst._looping    == src._looping
    print("  round-trip valeurs par défaut : OK")


def test_roundtrip_custom_loop_window():
    src = Pattern()
    src._loop_start = 4
    src._loop_end   = 27
    src._loop_count = 2
    src._looping    = True
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._loop_start == 4
    assert dst._loop_end   == 27
    assert dst._loop_count == 2
    assert dst._looping    is True
    print("  round-trip fenêtre personnalisée : OK")


def test_roundtrip_looping_off():
    src = Pattern()
    src._looping = False
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._looping is False
    print("  round-trip looping=False : OK")


def test_roundtrip_loop_start_only():
    """Point de début défini, fin = None."""
    src = Pattern()
    src._loop_start = 8
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._loop_start == 8
    assert dst._loop_end   is None
    print("  round-trip loop_start seul : OK")


def test_roundtrip_loop_end_only():
    """Point de fin défini, début = None."""
    src = Pattern()
    src._loop_end = 12
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._loop_start is None
    assert dst._loop_end   == 12
    print("  round-trip loop_end seul : OK")


def test_roundtrip_loop_count_zero_infinite():
    """loop_count=0 signifie répétition infinie."""
    src = Pattern()
    src._loop_count = 0
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._loop_count == 0
    print("  round-trip loop_count=0 (infini) : OK")


# ---------------------------------------------------------------------------
# Round-trip JSON (sérialisation fichier)
# ---------------------------------------------------------------------------

def test_json_roundtrip_loop_points():
    src = Pattern()
    src._loop_start = 3
    src._loop_end   = 19
    src._loop_count = 4
    src._looping    = True
    raw = json.dumps(src.to_dict())
    dst = Pattern()
    dst.from_dict(json.loads(raw))
    assert dst._loop_start == 3
    assert dst._loop_end   == 19
    assert dst._loop_count == 4
    assert dst._looping    is True
    print("  JSON round-trip complet : OK")


def test_json_roundtrip_none_values():
    """None est encodé en null en JSON, doit revenir None."""
    src = Pattern()  # loop_start=None, loop_end=None par défaut
    raw = json.dumps(src.to_dict())
    data = json.loads(raw)
    assert data["loop_start"] is None
    assert data["loop_end"]   is None
    dst = Pattern()
    dst.from_dict(data)
    assert dst._loop_start is None
    assert dst._loop_end   is None
    print("  JSON round-trip None→null→None : OK")


def test_json_roundtrip_loop_count_max():
    src = Pattern()
    src._loop_count = 99
    raw = json.dumps(src.to_dict())
    dst = Pattern()
    dst.from_dict(json.loads(raw))
    assert dst._loop_count == 99
    print("  JSON round-trip loop_count=99 : OK")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in fns:
        try:
            print(f"[RUN] {fn.__name__}")
            fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"Résultat : {passed} OK, {failed} FAIL")
