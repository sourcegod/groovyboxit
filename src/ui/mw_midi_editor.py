class MidiEditorMixin:
    """Méthodes MainWindow relatives à la fenêtre Éditeur MIDI."""

    def _open_midi_editor_window(self):
        from ui.midi_editor_window import MidiEditorWindow
        view_mode = self._midi_editor_view_mode
        if self._midi_editor_window is None:
            self._midi_editor_window = MidiEditorWindow(self, view_mode)
        else:
            self._midi_editor_window._view_mode = view_mode
            self._midi_editor_window._refresh()
        self._midi_editor_window.Show()
        self._midi_editor_window.Raise()
