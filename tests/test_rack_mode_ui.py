"""
    File: tests/test_rack_mode_ui.py
    Mode Rack 16 canaux, interface (Phase 8 étape 5e1, tests de 5d1 ;
    docs/DESIGN.md § Phase 8 étape 5a, M2, M4, M7, M12, M14-M16) : case des
    propriétés du pattern et Undo, libellé des pistes, Ctrl+T, slot courant
    qui suit le canal, Program Change reçu, kit sans renommer les pads,
    propriétés de piste où le slot est le canal, changement de pattern.
    Date: Sun, 01/11/2026
    Author: Coolbrother
"""

import os
import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import wx

import track_router as tr_mod
import ui.midi_handler_window as mh
from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_PATCH, bank_header, with_bank_header
from player.drum_player import DrumPlayer
from rack import Rack, InstrumentType
from track_router import TrackRouter
from ui.dialogs_properties import PatternPropertiesDialog, TrackPropertiesDialog
from ui.mw_pads import PadMixin
from ui.mw_patterns import PatternMixin
from ui.mw_tracks import TrackMixin
from test_bank_slot import FakeBankEngine, FakeSoundManager, FakeTimer, FakeSynthEngine

SF = "/fake/FluidR3_GM.sf2"
SYNTH, BANK, KIT = 1, 5, 9          # slots 2, 6 et 10 = canaux 2, 6 et 10


_APP = None


class _Synth(FakeSynthEngine):
    def stop_all_voices(self):
        pass


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """wx.App présente (d'autres fichiers détruisent la leur) ; pas de vrai
    Timer ni de vrai SynthEngine dans track_router."""
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    FakeTimer.created = []
    monkeypatch.setattr(tr_mod, "threading",
                        types.SimpleNamespace(Timer=FakeTimer, Thread=threading.Thread))
    monkeypatch.setattr(tr_mod, "SynthEngine", _Synth)


class _Evt:
    def Skip(self):
        pass


# ---------------------------------------------------------------------------
# Fenêtre factice : pistes, patterns et pads sur un vrai TrackRouter
# ---------------------------------------------------------------------------

class _Snd(FakeSoundManager):
    """Sons du kit : chargement noté, libellés du kit rendus."""

    def __init__(self):
        super().__init__()
        self.kit_path    = None
        self.loaded      = []
        self.mute_groups = [0] * 16
        self.gm_note_map = {}
        self.note_map    = {}

    def load_kit(self, path):
        self.loaded.append(path)
        self.kit_path = os.path.abspath(path)
        return [f"Kit pad {i + 1}" for i in range(16)], [""] * 16

    def load_sounds(self):
        self.kit_path = None


class _Silent:
    def stop_all(self):           pass
    def play_sound(self, *a):     pass
    def play_note(self, *a):      pass
    def play_metronome(self, *a): pass


class _RackWin(TrackMixin, PatternMixin, PadMixin):
    def __init__(self, rack_mode=True, kit_path=""):
        rack = Rack()
        rack.set_slot(SYNTH, InstrumentType.SYNTH, "Piano WAV", {"patch": "p"})
        rack.set_slot(BANK,  InstrumentType.BANK,  "FluidR3",   {"bank_slot": 0})
        rack.set_slot(KIT,   InstrumentType.KIT,   "808",       {"kit": kit_path})
        rack.set_bank_file(0, SF)
        self._rack   = rack
        self._snd    = _Snd()
        self.statuses, self.undos, self.labels = [], [], []
        self._router = TrackRouter(rack, "/fake", self._snd, lambda m: None,
                                   bank_engine=FakeBankEngine(), schedule=lambda *a: None)
        self._router._track_slots[:] = [BANK] * 16
        self._router.sync_bank_files()
        self._player = DrumPlayer(_Silent())
        self._player._pattern._rack_mode = rack_mode
        self._router.rack_mode = rack_mode
        self._pattern_list = [Pattern(), Pattern()]
        self._pattern_list[0]._rack_mode = rack_mode
        self._cur_pattern_idx = 0
        self._pattern_cache_dirty = set()
        self._cur_slot     = BANK
        self._slot_choice  = MagicMock()
        self._bpm_ctrl     = MagicMock()
        self._track_editor = SimpleNamespace(is_selected=lambda i: False)
        self._midi_editor_window = None

    def _refresh_track_list(self):
        self.labels = [self._track_label(i) for i in range(4)]

    def _refresh_grid(self):              pass
    def _refresh_pad_list(self):          pass
    def _refresh_pattern_listbox(self):   pass
    def _refresh_all_voice_display(self): pass
    def _play_toggle(self):               pass
    def _show_status(self, msg):          self.statuses.append(msg)
    def _add_undo(self, title):           self.undos.append(title)
    def _pop_last_undo(self):             self.undos.append("pop")


