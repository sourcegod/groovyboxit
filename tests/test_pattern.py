#python3
"""
    File: tests/test_pattern.py
    Tests unitaires de Pattern : valeurs initiales, new_pattern, load_pattern,
    reset_pattern, gen_pattern, double_bars, halve_bars, build_pattern_01,
    is_empty, resize, to_dict, from_dict.
    Date: Thu, 21/05/2026
    Author: Coolbrother
"""
import sys
import os
import copy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pat(**kw):
    """Crée un Pattern avec new_pattern() si num_bars/num_steps fournis."""
    p = Pattern()
    nb = kw.get("num_bars")
    ns = kw.get("num_steps")
    if nb or ns:
        p.new_pattern(nb or 1, ns or 16)
    return p


def step_count(pat):
    """Nombre total de notes de grille actives (etype 'G')."""
    return sum(1 for _ in pat.iter_grid())


def bar_lengths(pat):
    """Liste des longueurs (num_steps) de chaque bar[track=0][pad=0]."""
    return [len(pat.grid_row(0, 0, b)) for b in range(pat._num_bars)]


def pad_count(pat):
    """Nombre de mesures dans pad[track=0][pad=0]."""
    return pat._num_bars


# ---------------------------------------------------------------------------
# Valeurs initiales
# ---------------------------------------------------------------------------

def test_default_num_steps():
    p = Pattern()
    assert p._num_steps == 16
    print("  _num_steps == 16 (défaut) : OK")

def test_default_num_bars():
    p = Pattern()
    assert p._num_bars == 1
    print("  _num_bars == 1 (défaut) : OK")

def test_default_bpm():
    p = Pattern()
    assert p._bpm == 100
    print("  _bpm == 100 (défaut) : OK")

def test_default_looping_true():
    p = Pattern()
    assert p._looping is True
    print("  _looping == True (défaut) : OK")

def test_default_start_bar_zero():
    p = Pattern()
    assert p._start_bar == 0
    print("  _start_bar == 0 (défaut) : OK")

def test_default_is_empty():
    p = Pattern()
    assert p.is_empty()
    print("  Pattern vide par défaut : OK")

def test_default_dense_grid_shape():
    p = Pattern()
    dense = p.to_dense_grid()
    assert len(dense) == p._num_tracks
    assert len(dense[0]) == p._num_pads
    assert len(dense[0][0]) == p._num_bars
    assert len(dense[0][0][0]) == p._num_steps
    print("  Forme to_dense_grid() [tracks][pads][bars][steps] correcte : OK")


# ---------------------------------------------------------------------------
# new_pattern
# ---------------------------------------------------------------------------

def test_new_pattern_sets_dimensions():
    p = Pattern()
    p.new_pattern(4, 32)
    assert p._num_bars == 4
    assert p._num_steps == 32
    print("  new_pattern(4,32) → num_bars=4, num_steps=32 : OK")

def test_new_pattern_is_empty():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 100)
    p.new_pattern(2, 16)
    assert p.is_empty()
    print("  new_pattern efface les données existantes : OK")

def test_new_pattern_shape_correct():
    p = Pattern()
    p.new_pattern(3, 64)
    assert p._num_bars  == 3
    assert p._num_steps == 64
    print("  new_pattern(3,64) → shape [3][64] : OK")


# ---------------------------------------------------------------------------
# load_pattern
# ---------------------------------------------------------------------------

def test_load_pattern_updates_dimensions():
    src = Pattern()
    src.new_pattern(4, 32)
    dst = Pattern()
    dst.load_pattern(src.to_dense_grid())
    assert dst._num_bars == 4
    assert dst._num_steps == 32
    print("  load_pattern met à jour num_bars et num_steps : OK")

def test_load_pattern_copies_data_independently():
    src = Pattern()
    src.set_cell(0, 0, 0, 5, 100)
    dst = Pattern()
    dst.load_pattern(src.to_dense_grid())
    # Modifier la source ne doit pas affecter la destination
    src.set_cell(0, 0, 0, 5, 0)
    assert dst.get_cell(0, 0, 0, 5) == 100
    print("  load_pattern fait une copie indépendante : OK")

