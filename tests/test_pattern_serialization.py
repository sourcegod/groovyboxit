#python3
"""
    File: tests/test_pattern_serialization.py
    Tests de la sérialisation/désérialisation du Pattern en mode multi-piste :
    structure curpattern, track_slots, voices, round-trip JSON complet.
    Date: Mon, 18/05/2026
    Author: Coolbrother
"""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NUM_TRACKS = 8
NUM_PADS   = 16
NUM_STEPS  = 16


def _make_multitrack_pattern():
    """
    Retourne un Pattern avec des notes sur plusieurs pistes et track_slots variés.

      Piste 0 — pad 0  : steps 0, 4, 8, 12   (kick)
      Piste 0 — pad 4  : steps 2, 10          (snare)
      Piste 1 — pad 1  : steps 0, 8           (basse)
      Piste 2 — pad 7  : step  15             (ghost note)
      Piste 3 — pad 2  : step  3              (note isolée)
    """
    p = Pattern()
    cp = p._curpattern
    cp[0][0][0][0] = cp[0][0][0][4] = cp[0][0][0][8] = cp[0][0][0][12] = True
    cp[0][4][0][2] = cp[0][4][0][10] = True
    cp[1][1][0][0] = cp[1][1][0][8]  = True
    cp[2][7][0][15] = True
    cp[3][2][0][3]  = True
    # Assignations de slots variées
    p._track_slots = [0, 1, 2, 1, 0, 0, 0, 0]
    # Voix personnalisées sur quelques pads
    p._voices[0]["volume"] = 80
    p._voices[1]["pan"]    = -30
    p._voices[4]["mute"]   = True
    return p


def _serialize(pat):
    """Reproduit exactement le format de _save_preset pour un pattern."""
    return {
        "name":        pat._name,
        "bpm":         pat._bpm,
        "num_bars":    pat._num_bars,
        "num_steps":   pat._num_steps,
        "track_slots": pat._track_slots[:],
        "curpattern":  pat._curpattern,
        "voices":      pat._voices,
    }


def _deserialize(data):
    """Reproduit exactement la logique de _load_preset pour un pattern."""
    pat = Pattern()
    pat._name      = data.get("name", "")
    pat._bpm       = data.get("bpm", 100)
    pat._num_bars  = data.get("num_bars", 1)
    pat._num_steps = data.get("num_steps", 16)
    pat.load_pattern(data["curpattern"])
    if "track_slots" in data:
        pat._track_slots = data["track_slots"]
    if "voices" in data:
        pat._voices = data["voices"]
    return pat


# ---------------------------------------------------------------------------
# Tests Pattern._track_slots
# ---------------------------------------------------------------------------

def test_pattern_has_track_slots():
    p = Pattern()
    assert hasattr(p, "_track_slots"), "Pattern doit avoir _track_slots"
    assert p._track_slots == [0] * NUM_TRACKS
    print("  Pattern._track_slots (défaut) : OK")


def test_pattern_track_slots_length():
    p = Pattern()
    assert len(p._track_slots) == NUM_TRACKS
    print("  Pattern._track_slots longueur : OK")


# ---------------------------------------------------------------------------
# Tests structure curpattern
# ---------------------------------------------------------------------------

def test_curpattern_dimensions():
    p = Pattern()
    assert len(p._curpattern) == NUM_TRACKS
    for track in p._curpattern:
        assert len(track) == NUM_PADS
        for pad in track:
            assert len(pad) == 1          # 1 mesure par défaut
            assert len(pad[0]) == NUM_STEPS
    print("  curpattern dimensions [track][pad][bar][step] : OK")


def test_curpattern_initially_empty():
    p = Pattern()
    for track in p._curpattern:
        for pad in track:
            for bar in pad:
                assert not any(bar)
    print("  curpattern initialement vide : OK")


def test_load_pattern_preserves_dimensions():
    src = _make_multitrack_pattern()
    dst = Pattern()
    dst.load_pattern(src._curpattern)
    assert dst._num_tracks == NUM_TRACKS
    assert dst._num_pads   == NUM_PADS
    assert dst._num_bars   == 1
    assert dst._num_steps  == NUM_STEPS
    print("  load_pattern dimensions : OK")


# ---------------------------------------------------------------------------
# Tests round-trip sérialisation / désérialisation (dict)
# ---------------------------------------------------------------------------