def _channels(win, channels):
    for t, ch in enumerate(channels):
        win._router._track_channels[t] = ch
        win._router._track_cur_channels[t] = ch


def _grid(t=0):
    return TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=t)


# ---------------------------------------------------------------------------
# Propriétés du pattern (M2)
# ---------------------------------------------------------------------------

def _pattern_dlg(rack_mode=False):
    frame = wx.Frame(None)
    dlg = PatternPropertiesDialog(frame, 0, "P", 0, 1, 16, True, 999,
                                  Pattern.VALID_RESOLUTIONS, rack_mode=rack_mode)
    return frame, dlg


def test_pattern_dialog_rack_checkbox():
    frame, dlg = _pattern_dlg()
    assert dlg._rack.GetLabel() == "Mode Rack 16 canaux (canal N → slot N)"
    assert dlg.get_rack_mode() is False
    dlg.Destroy()
    dlg = PatternPropertiesDialog(frame, 0, "P", 0, 1, 16, True, 999,
                                  Pattern.VALID_RESOLUTIONS, rack_mode=True)
    assert dlg.get_rack_mode() is True
    dlg._rack.SetValue(False)
    assert dlg.get_rack_mode() is False
    dlg.Destroy()
    frame.Destroy()


def test_pattern_dialog_rack_checkbox_after_loop_in_tab_order():
    frame, dlg = _pattern_dlg()
    children = list(dlg.GetChildren())
    assert children.index(dlg._rack) == children.index(dlg._loop) + 1
    assert children.index(dlg._rack) < children.index(dlg._actions)
    dlg.Destroy()
    frame.Destroy()


def _fake_pattern_dlg(rack_mode, action="Courant", num_bars=1, num_steps=16):
    class FakeDlg:
        def __init__(self, *a, **kw): FakeDlg.kwargs = kw
        def ShowModal(self):       return wx.ID_OK
        def get_name(self):        return ""
        def get_start_bar(self):   return 0
        def get_num_bars(self):    return num_bars
        def get_num_steps(self):   return num_steps
        def get_num_beats(self):   return 4
        def get_denominator(self): return 4
        def get_resolution(self):  return num_steps
        def get_tempo(self):       return None
        def get_looping(self):     return True
        def get_rack_mode(self):   return rack_mode
        def get_action(self):      return action
        def Destroy(self):         pass
    return FakeDlg


def _properties(win, fake):
    with patch("ui.mw_patterns.PatternPropertiesDialog", fake):
        win._pattern_properties_dialog()


def test_pattern_properties_passes_current_rack_mode():
    win = _RackWin(rack_mode=True)
    fake = _fake_pattern_dlg(True)
    _properties(win, fake)
    assert fake.kwargs["rack_mode"] is True


def test_pattern_properties_enables_rack_mode_with_its_undo():
    win = _RackWin(rack_mode=False)
    _properties(win, _fake_pattern_dlg(True))
    assert win.undos == ["Mode Rack pattern 01 : activé"]
    assert win._pattern_list[0]._rack_mode is True
    assert win._player._pattern._rack_mode is True
    assert win._router.rack_mode is True
    assert 0 in win._pattern_cache_dirty
    assert "Pattern 01: mode Rack 16 canaux activé — le canal N joue le slot N" in win.statuses


