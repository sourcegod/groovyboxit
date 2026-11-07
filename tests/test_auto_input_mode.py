#python3
"""
    File: tests/test_auto_input_mode.py
    Mode Clavier d'office sur une banque ou un Synth SFZ, mode Pad sur un kit
    (Phase 8 étapes 9b1-9b2, docs/DESIGN.md § 9a K1-K8, § 9b2) :

    - règle (K1-K3) : Banque / SFZ → Clavier, Kit → Pad, synthé WAV et slot
      vide → mode inchangé ;
    - choix manuel gardé tant que le slot joué ne change pas (K4), passage
      d'office refait quand le contenu change de type ;
    - rien pendant l'enregistrement ou le décompte ;
    - annonce (K6) : « — Mode Clavier » ajouté à chaque message de l'action,
      oublié une fois l'action finie ;
    - appelants : navigation des pistes, Ctrl+T / mode Rack, chargement d'un
      pattern (racine de lecture du clavier, 9b2) ;
    - 9b2 : référence commune 36 du pavé et du contrôleur ; NumPad + / −
      déplacent les deux ; nouveaux patterns à 36, anciens à 48.

    Vraie MainWindow (sans FluidSynth ni sfizz) pour la règle, les annonces
    et le pavé ; vrai MidiHandler sur la fenêtre factice du mode Rack pour
    le contrôleur.
    Date: Sat, 07/11/2026
    Author: Coolbrother
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import wx

import ui.midi_handler_window as mh
from pattern import Pattern
from rack import InstrumentType
from test_key_manager import FakeEvent
from test_note_cuts import _env, _live_window, SYNTH, SYNTH2   # noqa: F401 (fixture)

# slots d'essai de la vraie fenêtre (en mémoire seulement, jamais sauvés)
S_BANK, S_SFZ, S_KIT, S_WAV, S_EMPTY = 11, 12, 13, 14, 15

_APP = None


@pytest.fixture(scope="module")
def _main_window():
    """Une seule vraie fenêtre pour le module : chaque MainWindow ouvre un
    client du séquenceur ALSA, et une trentaine épuise la limite."""
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    import ui.main_window as main_window
    w = main_window.MainWindow(no_fluidsynth=True, no_sfizz=True)
    w._router.wait_loaded()
    w.started_kb = (w._kb_root_midi, list(w._router.kb_notes_input[:1]))   # avant tout test
    yield w
    w._router.wait_loaded()
    w._midi.close()                     # comme _on_close
    w._audio_driver.close()
    w.Destroy()


@pytest.fixture
def win(_main_window, monkeypatch):
    import ui.main_window as main_window
    w = _main_window
    w._router.wait_loaded()
    rack = w._rack
    rack.set_slot(S_BANK, InstrumentType.BANK, "FluidR3", {"bank_slot": 0})
    rack.set_slot(S_SFZ,  InstrumentType.SFZ,  "Piano SFZ", {"sfz": "piano.sfz"})
    rack.set_slot(S_KIT,  InstrumentType.KIT,  "TR-707", {"kit": "k.json"})
    rack.set_slot(S_WAV,  InstrumentType.SYNTH, "Piano WAV", {"patch": "p"})
    rack.clear_slot(S_EMPTY)
    w._player.recording, w._player._count_in = False, 0
    w._auto_mode_key, w._mode_note = None, ""
    w._kb_root_midi = w.KB_INPUT_BASE   # état de départ (9b2)
    w._set_kb_play_root(w.KB_INPUT_BASE)
    w._set_input_mode("pad", announce=False)
    w._status_ctrl.SetString(0, "")
    # wx.CallAfter synchrone (feedback : fragilité des tests en suite complète)
    monkeypatch.setattr(main_window.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    yield w
    w._router.wait_loaded()


def _on(win, slot):
    """Le slot joué devient slot, puis la règle s'applique (comme
    _go_to_track ou _follow_track_slot)."""
    win._cur_slot = slot
    return win._apply_auto_input_mode()


# ---------------------------------------------------------------------------
# Règle (K1-K3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slot", [S_BANK, S_SFZ])
def test_bank_and_sfz_switch_to_keyboard(win, slot):
    assert _on(win, slot) == "keyboard"
    assert win._input_mode == "keyboard"
    assert win._mode_choice.GetSelection() == 1


def test_kit_switches_back_to_pad(win):
    _on(win, S_BANK)
    assert _on(win, S_KIT) == "pad"
    assert win._input_mode == "pad"
    assert win._mode_choice.GetSelection() == 0


@pytest.mark.parametrize("slot", [S_WAV, S_EMPTY])
@pytest.mark.parametrize("mode", ["pad", "keyboard"])
def test_wav_synth_and_empty_slot_keep_current_mode(win, slot, mode):
    win._set_input_mode(mode, announce=False)
    assert _on(win, slot) is None
    assert win._input_mode == mode


def test_nothing_when_wanted_mode_already_current(win):
    win._set_input_mode("keyboard", announce=False)
    assert _on(win, S_BANK) is None
    assert win._input_mode == "keyboard" and win._mode_note == ""


def test_keyboard_mode_updates_input_scale(win):
    """En Clavier d'office, la gamme d'entrée est à jour (K6) : NumPad1 joue
    la racine d'entrée."""
    _on(win, S_SFZ)
    assert win._router.kb_notes_input[0] == win._kb_root_midi


