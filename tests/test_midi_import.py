#python3
"""
    File: tests/test_midi_import.py
    Tests du module d'import MIDI (Phase 7 étape 18c1, docs/DESIGN.md
    § 18a1 I4, I6 à I10) : fichiers construits avec mido — type 2 refusé,
    nom du pattern et des pistes, tempo et changements, signature, PPQ,
    longueur, choix du nombre de pas et arrondi des notes, durées en ms,
    appariement des notes, notes non fermées, découpage par canal, type 0,
    fusion au-delà de 16 pistes, entête à 1.1.1, volume / pan de piste,
    CC / Pitch Bend / Program Change en temps flottant, messages ignorés,
    compte rendu, aller-retour export → import, lecture d'un fichier abîmé.
    Date: Thu, 29/10/2026
    Author: Coolbrother
"""
import sys
import os
import struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mido
import pytest

from pattern import (Pattern, TapeEvent, bank_header, ETYPE_PATCH, ETYPE_CC,
                     ETYPE_PGM, ETYPE_BEND)
from midi.midi_export import build_pattern_midi
from midi.midi_import import (build_pattern_from_midi, import_pattern,
                              ImportReport, DEFAULT_BPM)

PPQ = 480
BAR = PPQ * 4


# ---------------------------------------------------------------------------
# Construction des fichiers


def _track(events, name=None, end=None):
    """Piste SMF depuis [(tick absolu, message)] ; end = tick de fin de piste."""
    track = mido.MidiTrack()
    if name is not None:
        track.append(mido.MetaMessage("track_name", name=name, time=0))
    now = 0
    for at, msg in sorted(events, key=lambda e: e[0]):
        track.append(msg.copy(time=at - now))
        now = at
    track.append(mido.MetaMessage("end_of_track", time=max(0, (end or now) - now)))
    return track


def _mid(*tracks, type=1, ppq=PPQ, conductor=None):
    """MidiFile ; conductor = liste de métas au tick 0 (piste 0 sans canal)."""
    mid = mido.MidiFile(type=type, ticks_per_beat=ppq)
    if conductor is not None:
        mid.tracks.append(_track([(0, m) for m in conductor]))
    mid.tracks.extend(tracks)
    return mid


def _note(start, stop, note=60, vel=100, ch=0):
    return [(start, mido.Message("note_on", channel=ch, note=note, velocity=vel)),
            (stop, mido.Message("note_off", channel=ch, note=note, velocity=0))]


def _cc(tick, control, value, ch=0):
    return (tick, mido.Message("control_change", channel=ch, control=control, value=value))


def _pgm(tick, program, ch=0):
    return (tick, mido.Message("program_change", channel=ch, program=program))


def _tempo(bpm):
    return mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm))


def _import(*tracks, **kw):
    name = kw.pop("name", "fichier")
    return build_pattern_from_midi(_mid(*tracks, **kw), name=name)


def _of(pat, t, etype):
    return [ev for ev in pat._tape[t] if ev.etype == etype]


# ---------------------------------------------------------------------------
# Fichier, nom, tempo, signature


