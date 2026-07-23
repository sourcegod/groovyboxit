#python3
"""
    File: tests/test_midi_virtual_keyboard.py
    Tests unitaires — VirtualKeyboardMixin (Phase 6 étape 7f). Utilise un
    objet factice (duck-typing) au lieu d'un vrai wx.Frame : ces méthodes
    sont de la pure orchestration (Rack/TrackRouter/SoundManager + status),
    sans logique wx propre à tester.
    Date: Fri, 24/07/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rack import InstrumentType
import ui.midi_virtual_keyboard as vkmod


class _FakeListBox:
    def __init__(self):
        self._sel = 0
        self.set_string_calls = []

    def SetSelection(self, idx):
        self._sel = idx

    def GetSelection(self):
        return self._sel

    def SetString(self, idx, label):
        self.set_string_calls.append((idx, label))


class _FakeStatusCtrl:
    def __init__(self):
        self.last = None

    def SetString(self, idx, msg):
        self.last = msg


class _FakeSlot:
    def __init__(self, type_):
        self.type = type_


class _FakeRack:
    def __init__(self, slot_type):
        self._slot = _FakeSlot(slot_type)

    def get_slot(self, idx):
        return self._slot


class _FakeSynth:
    def __init__(self):
        self.played = []

    def play(self, midi, volume_factor=1.0, pan=0, maxtime_ms=500):
        self.played.append((midi, volume_factor, maxtime_ms))


class _FakeKitSynth:
    def __init__(self, loaded=True):
        self._loaded = loaded
        self.played = []

    def is_loaded(self):
        return self._loaded

    def play(self, midi, volume_factor=1.0, pan=0, maxtime_ms=500):
        self.played.append((midi, volume_factor, maxtime_ms))


class _FakeRouter:
    def __init__(self, ready=True, kit_synth=None):
        self._ready         = ready
        self.synth           = _FakeSynth()
        self.kit_synth        = kit_synth
        self.preview_loaded  = []

    def synth_ready(self):
        return self._ready

    def load_slot_preview(self, slot_idx):
        self.preview_loaded.append(slot_idx)


class _FakeSoundManager:
    def __init__(self, note_map=None):
        self.note_map      = note_map or {}
        self.played_notes  = []

    def play_note(self, midi, volume_factor=1.0):
        self.played_notes.append((midi, volume_factor))


class _FakeParent:
    def __init__(self, slot_type, router=None, snd=None, cur_slot=0):
        self._rack     = _FakeRack(slot_type)
        self._router   = router or _FakeRouter()
        self._snd      = snd or _FakeSoundManager()
        self._cur_slot = cur_slot


class _FakeVkWindow:
    """Objet minimal exposant les vraies méthodes du mixin."""
    _play_virtual_keyboard_note = vkmod.VirtualKeyboardMixin._play_virtual_keyboard_note
    _vk_move                    = vkmod.VirtualKeyboardMixin._vk_move
    _on_vk_listbox_select       = vkmod.VirtualKeyboardMixin._on_vk_listbox_select

    def __init__(self, parent, vk_note=48):
        self._parent          = parent
        self._vk_lb            = _FakeListBox()
        self._status_ctrl      = _FakeStatusCtrl()
        self._vk_note          = vk_note
        self._skip_vk_announce = False

    def _set_status(self, msg):
        self._status_ctrl.SetString(0, msg)


# ---------------------------------------------------------------------------
# midi_display_name
# ---------------------------------------------------------------------------

def test_midi_display_name_c4():
    assert vkmod.midi_display_name(48) == "C4"


def test_midi_display_name_c0():
    assert vkmod.midi_display_name(0) == "C0"


def test_midi_display_name_sharp():
    assert vkmod.midi_display_name(49) == "C#4"


# ---------------------------------------------------------------------------
# midi_display_label (anglo + solfège FR, pour la listbox et les annonces)
# ---------------------------------------------------------------------------

def test_midi_display_label_c4():
    assert vkmod.midi_display_label(48) == "C4: Do4"


def test_midi_display_label_sharp():
    assert vkmod.midi_display_label(49) == "C#4: Do#4"


def test_midi_display_label_c5():
    assert vkmod.midi_display_label(60) == "C5: Do5"


# ---------------------------------------------------------------------------
# _play_virtual_keyboard_note — SYNTH
# ---------------------------------------------------------------------------

def test_play_synth_ready():
    parent = _FakeParent(InstrumentType.SYNTH)
    win = _FakeVkWindow(parent)
    win._play_virtual_keyboard_note(60)
    assert parent._router.synth.played == [(60, 1.0, 500)]


def test_play_synth_not_ready_loads_preview():
    router = _FakeRouter(ready=False)
    parent = _FakeParent(InstrumentType.SYNTH, router=router, cur_slot=3)
    win = _FakeVkWindow(parent)
    win._play_virtual_keyboard_note(60)
    assert router.preview_loaded == [3]
    assert router.synth.played == []


# ---------------------------------------------------------------------------
# _play_virtual_keyboard_note — KIT
# ---------------------------------------------------------------------------

def test_play_kit_with_note_map():
    snd = _FakeSoundManager(note_map={60: object()})
    parent = _FakeParent(InstrumentType.KIT, snd=snd)
    win = _FakeVkWindow(parent)
    win._play_virtual_keyboard_note(60)
    assert snd.played_notes == [(60, 1.0)]


def test_play_kit_without_note_map_uses_kit_synth():
    kit_synth = _FakeKitSynth(loaded=True)
    router = _FakeRouter(kit_synth=kit_synth)
    parent = _FakeParent(InstrumentType.KIT, router=router)
    win = _FakeVkWindow(parent)
    win._play_virtual_keyboard_note(60)
    assert kit_synth.played == [(60, 1.0, 500)]


def test_play_kit_without_note_map_or_kit_synth_is_silent():
    parent = _FakeParent(InstrumentType.KIT)
    win = _FakeVkWindow(parent)
    win._play_virtual_keyboard_note(60)   # ne doit pas lever d'exception
    assert parent._snd.played_notes == []


def test_play_kit_synth_not_loaded_is_silent():
    kit_synth = _FakeKitSynth(loaded=False)
    router = _FakeRouter(kit_synth=kit_synth)
    parent = _FakeParent(InstrumentType.KIT, router=router)
    win = _FakeVkWindow(parent)
    win._play_virtual_keyboard_note(60)
    assert kit_synth.played == []


# ---------------------------------------------------------------------------
# _vk_move
# ---------------------------------------------------------------------------

def test_vk_move_up_plays_and_updates_selection():
    parent = _FakeParent(InstrumentType.SYNTH)
    win = _FakeVkWindow(parent, vk_note=48)
    win._vk_move(1)
    assert win._vk_note == 49
    assert win._vk_lb.GetSelection() == 49
    assert parent._router.synth.played == [(49, 1.0, 500)]
    assert win._status_ctrl.last == "Clavier virtuel: (C#4: Do#4)"


def test_vk_move_forces_name_change_via_set_string():
    """SetSelection() seul n'émet pas toujours NAME_CHANGE (AT-SPI) ; SetString()
    sur la ligne sélectionnée force Orca à l'annoncer (SPECS.md accessibilité)."""
    parent = _FakeParent(InstrumentType.SYNTH)
    win = _FakeVkWindow(parent, vk_note=48)
    win._vk_move(1)
    assert win._vk_lb.set_string_calls == [(49, "C#4: Do#4")]


