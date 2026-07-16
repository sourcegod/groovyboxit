#python3
"""
    File: tests/test_pattern_properties_bug.py
    Test de régression — bug mw_patterns.py::_pattern_properties_dialog.

    Avant la fusion _curpattern/_tape, les actions "Doubler"/"Diviser par 2"/
    "Redimensionner" faisaient `pat.load_pattern(live._curpattern)` (grille
    seule) SANS resynchroniser _tape/_bend_tape/_mod_tape vers l'objet Pattern
    stocké dans _pattern_list. Un pattern doublé contenant des notes K/P (ou
    de l'automation bend/mod) perdait donc la synchronisation entre la grille
    et la tape dans le store.

    La fusion en une seule structure (_tape) corrige ce bug par construction :
    Pattern.copy_from() clone dims + _tape + _bend_tape + _mod_tape en un seul
    appel, il est donc impossible d'oublier une partie de l'état.

    Ce test reproduit directement la séquence Python (sans wx) : l'essentiel
    du bug est dans la logique pure, pas dans le dialog.
    Date: Thu, 16/07/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH
from drum_player import DrumPlayer


def _make_live_with_kp(num_bars=2, num_steps=16):
    """DrumPlayer avec des notes G ET K/P, comme le pattern courant en édition."""
    player = DrumPlayer(sound_manager=None)
    player._pattern.new_pattern(num_bars, num_steps)
    live = player._pattern
    live.set_cell(0, 0, 0, 0, 100)     # note de grille (G)
    live._tape.setdefault((0, 0, 4), []).append(TapeEvent(ETYPE_KIT, 36, 90, 0, 0))
    live._tape.setdefault((0, 1, 2), []).append(TapeEvent(ETYPE_PATCH, 60, 80, 300, 50))
    live._bend_tape[0].append((5.0, 1000))
    live._mod_tape[0].append((3.0, 64))
    return player


def _buggy_sync(pat, live):
    """Reproduit l'ANCIEN code de _pattern_properties_dialog (le bug)."""
    pat.load_pattern(live.to_dense_grid())


def _fixed_sync(pat, live):
    """Reproduit le NOUVEAU code (le fix) : un seul appel copy_from()."""
    pat.copy_from(live)


# ---------------------------------------------------------------------------
# Doubler
# ---------------------------------------------------------------------------

def test_buggy_sync_loses_kp_after_double():
    """Documente le bug : load_pattern seul perd K/P/bend/mod après Doubler."""
    player = _make_live_with_kp(num_bars=2)
    live   = player._pattern
    pat    = Pattern()
    pat.new_pattern(2, 16)

    assert player.double_pattern() is True
    _buggy_sync(pat, live)

    # La grille (G) a bien été doublée...
    assert pat.get_cell(0, 0, 0, 0) == 100
    assert pat.get_cell(0, 0, 2, 0) == 100   # copie de la mesure 0 → mesure 2
    # ...mais K/P/bend/mod ont disparu (bug) : pat._tape ne contient QUE des G
    assert all(ev.etype == ETYPE_GRID for evs in pat._tape.values() for ev in evs)
    assert pat._bend_tape == [[] for _ in range(pat._num_tracks)]
    assert pat._mod_tape  == [[] for _ in range(pat._num_tracks)]
    print("  bug confirmé : load_pattern seul perd K/P/bend/mod après Doubler : OK")


