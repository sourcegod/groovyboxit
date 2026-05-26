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
    Retourne un Pattern avec des notes sur plusieurs pistes et états mixage variés.

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
    # Mixage par piste
    p._track_mutes[2]   = True
    p._track_solos[0]   = True
    p._track_volumes[1] = 75
    p._track_pans[3]    = -40
    # Voix personnalisées sur quelques pads
    p._voices[0]["volume"] = 80
    p._voices[1]["pan"]    = -30
    p._voices[4]["mute"]   = True
    return p


def _serialize(pat):
    """Reproduit exactement le format de _save_preset pour un pattern."""
    return {
        "name":          pat._name,
        "bpm":           pat._bpm,
        "num_bars":      pat._num_bars,
        "num_steps":     pat._num_steps,
        "track_slots":   pat._track_slots[:],
        "track_mutes":   pat._track_mutes[:],
        "track_solos":   pat._track_solos[:],
        "track_volumes": pat._track_volumes[:],
        "track_pans":    pat._track_pans[:],
        "curpattern":    pat._curpattern,
        "voices":        pat._voices,
    }


def _deserialize(data):
    """Reproduit exactement la logique de _load_preset pour un pattern."""
    pat = Pattern()
    pat._name      = data.get("name", "")
    pat._bpm       = data.get("bpm", 100)
    pat._num_bars  = data.get("num_bars", 1)
    pat._num_steps = data.get("num_steps", 16)
    pat.load_pattern(data["curpattern"])
    if "track_slots"   in data: pat._track_slots   = data["track_slots"]
    if "track_mutes"   in data: pat._track_mutes   = data["track_mutes"]
    if "track_solos"   in data: pat._track_solos   = data["track_solos"]
    if "track_volumes" in data: pat._track_volumes = data["track_volumes"]
    if "track_pans"    in data: pat._track_pans    = data["track_pans"]
    if "voices"        in data: pat._voices        = data["voices"]
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


def test_pattern_has_track_mix_fields():
    p = Pattern()
    assert hasattr(p, "_track_mutes")   and p._track_mutes   == [False] * NUM_TRACKS
    assert hasattr(p, "_track_solos")   and p._track_solos   == [False] * NUM_TRACKS
    assert hasattr(p, "_track_volumes") and p._track_volumes == [100]   * NUM_TRACKS
    assert hasattr(p, "_track_pans")    and p._track_pans    == [0]     * NUM_TRACKS
    print("  Pattern._track_mutes/solos/volumes/pans (défaut) : OK")


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
    assert cp[0][0][0][0],   "Piste 0 pad 0 step 0"
    assert cp[0][0][0][4],   "Piste 0 pad 0 step 4"
    assert cp[0][0][0][8],   "Piste 0 pad 0 step 8"
    assert cp[0][0][0][12],  "Piste 0 pad 0 step 12"
    assert cp[0][4][0][2],   "Piste 0 pad 4 step 2"
    assert cp[0][4][0][10],  "Piste 0 pad 4 step 10"
    assert cp[1][1][0][0],   "Piste 1 pad 1 step 0"
    assert cp[1][1][0][8],   "Piste 1 pad 1 step 8"
    assert cp[2][7][0][15],  "Piste 2 pad 7 step 15"
    assert cp[3][2][0][3],   "Piste 3 pad 2 step 3"
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


def test_roundtrip_track_mutes():
    src = _make_multitrack_pattern()
    data = _serialize(src)
    dst = _deserialize(data)
    assert dst._track_mutes[2] is True,  "Piste 2 doit être mutée"
    assert all(not dst._track_mutes[i] for i in range(NUM_TRACKS) if i != 2)
    print("  round-trip track_mutes : OK")


def test_roundtrip_track_solos():
    src = _make_multitrack_pattern()
    data = _serialize(src)
    dst = _deserialize(data)
    assert dst._track_solos[0] is True, "Piste 0 doit être en solo"
    assert all(not dst._track_solos[i] for i in range(NUM_TRACKS) if i != 0)
    print("  round-trip track_solos : OK")