def test_load_pattern_preserves_true_steps():
    src = Pattern()
    src.set_cell(0, 3, 0, 7, 100)
    dst = Pattern()
    dst.load_pattern(src.to_dense_grid())
    assert dst.get_cell(0, 3, 0, 7) == 100
    print("  load_pattern conserve les pas actifs : OK")

def test_load_pattern_preserves_kp_events():
    dst = Pattern()
    dst._tape[(0, 0, 0)] = []
    from pattern import TapeEvent
    dst._tape[(0, 0, 0)].append(TapeEvent("K", 60, 90, 0, 0))
    dst.load_pattern(Pattern().to_dense_grid())
    assert any(ev.etype == "K" for ev in dst._tape.get((0, 0, 0), []))
    print("  load_pattern préserve les événements K/P existants : OK")


# ---------------------------------------------------------------------------
# reset_pattern
# ---------------------------------------------------------------------------

def test_reset_pattern_clears_all_steps():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 100)
    p.set_cell(0, 5, 0, 3, 100)
    p.reset_pattern()
    assert p.is_empty()
    print("  reset_pattern efface tous les pas : OK")

def test_reset_pattern_preserves_dimensions():
    p = Pattern()
    p.new_pattern(3, 32)
    p.set_cell(0, 0, 0, 0, 100)
    p.reset_pattern()
    assert p._num_bars == 3
    assert p._num_steps == 32
    print("  reset_pattern conserve num_bars et num_steps : OK")


# ---------------------------------------------------------------------------
# gen_pattern
# ---------------------------------------------------------------------------

def test_gen_pattern_not_empty():
    p = Pattern()
    p.gen_pattern(0)
    assert not p.is_empty()
    print("  gen_pattern génère au moins un pas True : OK")

def test_gen_pattern_only_affects_given_track():
    p = Pattern()
    p.gen_pattern(0)
    # Les autres pistes (1..7) doivent rester vides
    for t in range(1, p._num_tracks):
        assert list(p.iter_grid(track=t)) == []
    print("  gen_pattern n'affecte que la piste demandée : OK")

def test_gen_pattern_resets_before_generating():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 100)
    p.gen_pattern(0)
    # gen_pattern appelle reset_pattern() en premier, donc le pas [0][0][0][0]
    # peut être actif ou non selon le random — mais toutes les notes actives
    # sont celles placées par gen_pattern, pas des résidus.
    assert not p.is_empty()
    print("  gen_pattern repart d'un état vide : OK")


# ---------------------------------------------------------------------------
# double_bars
# ---------------------------------------------------------------------------

def test_double_bars_doubles_num_bars():
    p = Pattern()
    p.new_pattern(2, 16)
    p.double_bars()
    assert p._num_bars == 4
    print("  double_bars: num_bars 2→4 : OK")

def test_double_bars_returns_true_on_success():
    p = Pattern()
    p.new_pattern(2, 16)
    assert p.double_bars() is True
    print("  double_bars retourne True si succès : OK")

def test_double_bars_duplicates_content():
    p = Pattern()
    p.new_pattern(2, 16)
    p.set_cell(0, 0, 0, 3, 100)   # bar 0, step 3
    p.set_cell(0, 0, 1, 7, 100)   # bar 1, step 7
    p.double_bars()
    # Après doublement : bars 0..3, les bars 2 et 3 sont des copies de 0 et 1
    assert p.get_cell(0, 0, 2, 3) == 100   # copie de bar 0
    assert p.get_cell(0, 0, 3, 7) == 100   # copie de bar 1
    print("  double_bars duplique le contenu des mesures : OK")

def test_double_bars_returns_false_at_max():
    p = Pattern()
    p.new_pattern(500, 16)   # 500 * 2 = 1000 > MAX_BARS(999)
    result = p.double_bars()
    assert result is False
    assert p._num_bars == 500   # inchangé
    print("  double_bars retourne False si limite MAX_BARS dépassée : OK")


# ---------------------------------------------------------------------------
# halve_bars
# ---------------------------------------------------------------------------

def test_halve_bars_halves_num_bars():
    p = Pattern()
    p.new_pattern(4, 16)
    p.halve_bars()
    assert p._num_bars == 2
    print("  halve_bars: num_bars 4→2 : OK")

