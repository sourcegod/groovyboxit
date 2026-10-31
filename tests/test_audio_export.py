#python3
"""
    File: tests/test_audio_export.py
    Tests de l'export audio WAV, Phase 8 étape 1g1 (docs/DESIGN.md § Phase
    8 étape 1a, W1-W7, et § 1d2, W9) : positions à l'échantillon près,
    carte de tempo, longueur exacte, régime établi (passages identiques,
    repli, charleston coupée à la jonction), fin de la résonance et
    plafond, fins de note avant les notes au même échantillon, passage à
    blanc et chargements à la volée, messages, progression et annulation,
    écoute intacte, gain, dither et formats.
    Le rendu est un prototype, cible C/C++ : ces tests fixent le contenu
    des tampons, référence de la version native.
    Date: Sat, 31/10/2026
    Author: Coolbrother
"""
import sys
import os
import math
import time
import types
import threading
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
import soundfile as sf

import audio_export as ax
import track_router as tr_mod
from track_router import TrackRouter
from rack import Rack, InstrumentType
from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_PATCH, ETYPE_PGM
from engines.bank_engine import BankEngine
from engines import fluidsynth_engine as fs_mod
from sound_device_driver import Mixer
from sound_manager import SoundManager
from synth_engine import SynthEngine
from voice_manager import VoiceManager

SR = 44100


# ---------------------------------------------------------------------------
# Aides
# ---------------------------------------------------------------------------

class FakeTimer:
    """Aucune minuterie murale ne doit servir au rendu."""
    created = []

    def __init__(self, interval, fn, args=None):
        FakeTimer.created.append(self)

    def start(self):
        pass


@pytest.fixture(autouse=True)
def _fake_timer(monkeypatch):
    FakeTimer.created = []
    monkeypatch.setattr(tr_mod, "threading",
                        types.SimpleNamespace(Timer=FakeTimer, Thread=threading.Thread))


def _write(path, data):
    sf.write(path, np.asarray(data, dtype=np.float32), SR)
    return path


def _impulse(tmp_path, name, n=4410, value=0.5):
    """Son dont seul le premier échantillon est non nul : révèle sa position."""
    data = np.zeros(n, dtype=np.float32)
    data[0] = value
    return _write(str(tmp_path / name), data)


def _const(tmp_path, name, seconds, value=0.25):
    return _write(str(tmp_path / name), np.full(int(seconds * SR), value, dtype=np.float32))


class Live:
    """Routeur de l'écoute sur un Mixer (sans carte son), kit sur le slot 0."""

    def __init__(self, tmp_path, pads=None, bank=None, rack=None):
        pads = pads or [_impulse(tmp_path, f"pad{i}.wav") for i in range(16)]
        self.driver = Mixer()
        self.snd = SoundManager(pads, pads[0], pads[0], driver=self.driver)
        self.snd.load_sounds()
        self.rack = rack or Rack()
        if rack is None:
            self.rack.set_slot(0, InstrumentType.KIT, "Kit", {})
        self.router = TrackRouter(self.rack, str(tmp_path), self.snd, lambda m: None,
                                  driver=self.driver, bank_engine=bank)
        self.router.set_playback_kb("major", 48)
        self.vm = VoiceManager()


def _pattern(bpm=120, bars=1):
    pat = Pattern()
    pat._bpm, pat._num_bars = bpm, bars      # 120 BPM, 16 pas : 2 s par mesure
    return pat


def _grid(pat, track, pad, time_steps, vel=100):
    pat._tape[track].append(TapeEvent(ETYPE_GRID, payload={"pad": pad, "vel": vel},
                                      time=time_steps))


def _render(pat, live, end=ax.END_TAIL, **kw):
    return ax.render_pattern(pat, pat.tempo_map(), live.router, live.vm, end=end, **kw)


def _sound_end(onset, n):
    """Fin d'un son one-shot de n échantillons lancé à onset : le fondu de
    fin (END_FADE_MS) finit à zéro, et l'interpolation du Mixer ne rend pas
    le dernier échantillon : le dernier non nul est onset + n - 2."""
    return onset + n - 1