# ---------------------------------------------------------------------------
# Choix manuel gardé (K4)
# ---------------------------------------------------------------------------

def test_manual_choice_kept_on_same_slot(win):
    _on(win, S_BANK)
    win._set_input_mode("pad", announce=False)          # Ctrl+1
    assert _on(win, S_BANK) is None                     # autre piste, même slot
    assert win._input_mode == "pad"


def test_manual_choice_dropped_on_other_slot(win):
    _on(win, S_BANK)
    win._set_input_mode("pad", announce=False)
    assert _on(win, S_SFZ) == "keyboard"


def test_content_type_change_on_same_slot_applies_again(win):
    _on(win, S_BANK)
    win._set_input_mode("pad", announce=False)
    win._rack.set_slot(S_BANK, InstrumentType.SFZ, "Orgue SFZ", {"sfz": "o.sfz"})
    assert _on(win, S_BANK) == "keyboard"               # Explorateur : SFZ chargé


def test_returning_to_kit_after_manual_keyboard(win):
    _on(win, S_KIT)
    win._set_input_mode("keyboard", announce=False)     # Ctrl+2 sur le kit
    assert _on(win, S_KIT) is None and win._input_mode == "keyboard"
    _on(win, S_BANK)
    assert _on(win, S_KIT) == "pad"


# ---------------------------------------------------------------------------
# Enregistrement et décompte
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("attr, value", [("recording", True), ("_count_in", 2)])
def test_no_switch_while_recording_or_counting_in(win, attr, value):
    setattr(win._player, attr, value)
    assert _on(win, S_BANK) is None
    assert win._input_mode == "pad"
    setattr(win._player, attr, False if attr == "recording" else 0)
    assert _on(win, S_BANK) == "keyboard"               # la clé n'a pas été retenue


# ---------------------------------------------------------------------------
# Annonce (K6)
# ---------------------------------------------------------------------------

def test_note_appended_to_every_message_of_the_action(win, monkeypatch):
    flushes = []
    import ui.main_window as main_window
    monkeypatch.setattr(main_window.wx, "CallAfter", lambda fn, *a: flushes.append(fn))
    _on(win, S_BANK)
    win._show_status("Piste 3 — FluidR3")
    assert win._status_ctrl.GetString(0) == "Piste 3 — FluidR3 — Mode Clavier"
    win._show_status("Banque chargée")                  # message suivant, même action
    assert win._status_ctrl.GetString(0) == "Banque chargée — Mode Clavier"
    for fn in flushes:
        fn()                                            # fin de l'action
    assert win._status_ctrl.GetString(0) == "Banque chargée — Mode Clavier"
    win._show_status("Lecture")
    assert win._status_ctrl.GetString(0) == "Lecture"


def test_flush_adds_note_when_no_message_followed(win):
    win._show_status("Piste 5")                         # message écrit avant
    _on(win, S_BANK)                                    # CallAfter synchrone : flush
    assert win._status_ctrl.GetString(0) == "Piste 5 — Mode Clavier"
    assert win._mode_note == ""


def test_kit_note_is_mode_pad(win):
    _on(win, S_BANK)
    win._show_status("Piste 1")
    assert _on(win, S_KIT) == "pad"
    assert win._status_ctrl.GetString(0) == "Piste 1 — Mode Pad"


def test_manual_mode_change_still_announced(win):
    win._set_input_mode("keyboard")                     # Ctrl+2 : annonce d'origine
    assert win._status_ctrl.GetString(0).startswith("Mode: Keyboard")