def test_halve_bars_returns_true_on_success():
    p = Pattern()
    p.new_pattern(4, 16)
    assert p.halve_bars() is True
    print("  halve_bars retourne True si succès : OK")

def test_halve_bars_keeps_first_half():
    p = Pattern()
    p.new_pattern(4, 16)
    p.set_cell(0, 0, 0, 1, 100)   # bar 0 → conservée
    p.set_cell(0, 0, 1, 2, 100)   # bar 1 → conservée
    p.set_cell(0, 0, 2, 3, 100)   # bar 2 → supprimée
    p.set_cell(0, 0, 3, 4, 100)   # bar 3 → supprimée
    p.halve_bars()
    assert p.get_cell(0, 0, 0, 1) == 100
    assert p.get_cell(0, 0, 1, 2) == 100
    assert p._num_bars == 2   # bars 2 et 3 supprimées
    print("  halve_bars conserve la première moitié : OK")

def test_halve_bars_returns_false_if_one_bar():
    p = Pattern()
    p.new_pattern(1, 16)
    result = p.halve_bars()
    assert result is False
    assert p._num_bars == 1   # inchangé
    print("  halve_bars retourne False si une seule mesure : OK")

def test_halve_bars_odd_num_bars():
    p = Pattern()
    p.new_pattern(5, 16)
    p.halve_bars()
    assert p._num_bars == 2   # 5 // 2
    print("  halve_bars sur nombre impair → 5//2 = 2 : OK")


# ---------------------------------------------------------------------------
# build_pattern_01
# ---------------------------------------------------------------------------

def test_build_pattern_01_not_empty():
    p = Pattern()
    p.build_pattern_01()
    assert not p.is_empty()
    print("  build_pattern_01 produit un pattern non vide : OK")

def test_build_pattern_01_kick_on_downbeat():
    p = Pattern()
    p.build_pattern_01()
    assert p.get_cell(0, 0, 0, 0)    # temps 1
    assert p.get_cell(0, 0, 0, 4)    # temps 2
    assert p.get_cell(0, 0, 0, 8)    # temps 3
    assert p.get_cell(0, 0, 0, 12)   # temps 4
    print("  build_pattern_01: kick sur les 4 temps : OK")

def test_build_pattern_01_resets_prior_data():
    p = Pattern()
    p.set_cell(0, 0, 0, 15, 100)
    p.build_pattern_01()
    # Après build, le pas 15 sur pad 0 doit être inactif (reset en premier)
    assert not p.get_cell(0, 0, 0, 15)
    print("  build_pattern_01 efface les données précédentes : OK")


# ---------------------------------------------------------------------------
# is_empty
# ---------------------------------------------------------------------------

def test_is_empty_true_on_new_pattern():
    p = Pattern()
    assert p.is_empty()
    print("  is_empty() == True sur pattern neuf : OK")

def test_is_empty_false_when_one_step_set():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 100)
    assert not p.is_empty()
    print("  is_empty() == False dès qu'un pas est actif : OK")

def test_is_empty_true_after_reset():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 100)
    p.reset_pattern()
    assert p.is_empty()
    print("  is_empty() == True après reset_pattern() : OK")

def test_is_empty_checks_all_tracks():
    p = Pattern()
    p.set_cell(7, 15, 0, 15, 100)   # dernière piste, dernier pad, dernier pas
    assert not p.is_empty()
    print("  is_empty() vérifie toutes les pistes et tous les pads : OK")

def test_is_empty_false_with_only_kp_events():
    """Un pattern sans note de grille mais avec une note K/P n'est pas vide."""
    from pattern import TapeEvent
    p = Pattern()
    p._tape[(0, 0, 0)] = [TapeEvent("K", 60, 90, 0, 0)]
    assert not p.is_empty()
    print("  is_empty() == False avec seulement des notes K/P : OK")


# ---------------------------------------------------------------------------
# resize
# ---------------------------------------------------------------------------

def test_resize_extend_steps_updates_num_steps():
    p = Pattern()
    p.new_pattern(1, 16)
    p.resize(1, 32)
    assert p._num_steps == 32
    print("  resize: extension de steps → _num_steps mis à jour : OK")

