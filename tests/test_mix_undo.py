#python3
"""
    File: tests/test_mix_undo.py
    Undo et projet modifié pour le mute, le solo et le volume des pistes et
    des pads (Phase 7 étape 13c1, docs/DESIGN.md § 13a1), et le pan (Phase 7
    étape 15c1, § 15a1 D1) :
    - _add_mix_undo (D2) : regroupement par clé, fenêtre de 1 s glissante
      (horloge injectée), autre action entre deux, key=None, titre qui suit
      la valeur atteinte (« Volume piste 2: 80 ») ;
    - chaque chemin (D1) : entrée créée, projet modifié, Ctrl+Z rend la
      valeur ; valeur inchangée sans entrée ni marquage ;
    - dialogue de propriétés du pad (D3) : Ok, Annuler, inchangé.
    Les vraies méthodes (ProjectMixin, TrackMixin, PadMixin, KeyManager,
    MidiHandler, PlaybackMixin) tournent sur une fenêtre factice ; seul
    _capture_state est réduit aux réglages de mixage.
    Date: Sun, 25/10/2026
    Author: Coolbrother
"""
import sys
import os
import copy
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

import ui.mw_pads as mw_pads
from undo_manager import UndoManager
from voice_manager import VoiceManager
from track_router import TrackRouter
from track_editor import TrackEditor
from ui.mw_project import ProjectMixin
from ui.mw_tracks import TrackMixin
from ui.mw_pads import PadMixin
from ui.mew_playback import PlaybackMixin
from ui.key_manager import KeyManager
from ui.midi_handler_window import MidiHandler


# ---------------------------------------------------------------------------
# Fenêtre factice
# ---------------------------------------------------------------------------

class _Widget:
    def __init__(self, value=0, focus=False):
        self.value = value
        self.focus = focus
    def GetValue(self):    return self.value
    def SetValue(self, v): self.value = v
    def HasFocus(self):    return self.focus


def _make_router():
    """Vrai TrackRouter sans son __init__ (synthé, kits) : seules les listes
    de mixage servent aux méthodes testées."""
    r = TrackRouter.__new__(TrackRouter)
    n = TrackRouter.NUM_TRACKS
    r._track_mutes   = [False] * n
    r._track_solos   = [False] * n
    r._track_volumes = [100] * n
    r._track_pans    = [0] * n
    r.bank_engine    = None          # sans moteur de banque (17d1)
    return r


class _MixWindow(ProjectMixin, TrackMixin, PadMixin):
    ROWS = 16

    def __init__(self):
        self._undo             = UndoManager()
        self._project_modified = False
        self._project_path     = "test.gvp"
        self._take             = None
        self._player = types.SimpleNamespace(
            voice_manager=VoiceManager(16), _cur_track=0, recording=False)
        self._router        = _make_router()
        self._track_editor  = TrackEditor()
        self._track_list    = _Widget()
        self._vol_ctrls     = [_Widget(100) for _ in range(16)]
        self._pan_ctrls     = [_Widget(0) for _ in range(16)]
        self._mute_btns     = [_Widget(False) for _ in range(16)]
        self._solo_btns     = [_Widget(False) for _ in range(16)]
        self._cur_row       = 0
        self._midi_editor_window = None
        self.status = []
        self.now    = 0.0
        self._mix_clock = lambda: self.now

    # Instantané réduit au mixage (le vrai passe par _flush_pattern_to_store
    # et voice_manager.to_list, docs/DESIGN.md § 13a1 « état des lieux »).
    def _capture_state(self):
        r = self._router
        return copy.deepcopy({
            "mutes": r._track_mutes, "solos": r._track_solos,
            "volumes": r._track_volumes, "pans": r._track_pans,
            "voices": self._player.voice_manager.to_list(),
        })

    def _restore_state(self, state):
        r = self._router
        r._track_mutes   = list(state["mutes"])
        r._track_solos   = list(state["solos"])
        r._track_volumes = list(state["volumes"])
        r._track_pans    = list(state["pans"])
        self._player.voice_manager.from_list(state["voices"])
        self._mark_modified()

    def SetTitle(self, title):            pass
    def _show_status(self, msg):          self.status.append(msg)
    def _refresh_track_list(self):        pass
    def _refresh_voice_display(self, i):  pass
    def _refresh_all_voice_display(self): pass
    def _play(self, idx):                 pass
    def _play_toggle(self):               pass

    # --- raccourcis de test
    def titles(self):
        return [e.title for e in self._undo.history_list()]

    def vm(self):
        return self._player.voice_manager