def test_roundtrip_curpattern_notes():
    """Les notes multi-pistes doivent survivre au cycle sérialise → désérialise."""
    src = _make_multitrack_pattern()
    data = _serialize(src)
    dst = _deserialize(data)

    cp = dst._curpattern
    assert cp[0][0][0][0]  == True,  "Piste 0 pad 0 step 0"
    assert cp[0][0][0][4]  == True,  "Piste 0 pad 0 step 4"
    assert cp[0][0][0][8]  == True,  "Piste 0 pad 0 step 8"
    assert cp[0][0][0][12] == True,  "Piste 0 pad 0 step 12"
    assert cp[0][4][0][2]  == True,  "Piste 0 pad 4 step 2"
    assert cp[0][4][0][10] == True,  "Piste 0 pad 4 step 10"
    assert cp[1][1][0][0]  == True,  "Piste 1 pad 1 step 0"
    assert cp[1][1][0][8]  == True,  "Piste 1 pad 1 step 8"
    assert cp[2][7][0][15] == True,  "Piste 2 pad 7 step 15"
    assert cp[3][2][0][3]  == True,  "Piste 3 pad 2 step 3"
    print("  round-trip curpattern (notes multi-pistes) : OK")


def test_roundtrip_curpattern_empty_tracks():
    """Les pistes sans notes doivent rester vides après round-trip."""
    src = _make_multitrack_pattern()
    data = _serialize(src)
    dst = _deserialize(data)
    for track_idx in range(4, NUM_TRACKS):
        for pad in dst._curpattern[track_idx]:
            for bar in pad:
                assert not any(bar), f"Piste {track_idx} doit être vide"
    print("  round-trip pistes vides : OK")


def test_roundtrip_track_slots():
    src = _make_multitrack_pattern()
    data = _serialize(src)
    dst = _deserialize(data)
    assert dst._track_slots == [0, 1, 2, 1, 0, 0, 0, 0]
    print("  round-trip track_slots : OK")


def test_roundtrip_voices():
    src = _make_multitrack_pattern()
    data = _serialize(src)
    dst = _deserialize(data)
    assert dst._voices[0]["volume"] == 80
    assert dst._voices[1]["pan"]    == -30
    assert dst._voices[4]["mute"]   == True
    print("  round-trip voices : OK")


def test_roundtrip_metadata():
    src = Pattern()
    src._name     = "Groove Test"
    src._bpm      = 140
    src._num_bars = 2
    data = _serialize(src)
    dst  = _deserialize(data)
    assert dst._name == "Groove Test"
    assert dst._bpm  == 140
    print("  round-trip métadonnées (name, bpm) : OK")


# ---------------------------------------------------------------------------
# Tests round-trip via JSON (fichier temporaire)
# ---------------------------------------------------------------------------

def _build_preset_dict(pattern_list):
    return {
        "version": 1,
        "patterns": [_serialize(p) for p in pattern_list],
    }


def _load_preset_dict(data):
    patterns = []
    for p in data.get("patterns", []):
        patterns.append(_deserialize(p))
    return patterns


def test_json_roundtrip_single_pattern():
    """Sérialisation JSON complète → fichier temporaire → chargement."""
    src = _make_multitrack_pattern()
    src._name = "JSON Test"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(_build_preset_dict([src]), f, indent=2)
        path = f.name

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        [dst] = _load_preset_dict(data)

        assert dst._name == "JSON Test"
        assert dst._track_slots == [0, 1, 2, 1, 0, 0, 0, 0]
        assert dst._curpattern[2][7][0][15] == True
        assert dst._curpattern[3][2][0][3]  == True
        assert dst._voices[0]["volume"]     == 80
    finally:
        os.unlink(path)
    print("  JSON round-trip (fichier temporaire) : OK")


def test_json_roundtrip_99_patterns():
    """Un preset complet de 99 patterns doit se recharger sans perte."""
    pattern_list = [Pattern() for _ in range(99)]
    # Quelques patterns non vides
    pattern_list[0]._curpattern[0][0][0][0]  = True
    pattern_list[0]._track_slots             = [0, 1, 2, 3, 0, 0, 0, 0]
    pattern_list[5]._curpattern[1][3][0][7]  = True
    pattern_list[5]._track_slots             = [1, 2, 0, 0, 0, 0, 0, 0]
    pattern_list[5]._name                    = "Pattern 6"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(_build_preset_dict(pattern_list), f, indent=2)
        path = f.name

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        loaded = _load_preset_dict(data)

        assert len(loaded) == 99
        assert loaded[0]._curpattern[0][0][0][0]  == True
        assert loaded[0]._track_slots             == [0, 1, 2, 3, 0, 0, 0, 0]
        assert loaded[5]._curpattern[1][3][0][7]  == True
        assert loaded[5]._track_slots             == [1, 2, 0, 0, 0, 0, 0, 0]
        assert loaded[5]._name                    == "Pattern 6"
        # Patterns vides
        for i in [1, 2, 10, 50, 98]:
            for track in loaded[i]._curpattern:
                for pad in track:
                    for bar in pad:
                        assert not any(bar), f"Pattern {i} doit être vide"
    finally:
        os.unlink(path)
    print("  JSON round-trip (99 patterns) : OK")


