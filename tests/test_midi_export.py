#python3
"""
    File: tests/test_midi_export.py
    Tests du module d'export MIDI (Phase 7 étape 10i1, docs/DESIGN.md § 10a1
    D4, D6, D7, D9) : fichier relu par mido — en-tête type 1 / PPQ 480,
    piste conductor, une piste SMF par piste non vide, canaux, notes GRID
    (synthé, kit), KIT, PATCH, vélocités, durées par défaut, conversions de
    temps, chevauchements, ordre à tick égal, CC/PGM/BEND, fin de piste ;
    notes des pads et conversion GM des notes de kit (Phase 7 étape 11g1,
    docs/DESIGN.md § 11a1 D1, D4, D5).
    Le Program Change, le volume et le pan ont leurs propres tests
    (test_gm_program.py, test_midi_export_mix.py).
    Date: Wed, 21/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mido

from pattern import (Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH,
                     ETYPE_CC, ETYPE_PGM, ETYPE_BEND)
from midi.midi_export import build_pattern_midi, export_pattern, PPQ, PATCH_DEFAULT_MS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SYNTH_NOTES = [60 + i for i in range(16)]


def _pattern(num_bars=1, num_steps=16):
    p = Pattern()
    p.new_pattern(num_bars, num_steps)
    return p

def _add(p, track, etype, time_val, payload, dur=0, channel=0):
    p._tape[track].append(TapeEvent(etype, dur=dur, channel=channel, payload=payload, time=time_val))

def _build(p, *, bpm=120, channels=None, is_synth=None, names=None,
           kit_base=36, voice_ms=None, name="Pattern_01", pad_notes=None,
           gm_map=None, unmapped=None):
    n = p._num_tracks
    return build_pattern_midi(
        p, name=name, bpm=bpm,
        track_channels=channels or [Pattern.default_channel(t) for t in range(n)],
        track_is_synth=is_synth if is_synth is not None else [True] * n,
        track_names=names or [""] * n,
        kit_pad_notes=pad_notes or [kit_base + i for i in range(16)],
        synth_grid_notes=SYNTH_NOTES, voice_durations=voice_ms or [500] * 16,
        kit_gm_map=gm_map, unmapped=unmapped)

def _abs(track):
    """[(tick absolu, message)] d'une piste mido."""
    out, now = [], 0
    for m in track:
        now += m.time
        out.append((now, m))
    return out

def _notes(track):
    """[(début, fin, note, vélocité, canal)] reconstruits depuis la piste."""
    on, out = {}, []
    for at, m in _abs(track):
        if m.type == "note_on":
            on[m.note] = (at, m.velocity, m.channel)
        elif m.type == "note_off":
            start, vel, ch = on.pop(m.note)
            out.append((start, at, m.note, vel, ch))
    assert not on, "note_on sans note_off"
    return sorted(out)

def _ms_ticks(ms, bpm=120):
    return round(ms / 1000.0 * bpm / 60.0 * PPQ)


# ---------------------------------------------------------------------------
# Fichier et piste conductor (D4)
# ---------------------------------------------------------------------------

def test_file_type_1_ppq_480_written_and_reread(tmp_path):
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 100}, dur=250)
    path = str(tmp_path / "p.mid")
    export_pattern(path, p, name="P", bpm=120,
                   track_channels=list(range(16)), track_is_synth=[True] * 16,
                   track_names=[""] * 16, kit_pad_notes=list(range(36, 52)),
                   synth_grid_notes=SYNTH_NOTES, voice_durations=[500] * 16)
    mid = mido.MidiFile(path)
    assert mid.type == 1 and mid.ticks_per_beat == PPQ == 480
    assert len(mid.tracks) == 2
    print("  fichier écrit et relu : type 1, 480 ticks par noire : OK")

def test_conductor_name_tempo_signature_end():
    p = _pattern(num_bars=2)
    mid = _build(p, bpm=100, name="Groove")
    cond = _abs(mid.tracks[0])
    kinds = [m.type for _, m in cond]
    assert kinds == ["track_name", "set_tempo", "time_signature", "end_of_track"]
    assert cond[0][1].name == "Groove"
    assert cond[1][1].tempo == mido.bpm2tempo(100)
    assert (cond[2][1].numerator, cond[2][1].denominator) == (4, 4)
    assert cond[3][0] == 2 * 4 * PPQ                 # fin : 2 mesures de 4 temps
    print("  conductor : nom, tempo, signature 4/4, fin à la fin du pattern : OK")

