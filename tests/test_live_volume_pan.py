"""Volume et pan de piste en temps réel (Phase 8 étape 18c1, docs/DESIGN.md
§ Phase 8 étape 18a, V1-V8).

Catégories (V8, demande de l'utilisateur) :
- Mixer sans flux, rampe et loi de pan à l'échantillon près : sans marque ;
- vrai TrackRouter + Mixer, moteur Wave léger, voix mixées à la main :
  sans marque ;
- retour de boucle sous retard (fil de lecture réel, attente en temps
  réel) : audio ;
- vrais moteurs FluidSynth, sfizz et Wave ensemble : slow ;
- vraie fenêtre principale : gui (dans le même test que les autres
  vraies fenêtres du module : une seule par module, clients ALSA).
"""

import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from audio import audio_takes as at
from audio.sound_device_driver import Mixer, SdSound, pan_gains
from audio.sound_manager import SoundManager
from audio.track_live_mix import LiveVoice, live_gain
from midi.midi_constants import gm_gain
from rack import Rack, InstrumentType
from track_router import TrackRouter

SR = 44100
RAMP = int(Mixer.GAIN_RAMP_MS / 1000 * SR)          # 441 échantillons


def _flat(n=SR, value=1.0):
    return SdSound(np.full((n, 2), value, np.float32), SR)


def _mix(mixer, frames):
    out = np.zeros((frames, 2), np.float32)
    mixer.mix(out)
    return out


def _target(voice):
    return voice.tgt_l, voice.tgt_r


def _expect(voice, vol, pan):
    l, r = pan_gains(vol, pan)
    assert voice.tgt_l == pytest.approx(l) and voice.tgt_r == pytest.approx(r)


# ---------------------------------------------------------------------------
# Mixer : loi de pan, rampe (sans marque)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("vol, pan, expected", [
    (1.0, 0, (1.0, 1.0)), (0.5, 100, (0.0, 0.5)), (0.5, -100, (0.5, 0.0)),
    (0.8, 50, (0.4, 0.8)), (0.8, -25, (0.8, 0.6)), (1.0, 300, (0.0, 1.0)),
])
def test_pan_gains_law(vol, pan, expected):
    assert pan_gains(vol, pan) == pytest.approx(expected)


def test_play_starts_at_full_gain_without_ramp():
    m = Mixer(SR)
    v = m.play(_flat(), 0.5, 100)
    assert v.ramp == 0 and _target(v) == (v.vol_l, v.vol_r)
    out = _mix(m, 64)
    assert np.allclose(out[:, 0], 0.0) and np.allclose(out[:, 1], 0.5)


def test_set_voice_gain_ramps_linearly_then_holds():
    m = Mixer(SR)
    v = m.play(_flat(), 1.0, 0)
    m.set_voice_gain(v, 0.0, 0)
    out = _mix(m, 1024)
    k = np.arange(1, RAMP + 1)
    assert np.allclose(out[:RAMP, 0], 1.0 - k / RAMP, atol=1e-5)
    assert out[RAMP - 1, 0] == 0.0 and np.all(out[RAMP:] == 0.0)
    assert v.ramp == 0 and (v.vol_l, v.vol_r) == (0.0, 0.0)


def test_ramp_spans_several_blocks_without_jump():
    m = Mixer(SR)
    v = m.play(_flat(), 1.0, 0)
    m.set_voice_gain(v, 0.5, -100)               # gauche 0,5 ; droite 0
    blocks = np.concatenate([_mix(m, 128) for _ in range(5)])
    ref_l = np.concatenate([1.0 - 0.5 * np.arange(1, RAMP + 1) / RAMP,
                            np.full(640 - RAMP, 0.5)])
    ref_r = np.concatenate([1.0 - np.arange(1, RAMP + 1) / RAMP, np.zeros(640 - RAMP)])
    assert np.allclose(blocks[:, 0], ref_l, atol=1e-5)
    assert np.allclose(blocks[:, 1], ref_r, atol=1e-5)


