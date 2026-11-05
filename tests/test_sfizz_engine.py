#python3
"""
    File: tests/test_sfizz_engine.py
    Moteur SFZ (Phase 8 étapes 7c1 et 7g1, docs/DESIGN.md § 7a2 Z5, Z8, Z9,
    § 7a3 Z19, Z22 ; avancement 7b1, 7f1, 7f2) : SfzEngine, libsfizz par
    ctypes derrière BankEngine,
    sur des WAV et des .sfz fabriqués (cosinus à 440 et 660 Hz) :
    emplacements (= slots du Rack), sélection d'un canal et chargement en
    arrière-plan, file d'événements vidée par render(), échange
    d'instance, état des CC rejoué, une instance par canal, coupures,
    Pitch Bend, gain, rendu hors temps réel (render_copy), fichier refusé,
    fermeture ; banque de programmes (7g1) : sources dossier et .bank.xml
    (définitions), programme par canal, préchargement et bascule sans
    attente, instances en extinction (fin de note, pédale, coupure),
    abandon et libération, canal libéré, gain par slot. Sautés si libsfizz
    est absente (docs/sfizz_build.md).
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
def test_bank_is_ignored_and_single_file_has_only_program_0(eng, sfz):
    eng.load(0, sfz["sine"])
    assert eng.select(0, 0, 128, 0)            # banque sans objet
    _ready(eng, 0)
    eng.note_on(0, 69, 100)
    assert _close(_freq(_render(eng)[4096:]), 440.0)
    assert not eng.select(1, 0, 0, 1)          # un .sfz seul = le programme 0 seulement


@needs_sfizz
def test_reselect_same_program_does_not_reload(eng, sfz):
    _loaded(eng, sfz)
    inst = eng._inst[0]
    assert eng.select(0, 0, 0, 0)
    assert eng._threads == [] and not eng._queue
    assert eng._inst[0] == inst and eng.channel_ready(0)


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
    # l'instance du premier, plus voulue, n'est pas gardée
    assert [k[1] for k in eng._owned[0]] == [sfz["high"]]


@needs_sfizz
def test_stale_swap_is_ignored_then_dropped(eng, sfz):
    # Course : un autre programme est demandé entre la mise au registre d'une
    # instance et son échange ; le callback ignore l'échange périmé, puis
    # l'instance, plus voulue, lui est confiée (EV_DROP) et libérée.
    _loaded(eng, sfz)
    current = eng._inst[0]
    stale = eng._lib.sfizz_create_synth()
    stale_key = (0, "/perime.sfz", ())
    eng._owned[0][stale_key] = stale
    eng._queue.append((sfizz_engine.EV_SWAP, 0, stale, stale_key))
    _render(eng, BLOCK)
    assert eng._inst[0] == current
    eng._collect()                             # plus voulue : confiée au callback
    assert stale_key not in eng._owned[0]
    _render(eng, BLOCK)                        # le callback la rend
    eng._free_pending()
    assert not eng._freeq and stale not in eng._drop


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
    assert e._inst == [None] * 16 and not e._queue and not e._freeq
    assert all(not o for o in e._owned) and all(not f for f in e._fading)
    e.close()


# ---------------------------------------------------------------------------
# Banque de programmes (Phase 8 étapes 7f1, 7f2 ; § 7a3 Z16-Z22)
# ---------------------------------------------------------------------------

@pytest.fixture
def progs(tmp_path):
    """Dossier de trois programmes (la 440, mi 660, la 880 à la note 69,
    release 0,3 s) et .bank.xml avec une définition ($sample_dir)."""
    _write_wav(tmp_path / "a440.wav", 440.0)
    _write_wav(tmp_path / "e660.wav", 660.0)
    _write_wav(tmp_path / "a880.wav", 880.0)
    folder = tmp_path / "Melodic"
    folder.mkdir()
    for name, wav in (("001-la", "a440"), ("002-mi", "e660"), ("003-la8", "a880")):
        (folder / f"{name}.sfz").write_text(
            f"<region> sample=../{wav}.wav pitch_keycenter=69 lokey=0 hikey=127 "
            f"ampeg_release=0.3\n")
    (tmp_path / "Samples").mkdir()
    _write_wav(tmp_path / "Samples" / "s.wav", 440.0)
    (tmp_path / "Programs").mkdir()
    (tmp_path / "Programs" / "p.sfz").write_text(
        "<control> default_path=$sample_dir/\n<region> sample=s.wav pitch_keycenter=69 "
        "lokey=0 hikey=127\n")
    bank = tmp_path / "Lib.bank.xml"
    bank.write_text('<?xml version="1.0" ?>\n<Key>AB</Key>\n<AriaBank name="Lib">'
                    '<Define name="$sample_dir" value="../Samples"/>'
                    '<AriaProgram name="Un"><AriaElement path="Programs/p.sfz"/></AriaProgram>'
                    '<AriaProgram name="Deux"><AriaElement path="Programs/absent.sfz"/>'
                    '</AriaProgram></AriaBank>\n')
    return {"folder": str(folder), "bank": str(bank)}


def _prog_ready(e, channel=0, program=0, slot=0):
    assert e.select(channel, slot, 0, program)
    _ready(e, channel)


def _voices(e, synth):
    return e._lib.sfizz_get_num_active_voices(synth)


@needs_sfizz
def test_folder_source_presets_and_programs(eng, progs):
    assert eng.load(0, progs["folder"])
    assert eng.loaded_path(0) == progs["folder"]
    assert eng.presets(0) == [(0, 0, "001-la"), (0, 1, "002-mi"), (0, 2, "003-la8")]
    assert eng.source(0).name.endswith(" — Melodic")       # « parent — dossier » (7h1)
    for program, freq in ((0, 440.0), (1, 660.0), (2, 880.0)):
        _prog_ready(eng, program, program)     # un canal par programme
        eng.note_on(program, 69, 100)
        assert _close(_freq(_render(eng)[4096:]), freq)
        eng.all_sounds_off()
        _render(eng, BLOCK)


@needs_sfizz
def test_missing_program_is_refused(eng, progs):
    eng.load(0, progs["folder"])
    assert not eng.select(0, 0, 0, 3)
    assert eng.channel_path(0) is None


@needs_sfizz
def test_source_without_programs_is_refused(eng, tmp_path):
    (tmp_path / "vide").mkdir()
    assert not eng.load(0, str(tmp_path / "vide"))
    assert eng.loaded_path(0) is None
    assert any("aucun programme" in m for m in eng.msgs)


@needs_sfizz
def test_bank_xml_defines_reach_sfizz_and_messages(eng, progs):
    assert eng.load(1, progs["bank"])
    assert eng.presets(1) == [(0, 0, "Un")]
    assert eng.msgs == ["SFZ Lib : programme « Deux » : fichier introuvable"]
    _prog_ready(eng, 0, 0, slot=1)
    eng.note_on(0, 69, 100)
    x = _render(eng)[4096:]
    assert _rms(x) > 0.01 and _close(_freq(x), 440.0)     # sample trouvé par $sample_dir


@needs_sfizz
def test_prefetched_program_switches_without_loading(eng, progs):
    eng.load(0, progs["folder"])
    _prog_ready(eng, 0, 0)
    eng.prefetch(0, 0, [0, 1, 2])
    eng.wait_loaded()
    assert len(eng._owned[0]) == 3
    eng.select(0, 0, 0, 2)
    assert eng._threads == []                  # rien à charger : instance prête
    _render(eng, BLOCK)
    assert eng.channel_ready(0)
    eng.note_on(0, 69, 100)
    assert _close(_freq(_render(eng)[4096:]), 880.0)


@needs_sfizz
def test_unprepared_program_is_loaded(eng, progs):
    eng.load(0, progs["folder"])
    _prog_ready(eng, 0, 0)
    eng.select(0, 0, 0, 1)
    assert not eng.channel_ready(0)
    _ready(eng, 0)
    assert eng.channel_path(0).endswith("002-mi.sfz")


def _switched_with_note(eng, progs):
    """Programme 0 qui joue la 69, puis bascule vers le programme 1 préparé."""
    eng.load(0, progs["folder"])
    _prog_ready(eng, 0, 0)
    eng.prefetch(0, 0, [1])
    eng.wait_loaded()
    eng.note_on(0, 69, 100)
    _render(eng, 4 * BLOCK)
    old = eng._inst[0][0]
    eng.select(0, 0, 0, 1)
    _render(eng, BLOCK)
    return old


@needs_sfizz
def test_replaced_instance_keeps_sounding(eng, progs):
    old = _switched_with_note(eng, progs)
    assert eng._fading[0] == [old] and _voices(eng, old) == 1
    eng.note_on(0, 76, 100)                    # la nouvelle note va au programme 1
    assert _voices(eng, old) == 1
    _render(eng, BLOCK)
    assert _voices(eng, eng._inst[0][0]) == 1
    x = _render(eng, SR // 2)[4096:, 0]
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    peaks = sorted(round(k * SR / len(x)) for k in np.argsort(spec)[-2:])
    # 440 Hz de l'ancienne note, 660 × 2^(7/12) ≈ 989 Hz de la nouvelle
    assert abs(peaks[0] - 440) < 5 and abs(peaks[1] - 989) < 5


@needs_sfizz
def test_note_off_reaches_fading_instance_then_freed(eng, progs):
    # Le pattern ne demande que le programme 1 : le 0, remplacé, n'est plus
    # voulu ; il finit sa note, puis il est libéré.
    old = _switched_with_note(eng, progs)
    assert old not in eng._owned[0].values() and old in eng._drop
    eng.note_off(0, 69)
    _render(eng, SR // 2)                      # release 0,3 s
    eng._free_pending()
    assert eng._fading[0] == [] and old not in eng._drop and not eng._freeq


@needs_sfizz
def test_fading_instance_still_wanted_is_kept(eng, progs):
    # Le pattern demande aussi le programme 0 : son instance est gardée,
    # prête pour le prochain retour au programme 0
    eng.load(0, progs["folder"])
    _prog_ready(eng, 0, 0)
    eng.prefetch(0, 0, [0, 1])
    eng.wait_loaded()
    eng.note_on(0, 69, 100)
    _render(eng, 4 * BLOCK)
    old = eng._inst[0][0]
    eng.select(0, 0, 0, 1)
    eng.note_off(0, 69)
    _render(eng, SR // 2)
    assert eng._fading[0] == [] and old in eng._owned[0].values()
    eng.select(0, 0, 0, 0)                     # retour sans chargement
    assert eng._threads == []
    _render(eng, BLOCK)
    assert eng._inst[0][0] == old


@needs_sfizz
def test_pedal_release_reaches_fading_instance(eng, progs):
    eng.load(0, progs["folder"])
    _prog_ready(eng, 0, 0)
    eng.prefetch(0, 0, [1])
    eng.wait_loaded()
    eng.cc(0, 64, 127)
    eng.note_on(0, 69, 100)
    _render(eng, 2 * BLOCK)
    eng.note_off(0, 69)
    old = eng._inst[0][0]
    eng.select(0, 0, 0, 1)
    _render(eng, SR // 2)
    assert _voices(eng, old) == 1              # tenue par la pédale
    eng.cc(0, 64, 0)
    _render(eng, SR // 2)
    assert _voices(eng, old) == 0 and eng._fading[0] == []


@needs_sfizz
def test_sounds_off_cuts_fading_instances(eng, progs):
    old = _switched_with_note(eng, progs)
    eng.channel_sounds_off(0)
    _render(eng, BLOCK)
    assert _voices(eng, old) == 0 and eng.active_voices() == 0


@needs_sfizz
def test_new_instance_gets_channel_state(eng, progs):
    eng.load(0, progs["folder"])
    _prog_ready(eng, 0, 0)
    eng.prefetch(0, 0, [1])
    eng.wait_loaded()
    eng.cc(0, 10, 0)                           # pan à gauche, avant la bascule
    eng.select(0, 0, 0, 1)
    _render(eng, BLOCK)
    eng.note_on(0, 69, 100)
    x = _render(eng)[4096:]
    assert _rms(x[:, 1]) < 1e-6 < _rms(x[:, 0])


@needs_sfizz
def test_prefetch_drops_unwanted_but_keeps_current(eng, progs):
    eng.load(0, progs["folder"])
    _prog_ready(eng, 0, 0)
    eng.prefetch(0, 0, [0, 1, 2])
    eng.wait_loaded()
    dropped = [s for k, s in eng._owned[0].items() if k[1].endswith("003-la8.sfz")]
    eng.prefetch(0, 0, [1])
    assert sorted(os.path.basename(k[1]) for k in eng._owned[0]) == ["001-la.sfz", "002-mi.sfz"]
    _render(eng, BLOCK)                        # EV_DROP : rendue au fil principal
    eng._free_pending()
    assert not eng._freeq and dropped[0] not in eng._drop


@needs_sfizz
def test_release_channel_frees_current_once_silent(eng, progs):
    eng.load(0, progs["folder"])
    _prog_ready(eng, 0, 0)
    eng.note_on(0, 69, 100)
    _render(eng, 2 * BLOCK)
    eng.release_channel(0)
    assert eng._owned[0] == {} and eng.channel_path(0) is None
    _render(eng, BLOCK)
    assert eng._inst[0] is not None            # finit sa note
    eng.note_off(0, 69)
    _render(eng, SR // 2)
    eng._free_pending()
    assert eng._inst[0] is None and not eng._drop and eng.active_voices() == 0


@needs_sfizz
def test_slot_gain_scales_instances_already_playing(eng, progs):
    eng.load(0, progs["folder"])
    _prog_ready(eng, 0, 0)
    eng.note_on(0, 69, 100)
    full = _rms(_render(eng)[4096:])
    eng.set_slot_gain(0, -6.0)
    half = _rms(_render(eng)[4096:])
    assert half == pytest.approx(full * 10 ** (-6 / 20), rel=0.02)
    assert eng.slot_gain_db(0) == pytest.approx(-6.0)


@needs_sfizz
def test_slot_gain_applies_to_new_instances(eng, progs):
    eng.load(0, progs["folder"])
    eng.set_slot_gain(0, -12.0)
    _prog_ready(eng, 0, 0)
    assert eng._inst_gain[eng._inst[0][0]] == pytest.approx(10 ** (-12 / 20))


@needs_sfizz
def test_same_file_in_two_slots_two_instances_two_gains(eng, sfz):
    eng.load(0, sfz["sine"])
    eng.load(1, sfz["sine"])
    eng.set_slot_gain(1, -6.0)
    _prog_ready(eng, 0, 0, slot=0)
    first = eng._inst[0][0]
    _prog_ready(eng, 0, 0, slot=1)
    assert eng._inst[0][0] != first
    assert eng._inst_gain[eng._inst[0][0]] == pytest.approx(10 ** (-6 / 20))


@needs_sfizz
def test_render_copy_keeps_sources_and_gains(eng, progs):
    eng.load(3, progs["folder"])
    eng.set_slot_gain(3, -6.0)
    c = eng.render_copy()
    assert c.presets(3) == eng.presets(3) and c.slot_gain_db(3) == pytest.approx(-6.0)
    c.prefetch(0, 3, [0, 2])                   # chargement bloquant
    assert len(c._owned[0]) == 2 and c._threads == []
    assert c.select(0, 3, 0, 2) and c.channel_ready(0)
    c.note_on(0, 69, 100)
    out = np.zeros((SR // 4, 2), np.float32)
    c.render(out)
    assert _close(_freq(out[4096:]), 880.0)
    c.close()



# ---------------------------------------------------------------------------
# Notes jouées pendant un chargement, programmes factices (Phase 8 étape 7h1)
# ---------------------------------------------------------------------------

def _loading_program_1(eng, progs):
    """Canal 0 sur le programme 0, puis le programme 1 demandé (pas préparé :
    il se charge) ; la bascule n'a pas encore eu lieu."""
    eng.load(0, progs["folder"])
    _prog_ready(eng, 0, 0)
    eng.select(0, 0, 0, 1)
    eng.wait_loaded()                          # chargé, échange pas encore rendu
    return eng._inst[0][0]


