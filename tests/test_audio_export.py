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
# Limiteur (W10, § Phase 8 étape 1h3)
# ---------------------------------------------------------------------------

TARGET = 10 ** (ax.PEAK_DB / 20)
A      = round(ax.LOOKAHEAD_S * SR)            # anticipation, en échantillons
TAU    = ax.RELEASE_S * SR


def _quiet(seconds=2.0, level=0.3, seed=0):
    """Signal stéréo sous le seuil (sinus + bruit borné), deux canaux distincts."""
    n = int(seconds * SR)
    t = np.arange(n)
    noise = np.random.default_rng(seed).uniform(-0.05, 0.05, (n, 2))
    sig = np.column_stack([level * np.sin(t * 0.02), -0.7 * level * np.sin(t * 0.031)])
    return (sig + noise).astype(np.float32)


def _gain(src, out):
    """Gain appliqué, mesuré sur le canal le plus fort de chaque échantillon."""
    ch = np.argmax(np.abs(src), axis=1)
    rows = np.arange(len(src))
    s, o = src[rows, ch], out[rows, ch]
    return np.where(np.abs(s) > 1e-6, o / np.where(s == 0, 1, s), 1.0)


def _spiked(p=SR, value=1.8):
    x = _quiet()
    x[p] = [value, -0.6 * value]
    return x


def test_limiter_no_sample_above_threshold():
    rng = np.random.default_rng(3)
    x = (rng.standard_normal((SR * 3, 2)) * 0.5).astype(np.float32)   # très chaud
    for loop in (False, True):
        y, red = ax.limit_peaks(x, TARGET, SR, loop)
        assert np.abs(y).max() <= TARGET * (1 + 1e-6)
        assert red < -3


def test_limiter_peak_reaches_threshold_exactly():
    x = _spiked(value=1.8)
    y, red = ax.limit_peaks(x, TARGET, SR)
    assert np.abs(y[SR]).max() == pytest.approx(TARGET, rel=1e-5)
    assert red == pytest.approx(20 * math.log10(TARGET / 1.8), abs=1e-3)


def test_limiter_gain_one_away_from_peaks():
    """Le niveau de l'écoute est gardé hors des crêtes : c'était le défaut de
    l'atténuation globale (1h3)."""
    x = _spiked()
    y, _ = ax.limit_peaks(x, TARGET, SR)
    g = _gain(x, y)
    assert np.allclose(g[:SR - A - 1], 1.0)                 # avant l'anticipation
    assert np.allclose(g[SR + int(12 * TAU):], 1.0, atol=1e-4)   # après le retour
    assert np.array_equal(y[:SR - A - 1], x[:SR - A - 1])


def test_limiter_lookahead_ramp_before_peak():
    x = _spiked()
    g = _gain(x, ax.limit_peaks(x, TARGET, SR)[0])
    assert g[SR - A - 1] == pytest.approx(1.0)
    assert g[SR - A] < 1.0                                  # la rampe commence A avant
    ramp = g[SR - A:SR + 1]
    assert np.all(np.diff(ramp) <= 1e-9)                    # descente continue
    assert np.max(np.abs(np.diff(ramp))) < 0.01             # sans saut


def test_limiter_release_exponential():
    x = _spiked(value=1.8)
    g = _gain(x, ax.limit_peaks(x, TARGET, SR)[0])
    r = TARGET / 1.8
    for k, tol in ((int(TAU), 0.02), (int(3 * TAU), 0.01)):
        expected = 1 - (1 - r) * math.exp(-k / TAU)
        assert g[SR + k] == pytest.approx(expected, abs=tol)
    after = g[SR:SR + int(5 * TAU)]
    assert np.all(np.diff(after) >= -1e-9)                  # remonte sans rechute