def _onsets(data):
    return list(np.flatnonzero(np.abs(data[:, 0]) > 1e-6))


def _fold(tail_result):
    """Repli additif (méthode TiMidity) d'un rendu « pattern + résonance »."""
    L = tail_result.pattern_samples
    out = tail_result.data[:L].copy()
    rest = tail_result.data[L:]
    for k in range(0, len(rest), L):
        chunk = rest[k:k + L]
        out[:len(chunk)] += chunk
    return out


# ---------------------------------------------------------------------------
# Positions, tempo, longueur
# ---------------------------------------------------------------------------

def test_events_at_exact_sample(tmp_path):
    live, pat = Live(tmp_path), _pattern()
    for t in (0, 4, 8.5, 15):
        _grid(pat, 0, 1, t)
    res = _render(pat, live)
    step = 60.0 / 120 / 4                     # 0,125 s par pas
    assert _onsets(res.data) == [round(t * step * SR) for t in (0, 4, 8.5, 15)]


def test_events_follow_tempo_map(tmp_path):
    live, pat = Live(tmp_path), _pattern()
    pat.set_tempo_changes([(8, 60)])           # 60 BPM à partir du pas 8
    for t in (4, 8, 12):
        _grid(pat, 0, 1, t)
    res = _render(pat, live)
    tm = pat.tempo_map()
    assert _onsets(res.data) == [round(tm.secs(t) * SR) for t in (4, 8, 12)]
    assert res.pattern_samples == round(tm.secs(16) * SR) == round(3.0 * SR)


def test_signature_and_bars_set_length(tmp_path):
    live, pat = Live(tmp_path), _pattern(bpm=90)
    pat.set_signature(3, 4)                    # 12 pas par mesure
    pat._num_bars = 3
    res = _render(pat, live, end=ax.END_LOOP)
    tm = pat.tempo_map()
    assert len(res.data) == res.pattern_samples == round(tm.secs(3 * pat._num_steps) * SR)
    assert res.pattern_samples == round(3 * 3 * 60 / 90 * SR)     # 3 mesures de 3 noires


def test_loop_length_exact_and_tail_mode_longer(tmp_path):
    pads = [_const(tmp_path, f"c{i}.wav", 0.8) for i in range(16)]
    live, pat = Live(tmp_path, pads), _pattern()
    _grid(pat, 0, 0, 14)                       # 1,75 s + 0,8 s : dépasse de 0,55 s
    loop = _render(pat, live, end=ax.END_LOOP)
    tail = _render(pat, live, end=ax.END_TAIL)
    assert len(loop.data) == 2 * SR == loop.pattern_samples
    assert len(tail.data) == 2 * SR + tail.tail_samples
    assert tail.tail_samples == _sound_end(round(1.75 * SR), int(0.8 * SR)) - 2 * SR
    assert not tail.tail_cut and tail.passes == 1


def test_empty_pattern_is_silence_of_pattern_length(tmp_path):
    live, pat = Live(tmp_path), _pattern()
    for end in (ax.END_LOOP, ax.END_TAIL):
        res = _render(pat, live, end=end)
        assert len(res.data) == 2 * SR and not res.data.any()
        assert res.tail_samples == 0


def test_window_like_playback_last_step_excluded_beyond(tmp_path):
    live, pat = Live(tmp_path), _pattern()
    _grid(pat, 0, 1, 15)                       # dernier pas : joué
    _grid(pat, 0, 1, 15.5)                     # au-delà de total - 1 : ignoré, comme à l'écoute
    res = _render(pat, live)
    assert _onsets(res.data) == [round(15 * 0.125 * SR)]


# ---------------------------------------------------------------------------
# Régime établi (W2)
# ---------------------------------------------------------------------------

def test_loop_steady_state_equals_fold_without_interactions(tmp_path):
    pads = [_write(str(tmp_path / f"d{i}.wav"),
                   0.4 * np.exp(-np.arange(int(1.5 * SR)) / 9000.0)) for i in range(16)]
    live, pat = Live(tmp_path, pads), _pattern()
    _grid(pat, 0, 0, 0)
    _grid(pat, 1, 1, 13)
    loop = _render(pat, live, end=ax.END_LOOP)
    tail = _render(pat, live, end=ax.END_TAIL)
    assert loop.passes == 2
    assert np.allclose(loop.data, _fold(tail), atol=1e-6)