# ---------------------------------------------------------------------------
# Appelants (K5, K7)
# ---------------------------------------------------------------------------

def _spy(win, monkeypatch, name):
    calls = []
    real = getattr(win, name)
    def spy(*a):
        calls.append(a)
        return real(*a)
    monkeypatch.setattr(win, name, spy)
    return calls


def test_go_to_track_applies_rule(win, monkeypatch):
    calls = _spy(win, monkeypatch, "_apply_auto_input_mode")
    win._go_to_track(1)
    assert calls == [()]
    assert win._cur_slot == win._router.slot_for_track(1)


def test_go_to_track_refused_while_recording_does_not_apply(win, monkeypatch):
    calls = _spy(win, monkeypatch, "_apply_auto_input_mode")
    win._player.recording = True
    win._go_to_track(1)
    win._player.recording = False
    assert calls == []


def test_follow_track_slot_applies_rule(win, monkeypatch):
    calls = _spy(win, monkeypatch, "_apply_auto_input_mode")
    win._follow_track_slot()
    assert calls == [()]


def test_pattern_load_sets_keyboard_play_root(win, monkeypatch):
    calls = _spy(win, monkeypatch, "_set_kb_play_root")
    old = win._pattern_list[1]
    old._kb_root_midi = 48                               # pattern d'avant 9b2
    win._apply_pattern_from_store(old)
    assert calls == [(48,)]
    assert win._kb_play_root == 48


# ---------------------------------------------------------------------------
# 9b2 : référence commune du pavé et du contrôleur
# ---------------------------------------------------------------------------

def test_input_base_is_36_and_window_starts_there(win):
    assert win.KB_INPUT_BASE == 36
    assert win.started_kb == (36, [36])                  # relevé à la création


def test_new_pattern_root_36_old_pattern_kept_at_48():
    assert Pattern()._kb_root_midi == 36
    d = Pattern().to_dict()
    d.pop("kb_root_midi")
    p = Pattern()
    p.from_dict(d)
    assert p._kb_root_midi == 48                         # fichier d'avant 9b2
    d["kb_root_midi"] = 60
    p.from_dict(d)
    assert p._kb_root_midi == 60


def test_numpad1_plays_36_then_moves_by_octave(win):
    _on(win, S_BANK)
    assert win._router.kb_notes_input[0] == 36
    win._key_manager.handle(FakeEvent(key=wx.WXK_NUMPAD_ADD))
    assert win._kb_root_midi == 48 and win._router.kb_notes_input[0] == 48
    win._key_manager.handle(FakeEvent(key=wx.WXK_NUMPAD_SUBTRACT))
    win._key_manager.handle(FakeEvent(key=wx.WXK_NUMPAD_SUBTRACT))
    assert win._kb_root_midi == 24 and win._router.kb_notes_input[0] == 24


def test_set_kb_play_root_keeps_input_octave(win):
    _on(win, S_BANK)
    win._key_manager.handle(FakeEvent(key=wx.WXK_NUMPAD_ADD))       # entrée à 48
    win._set_kb_play_root(60)
    assert win._kb_play_root == 60
    assert win._router.kb_notes[0] == 60                 # cases de la grille
    assert win._router.kb_notes_input[0] == 48           # pavé inchangé


def _controller(root):
    """Vrai MidiHandler : un synthé sur la piste 1, mode Clavier, racine
    d'entrée root ; retourne (fenêtre, handler, moteur)."""
    w, h = _live_window()
    r = w._router
    r.assign_slot(0, SYNTH)
    r.wait_loaded()
    w._go_to_track(0)
    w._kb_root_midi = root
    return w, h, r.synth


def test_controller_lowest_key_untransposed_at_start():
    w, h, synth = _controller(36)
    h.on_note_on(36, 100, 0)
    h.on_note_off(36, 0)
    assert synth.plays == [36] and synth.stops == [36]   # comme NumPad1


@pytest.mark.parametrize("root, played", [(48, 48), (24, 24), (60, 60)])
def test_controller_follows_numpad_octave(root, played):
    w, h, synth = _controller(root)
    h.on_note_on(36, 100, 0)
    h.on_note_off(36, 0)
    assert synth.plays == [played] and synth.stops == [played]


def test_controller_offset_uses_input_base_not_play_root():
    """La racine de lecture (pattern d'avant 9b2 à 48) ne transpose pas le
    contrôleur."""
    w, h, synth = _controller(36)
    w._kb_play_root = 48
    h.on_note_on(40, 100, 0)
    assert synth.plays == [40]