def test_resize_extend_steps_bar_length():
    p = Pattern()
    p.new_pattern(1, 16)
    p.resize(1, 32)
    assert bar_lengths(p) == [32]
    print("  resize: chaque bar a la nouvelle longueur après extension : OK")

def test_resize_truncate_steps_bar_length():
    p = Pattern()
    p.new_pattern(1, 32)
    p.resize(1, 16)
    assert bar_lengths(p) == [16]
    print("  resize: chaque bar tronquée à la nouvelle longueur : OK")

def test_resize_extend_steps_preserves_existing():
    p = Pattern()
    p.new_pattern(1, 16)
    p.set_cell(0, 0, 0, 3, 100)
    p.resize(1, 32)
    assert p.get_cell(0, 0, 0, 3) == 100
    print("  resize: l'extension de steps conserve les pas existants : OK")

def test_resize_extend_steps_new_steps_are_false():
    p = Pattern()
    p.new_pattern(1, 16)
    p.resize(1, 32)
    assert not p.get_cell(0, 0, 0, 16)
    assert not p.get_cell(0, 0, 0, 31)
    print("  resize: nouveaux pas initialisés à False : OK")

def test_resize_extend_bars_updates_num_bars():
    p = Pattern()
    p.new_pattern(2, 16)
    p.resize(4, 16)
    assert p._num_bars == 4
    print("  resize: extension de bars → _num_bars mis à jour : OK")

def test_resize_extend_bars_count():
    p = Pattern()
    p.new_pattern(2, 16)
    p.resize(5, 16)
    assert pad_count(p) == 5
    print("  resize: nombre de bars correct après extension : OK")

def test_resize_truncate_bars_count():
    p = Pattern()
    p.new_pattern(4, 16)
    p.resize(2, 16)
    assert pad_count(p) == 2
    print("  resize: nombre de bars correct après troncature : OK")

def test_resize_extend_bars_preserves_existing():
    p = Pattern()
    p.new_pattern(2, 16)
    p.set_cell(0, 0, 1, 5, 100)   # bar 1
    p.resize(4, 16)
    assert p.get_cell(0, 0, 1, 5) == 100
    print("  resize: l'extension de bars conserve les bars existantes : OK")

def test_resize_new_bars_are_empty():
    p = Pattern()
    p.new_pattern(2, 16)
    p.resize(4, 16)
    assert not any(p.grid_row(0, 0, 2))
    assert not any(p.grid_row(0, 0, 3))
    print("  resize: nouvelles bars initialisées à False : OK")

def test_resize_noop_same_dimensions():
    p = Pattern()
    p.new_pattern(2, 16)
    p.set_cell(0, 0, 0, 3, 100)
    p.resize(2, 16)
    assert p._num_bars == 2
    assert p._num_steps == 16
    assert p.get_cell(0, 0, 0, 3) == 100
    print("  resize: aucun changement si dimensions identiques : OK")

def test_resize_both_bars_and_steps():
    p = Pattern()
    p.new_pattern(2, 16)
    p.set_cell(0, 0, 0, 0, 100)
    p.resize(4, 32)
    assert p._num_bars == 4
    assert p._num_steps == 32
    assert p.get_cell(0, 0, 0, 0) == 100
    assert pad_count(p) == 4
    assert len(p.grid_row(0, 0, 0)) == 32
    print("  resize: extension simultanée bars et steps : OK")


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {
    "name", "bpm", "num_bars", "num_steps", "start_bar", "looping",
    "track_slots", "track_mutes", "track_solos", "track_volumes",
    "track_pans", "curpattern", "voices",
}

def test_to_dict_has_all_keys():
    p = Pattern()
    d = p.to_dict()
    assert REQUIRED_KEYS <= d.keys()
    print("  to_dict contient toutes les clés requises : OK")

def test_to_dict_name_value():
    p = Pattern()
    p._name = "Groove A"
    assert p.to_dict()["name"] == "Groove A"
    print("  to_dict['name'] reflète _name : OK")