def test_tail_longer_than_pattern_takes_more_passes(tmp_path):
    pads = [_const(tmp_path, f"l{i}.wav", 5.0, 0.1) for i in range(16)]
    live, pat = Live(tmp_path, pads), _pattern()
    _grid(pat, 0, 0, 8)                        # 1 s + 5 s : 4 s de résonance
    loop = _render(pat, live, end=ax.END_LOOP)
    tail = _render(pat, live, end=ax.END_TAIL)
    assert loop.passes == 1 + math.ceil(tail.tail_samples / loop.pattern_samples) == 3
    assert np.allclose(loop.data, _fold(tail), atol=1e-6)
    # en régime établi, au début, sonnent les notes lancées 1 s et 3 s plus tôt
    assert loop.data[100, 0] == pytest.approx(2 * 0.1, abs=1e-3)


def test_passes_are_identical(tmp_path):
    pads = [_const(tmp_path, f"p{i}.wav", 0.3) for i in range(16)]
    live, pat = Live(tmp_path, pads), _pattern(bpm=97)        # pas non entier en échantillons
    for t in (0, 3, 7.25, 11):
        _grid(pat, int(t) % 2, int(t) % 3, t)
    tm = pat.tempo_map()
    L = round(tm.secs(16) * SR)
    tape = ax._snapshot(pat)
    events = ax._pattern_events(tape, pat, tm, SR)
    s = ax._Session(live.router, SR, 1.0)
    try:
        data, _, _ = ax._run(s, tape, events, live.vm, 0, L, 3, False,
                             None, None, 0.0, 1.0)
    finally:
        s.close()
    assert np.array_equal(data[L:2 * L], data[2 * L:3 * L])


def test_mute_group_cuts_at_loop_junction(tmp_path):
    """Charleston ouverte longue à la fin, fermée au début, même groupe :
    en boucle, la fermée coupe l'ouverte du passage précédent (le repli
    additif la laisserait sonner)."""
    pads = [_const(tmp_path, f"h{i}.wav", 0.1 if i == 0 else 1.5, 0.2) for i in range(16)]
    live, pat = Live(tmp_path, pads), _pattern()
    live.snd.set_pad_mute_group(0, 1)          # fermée
    live.snd.set_pad_mute_group(1, 1)          # ouverte
    _grid(pat, 0, 0, 0)
    _grid(pat, 0, 1, 12)                       # 1,5 s : dépasse de 1 s
    loop = _render(pat, live, end=ax.END_LOOP)
    tail = _render(pat, live, end=ax.END_TAIL)
    between = slice(int(0.2 * SR), int(1.4 * SR))      # après la fermée, avant l'ouverte
    assert not loop.data[between].any()
    assert _fold(tail)[between].any()


# ---------------------------------------------------------------------------
# Fin de la résonance (W7)
# ---------------------------------------------------------------------------

def test_tail_ends_when_last_voice_ends(tmp_path):
    pads = [_const(tmp_path, f"t{i}.wav", 0.5) for i in range(16)]
    live, pat = Live(tmp_path, pads), _pattern()
    _grid(pat, 0, 0, 15)
    res = _render(pat, live)
    end_of_sound = _sound_end(round(15 * 0.125 * SR), int(0.5 * SR))
    assert len(res.data) == end_of_sound       # au dernier échantillon non nul
    assert res.data[-1].any()


def test_tail_cut_at_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ax, "TAIL_MAX_S", 0.25)
    pads = [_const(tmp_path, f"k{i}.wav", 3.0) for i in range(16)]
    live, pat = Live(tmp_path, pads), _pattern()
    _grid(pat, 0, 0, 0)
    res = _render(pat, live)
    assert res.tail_cut
    assert res.tail_samples == int(0.25 * SR)
    assert len(res.data) == 2 * SR + int(0.25 * SR)


