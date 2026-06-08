import wx
from song import Song


class SongWindow(wx.Frame):
    def __init__(self, parent):
        super().__init__(parent, title="Songs", size=(820, 420),
                         style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT)
        self._parent = parent
        self._cur_song_idx = 0
        self._build_ui()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    # ------------------------------------------------------------------

    def _build_ui(self):
        panel = wx.Panel(self)
        main_vbox = wx.BoxSizer(wx.VERTICAL)

        hbox = wx.BoxSizer(wx.HORIZONTAL)

        # ListBox 1 — Songs
        vbox1 = wx.BoxSizer(wx.VERTICAL)
        vbox1.Add(wx.StaticText(panel, label="Songs"), 0, wx.BOTTOM, 4)
        self._song_lb = wx.ListBox(panel, style=wx.LB_SINGLE, size=(180, 320))
        vbox1.Add(self._song_lb, 1, wx.EXPAND)
        hbox.Add(vbox1, 1, wx.EXPAND | wx.RIGHT, 8)

        # ListBox 2 — Patterns disponibles
        vbox2 = wx.BoxSizer(wx.VERTICAL)
        vbox2.Add(wx.StaticText(panel, label="Patterns disponibles"), 0, wx.BOTTOM, 4)
        self._avail_lb = wx.ListBox(panel, style=wx.LB_SINGLE, size=(220, 320))
        vbox2.Add(self._avail_lb, 1, wx.EXPAND)
        hbox.Add(vbox2, 1, wx.EXPAND | wx.RIGHT, 8)

        # ListBox 3 — Séquence
        vbox3 = wx.BoxSizer(wx.VERTICAL)
        self._seq_label = wx.StaticText(panel, label="Séquence")
        vbox3.Add(self._seq_label, 0, wx.BOTTOM, 4)
        self._seq_lb = wx.ListBox(panel, style=wx.LB_SINGLE, size=(220, 320))
        vbox3.Add(self._seq_lb, 1, wx.EXPAND)
        hbox.Add(vbox3, 1, wx.EXPAND)

        main_vbox.Add(hbox, 1, wx.EXPAND | wx.ALL, 8)

        # Boutons
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_empty = wx.Button(panel, label="Vider")
        self._btn_play  = wx.Button(panel, label="Jouer le song")
        self._status    = wx.StaticText(panel, label="")
        btn_box.Add(self._btn_empty, 0, wx.RIGHT, 8)
        btn_box.Add(self._status, 1, wx.ALIGN_CENTER_VERTICAL)
        btn_box.Add(self._btn_play, 0)
        main_vbox.Add(btn_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(main_vbox)

        # Tab order explicite (GTK ne garantit pas l'ordre de création)
        self._avail_lb.MoveAfterInTabOrder(self._song_lb)
        self._seq_lb.MoveAfterInTabOrder(self._avail_lb)
        self._btn_empty.MoveAfterInTabOrder(self._seq_lb)
        self._btn_play.MoveAfterInTabOrder(self._btn_empty)

        # Bindings
        # GTK : Enter sur ListBox génère EVT_LISTBOX_DCLICK (pas EVT_KEY_DOWN)
        self._song_lb.Bind(wx.EVT_LISTBOX,        self._on_song_select)
        self._song_lb.Bind(wx.EVT_LISTBOX_DCLICK, self._on_song_activate)
        self._avail_lb.Bind(wx.EVT_LISTBOX_DCLICK, self._on_avail_activate)
        self._seq_lb.Bind(wx.EVT_KEY_DOWN, self._on_seq_key)
        self._seq_lb.Bind(wx.EVT_LISTBOX_DCLICK, self._on_seq_activate)
        self._btn_empty.Bind(wx.EVT_BUTTON, self._on_empty)
        self._btn_play.Bind(wx.EVT_BUTTON,  self._on_play)

        self._refresh_song_lb()
        self._refresh_avail_lb()
        self._refresh_seq_lb()
        self._song_lb.SetFocus()

    # ------------------------------------------------------------------

    def _song_label(self, idx):
        song = self._parent._song_list[idx]
        name = song._name if song._name else f"Song_{idx+1:02d}"
        n = len(song._sequence)
        return f"{name} ({n})" if n else name

    def _pat_label(self, pat_idx):
        return self._parent._pattern_label(pat_idx)

    def _refresh_song_lb(self):
        self._song_lb.Set([self._song_label(i) for i in range(Song.MAX_SONGS)])
        self._song_lb.SetSelection(self._cur_song_idx)

    def _refresh_avail_lb(self):
        sel = self._avail_lb.GetSelection()
        self._avail_lb.Set([self._pat_label(i) for i in range(99)])
        self._avail_lb.SetSelection(max(0, sel))

    def _refresh_seq_lb(self, sel_after=None):
        song = self._parent._song_list[self._cur_song_idx]
        n = len(song._sequence)
        self._seq_label.SetLabel(f"Séquence ({n})")
        labels = [self._pat_label(i) for i in song._sequence]
        self._seq_lb.Set(labels)
        if sel_after is not None and 0 <= sel_after < n:
            self._seq_lb.SetSelection(sel_after)
        elif n:
            self._seq_lb.SetSelection(min(self._seq_lb.GetSelection(), n - 1)
                                      if self._seq_lb.GetSelection() != wx.NOT_FOUND else 0)

    # ------------------------------------------------------------------

    def _on_song_select(self, evt):
        idx = self._song_lb.GetSelection()
        if idx != wx.NOT_FOUND:
            self._cur_song_idx = idx
            self._refresh_seq_lb()

    def _on_song_activate(self, evt):
        self._on_song_select(evt)

    def _on_avail_activate(self, evt):
        idx = self._avail_lb.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        self._insert_avail_pattern(idx, before=wx.GetKeyState(wx.WXK_CONTROL))

    def _on_seq_activate(self, evt):
        # Ctrl+Enter depuis la séquence : insère le pattern avail sélectionné avant la pos courante
        if wx.GetKeyState(wx.WXK_CONTROL):
            avail_idx = self._avail_lb.GetSelection()
            if avail_idx != wx.NOT_FOUND:
                self._insert_avail_pattern(avail_idx, before=True)
        # Enter simple / double-clic sans Ctrl : rien de spécial
        else:
            evt.Skip()

    def _insert_avail_pattern(self, pat_idx, before=False):
        """Ajoute pat_idx à la séquence : avant la sélection courante si before=True, sinon en fin."""
        song = self._parent._song_list[self._cur_song_idx]
        seq  = song._sequence
        sel  = self._seq_lb.GetSelection()
        if before and sel != wx.NOT_FOUND:
            seq.insert(sel, pat_idx)
            new_sel = sel
            verb = "inséré"
        else:
            seq.append(pat_idx)
            new_sel = len(seq) - 1
            verb = "ajouté"
        self._refresh_song_lb()
        self._refresh_seq_lb(new_sel)
        self._set_status(f"Pat_{pat_idx+1:02d} {verb}")

    def _on_seq_key(self, evt):
        key = evt.GetKeyCode()
        sel = self._seq_lb.GetSelection()
        song = self._parent._song_list[self._cur_song_idx]
        seq  = song._sequence

        if key in (wx.WXK_DELETE, wx.WXK_BACK) and sel != wx.NOT_FOUND:
            del seq[sel]
            new_sel = min(sel, len(seq) - 1) if seq else wx.NOT_FOUND
            self._refresh_song_lb()
            self._refresh_seq_lb(new_sel if new_sel >= 0 else None)
            self._set_status("Entrée supprimée")
            return

        if key == wx.WXK_UP and evt.AltDown() and sel > 0:
            seq[sel - 1], seq[sel] = seq[sel], seq[sel - 1]
            self._refresh_seq_lb(sel - 1)
            return

        if key == wx.WXK_DOWN and evt.AltDown() \
                and sel != wx.NOT_FOUND and sel < len(seq) - 1:
            seq[sel], seq[sel + 1] = seq[sel + 1], seq[sel]
            self._refresh_seq_lb(sel + 1)
            return

        evt.Skip()

    def _on_empty(self, evt):
        song = self._parent._song_list[self._cur_song_idx]
        song._sequence.clear()
        self._refresh_song_lb()
        self._refresh_seq_lb()
        self._set_status("Séquence vidée")

    def _on_play(self, evt):
        self._parent._play_song(self._cur_song_idx)

    def _on_key(self, evt):
        key   = evt.GetKeyCode()
        ukey  = evt.GetUnicodeKey()
        ctrl  = evt.ControlDown()
        shift = evt.ShiftDown()

        if key == wx.WXK_ESCAPE:
            self.Close()
            return

        # Overrides song-specific : Play/Pause, GotoStart, GotoEnd
        if not ctrl:
            if not shift and (ukey in (ord(' '), ord('p')) or key in (wx.WXK_SPACE, ord('P'))):
                self._parent._song_play_pause(self._cur_song_idx)
                return
            if not shift and (ukey == ord('g') or key == ord('G')):
                self._parent._song_goto_start(self._cur_song_idx)
                return
            if shift and (ukey == ord('g') or key == ord('G')):
                self._parent._song_goto_end(self._cur_song_idx)
                return

        if self._parent._key_manager.handle_transport(evt):
            return
        evt.Skip()

    def _on_close(self, evt):
        self._parent._song_window = None
        evt.Skip()

    def _set_status(self, msg):
        self._status.SetLabel(msg)

    # ------------------------------------------------------------------

    def refresh(self):
        """Rafraîchit tous les labels (à appeler depuis main_window si besoin)."""
        self._refresh_song_lb()
        self._refresh_avail_lb()
        self._refresh_seq_lb()

    def on_song_advance(self, pat_idx):
        """Met à jour le label de statut lors d'une transition de song."""
        if pat_idx < 0:
            self._set_status("Song terminé")
        else:
            self._set_status(f"→ Pat_{pat_idx+1:02d}")