def test_limiter_stereo_linked():
    x = _spiked()
    y, _ = ax.limit_peaks(x, TARGET, SR)
    sl = slice(SR - A, SR + int(3 * TAU))
    ratio_l = y[sl, 0] / x[sl, 0]
    ratio_r = y[sl, 1] / x[sl, 1]
    ok = (np.abs(x[sl, 0]) > 1e-3) & (np.abs(x[sl, 1]) > 1e-3)
    assert np.allclose(ratio_l[ok], ratio_r[ok], atol=1e-5)


def test_limiter_below_threshold_untouched():
    x = _quiet()
    y, red = ax.limit_peaks(x, TARGET, SR)
    assert y is x and red == 0.0
    z = np.zeros((0, 2), dtype=np.float32)
    assert ax.limit_peaks(z, TARGET, SR)[1] == 0.0


def test_limiter_loop_is_circular():
    """Crête au tout début : en boucle, la fin du fichier (qui la précède)
    est déjà réduite, et la jonction fin → début est continue ; sans boucle,
    la fin reste intacte."""
    x = _quiet()
    x[10] = [1.6, 1.6]
    yl, _ = ax.limit_peaks(x, TARGET, SR, loop=True)
    yn, _ = ax.limit_peaks(x, TARGET, SR, loop=False)
    gl, gn = _gain(x, yl), _gain(x, yn)
    assert gl[-1] < 0.99 and gn[-1] == pytest.approx(1.0)
    junction = np.concatenate([gl[-50:], gl[:50]])
    assert np.max(np.abs(np.diff(junction))) < 0.01
    assert np.abs(yl).max() <= TARGET * (1 + 1e-6)


def test_limiter_loop_matches_steady_state():
    """Le limiteur circulaire donne ce que donnerait le fichier joué en
    boucle : le passage du milieu de trois copies limitées d'un bloc."""
    x = _quiet(seconds=0.5)
    x[100] = [1.7, -1.0]
    x[-30] = [-1.4, 1.2]
    yl, _ = ax.limit_peaks(x, TARGET, SR, loop=True)
    tiled = np.concatenate([x, x, x])
    yt, _ = ax.limit_peaks(tiled, TARGET, SR)
    n = len(x)
    assert np.allclose(yl, yt[n:2 * n], atol=2e-3)


def test_limiter_long_file_is_fast():
    x = (np.random.default_rng(5).standard_normal((SR * 60, 2)) * 0.4).astype(np.float32)
    t0 = time.perf_counter()
    ax.limit_peaks(x, TARGET, SR, loop=True)
    assert time.perf_counter() - t0 < 10.0                 # une minute : vectorisé


# ---------------------------------------------------------------------------
# Mesures et normalisation au niveau visé (W11, W12, § 1h6, § 1h8)
# ---------------------------------------------------------------------------

def _tone(level_dbfs, seconds=3.0, freq=997.0, sr=SR, channels=(0, 1)):
    """Sinus de crête level_dbfs sur les canaux donnés (les autres muets)."""
    t = np.arange(int(seconds * sr)) / sr
    s = (10 ** (level_dbfs / 20.0)) * np.sin(2 * np.pi * freq * t)
    out = np.zeros((len(t), 2), dtype=np.float32)
    for ch in channels:
        out[:, ch] = s
    return out


@pytest.mark.parametrize("sr", (48000, 44100))
def test_lufs_reference_997hz_one_channel(sr):
    """BS.1770-4 : un sinus de 997 Hz à 0 dBFS sur un seul canal = −3,01 LUFS."""
    assert ax.loudness_lufs(_tone(0.0, sr=sr, channels=(0,)), sr) == pytest.approx(-3.01, abs=0.02)


def test_lufs_stereo_and_linear_in_db():
    assert ax.loudness_lufs(_tone(0.0), SR) == pytest.approx(0.0, abs=0.03)
    assert ax.loudness_lufs(_tone(-20.0), SR) == pytest.approx(-20.0, abs=0.03)
    assert ax.loudness_lufs(_tone(-26.0), SR) == pytest.approx(-26.0, abs=0.03)