class _Event:
    def __init__(self, key):
        self._key = key
    def GetKeyCode(self): return self._key
    def Skip(self):       pass


def _ctx(key, shift=False, alt=False, on_track_list=False):
    return types.SimpleNamespace(
        key=key, ukey=0, ctrl=False, shift=shift, alt=alt,
        on_quant_list=False, on_pattern_list=False, on_bpm=False,
        on_volume=False, on_pan=False, on_voice_spin=False,
        on_mode_choice=False, on_scale_choice=False, on_slot_choice=False,
        on_track_list=on_track_list, on_pad_list=False, on_vel_list=False,
        on_midi_port_list=False, on_status_ctrl=False,
    )


def _char(win, letter, shift=False, on_track_list=False):
    km  = KeyManager(win)
    key = ord(letter)
    assert km._handle_chars(_Event(key), _ctx(key, shift=shift, on_track_list=on_track_list))


def _alt(win, key, on_track_list=False):
    km = KeyManager(win)
    assert km._handle_alt(_Event(key), _ctx(key, alt=True, on_track_list=on_track_list))


@pytest.fixture
def win():
    return _MixWindow()


# ---------------------------------------------------------------------------
# _add_mix_undo — regroupement (D2)
# ---------------------------------------------------------------------------

KEY = ("track_volume", 1)

def test_same_key_within_window_groups_and_title_follows_value(win):
    for t, v in ((0.0, 85), (0.5, 90), (0.9, 95)):
        win.now = t
        win._add_mix_undo(f"Volume piste 2: {v}", KEY)
    assert win.titles() == ["Volume piste 2: 95"]


def test_window_slides_with_each_change(win):
    for t in (0.0, 0.9, 1.8, 2.7):          # 2,7 s au total, < 1 s entre deux
        win.now = t
        win._add_mix_undo("Volume piste 2: 80", KEY)
    assert len(win.titles()) == 1


def test_one_second_gap_starts_new_entry(win):
    win._add_mix_undo("Volume piste 2: 80", KEY)
    win.now = 1.0                            # pas « moins de 1 s »
    win._add_mix_undo("Volume piste 2: 85", KEY)
    assert win.titles() == ["Volume piste 2: 85", "Volume piste 2: 80"]


def test_other_key_starts_new_entry(win):
    win._add_mix_undo("Volume piste 2: 80", KEY)
    win.now = 0.1
    win._add_mix_undo("Volume piste 3: 80", ("track_volume", 2))
    win.now = 0.2
    win._add_mix_undo("Volume pad 2: 80", ("pad_volume", 1))
    assert len(win.titles()) == 3


def test_other_action_between_starts_new_entry(win):
    win._add_mix_undo("Volume piste 2: 80", KEY)
    win.now = 0.1
    win._add_undo("Autre action")
    win.now = 0.2
    win._add_mix_undo("Volume piste 2: 85", KEY)
    assert win.titles() == ["Volume piste 2: 85", "Autre action", "Volume piste 2: 80"]


def test_toggle_key_none_never_groups(win):
    win._add_mix_undo("Mute piste 1")
    win._add_mix_undo("Mute piste 1")
    assert win.titles() == ["Mute piste 1", "Mute piste 1"]


def test_toggle_between_two_volume_changes_splits_them(win):
    win._add_mix_undo("Volume piste 2: 80", KEY)
    win._add_mix_undo("Mute piste 2")
    win._add_mix_undo("Volume piste 2: 85", KEY)
    assert len(win.titles()) == 3


