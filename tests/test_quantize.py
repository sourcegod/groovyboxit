#python3
"""
    File: tests/test_quantize.py
    Tests unitaires de la quantize en Lecture (apply_quant_row,
    apply_quant_to_pattern) et en Enregistrement (record_hit avec
    _quant_in_recording).
    Date: Tue, 19/05/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import patch
from drum_player import DrumPlayer
from pattern import Pattern


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeSoundManager:
    def play_sound(self, pad_idx, vol, pan): pass
    def stop_all(self):                      pass
    def play_metronome(self, beat):          pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T0 = 1000.0   # temps de référence arbitraire pour record_hit

def make_player():
    player = DrumPlayer(sound_manager=FakeSoundManager())
    player.bpm           = 120
    player.step_duration = 60.0 / 120 / 4   # 0.125 s/pas
    return player

def active_steps(player, pad_idx, bar=0):
    return [
        i for i, v in enumerate(
            player._pattern._curpattern[0][pad_idx][bar]
        )
        if v
    ]

def hit_at(player, float_offset):
    """Simule un hit à `float_offset` pas après measure_start."""
    t = T0 + float_offset * player.step_duration
    with patch("time.perf_counter", return_value=t):
        return player.record_hit(0)


# ---------------------------------------------------------------------------
# Quantize en Lecture — apply_quant_row
# ---------------------------------------------------------------------------

def test_quant_row_1_4_places_steps_on_quarter_grid():
    player = make_player()
    player.apply_quant_row(Pattern.QUANT_STEPS.index(4), 0)
    assert active_steps(player, 0) == [0, 4, 8, 12]
    print("  quant_row 1/4 → [0,4,8,12] : OK")

def test_quant_row_1_8_places_steps_on_eighth_grid():
    player = make_player()
    player.apply_quant_row(Pattern.QUANT_STEPS.index(8), 0)
    assert active_steps(player, 0) == [0, 2, 4, 6, 8, 10, 12, 14]
    print("  quant_row 1/8 → [0,2,4,…14] : OK")

def test_quant_row_1_16_fills_every_step():
    player = make_player()
    player.apply_quant_row(Pattern.QUANT_STEPS.index(16), 0)
    assert active_steps(player, 0) == list(range(16))
    print("  quant_row 1/16 → tous les pas : OK")

def test_quant_row_clears_previous_content():
    player = make_player()
    pat = player._pattern._curpattern[0][0][0]
    pat[1] = pat[3] = pat[7] = True
    player.apply_quant_row(Pattern.QUANT_STEPS.index(4), 0)
    assert active_steps(player, 0) == [0, 4, 8, 12]
    print("  quant_row efface le contenu précédent : OK")

def test_quant_row_updates_float_offsets():
    player = make_player()
    player.apply_quant_row(Pattern.QUANT_STEPS.index(4), 0)
    assert player.float_offsets[0] == [0.0, 4.0, 8.0, 12.0]
    print("  quant_row met à jour float_offsets : OK")


# ---------------------------------------------------------------------------
# Quantize en Lecture — apply_quant_to_pattern
# ---------------------------------------------------------------------------

def test_quant_pattern_snaps_2_6_to_1_4_grid():
    # grille 1/4 (0,4,8,12) : le plus proche de 2.6 est 4
    player = make_player()
    player.float_offsets[0] = [2.6]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4))
    steps = active_steps(player, 0)
    assert 4 in steps and 2 not in steps and 3 not in steps
    print("  quant_pattern 1/4 : 2.6 → step 4 : OK")

def test_quant_pattern_snaps_3_4_to_1_8_grid():
    # grille 1/8 (0,2,4,…) : le plus proche de 3.4 est 4
    player = make_player()
    player.float_offsets[0] = [3.4]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(8))
    steps = active_steps(player, 0)
    assert 4 in steps and 3 not in steps
    print("  quant_pattern 1/8 : 3.4 → step 4 : OK")

def test_quant_pattern_clears_old_steps_before_snap():
    player = make_player()
    pat = player._pattern._curpattern[0][0][0]
    pat[3] = True
    player.float_offsets[0] = [3.4]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(8))
    assert not pat[3]
    print("  quant_pattern efface les pas existants avant snap : OK")

def test_quant_pattern_no_offsets_leaves_pad_empty():
    player = make_player()
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4))
    assert active_steps(player, 0) == []
    print("  quant_pattern sans offsets → pad vide : OK")

def test_quant_pattern_none_idx_does_not_modify_pattern():
    player = make_player()
    pat = player._pattern._curpattern[0][0][0]
    pat[3] = True
    player.quant_idx = -1
    player.apply_quant_to_pattern()
    assert pat[3]
    print("  quant_pattern quant_idx=-1 (None) → pattern inchangé : OK")

def test_quant_pattern_snap_in_second_bar():
    # offset 18.4 sur grille 1/4 → point 20 → bar 1, step 4
    player = make_player()
    player._pattern.new_pattern(num_bars=2, num_steps=16)
    player._all_offsets = [
        [[] for _ in range(player._pattern._num_pads)]
        for _ in range(player._pattern._num_tracks)
    ]
    player.float_offsets[0] = [18.4]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4))
    bar1 = player._pattern._curpattern[0][0][1]
    assert bar1[4]
    print("  quant_pattern multi-bar : 18.4 → bar 1, step 4 : OK")


# ---------------------------------------------------------------------------
# Quantize en Enregistrement — record_hit
# ---------------------------------------------------------------------------

def test_rec_quant_disabled_rounds_to_nearest_step():
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = False
    _, step = hit_at(player, 2.6)
    assert step == 3   # round(2.6) = 3
    print("  rec quant OFF : 2.6 → step 3 (round simple) : OK")

def test_rec_quant_1_4_snaps_2_6_to_step_4():
    # quant_size=4 ; round(2.6/4)*4 = 1*4 = 4
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = Pattern.QUANT_STEPS.index(4)
    _, step = hit_at(player, 2.6)
    assert step == 4
    print("  rec quant 1/4 : 2.6 → step 4 : OK")

def test_rec_quant_1_8_snaps_3_4_to_step_4():
    # quant_size=2 ; round(3.4/2)*2 = 2*2 = 4
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = Pattern.QUANT_STEPS.index(8)
    _, step = hit_at(player, 3.4)
    assert step == 4
    print("  rec quant 1/8 : 3.4 → step 4 : OK")

def test_rec_quant_1_16_equals_no_quant():
    # quant_size=1 → identique à round()
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = Pattern.QUANT_STEPS.index(16)
    _, step = hit_at(player, 2.6)
    assert step == 3
    print("  rec quant 1/16 = round() : 2.6 → step 3 : OK")

def test_rec_quant_none_idx_disables_snap():
    # quant_idx=-1 → même si flag actif, pas de snap
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = -1
    _, step = hit_at(player, 2.6)
    assert step == 3
    print("  rec quant quant_idx=-1 (None) → pas de snap : OK")

def test_rec_quant_writes_snapped_step_in_pattern():
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = Pattern.QUANT_STEPS.index(4)
    hit_at(player, 2.6)   # snap → step 4
    assert player._pattern._curpattern[0][0][0][4]
    print("  rec quant écrit step 4 dans le pattern : OK")

def test_rec_quant_does_not_write_raw_step():
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = Pattern.QUANT_STEPS.index(4)
    hit_at(player, 2.6)   # snap → 4, pas 3
    assert not player._pattern._curpattern[0][0][0][3]
    print("  rec quant n'écrit pas le step brut (3) : OK")

def test_rec_quant_stores_snapped_float_offset():
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = Pattern.QUANT_STEPS.index(4)
    hit_at(player, 2.6)   # snap → 4.0
    assert 4.0 in player.float_offsets[0]
    print("  rec quant stocke l'offset snappé (4.0) : OK")

def test_rec_quant_wraps_at_end_of_measure():
    # offset 15.6 ; 1/4 : round(15.6/4)*4 = 4*4 = 16 → %16 = 0
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = Pattern.QUANT_STEPS.index(4)
    bar, step = hit_at(player, 15.6)
    assert step == 0 and bar == 0
    print("  rec quant wrap fin de mesure : 15.6 → step 0 bar 0 : OK")

def test_rec_quant_multi_bar_correct_bar_and_step():
    # offset 17.4 → 1/8 → 18.0 → bar 1, step 2
    player = make_player()
    player._pattern.new_pattern(num_bars=2, num_steps=16)
    player._all_offsets = [
        [[] for _ in range(player._pattern._num_pads)]
        for _ in range(player._pattern._num_tracks)
    ]
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = Pattern.QUANT_STEPS.index(8)
    bar, step = hit_at(player, 17.4)
    assert bar == 1 and step == 2
    print("  rec quant multi-bar : 17.4 → bar 1, step 2 : OK")


# ---------------------------------------------------------------------------
# GRID_RESOLUTIONS et grid_step_size
# ---------------------------------------------------------------------------

def test_grid_step_size_snaps_1_16():
    # GRID_RESOLUTIONS[10] = ("1/16", "snaps", 16) → 16/16 = 1.0
    size = Pattern.grid_step_size(10, num_steps=16)
    assert size == 1.0
    print("  grid_step_size 1/16 (snaps, val=16) → 1.0 step : OK")

def test_grid_step_size_snaps_1_4():
    # GRID_RESOLUTIONS[6] = ("1/4", "snaps", 4) → 16/4 = 4.0
    size = Pattern.grid_step_size(6, num_steps=16)
    assert size == 4.0
    print("  grid_step_size 1/4 (snaps, val=4) → 4.0 steps : OK")

def test_grid_step_size_bars_4_mes():
    # GRID_RESOLUTIONS[0] = ("4 mes.", "bars", 4) → 4*16 = 64.0
    size = Pattern.grid_step_size(0, num_steps=16)
    assert size == 64.0
    print("  grid_step_size 4 mes. (bars, val=4) → 64.0 steps : OK")

def test_grid_step_size_bars_3_mes():
    # GRID_RESOLUTIONS[1] = ("3 mes.", "bars", 3) → 3*16 = 48.0
    size = Pattern.grid_step_size(1, num_steps=16)
    assert size == 48.0
    print("  grid_step_size 3 mes. (bars, val=3) → 48.0 steps : OK")

def test_grid_step_size_bars_2_mes():
    # GRID_RESOLUTIONS[2] = ("2 mes.", "bars", 2) → 2*16 = 32.0
    size = Pattern.grid_step_size(2, num_steps=16)
    assert size == 32.0
    print("  grid_step_size 2 mes. (bars, val=2) → 32.0 steps : OK")

def test_grid_default_idx():
    assert Pattern.GRID_DEFAULT_IDX == 10
    label, kind, val = Pattern.GRID_RESOLUTIONS[10]
    assert label == "1/16" and kind == "snaps" and val == 16
    print("  GRID_DEFAULT_IDX=10 → '1/16' snaps 16 : OK")


# ---------------------------------------------------------------------------
# Valeurs par défaut des nouveaux paramètres dans DrumPlayer
# ---------------------------------------------------------------------------

def test_player_default_quant_params():
    player = make_player()
    assert player._quant_res_idx    == -1
    assert player._quant_force_idx  == 4
    assert player._quant_swing_idx  == 0
    assert player._quant_window_idx == 4
    assert player._quant_starts     == True
    assert player._quant_durations  == False
    assert player._grid_idx         == Pattern.GRID_DEFAULT_IDX
    print("  valeurs par défaut quant_params : OK")


# ---------------------------------------------------------------------------
# Force — G events (apply_quant_to_pattern avec force_idx)
#
# Setup : pos=2.6, grille 1/4 (step_size=4), point le plus proche = 4.0
#   force_idx=0 (0%)  : new_pos=2.6        → round=3
#   force_idx=2 (50%) : new_pos=3.3        → round=3
#   force_idx=3 (75%) : new_pos=3.65       → round=4
#   force_idx=4 (100%): new_pos=4.0        → round=4
# ---------------------------------------------------------------------------

def test_quant_force_0_leaves_note_in_place():
    player = make_player()
    player.float_offsets[0] = [2.6]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), force_idx=0)
    steps = active_steps(player, 0)
    assert 3 in steps and 4 not in steps
    print("  force 0 %  : 2.6 → step 3 (pas de déplacement) : OK")

def test_quant_force_50_partial_snap():
    # 2.6+(4-2.6)*0.5=3.3 → round=3 (toujours en-dessous de 3.5)
    player = make_player()
    player.float_offsets[0] = [2.6]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), force_idx=2)
    steps = active_steps(player, 0)
    assert 3 in steps and 4 not in steps
    print("  force 50 % : 2.6 → step 3 (déplacement partiel, sous 3.5) : OK")

def test_quant_force_75_snaps_close_enough():
    # 2.6+(4-2.6)*0.75=3.65 → round=4
    player = make_player()
    player.float_offsets[0] = [2.6]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), force_idx=3)
    steps = active_steps(player, 0)
    assert 4 in steps and 3 not in steps
    print("  force 75 % : 2.6 → step 4 (déplacement suffisant) : OK")

def test_quant_force_100_regression():
    # Régression : comportement original inchangé
    player = make_player()
    player.float_offsets[0] = [2.6]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), force_idx=4)
    steps = active_steps(player, 0)
    assert 4 in steps and 2 not in steps and 3 not in steps
    print("  force 100% : 2.6 → step 4 (snap complet) : OK")


# ---------------------------------------------------------------------------
# Swing — G events (apply_quant_to_pattern avec swing_idx)
#
# Grille 1/4, 16 steps, swing 100% :
#   swing_shift = 1.0 * 4/2 = 2.0
#   full_grid = [0.0, 6.0, 8.0, 14.0]   (temps impairs décalés de +2)
#   pos=5.0 → sans swing : nearest=4 ; avec swing=100% : nearest=6 → step 6
# ---------------------------------------------------------------------------

def test_quant_swing_0_no_shift():
    # Sans swing : full_grid=[0,4,8,12], pos=5 → nearest=4
    player = make_player()
    player.float_offsets[0] = [5.0]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), swing_idx=0)
    assert 4 in active_steps(player, 0)
    print("  swing 0 %  : pos 5 → step 4 (aucun décalage) : OK")

def test_quant_swing_100_shifts_odd_grid_point():
    # Avec swing=100% : full_grid=[0,6,8,14], pos=5 → nearest=6 → step 6
    player = make_player()
    player.float_offsets[0] = [5.0]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), swing_idx=4)
    assert 6 in active_steps(player, 0)
    assert 4 not in active_steps(player, 0)
    print("  swing 100% : pos 5 → step 6 (point impair décalé) : OK")

def test_quant_swing_100_even_grid_point_unaffected():
    # Point pair (i=0, i=2…) ne bouge pas même avec swing maximal
    # pos=0.2, nearest=0 avec ou sans swing
    player = make_player()
    player.float_offsets[0] = [0.2]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), swing_idx=4)
    assert 0 in active_steps(player, 0)
    print("  swing 100% : pos 0.2 → step 0 (point pair non affecté) : OK")


# ---------------------------------------------------------------------------
# Fenêtre (Window) — G events (apply_quant_to_pattern avec window_idx)
#
# Grille 1/4 : step_size=4, half_step=2
#   window 100% : seuil=2.0 → tous dans la fenêtre
#   window 50%  : seuil=1.0 → pos=1.5 (dist=1.5 > 1.0 → non quantisé)
#                            → pos=3.5 (dist=0.5 ≤ 1.0 → quantisé → step 4)
#   window 0%   : seuil=0.0 → pos=1.0 (dist=1.0 > 0 → non quantisé)
# ---------------------------------------------------------------------------

def test_quant_window_100_quantizes_all():
    # pos=1.5, nearest=0, dist=1.5 ≤ seuil=2.0 → snap vers 0
    player = make_player()
    player.float_offsets[0] = [1.5]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), window_idx=4)
    assert 0 in active_steps(player, 0)
    print("  fenêtre 100% : pos 1.5 → step 0 (dans la fenêtre) : OK")

def test_quant_window_50_leaves_far_note():
    # pos=1.5, nearest=0, dist=1.5 > seuil=1.0 → non quantisé → round(1.5)=2
    player = make_player()
    player.float_offsets[0] = [1.5]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), window_idx=2)
    steps = active_steps(player, 0)
    assert 2 in steps and 0 not in steps
    print("  fenêtre 50 % : pos 1.5 (trop loin) → step 2 (inchangé) : OK")

def test_quant_window_50_quantizes_close_note():
    # pos=3.5, nearest=4, dist=0.5 ≤ seuil=1.0 → snap vers 4
    player = make_player()
    player.float_offsets[0] = [3.5]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), window_idx=2)
    assert 4 in active_steps(player, 0)
    print("  fenêtre 50 % : pos 3.5 (proche) → step 4 (quantisé) : OK")

def test_quant_window_0_leaves_off_grid_note():
    # pos=1.0, nearest=0, dist=1.0 > seuil=0.0 → non quantisé → step 1
    player = make_player()
    player.float_offsets[0] = [1.0]
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), window_idx=0)
    steps = active_steps(player, 0)
    assert 1 in steps and 0 not in steps
    print("  fenêtre 0 %  : pos 1.0 hors grille → step 1 (non quantisé) : OK")


# ---------------------------------------------------------------------------
# Helpers pour les tests Tape K/P
# ---------------------------------------------------------------------------

from pattern import TapeEvent as _TapeEvent

def _add_K(player, bar, step, dur=500):
    """Ajoute un TapeEvent K sur la piste 0."""
    key = (0, bar, step)
    player._pattern._tape.setdefault(key, []).append(
        _TapeEvent("K", 0, 100, dur, 0)
    )

def _tape_pos(player):
    """Retourne les positions (bar, step) des événements sur la piste 0."""
    return {(b, s) for (t, b, s) in player._pattern._tape if t == 0}


# ---------------------------------------------------------------------------
# Tape K/P — quant_starts
# ---------------------------------------------------------------------------

def test_quant_tape_starts_snaps_position():
    # K event step=3, grille 1/4, force=100% → snap vers step 4
    player = make_player()
    _add_K(player, 0, 3, dur=500)
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4),
                                   quant_starts=True, quant_durations=False)
    pos = _tape_pos(player)
    assert (0, 4) in pos and (0, 3) not in pos
    print("  tape quant_starts=True : step 3 → step 4 : OK")

def test_quant_tape_starts_false_leaves_position():
    # quant_starts=False → position inchangée (step 3 reste en place)
    player = make_player()
    _add_K(player, 0, 3, dur=500)
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4),
                                   quant_starts=False, quant_durations=True)
    pos = _tape_pos(player)
    assert (0, 3) in pos and (0, 4) not in pos
    print("  tape quant_starts=False : step 3 reste en place : OK")


# ---------------------------------------------------------------------------
# Tape K/P — quant_durations
#
# Setup : bpm=120, num_steps=16, num_beats=4
#   steps_per_beat=4, ms_per_step=125ms
#   dur=250ms → dur_steps=2.0, step_size=4.0
#   dur_grid=[4.0,8.0,…], nearest(2.0)=4.0 → n_dur=4*125=500ms
# ---------------------------------------------------------------------------

def test_quant_tape_durations_snaps_duration():
    player = make_player()
    player.bpm = 120
    _add_K(player, 0, 0, dur=250)
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4),
                                   quant_starts=False, quant_durations=True)
    evs = player._pattern._tape.get((0, 0, 0), [])
    assert evs and evs[0].dur == 500
    print("  tape quant_durations=True : dur 250ms → 500ms : OK")

def test_quant_tape_durations_false_leaves_duration():
    player = make_player()
    player.bpm = 120
    _add_K(player, 0, 0, dur=250)
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4),
                                   quant_starts=True, quant_durations=False)
    # position snappée (step 0 → step 0, nearest grid), durée inchangée
    evs = []
    for (t, b, s), lst in player._pattern._tape.items():
        if t == 0:
            evs.extend(lst)
    assert evs and evs[0].dur == 250
    print("  tape quant_durations=False : dur 250ms inchangée : OK")


# ---------------------------------------------------------------------------
# Tape K/P — Force
# ---------------------------------------------------------------------------

def test_quant_tape_force_100_snaps():
    # K event step=3, force=100% → step 4
    player = make_player()
    _add_K(player, 0, 3)
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), force_idx=4)
    pos = _tape_pos(player)
    assert (0, 4) in pos
    print("  tape force 100% : step 3 → step 4 : OK")

def test_quant_tape_force_0_leaves_in_place():
    # K event step=3, force=0% : pos=3.0, nearest=4, new_pos=3.0 → step 3
    player = make_player()
    _add_K(player, 0, 3)
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4), force_idx=0)
    pos = _tape_pos(player)
    assert (0, 3) in pos and (0, 4) not in pos
    print("  tape force 0 %  : step 3 reste en place : OK")


# ---------------------------------------------------------------------------
# Tape K/P — Fenêtre
#
# Grille 1/4 : step_size=4, half_step=2, window 50% → seuil=1.0
#   K step=1 : pos=1.0, nearest=0, dist=1.0 > 1.0 → NON quantisé (condition >)
#   K step=3 : pos=3.0, nearest=4, dist=1.0 ≤ 1.0 → quantisé → step 4
# ---------------------------------------------------------------------------

def test_quant_tape_window_50_leaves_far_note():
    # K step=2 : pos=2.0, nearest=0 (dist=2.0 > seuil=1.0) → non quantisé
    player = make_player()
    _add_K(player, 0, 2)
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4),
                                   force_idx=4, window_idx=2)
    pos = _tape_pos(player)
    assert (0, 2) in pos and (0, 0) not in pos
    print("  tape fenêtre 50% : step 2 (dist>seuil) reste en place : OK")

def test_quant_tape_window_50_quantizes_close_note():
    # dist=1.0 ≤ seuil=1.0 → quantisé → step 4
    player = make_player()
    _add_K(player, 0, 3)
    player.apply_quant_to_pattern(Pattern.QUANT_STEPS.index(4),
                                   force_idx=4, window_idx=2)
    pos = _tape_pos(player)
    assert (0, 4) in pos and (0, 3) not in pos
    print("  tape fenêtre 50% : step 3 (dist≤seuil) → step 4 : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_quantize ===")
    # Quantize en Lecture — apply_quant_row
    test_quant_row_1_4_places_steps_on_quarter_grid()
    test_quant_row_1_8_places_steps_on_eighth_grid()
    test_quant_row_1_16_fills_every_step()
    test_quant_row_clears_previous_content()
    test_quant_row_updates_float_offsets()
    # Quantize en Lecture — apply_quant_to_pattern
    test_quant_pattern_snaps_2_6_to_1_4_grid()
    test_quant_pattern_snaps_3_4_to_1_8_grid()
    test_quant_pattern_clears_old_steps_before_snap()
    test_quant_pattern_no_offsets_leaves_pad_empty()
    test_quant_pattern_none_idx_does_not_modify_pattern()
    test_quant_pattern_snap_in_second_bar()
    # Quantize en Enregistrement — record_hit
    test_rec_quant_disabled_rounds_to_nearest_step()
    test_rec_quant_1_4_snaps_2_6_to_step_4()
    test_rec_quant_1_8_snaps_3_4_to_step_4()
    test_rec_quant_1_16_equals_no_quant()
    test_rec_quant_none_idx_disables_snap()
    test_rec_quant_writes_snapped_step_in_pattern()
    test_rec_quant_does_not_write_raw_step()
    test_rec_quant_stores_snapped_float_offset()
    test_rec_quant_wraps_at_end_of_measure()
    test_rec_quant_multi_bar_correct_bar_and_step()
    # GRID_RESOLUTIONS et grid_step_size
    test_grid_step_size_snaps_1_16()
    test_grid_step_size_snaps_1_4()
    test_grid_step_size_bars_4_mes()
    test_grid_step_size_bars_3_mes()
    test_grid_step_size_bars_2_mes()
    test_grid_default_idx()
    # Valeurs par défaut
    test_player_default_quant_params()
    # Force — G events
    test_quant_force_0_leaves_note_in_place()
    test_quant_force_50_partial_snap()
    test_quant_force_75_snaps_close_enough()
    test_quant_force_100_regression()
    # Swing — G events
    test_quant_swing_0_no_shift()
    test_quant_swing_100_shifts_odd_grid_point()
    test_quant_swing_100_even_grid_point_unaffected()
    # Fenêtre — G events
    test_quant_window_100_quantizes_all()
    test_quant_window_50_leaves_far_note()
    test_quant_window_50_quantizes_close_note()
    test_quant_window_0_leaves_off_grid_note()
    # Tape K/P — quant_starts
    test_quant_tape_starts_snaps_position()
    test_quant_tape_starts_false_leaves_position()
    # Tape K/P — quant_durations
    test_quant_tape_durations_snaps_duration()
    test_quant_tape_durations_false_leaves_duration()
    # Tape K/P — force
    test_quant_tape_force_100_snaps()
    test_quant_tape_force_0_leaves_in_place()
    # Tape K/P — fenêtre
    test_quant_tape_window_50_leaves_far_note()
    test_quant_tape_window_50_quantizes_close_note()
    print("Tous les tests : OK")