def test_k_weighting_response():
    """Pondération K à 48 kHz : ≈ 0 dB à 1 kHz, plateau ≈ +4 dB dans
    l'aigu, coupure dans le grave."""
    (b1, a1), (b2, a2) = ax.k_weighting(48000)
    def db(f):
        w = np.array([2 * math.pi * f / 48000])
        h = ax._biquad_response(b1, a1, w) * ax._biquad_response(b2, a2, w)
        return 20 * math.log10(abs(h[0]))
    assert abs(db(1000)) < 0.7
    assert 3.5 < db(10000) < 4.2
    assert db(20) < -10 < db(60)


def test_lufs_k_weighting_favours_treble():
    low = ax.loudness_lufs(_tone(-20.0, freq=40.0), SR)
    high = ax.loudness_lufs(_tone(-20.0, freq=8000.0), SR)
    assert high > -20.0 + 3 and low < -20.0 - 1


def test_lufs_absolute_gate_ignores_silence():
    """6 s de silence de part et d'autre ne changent rien : seuls comptent
    les blocs qui touchent le son (ceux du bord, en partie, comme le veut
    la norme). Sans porte, la moyenne serait diluée de 7 dB."""
    tone = _tone(-20.0, seconds=3.0)
    def pad(seconds):
        z = np.zeros((int(seconds * SR), 2), np.float32)
        return np.concatenate([z, tone, z])
    assert ax.loudness_lufs(pad(6.0), SR) == pytest.approx(ax.loudness_lufs(pad(0.5), SR), abs=0.01)
    assert ax.loudness_lufs(pad(6.0), SR) > ax.loudness_lufs(tone, SR) - 0.5


def test_lufs_relative_gate_ignores_quiet_part():
    loud, quiet = _tone(-20.0, seconds=5.0), _tone(-45.0, seconds=5.0)
    both = np.concatenate([loud, quiet])
    ungated = -0.691 + 10 * math.log10(
        np.mean(np.sum(np.stack([ax._k_filter(both[:, c], SR) ** 2 for c in (0, 1)]), axis=0)))
    assert ungated < -22.0                                    # sans porte : dilué
    assert ax.loudness_lufs(both, SR) == pytest.approx(-20.0, abs=0.3)


def test_lufs_silence_and_below_gate_is_none():
    assert ax.loudness_lufs(np.zeros((SR, 2), np.float32), SR) is None
    assert ax.loudness_lufs(_tone(-80.0), SR) is None
    assert ax.loudness_lufs(np.zeros((0, 2), np.float32), SR) is None


def test_lufs_short_file_single_block():
    short = _tone(-20.0, seconds=0.2)
    assert ax.loudness_lufs(short, SR) == pytest.approx(-20.0, abs=0.5)


def test_lufs_long_file_is_fast():
    x = (np.random.default_rng(2).standard_normal((SR * 120, 2)) * 0.1).astype(np.float32)
    t0 = time.perf_counter()
    assert ax.loudness_lufs(x, SR) is not None
    assert time.perf_counter() - t0 < 10.0


def test_measure_peak_and_rms():
    x = _tone(-6.0)
    assert ax.measure_level(x, "peak", SR) == pytest.approx(-6.0, abs=0.01)
    assert ax.measure_level(x, "rms", SR) == pytest.approx(-6.0 - 3.01, abs=0.02)
    one = _tone(0.0, channels=(0,))                           # moyenne sur les deux canaux
    assert ax.measure_level(one, "rms", SR) == pytest.approx(-6.02, abs=0.02)
    for m in ax.MEASURES:
        assert ax.measure_level(np.zeros((100, 2), np.float32), m, SR) is None
    with pytest.raises(ValueError):
        ax.measure_level(x, "true_peak", SR)


def test_normalize_down_too():
    loud = _tone(-3.0)
    out, gain_db, limit_db = ax.apply_gain(loud, True, "lufs", -20, samplerate=SR)
    assert gain_db == pytest.approx(-20.0 - ax.loudness_lufs(loud, SR), abs=0.01) and gain_db < 0
    assert limit_db == 0.0
    assert ax.loudness_lufs(out, SR) == pytest.approx(-20.0, abs=0.03)


