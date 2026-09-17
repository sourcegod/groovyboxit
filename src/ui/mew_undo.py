import wx


class UndoMixin:
    """MidiEditorWindow — Undo/Redo, délégués vers MainWindow._undo."""

    def _add_undo(self, title):
        self._parent._add_undo(title)

    def _undo_action(self):
        hist = self._parent._undo.history_list()
        title = hist[0].title if hist else None
        self._parent._undo_action()
        self._refresh()
        self._set_status(f"Undo: {title}" if title else "Undo: rien à annuler")

    def _redo_action(self):
        fut = self._parent._undo.future_list()
        title = fut[0].title if fut else None
        self._parent._redo_action()
        self._refresh()
        self._set_status(f"Redo: {title}" if title else "Redo: rien à refaire")

    def _undo_history_dialog(self):
        from ui.dialogs import UndoHistoryDialog
        entries = self._parent._undo.history_list()
        if not entries:
            self._set_status("Historique Undo: vide")
            return
        prev_focus = wx.Window.FindFocus()
        dlg = UndoHistoryDialog(self, entries)
        if dlg.ShowModal() == wx.ID_OK:
            steps = dlg.get_steps()
            for _ in range(steps):
                self._undo_action()
        dlg.Destroy()
        if prev_focus:
            prev_focus.SetFocus()