class TestFile:

    def test_type_2_refused(self):
        with pytest.raises(ValueError):
            build_pattern_from_midi(mido.MidiFile(type=2))

    def test_empty_file(self):
        pat, rep = _import()
        assert rep.num_tracks == 0
        assert pat._num_bars == 1
        assert pat._bpm == DEFAULT_BPM
        assert pat.is_empty()

    def test_returns_new_pattern_and_report(self):
        pat, rep = _import(_track(_note(0, 100)))
        assert isinstance(pat, Pattern)
        assert isinstance(rep, ImportReport)

    def test_conductor_name_is_pattern_name(self):
        pat, _ = _import(_track(_note(0, 100)), name="fichier",
                         conductor=[mido.MetaMessage("track_name", name="Morceau")])
        assert pat._name == "Morceau"

    def test_file_name_without_conductor_name(self):
        pat, _ = _import(_track(_note(0, 100), name="Basse"), name="fichier")
        assert pat._name == "fichier"

    def test_first_track_with_notes_is_not_conductor(self):
        pat, _ = _import(_track(_note(0, 100), name="Basse"), name="fichier")
        assert pat._voices[0]["name"] == "Basse"

    def test_first_tempo_gives_bpm(self):
        pat, rep = _import(_track(_note(0, 100)), conductor=[_tempo(96)])
        assert pat._bpm == 96
        assert rep.bpm == 96
        assert rep.tempo_changes == 0

    def test_bpm_rounded_and_clamped(self):
        pat, _ = _import(_track(_note(0, 100)), conductor=[_tempo(97.6)])
        assert pat._bpm == 98
        pat, _ = _import(_track(_note(0, 100)),
                         conductor=[mido.MetaMessage("set_tempo", tempo=50000)])  # 1200 BPM
        assert pat._bpm == 600

    def test_tempo_changes_kept_in_map(self):
        # Phase 7 étape 19b1 (§ 19a1 T6) : gardés, plus ignorés
        conductor = _track([(0, _tempo(100)), (BAR, _tempo(100)),
                            (2 * BAR, _tempo(120)), (3 * BAR, _tempo(90))])
        mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)
        mid.tracks.extend([conductor, _track(_note(0, 100), end=4 * BAR)])
        pat, rep = build_pattern_from_midi(mid)
        assert pat._bpm == 100
        assert pat._tempo_changes == [(32, 120), (48, 90)]   # 100 répété : retiré
        assert rep.tempo_changes == 2

    def test_time_signature_reported_if_not_4_4(self):
        sig = mido.MetaMessage("time_signature", numerator=3, denominator=4)
        _, rep = _import(_track(_note(0, 100)), conductor=[sig])
        assert rep.time_signature == (3, 4)
        sig = mido.MetaMessage("time_signature", numerator=4, denominator=4)
        _, rep = _import(_track(_note(0, 100)), conductor=[sig])
        assert rep.time_signature is None

    def test_ppq_of_file_used(self):
        # PPQ 96 : un temps = 96 ticks ; note au 2e temps = pas 4 sur 16
        pat, _ = _import(_track(_note(96, 192)), ppq=96)
        assert _of(pat, 0, ETYPE_PATCH)[0].time == 4


# ---------------------------------------------------------------------------
# Longueur, pas, arrondi