def test_new_target_during_ramp_starts_from_current_gain():
    m = Mixer(SR)
    v = m.play(_flat(), 1.0, 0)
    m.set_voice_gain(v, 0.0, 0)
    _mix(m, 200)
    mid = v.vol_l
    assert 0.0 < mid < 1.0
    m.set_voice_gain(v, 1.0, 0)                  # demi-tour
    out = _mix(m, 1024)
    assert out[0, 0] == pytest.approx(mid + (1.0 - mid) / RAMP, abs=1e-5)
    assert np.allclose(out[RAMP:, 0], 1.0)


def test_same_target_adds_no_ramp():
    m = Mixer(SR)
    v = m.play(_flat(), 0.5, 20)
    m.set_voice_gain(v, 0.5, 20)
    assert v.ramp == 0


def test_loop_voice_ramp_matches_one_shot_voice():
    m = Mixer(SR)
    data = np.full(SR, 1.0, np.float32)
    lv = m.play(m.make_loop_sound(data, SR, 1000, 40000), 1.0, 0)   # données à 0,5
    m.set_voice_gain(lv, 0.0, 0)
    out = _mix(m, 1024)
    assert np.allclose(out[:RAMP, 0], 0.5 * (1.0 - np.arange(1, RAMP + 1) / RAMP), atol=1e-5)
    assert np.all(out[RAMP:] == 0.0) and lv.ramp == 0


def test_set_voice_gain_on_finished_or_missing_voice_is_harmless():
    m = Mixer(SR)
    v = m.play(_flat(100), 1.0, 0)
    _mix(m, 512)                                 # voix finie, retirée
    assert m.voice_count() == 0
    m.set_voice_gain(v, 0.2, 0)
    m.set_voice_gain(None, 0.2, 0)
    assert np.all(_mix(m, 64) == 0.0)


def test_live_voice_ids():
    m = Mixer(SR)
    a, b = m.play(_flat(100), 1.0), m.play(_flat(), 1.0)
    assert m.live_voice_ids() == {id(a), id(b)}
    _mix(m, 512)
    assert m.live_voice_ids() == {id(b)}


# ---------------------------------------------------------------------------
# Formule (sans marque)
# ---------------------------------------------------------------------------

def test_live_gain_formula():
    grid = LiveVoice(None, None, 0.8, base_pan=30, master_ref=20)
    assert live_gain(grid, 50, 10, -30) == pytest.approx((gm_gain(0.4), -10))
    kit = LiveVoice(None, None, 1.0, master_ref=0, cap=True)
    assert live_gain(kit, 100, 0, 0) == pytest.approx((gm_gain(1.0), 0))
    clip = LiveVoice(None, None, 1.5, master_ref=0, gm=False)
    assert live_gain(clip, 100, 80, 60) == pytest.approx((1.5, 100))     # pan borné
    alone = LiveVoice(None, None, 1.0, base_pan=40, gm=False)            # sans pan global
    assert live_gain(alone, 100, 0, -100) == pytest.approx((1.0, 40))


# ---------------------------------------------------------------------------
# Vrai TrackRouter + Mixer (sans marque)
# ---------------------------------------------------------------------------

class _Wave:
    """Moteur Wave léger : comme SynthEngine.play (courbe GM), sans patch."""

    pitch_bend = 0
    pitch_bend_semitones = 0.0

    def __init__(self, driver, sound):
        self._driver, self._sound = driver, sound
        self.stopped = []

    def is_loaded(self):
        return True

    def play(self, midi_note, volume_factor=1.0, pan=0, maxtime_ms=500):
        return self._driver.play(self._sound, gm_gain(volume_factor), pan)

    def stop(self, midi_note):
        self.stopped.append(midi_note)

    def render_copy(self, driver):
        return _Wave(driver, self._sound)


@pytest.fixture
def env(tmp_path):
    """Pistes : 0 Kit, 1 Wave, 2 Banque (sans moteur), 3 audio."""
    pads = []
    for i in range(16):
        p = str(tmp_path / f"pad{i}.wav")
        at.write_take(p, np.full(SR, 0.5, np.float32), SR)
        pads.append(p)
    at.write_take(str(tmp_path / "clip.wav"), np.full(SR, 0.5, np.float32), SR)
    mix = Mixer(SR)
    snd = SoundManager(pads, pads[0], pads[0], driver=mix)
    snd.load_sounds()
    snd.note_map[36] = snd.drum_sounds[0]
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    rack.set_slot(1, InstrumentType.SYNTH, "Wave", {})
    rack.set_slot(2, InstrumentType.BANK, "GM", {"bank_slot": 0})
    r = TrackRouter(rack, str(tmp_path), snd, lambda m: None, driver=mix,
                    schedule=lambda *a: None)
    r.set_playback_kb("major", 48)
    wave = _Wave(mix, _flat())
    r._slot_synths[1] = wave
    r._track_slots[1] = 1
    r._track_slots[2] = 2
    r._track_kinds[3] = "audio"
    r.audio_resolver = lambda rel: str(tmp_path / rel)

    class E:
        pass
    e = E()
    e.r, e.mix, e.snd, e.wave = r, mix, snd, wave
    return e


