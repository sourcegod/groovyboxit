#python3
"""
    File: src/ui/key_manager.py
    Gestion centralisée des raccourcis clavier de MainWindow.
    Date: Thu, 21/05/2026
    Author: Coolbrother
"""
import types
import wx

from . import menu_bar

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
        # F3 / F4 : Mute / Solo exclusifs (Phase 8 étape 6d1, § 6a N5, N10)
        if key in (wx.WXK_F3, wx.WXK_F4) and not (ctx.ctrl or ctx.alt or ctx.shift):
            win._toggle_exclusive("mute" if key == wx.WXK_F3 else "solo")
            return
        # F8 : monitoring de l'entrée (Phase 8 étape 20d1, M4)
        if key == wx.WXK_F8 and not (ctx.ctrl or ctx.alt or ctx.shift):
            win._toggle_monitor()
            return
        # Raccourcis MIDI regroupés sur F12 (Phase 8 étape 11d1, demande de
        # l'utilisateur) : Ctrl+F12 = Panic (key_handler_ctrl), Shift+F12 =
        # connecter / déconnecter les entrées, Ctrl+Shift+F12 = réinitialiser
        if key == wx.WXK_F12 and ctx.shift and not ctx.alt:
            if ctx.ctrl:
                win._reconnect_midi()
            else:
                win._toggle_midi_inputs()
            return
        # F5 : tous les Mute / Solo réinitialisés, mode exclusif quitté (6d2)
        if key == wx.WXK_F5 and not (ctx.ctrl or ctx.alt or ctx.shift):
            win._reset_mute_solo()
            return
        # Retour arrière : remise du volume / pan (Phase 8 étape 19b1, § 19a)
        if key == wx.WXK_BACK and self._handle_mix_reset(ctx):
            return
        if ctx.alt and self._handle_alt(event, ctx):
            return
        # Alt+lettre d'un menu, après les commandes Alt+lettre (K3), F10 :
        # barre de menus (Phase 9 étape 1b1, § 1a K1, K2)
        if ctx.alt and not (ctx.ctrl or ctx.shift) and 0 < ukey < 128 \
                and chr(ukey).isalpha() and menu_bar.open_menu(win, chr(ukey)):
            return
        if key == wx.WXK_F10 and not (ctx.ctrl or ctx.alt or ctx.shift) \
                and menu_bar.open_first(win):
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

    # Champs de saisie où Retour arrière efface un caractère (19b1)
    _TEXT_FIELDS = ("on_bpm", "on_volume", "on_pan", "on_voice_spin")

    def _handle_mix_reset(self, ctx):
        """Retour arrière avec modificateur (Phase 8 étape 19b1, § 19a révisé
        à l'essai : Alt+Retour arrière est pris par Orca) : Ctrl → volume et
        pan globaux des préférences ; Shift → volume 100 et pan 0 de la piste
        courante (liste des pistes) ou, ailleurs, du pad courant. Une seule
        entrée d'Undo, rien si tout est déjà à sa valeur ; son en temps réel.
        Rien dans un champ de saisie : Retour arrière y efface."""
        if any(getattr(ctx, name) for name in self._TEXT_FIELDS):
            return False
        win = self._win
        ctrl, shift, alt = ctx.ctrl, ctx.shift, ctx.alt
        if alt or ctrl == shift:
            return False
        if ctrl:
            vol, pan = win._master_defaults
            if (vol, pan) != (win._player.volume, win._player.pan):
                win._add_mix_undo("Volume et pan globaux : préférences")
                win._apply_master(vol, pan)
            win._show_status(f"Volume Global: {win.master_volume_text(win._player.volume)}, "
                             f"Pan Global: {win._player.pan} (préférences)")
            return True
        if ctx.on_track_list:
            r, t = win._router, win._player._cur_track
            if (r.get_track_volume(t), r.get_track_pan(t)) != (100, 0):
                win._add_mix_undo(f"Volume et pan piste {t + 1} : 100 / 0")
                r.set_track_volume(t, 100)
                r.set_track_pan(t, 0)
            win._show_status(f"Piste {t + 1}: Volume 100, Pan 0 (centre)")
            return True
        vm, row = win._player.voice_manager, win._cur_row
        if (vm.get_voice(row).volume, vm.get_pan(row)) != (100, 0):
            win._add_mix_undo(f"Volume et pan pad {row + 1} : 100 / 0")
            vm.set_volume(row, 100)
            vm.set_pan(row, 0)
        win._refresh_voice_display(row)
        win._show_status(f"Pad {row + 1}: Volume 100, Pan 0 (centre)")
        if ctx.on_pad_list:
            win._play(row)
        return True