def test_normalize_then_limiter_holds_peaks():
    """Niveau visé élevé : le morceau monte, le limiteur tient les crêtes ;
    la loudness finale reste un peu sous la cible (comme Reaper)."""
    x = _quiet(seconds=3.0, level=0.1)
    x[SR] = [0.9, -0.5]
    out, gain_db, limit_db = ax.apply_gain(x, True, "lufs", 0, samplerate=SR)
    assert gain_db > 10 and limit_db < -3
    assert np.abs(out).max() <= TARGET * (1 + 1e-6)
    assert ax.loudness_lufs(out, SR) < 0.0


def test_normalize_skipped_on_silence():
    z = np.zeros((SR, 2), dtype=np.float32)
    out, gain_db, limit_db = ax.apply_gain(z, True, "lufs", -6, samplerate=SR)
    assert (gain_db, limit_db) == (0.0, 0.0) and not out.any()


def test_normalize_loop_uses_circular_limiter():
    x = _quiet(seconds=1.0, level=0.2)
    x[10] = [0.9, 0.9]
    out, _, limit_db = ax.apply_gain(x, True, "peak", 0, samplerate=SR, loop=True)
    assert limit_db < 0
    g_end = _gain(x[-200:], out[-200:]) / 10 ** ((0 - 20 * math.log10(0.9)) / 20)
    assert g_end.min() < 0.99                                 # la fin précède la crête du début


def test_level_range_and_default():
    assert (ax.LEVEL_MIN_DB, ax.LEVEL_MAX_DB, ax.LEVEL_DEFAULT) == (-24, 0, -14)
    assert ax.MEASURES == ("peak", "rms", "lufs")


def test_dialog_normalize_fields():
    from ui.dialogs import AudioExportDialog
    import wx
    dlg = AudioExportDialog(None, level_min=ax.LEVEL_MIN_DB, level_max=ax.LEVEL_MAX_DB)
    try:
        assert not dlg.get_normalize()
        assert not dlg._measure_lb.IsEnabled() and not dlg._level.IsEnabled()
        assert dlg.get_measure_idx() == 2 and dlg.get_level_db() == -14
        assert (dlg._level.GetMin(), dlg._level.GetMax()) == (-24, 0)
        assert dlg._measure_lb.GetString(2) == "Mesure : LUFS-I"
        dlg._normalize_cb.SetValue(True)
        dlg._normalize_cb.ProcessEvent(wx.CommandEvent(wx.EVT_CHECKBOX.typeId,
                                                       dlg._normalize_cb.GetId()))
        assert dlg._measure_lb.IsEnabled() and dlg._level.IsEnabled()
        dlg._level.SetValue(0)
        dlg._measure_lb.SetSelection(1)
        assert (dlg.get_normalize(), dlg.get_measure_idx(), dlg.get_level_db()) == (True, 1, 0)
    finally:
        dlg.Destroy()


def test_dialog_restores_options_and_clamps_level():
    from ui.dialogs import AudioExportDialog
    dlg = AudioExportDialog(None, 1, 2, True, 0, -30, -24, 0)
    try:
        assert (dlg.get_end_idx(), dlg.get_format_idx(), dlg.get_normalize(),
                dlg.get_measure_idx(), dlg.get_level_db()) == (1, 2, True, 0, -24)
        assert dlg._measure_lb.IsEnabled()
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# Gain, dither, écriture (W3, W4, W10)
# ---------------------------------------------------------------------------

def test_gain_hot_mix_goes_to_limiter():
    x = _spiked(value=2.0)
    out, gain_db, limit_db = ax.apply_gain(x)               # sans Normaliser
    assert gain_db == 0.0
    assert limit_db == pytest.approx(20 * math.log10(TARGET / 2.0), abs=1e-3)
    assert np.abs(out).max() <= TARGET * (1 + 1e-6)
    assert np.allclose(out[:SR - A - 1], x[:SR - A - 1])