def test_pattern_properties_disables_rack_mode():
    win = _RackWin(rack_mode=True)
    _properties(win, _fake_pattern_dlg(False))
    assert win.undos == ["Mode Rack pattern 01 : désactivé"]
    assert win._router.rack_mode is False and win._pattern_list[0]._rack_mode is False
    assert "Pattern 01: mode Rack 16 canaux désactivé" in win.statuses


def test_pattern_properties_rack_mode_with_resize_keeps_resize_undo():
    win = _RackWin(rack_mode=False)
    _properties(win, _fake_pattern_dlg(True, num_bars=2))
    assert win.undos == ["Redimensionner pattern 01"]
    assert win._router.rack_mode is True and win._player._pattern._num_bars == 2


def test_pattern_properties_rack_mode_unchanged_does_nothing():
    win = _RackWin(rack_mode=False)
    _properties(win, _fake_pattern_dlg(False))
    assert win.undos == ["Redimensionner pattern 01"]
    assert win._router.rack_mode is False
    assert not any("mode Rack" in s for s in win.statuses)


def test_set_rack_mode_chases_and_follows_slot():
    win = _RackWin(rack_mode=False)
    _channels(win, [SYNTH])
    win._set_rack_mode(True)
    assert win._cur_slot == SYNTH
    win._slot_choice.SetSelection.assert_called_with(SYNTH)
    assert win.labels[0].startswith("  Track_01 - Canal 2 → Slot_02 Piano WAV")
    win._set_rack_mode(False)
    assert win._cur_slot == BANK                      # la piste retrouve son slot


# ---------------------------------------------------------------------------
# Libellés (M14)
# ---------------------------------------------------------------------------

def test_rack_channel_desc():
    win = _RackWin()
    assert win._rack_channel_desc(SYNTH) == "Slot_02 Piano WAV"
    assert win._rack_channel_desc(3) == "Slot_04 vide → banque GM (Slot_06 FluidR3)"
    win._rack.clear_slot(BANK)
    assert win._rack_channel_desc(3) == "Slot_04 vide, muet"


def test_track_label_in_rack_mode():
    win = _RackWin()
    _channels(win, [SYNTH, 3, KIT])
    win._player.voice_manager.set_name(1, "Basse")
    labels = [win._track_label(t) for t in range(3)]
    assert labels[0] == "  Track_01 - Canal 2 → Slot_02 Piano WAV"
    assert labels[1].startswith("  Track_02 (Basse) - Canal 4 → Slot_04 vide → banque GM "
                                "(Slot_06 FluidR3) - ")      # + nom du preset du canal
    assert labels[2] == "  Track_03 - Canal 10 → Slot_10 808"


def test_track_label_follows_current_channel():
    win = _RackWin()
    _channels(win, [SYNTH])
    win._router._track_cur_channels[0] = KIT          # Program Change passé
    assert win._track_label(0) == "  Track_01 - Canal 10 → Slot_10 808"


def test_track_label_normal_mode_unchanged():
    win = _RackWin(rack_mode=False)
    win._router._track_slots[0] = SYNTH
    assert win._track_label(0) == "  Track_01 - Slot_02 - Piano WAV"


def test_track_label_keeps_mute_flag_in_rack_mode():
    win = _RackWin()
    _channels(win, [SYNTH])
    win._router.toggle_track_mute(0)
    assert win._track_label(0).endswith(" [M]")


# ---------------------------------------------------------------------------
# Ctrl+T (M7)
# ---------------------------------------------------------------------------

def test_ctrl_t_in_rack_mode_moves_track_to_slot_channel():
    win = _RackWin()
    _channels(win, [0])
    win._cur_slot = SYNTH
    win._assign_track_slot()
    r = win._router
    assert r.get_track_channel(0) == SYNTH and r.track_channel_now(0) == SYNTH
    assert r._track_slots[0] == BANK                  # slot propre intact (M9)
    assert win.undos == ["Piste 1 → canal 2"]
    assert win.statuses[-1] == "Piste 1 → canal 2 — Slot_02 Piano WAV"
    assert win._cur_slot == SYNTH