@needs_sfizz
def test_note_during_load_waits_for_new_program(eng, progs):
    old = _loading_program_1(eng, progs)
    eng.note_on(0, 69, 100)
    _render(eng, BLOCK)                        # l'échange passe avant la note
    assert eng._inst[0][0] != old and _voices(eng, old) == 0
    assert _close(_freq(_render(eng)[4096:]), 660.0)     # le nouveau programme


@needs_sfizz
def test_note_queued_before_swap_is_held_then_played(eng, progs):
    old = _loading_program_1(eng, progs)
    swap = [ev for ev in eng._queue if ev[0] == sfizz_engine.EV_SWAP]
    eng._queue.clear()                         # l'échange n'est pas encore arrivé
    eng.note_on(0, 69, 100)
    _render(eng, BLOCK)
    assert eng._pending[0] == [(69, 100)] and _voices(eng, old) == 0
    eng._queue.extend(swap)
    _render(eng, BLOCK)
    assert eng._pending[0] == [] and _voices(eng, eng._inst[0][0]) == 1
    assert _close(_freq(_render(eng)[4096:]), 660.0)


@needs_sfizz
def test_released_before_swap_is_cancelled(eng, progs):
    _loading_program_1(eng, progs)
    swap = [ev for ev in eng._queue if ev[0] == sfizz_engine.EV_SWAP]
    eng._queue.clear()
    eng.note_on(0, 69, 100)
    eng.note_on(0, 72, 90)
    eng.note_off(0, 69)
    _render(eng, BLOCK)
    assert eng._pending[0] == [(72, 90)]
    eng._queue.extend(swap)
    _render(eng, BLOCK)
    assert eng.active_voices() == 1