def test_gain_quiet_unchanged_without_normalize():
    quiet = np.array([[0.5, -0.2]], dtype=np.float32)
    out, gain_db, limit_db = ax.apply_gain(quiet)
    assert out is quiet and gain_db == 0.0 and limit_db == 0.0


def test_gain_normalize_raises_quiet_file():
    quiet = _tone(-40.0)
    out, gain_db, limit_db = ax.apply_gain(quiet, True, "rms", -20, samplerate=SR)
    assert gain_db == pytest.approx(-20.0 - (-40.0 - 3.0103), abs=0.01) and limit_db == 0.0
    assert ax.measure_level(out, "rms", SR) == pytest.approx(-20.0, abs=0.01)


def test_gain_silence_unchanged():
    z = np.zeros((10, 2), dtype=np.float32)
    assert ax.apply_gain(z, normalize=True)[1:] == (0.0, 0.0)
    assert ax.apply_gain(np.zeros((0, 2), dtype=np.float32))[1:] == (0.0, 0.0)


def test_dither_within_one_lsb_and_centered():
    data = np.zeros((20000, 2), dtype=np.float32)
    out = ax.dither_tpdf(data, 16, np.random.default_rng(1))
    lsb = 1 / 32768
    assert np.abs(out).max() <= lsb + 1e-9
    assert abs(float(out.mean())) < lsb / 20
    again = ax.dither_tpdf(data, 16, np.random.default_rng(1))
    assert np.array_equal(out, again)


def _result(data, looped=False):
    return ax.RenderResult(np.asarray(data, dtype=np.float32), SR, len(data), 0, False, 1,
                           looped=looped)