def test_empty_pattern_has_only_conductor():
    mid = _build(_pattern())
    assert len(mid.tracks) == 1
    print("  pattern vide : seulement la piste conductor : OK")

def test_one_smf_track_per_non_empty_track_with_names():
    p = _pattern()
    _add(p, 2, ETYPE_PATCH, 0.0, {"note": 60, "vel": 100})
    _add(p, 11, ETYPE_PATCH, 0.0, {"note": 62, "vel": 100})
    names = [""] * 16
    names[2] = "Piano 1"
    mid = _build(p, names=names)
    assert [tr.name for tr in mid.tracks[1:]] == ["Piano 1", "Track 12"]
    print("  une piste SMF par piste non vide, nom ou « Track NN » : OK")

def test_track_end_at_pattern_end_or_last_note_off():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 100}, dur=100)
    _add(p, 1, ETYPE_PATCH, 15.0, {"note": 60, "vel": 100}, dur=2000)   # déborde
    mid = _build(p)
    assert _abs(mid.tracks[1])[-1] == (4 * PPQ, mid.tracks[1][-1])
    end2 = _abs(mid.tracks[2])[-1][0]
    assert end2 == 15 * PPQ // 4 + _ms_ticks(2000)
    assert mid.tracks[2][-1].type == "end_of_track"
    print("  fin de piste : fin du pattern, ou dernier note-off s'il déborde : OK")


# ---------------------------------------------------------------------------
# Canaux et notes (D5, D6)
# ---------------------------------------------------------------------------

def test_every_event_on_track_channel_not_ev_channel():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 100}, channel=5)
    _add(p, 0, ETYPE_CC, 0.0, {"cc_num": 1, "value": 64}, channel=5)
    _add(p, 0, ETYPE_BEND, 0.0, {"value": 100}, channel=5)
    _add(p, 0, ETYPE_KIT, 4.0, {"note": 38, "vel": 100}, channel=5)
    channels = [0] * 16
    channels[0] = 6
    mid = _build(p, channels=channels)
    chans = {m.channel for m in mid.tracks[1] if hasattr(m, "channel")}
    assert chans == {6}
    print("  tous les événements sur le canal de la piste (ev.channel ignoré) : OK")

def test_grid_note_synth_uses_scale_notes_kit_uses_pad_notes():
    p = _pattern()
    _add(p, 0, ETYPE_GRID, 0.0, {"pad": 3, "vel": 100})
    _add(p, 1, ETYPE_GRID, 0.0, {"pad": 3, "vel": 100})
    is_synth = [True] * 16
    is_synth[1] = False
    mid = _build(p, is_synth=is_synth, kit_base=40)
    assert _notes(mid.tracks[1])[0][2] == SYNTH_NOTES[3]
    assert _notes(mid.tracks[2])[0][2] == 43
    print("  GRID : gamme du router (synthé), note du pad (kit) : OK")

def test_kit_and_patch_use_payload_note():
    p = _pattern()
    _add(p, 0, ETYPE_KIT, 0.0, {"note": 38, "vel": 90})
    _add(p, 0, ETYPE_PATCH, 4.0, {"note": 67, "vel": 80}, dur=100)
    assert [n[2] for n in _notes(_build(p).tracks[1])] == [38, 67]
    print("  KIT et PATCH : note du payload : OK")

def test_velocity_clamped_to_1_127():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 0}, dur=100)
    _add(p, 0, ETYPE_PATCH, 4.0, {"note": 61, "vel": 200}, dur=100)
    assert [n[3] for n in _notes(_build(p).tracks[1])] == [1, 127]
    print("  vélocités bornées à 1..127 (0 vaudrait note-off) : OK")


# ---------------------------------------------------------------------------
# Durées (D6)
# ---------------------------------------------------------------------------

def test_grid_duration_own_or_voice():
    p = _pattern()
    _add(p, 0, ETYPE_GRID, 0.0, {"pad": 2, "vel": 100})             # durée de la voix
    _add(p, 0, ETYPE_GRID, 8.0, {"pad": 5, "vel": 100}, dur=250)    # durée propre
    voice = [500] * 16
    voice[2] = 1000
    n = _notes(_build(p, voice_ms=voice).tracks[1])
    assert n[0][1] - n[0][0] == _ms_ticks(1000)
    assert n[1][1] - n[1][0] == _ms_ticks(250)
    print("  GRID : dur propre, sinon durée de la voix du pad : OK")

