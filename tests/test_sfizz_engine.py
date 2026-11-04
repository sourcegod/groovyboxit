#python3
"""
    File: tests/test_sfizz_engine.py
    Moteur SFZ (Phase 8 étape 7c1, docs/DESIGN.md § 7a2 Z5, Z8, Z9 ;
    avancement 7b1) : SfzEngine, libsfizz par ctypes derrière BankEngine,
    sur des WAV et des .sfz fabriqués (cosinus à 440 et 660 Hz) :
    emplacements (= slots du Rack), sélection d'un canal et chargement en
    arrière-plan, file d'événements vidée par render(), échange
    d'instance, état des CC rejoué, une instance par canal, coupures,
    Pitch Bend, gain, rendu hors temps réel (render_copy), fichier refusé,
    fermeture. Sautés si libsfizz est absente (docs/sfizz_build.md).
    Date: Wed, 04/11/2026
    Author: Coolbrother
"""
import sys
import os
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest

from engines.bank_engine import BankEngine
from engines.sfizz_engine import SfzEngine, SfizzUnavailable, sfizz_available
from engines import sfizz_engine

needs_sfizz = pytest.mark.skipif(not sfizz_available(),
                                 reason="libsfizz absente (docs/sfizz_build.md)")

SR    = 48000
BLOCK = 512


# ---------------------------------------------------------------------------
# Fichiers d'essai
# ---------------------------------------------------------------------------