class TestLengthAndSteps:

    def test_bars_from_end_of_track(self):
        pat, rep = _import(_track(_note(0, 100), end=3 * BAR))
        assert pat._num_bars == 3
        assert rep.num_bars == 3

    def test_bars_rounded_up(self):
        pat, _ = _import(_track(_note(0, 100), end=2 * BAR + 1))
        assert pat._num_bars == 3

    def test_bars_from_latest_track(self):
        pat, _ = _import(_track(_note(0, 100), end=BAR),
                         _track(_note(0, 100, ch=1), end=4 * BAR))
        assert pat._num_bars == 4

    def test_bars_clamped_to_999_events_lost(self):
        far = Pattern.MAX_BARS * BAR
        pat, rep = _import(_track(_note(0, 100) + _note(far + 10, far + 20)
                                  + [_cc(far + 5, 1, 64)]))
        assert pat._num_bars == Pattern.MAX_BARS
        assert len(_of(pat, 0, ETYPE_PATCH)) == 1
        assert rep.lost_events == 2

    @pytest.mark.parametrize("num_steps", Pattern.VALID_NUM_STEPS)
    def test_smallest_exact_num_steps(self, num_steps):
        tick = BAR // num_steps               # premier pas de cette résolution
        pat, rep = _import(_track(_note(0, 10) + _note(tick, tick + 10, note=62)))
        assert pat._num_steps == num_steps
        assert rep.num_steps == num_steps
        assert rep.moved_notes == 0
        assert [ev.time for ev in _of(pat, 0, ETYPE_PATCH)] == [0, 1]

    def test_off_grid_note_rounded_on_128(self):
        # pas de 128 = 15 ticks ; 22 ticks → 1,47 pas → 1 ; 23 → 1,53 → 2
        pat, rep = _import(_track(_note(22, 100) + _note(23, 100, note=62)))
        assert pat._num_steps == 128
        assert [ev.time for ev in _of(pat, 0, ETYPE_PATCH)] == [1, 2]
        assert rep.moved_notes == 2

    def test_half_step_rounds_up(self):
        # PPQ 960 : pas de 128 = 30 ticks ; 15 ticks = un demi-pas exact → 1
        pat, rep = _import(_track(_note(15, 100) + _note(45, 100, note=62)), ppq=960)
        assert [ev.time for ev in _of(pat, 0, ETYPE_PATCH)] == [1, 2]
        assert rep.moved_notes == 2

    def test_rounding_never_leaves_pattern(self):
        last = BAR - 1                        # 127,93 pas → 128 = hors pattern
        pat, _ = _import(_track(_note(last, BAR), end=BAR))
        assert pat._num_bars == 1
        assert _of(pat, 0, ETYPE_PATCH)[0].time == 127

    def test_note_times_are_integers(self):
        pat, _ = _import(_track(_note(22, 100)))
        assert isinstance(_of(pat, 0, ETYPE_PATCH)[0].time, int)


# ---------------------------------------------------------------------------
# Notes


class TestNotes:

    def test_note_becomes_patch(self):
        pat, _ = _import(_track(_note(0, PPQ, note=64, vel=90, ch=3)))
        ev = _of(pat, 0, ETYPE_PATCH)[0]
        assert ev.payload == {"note": 64, "vel": 90}
        assert ev.channel == 3

    def test_duration_in_ms_at_pattern_bpm(self):
        # une noire à 120 BPM = 500 ms ; à 60 BPM = 1000 ms
        pat, _ = _import(_track(_note(0, PPQ)), conductor=[_tempo(120)])
        assert _of(pat, 0, ETYPE_PATCH)[0].dur == 500
        pat, _ = _import(_track(_note(0, PPQ)), conductor=[_tempo(60)])
        assert _of(pat, 0, ETYPE_PATCH)[0].dur == 1000

    def test_duration_at_least_1_ms(self):
        pat, _ = _import(_track(_note(0, 0)))
        assert _of(pat, 0, ETYPE_PATCH)[0].dur == 1

    def test_note_on_velocity_0_is_note_off(self):
        events = [(0, mido.Message("note_on", note=60, velocity=100)),
                  (PPQ, mido.Message("note_on", note=60, velocity=0))]
        pat, _ = _import(_track(events), conductor=[_tempo(120)])
        notes = _of(pat, 0, ETYPE_PATCH)
        assert len(notes) == 1
        assert notes[0].dur == 500

    def test_same_note_first_in_first_out(self):
        events = [(0, mido.Message("note_on", note=60, velocity=100)),
                  (PPQ, mido.Message("note_on", note=60, velocity=80)),
                  (2 * PPQ, mido.Message("note_off", note=60)),
                  (4 * PPQ, mido.Message("note_off", note=60))]
        pat, _ = _import(_track(events), conductor=[_tempo(120)])
        notes = _of(pat, 0, ETYPE_PATCH)
        assert [(n.time, n.dur, n.payload["vel"]) for n in notes] == \
               [(0, 1000, 100), (4, 1500, 80)]

    def test_unclosed_note_ends_at_track_end(self):
        events = [(0, mido.Message("note_on", note=60, velocity=100))]
        pat, _ = _import(_track(events, end=BAR), conductor=[_tempo(120)])
        assert _of(pat, 0, ETYPE_PATCH)[0].dur == 2000

    def test_orphan_note_off_ignored(self):
        events = [(0, mido.Message("note_off", note=60))] + _note(PPQ, 2 * PPQ, note=62)
        pat, _ = _import(_track(events))
        assert [n.payload["note"] for n in _of(pat, 0, ETYPE_PATCH)] == [62]

    def test_drum_notes_are_patch_on_channel_10(self):
        pat, _ = _import(_track(_note(0, 60, note=36, ch=9)))
        ev = _of(pat, 0, ETYPE_PATCH)[0]
        assert ev.channel == 9
        assert pat._track_channels[0] == 9