def test_change_after_undo_does_not_reuse_undone_entry(win):
    win._router.set_track_volume(1, 50)
    win._set_track_volume_undo(1, 60)
    win._undo_action()
    win.now = 0.2
    win._set_track_volume_undo(1, 70)
    assert win.titles() == ["Volume piste 2: 70"]
    win._undo_action()
    assert win._router.get_track_volume(1) == 50


def test_grouped_change_still_marks_modified(win):
    win._add_mix_undo("Volume piste 2: 80", KEY)
    win._project_modified = False            # sauvegarde entre-temps
    win.now = 0.5
    win._add_mix_undo("Volume piste 2: 85", KEY)
    assert win._project_modified is True
    assert len(win.titles()) == 1


# ---------------------------------------------------------------------------
# Bascules au clavier : X, S, Shift+X, Shift+S (D1)
# ---------------------------------------------------------------------------

def _track_mutes(w): return w._router._track_mutes
def _track_solos(w): return w._router._track_solos
def _pad_mutes(w):   return [v["mute"] for v in w.vm().to_list()]
def _pad_solos(w):   return [v["solo"] for v in w.vm().to_list()]


@pytest.mark.parametrize("letter, on_track_list, read, title", [
    ('X', True,  _track_mutes, "Mute piste 3"),
    ('S', True,  _track_solos, "Solo piste 3"),
    ('X', False, _pad_mutes,   "Mute pad 3"),
    ('S', False, _pad_solos,   "Solo pad 3"),
])
def test_toggle_key_adds_entry_and_undo_restores(win, letter, on_track_list, read, title):
    win._player._cur_track = 2
    win._cur_row = 2
    _char(win, letter, on_track_list=on_track_list)
    assert read(win)[2] is True
    assert win.titles() == [title]
    assert win._project_modified is True
    win._undo_action()
    assert read(win)[2] is False


@pytest.mark.parametrize("letter, on_track_list, read, title", [
    ('X', True,  _track_mutes, "Démuter toutes les pistes"),
    ('S', True,  _track_solos, "Désolo toutes les pistes"),
    ('X', False, _pad_mutes,   "Démuter tous les pads"),
    ('S', False, _pad_solos,   "Désolo tous les pads"),
])
def test_shift_toggle_all_adds_entry_and_undo_restores(win, letter, on_track_list, read, title):
    attr = "mute" if letter == 'X' else "solo"
    if on_track_list:
        read(win)[1] = read(win)[4] = True
    else:
        for i in (1, 4):
            setattr(win.vm().get_voice(i), attr, True)
    _char(win, letter, shift=True, on_track_list=on_track_list)
    assert not any(read(win))
    assert win.titles() == [title]
    assert win._project_modified is True
    win._undo_action()
    assert [i for i, b in enumerate(read(win)) if b] == [1, 4]


@pytest.mark.parametrize("letter, on_track_list", [
    ('X', True), ('S', True), ('X', False), ('S', False),
])
def test_shift_toggle_all_with_nothing_to_do_adds_nothing(win, letter, on_track_list):
    _char(win, letter, shift=True, on_track_list=on_track_list)
    assert win.titles() == []
    assert win._project_modified is False


# ---------------------------------------------------------------------------
# Volume au clavier : Alt+↑/↓ (D1, D2)
# ---------------------------------------------------------------------------

def test_alt_up_track_volume_entry_and_undo(win):
    win._router.set_track_volume(0, 50)
    _alt(win, wx.WXK_UP, on_track_list=True)
    assert win._router.get_track_volume(0) == 55
    assert win.titles() == ["Volume piste 1: 55"]
    assert win._project_modified is True
    win._undo_action()
    assert win._router.get_track_volume(0) == 50


def test_alt_up_burst_gives_one_entry_undone_at_once(win):
    win._router.set_track_volume(0, 50)
    for t in (0.0, 0.3, 0.6):
        win.now = t
        _alt(win, wx.WXK_UP, on_track_list=True)
    assert win.titles() == ["Volume piste 1: 65"]
    win._undo_action()
    assert win._router.get_track_volume(0) == 50