@needs_sfizz
@pytest.mark.parametrize("cut", ["sounds_off", "cc120", "cc123", "release"])
def test_pending_notes_dropped_by_cuts(eng, progs, cut):
    _loading_program_1(eng, progs)
    eng._queue.clear()
    eng.note_on(0, 69, 100)
    _render(eng, BLOCK)
    assert eng._pending[0]
    if cut == "sounds_off":
        eng.channel_sounds_off(0)
    elif cut == "release":
        eng.release_channel(0)
    else:
        eng.cc(0, int(cut[2:]), 0)
    _render(eng, BLOCK)
    assert eng._pending[0] == []


@needs_sfizz
def test_pending_dropped_when_load_refused(eng, sfz, progs):
    eng.load(0, progs["folder"])
    eng.load(1, sfz["bad"])
    _prog_ready(eng, 0, 0)
    eng._paths[1] = sfz["bad"]
    eng.select(0, 1, 0, 0)                     # programme refusé par sfizz
    eng.note_on(0, 69, 100)
    eng.wait_loaded()
    _render(eng, BLOCK)
    assert eng._pending[0] == [] and "SFZ refusé : bad" in eng.msgs


@needs_sfizz
def test_pending_notes_capped(eng, progs):
    _loading_program_1(eng, progs)
    eng._queue.clear()
    for i in range(SfzEngine.MAX_PENDING + 10):
        eng.note_on(0, 30 + i % 60, 100)
    _render(eng, BLOCK)
    assert len(eng._pending[0]) == SfzEngine.MAX_PENDING