def test_patch_default_duration_and_kit_one_step():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 100})          # dur 0
    _add(p, 0, ETYPE_KIT, 8.0, {"note": 38, "vel": 100})
    n = _notes(_build(p).tracks[1])
    assert n[0][1] - n[0][0] == _ms_ticks(PATCH_DEFAULT_MS) == 480
    assert n[1][1] - n[1][0] == PPQ // 4                            # un pas à 16 pas
    print("  PATCH sans dur : 500 ms ; KIT : un pas : OK")

def test_duration_depends_on_bpm_and_is_at_least_one_tick():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 100}, dur=500)
    _add(p, 0, ETYPE_PATCH, 4.0, {"note": 61, "vel": 100}, dur=0.1)
    n = _notes(_build(p, bpm=60).tracks[1])
    assert n[0][1] - n[0][0] == 240                                 # 0,5 s à 60 BPM
    assert n[1][1] - n[1][0] == 1
    print("  durée en ticks selon le BPM, au moins 1 tick : OK")


# ---------------------------------------------------------------------------
# Temps (D1 de 10b1, D6)
# ---------------------------------------------------------------------------

def test_time_conversion_16_and_32_steps():
    for steps, step_ticks in ((16, PPQ // 4), (32, PPQ // 8)):
        p = _pattern(num_steps=steps)
        _add(p, 0, ETYPE_KIT, 3.0, {"note": 38, "vel": 100})
        _add(p, 0, ETYPE_KIT, steps + 0.5, {"note": 40, "vel": 100})     # mesure 2
        starts = [n[0] for n in _notes(_build(p).tracks[1])]
        assert starts == [3 * step_ticks, round((steps + 0.5) * step_ticks)], steps
    print("  temps : pas = PPQ·4/num_steps (16 et 32 pas), temps flottant arrondi : OK")


# ---------------------------------------------------------------------------
# Chevauchements (D6) et ordre à tick égal (D7)
# ---------------------------------------------------------------------------

def test_overlapping_same_note_cut_at_next_note_on():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 100}, dur=1000)
    _add(p, 0, ETYPE_PATCH, 2.0, {"note": 60, "vel": 90}, dur=100)
    n = _notes(_build(p).tracks[1])
    assert n[0][:2] == (0, 2 * PPQ // 4)
    assert n[1][0] == 2 * PPQ // 4
    print("  même note rejouée avant son note-off : la première est coupée : OK")

def test_duplicate_note_same_tick_written_once():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 4.0, {"note": 60, "vel": 100}, dur=100)
    _add(p, 0, ETYPE_KIT, 4.0, {"note": 60, "vel": 80})
    assert len(_notes(_build(p).tracks[1])) == 1
    print("  même note deux fois au même tick : écrite une seule fois : OK")

def test_order_at_same_tick():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 50, "vel": 100}, dur=_ms(4))  # finit au tick 480
    _add(p, 0, ETYPE_PATCH, 4.0, {"note": 60, "vel": 100}, dur=100)
    _add(p, 0, ETYPE_BEND, 4.0, {"value": 500})
    _add(p, 0, ETYPE_CC, 4.0, {"cc_num": 1, "value": 10})
    _add(p, 0, ETYPE_PGM, 4.0, {"program": 5})
    at_480 = [m.type for at, m in _abs(_build(p).tracks[1]) if at == PPQ]
    assert at_480 == ["note_off", "program_change", "control_change", "pitchwheel", "note_on"]
    print("  tick égal : note-off, PGM, CC, bend, note-on : OK")

def _ms(steps, bpm=120):
    """Durée en ms de `steps` pas à 16 pas par mesure."""
    return steps * 60000.0 / bpm / 4

def test_two_bends_same_tick_keep_tape_order():
    """Le dernier dans _tape l'emporte, comme Pattern._bend_state_at."""
    p = _pattern()
    _add(p, 0, ETYPE_BEND, 4.0, {"value": 3000})
    _add(p, 0, ETYPE_BEND, 4.0, {"value": -2000})
    bends = [m.pitch for m in _build(p).tracks[1] if m.type == "pitchwheel"]
    assert bends == [3000, -2000]
    assert p._bend_state_at(0, 4.0) == -2000
    print("  deux bends au même tick : ordre de _tape, le dernier l'emporte : OK")


# ---------------------------------------------------------------------------
# CC / PGM / BEND (D4)
# ---------------------------------------------------------------------------