def test_alt_up_track_at_max_adds_nothing(win):
    _alt(win, wx.WXK_UP, on_track_list=True)        # déjà à 100
    assert win.titles() == []
    assert win._project_modified is False
    assert win.status[-1] == "Piste 1: Volume 100"


def test_alt_down_pad_volume_entry_and_undo(win):
    win._cur_row = 4
    _alt(win, wx.WXK_DOWN)
    assert win.vm().get_voice(4).volume == 95
    assert win.titles() == ["Volume pad 5: 95"]
    assert win._project_modified is True
    win._undo_action()
    assert win.vm().get_voice(4).volume == 100


def test_alt_down_pad_at_min_adds_nothing(win):
    win.vm().set_volume(0, 0)
    _alt(win, wx.WXK_DOWN)
    assert win.titles() == []
    assert win._project_modified is False


# ---------------------------------------------------------------------------
# Volume par le contrôleur : CC7 (D1, D2)
# ---------------------------------------------------------------------------

def test_cc7_on_track_list_knob_turn_is_one_entry(win):
    win._track_list.focus = True
    win._router.set_track_volume(0, 80)
    mh = MidiHandler(win)
    for t, value in ((0.0, 127), (0.2, 100), (0.4, 64)):
        win.now = t
        mh.on_cc(7, value, 0)
    assert win._router.get_track_volume(0) == 50
    assert win.titles() == ["Volume piste 1: 50"]
    assert win._project_modified is True
    win._undo_action()
    assert win._router.get_track_volume(0) == 80


def test_cc7_on_pad_sets_spin_and_undo_restores(win):
    win._cur_row = 2
    MidiHandler(win).on_cc(7, 64, 0)
    assert win.vm().get_voice(2).volume == 50
    assert win._vol_ctrls[2].value == 50
    assert win.titles() == ["Volume pad 3: 50"]
    win._undo_action()
    assert win.vm().get_voice(2).volume == 100


def test_cc7_same_value_adds_nothing(win):
    win._track_list.focus = True
    MidiHandler(win).on_cc(7, 127, 0)                # 127 → 100, déjà à 100
    assert win.titles() == []
    assert win._project_modified is False


# ---------------------------------------------------------------------------
# Pan des pistes et des pads (Phase 7 étape 15c1, docs/DESIGN.md § 15a1 D1)
# ---------------------------------------------------------------------------

def test_alt_right_track_pan_entry_and_undo(win):
    _alt(win, wx.WXK_RIGHT, on_track_list=True)
    assert win._router.get_track_pan(0) == 10
    assert win.titles() == ["Pan piste 1: 10"]
    assert win._project_modified is True
    win._undo_action()
    assert win._router.get_track_pan(0) == 0


def test_alt_left_burst_track_pan_is_one_entry_undone_at_once(win):
    for t in (0.0, 0.4, 0.8):
        win.now = t
        _alt(win, wx.WXK_LEFT, on_track_list=True)
    assert win.titles() == ["Pan piste 1: -30"]
    win._undo_action()
    assert win._router.get_track_pan(0) == 0


def test_alt_right_track_pan_at_max_adds_nothing(win):
    win._router.set_track_pan(0, 100)
    _alt(win, wx.WXK_RIGHT, on_track_list=True)
    assert win.titles() == []
    assert win._project_modified is False
    assert win.status[-1] == "Piste 1: Pan 100"


@pytest.mark.parametrize("on_track_list", [True, False])
def test_alt_0_on_centered_pan_adds_nothing(win, on_track_list):
    _alt(win, ord('0'), on_track_list=on_track_list)
    assert win.titles() == []
    assert win._project_modified is False


def test_alt_0_track_pan_entry_and_undo(win):
    win._router.set_track_pan(0, -40)
    _alt(win, ord('0'), on_track_list=True)
    assert win._router.get_track_pan(0) == 0
    assert win.titles() == ["Pan piste 1: 0"]
    win._undo_action()
    assert win._router.get_track_pan(0) == -40


