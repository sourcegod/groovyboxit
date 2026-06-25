#python3
"""
    File: src/ui/key_manager.py
    Gestion centralisée des raccourcis clavier de MainWindow.
    Date: Thu, 21/05/2026
    Author: Coolbrother
"""
import types
import wx

from .key_handler_alt        import AltHandler
from .key_transport          import TransportHandler
from .key_handler_ctrl       import CtrlHandler
from .key_handler_navigation import NavigationHandler
from .key_handler_numpad     import NumpadHandler
from .key_handler_chars      import CharHandler


class KeyManager(AltHandler, TransportHandler, CtrlHandler,
                 NavigationHandler, NumpadHandler, CharHandler):
    """Dispatche les événements clavier reçus par MainWindow._on_char_hook."""

    def __init__(self, win):
        self._win = win

    # ------------------------------------------------------------------
    # Point d'entrée unique
    # ------------------------------------------------------------------

    def handle(self, event):
        win     = self._win
        key     = event.GetKeyCode()
        ukey    = event.GetUnicodeKey()
        ctrl    = event.ControlDown()
        shift   = event.ShiftDown()
        alt     = event.AltDown()
        focused = wx.Window.FindFocus()

        ctx = types.SimpleNamespace(
            key   = key,   ukey  = ukey,
            ctrl  = ctrl,  shift = shift, alt = alt,
            on_quant_list   = focused == win._quant_list,
            on_pattern_list = focused == win._pattern_listbox,
            on_bpm          = focused == win._bpm_ctrl,
            on_volume       = focused == win._volume_ctrl,
            on_pan          = focused == win._pan_ctrl,
            on_voice_spin   = focused in win._vol_ctrls or focused in win._pan_ctrls,
            on_mode_choice  = focused == win._mode_choice,
            on_scale_choice = focused == win._scale_choice,
            on_slot_choice  = focused == win._slot_choice,
            on_track_list   = focused == win._track_list,
            on_pad_list          = focused == win._pad_list,
            on_vel_list          = focused == win._vel_list,
            on_midi_port_list    = focused == win._midi_port_list,
            on_status_ctrl       = focused == win._status_ctrl,
        )

        if key == wx.WXK_F1:
            win._show_keyboard_help()
            return
        if key == wx.WXK_F2:
            if ctx.on_track_list:
                win._rename_track()
            else:
                win._rename_pattern()
            return
        if ctx.alt and self._handle_alt(event, ctx):
            return
        if ctx.ctrl and self._handle_ctrl(event, ctx):
            return
        if self._handle_navigation(event, ctx):
            return
        if self._handle_numpad(event, ctx):
            return
        if self._handle_chars(event, ctx):
            return

        print(f"DEBUG key={key} ukey={ukey} shift={shift} ctrl={ctrl} "
              f"char={chr(ukey) if ukey > 31 else '?'}")
        event.Skip()