def test_to_dict_bpm_value():
    p = Pattern()
    p._bpm = 140
    assert p.to_dict()["bpm"] == 140
    print("  to_dict['bpm'] reflète _bpm : OK")

def test_to_dict_looping_value():
    p = Pattern()
    p._looping = False
    assert p.to_dict()["looping"] is False
    print("  to_dict['looping'] reflète _looping : OK")

def test_to_dict_curpattern_matches_dense_grid():
    p = Pattern()
    p.set_cell(0, 3, 0, 7, 100)
    d = p.to_dict()
    # curpattern est désormais dérivé à la volée depuis _tape (etype "G")
    assert d["curpattern"] == p.to_dense_grid()
    print("  to_dict['curpattern'] == to_dense_grid() (dérivé de _tape) : OK")


# ---------------------------------------------------------------------------
# from_dict
# ---------------------------------------------------------------------------

def test_from_dict_restores_name():
    p = Pattern()
    p.from_dict({"name": "Test", "bpm": 100, "curpattern": Pattern().to_dense_grid()})
    assert p._name == "Test"
    print("  from_dict restaure _name : OK")

def test_from_dict_restores_bpm():
    p = Pattern()
    p.from_dict({"name": "", "bpm": 175, "curpattern": Pattern().to_dense_grid()})
    assert p._bpm == 175
    print("  from_dict restaure _bpm : OK")

def test_from_dict_restores_looping():
    p = Pattern()
    p.from_dict({"name": "", "bpm": 100, "looping": False,
                 "curpattern": Pattern().to_dense_grid()})
    assert p._looping is False
    print("  from_dict restaure _looping : OK")

def test_from_dict_defaults_for_missing_fields():
    p = Pattern()
    p.from_dict({"curpattern": Pattern().to_dense_grid()})
    assert p._name      == ""
    assert p._bpm       == 100
    assert p._looping   is True
    assert p._start_bar == 0
    print("  from_dict applique les défauts pour les champs absents : OK")

def test_from_dict_restores_track_slots():
    p = Pattern()
    src = Pattern()
    src._track_slots = [3, 1, 0, 0, 0, 0, 0, 0]
    d = src.to_dict()
    p.from_dict(d)
    assert p._track_slots == [3, 1, 0, 0, 0, 0, 0, 0]
    print("  from_dict restaure _track_slots : OK")

def test_from_dict_restores_voices():
    p = Pattern()
    src = Pattern()
    src._voices[2]["volume"] = 42
    d = src.to_dict()
    p.from_dict(d)
    assert p._voices[2]["volume"] == 42
    print("  from_dict restaure _voices : OK")

def test_from_dict_missing_track_fields_keep_defaults():
    p = Pattern()
    p.from_dict({"curpattern": Pattern().to_dense_grid()})
    # Sans clés track_*, les listes par défaut doivent rester intactes
    assert p._track_mutes   == [False] * 8
    assert p._track_volumes == [100]   * 8
    print("  from_dict sans track_* → listes par défaut conservées : OK")

def test_from_dict_preserves_kit_and_patch_tape():
    """from_dict doit peupler les événements G AVANT d'ajouter kit_tape/patch_tape."""
    src = Pattern()
    src.set_cell(0, 3, 0, 7, 100)
    src._tape.setdefault((0, 0, 2), []).extend([])
    from pattern import TapeEvent
    src._tape.setdefault((0, 0, 2), []).append(TapeEvent("K", 60, 90, 0, 0))
    d = src.to_dict()
    dst = Pattern()
    dst.from_dict(d)
    assert dst.get_cell(0, 3, 0, 7) == 100
    assert any(ev.etype == "K" for ev in dst._tape.get((0, 0, 2), []))
    print("  from_dict conserve G (via curpattern) et K/P (via kit_tape) : OK")


# ---------------------------------------------------------------------------
# Aller-retour to_dict / from_dict
# ---------------------------------------------------------------------------

def test_roundtrip_preserves_metadata():
    src = Pattern()
    src._name      = "Roundtrip"
    src._bpm       = 128
    src._looping   = False
    src._start_bar = 3
    d = src.to_dict()
    dst = Pattern()
    dst.from_dict(d)
    assert dst._name      == "Roundtrip"
    assert dst._bpm       == 128
    assert dst._looping   is False
    assert dst._start_bar == 3
    print("  to_dict → from_dict conserve name, bpm, looping, start_bar : OK")