@pytest.mark.parametrize("subtype", ax.SUBTYPES)
def test_write_wav_formats(tmp_path, subtype):
    t = np.arange(SR // 10)
    x = (0.5 * np.sin(t * 0.03)).astype(np.float32)
    path = str(tmp_path / f"o_{subtype}.wav")
    gains = ax.write_wav(path, _result(np.column_stack([x, -x])), subtype,
                         rng=np.random.default_rng(0))
    info = sf.info(path)
    assert (info.subtype, info.samplerate, info.channels, info.format) == (subtype, SR, 2, "WAV")
    back, _ = sf.read(path, dtype="float32")
    tol = {"PCM_16": 3 / 32768, "PCM_24": 1e-6, "FLOAT": 0.0}[subtype]
    assert gains == (0.0, 0.0)
    assert np.abs(back[:, 0] - x).max() <= tol + 1e-7


def test_write_wav_default_is_16_bits(tmp_path):
    path = str(tmp_path / "d.wav")
    ax.write_wav(path, _result(np.zeros((100, 2))))
    assert sf.info(path).subtype == "PCM_16"


@pytest.mark.parametrize("subtype", ax.SUBTYPES)
def test_write_wav_hot_mix_limited_keeps_level(tmp_path, subtype):
    """Quelques crêtes au-dessus de 0 dBFS : le fichier garde le niveau de
    l'écoute ailleurs (défaut de l'atténuation globale, 1h3)."""
    x = _spiked(value=1.8)
    path = str(tmp_path / f"hot_{subtype}.wav")
    gain_db, limit_db = ax.write_wav(path, _result(x), subtype, rng=np.random.default_rng(0))
    back, _ = sf.read(path, dtype="float32")
    assert gain_db == 0.0 and limit_db < -5
    lsb = 2 / 32768 if subtype == "PCM_16" else 1e-6
    assert np.abs(back).max() <= TARGET + lsb
    far = slice(0, SR - A - 1)
    rms = lambda a: float(np.sqrt(np.mean(a.astype(np.float64) ** 2)))
    assert rms(back[far]) == pytest.approx(rms(x[far]), rel=1e-3)


def test_write_wav_looped_result_uses_circular_limiter(tmp_path):
    x = _quiet()
    x[10] = [1.6, 1.6]
    for looped, expect_end_reduced in ((True, True), (False, False)):
        path = str(tmp_path / f"l{looped}.wav")
        ax.write_wav(path, _result(x, looped), "FLOAT")
        back, _ = sf.read(path, dtype="float32")
        g_end = _gain(x[-200:], back[-200:])
        assert (g_end.min() < 0.99) == expect_end_reduced


def test_render_loop_result_is_looped(tmp_path):
    live, pat = Live(tmp_path), _pattern()
    assert _render(pat, live, end=ax.END_LOOP).looped
    assert not _render(pat, live, end=ax.END_TAIL).looped


@pytest.mark.parametrize("measure, level", [("peak", -6), ("rms", -20), ("lufs", -14)])
def test_write_wav_normalize_to_target(tmp_path, measure, level):
    path = str(tmp_path / f"n_{measure}.wav")
    gain_db, limit_db = ax.write_wav(path, _result(_tone(-35.0, seconds=2.0)), "FLOAT",
                                     normalize=True, measure=measure, level_db=level)
    back, _ = sf.read(path, dtype="float32")
    assert limit_db == 0.0 and gain_db > 0
    assert ax.measure_level(back, measure, SR) == pytest.approx(level, abs=0.05)


def test_write_wav_default_normalization_is_lufs_minus_14(tmp_path):
    path = str(tmp_path / "d.wav")
    ax.write_wav(path, _result(_tone(-30.0, seconds=2.0)), "FLOAT", normalize=True)
    back, _ = sf.read(path, dtype="float32")
    assert ax.loudness_lufs(back, SR) == pytest.approx(-14.0, abs=0.05)


def test_write_wav_unknown_format(tmp_path):
    with pytest.raises(ValueError):
        ax.write_wav(str(tmp_path / "x.wav"), _result(np.zeros((4, 2))), "MP3")


# ---------------------------------------------------------------------------
# Compte rendu (W8, W10)
# ---------------------------------------------------------------------------

def _report(res, end_idx=0, format_idx=0, gain_db=0.0, limit_db=0.0, notes=(), norm=None):
    from ui.mw_project import ProjectMixin
    win = ProjectMixin.__new__(ProjectMixin)
    return win._audio_export_report("Pattern 01", "/x/Pat_01.wav", res, end_idx,
                                    format_idx, gain_db, limit_db, list(notes), norm)


def test_report_limiter_and_normalize():
    res = _result(np.zeros((SR * 2, 2)))
    msg = _report(res, limit_db=-5.412)
    assert "limiteur : −5,41 dB au plus" in msg and "normalisé" not in msg
    msg = _report(res, gain_db=3.1, norm=(2, -14))
    assert "normalisé à −14 LUFS-I : +3,10 dB" in msg and "limiteur" not in msg
    msg = _report(res, gain_db=-2.5, norm=(1, -20))
    assert "normalisé à −20 dBFS RMS : −2,50 dB" in msg
    msg = _report(res, gain_db=8.0, limit_db=-3.0, norm=(0, 0))
    assert msg.endswith("normalisé à 0 dBFS crête : +8,00 dB — limiteur : −3,00 dB au plus")
    msg = _report(res)
    assert "limiteur" not in msg and "normalisé" not in msg and "atténué" not in msg


def test_report_file_length_end_format_and_notes():
    res = ax.RenderResult(np.zeros((SR * 3, 2), np.float32), SR, SR * 2, SR, True, 1)
    msg = _report(res, end_idx=1, format_idx=1, notes=["Erreur slot 04: absent"])
    assert msg.startswith("Pattern 01 exporté en WAV : Pat_01.wav")
    assert "3,00 s, pattern + résonance (1,00 s), 24 bits" in msg
    assert "résonance coupée à 30,00 s" in msg
    assert msg.endswith("Erreur slot 04: absent")
    loop = ax.RenderResult(np.zeros((SR, 2), np.float32), SR, SR, 0, False, 2, looped=True)
    assert "boucle exacte, 16 bits" in _report(loop)
    assert "pattern + résonance (aucune)" in _report(_result(np.zeros((SR, 2))), end_idx=1)