def _write_wav(path, freq, seconds=2.0, amp=0.5):
    """Cosinus mono 16 bits : le premier échantillon n'est pas nul."""
    t = np.arange(int(seconds * SR)) / SR
    pcm = (np.cos(2 * np.pi * freq * t) * amp * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


@pytest.fixture
def sfz(tmp_path):
    """dict nom → chemin : sine (la 440 Hz à la note 69, tout le clavier),
    high (mi 660 Hz à la note 76), bad (sample absent : refusé)."""
    _write_wav(tmp_path / "a440.wav", 440.0)
    _write_wav(tmp_path / "e660.wav", 660.0)
    files = {
        "sine": "<region> sample=a440.wav pitch_keycenter=69 lokey=0 hikey=127 "
                "ampeg_release=0.05\n",
        "high": "<region> sample=e660.wav pitch_keycenter=76 lokey=0 hikey=127 "
                "ampeg_release=0.05\n",
        "bad":  "<region> sample=absent.wav\n",
    }
    out = {}
    for name, text in files.items():
        p = tmp_path / f"{name}.sfz"
        p.write_text(text)
        out[name] = str(p)
    return out


@pytest.fixture
def eng():
    msgs = []
    e = SfzEngine(SR, status_cb=msgs.append)
    e.msgs = msgs
    yield e
    e.close()


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------

def _render(e, frames=SR // 4, block=BLOCK):
    """frames échantillons, par blocs comme le callback du pilote."""
    out = np.zeros((frames, 2), np.float32)
    for i in range(0, frames, block):
        e.render(out[i:i + block])
    return out


def _ready(e, channel):
    """Attend le chargement puis rend un bloc : l'échange se fait dans render."""
    e.wait_loaded()
    _render(e, BLOCK)
    assert e.channel_ready(channel)


def _freq(x):
    x = x[:, 0]
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    k = int(np.argmax(spec[1:-1])) + 1
    a, b, c = np.log(spec[k - 1:k + 2] + 1e-12)
    k += 0.5 * (a - c) / (a - 2 * b + c)
    return k * SR / len(x)


def _rms(x):
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def _close(f, target, tol=0.01):
    return abs(f - target) <= target * tol


def _loaded(e, sfz, channel=0, slot=0, name="sine"):
    assert e.load(slot, sfz[name])
    assert e.select(channel, slot, 0, 0)
    _ready(e, channel)


# ---------------------------------------------------------------------------
# Contrat, emplacements
# ---------------------------------------------------------------------------

def test_engine_is_a_bank_engine_with_16_slots():
    assert issubclass(SfzEngine, BankEngine)
    assert SfzEngine.NUM_BANK_SLOTS == 16      # emplacement = slot du Rack (Z8)
    assert SfzEngine.NUM_CHANNELS == 16


def test_unavailable_library_raises(monkeypatch):
    monkeypatch.setattr(sfizz_engine, "_lib", None)
    monkeypatch.setattr(sfizz_engine, "_LIB_NAMES", ("/nexiste/pas/libsfizz.so",))
    monkeypatch.setattr(sfizz_engine.ctypes.util, "find_library", lambda name: None)
    assert not sfizz_available()
    with pytest.raises(SfizzUnavailable):
        SfzEngine(SR)


@needs_sfizz
def test_load_keeps_file_per_slot(eng, sfz):
    assert eng.load(3, sfz["sine"])
    assert eng.load(15, sfz["high"])
    assert eng.loaded_path(3) == sfz["sine"]
    assert eng.loaded_path(15) == sfz["high"]
    assert eng.loaded_path(0) is None


@needs_sfizz
@pytest.mark.parametrize("slot, path", [(-1, None), (16, None), (0, "/nexiste/pas.sfz"), (0, "")])
def test_load_refuses_bad_slot_or_missing_file(eng, sfz, slot, path):
    assert not eng.load(slot, path if path is not None else sfz["sine"])


@needs_sfizz
def test_unload_forgets_file(eng, sfz):
    eng.load(2, sfz["sine"])
    eng.unload(2)
    assert eng.loaded_path(2) is None
    assert eng.presets(2) == []


@needs_sfizz
def test_presets_is_the_file_name(eng, sfz):
    eng.load(4, sfz["sine"])
    assert eng.presets(4) == [(0, 0, "sine")]
    assert eng.presets(5) == []


# ---------------------------------------------------------------------------
# Sélection, chargement, échange (Z9)
# ---------------------------------------------------------------------------

@needs_sfizz
def test_select_without_file_is_refused(eng):
    assert not eng.select(0, 7, 0, 0)
    assert eng.channel_path(0) is None


@needs_sfizz
def test_instance_swapped_in_by_render(eng, sfz):
    eng.load(0, sfz["sine"])
    assert eng.select(0, 0, 0, 0)
    eng.wait_loaded()
    assert not eng.channel_ready(0)            # pas encore mise en place
    _render(eng, BLOCK)
    assert eng.channel_ready(0)
    assert eng.channel_path(0) == sfz["sine"]
    assert eng.msgs == ["SFZ prêt : sine (canal 1)"]


@needs_sfizz
def test_bank_and_program_are_ignored(eng, sfz):
    eng.load(0, sfz["sine"])
    assert eng.select(0, 0, 128, 42)
    _ready(eng, 0)
    eng.note_on(0, 69, 100)
    assert _close(_freq(_render(eng)[4096:]), 440.0)


@needs_sfizz
def test_reselect_same_file_does_not_reload(eng, sfz):
    _loaded(eng, sfz)
    gen = eng._gen[0]
    assert eng.select(0, 0, 0, 0)
    assert eng._gen[0] == gen and eng.channel_ready(0)


@needs_sfizz
def test_file_replaced_while_loading_keeps_the_last(eng, sfz):
    eng.load(0, sfz["sine"])
    eng.load(1, sfz["high"])
    eng.select(0, 0, 0, 0)
    eng.select(0, 1, 0, 0)                     # avant la fin du premier chargement
    _ready(eng, 0)
    assert eng.channel_path(0) == sfz["high"]
    eng.note_on(0, 76, 100)
    assert _close(_freq(_render(eng)[4096:]), 660.0)
    eng._free_retired()
    assert not eng._retired                    # l'instance dépassée est libérée


@needs_sfizz
def test_stale_swap_is_retired_in_render(eng, sfz):
    # Course : un autre fichier est demandé entre la vérification du fil de
    # chargement et l'échange ; le callback écarte l'instance périmée.
    _loaded(eng, sfz)
    current = eng._inst[0]
    stale = eng._lib.sfizz_create_synth()
    eng._queue.append((sfizz_engine.EV_SWAP, 0, stale, eng._gen[0] - 1))
    _render(eng, BLOCK)
    assert eng._inst[0] == current
    assert list(eng._retired) == [stale]
    eng._free_retired()
    assert not eng._retired


@needs_sfizz
def test_events_wait_in_queue_until_render(eng, sfz):
    _loaded(eng, sfz)
    eng.note_on(0, 69, 100)
    assert len(eng._queue) == 1 and eng.active_voices() == 0
    _render(eng, BLOCK)
    assert not eng._queue and eng.active_voices() == 1


@needs_sfizz
def test_events_to_unloaded_channel_are_dropped(eng, sfz):
    eng.note_on(5, 69, 100)
    out = _render(eng, BLOCK)
    assert not eng._queue and float(np.abs(out).max()) == 0.0


@needs_sfizz
def test_refused_file_reported_and_channel_silent(eng, sfz):
    eng.load(0, sfz["bad"])
    assert eng.select(0, 0, 0, 0)
    eng.wait_loaded()
    _render(eng, BLOCK)
    assert eng.msgs == ["SFZ refusé : bad"]
    assert not eng.channel_ready(0)
    eng.note_on(0, 69, 100)
    assert float(np.abs(_render(eng)).max()) == 0.0


# ---------------------------------------------------------------------------
# Rendu, notes, hauteur
# ---------------------------------------------------------------------------

@needs_sfizz
def test_silence_before_any_note(eng, sfz):
    _loaded(eng, sfz)
    assert float(np.abs(_render(eng)).max()) == 0.0


@needs_sfizz
def test_render_adds_into_out(eng, sfz):
    _loaded(eng, sfz)
    eng.note_on(0, 69, 100)
    out = np.full((BLOCK, 2), 0.25, np.float32)
    eng.render(out)
    ref = SfzEngine(SR, realtime=False)
    ref.load(0, sfz["sine"])
    ref.select(0, 0, 0, 0)
    ref.note_on(0, 69, 100)
    alone = np.zeros((BLOCK, 2), np.float32)
    ref.render(alone)
    ref.close()
    assert np.allclose(out, alone + 0.25, atol=1e-6)


@needs_sfizz
@pytest.mark.parametrize("note, target", [(69, 440.0), (81, 880.0), (57, 220.0)])
def test_note_pitch(eng, sfz, note, target):
    _loaded(eng, sfz)
    eng.note_on(0, note, 100)
    assert _close(_freq(_render(eng, SR // 2)[4096:]), target)


@needs_sfizz
def test_note_off_frees_the_voice(eng, sfz):
    _loaded(eng, sfz)
    eng.note_on(0, 69, 100)
    _render(eng, 4 * BLOCK)
    eng.note_off(0, 69)
    _render(eng, SR // 5)                      # ampeg_release = 50 ms
    assert eng.active_voices() == 0
    assert float(np.abs(_render(eng, BLOCK)).max()) == 0.0


@needs_sfizz
def test_block_longer_than_max_block(eng, sfz):
    _loaded(eng, sfz)
    eng.note_on(0, 69, 100)
    out = _render(eng, 3 * SfzEngine.MAX_BLOCK + 100, block=3 * SfzEngine.MAX_BLOCK + 100)
    assert _close(_freq(out[2048:]), 440.0)
    assert float(np.abs(out[-100:]).max()) > 0.01        # rendu jusqu'au bout


@needs_sfizz
def test_idle_channel_plays_again_after_silence(eng, sfz):
    _loaded(eng, sfz)
    _render(eng, SR // 2)                      # canal au repos, non rendu
    eng.note_on(0, 69, 100)
    assert _close(_freq(_render(eng)[4096:]), 440.0)


@needs_sfizz
def test_gain_scales_the_output(sfz):
    def level(gain):
        e = SfzEngine(SR, gain=gain, realtime=False)
        e.load(0, sfz["sine"])
        e.select(0, 0, 0, 0)
        e.note_on(0, 69, 100)
        out = np.zeros((SR // 4, 2), np.float32)
        e.render(out)
        e.close()
        return _rms(out)
    assert level(2.0) == pytest.approx(2 * level(1.0), rel=1e-4)
    assert level(0.0) == 0.0


# ---------------------------------------------------------------------------
# Canaux et contrôleurs (Z5)
# ---------------------------------------------------------------------------

@needs_sfizz
def test_one_instance_per_channel(eng, sfz):
    eng.load(0, sfz["sine"])
    eng.select(0, 0, 0, 0)
    eng.select(1, 0, 0, 0)
    eng.wait_loaded()
    _render(eng, BLOCK)
    assert eng.channel_ready(0) and eng.channel_ready(1)
    assert eng._inst[0][0] != eng._inst[1][0]


@needs_sfizz
def test_channels_have_their_own_volume(eng, sfz):
    eng.load(0, sfz["sine"])
    eng.select(0, 0, 0, 0)
    eng.select(1, 0, 0, 0)
    eng.wait_loaded()
    _render(eng, BLOCK)
    eng.cc(1, 7, 20)
    eng.note_on(0, 69, 100)
    loud = _rms(_render(eng)[4096:])
    eng.channel_sounds_off(0)
    _render(eng, BLOCK)
    eng.note_on(1, 69, 100)
    soft = _rms(_render(eng)[4096:])
    assert soft < loud * 0.1


@needs_sfizz
def test_cc_sent_before_load_is_replayed(eng, sfz):
    eng.cc(0, 7, 20)                           # avant la sélection
    eng.load(0, sfz["sine"])
    eng.select(0, 0, 0, 0)
    eng.cc(0, 10, 0)                           # pendant le chargement
    _ready(eng, 0)
    eng.note_on(0, 69, 100)
    x = _render(eng)[4096:]
    full = SfzEngine(SR, realtime=False)
    full.load(0, sfz["sine"])
    full.select(0, 0, 0, 0)
    full.note_on(0, 69, 100)
    ref = np.zeros((SR // 4, 2), np.float32)
    full.render(ref)
    full.close()
    assert _rms(x[:, 0]) < _rms(ref[4096:, 0]) * 0.2      # CC7 à 20 rejoué
    assert _rms(x[:, 1]) < 1e-6                            # CC10 à 0 : tout à gauche


@needs_sfizz
def test_pitch_bend_and_clamp(eng, sfz):
    _loaded(eng, sfz)
    eng.note_on(0, 69, 100)
    eng.pitch_bend(0, 99999)                   # borné à +8191 = +2 demi-tons
    assert eng._bend[0] == 8191
    assert _close(_freq(_render(eng, SR // 2)[4096:]), 440.0 * 2 ** (2 / 12))


@needs_sfizz
def test_bend_replayed_on_new_instance(eng, sfz):
    eng.pitch_bend(0, 8191)
    _loaded(eng, sfz)
    eng.note_on(0, 69, 100)
    assert _close(_freq(_render(eng, SR // 2)[4096:]), 440.0 * 2 ** (2 / 12))


@needs_sfizz
def test_reset_controllers_recentres_bend_and_forgets_state(eng, sfz):
    _loaded(eng, sfz)
    eng.cc(0, 7, 20)
    eng.pitch_bend(0, 8191)
    eng.reset_controllers()
    assert eng._ccs[0] == {} and eng._bend[0] == 0
    eng.note_on(0, 69, 100)
    assert _close(_freq(_render(eng, SR // 2)[4096:]), 440.0)


@needs_sfizz
def test_mode_messages_are_not_kept_as_state(eng, sfz):
    _loaded(eng, sfz)
    eng.cc(0, 64, 127)
    eng.cc(0, 120, 0)
    eng.cc(0, 123, 0)
    assert eng._ccs[0] == {64: 127}


@needs_sfizz
def test_program_change_has_no_effect(eng, sfz):
    _loaded(eng, sfz)
    eng.program_change(0, 40)
    assert not eng._queue
    eng.note_on(0, 69, 100)
    assert _close(_freq(_render(eng)[4096:]), 440.0)


# ---------------------------------------------------------------------------
# Coupures
# ---------------------------------------------------------------------------

def _two_channels_playing(eng, sfz):
    eng.load(0, sfz["sine"])
    eng.select(0, 0, 0, 0)
    eng.select(1, 0, 0, 0)
    eng.wait_loaded()
    _render(eng, BLOCK)
    eng.note_on(0, 69, 100)
    eng.note_on(1, 72, 100)
    _render(eng, 2 * BLOCK)
    assert eng.active_voices() == 2


@needs_sfizz
def test_channel_sounds_off_cuts_only_that_channel(eng, sfz):
    _two_channels_playing(eng, sfz)
    eng.channel_sounds_off(0)
    _render(eng, BLOCK)
    assert eng.active_voices() == 1
    assert eng._lib.sfizz_get_num_active_voices(eng._inst[1][0]) == 1


@needs_sfizz
def test_channel_sounds_off_cuts_notes_held_by_the_pedal(eng, sfz):
    _loaded(eng, sfz)
    eng.cc(0, 64, 127)
    eng.note_on(0, 69, 100)
    _render(eng, 2 * BLOCK)
    eng.note_off(0, 69)
    _render(eng, SR // 5)
    assert eng.active_voices() == 1            # tenue par la pédale
    eng.channel_sounds_off(0)
    _render(eng, BLOCK)
    assert eng.active_voices() == 0


@needs_sfizz
def test_all_sounds_off_and_all_notes_off(eng, sfz):
    _two_channels_playing(eng, sfz)
    eng.all_sounds_off()
    _render(eng, BLOCK)
    assert eng.active_voices() == 0
    eng.note_on(0, 69, 100)
    eng.note_on(1, 72, 100)
    _render(eng, 2 * BLOCK)
    eng.all_notes_off()
    _render(eng, SR // 5)
    assert eng.active_voices() == 0


# ---------------------------------------------------------------------------
# Hors temps réel (render_copy, export WAV)
# ---------------------------------------------------------------------------

@needs_sfizz
def test_render_copy_keeps_files_and_settings(sfz):
    e = SfzEngine(SR, gain=0.7)
    e.load(2, sfz["sine"])
    c = e.render_copy()
    assert isinstance(c, SfzEngine) and c is not e
    assert not c._realtime and c.gain == 0.7 and c._samplerate == SR
    assert c.loaded_path(2) == sfz["sine"]
    assert c.channel_path(0) is None           # aucun canal chargé d'avance
    c.close()
    e.close()


@needs_sfizz
def test_render_copy_loads_and_plays_at_once(eng, sfz):
    eng.load(0, sfz["sine"])
    c = eng.render_copy()
    assert c.select(0, 0, 0, 0)
    assert c.channel_ready(0)                  # chargement bloquant
    c.note_on(0, 69, 100)
    assert not c._queue and c.active_voices() == 1
    out = np.zeros((SR // 4, 2), np.float32)
    c.render(out)                              # un seul long bloc, découpé
    assert _close(_freq(out[4096:]), 440.0)
    c.close()


# ---------------------------------------------------------------------------
# Fermeture
# ---------------------------------------------------------------------------

@needs_sfizz
def test_close_frees_everything_and_twice_is_harmless(sfz):
    e = SfzEngine(SR)
    e.load(0, sfz["sine"])
    e.select(0, 0, 0, 0)
    e.select(1, 0, 0, 0)
    e.wait_loaded()
    _render(e, BLOCK)                          # canal 0 et 1 en place
    e.load(1, sfz["high"])
    e.select(2, 1, 0, 0)
    e.wait_loaded()                            # canal 2 en attente d'échange
    e.close()
    assert e._inst == [None] * 16 and not e._queue and not e._retired
    e.close()