def test_tail_waits_for_pending_note_off(tmp_path):
    """Note de synthé tenue au-delà de la fin : la résonance attend sa fin."""
    live, pat = _synth_live(tmp_path), _pattern()
    pat._tape[0].append(TapeEvent(ETYPE_PATCH, dur=1000,
                                  payload={"note": 60, "vel": 127}, time=12))
    res = _render(pat, live)
    assert res.tail_samples >= round(0.5 * SR) - BLOCK_SLACK


BLOCK_SLACK = ax.BLOCK


# ---------------------------------------------------------------------------
# Fins de note avant les notes au même échantillon
# ---------------------------------------------------------------------------

def _synth_live(tmp_path, seconds=2.0):
    wav = _const(tmp_path, "synth.wav", seconds, 0.3)
    rack = Rack()
    rack.set_slot(0, InstrumentType.SYNTH, "Synth", {"patch": "s"})
    live = Live(tmp_path, rack=rack)
    eng = SynthEngine(str(tmp_path), driver=live.driver)
    eng.load_single_sample(wav, root_midi=60)
    live.router._slot_synths[0] = eng
    return live


def test_note_off_before_retriggered_note_same_sample(tmp_path):
    live, pat = _synth_live(tmp_path), _pattern()
    # deux notes de 500 ms (4 pas à 120 BPM) : la fin de la première tombe
    # pile sur le début de la seconde
    for t in (0, 4):
        pat._tape[0].append(TapeEvent(ETYPE_PATCH, dur=500,
                                      payload={"note": 60, "vel": 127}, time=t))
    res = _render(pat, live)
    second = round(4 * 0.125 * SR)
    assert res.data[second + 2000].any()       # la seconde n'a pas été coupée
    assert res.data[second - 2000].any()
    assert not res.data[second + round(0.5 * SR) + 10:].any()


def test_render_uses_no_wall_clock_timer(tmp_path):
    live, pat = _synth_live(tmp_path), _pattern()
    pat._tape[0].append(TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 60, "vel": 100}, time=0))
    _render(pat, live)
    assert FakeTimer.created == []


# ---------------------------------------------------------------------------
# Passage à blanc et chargements à la volée (W9)
# ---------------------------------------------------------------------------

class SlowSynth(SynthEngine):
    """SynthEngine dont le patch met du temps à se charger, comme un vrai."""
    wav = None
    loads = []

    def load_patch(self, patch_ref):
        time.sleep(0.2)
        if patch_ref == "absent":
            raise FileNotFoundError("patch absent")
        SlowSynth.loads.append(patch_ref)
        self.load_single_sample(SlowSynth.wav, root_midi=60)

    def has_full_range(self):
        return True            # pas de pré-calcul C2-C7 (6 s de rubberband par test)


@pytest.fixture
def slow_synth(tmp_path, monkeypatch):
    SlowSynth.wav = _const(tmp_path, "slow.wav", 1.0, 0.3)
    SlowSynth.loads = []
    monkeypatch.setattr(tr_mod, "SynthEngine", SlowSynth)
    return SlowSynth


def _pgm_pattern(program=3, note_time=1):
    pat = _pattern()
    pat._tape[0].append(TapeEvent(ETYPE_PGM, channel=0, payload={"program": program}, time=0))
    pat._tape[0].append(TapeEvent(ETYPE_PATCH, dur=400,
                                  payload={"note": 60, "vel": 127}, time=note_time))
    return pat


def test_synth_loaded_on_the_fly_is_rendered(tmp_path, slow_synth):
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    rack.set_slot(3, InstrumentType.SYNTH, "Slow", {"patch": "slow"})
    live = Live(tmp_path, rack=rack)
    pat = _pgm_pattern()
    res = _render(pat, live, end=ax.END_TAIL)
    on = round(0.125 * SR)
    assert not res.data[:on].any()
    assert res.data[on + 1000].any()           # la note sonne dès le premier passage
    assert slow_synth.loads == ["slow"]        # chargé une fois (passage à blanc)