def test_ctrl_t_in_rack_mode_rewrites_header_on_new_channel():
    win = _RackWin()
    _channels(win, [3])
    live = win._player._pattern
    live._tape[0] = with_bank_header([_grid()], 3, 33, 8, 0)
    win._cur_slot = KIT
    win._assign_track_slot()
    assert bank_header(live._tape[0]) == (KIT, 33, 8, 0)
    assert win._router.track_channel_now(0) == KIT    # la poursuite garde le canal


def test_ctrl_t_in_rack_mode_same_channel_does_nothing():
    win = _RackWin()
    _channels(win, [SYNTH])
    win._cur_slot = SYNTH
    win._assign_track_slot()
    assert win.undos == []
    assert win.statuses == ["Piste 1: déjà au canal 2 — Slot_02 Piano WAV"]


def test_ctrl_t_normal_mode_assigns_slot():
    win = _RackWin(rack_mode=False)
    win._refresh_track_list = lambda: None
    win._cur_slot = SYNTH
    win._assign_track_slot()
    assert win._router._track_slots[0] == SYNTH and win.undos == []


# ---------------------------------------------------------------------------
# Slot courant qui suit la piste (M4, M16) et kit sans renommage (M12)
# ---------------------------------------------------------------------------

def test_follow_track_slot_loads_synth_preview():
    win = _RackWin()
    _channels(win, [SYNTH])
    win._follow_track_slot()
    assert win._cur_slot == SYNTH and win._router._synth_slot_idx == SYNTH


def test_follow_track_slot_bank_preview_on_fallback():
    win = _RackWin()
    _channels(win, [3])
    win._follow_track_slot()
    assert win._cur_slot == BANK and win._router.synth is win._router._bank_preview


def test_go_to_track_follows_channel_slot():
    win = _RackWin()
    _channels(win, [0, SYNTH])
    win._go_to_track(1)
    assert win._cur_slot == SYNTH
    assert win.statuses[-1] == "Piste 2 — Piano WAV"


def test_load_kit_slot_does_not_rename_pads_in_rack_mode(tmp_path):
    path = tmp_path / "kit.json"
    path.write_text("{}")
    win = _RackWin(kit_path=str(path))
    win._player.voice_manager.set_name(0, "Batterie")
    win._load_kit_slot(KIT)
    assert win._snd.loaded == [str(path)]
    assert win._player.voice_manager.get_name(0) == "Batterie"


def test_load_kit_slot_renames_pads_in_normal_mode(tmp_path):
    path = tmp_path / "kit.json"
    path.write_text("{}")
    win = _RackWin(rack_mode=False, kit_path=str(path))
    win._kit_status = lambda: "kit"
    win._load_kit_slot(KIT)
    assert win._player.voice_manager.get_name(0) == "Kit pad 1"


def test_go_to_kit_track_in_rack_mode_keeps_track_names(tmp_path):
    path = tmp_path / "kit.json"
    path.write_text("{}")
    win = _RackWin(kit_path=str(path))
    _channels(win, [0, KIT])
    win._player.voice_manager.set_name(1, "Batterie")
    win._go_to_track(1)
    assert win._snd.loaded == [str(path)]
    assert win._player.voice_manager.get_name(1) == "Batterie"


# ---------------------------------------------------------------------------
# Program Change reçu du contrôleur (M3, M4, M16)
# ---------------------------------------------------------------------------

def _handler(win):
    win._input_mode = "pads"
    return mh.MidiHandler(win)


def test_live_program_change_on_synth_channel_message():
    win = _RackWin()
    _channels(win, [SYNTH])
    _handler(win).on_program_change(40, 7)            # canal du contrôleur ignoré (M4)
    assert win._router._track_slots[0] == BANK        # pas de pont
    assert win._router.track_channel_now(0) == SYNTH
    assert win.statuses[-1] == ("Piste 1: Program Change 40 — canal 2, Slot_02 Piano WAV "
                                "(programme sans effet sur ce slot)")


def test_live_program_change_on_bank_channel_names_preset():
    win = _RackWin()
    _channels(win, [3])
    _handler(win).on_program_change(33, 0)
    msg = win.statuses[-1]
    assert msg.startswith("Piste 1: Program Change 33 — canal 4, Slot_04 vide → banque GM")
    assert "sans effet" not in msg