@needs_sfizz
def test_no_pending_without_target(eng, progs):
    eng.note_on(3, 69, 100)                    # canal sans programme voulu
    _render(eng, BLOCK)
    assert eng._pending[3] == []


@needs_sfizz
def test_placeholder_program_shown_as_dummy(eng, tmp_path):
    folder = tmp_path / "GM"
    folder.mkdir()
    (folder / "001-Piano.sfz").write_text("<region> sample=*sine pitch_keycenter=60\n")
    (folder / "020-Church Organ.sfz").write_text("//dummy\n<region> sample=*sine\n")
    eng.load(0, str(folder))
    assert eng.presets(0) == [(0, 0, "001-Piano"), (0, 19, "020-Church Organ (Dummy)")]


# ---------------------------------------------------------------------------
# Source modifiée depuis sa lecture (correction de l'essai de 7j1)
# ---------------------------------------------------------------------------

def _rewrite_later(path, text):
    before = os.stat(path).st_mtime_ns
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.utime(path, ns=(before + 10 ** 9, before + 10 ** 9))


@needs_sfizz
def test_source_stale_after_bank_rewritten(eng, progs, tmp_path):
    from sfz_sources import write_sfzbank
    bank = str(tmp_path / "Essai.sfzbank.json")
    first = os.path.join(progs["folder"], "001-la.sfz")
    write_sfzbank(bank, "Essai", [(0, "La", first)])
    eng.load(0, bank)
    assert not eng.source_stale(0)
    write_sfzbank(bank, "Essai", [(0, "La", first),
                                  (1, "Mi", os.path.join(progs["folder"], "002-mi.sfz"))])
    os.utime(bank, ns=(os.stat(bank).st_mtime_ns + 10 ** 9,) * 2)
    assert eng.source_stale(0)
    eng.load(0, bank)                          # relue
    assert not eng.source_stale(0) and len(eng.presets(0)) == 2


@needs_sfizz
def test_source_stale_after_folder_changed(eng, progs):
    eng.load(0, progs["folder"])
    assert not eng.source_stale(0)
    with open(os.path.join(progs["folder"], "004-re.sfz"), "w") as f:
        f.write("<region> sample=../a440.wav\n")
    assert eng.source_stale(0)


@needs_sfizz
def test_source_stale_false_without_source_and_copied(eng, progs):
    assert not eng.source_stale(3)
    eng.load(3, progs["folder"])
    eng.unload(3)
    assert not eng.source_stale(3)
    eng.load(3, progs["folder"])
    copy = eng.render_copy()
    assert copy._stamps[3] == eng._stamps[3] and not copy.source_stale(3)
    copy.close()