def test_on_the_fly_load_leaves_live_untouched(tmp_path, slow_synth):
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    rack.set_slot(3, InstrumentType.SYNTH, "Slow", {"patch": "slow"})
    live = Live(tmp_path, rack=rack)
    _render(_pgm_pattern(), live, end=ax.END_LOOP)
    assert live.router._track_slots[0] == 0
    assert 3 not in live.router._slot_synths
    assert live.driver.voice_count() == 0


def test_status_reports_load_error(tmp_path, slow_synth):
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    rack.set_slot(3, InstrumentType.SYNTH, "Absent", {"patch": "absent"})
    live = Live(tmp_path, rack=rack)
    seen = []
    res = _render(_pgm_pattern(), live, status_cb=seen.append)
    assert any("Erreur slot 04" in m for m in seen)
    assert not res.data.any()


def test_waits_for_live_loading_engine(tmp_path, slow_synth):
    """Un patch encore en chargement dans l'écoute est attendu avant la copie."""
    rack = Rack()
    rack.set_slot(1, InstrumentType.SYNTH, "Slow", {"patch": "slow"})
    live = Live(tmp_path, rack=rack)
    live.router.assign_slot(0, 1)              # chargement en tâche de fond
    pat = _pattern()
    pat._tape[0].append(TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 60, "vel": 127}, time=0))
    res = _render(pat, live)
    assert res.data[1000].any()


# ---------------------------------------------------------------------------
# Banque (FluidSynth), écoute intacte, moteurs fermés
# ---------------------------------------------------------------------------

class FakeBank(BankEngine):
    """Banque qui sonne d'une constante tant qu'une note est tenue, avec une
    release de release_frames échantillons."""
    copies = []

    def __init__(self, release_frames=0):
        super().__init__()
        self.paths, self.held, self.release = [None] * 4, set(), 0
        self.release_frames = release_frames
        self.closed = False
        self.calls = []

    def load(self, slot, path):
        self.paths[slot] = path
        return True

    def unload(self, slot):
        self.paths[slot] = None

    def loaded_path(self, slot):
        return self.paths[slot]

    def presets(self, slot):
        return []

    def select(self, channel, slot, bank, program):
        return True

    def note_on(self, channel, note, velocity):
        self.calls.append(("on", channel, note))
        self.held.add((channel, note))

    def note_off(self, channel, note):
        self.calls.append(("off", channel, note))
        if (channel, note) in self.held:
            self.held.discard((channel, note))
            self.release = self.release_frames

    def cc(self, channel, num, value):
        pass

    def pitch_bend(self, channel, value):
        pass

    def all_notes_off(self):
        pass

    def all_sounds_off(self):
        self.held.clear()
        self.release = 0

    def reset_controllers(self):
        pass

    def active_voices(self):
        return len(self.held) + (1 if self.release > 0 else 0)

    def render(self, out):
        if self.held:
            out += 0.1
        elif self.release > 0:
            n = min(len(out), self.release)
            out[:n] += 0.05
            self.release -= n

    def render_copy(self):
        c = FakeBank(self.release_frames)
        FakeBank.copies.append(c)
        return c

    def close(self):
        self.closed = True


def _bank_live(tmp_path, release_frames=0):
    FakeBank.copies = []
    bank = FakeBank(release_frames)
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    rack.set_slot(2, InstrumentType.BANK, "GM", {"bank_slot": 0})
    rack.set_bank_file(0, "/fake/gm.sf2")
    live = Live(tmp_path, bank=bank, rack=rack)
    live.router.assign_slot(1, 2)
    return live, bank


