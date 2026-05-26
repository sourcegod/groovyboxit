#python3
"""
    File: tests/test_multitrack.py
    Tests de la lecture multi-piste : _all_offsets, float_offsets property,
    _compute_offsets, double/halve_pattern, et dispatch via _on_track_play_cb.
    Date: Mon, 18/05/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from drum_player import DrumPlayer
from pattern import Pattern


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_player_with_notes():
    """
    Retourne un DrumPlayer dont le pattern contient :
      Piste 0 — Pad 0  : steps 0, 4, 8, 12   (noire sur 4 temps)
      Piste 0 — Pad 3  : step  2              (snare au 2e temps)
      Piste 1 — Pad 1  : steps 0, 8           (basse sur 1 et 3)
      Piste 2 — Pad 7  : step  15             (ghost note en fin de mesure)
    """
    p = DrumPlayer()
    cp = p._pattern._curpattern
    cp[0][0][0][0]  = cp[0][0][0][4]  = cp[0][0][0][8]  = cp[0][0][0][12] = True
    cp[0][3][0][2]  = True
    cp[1][1][0][0]  = cp[1][1][0][8]  = True
    cp[2][7][0][15] = True
    p._compute_offsets()
    return p


# ---------------------------------------------------------------------------
# Tests property float_offsets
# ---------------------------------------------------------------------------

def test_float_offsets_alias_cur_track():
    p = DrumPlayer()
    p._cur_track = 0
    assert p.float_offsets is p._all_offsets[0], \
        "float_offsets doit être un alias de _all_offsets[_cur_track]"

    p._cur_track = 1
    assert p.float_offsets is p._all_offsets[1]
    print("  float_offsets alias : OK")


def test_float_offsets_setter():
    p = DrumPlayer()
    p._cur_track = 2
    new_val = [[1.0, 2.0], [3.0]]
    p.float_offsets = new_val
    assert p._all_offsets[2] is new_val, \
        "Le setter doit écrire dans _all_offsets[_cur_track]"
    print("  float_offsets setter : OK")


def test_float_offsets_item_setitem():
    """Vérifier que float_offsets[pad] = [...] modifie bien _all_offsets[cur_track]."""
    p = DrumPlayer()
    p._cur_track = 0
    p.float_offsets[0] = [0.0, 4.0, 8.0]
    assert p._all_offsets[0][0] == [0.0, 4.0, 8.0]
    print("  float_offsets[pad] = [...] : OK")


# ---------------------------------------------------------------------------
# Tests _compute_offsets
# ---------------------------------------------------------------------------

def test_compute_offsets_all_tracks():
    p = _make_player_with_notes()

    assert p._all_offsets[0][0] == [0.0, 4.0, 8.0, 12.0], \
        f"Piste 0 pad 0 attendu [0,4,8,12], obtenu {p._all_offsets[0][0]}"
    assert p._all_offsets[0][3] == [2.0], \
        f"Piste 0 pad 3 attendu [2], obtenu {p._all_offsets[0][3]}"
    assert p._all_offsets[1][1] == [0.0, 8.0], \
        f"Piste 1 pad 1 attendu [0,8], obtenu {p._all_offsets[1][1]}"
    assert p._all_offsets[2][7] == [15.0], \
        f"Piste 2 pad 7 attendu [15], obtenu {p._all_offsets[2][7]}"
    print("  _compute_offsets (toutes pistes) : OK")


def test_compute_offsets_empty_tracks():
    """Les pistes sans notes doivent avoir des offsets vides."""
    p = _make_player_with_notes()
    # Pistes 3..7 : aucune note
    for track_idx in range(3, p._pattern._num_tracks):
        for pad_offsets in p._all_offsets[track_idx]:
            assert pad_offsets == [], \
                f"Piste {track_idx} devrait être vide, obtenu {pad_offsets}"
    print("  _compute_offsets pistes vides : OK")


# ---------------------------------------------------------------------------
# Tests double_pattern / halve_pattern multi-piste
# ---------------------------------------------------------------------------

def test_double_pattern_all_tracks():
    p = _make_player_with_notes()
    half = p._pattern._num_steps  # = 16 avant le doublement

    ok = p.double_pattern()
    assert ok, "double_pattern doit réussir"

    # Piste 0, pad 0 : [0,4,8,12] + [16,20,24,28]
    assert p._all_offsets[0][0] == [0.0, 4.0, 8.0, 12.0, 16.0, 20.0, 24.0, 28.0]
    # Piste 1, pad 1 : [0,8] + [16,24]
    assert p._all_offsets[1][1] == [0.0, 8.0, 16.0, 24.0]
    # Piste 2, pad 7 : [15] + [31]
    assert p._all_offsets[2][7] == [15.0, 31.0]
    print("  double_pattern (toutes pistes) : OK")


def test_halve_pattern_all_tracks():
    p = _make_player_with_notes()
    p.double_pattern()   # 2 mesures
    p.halve_pattern()    # retour à 1 mesure

    assert p._all_offsets[0][0] == [0.0, 4.0, 8.0, 12.0]
    assert p._all_offsets[1][1] == [0.0, 8.0]
    assert p._all_offsets[2][7] == [15.0]
    print("  halve_pattern (toutes pistes) : OK")


# ---------------------------------------------------------------------------
# Test dispatch via _on_track_play_cb
# ---------------------------------------------------------------------------

def test_on_track_play_cb_called_per_track():
    """
    Simule un cycle de lecture (sans audio réel) et vérifie que le callback
    est appelé avec le bon (track_idx, pad_idx) pour chaque note du pattern.
    """
    import time

    p = _make_player_with_notes()

    received = []

    def fake_cb(track_idx, pad_idx, vol, pan, dur=0):
        received.append((track_idx, pad_idx))

    p._on_track_play_cb = fake_cb
    p.bpm = 240          # très rapide → mesure de 1 s
    p.step_duration = 60.0 / p.bpm / 4

    # Lancer la lecture et laisser tourner 2 mesures
    p.play_pattern()
    time.sleep(2.5)
    p.stop_pattern()

    # Vérifier que chaque événement attendu a été reçu au moins une fois
    expected = [
        (0, 0),  # piste 0 pad 0 (kicks)
        (0, 3),  # piste 0 pad 3 (snare)
        (1, 1),  # piste 1 pad 1 (basse)
        (2, 7),  # piste 2 pad 7 (ghost note)
    ]
    for evt in expected:
        assert evt in received, \
            f"Événement {evt} non reçu — reçus: {set(received)}"
    print(f"  _on_track_play_cb : OK ({len(received)} événements reçus)")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_multitrack ===")
    test_float_offsets_alias_cur_track()
    test_float_offsets_setter()
    test_float_offsets_item_setitem()
    test_compute_offsets_all_tracks()
    test_compute_offsets_empty_tracks()
    test_double_pattern_all_tracks()
    test_halve_pattern_all_tracks()
    test_on_track_play_cb_called_per_track()
    print("Tous les tests : OK")