def test_cc_pgm_bend_values_and_clamps():
    p = _pattern()
    _add(p, 0, ETYPE_CC, 1.0, {"cc_num": 64, "value": 127})
    _add(p, 0, ETYPE_CC, 2.0, {"cc_num": 200, "value": -5})
    _add(p, 0, ETYPE_PGM, 3.0, {"program": 300})
    _add(p, 0, ETYPE_CC, 4.0, {"cc_num": -3, "value": 200})
    _add(p, 0, ETYPE_BEND, 5.0, {"value": 9000})
    _add(p, 0, ETYPE_BEND, 6.0, {"value": -9000})
    msgs = [(at, m) for at, m in _abs(_build(p).tracks[1]) if m.type != "track_name"
            and m.type != "end_of_track"]
    step = PPQ // 4
    assert [(at, m.type) for at, m in msgs] == [
        (step, "control_change"), (2 * step, "control_change"), (3 * step, "program_change"),
        (4 * step, "control_change"), (5 * step, "pitchwheel"), (6 * step, "pitchwheel")]
    m = [x for _, x in msgs]
    assert (m[0].control, m[0].value) == (64, 127)
    assert (m[1].control, m[1].value) == (127, 0)
    assert m[2].program == 127
    assert (m[3].control, m[3].value) == (0, 127)
    assert (m[4].pitch, m[5].pitch) == (8191, -8192)
    print("  CC, PGM et bend : valeurs, temps et bornes : OK")


# ---------------------------------------------------------------------------
# Notes des pads et conversion GM des notes de kit (Phase 7 étape 11g1,
# docs/DESIGN.md § 11a1 D1, D4, D5)
# ---------------------------------------------------------------------------

# Pads de la TR-707 : notes 35 à 49, puis le pad 16 sur 51 (kit_base + 15)
TR_707_PAD_NOTES = list(range(35, 50)) + [51]
TR_707_GM = {35: 35, 36: 36, 37: 37, 38: 38, 39: 39, 40: 40, 41: 41, 42: 42,
             43: 47, 44: 46, 45: 50, 46: 49, 47: 51, 48: 54, 49: 56}
KIT_TRACKS = [False] * 16

def _note_list(track):
    return [n[2] for n in _notes(track)]

def test_grid_kit_note_is_pad_note_not_base_plus_pad():
    """Bug D1 : le pad 14 (Tambourine, note 48) n'est plus écrit 36 + 13."""
    p = _pattern()
    _add(p, 0, ETYPE_GRID, 0.0, {"pad": 0, "vel": 100})
    _add(p, 0, ETYPE_GRID, 4.0, {"pad": 13, "vel": 100})
    _add(p, 0, ETYPE_GRID, 8.0, {"pad": 15, "vel": 100})
    mid = _build(p, is_synth=KIT_TRACKS, pad_notes=TR_707_PAD_NOTES)
    assert _note_list(mid.tracks[1]) == [35, 48, 51]
    print("  GRID kit : note du son du pad, pas kit_base + pad : OK")

def test_grid_kit_converted_to_gm():
    p = _pattern()
    for i, pad in enumerate((7, 9, 11, 13, 14)):
        _add(p, 0, ETYPE_GRID, float(i * 2), {"pad": pad, "vel": 100})
    mid = _build(p, is_synth=KIT_TRACKS, pad_notes=TR_707_PAD_NOTES, gm_map=TR_707_GM)
    # HH Closed, HH Open, Crash, Tambourine, Cowbell
    assert _note_list(mid.tracks[1]) == [42, 46, 49, 54, 56]
    print("  GRID kit : notes converties en GM : OK")

def test_kit_events_converted_on_any_track():
    """D5 : la note d'un KIT est une note du kit, même sur une piste synthé."""
    p = _pattern()
    _add(p, 0, ETYPE_KIT, 0.0, {"note": 49, "vel": 100})
    _add(p, 1, ETYPE_KIT, 0.0, {"note": 44, "vel": 100})
    is_synth = [False, True] + [False] * 14
    mid = _build(p, is_synth=is_synth, gm_map=TR_707_GM)
    assert _note_list(mid.tracks[1]) == [56]
    assert _note_list(mid.tracks[2]) == [46]
    print("  KIT : converti en GM sur piste kit comme sur piste synthé : OK")