def _only(env, track):
    voices = env.r.live_voices(track)
    assert len(voices) == 1
    return voices[0].voice


def test_grid_kit_follows_track_volume_pan_and_master(env):
    r = env.r
    r.set_master_pan(20)
    r.on_play(0, 0, 0.8, 30, 500)              # pan de grille = pad 10 + global 20
    v = _only(env, 0)
    _expect(v, gm_gain(0.8), 30)
    r.set_track_volume(0, 50)
    _expect(v, gm_gain(0.4), 30)
    r.set_track_pan(0, -40)
    _expect(v, gm_gain(0.4), -10)
    r.set_master_pan(-30)                      # pan du pad gardé, global remplacé
    _expect(v, gm_gain(0.4), -60)
    assert v.ramp == RAMP


def test_grid_wave_follows_its_track(env):
    r = env.r
    r.on_play(1, 0, 1.0, 0, 500)
    v = _only(env, 1)
    r.set_track_volume(1, 25)
    _expect(v, gm_gain(0.25), 0)
    r.set_track_pan(1, 60)
    _expect(v, gm_gain(0.25), 60)


def test_kit_tape_note_starts_with_track_and_master_pan_and_follows(env):
    r = env.r
    r.set_track_pan(0, 30)
    r.set_master_pan(-10)
    r.on_kit_tape(0, 36, 127)
    v = _only(env, 0)
    assert (v.vol_l, v.vol_r) == pytest.approx(pan_gains(gm_gain(1.0), 20))
    r.set_track_volume(0, 60)
    _expect(v, gm_gain(0.6), 20)
    r.set_master_pan(50)
    _expect(v, gm_gain(0.6), 80)


def test_patch_note_on_kit_slot_follows(env):
    r = env.r
    r.on_patch_tape(0, 36, 127)
    v = _only(env, 0)
    r.set_master_pan(-100)
    _expect(v, gm_gain(1.0), -100)


def test_wave_patch_note_starts_with_master_pan_and_follows(env):
    """Essai 18b1 : les notes PATCH (orgue, piano enregistrés au clavier)
    n'avaient jamais le pan global, même au départ."""
    r = env.r
    r.set_master_pan(40)
    r.on_patch_tape(1, 60, 127, 500)
    v = _only(env, 1)
    assert (v.vol_l, v.vol_r) == pytest.approx(pan_gains(gm_gain(1.0), 40))
    r.set_master_pan(-40)
    _expect(v, gm_gain(1.0), -40)
    r.set_track_volume(1, 50)
    _expect(v, gm_gain(0.5), -40)


def test_clip_starts_with_master_pan_and_follows_without_gm_curve(env):
    r = env.r
    r.set_master_pan(-20)
    v = r.on_audio_clip(3, "clip.wav", 0.8, clip_id=1)
    assert (v.vol_l, v.vol_r) == pytest.approx(pan_gains(0.8, -20))
    r.set_track_volume(3, 50)
    _expect(v, 0.4, -20)                       # gain du clip × volume, sans courbe GM
    r.set_track_pan(3, 100)
    _expect(v, 0.4, 80)
    r.set_master_pan(0)
    _expect(v, 0.4, 100)


def test_change_reaches_only_its_track(env):
    r = env.r
    r.on_play(0, 0, 1.0, 0, 500)
    r.on_play(1, 0, 1.0, 0, 500)
    kit, wave = _only(env, 0), _only(env, 1)
    r.set_track_volume(1, 10)
    assert kit.ramp == 0 and _target(kit) == (kit.vol_l, kit.vol_r)
    _expect(wave, gm_gain(0.1), 0)