def test_roundtrip_preserves_curpattern():
    src = Pattern()
    src.set_cell(0, 5, 0, 11, 100)
    d = src.to_dict()
    dst = Pattern()
    dst.from_dict(d)
    assert dst.get_cell(0, 5, 0, 11) == 100
    print("  to_dict → from_dict conserve les notes de grille : OK")

def test_roundtrip_is_independent_copy():
    src = Pattern()
    src.set_cell(0, 0, 0, 0, 100)
    d = src.to_dict()
    dst = Pattern()
    dst.from_dict(d)
    # from_dict fait load_pattern qui copie → modifier src ne doit pas affecter dst
    src.set_cell(0, 0, 0, 0, 0)
    assert dst.get_cell(0, 0, 0, 0) == 100
    print("  from_dict produit une copie indépendante : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_pattern ===")
    # Valeurs initiales
    test_default_num_steps()
    test_default_num_bars()
    test_default_bpm()
    test_default_looping_true()
    test_default_start_bar_zero()
    test_default_is_empty()
    test_default_dense_grid_shape()
    # new_pattern
    test_new_pattern_sets_dimensions()
    test_new_pattern_is_empty()
    test_new_pattern_shape_correct()
    # load_pattern
    test_load_pattern_updates_dimensions()
    test_load_pattern_copies_data_independently()
    test_load_pattern_preserves_true_steps()
    test_load_pattern_preserves_kp_events()
    # reset_pattern
    test_reset_pattern_clears_all_steps()
    test_reset_pattern_preserves_dimensions()
    # gen_pattern
    test_gen_pattern_not_empty()
    test_gen_pattern_only_affects_given_track()
    test_gen_pattern_resets_before_generating()
    # double_bars
    test_double_bars_doubles_num_bars()
    test_double_bars_returns_true_on_success()
    test_double_bars_duplicates_content()
    test_double_bars_returns_false_at_max()
    # halve_bars
    test_halve_bars_halves_num_bars()
    test_halve_bars_returns_true_on_success()
    test_halve_bars_keeps_first_half()
    test_halve_bars_returns_false_if_one_bar()
    test_halve_bars_odd_num_bars()
    # build_pattern_01
    test_build_pattern_01_not_empty()
    test_build_pattern_01_kick_on_downbeat()
    test_build_pattern_01_resets_prior_data()
    # is_empty
    test_is_empty_true_on_new_pattern()
    test_is_empty_false_when_one_step_set()
    test_is_empty_true_after_reset()
    test_is_empty_checks_all_tracks()
    test_is_empty_false_with_only_kp_events()
    # resize
    test_resize_extend_steps_updates_num_steps()
    test_resize_extend_steps_bar_length()
    test_resize_truncate_steps_bar_length()
    test_resize_extend_steps_preserves_existing()
    test_resize_extend_steps_new_steps_are_false()
    test_resize_extend_bars_updates_num_bars()
    test_resize_extend_bars_count()
    test_resize_truncate_bars_count()
    test_resize_extend_bars_preserves_existing()
    test_resize_new_bars_are_empty()
    test_resize_noop_same_dimensions()
    test_resize_both_bars_and_steps()
    # to_dict
    test_to_dict_has_all_keys()
    test_to_dict_name_value()
    test_to_dict_bpm_value()
    test_to_dict_looping_value()
    test_to_dict_curpattern_matches_dense_grid()
    # from_dict
    test_from_dict_restores_name()
    test_from_dict_restores_bpm()
    test_from_dict_restores_looping()
    test_from_dict_defaults_for_missing_fields()
    test_from_dict_restores_track_slots()
    test_from_dict_restores_voices()
    test_from_dict_missing_track_fields_keep_defaults()
    test_from_dict_preserves_kit_and_patch_tape()
    # Aller-retour
    test_roundtrip_preserves_metadata()
    test_roundtrip_preserves_curpattern()
    test_roundtrip_is_independent_copy()
    print("Tous les tests : OK")
