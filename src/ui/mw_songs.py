import wx
from .dialogs import SaveSongDialog


class SongMixin:
    """Méthodes MainWindow relatives au mode Song."""

    def _open_song_window(self):
        if self._song_window is None:
            self._pre_song_pattern_idx = self._cur_pattern_idx
            if self._player.playing:
                self._player.stop_pattern()
                self._router.stop_all_synth_voices()
            from ui.song_window import SongWindow
            self._song_window = SongWindow(self)
        self._song_window.Show()
        self._song_window.Raise()

    def _exit_song_mode(self):
        if self._player.playing:
            self._player.stop_pattern()
            self._router.stop_all_synth_voices()
        p = self._player
        p._song_mode     = False
        p._song_looping  = False
        p._song_sequence = []
        p._song_pos      = 0
        pre = self._pre_song_pattern_idx
        self._switch_pattern(pre)
        self._pattern_listbox.SetSelection(pre)
        p.goto_start()
        self._show_status(f"Mode Song quitté → Pat_{pre+1:02d}")

    def _play_song(self, song_idx):
        song = self._song_list[song_idx]
        if not song._sequence:
            self._show_status("Song vide — ajoutez des patterns dans la fenêtre Songs")
            return
        if self._player.playing:
            self._player.stop_pattern()
        first_idx = song._sequence[0]
        cur = self._pattern_list[self._cur_pattern_idx]
        cur._voices = self._player.voice_manager.to_list()
        self._flush_pattern_to_store(cur)
        self._cur_pattern_idx = first_idx
        new = self._pattern_list[first_idx]
        self._apply_pattern_from_store(new)
        self._player._compute_offsets()
        self._pattern_listbox.SetSelection(first_idx)
        self._player.play_song(song._sequence, self._pattern_list, song._looping)
        n = len(song._sequence)
        loop_str = " [Boucle]" if song._looping else ""
        self._show_status(
            f"Song {song_idx+1:02d} → Pat_{first_idx+1:02d} ({n} patterns){loop_str}"
        )

    def _song_play_pause(self, song_idx):
        p = self._player
        if p.playing:
            p.pause_pattern()
            self._router.stop_all_synth_voices()
            self._show_status("Song: Pause")
        elif p._song_mode:
            p.play_pattern()
            self._show_status("Song: Reprise")
        else:
            self._play_song(song_idx)

    def _song_goto_start(self, song_idx):
        song = self._song_list[song_idx]
        if not song._sequence:
            self._show_status("Song vide")
            return
        first_idx = song._sequence[0]
        self._song_load_pattern(song, first_idx, song_pos=0)
        self._player.goto_start()
        self._show_status(f"Song: Début → Pat_{first_idx+1:02d}")

    def _song_goto_end(self, song_idx):
        song = self._song_list[song_idx]
        if not song._sequence:
            self._show_status("Song vide")
            return
        last_idx = song._sequence[-1]
        last_pos = len(song._sequence) - 1
        self._song_load_pattern(song, last_idx, song_pos=last_pos)
        self._player.goto_end()
        self._show_status(f"Song: Fin → Pat_{last_idx+1:02d}")

    def _on_song_cross_nav(self, direction):
        p       = self._player
        new_pos = p._song_pos + direction
        if not (0 <= new_pos < len(p._song_sequence)):
            return
        pat_idx = p._song_sequence[new_pos]
        new     = self._pattern_list[pat_idx]
        cur     = self._pattern_list[self._cur_pattern_idx]
        cur._voices = p.voice_manager.to_list()
        self._flush_pattern_to_store(cur)
        self._cur_pattern_idx = pat_idx
        self._apply_pattern_from_store(new)
        p._pattern._looping = False
        p._song_pos         = new_pos
        p._compute_offsets()
        self._pattern_listbox.SetSelection(pat_idx)
        if direction < 0:
            last_bar_start = float((new._num_bars - 1) * new._num_steps)
            p._go_to_offset(last_bar_start)
        else:
            p.goto_start()
        arrow = "←" if direction < 0 else "→"
        self._show_status(f"Song {arrow} Pat_{pat_idx+1:02d}")
        if self._song_window:
            self._song_window.on_song_advance(pat_idx)

    def _song_load_pattern(self, song, pat_idx, song_pos):
        p   = self._player
        cur = self._pattern_list[self._cur_pattern_idx]
        cur._voices = p.voice_manager.to_list()
        self._flush_pattern_to_store(cur)
        self._cur_pattern_idx = pat_idx
        new = self._pattern_list[pat_idx]
        self._apply_pattern_from_store(new)
        p._pattern._looping  = False
        p._song_sequence     = list(song._sequence)
        p._pattern_list_ref  = self._pattern_list
        p._song_pos          = song_pos
        p._song_mode         = True
        p._song_looping      = song._looping
        p._compute_offsets()
        self._pattern_listbox.SetSelection(pat_idx)

    def _on_song_advance(self, next_pat_idx):
        if next_pat_idx < 0:
            self._show_status("Song terminé")
            if self._song_window:
                self._song_window.on_song_advance(-1)
            return
        new = self._pattern_list[next_pat_idx]
        self._cur_pattern_idx = next_pat_idx
        self._pattern_listbox.SetSelection(next_pat_idx)
        self._player.voice_manager.from_list(new._voices)
        self._router._track_slots[:]   = new._track_slots
        self._router._track_mutes[:]   = new._track_mutes
        self._router._track_solos[:]   = new._track_solos
        self._router._track_volumes[:] = new._track_volumes
        self._router._track_pans[:]    = new._track_pans
        self._router.set_playback_kb(new._kb_scale, new._kb_root_midi)
        self._bpm_ctrl.SetValue(int(new._bpm))
        self._show_status(f"Song → Pat_{next_pat_idx+1:02d}")
        if self._song_window:
            self._song_window.on_song_advance(next_pat_idx)

    def _save_song(self):
        self._save_project()
        self._show_status(f"Song {self._cur_song_idx + 1:02d} sauvegardé")

    def _save_song_as(self):
        src = self._song_list[self._cur_song_idx]
        dlg = SaveSongDialog(self, self._cur_song_idx, src._name)
        if dlg.ShowModal() == wx.ID_OK:
            idx  = dlg.get_selection()
            name = dlg.get_name()
            dst  = self._song_list[idx]
            dst._sequence = src._sequence[:]
            dst._looping  = src._looping
            dst._name     = name
            self._cur_song_idx = idx
            if self._song_window:
                self._song_window.set_cur_song(idx)
            self._save_project()
            self._show_status(f"Song {idx + 1:02d} sauvegardé")
        dlg.Destroy()