def test_vk_move_down():
    parent = _FakeParent(InstrumentType.SYNTH)
    win = _FakeVkWindow(parent, vk_note=48)
    win._vk_move(-1)
    assert win._vk_note == 47


def test_vk_move_clamped_at_upper_bound():
    parent = _FakeParent(InstrumentType.SYNTH)
    win = _FakeVkWindow(parent, vk_note=127)
    win._vk_move(1)
    assert win._vk_note == 127
    assert win._status_ctrl.last == "Clavier virtuel: déjà à la borne"
    assert parent._router.synth.played == []


def test_vk_move_clamped_at_lower_bound():
    parent = _FakeParent(InstrumentType.SYNTH)
    win = _FakeVkWindow(parent, vk_note=0)
    win._vk_move(-1)
    assert win._vk_note == 0
    assert win._status_ctrl.last == "Clavier virtuel: déjà à la borne"


def test_vk_move_sets_skip_announce_flag():
    parent = _FakeParent(InstrumentType.SYNTH)
    win = _FakeVkWindow(parent, vk_note=48)
    win._vk_move(1)
    assert win._skip_vk_announce is True


# ---------------------------------------------------------------------------
# _on_vk_listbox_select
# ---------------------------------------------------------------------------

def test_on_vk_listbox_select_plays_and_updates_note():
    parent = _FakeParent(InstrumentType.SYNTH)
    win = _FakeVkWindow(parent, vk_note=48)
    win._vk_lb.SetSelection(60)
    win._on_vk_listbox_select(None)
    assert win._vk_note == 60
    assert parent._router.synth.played == [(60, 1.0, 500)]
    assert win._status_ctrl.last == "Clavier virtuel: (C5: Do5)"


def test_on_vk_listbox_select_skips_announce_once():
    parent = _FakeParent(InstrumentType.SYNTH)
    win = _FakeVkWindow(parent, vk_note=48)
    win._skip_vk_announce = True
    win._vk_lb.SetSelection(60)
    win._on_vk_listbox_select(None)
    assert win._vk_note == 60
    assert parent._router.synth.played == []   # pas joué, juste synchronisé
    assert win._skip_vk_announce is False       # flag consommé
