import wx
from midi_editor import MidiEditor
from ui.midi_virtual_keyboard import VirtualKeyboardMixin
from ui.mew_display          import DisplayMixin
from ui.mew_playback         import PlaybackMixin
from ui.mew_navigation       import NavigationMixin
from ui.mew_undo             import UndoMixin
from ui.mew_selection        import SelectionMixin
from ui.mew_editing          import EditingMixin
from ui.mew_numpad           import NumpadMixin
from ui.mew_quantize         import QuantizeMixin
from ui.mew_delete_clipboard import DeleteClipboardMixin
from ui.mew_keymap           import KeymapMixin


class MidiEditorWindow(VirtualKeyboardMixin, DisplayMixin, PlaybackMixin,
                       NavigationMixin, UndoMixin, SelectionMixin, EditingMixin,
                       NumpadMixin, QuantizeMixin, DeleteClipboardMixin,
                       KeymapMixin, wx.Frame):
    """Fenêtre d'éditeur MIDI — deux modes : notes (Ctrl+1) et tous les événements (Ctrl+2).

    Navigation :
      ←/→  : groupe précédent/suivant (même offset = accord)
      ↑/↓  : note précédente/suivante dans l'accord courant
      Entrée : éditer la note sélectionnée
      Suppr  : supprimer la note sélectionnée
    """

    MODE_NOTES = 0   # notes de la piste courante (grille séquenceur)
    MODE_ALL   = 1   # tous les événements MIDI (grille + tape KIT/PATCH + CC)

    def __init__(self, parent, view_mode=MODE_NOTES):
        super().__init__(parent, title="Éditeur MIDI",
                         size=(780, 560),
                         style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT)
        self._parent               = parent
        self._view_mode            = view_mode
        self._events               = []
        self._midi_editor          = MidiEditor()
        self._skip_listbox_announce = False   # évite que EVT_LISTBOX écrase l'annonce clavier
        self._preview_midis        = []       # notes MIDI en cours de preview (accord)
        self._preview_timer        = None     # Timer d'arrêt automatique
        self._group_entry          = False    # ←/→ vient d'atterrir sur un groupe
        self._selected_indices     = set()    # indices sélectionnés dans self._events
        self._vk_note              = 48       # clavier virtuel (7f) : note courante (C4)
        self._skip_vk_announce     = False    # évite que EVT_LISTBOX écrase l'annonce clavier
        self._insert_last_vel      = None     # 7i : dernière vélocité utilisée (dialog Ctrl+Shift+I)
        self._insert_last_dur      = None     # 7i : dernière durée utilisée (dialog Ctrl+Shift+I)
        self._build_ui()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE,     self._on_close)
        self.Bind(wx.EVT_ACTIVATE,  self._on_activate)
        self._refresh()

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        panel = wx.Panel(self)
        vbox  = wx.BoxSizer(wx.VERTICAL)

        self._mode_label = wx.StaticText(panel, label="")
        vbox.Add(self._mode_label, 0, wx.ALL, 6)

        self._event_lb = wx.ListBox(panel, style=wx.LB_SINGLE, size=(-1, 320))
        vbox.Add(self._event_lb, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        self._event_lb.Bind(wx.EVT_LISTBOX,       self._on_listbox_select)
        # GTK : Enter sur ListBox génère EVT_LISTBOX_DCLICK (pas EVT_CHAR_HOOK)
        self._event_lb.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._edit_note_dialog())

        self._build_vk_ui(panel, vbox)

        # ListBox status (annoncée en temps réel par le lecteur d'écran)
        self._status_ctrl = wx.ListBox(panel, choices=[""], style=wx.LB_SINGLE)
        vbox.Add(self._status_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # ListBox statut MIDI live (messages entrants du clavier externe),
        # distincte de _status_ctrl (annonces de navigation/sélection) —
        # même astuce SetString pour l'annonce Orca (feedback_accessibility_spinctrl).
        self._midi_status_ctrl = wx.ListBox(panel, choices=[""], style=wx.LB_SINGLE)
        vbox.Add(self._midi_status_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        panel.SetSizer(vbox)
        self._event_lb.SetFocus()

    def _on_activate(self, evt):
        if evt.GetActive():
            self._event_lb.SetFocus()
        evt.Skip()

    def _on_close(self, evt):
        self._stop_preview()
        self._parent._midi_editor_window = None
        evt.Skip()

    # ------------------------------------------------------------------

    def refresh(self):
        """Appelé depuis MainWindow si le pattern ou la piste change."""
        self._refresh()