def test_bank_release_extends_tail(tmp_path):
    live, bank = _bank_live(tmp_path, release_frames=SR // 2)
    pat = _pattern()
    pat._tape[1].append(TapeEvent(ETYPE_PATCH, dur=250, payload={"note": 60, "vel": 100}, time=15))
    res = _render(pat, live)
    off = round(15 * 0.125 * SR) + round(0.25 * SR)
    assert res.tail_samples == pytest.approx(off + SR // 2 - 2 * SR, abs=ax.BLOCK)
    assert res.data[off - 100, 0] == pytest.approx(0.1)
    assert res.data[off + 100, 0] == pytest.approx(0.05)


def test_bank_copies_closed_live_bank_untouched(tmp_path):
    live, bank = _bank_live(tmp_path)
    pat = _pattern()
    pat._tape[1].append(TapeEvent(ETYPE_PATCH, dur=200, payload={"note": 64, "vel": 100}, time=0))
    _render(pat, live, end=ax.END_LOOP)
    assert len(FakeBank.copies) == 3           # passage à blanc, passage simple, régime établi
    assert all(c.closed for c in FakeBank.copies)
    assert bank.calls == [] and not bank.closed
    assert all(c.loaded_path(0) == "/fake/gm.sf2" for c in FakeBank.copies)


def test_live_mixer_and_state_untouched(tmp_path):
    live = Live(tmp_path)
    live.router.set_track_volume(0, 60)
    pat = _pattern()
    _grid(pat, 0, 2, 0)
    before = (list(live.router._track_slots), list(live.router._track_volumes),
              list(live.router._track_cur_channels))
    _render(pat, live, end=ax.END_LOOP)
    assert live.driver.voice_count() == 0
    assert (list(live.router._track_slots), list(live.router._track_volumes),
            list(live.router._track_cur_channels)) == before


def test_mute_solo_volume_and_master_volume(tmp_path):
    pads = [_const(tmp_path, f"v{i}.wav", 0.3, 0.5) for i in range(16)]
    live, pat = Live(tmp_path, pads), _pattern()
    _grid(pat, 0, 0, 0)
    _grid(pat, 1, 1, 8)
    live.router.set_track_volume(0, 50)
    live.router.toggle_track_mute(1)
    res = _render(pat, live, master_volume=80)
    assert res.data[100, 0] == pytest.approx(0.5 * 0.25 * 0.8, abs=1e-4)   # gm_gain(0,5) = 0,25
    assert not res.data[round(SR) + 100:].any()                          # piste 1 muette


def test_master_pan_and_pad_pan(tmp_path):
    pads = [_const(tmp_path, f"q{i}.wav", 0.3, 0.5) for i in range(16)]
    live, pat = Live(tmp_path, pads), _pattern()
    _grid(pat, 0, 0, 0)
    live.vm._voices[0].pan = -50
    res = _render(pat, live, master_pan=-50)                # pan total -100
    assert res.data[100, 0] == pytest.approx(0.5) and res.data[100, 1] == 0.0


@pytest.mark.skipif(not fs_mod.fluidsynth_available()
                    or not os.path.isfile("/usr/share/sounds/sf2/TimGM6mb.sf2"),
                    reason="libfluidsynth ou TimGM6mb absente")
def test_fluidsynth_render_and_live_engine_untouched(tmp_path):
    bank = fs_mod.FluidSynthEngine()
    try:
        rack = Rack()
        rack.set_slot(2, InstrumentType.BANK, "GM", {"bank_slot": 0})
        rack.set_bank_file(0, "/usr/share/sounds/sf2/TimGM6mb.sf2")
        live = Live(tmp_path, bank=bank, rack=rack)
        live.router.assign_slot(0, 2)
        pat = _pattern()
        pat._tape[0].append(TapeEvent(ETYPE_PATCH, dur=500, payload={"note": 60, "vel": 100}, time=0))
        res = _render(pat, live)
        assert np.abs(res.data[:SR // 2]).max() > 0.01
        assert not res.tail_cut
        assert bank.active_voices() == 0
    finally:
        bank.close()


# ---------------------------------------------------------------------------
# Progression et annulation
# ---------------------------------------------------------------------------

def test_progress_monotonic_ends_at_one(tmp_path):
    live, pat = Live(tmp_path), _pattern(bars=4)
    seen = []
    _render(pat, live, end=ax.END_LOOP, progress=seen.append)
    assert seen and seen[-1] == 1.0
    assert all(a <= b for a, b in zip(seen, seen[1:]))
    assert any(0.0 < x < 1.0 for x in seen)


def test_cancel_raises_and_closes_engines(tmp_path):
    live, bank = _bank_live(tmp_path)
    pat = _pattern(bars=4)
    with pytest.raises(ax.RenderCancelled):
        _render(pat, live, cancelled=lambda: True)
    assert FakeBank.copies and all(c.closed for c in FakeBank.copies)


# ---------------------------------------------------------------------------
# Gain, dither, écriture (W3, W4)
# ---------------------------------------------------------------------------

TARGET = 10 ** (ax.PEAK_DB / 20)


def test_gain_attenuates_only_above_target():
    data = np.array([[2.0, -1.0], [0.5, 0.0]], dtype=np.float32)
    out, db = ax.apply_gain(data)
    assert np.abs(out).max() == pytest.approx(TARGET)
    assert db == pytest.approx(20 * math.log10(TARGET / 2.0))
    quiet = np.array([[0.5, -0.2]], dtype=np.float32)
    out, db = ax.apply_gain(quiet)
    assert out is quiet and db == 0.0


def test_gain_normalize_raises_quiet_file():
    quiet = np.array([[0.25, -0.1]], dtype=np.float32)
    out, db = ax.apply_gain(quiet, normalize=True)
    assert np.abs(out).max() == pytest.approx(TARGET)
    assert db == pytest.approx(20 * math.log10(TARGET / 0.25)) and db > 0


def test_gain_silence_unchanged():
    z = np.zeros((10, 2), dtype=np.float32)
    assert ax.apply_gain(z, normalize=True)[1] == 0.0
    assert ax.apply_gain(np.zeros((0, 2), dtype=np.float32))[1] == 0.0


def test_dither_within_one_lsb_and_centered():
    data = np.zeros((20000, 2), dtype=np.float32)
    out = ax.dither_tpdf(data, 16, np.random.default_rng(1))
    lsb = 1 / 32768
    assert np.abs(out).max() <= lsb + 1e-9
    assert abs(float(out.mean())) < lsb / 20
    again = ax.dither_tpdf(data, 16, np.random.default_rng(1))
    assert np.array_equal(out, again)


def _result(data):
    return ax.RenderResult(np.asarray(data, dtype=np.float32), SR, len(data), 0, False, 1)


@pytest.mark.parametrize("subtype", ax.SUBTYPES)
def test_write_wav_formats(tmp_path, subtype):
    t = np.arange(SR // 10)
    x = (0.5 * np.sin(t * 0.03)).astype(np.float32)
    path = str(tmp_path / f"o_{subtype}.wav")
    db = ax.write_wav(path, _result(np.column_stack([x, -x])), subtype,
                      rng=np.random.default_rng(0))
    info = sf.info(path)
    assert (info.subtype, info.samplerate, info.channels, info.format) == (subtype, SR, 2, "WAV")
    back, _ = sf.read(path, dtype="float32")
    tol = {"PCM_16": 3 / 32768, "PCM_24": 1e-6, "FLOAT": 0.0}[subtype]
    assert db == 0.0
    assert np.abs(back[:, 0] - x).max() <= tol + 1e-7


def test_write_wav_default_is_16_bits(tmp_path):
    path = str(tmp_path / "d.wav")
    ax.write_wav(path, _result(np.zeros((100, 2))))
    assert sf.info(path).subtype == "PCM_16"


def test_write_wav_attenuates_hot_mix(tmp_path):
    path = str(tmp_path / "hot.wav")
    data = np.full((1000, 2), 1.8, dtype=np.float32)
    db = ax.write_wav(path, _result(data), "FLOAT")
    back, _ = sf.read(path, dtype="float32")
    assert np.abs(back).max() == pytest.approx(TARGET, abs=1e-6)
    assert db == pytest.approx(20 * math.log10(TARGET / 1.8))


def test_write_wav_normalize_flag(tmp_path):
    path = str(tmp_path / "n.wav")
    db = ax.write_wav(path, _result(np.full((100, 2), 0.1)), "FLOAT", normalize=True)
    assert sf.read(path, dtype="float32")[0].max() == pytest.approx(TARGET, abs=1e-6)
    assert db > 19


def test_write_wav_unknown_format(tmp_path):
    with pytest.raises(ValueError):
        ax.write_wav(str(tmp_path / "x.wav"), _result(np.zeros((4, 2))), "MP3")