def test_fixed_sync_preserves_everything_after_double():
    """copy_from() transfère G + K/P + bend/mod, avec bar_idx décalé de `half`."""
    player = _make_live_with_kp(num_bars=2)
    live   = player._pattern
    pat    = Pattern()
    pat.new_pattern(2, 16)

    assert player.double_pattern() is True
    _fixed_sync(pat, live)

    # Grille doublée
    assert pat.get_cell(0, 0, 0, 0) == 100
    assert pat.get_cell(0, 0, 2, 0) == 100

    # K/P d'origine ET leurs copies décalées de `half` (2 mesures)
    k_bars = sorted(b for (t, b, s), evs in pat._tape.items()
                     for ev in evs if ev.etype == ETYPE_KIT)
    p_bars = sorted(b for (t, b, s), evs in pat._tape.items()
                     for ev in evs if ev.etype == ETYPE_PATCH)
    assert k_bars == [0, 2]   # original bar=0, copie bar=0+half(2)
    assert p_bars == [1, 3]   # original bar=1, copie bar=1+half(2)

    # bend/mod également dupliqués avec l'offset de mesures
    assert pat._bend_tape[0] == live._bend_tape[0]
    assert pat._mod_tape[0]  == live._mod_tape[0]
    assert len(pat._bend_tape[0]) == 2   # (5.0, ...) + copie (5.0+32, ...)
    print("  fix confirmé : copy_from() préserve G + K/P + bend/mod après Doubler : OK")


# ---------------------------------------------------------------------------
# Diviser par 2
# ---------------------------------------------------------------------------

def test_buggy_sync_loses_kp_after_halve():
    player = _make_live_with_kp(num_bars=4)
    live   = player._pattern
    # Dupliquer les notes sur les mesures 2-3 pour vérifier leur troncature
    live.set_cell(0, 0, 3, 5, 100)
    pat = Pattern()
    pat.new_pattern(4, 16)

    assert player.halve_pattern() is True   # 4 → 2 mesures
    _buggy_sync(pat, live)

    assert all(ev.etype == ETYPE_GRID for evs in pat._tape.values() for ev in evs)
    print("  bug confirmé : load_pattern seul perd K/P après Diviser : OK")


def test_fixed_sync_preserves_kp_after_halve():
    player = _make_live_with_kp(num_bars=4)
    live   = player._pattern
    pat    = Pattern()
    pat.new_pattern(4, 16)

    assert player.halve_pattern() is True   # 4 → 2 mesures
    _fixed_sync(pat, live)

    assert pat._num_bars == 2
    assert pat._tape == live._tape
    assert pat._bend_tape == live._bend_tape
    assert pat._mod_tape  == live._mod_tape
    # Les notes K (bar=0) et P (bar=1) sont dans la moitié conservée
    etypes = {ev.etype for evs in pat._tape.values() for ev in evs}
    assert etypes == {ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH}
    print("  fix confirmé : copy_from() préserve K/P après Diviser : OK")


# ---------------------------------------------------------------------------
# Redimensionner (resize)
# ---------------------------------------------------------------------------

def test_buggy_sync_loses_kp_after_resize():
    player = _make_live_with_kp(num_bars=2)
    live   = player._pattern
    pat    = Pattern()
    pat.new_pattern(2, 16)

    live.resize(4, 32)   # étend mesures et pas
    _buggy_sync(pat, live)

    assert all(ev.etype == ETYPE_GRID for evs in pat._tape.values() for ev in evs)
    print("  bug confirmé : load_pattern seul perd K/P après Redimensionner : OK")


def test_fixed_sync_preserves_kp_after_resize():
    player = _make_live_with_kp(num_bars=2)
    live   = player._pattern
    pat    = Pattern()
    pat.new_pattern(2, 16)

    live.resize(4, 32)
    _fixed_sync(pat, live)

    assert pat._num_bars  == 4
    assert pat._num_steps == 32
    assert pat._tape == live._tape
    etypes = {ev.etype for evs in pat._tape.values() for ev in evs}
    assert etypes == {ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH}
    print("  fix confirmé : copy_from() préserve K/P après Redimensionner : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_buggy_sync_loses_kp_after_double()
    test_fixed_sync_preserves_everything_after_double()
    test_buggy_sync_loses_kp_after_halve()
    test_fixed_sync_preserves_kp_after_halve()
    test_buggy_sync_loses_kp_after_resize()
    test_fixed_sync_preserves_kp_after_resize()
    print("Tous les tests test_pattern_properties_bug ont réussi.")
