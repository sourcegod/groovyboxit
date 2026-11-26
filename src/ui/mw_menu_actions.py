#python3
"""
    File: src/ui/mw_menu_actions.py
    Éléments de menus de la fenêtre principale appelés par méthode (Phase 9
    étape 3b1, docs/DESIGN.md § Phase 9 étape 3a) : ceux dont la touche ne
    marche que sur une liste précise (liste des pistes, des patterns) ou qui
    n'ont pas de raccourci. Ils agissent sur la piste ou le pattern courant
    quel que soit le focus. La logique partagée avec le clavier reste dans
    KeyManager (jamais une copie du code).
    Date: Mon, 23/11/2026
    Author: Coolbrother
"""
import wx

from .gtk_listbox import select_with_cursor


class MainMenuActions:
    """Mixin MainWindow (avant MenuBarMixin : _menu_delete le remplace)."""

    # --- Edition ------------------------------------------------------

    def _menu_delete(self):
        """Edition > Supprimer : Suppr de la liste des pistes, avec Undo."""
        self._key_manager.delete_tracks()

    def _menu_select_track(self, selected):
        """Edition > Sélection : met la piste courante dans la sélection
        (selected True) ou l'en retire ; Shift+Espace bascule."""
        te  = self._track_editor
        cur = self._player._cur_track
        if te.is_selected(cur) == selected:
            self._show_status(f"Piste {cur + 1}: déjà "
                              + ("sélectionnée" if selected else "hors de la sélection"))
            return
        te.toggle_track(cur)
        self._refresh_track_list()
        sel = sorted(te._sel_tracks)
        if sel:
            self._show_status(f"Sélection: Piste{'s' if len(sel) > 1 else ''} "
                              f"{', '.join(str(i + 1) for i in sel)}")
        else:
            self._show_status(f"Piste {cur + 1}: désélectionnée")

    # --- Piste, Pattern -----------------------------------------------

    def _menu_step_track(self, delta):
        """Piste > Piste précédente / suivante (Haut / Bas de la liste des
        pistes) : la sélection est gardée, le curseur de la liste suit."""
        cur, n = self._player._cur_track, self._track_list.GetCount()
        new = cur + delta
        if not 0 <= new < n:
            wx.Bell()
            self._show_status(f"Piste {cur + 1}: "
                              + ("première piste" if delta < 0 else "dernière piste"))
            return
        self._go_to_track(new)
        select_with_cursor(self._track_list, self._player._cur_track)

    def _menu_step_pattern(self, delta):
        """Pattern > Changer de pattern > précédent / suivant (Haut / Bas de
        la liste des patterns) ; le curseur de la liste suit."""
        cur, n = self._cur_pattern_idx, len(self._pattern_list)
        new = cur + delta
        if not 0 <= new < n:
            wx.Bell()
            self._show_status(f"Pattern {cur + 1:02d}: "
                              + ("premier pattern" if delta < 0 else "dernier pattern"))
            return
        self._switch_pattern(new)
        select_with_cursor(self._pattern_listbox, new)

    def _last_used_pattern(self):
        """Indice du dernier pattern non vide (le courant tel qu'il est
        joué), 0 si tous sont vides (Phase 9 étape 4c6, § 4c5 P1)."""
        for i in range(len(self._pattern_list) - 1, -1, -1):
            pat = self._player._pattern if i == self._cur_pattern_idx else self._pattern_list[i]
            if not pat.is_empty():
                return i
        return 0

    def _menu_edge_pattern(self, last):
        """Ctrl+< : premier pattern ; Ctrl+> : dernier pattern utilisé (non
        vide) ; bip si l'on y est déjà (4c6, § 4c5 P1, P3)."""
        cur = self._cur_pattern_idx
        new = self._last_used_pattern() if last else 0
        if new == cur:
            wx.Bell()
            self._show_status(f"Pattern {cur + 1:02d}: "
                              + ("dernier pattern utilisé" if last else "premier pattern"))
            return
        self._switch_pattern(new)
        select_with_cursor(self._pattern_listbox, new)

    def _menu_choose_pattern(self):
        """Pattern > Changer de pattern > Choisir un pattern… (3d1)."""
        from .dialogs_menu import PatternChoiceDialog
        n   = len(self._pattern_list)
        dlg = PatternChoiceDialog(self, [self._pattern_label(i) for i in range(n)],
                                  self._cur_pattern_idx)
        ok, idx = dlg.ShowModal() == wx.ID_OK, dlg.get_index()
        dlg.Destroy()
        if not ok or idx < 0:
            return
        if idx == self._cur_pattern_idx:
            self._show_status(f"Pattern {idx + 1:02d}: déjà le pattern courant")
            return
        self._switch_pattern(idx)
        select_with_cursor(self._pattern_listbox, idx)

    def _menu_resize_pattern(self):
        """Pattern > Redimensionner > Redimensionner le pattern… (3d1) :
        mesures et résolution, signature gardée ; un point d'Undo, rien si
        rien ne change ; même chemin que le dialogue des propriétés."""
        from pattern import Pattern
        from .dialogs_menu import ResizePatternDialog
        live = self._player._pattern
        resolution = round(live._num_steps * live._denumerator / live._num_beats)
        dlg = ResizePatternDialog(self, live._num_bars, Pattern.MAX_BARS, resolution,
                                  Pattern.VALID_RESOLUTIONS)
        ok = dlg.ShowModal() == wx.ID_OK
        num_bars, res = dlg.get_num_bars(), dlg.get_resolution()
        dlg.Destroy()
        if not ok:
            return
        num_steps = Pattern.steps_for(res, live._num_beats, live._denumerator)
        if num_steps is None:
            self._show_status(f"Résolution 1/{res} impossible dans la signature "
                              f"{live._num_beats}/{live._denumerator}")
            return
        idx = self._cur_pattern_idx
        if (num_bars, num_steps) != (live._num_bars, live._num_steps):
            self._add_undo(f"Redimensionner pattern {idx + 1:02d}")
            self._resize_live_pattern(num_bars, num_steps)
            self._refresh_grid()
        self._show_status(f"Pattern {idx + 1:02d}: {live._num_bars} mesure"
                          f"{'s' if live._num_bars > 1 else ''}, résolution 1/{res}")

    def _menu_reset_pattern(self):
        """Pattern > Redimensionner > Vider le pattern (Shift+Suppr), avec Undo."""
        self._key_manager.reset_pattern_undo()

    def _menu_track_mute(self):
        """Piste > Mute de la piste (X de la liste des pistes, 3b3)."""
        self._key_manager.track_mute_toggle()

    def _menu_unmute_all(self):
        self._key_manager.track_unmute_all()

    def _menu_track_solo(self):
        self._key_manager.track_solo_toggle()

    def _menu_unsolo_all(self):
        self._key_manager.track_unsolo_all()

    # --- Transport ----------------------------------------------------

    def _menu_set_tempo(self):
        """Transport > Métronome > Régler le tempo… (3d1, § 3b2 A2) : le
        premier tempo ; tous les tempos changent dans la même proportion,
        comme ( ) et le champ BPM ; un point d'Undo, rien si inchangé."""
        from tempo_map import format_bpm
        from .dialogs_menu import TempoSetDialog
        p, metro = self._player, self._player._metro
        metro.reset_tap()

        def click(on):                     # case Click : comme la touche C
            if on and not p.clicking:
                p.play_click()
            elif not on and p.clicking:
                p.stop_click()
            self._show_status(f"Click: {'On' if on else 'Off'}")
        # Entendu en direct, rétabli avant l'Undo ou à l'annulation (essai de
        # 3d1, même mécanisme que le champ Tempo des propriétés, 20e3)
        self._tempo_origin = (p.bpm, list(p._pattern._tempo_changes))
        dlg = TempoSetDialog(self, p.tempo_at(0), metro.tap,
                             lambda: len(getattr(metro, "_tap_times", [])),
                             on_change=self._preview_properties_tempo,
                             click=(lambda: p.clicking, click))
        ok, bpm = dlg.ShowModal() == wx.ID_OK, dlg.get_value()
        dlg.Destroy()
        self._restore_properties_tempo()
        if not ok:
            return
        if bpm != round(p.tempo_at(0)):
            self._add_undo(f"Tempo : {bpm} BPM (tous les tempos en proportion)")
            p.set_tempo_scaled(bpm, 0)
            self._update_bpm_display()
            if getattr(self, "_midi_editor_window", None) is not None:
                self._midi_editor_window.refresh()
        self._show_status(f"Premier tempo : {format_bpm(p.tempo_at(0))} BPM")

    def _menu_tap_tempo(self):
        """Transport > Métronome > Tap Tempo (H, sauf dans un champ, 3b3)."""
        self._key_manager.tap_tempo()

    # --- Mixer --------------------------------------------------------

    def _menu_set_value(self, title, label, value, lo, hi, apply, announce):
        """« Régler… » (3d1) : ValueDialog, puis apply(valeur) (avec Undo,
        rien si inchangé) et announce(valeur obtenue) dans la barre d'état."""
        from .dialogs_menu import ValueDialog
        dlg = ValueDialog(self, title, label, value, lo, hi)
        ok, v = dlg.ShowModal() == wx.ID_OK, dlg.get_value()
        dlg.Destroy()
        if ok:
            self._show_status(announce(apply(v)))

    def _menu_set_master_volume(self):
        self._menu_set_value("Régler le volume global", "Volume global", self._player.volume,
                             0, self.MASTER_VOLUME_MAX, self._set_master_volume_undo,
                             lambda v: f"Volume Global: {self.master_volume_text(v)}")

    def _menu_set_master_pan(self):
        self._menu_set_value("Régler le pan global", "Pan global", self._player.pan,
                             -100, 100, self._set_master_pan_undo,
                             lambda v: f"Pan Global: {v}")

    def _menu_set_track_volume(self):
        t = self._player._cur_track
        self._menu_set_value("Régler le volume de la piste", f"Volume de la piste {t + 1}",
                             self._router.get_track_volume(t), 0, 100,
                             lambda v: self._set_track_volume_undo(t, v),
                             lambda v: f"Piste {t + 1}: Volume {v}")

    def _menu_set_track_pan(self):
        t = self._player._cur_track
        self._menu_set_value("Régler le pan de la piste", f"Pan de la piste {t + 1}",
                             self._router.get_track_pan(t), -100, 100,
                             lambda v: self._set_track_pan_undo(t, v),
                             lambda v: f"Piste {t + 1}: Pan {v}")

    def _menu_track_volume(self, delta):
        self._key_manager.track_volume_step(delta)

    def _menu_track_pan(self, delta):
        self._key_manager.track_pan_step(delta)

    def _menu_master_mix_reset(self):
        self._key_manager.master_mix_reset()

    def _menu_track_mix_reset(self):
        self._key_manager.track_mix_reset()
