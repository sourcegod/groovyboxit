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

    def _menu_reset_pattern(self):
        """Pattern > Redimensionner > Vider le pattern (Shift+Suppr), avec Undo."""
        self._key_manager.reset_pattern_undo()

    # --- Mixer --------------------------------------------------------

    def _menu_track_volume(self, delta):
        self._key_manager.track_volume_step(delta)

    def _menu_track_pan(self, delta):
        self._key_manager.track_pan_step(delta)

    def _menu_master_mix_reset(self):
        self._key_manager.master_mix_reset()

    def _menu_track_mix_reset(self):
        self._key_manager.track_mix_reset()