def test_json_backwards_compatible_no_track_slots():
    """Un ancien preset sans track_slots doit se charger avec des valeurs par défaut."""
    old_data = {
        "version": 1,
        "patterns": [
            {
                "name": "Old",
                "bpm": 120,
                "num_bars": 1,
                "num_steps": 16,
                "curpattern": Pattern()._curpattern,
                # pas de track_slots
                "voices": Pattern()._voices,
            }
        ],
    }
    loaded = _load_preset_dict(old_data)
    assert loaded[0]._track_slots == [0] * NUM_TRACKS, \
        "Défaut [0]*8 si track_slots absent"
    print("  backward-compat (pas de track_slots) : OK")


# ---------------------------------------------------------------------------
# Tests switch_pattern (logique pure, sans wx)
# ---------------------------------------------------------------------------

def _simulate_switch_pattern(pattern_list, cur_idx, router_track_slots,
                             new_idx, new_router_slots):
    """
    Reproduit la logique de _switch_pattern sans wx :
      1. Sauvegarder les track_slots courants dans le pattern courant
      2. Charger les track_slots du nouveau pattern dans le router
    Retourne (router_track_slots_after, pattern_list[cur_idx]._track_slots).
    """
    pattern_list[cur_idx]._track_slots = router_track_slots[:]
    router_track_slots[:] = pattern_list[new_idx]._track_slots
    return router_track_slots[:], pattern_list[cur_idx]._track_slots


def test_switch_pattern_saves_current_track_slots():
    p0 = Pattern()
    p1 = Pattern()
    p0._track_slots = [0, 1, 2, 0, 0, 0, 0, 0]
    p1._track_slots = [3, 0, 0, 0, 0, 0, 0, 0]
    router_slots = [0, 1, 2, 0, 0, 0, 0, 0]

    new_router, saved_p0 = _simulate_switch_pattern(
        [p0, p1], 0, router_slots, 1, [3, 0, 0, 0, 0, 0, 0, 0]
    )
    assert saved_p0   == [0, 1, 2, 0, 0, 0, 0, 0], "Slots de p0 doivent être sauvegardés"
    assert new_router == [3, 0, 0, 0, 0, 0, 0, 0], "Router doit prendre les slots de p1"
    print("  switch_pattern sauvegarde + restaure track_slots : OK")


def test_switch_pattern_preserves_both_patterns():
    """Aller-retour entre deux patterns doit préserver les deux jeux de slots."""
    p0 = Pattern(); p0._track_slots = [0, 1, 2, 3, 0, 0, 0, 0]
    p1 = Pattern(); p1._track_slots = [2, 2, 0, 0, 0, 0, 0, 0]
    router_slots = p0._track_slots[:]

    # Aller : 0 → 1
    _, _ = _simulate_switch_pattern([p0, p1], 0, router_slots, 1, p1._track_slots)
    # Retour : 1 → 0
    _, _ = _simulate_switch_pattern([p0, p1], 1, router_slots, 0, p0._track_slots)

    assert p0._track_slots == [0, 1, 2, 3, 0, 0, 0, 0]
    assert p1._track_slots == [2, 2, 0, 0, 0, 0, 0, 0]
    print("  switch_pattern aller-retour : OK")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_pattern_serialization ===")
    test_pattern_has_track_slots()
    test_pattern_track_slots_length()
    test_curpattern_dimensions()
    test_curpattern_initially_empty()
    test_load_pattern_preserves_dimensions()
    test_roundtrip_curpattern_notes()
    test_roundtrip_curpattern_empty_tracks()
    test_roundtrip_track_slots()
    test_roundtrip_voices()
    test_roundtrip_metadata()
    test_json_roundtrip_single_pattern()
    test_json_roundtrip_99_patterns()
    test_json_backwards_compatible_no_track_slots()
    test_switch_pattern_saves_current_track_slots()
    test_switch_pattern_preserves_both_patterns()
    print("Tous les tests : OK")