def test_live_program_change_recorded_on_track_channel():
    win = _RackWin()
    _channels(win, [SYNTH])
    win._player.recording = True
    recorded = []
    win._player.record_program_change = lambda p, ch: recorded.append((p, ch))
    _handler(win).on_program_change(12, 7)
    assert recorded == [(12, SYNTH)]                  # O7 : canal de la piste


def test_live_program_change_normal_mode_keeps_bridge_message():
    win = _RackWin(rack_mode=False)
    win._router._track_slots[0] = KIT
    _handler(win).on_program_change(17, 0)
    assert win.statuses[-1] == "Piste 1: Program Change → Slot 2"


# ---------------------------------------------------------------------------
# Propriétés de piste (M15)
# ---------------------------------------------------------------------------

def _track_dlg(win, channel, received=None):
    frame = wx.Frame(None)
    r = win._router
    instruments = [r.channel_instrument(c) for c in range(16)]
    dlg = TrackPropertiesDialog(
        frame, 0, win._rack, r.slot_for_track(0), 100, 0, False, False,
        on_change=(lambda *a: received.append(a)) if received is not None else None,
        channel=channel,
        slot_program=lambda s: ({InstrumentType.SYNTH: "synth"}.get(win._rack.get_slot(s).type),
                                win._rack.get_slot(s).gm_program()),
        slot_gm_tuning=win._slot_gm_tuning,
        bank_info=lambda s, c, m=None, l=None: win._bank_info(s, c, m, l, instruments),
        rack_slot_of=r.rack_slot_idx,
        channel_labels=[f"Canal {c + 1} — {win._rack_channel_desc(c)}" for c in range(16)])
    return frame, dlg


def test_track_dialog_rack_slot_is_channel_and_labels():
    win = _RackWin()
    _channels(win, [3])
    frame, dlg = _track_dlg(win, 3)
    assert dlg.get_slot_idx() == 3                    # slot N = canal N, même vide
    assert dlg._channels.GetString(1) == "Canal 2 — Slot_02 Piano WAV"
    assert dlg._channels.GetString(3) == "Canal 4 — Slot_04 vide → banque GM (Slot_06 FluidR3)"
    assert dlg.get_msb() is not None                  # le canal joue la banque de repli
    dlg.Destroy()
    frame.Destroy()


def test_track_dialog_rack_channel_change_moves_slot_and_programs():
    win = _RackWin()
    _channels(win, [3])
    received = []
    frame, dlg = _track_dlg(win, 3, received)
    dlg._channels.SetSelection(SYNTH)
    dlg._on_channel_change(_Evt())
    assert dlg.get_slot_idx() == SYNTH
    assert dlg.get_msb() is None and dlg._program_label.GetLabel() == "Programme GM du slot :"
    assert dlg._transpose.IsEnabled()                 # réglages GM du synthé
    assert received[-1][0] == SYNTH and received[-1][5] == SYNTH
    dlg.Destroy()
    frame.Destroy()


def test_track_dialog_rack_slot_change_moves_channel():
    win = _RackWin()
    _channels(win, [SYNTH])
    received = []
    frame, dlg = _track_dlg(win, SYNTH, received)
    dlg._slots.SetSelection(7)                        # slot vide → banque de repli
    dlg._on_slot_change(_Evt())
    assert dlg.get_channel() == 7
    assert dlg.get_msb() is not None and dlg._program_label.GetLabel() == "Programme du canal 8 :"
    dlg.Destroy()
    frame.Destroy()