# ---------------------------------------------------------------------------
# Pistes


class TestTracks:

    def test_one_track_per_smf_track(self):
        pat, rep = _import(_track(_note(0, 10), name="A"),
                           _track(_note(0, 10, ch=5), name="B"))
        assert rep.num_tracks == 2
        assert pat._track_channels[:2] == [0, 5]
        assert [pat._voices[t]["name"] for t in range(2)] == ["A", "B"]
        assert rep.track_names == ["A", "B"]

    def test_names_stripped(self):
        pat, _ = _import(_track(_note(0, 10), name="  Bass  "))
        assert pat._voices[0]["name"] == "Bass"

    def test_unused_tracks_keep_defaults(self):
        pat, _ = _import(_track(_note(0, 10, ch=7)))
        assert pat._track_channels[1:] == [Pattern.default_channel(t) for t in range(1, 16)]
        assert pat._tape[1] == []

    def test_track_with_two_channels_split(self):
        pat, rep = _import(_track(_note(0, 10, ch=4) + _note(5, 10, ch=2), name="Mix"))
        assert rep.num_tracks == 2
        assert pat._track_channels[:2] == [4, 2]          # ordre d'apparition
        assert pat._voices[0]["name"] == pat._voices[1]["name"] == "Mix"
        assert all(ev.channel == 4 for ev in pat._tape[0])
        assert all(ev.channel == 2 for ev in pat._tape[1])

    def test_type_0_one_track_per_channel_name_is_pattern(self):
        track = _track(_note(0, 10, ch=0) + _note(0, 10, note=36, ch=9), name="Chanson")
        pat, rep = build_pattern_from_midi(_mid(track, type=0), name="fichier")
        assert rep.num_tracks == 2
        assert pat._name == "Chanson"
        assert pat._voices[0]["name"] == pat._voices[1]["name"] == ""

    def test_track_without_channel_events_skipped(self):
        meta_only = _track([(0, mido.MetaMessage("marker", text="x"))], name="Vide")
        pat, rep = _import(_track(_note(0, 10), name="A"), meta_only,
                           _track(_note(0, 10, ch=1), name="B"))
        assert rep.num_tracks == 2
        assert pat._voices[1]["name"] == "B"

    def test_more_than_16_tracks_merged_by_channel(self):
        tracks = [_track(_note(i * 10, i * 10 + 5, note=40 + i, ch=i % 4), name=f"T{i}")
                  for i in range(18)]
        pat, rep = _import(*tracks)
        assert rep.merged
        assert rep.num_tracks == 4
        assert pat._track_channels[:4] == [0, 1, 2, 3]
        assert [pat._voices[t]["name"] for t in range(4)] == ["T0", "T1", "T2", "T3"]
        assert [n.payload["note"] for n in _of(pat, 0, ETYPE_PATCH)] == [40, 44, 48, 52, 56]
        assert "pistes d'un même canal fusionnées" in rep.details()

    def test_16_tracks_not_merged(self):
        tracks = [_track(_note(0, 5, ch=0)) for _ in range(16)]
        pat, rep = _import(*tracks)
        assert not rep.merged
        assert rep.num_tracks == 16


# ---------------------------------------------------------------------------
# Entête, volume, pan, événements