def test_roundtrip_track_volumes():
    src = _make_multitrack_pattern()
    data = _serialize(src)
    dst = _deserialize(data)
    assert dst._track_volumes[1] == 75,  "Piste 1 volume 75"
    assert all(dst._track_volumes[i] == 100 for i in range(NUM_TRACKS) if i != 1)
    print("  round-trip track_volumes : OK")


def test_roundtrip_track_pans():
    src = _make_multitrack_pattern()
    data = _serialize(src)
    dst = _deserialize(data)
    assert dst._track_pans[3] == -40, "Piste 3 pan -40"
    assert all(dst._track_pans[i] == 0 for i in range(NUM_TRACKS) if i != 3)
    print("  round-trip track_pans : OK")


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
        assert dst._curpattern[2][7][0][15]
        assert dst._curpattern[3][2][0][3]
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
        assert loaded[0]._curpattern[0][0][0][0]
        assert loaded[0]._track_slots             == [0, 1, 2, 3, 0, 0, 0, 0]
        assert loaded[5]._curpattern[1][3][0][7]
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


def test_json_backwards_compatible_no_track_fields():
    """Un ancien preset sans les champs de mixage piste doit se charger avec les défauts."""
    old_data = {
        "version": 1,
        "patterns": [
            {
                "name": "Old",
                "bpm": 120,
                "num_bars": 1,
                "num_steps": 16,
                "curpattern": Pattern()._curpattern,
                # pas de track_slots, track_mutes, track_solos, track_volumes, track_pans
                "voices": Pattern()._voices,
            }
        ],
    }
    loaded = _load_preset_dict(old_data)
    p = loaded[0]
    assert p._track_slots   == [0]     * NUM_TRACKS, "Défaut [0]*8"
    assert p._track_mutes   == [False] * NUM_TRACKS, "Défaut [False]*8"
    assert p._track_solos   == [False] * NUM_TRACKS, "Défaut [False]*8"
    assert p._track_volumes == [100]   * NUM_TRACKS, "Défaut [100]*8"
    assert p._track_pans    == [0]     * NUM_TRACKS, "Défaut [0]*8"
    print("  backward-compat (champs mixage piste absents) : OK")


# ---------------------------------------------------------------------------
# Tests switch_pattern (logique pure, sans wx)
# ---------------------------------------------------------------------------

class FakeRouter:
    """Simule l'état du TrackRouter pour les tests switch_pattern."""
    def __init__(self, slots, mutes, solos, volumes, pans):
        self._track_slots   = slots[:]
        self._track_mutes   = mutes[:]
        self._track_solos   = solos[:]
        self._track_volumes = volumes[:]
        self._track_pans    = pans[:]


def _simulate_switch_pattern(pattern_list, cur_idx, router, new_idx):
    """
    Reproduit la logique de _switch_pattern sans wx :
      1. Sauvegarder l'état du router dans le pattern courant
      2. Charger l'état du nouveau pattern dans le router
    """
    cur = pattern_list[cur_idx]
    cur._track_slots   = router._track_slots[:]
    cur._track_mutes   = router._track_mutes[:]
    cur._track_solos   = router._track_solos[:]
    cur._track_volumes = router._track_volumes[:]
    cur._track_pans    = router._track_pans[:]
    new = pattern_list[new_idx]
    router._track_slots[:]   = new._track_slots
    router._track_mutes[:]   = new._track_mutes
    router._track_solos[:]   = new._track_solos
    router._track_volumes[:] = new._track_volumes
    router._track_pans[:]    = new._track_pans