def test_mixed_output_follows_after_ramp(env):
    r = env.r
    r.on_audio_clip(3, "clip.wav", 1.0, clip_id=1)
    assert np.allclose(_mix(env.mix, 256), 0.5)
    r.set_track_pan(3, -100)
    out = _mix(env.mix, 1024)
    assert np.allclose(out[RAMP:, 0], 0.5) and np.allclose(out[RAMP:, 1], 0.0)


def test_bank_track_keeps_cc_path_and_registers_no_voice(env):
    r = env.r
    sent = []
    r._send_bank_mix = lambda t: sent.append(t)
    r.set_track_volume(2, 40)
    assert sent == [2] and r.live_voices(2) == []


def test_finished_voices_are_forgotten(env):
    r = env.r
    r.on_audio_clip(3, "clip.wav", 1.0, clip_id=1)
    for _ in range(SR // 512 + 2):
        _mix(env.mix, 512)                     # clip d'1 s fini
    r.set_track_volume(3, 50)
    assert r.live_voices(3) == []


def test_register_prunes_beyond_limit(env):
    r = env.r
    short = _flat(64)
    for _ in range(r.LIVE_PRUNE_AT):
        r._track_voice(0, env.mix, env.mix.play(short, 1.0), 1.0)
    _mix(env.mix, 128)                         # toutes finies
    keep = env.mix.play(_flat(), 1.0)
    r._track_voice(0, env.mix, keep, 1.0)
    assert [e.voice for e in r.live_voices(0)] == [keep]


def test_forget_track_voices(env):
    r = env.r
    r.on_play(0, 0, 1.0, 0, 500)
    r.on_play(1, 0, 1.0, 0, 500)
    r.forget_track_voices(0)
    assert r.live_voices(0) == [] and len(r.live_voices(1)) == 1
    r.forget_track_voices()
    assert r.live_voices(1) == []


def test_render_copy_has_its_own_register(env):
    r = env.r
    r.on_play(0, 0, 1.0, 0, 500)
    copy = r.render_copy(Mixer(SR))
    assert copy.live_voices(0) == [] and len(r.live_voices(0)) == 1


# ---------------------------------------------------------------------------
# Retour de boucle en retard (fil de lecture réel : audio)
# ---------------------------------------------------------------------------

def _loop_player():
    from player.drum_player import DrumPlayer
    from pattern import TapeEvent, ETYPE_PATCH

    class _S:
        def __getattr__(self, name):
            return lambda *a, **k: None
    p = DrumPlayer(_S())
    p.set_bpm(600)                             # 16 pas × 25 ms : 0,4 s par passage
    for step, note in ((0.0, 60), (8.0, 62)):
        p._pattern._tape[2].append(TapeEvent(ETYPE_PATCH, payload={"note": note, "vel": 100},
                                             time=step))
    hits = []
    p._on_patch_tape_cb = lambda t, n, v, d=0: hits.append(n)
    return p, hits


@pytest.mark.audio
def test_late_loop_return_keeps_first_notes():
    """Essai 18b1 : sous la charge du fil principal, le fil de lecture
    arrivait en retard au retour de boucle et perdait les notes du début
    (pas 0 joué 2 fois sur 11). Retard simulé : 20 ms après chaque fin de
    mesure, bien au-delà de la tolérance de 2 ms."""
    p, hits = _loop_player()
    orig = p._on_measure_end

    def late(*a):
        res = orig(*a)
        time.sleep(0.02)
        return res
    p._on_measure_end = late
    p.play_pattern()
    try:
        time.sleep(1.5)                        # 3 retours de boucle
    finally:
        p.stop_pattern()
    passes = hits.count(62)
    assert passes >= 3
    assert hits.count(60) >= passes            # chaque passage a son début


@pytest.mark.audio
def test_wakeup_mid_pass_does_not_replay_played_notes():
    """Le filtre reste après un réveil : la note déjà jouée ne repart pas."""
    p, hits = _loop_player()
    p.play_pattern()
    try:
        time.sleep(0.1)                        # pas 0 joué, pas 8 pas encore
        p._wakeup.set()
        time.sleep(0.25)                       # pas 8 joué, avant le retour
    finally:
        p.stop_pattern()
    assert hits[:2] == [60, 62] and hits.count(60) == 1


# ---------------------------------------------------------------------------
# Vrais moteurs ensemble : Kit, Wave, FluidSynth, sfizz, clip (slow)
# ---------------------------------------------------------------------------

_SF2 = next((p for p in ("/usr/share/sounds/sf2/FluidR3_GM.sf2",
                         "/usr/share/sounds/sf2/TimGM6mb.sf2") if os.path.isfile(p)), None)


def _sine(path, freq=220.0, secs=3.0, value=0.3):
    t = np.arange(int(SR * secs)) / SR
    at.write_take(str(path), (value * np.sin(2 * np.pi * freq * t)).astype(np.float32), SR)


def _levels(mixer):
    _mix(mixer, 2048)                          # rampe passée
    out = _mix(mixer, 8192)
    return float(np.abs(out[:, 0]).mean()), float(np.abs(out[:, 1]).mean())


@pytest.mark.slow
def test_all_track_kinds_follow_master_pan_with_real_engines(tmp_path):
    """Demande de l'utilisateur (essai 18b1) : pistes FluidSynth et sfizz en
    même temps que Kit, Wave et audio ; note qui sonne, puis pan global −100.
    FluidSynth suit par CC10 mais pas jusqu'au bout (pan propre des presets),
    comme un pan de piste à −100 : la droite y baisse nettement."""
    from audio.engines.fluidsynth_engine import FluidSynthEngine, FluidSynthUnavailable
    from audio.engines.sfizz_engine import SfzEngine, sfizz_available
    from audio.synth_engine import SynthEngine
    if _SF2 is None or not sfizz_available():
        pytest.skip("FluidSynth (soundfont GM) ou sfizz absent")
    try:
        fs = FluidSynthEngine(samplerate=SR)
    except FluidSynthUnavailable:
        pytest.skip("libfluidsynth absente")
    pads = []
    for i in range(16):
        _sine(tmp_path / f"pad{i}.wav")
        pads.append(str(tmp_path / f"pad{i}.wav"))
    _sine(tmp_path / "clip.wav")
    patch = tmp_path / "patchs" / "Sine"
    patch.mkdir(parents=True)
    _sine(patch / "A4.wav", 440.0)
    import json
    (patch / "patch.json").write_text(json.dumps({
        "name": "Sine", "loop": False, "loop_start": None, "loop_end": None,
        "samples": [{"file": "A4.wav", "root": "A4"}]}))
    (tmp_path / "sine.sfz").write_text(
        "<region> sample=clip.wav pitch_keycenter=57 lokey=0 hikey=127 ampeg_release=0.05\n")
    mix = Mixer(SR)
    snd = SoundManager(pads, pads[0], pads[0], driver=mix)
    snd.load_sounds()
    sfz = SfzEngine(samplerate=SR, realtime=False)
    mix.add_render_source(fs.render)
    mix.add_render_source(sfz.render)
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    rack.set_slot(1, InstrumentType.SYNTH, "Sine", {})
    rack.set_slot(2, InstrumentType.BANK, "GM", {"bank_slot": 0})
    rack.set_bank_file(0, _SF2)
    rack.set_slot(3, InstrumentType.SFZ, "Sine", {"sfz_source": str(tmp_path / "sine.sfz")})
    r = TrackRouter(rack, str(tmp_path / "patchs"), snd, lambda m: None, driver=mix,
                    bank_engine=fs, sfz_engine=sfz, sfz_dir=str(tmp_path),
                    schedule=lambda *a: None)
    try:
        r.set_playback_kb("major", 48)
        wave = SynthEngine(str(tmp_path / "patchs"), driver=mix)
        wave.load_patch("Sine")
        r._slot_synths[1] = wave
        r._track_slots[1] = 1
        for t, s in ((0, 0), (2, 2), (3, 3)):
            r.assign_slot(t, s)
        r._track_channels[2] = r._track_cur_channels[2] = 2
        r._track_channels[3] = r._track_cur_channels[3] = 3
        r._track_kinds[4] = "audio"
        r.audio_resolver = lambda rel: str(tmp_path / rel)
        r.sync_banks()
        fs.program_change(2, 73)                 # flûte, mono
        results = {}
        for t, start in ((0, lambda: r.on_play(0, 0, 1.0, 0, 3000)),
                         (1, lambda: r.on_patch_tape(1, 69, 100, 3000)),
                         (2, lambda: r.on_patch_tape(2, 72, 100, 3000)),
                         (3, lambda: r.on_patch_tape(3, 57, 100, 3000)),
                         (4, lambda: r.on_audio_clip(4, "clip.wav", 1.0, clip_id=1))):
            r.set_master_pan(0)
            for _ in range(12):
                _mix(mix, 4096)                  # restes de la piste précédente
            start()
            before = _levels(mix)
            r.set_master_pan(-100)               # pendant que la note sonne
            results[t] = before, _levels(mix)
            r.cut_track_notes(t)
        for t in (0, 1, 3, 4):                   # Kit, Wave, sfizz, clip : tout à gauche
            (l0, r0), (l1, r1) = results[t]
            assert l0 > 0.01 and r0 > 0.01, (t, results[t])
            assert r1 < 0.05 * l1, (t, results[t])
        (l0, r0), (l1, r1) = results[2]          # FluidSynth : nettement à gauche
        assert l0 > 0.005 and r1 / l1 < 0.7 * (r0 / l0), results[2]
    finally:
        fs.close()
        sfz.close()


# ---------------------------------------------------------------------------
# Vraie fenêtre principale (gui)
# ---------------------------------------------------------------------------

class _CtrlKey:
    def __init__(self, key):
        self.k = key
    def GetKeyCode(self):    return self.k
    def GetUnicodeKey(self): return 0
    def ControlDown(self):   return True
    def ShiftDown(self):     return False
    def AltDown(self):       return False
    def Skip(self):          pass


_APP = None


@pytest.mark.gui
def test_real_main_window_clip_follows_volume_pan_master_and_undo(isolated_preferences, tmp_path):
    """Une seule vraie MainWindow (clients ALSA) : un clip qui sonne suit le
    volume et le pan de sa piste (mêmes méthodes qu'Alt+Haut / Alt+Droite)
    et le pan global (Ctrl+Droite) ; une note de kit longue suit leurs
    Ctrl+Z (l'Undo coupe les clips, 14d1 : la lecture les relance)."""
    global _APP
    import wx
    if wx.GetApp() is None:
        _APP = wx.App(False)
    from ui.main_window import MainWindow
    win = None
    try:
        win = MainWindow(no_fluidsynth=True, no_sfizz=True)
        win._router.wait_loaded()
        r = win._router
        r._track_kinds[3] = "audio"
        at.write_take(str(tmp_path / "clip.wav"), np.full(SR * 5, 0.5, np.float32), SR)
        r.audio_resolver = lambda rel: str(tmp_path / rel)
        v = r.on_audio_clip(3, "clip.wav", 1.0, clip_id=99)
        assert v is not None
        win._set_track_volume_undo(3, 50)
        _expect(v, 0.5, 0)
        win._set_track_pan_undo(3, -60)
        _expect(v, 0.5, -60)
        win._key_manager.handle(_CtrlKey(wx.WXK_RIGHT))      # pan global +1
        assert win._player.pan == 1 and r.master_pan == 1
        _expect(v, 0.5, -59)
        r.stop_audio_clips()
        snd = win._router._snd
        snd.drum_sounds[0] = SdSound(np.full((SR * 5, 2), 0.1, np.float32), SR)
        r._track_slots[0] = 0
        win._set_track_volume_undo(0, 50)
        win._set_track_pan_undo(0, 40)
        r.on_play(0, 0, 1.0, 1, 3000)                 # pan de grille = pad 0 + global 1
        kit = r.live_voices(0)[-1].voice
        _expect(kit, gm_gain(0.5), 41)
        for vol, pan in ((0.5, 1), (1.0, 1)):         # Ctrl+Z du pan, puis du volume
            win._undo_action()
            _expect(kit, gm_gain(vol), pan)
        win._undo_action()                            # Ctrl+Z du pan global
        assert r.master_pan == 0
        _expect(kit, gm_gain(1.0), 0)
    finally:
        if win is not None:
            win._router.stop_audio_clips()
            win._player.stop_all()
            win._router.wait_loaded()
            win._close_midi_devices()
            win._audio_driver.close()
            win.Destroy()