def test_patch_and_synth_grid_not_converted():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 49, "vel": 100}, dur=100)
    _add(p, 0, ETYPE_GRID, 4.0, {"pad": 3, "vel": 100})
    gm_map = {49: 56, SYNTH_NOTES[3]: 35}
    unmapped = set()
    mid = _build(p, gm_map=gm_map, unmapped=unmapped)
    assert _note_list(mid.tracks[1]) == [49, SYNTH_NOTES[3]]
    assert unmapped == set()
    print("  PATCH et GRID synthé : jamais convertis ni signalés : OK")

def test_no_gm_map_writes_kit_notes_as_is():
    p = _pattern()
    _add(p, 0, ETYPE_GRID, 0.0, {"pad": 14, "vel": 100})
    _add(p, 0, ETYPE_KIT, 4.0, {"note": 49, "vel": 100})
    unmapped = set()
    mid = _build(p, is_synth=KIT_TRACKS, pad_notes=TR_707_PAD_NOTES, unmapped=unmapped)
    assert _note_list(mid.tracks[1]) == [49, 49]
    assert unmapped == set()
    print("  kit_gm_map=None : notes de kit telles quelles, rien de signalé : OK")

def test_unmapped_kit_notes_kept_and_collected():
    """D4 : sans correspondance, la note du kit est gardée et signalée."""
    p = _pattern()
    _add(p, 0, ETYPE_GRID, 0.0, {"pad": 15, "vel": 100})     # note 51, absente
    _add(p, 0, ETYPE_GRID, 4.0, {"pad": 15, "vel": 100})     # même note : un seul
    _add(p, 0, ETYPE_KIT, 8.0, {"note": 90, "vel": 100})     # absente
    _add(p, 0, ETYPE_KIT, 12.0, {"note": 49, "vel": 100})    # convertie
    unmapped = set()
    mid = _build(p, is_synth=KIT_TRACKS, pad_notes=TR_707_PAD_NOTES,
                 gm_map=TR_707_GM, unmapped=unmapped)
    assert _note_list(mid.tracks[1]) == [51, 51, 90, 56]
    assert unmapped == {51, 90}
    print("  sans correspondance GM : note gardée, ajoutée à unmapped : OK")

def test_unmapped_none_is_accepted():
    p = _pattern()
    _add(p, 0, ETYPE_KIT, 0.0, {"note": 90, "vel": 100})
    mid = _build(p, is_synth=KIT_TRACKS, gm_map=TR_707_GM, unmapped=None)
    assert _note_list(mid.tracks[1]) == [90]
    print("  unmapped=None : rien à remplir, pas d'erreur : OK")

def test_patch_skipped_on_kit_track_not_collected():
    """Les PATCH d'une piste sans synthé ne sont pas exportés (10h5) : ni
    convertis ni signalés."""
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 90, "vel": 100}, dur=100)
    unmapped = set()
    mid = _build(p, is_synth=KIT_TRACKS, gm_map=TR_707_GM, unmapped=unmapped)
    assert _note_list(mid.tracks[1]) == [] and unmapped == set()
    print("  PATCH omis sur piste kit : pas signalé : OK")

def test_overlap_rule_applies_after_conversion():
    """Deux notes de kit différentes converties vers la même note GM au même
    tick : un seul note-on (doublon ignoré, D6)."""
    p = _pattern()
    _add(p, 0, ETYPE_KIT, 0.0, {"note": 46, "vel": 100})
    _add(p, 0, ETYPE_KIT, 0.0, {"note": 60, "vel": 100})
    mid = _build(p, is_synth=KIT_TRACKS, gm_map={46: 49, 60: 49})
    assert _note_list(mid.tracks[1]) == [49]
    print("  chevauchements : appliqués aux notes déjà converties : OK")

def test_export_pattern_passes_unmapped(tmp_path):
    p = _pattern()
    _add(p, 0, ETYPE_KIT, 0.0, {"note": 90, "vel": 100})
    _add(p, 0, ETYPE_KIT, 4.0, {"note": 49, "vel": 100})
    unmapped = set()
    path = str(tmp_path / "k.mid")
    export_pattern(path, p, name="P", bpm=120, track_channels=[9] * 16,
                   track_is_synth=KIT_TRACKS, track_names=[""] * 16,
                   kit_pad_notes=TR_707_PAD_NOTES, synth_grid_notes=SYNTH_NOTES,
                   voice_durations=[500] * 16, kit_gm_map=TR_707_GM,
                   unmapped=unmapped)
    assert unmapped == {90}
    assert _note_list(mido.MidiFile(path).tracks[1]) == [90, 56]
    print("  export_pattern : unmapped transmis, fichier converti : OK")