class TestHeaderAndEvents:

    def test_header_moved_to_start_in_order(self):
        events = [_pgm(10, 33, ch=2), _cc(5, 32, 1, ch=2), _cc(0, 0, 8, ch=2)] \
                 + _note(PPQ, 2 * PPQ, ch=2)
        pat, _ = _import(_track(events))
        head = pat._tape[0][:3]
        assert [(ev.etype, ev.time, ev.channel) for ev in head] == \
               [(ETYPE_CC, 0, 2), (ETYPE_CC, 0, 2), (ETYPE_PGM, 0, 2)]
        assert [ev.payload for ev in head] == \
               [{"cc_num": 0, "value": 8}, {"cc_num": 32, "value": 1}, {"program": 33}]
        assert bank_header(pat._tape[0]) == (2, 33, 8, 1)

    def test_header_last_of_each_kind_wins(self):
        events = [_pgm(0, 10), _pgm(5, 20), _cc(0, 0, 1), _cc(3, 0, 2)] + _note(PPQ, 2 * PPQ)
        pat, _ = _import(_track(events))
        assert len(_of(pat, 0, ETYPE_PGM)) == 1
        assert bank_header(pat._tape[0]) == (0, 20, 2, 0)

    def test_header_only_present_kinds(self):
        pat, _ = _import(_track([_pgm(0, 5)] + _note(0, 10)))
        assert [ev.etype for ev in pat._tape[0]] == [ETYPE_PGM, ETYPE_PATCH]

    def test_header_at_same_tick_as_first_note(self):
        pat, _ = _import(_track(_note(PPQ, 2 * PPQ) + [_pgm(PPQ, 7)]))
        assert pat._tape[0][0].etype == ETYPE_PGM
        assert pat._tape[0][0].time == 0

    def test_program_change_after_first_note_stays(self):
        pat, _ = _import(_track(_note(0, 10) + [_pgm(PPQ, 40), _cc(PPQ, 0, 1)]))
        pgm = _of(pat, 0, ETYPE_PGM)[0]
        assert pgm.time == 4
        cc0 = _of(pat, 0, ETYPE_CC)[0]
        assert (cc0.time, cc0.payload) == (4, {"cc_num": 0, "value": 1})

    def test_track_without_notes_header_at_start(self):
        pat, _ = _import(_track([_pgm(PPQ, 9, ch=1), _cc(2 * PPQ, 0, 3, ch=1)]))
        assert bank_header(pat._tape[0]) == (1, 9, 3, 0)

    def test_volume_and_pan_before_first_note(self):
        events = [_cc(0, 7, 127), _cc(0, 10, 1), _cc(0, 7, 64)] + _note(PPQ, 2 * PPQ)
        pat, _ = _import(_track(events))
        assert pat._track_volumes[0] == 50           # le dernier l'emporte
        assert pat._track_pans[0] == -100
        assert _of(pat, 0, ETYPE_CC) == []

    def test_volume_and_pan_conversion(self):
        pat, _ = _import(_track([_cc(0, 7, 102), _cc(0, 10, 96)] + _note(0, 10)))
        assert pat._track_volumes[0] == round(102 * 100 / 127)
        assert pat._track_pans[0] == round((96 - 64) * 100 / 63)

    def test_volume_after_first_note_is_cc_event(self):
        pat, _ = _import(_track(_note(0, 10) + [_cc(PPQ, 7, 50)]))
        assert pat._track_volumes[0] == 100
        assert _of(pat, 0, ETYPE_CC)[0].payload == {"cc_num": 7, "value": 50}

    def test_other_cc_kept_at_exact_time(self):
        pat, _ = _import(_track(_note(0, 10) + [_cc(22, 1, 64), _cc(0, 91, 0)]))
        ccs = _of(pat, 0, ETYPE_CC)
        assert [(ev.time, ev.payload["cc_num"]) for ev in ccs] == [(0, 91), (22 * 16 / BAR, 1)]

    def test_exact_cc_time_is_integer(self):
        pat, _ = _import(_track(_note(0, 10) + [_cc(PPQ, 1, 64)]))
        assert _of(pat, 0, ETYPE_CC)[0].time == 4
        assert isinstance(_of(pat, 0, ETYPE_CC)[0].time, int)

    def test_pitchwheel_becomes_bend(self):
        events = _note(0, 10) + [(30, mido.Message("pitchwheel", channel=0, pitch=-4096))]
        pat, _ = _import(_track(events))
        ev = _of(pat, 0, ETYPE_BEND)[0]
        assert ev.payload == {"value": -4096}
        assert ev.time == 30 * 16 / BAR

    def test_events_sorted_by_time(self):
        events = _note(PPQ, PPQ + 10, note=62) + _note(0, 10) + [_cc(PPQ // 2, 1, 3)]
        pat, _ = _import(_track(events))
        times = [ev.time for ev in pat._tape[0]]
        assert times == sorted(times)


# ---------------------------------------------------------------------------
# Messages ignorés, compte rendu


class TestReport:

    def test_ignored_messages_counted(self):
        events = _note(0, 10) + [
            (1, mido.Message("aftertouch", value=10)),
            (2, mido.Message("polytouch", note=60, value=10)),
            (3, mido.Message("sysex", data=[0x7E, 0x7F, 0x09, 0x01])),
            (4, mido.MetaMessage("marker", text="A")),
        ]
        pat, rep = _import(_track(events))
        assert rep.ignored == {"aftertouch": 2, "SysEx": 1, "méta": 1}
        assert len(pat._tape[0]) == 1

    def test_known_metas_not_counted(self):
        sig = mido.MetaMessage("time_signature", numerator=4, denominator=4)
        _, rep = _import(_track(_note(0, 10), name="A"), conductor=[_tempo(100), sig])
        assert rep.ignored == {}

    def test_details_empty_when_nothing_to_say(self):
        _, rep = _import(_track(_note(0, 10)))
        assert rep.details() == []

    def test_details_text(self):
        rep = ImportReport()
        rep.moved_notes   = 12
        rep.tempo_changes = 1
        rep.time_signature = (3, 4)
        rep.lost_events   = 2
        rep.ignored       = {"aftertouch": 40, "SysEx": 2}
        assert rep.details() == [
            "12 notes déplacées",
            "1 changement de tempo",
            "signature 3/4 lue en 4/4",
            "2 événements au-delà de 999 mesures",
            "ignorés : 40 aftertouch, 2 SysEx",
        ]

    def test_details_singular(self):
        rep = ImportReport()
        rep.moved_notes = 1
        assert rep.details() == ["1 note déplacée"]


# ---------------------------------------------------------------------------
# Aller-retour export → import


class TestRoundTrip:

    def _export(self, pat, bpm=100, channels=None, volumes=None, pans=None, names=None):
        n = Pattern.DEFAULT_NUM_TRACKS
        return build_pattern_midi(
            pat, name="Essai", bpm=bpm,
            track_channels=channels or [Pattern.default_channel(t) for t in range(n)],
            track_is_synth=[False] * n, track_is_bank=[True] * n,
            track_names=names or [""] * n, kit_pad_notes=[36] * 16,
            synth_grid_notes=[60] * 16, voice_durations=[500] * 16,
            track_volumes=volumes or [100] * n, track_pans=pans or [0] * n)

    def _source(self):
        p = Pattern()
        p._bpm, p._num_bars, p._num_steps = 100, 2, 32
        p._tape[0] = [
            TapeEvent(ETYPE_CC, channel=0, payload={"cc_num": 0, "value": 0}, time=0),
            TapeEvent(ETYPE_CC, channel=0, payload={"cc_num": 32, "value": 0}, time=0),
            TapeEvent(ETYPE_PGM, channel=0, payload={"program": 33}, time=0),
            TapeEvent(ETYPE_PATCH, dur=500, channel=0, payload={"note": 40, "vel": 90}, time=0),
            TapeEvent(ETYPE_PATCH, dur=250, channel=0, payload={"note": 43, "vel": 80}, time=9),
            TapeEvent(ETYPE_CC, channel=0, payload={"cc_num": 1, "value": 64}, time=10.5),
            TapeEvent(ETYPE_BEND, channel=0, payload={"value": -2000}, time=12),
        ]
        p._tape[1] = [TapeEvent(ETYPE_PATCH, dur=100, channel=9,
                                payload={"note": 36, "vel": 127}, time=t) for t in (0, 8, 16, 24)]
        return p

    def test_round_trip(self):
        src = self._source()
        n = Pattern.DEFAULT_NUM_TRACKS
        mid = self._export(src, channels=[0, 9] + list(range(2, n)),
                           volumes=[80, 100] + [100] * (n - 2),
                           names=["Basse", "Batterie"] + [""] * (n - 2))
        pat, rep = build_pattern_from_midi(mid)
        assert (pat._name, pat._bpm, pat._num_bars, pat._num_steps) == ("Essai", 100, 2, 32)
        assert rep.num_tracks == 2
        assert rep.moved_notes == 0
        assert pat._track_channels[:2] == [0, 9]
        assert pat._track_volumes[:2] == [80, 100]
        assert [pat._voices[t]["name"] for t in range(2)] == ["Basse", "Batterie"]
        assert bank_header(pat._tape[0]) == (0, 33, 0, 0)
        # CC91 / CC93 de l'export : gardés comme événements (I9)
        kept = [ev for ev in pat._tape[0] if not (ev.etype == ETYPE_CC
                                                   and ev.payload["cc_num"] in (91, 93))]
        assert [(ev.etype, ev.time, ev.dur, ev.payload) for ev in kept] == \
               [(ev.etype, ev.time, ev.dur, ev.payload) for ev in src._tape[0]]
        assert [(ev.time, ev.dur, ev.channel, ev.payload) for ev in _of(pat, 1, ETYPE_PATCH)] == \
               [(ev.time, ev.dur, ev.channel, ev.payload) for ev in src._tape[1]]

    def test_round_trip_pan_within_one(self):
        n = Pattern.DEFAULT_NUM_TRACKS
        src = self._source()
        for pan in (-100, -50, 0, 33, 100):
            pat, _ = build_pattern_from_midi(self._export(src, pans=[pan] * n))
            assert abs(pat._track_pans[0] - pan) <= 1

    def test_imported_pattern_survives_save(self):
        pat, _ = build_pattern_from_midi(self._export(self._source()))
        copy = Pattern()
        copy.from_dict(pat.to_dict())
        assert copy.to_dict() == pat.to_dict()


# ---------------------------------------------------------------------------
# Lecture d'un fichier


class TestImportPattern:

    def test_name_from_file(self, tmp_path):
        path = tmp_path / "ma_chanson.mid"
        _mid(_track(_note(0, 10))).save(str(path))
        pat, rep = import_pattern(str(path))
        assert pat._name == "ma_chanson"
        assert rep.num_tracks == 1

    def test_damaged_file_read(self, tmp_path):
        # note on de vélocité 0x80 : octet de données invalide, refusé par
        # mido sans clip
        body = bytes([0x00, 0x90, 0x3C, 0x80, 0x60, 0x80, 0x3C, 0x00,
                      0x00, 0xFF, 0x2F, 0x00])
        data = (b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQ)
                + b"MTrk" + struct.pack(">I", len(body)) + body)
        path = tmp_path / "abime.mid"
        path.write_bytes(data)
        with pytest.raises(Exception):
            mido.MidiFile(str(path))
        pat, _ = import_pattern(str(path))
        assert _of(pat, 0, ETYPE_PATCH)[0].payload == {"note": 60, "vel": 127}