def _scripted_track_dlg(result, channel=None):
    """Dialogue factice : enregistre ses arguments ; channel : canal choisi
    (le slot suit, comme le vrai dialogue en mode Rack)."""
    class FakeDlg:
        def __init__(self, parent, tidx, rack, slot, vol, pan, mute, solo, **kw):
            FakeDlg.kw, FakeDlg.slot = kw, slot
            ch = kw["channel"] if channel is None else channel
            played = kw["rack_slot_of"](ch) if kw.get("rack_slot_of") else slot
            info = kw["bank_info"](played, ch)
            self.v = [ch if kw.get("rack_slot_of") else slot, vol, pan, mute, solo, ch,
                      info["program"] if info else kw["slot_program"](played)[1],
                      *kw["slot_gm_tuning"](played),
                      info["msb"] if info else None, info["lsb"] if info else None]
            if channel is not None:
                kw["on_change"](*self.v)

        def ShowModal(self):     return result
        def get_slot_idx(self):  return self.v[0]
        def get_volume(self):    return self.v[1]
        def get_pan(self):       return self.v[2]
        def get_mute(self):      return self.v[3]
        def get_solo(self):      return self.v[4]
        def get_channel(self):   return self.v[5]
        def get_program(self):   return self.v[6]
        def get_transpose(self): return self.v[7]
        def get_gain_db(self):   return self.v[8]
        def get_msb(self):       return self.v[9]
        def get_lsb(self):       return self.v[10]
        def Destroy(self):       pass
    return FakeDlg


def _track_props(win, fake):
    with patch("ui.mw_tracks.TrackPropertiesDialog", fake):
        win._track_properties_dialog()


def test_track_properties_rack_mode_passes_channel_as_slot():
    win = _RackWin()
    _channels(win, [3])
    fake = _scripted_track_dlg(wx.ID_OK)
    _track_props(win, fake)
    assert fake.slot == 3                             # pas le slot de repli (BANK)
    assert fake.kw["rack_slot_of"](3) == BANK
    assert fake.kw["channel_labels"][1] == "Canal 2 — Slot_02 Piano WAV"
    assert win.statuses[-1] == "Piste 1: propriétés inchangées"
    assert win.undos == ["Propriétés piste 1", "pop"]


def test_track_properties_rack_mode_change_channel_keeps_track_slot():
    win = _RackWin()
    _channels(win, [3])
    _track_props(win, _scripted_track_dlg(wx.ID_OK, channel=SYNTH))
    r = win._router
    assert r.get_track_channel(0) == SYNTH and r._track_slots[0] == BANK
    assert win._cur_slot == SYNTH
    assert win.statuses[-1] == "Piste 1: propriétés mises à jour"
    assert win.undos == ["Propriétés piste 1"]


def test_track_properties_rack_mode_cancel_restores_channel():
    win = _RackWin()
    _channels(win, [3])
    _track_props(win, _scripted_track_dlg(wx.ID_CANCEL, channel=SYNTH))
    assert win._router.get_track_channel(0) == 3 and win._cur_slot == BANK
    assert win.undos[-1] == "pop"


def test_track_properties_normal_mode_has_no_rack_args():
    win = _RackWin(rack_mode=False)
    fake = _scripted_track_dlg(wx.ID_CANCEL)
    _track_props(win, fake)
    assert fake.kw["rack_slot_of"] is None and fake.kw["channel_labels"] is None


# ---------------------------------------------------------------------------
# Changement de pattern (M16, M6)
# ---------------------------------------------------------------------------

def test_switch_to_rack_pattern_announces_mode_and_follows_slot():
    win = _RackWin(rack_mode=False)
    win._player.voice_manager.to_list = lambda: []
    new = win._pattern_list[1]
    new._rack_mode = True
    new._track_slots = [BANK] * 16
    new._track_channels = [SYNTH] + [Pattern.default_channel(t) for t in range(1, 16)]
    new._tape[0] = [TapeEvent(ETYPE_PATCH, payload={"note": 60, "vel": 100}, time=0, channel=SYNTH)]
    win._switch_pattern(1)
    assert win._router.rack_mode is True
    assert win._cur_slot == SYNTH
    assert win.statuses[-1] == "Pattern 02 — mode Rack 16 canaux"


def test_switch_back_to_normal_pattern_restores_track_slot():
    win = _RackWin(rack_mode=True)
    _channels(win, [SYNTH])
    win._player.voice_manager.to_list = lambda: []
    win._pattern_list[1]._track_slots = [BANK] * 16
    win._switch_pattern(1)
    assert win._router.rack_mode is False and win._cur_slot == BANK
    assert win.statuses[-1] == "Pattern 02"