def test_alt_left_pad_pan_entry_and_undo(win):
    win._cur_row = 5
    _alt(win, wx.WXK_LEFT)
    assert win.vm().get_pan(5) == -10
    assert win.titles() == ["Pan pad 6: -10"]
    assert win._project_modified is True
    win._undo_action()
    assert win.vm().get_pan(5) == 0


def test_alt_0_pad_pan_entry_and_undo(win):
    win.vm().set_pan(2, 50)
    win._cur_row = 2
    _alt(win, ord('0'))
    assert win.vm().get_pan(2) == 0
    assert win.titles() == ["Pan pad 3: 0"]
    win._undo_action()
    assert win.vm().get_pan(2) == 50


def test_pan_and_volume_of_same_track_are_separate_entries(win):
    win._router.set_track_volume(0, 50)
    _alt(win, wx.WXK_UP, on_track_list=True)
    win.now = 0.2
    _alt(win, wx.WXK_RIGHT, on_track_list=True)
    win.now = 0.4
    _alt(win, wx.WXK_RIGHT, on_track_list=True)
    assert win.titles() == ["Pan piste 1: 20", "Volume piste 1: 55"]


def test_cc10_on_track_list_knob_turn_is_one_entry(win):
    win._track_list.focus = True
    mh = MidiHandler(win)
    for t, value in ((0.0, 127), (0.2, 96), (0.4, 0)):
        win.now = t
        mh.on_cc(10, value, 0)
    assert win._router.get_track_pan(0) == -100
    assert win.titles() == ["Pan piste 1: -100"]
    assert win._project_modified is True
    win._undo_action()
    assert win._router.get_track_pan(0) == 0


def test_cc10_on_pad_sets_spin_and_undo_restores(win):
    win._cur_row = 4
    MidiHandler(win).on_cc(10, 127, 0)
    assert win.vm().get_pan(4) == 100
    assert win._pan_ctrls[4].value == 100
    assert win.titles() == ["Pan pad 5: 100"]
    win._undo_action()
    assert win.vm().get_pan(4) == 0


def test_cc10_center_on_centered_pan_adds_nothing(win):
    win._track_list.focus = True
    MidiHandler(win).on_cc(10, 64, 0)               # 64 → 0, déjà centré
    assert win.titles() == []
    assert win._project_modified is False


def test_pan_spin_entry_and_undo(win):
    win._pan_ctrls[3].value = -25
    win._on_pan_spin(3)
    assert win.vm().get_pan(3) == -25
    assert win.titles() == ["Pan pad 4: -25"]
    assert win._project_modified is True
    assert win.status[-1] == "Pad 4: Pan -25"
    win._undo_action()
    assert win.vm().get_pan(3) == 0


def test_pan_spin_unchanged_adds_nothing(win):
    win._on_pan_spin(3)                               # SpinCtrl à 0 = voix
    assert win.titles() == []
    assert win._project_modified is False


# ---------------------------------------------------------------------------
# Widgets des pads : SpinCtrl Volume, boutons Mute et Solo (D1)
# ---------------------------------------------------------------------------

def test_vol_spin_entry_and_undo(win):
    win._vol_ctrls[6].value = 70
    win._on_vol_spin(6)
    assert win.vm().get_voice(6).volume == 70
    assert win.titles() == ["Volume pad 7: 70"]
    assert win._project_modified is True
    win._undo_action()
    assert win.vm().get_voice(6).volume == 100


def test_vol_spin_unchanged_adds_nothing(win):
    win._on_vol_spin(6)                               # SpinCtrl à 100 = voix
    assert win.titles() == []
    assert win._project_modified is False


@pytest.mark.parametrize("handler, attr, title", [
    ("_on_mute_btn", "mute", "Mute pad 2"),
    ("_on_solo_btn", "solo", "Solo pad 2"),
])
def test_mute_solo_buttons_entry_and_undo(win, handler, attr, title):
    getattr(win, handler)(1)
    assert getattr(win.vm().get_voice(1), attr) is True
    assert win.titles() == [title]
    assert win._project_modified is True
    win._undo_action()
    assert getattr(win.vm().get_voice(1), attr) is False


