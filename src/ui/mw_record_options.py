#python3
"""
    File: src/ui/mw_record_options.py
    Mixin MainWindow — Options de l'enregistrement (Ctrl+Shift+R, Phase 8
    étape 16b1, docs/DESIGN.md § Phase 8 étape 16a, O1-O11) : dialogue depuis
    la fenêtre principale, l'éditeur MIDI et la fenêtre Songs ; options du
    projet (clé record_options du .gvp, défauts à Ctrl+N et pour un ancien
    projet), point d'Undo, appliquées au lecteur (décompte, clic pendant
    l'enregistrement, clic pendant la lecture) ; mode suivi par R et Ctrl+R.
    Date: Tue, 17/11/2026
    Author: Coolbrother
"""
import wx

import record_modes
from .dialogs import RecordOptionsDialog


class RecordOptionsMixin:

    _record_options = dict(record_modes.DEFAULTS)

    def _record_mode(self):
        """RecordMode suivi par R et Ctrl+R (O1)."""
        return record_modes.mode_of(self._record_options.get("mode"))

    def _apply_record_options(self, options):
        """Options gardées et appliquées au lecteur (décompte, clics)."""
        opts = record_modes.normalize(options)
        self._record_options = opts
        p = self._player
        p.count_in_bars = opts["count_in"]
        p.click_in_recording = opts["click_record"]
        p.click_in_playback = opts["click_play"]
        p.count_in_play_bars = opts["count_in_play"]        # 16b1, essai
        return opts

    def _open_record_options(self, parent=None, status=None):
        """Ctrl+Shift+R : dialogue ; Ok avec un changement → point d'Undo,
        options appliquées et annoncées."""
        say = status or self._show_status
        dlg = RecordOptionsDialog(parent or self, self._record_options)
        try:
            ok = dlg.ShowModal() == wx.ID_OK
            new = record_modes.normalize(dlg.get_options())
        finally:
            dlg.Destroy()
        if not ok:
            say("Options de l'enregistrement : annulé")
            return False
        if new == self._record_options:
            say("Options de l'enregistrement inchangées")
            return False
        self._add_undo("Options de l'enregistrement")
        self._apply_record_options(new)
        self._update_title()
        say("Options de l'enregistrement — " + record_modes.describe(new))
        return True