def test_switch_pattern_saves_all_track_state():
    """switch_pattern sauvegarde les 5 champs piste du router dans le pattern courant."""
    p0 = Pattern()
    p0._track_slots   = [0, 1, 2, 0, 0, 0, 0, 0]
    p0._track_mutes   = [False, True, False, False, False, False, False, False]
    p0._track_solos   = [True,  False, False, False, False, False, False, False]
    p0._track_volumes = [80, 100, 60, 100, 100, 100, 100, 100]
    p0._track_pans    = [-20, 0, 30, 0, 0, 0, 0, 0]

    p1 = Pattern()   # état par défaut

    router = FakeRouter(
        slots   = p0._track_slots,
        mutes   = p0._track_mutes,
        solos   = p0._track_solos,
        volumes = p0._track_volumes,
        pans    = p0._track_pans,
    )
    _simulate_switch_pattern([p0, p1], 0, router, 1)

    assert p0._track_slots   == [0, 1, 2, 0, 0, 0, 0, 0]
    assert p0._track_mutes   == [False, True, False, False, False, False, False, False]
    assert p0._track_solos   == [True,  False, False, False, False, False, False, False]
    assert p0._track_volumes == [80, 100, 60, 100, 100, 100, 100, 100]
    assert p0._track_pans    == [-20, 0, 30, 0, 0, 0, 0, 0]
    # Router doit avoir chargé les défauts de p1
    assert router._track_slots   == [0] * NUM_TRACKS
    assert router._track_mutes   == [False] * NUM_TRACKS
    assert router._track_solos   == [False] * NUM_TRACKS
    assert router._track_volumes == [100]   * NUM_TRACKS
    assert router._track_pans    == [0]     * NUM_TRACKS
    print("  switch_pattern sauvegarde + restaure tous les champs piste : OK")


def test_switch_pattern_preserves_both_patterns():
    """Aller-retour entre deux patterns doit préserver les deux jeux d'état."""
    p0 = Pattern()
    p0._track_slots   = [0, 1, 2, 3, 0, 0, 0, 0]
    p0._track_mutes   = [True, False, False, False, False, False, False, False]
    p0._track_volumes = [90, 100, 100, 100, 100, 100, 100, 100]
    p0._track_pans    = [10, 0, 0, 0, 0, 0, 0, 0]

    p1 = Pattern()
    p1._track_slots   = [2, 2, 0, 0, 0, 0, 0, 0]
    p1._track_solos   = [False, True, False, False, False, False, False, False]
    p1._track_volumes = [100, 50, 100, 100, 100, 100, 100, 100]
    p1._track_pans    = [0, -30, 0, 0, 0, 0, 0, 0]

    router = FakeRouter(
        slots=p0._track_slots, mutes=p0._track_mutes, solos=p0._track_solos,
        volumes=p0._track_volumes, pans=p0._track_pans,
    )

    _simulate_switch_pattern([p0, p1], 0, router, 1)  # 0 → 1
    _simulate_switch_pattern([p0, p1], 1, router, 0)  # 1 → 0

    assert p0._track_slots   == [0, 1, 2, 3, 0, 0, 0, 0]
    assert p0._track_mutes   == [True, False, False, False, False, False, False, False]
    assert p0._track_volumes == [90, 100, 100, 100, 100, 100, 100, 100]
    assert p0._track_pans    == [10, 0, 0, 0, 0, 0, 0, 0]
    assert p1._track_slots   == [2, 2, 0, 0, 0, 0, 0, 0]
    assert p1._track_solos   == [False, True, False, False, False, False, False, False]
    assert p1._track_volumes == [100, 50, 100, 100, 100, 100, 100, 100]
    assert p1._track_pans    == [0, -30, 0, 0, 0, 0, 0, 0]
    print("  switch_pattern aller-retour (5 champs) : OK")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_pattern_serialization ===")
    test_pattern_has_track_slots()
    test_pattern_track_slots_length()
    test_pattern_has_track_mix_fields()
    test_curpattern_dimensions()
    test_curpattern_initially_empty()
    test_load_pattern_preserves_dimensions()
    test_roundtrip_curpattern_notes()
    test_roundtrip_curpattern_empty_tracks()
    test_roundtrip_track_slots()
    test_roundtrip_track_mutes()
    test_roundtrip_track_solos()
    test_roundtrip_track_volumes()
    test_roundtrip_track_pans()
    test_roundtrip_voices()
    test_roundtrip_metadata()
    test_json_roundtrip_single_pattern()
    test_json_roundtrip_99_patterns()
    test_json_backwards_compatible_no_track_fields()
    test_switch_pattern_saves_all_track_state()
    test_switch_pattern_preserves_both_patterns()
    print("Tous les tests : OK")