# ---------------------------------------------------------------------------
# Éditeur MIDI : X et S sur la sélection de pistes (D1)
# ---------------------------------------------------------------------------

class _Editor(PlaybackMixin):
    def __init__(self, parent):
        self._parent = parent
        self.status  = []
    def _set_status(self, msg): self.status.append(msg)


def test_editor_multi_track_mute_is_one_entry_undone_at_once(win):
    te = win._track_editor
    te.select_one(1)
    te.toggle_track(3)
    _Editor(win)._toggle_track_mute()
    assert win._router._track_mutes[1] and win._router._track_mutes[3]
    assert win.titles() == ["Mute pistes 2, 4"]
    assert win._project_modified is True
    win._undo_action()
    assert not any(win._router._track_mutes)


# ---------------------------------------------------------------------------
# Dialogue de propriétés du pad (D3)
# ---------------------------------------------------------------------------

class _FakePadDialog:
    """Remplace PadPropertiesDialog : applique `live` en aperçu (on_change),
    puis rend `result` et les valeurs `final`."""
    result = wx.ID_OK
    live   = None
    final  = None

    def __init__(self, parent, pad_idx, volume, pan, mute, solo, duration_ms,
                 on_change=None, on_play=None, on_play_toggle=None):
        self._vals = (volume, pan, mute, solo, duration_ms)
        if self.live is not None:
            on_change(*self.live)
        if self.final is not None:
            self._vals = self.final

    def ShowModal(self):        return self.result
    def get_volume(self):       return self._vals[0]
    def get_pan(self):          return self._vals[1]
    def get_mute(self):         return self._vals[2]
    def get_solo(self):         return self._vals[3]
    def get_duration_ms(self):  return self._vals[4]
    def Destroy(self):          pass


def _pad_dialog(monkeypatch, win, result, live=None, final=None):
    dlg = type("_Dlg", (_FakePadDialog,), dict(result=result, live=live, final=final))
    monkeypatch.setattr(mw_pads, "PadPropertiesDialog", dlg)
    win._pad_properties_dialog()


def _voice(win, i):
    v = win.vm().get_voice(i)
    return (v.volume, v.pan, v.mute, v.solo, v.duration_ms)


def test_pad_dialog_ok_changed_keeps_entry_and_undo_restores(win, monkeypatch):
    win._cur_row = 3
    orig = _voice(win, 3)
    new  = (40, -20, True, False, 800)
    _pad_dialog(monkeypatch, win, wx.ID_OK, live=new, final=new)
    assert _voice(win, 3) == new
    assert win.titles() == ["Propriétés pad 4"]
    assert win._project_modified is True
    win._undo_action()
    assert _voice(win, 3) == orig


@pytest.mark.parametrize("was_modified", [False, True])
def test_pad_dialog_ok_unchanged_removes_entry(win, monkeypatch, was_modified):
    win._project_modified = was_modified
    _pad_dialog(monkeypatch, win, wx.ID_OK)
    assert win.titles() == []
    assert win._project_modified is was_modified
    assert win.status[-1] == "Pad 1: propriétés inchangées"


@pytest.mark.parametrize("was_modified", [False, True])
def test_pad_dialog_cancel_restores_values_and_removes_entry(win, monkeypatch, was_modified):
    win._project_modified = was_modified
    orig = _voice(win, 0)
    _pad_dialog(monkeypatch, win, wx.ID_CANCEL, live=(10, 50, True, True, 100),
                final=(10, 50, True, True, 100))
    assert _voice(win, 0) == orig
    assert win.titles() == []
    assert win._project_modified is was_modified
    assert win.status[-1] == "Pad 1: modifications annulées"


def test_pad_dialog_keeps_earlier_entries(win, monkeypatch):
    win._add_undo("Avant")
    _pad_dialog(monkeypatch, win, wx.ID_CANCEL)
    assert win.titles() == ["Avant"]
