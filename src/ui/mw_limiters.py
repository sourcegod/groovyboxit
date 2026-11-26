#python3
"""
    File: src/ui/mw_limiters.py
    Limiteurs gauche / droit (Phase 9 étape 3g4, docs/DESIGN.md § Phase 9
    étapes 3g2 et 3g3) : jusqu'ici une simple sélection, ils deviennent une
    donnée du projet.
    - enregistrés dans le .gvp (clé "limiters" ; absente : aucun limiteur) et
      capturés par l'Undo (U1, U2) ;
    - une entrée d'Undo par commande qui les change, rien si rien ne change
      (U3) : _set_limiters_undo, appelée par i / o, Shift+I / Shift+O
      (fenêtre principale et éditeur MIDI), Alt+Début, Ctrl+A /
      Ctrl+Shift+A, Ctrl+Entrée, Ctrl+Début / Ctrl+Fin de l'éditeur et le
      dialogue Sélection des limiteurs (Ctrl+Shift+I, deux fenêtres).
    Date: Tue, 24/11/2026
    Author: Coolbrother
"""
import wx


class LimitersMixin:
    """Mixin MainWindow : limiteurs dans le projet et dans l'Undo."""

    # --- projet et Undo -----------------------------------------------

    def _limiters_dict(self):
        te = self._track_editor
        return {"left": te._lim_left, "right": te._lim_right}

    def _limiters_from_dict(self, d):
        """Limiteurs d'une clé "limiters" (pas entiers ≥ 0, ou None) ;
        absente ou invalide : aucun limiteur."""
        te = self._track_editor
        te.reset_lims()
        if not isinstance(d, dict):
            return
        for key, setter in (("left", te.set_lim_left), ("right", te.set_lim_right)):
            v = d.get(key)
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                setter(v)

    # --- changement avec Undo -----------------------------------------

    def _lim_bbt(self, step):
        pat = self._player._pattern
        total = pat._num_bars * pat._num_steps
        return self._track_editor.fmt_bbt(
            step, pat._num_steps, max(1, pat._num_steps // pat._num_beats), total)

    def _lim_end_bbt(self, right):
        """Limiteur droit tel que l'utilisateur le voit : la position EXCLUE
        (interne + 1), comme la fin de boucle (Phase 9 étape 4d1, § 4a L1)."""
        return self._lim_bbt(right + 1)

    def _limiters_title(self, left, right):
        """« Limiteurs : 2:1:1 à 5:1:1 », « Limiteur gauche : 2:1:1 »,
        « Limiteurs effacés » — droit exclu (4d1)."""
        te = self._track_editor
        if left is None and right is None:
            return "Limiteurs effacés"
        if right == te._lim_right and left is not None:
            return f"Limiteur gauche : {self._lim_bbt(left)}"
        if left == te._lim_left and right is not None:
            return f"Limiteur droit : {self._lim_end_bbt(right)}"
        return (f"Limiteurs : {self._lim_bbt(left) if left is not None else '—'} à "
                f"{self._lim_end_bbt(right) if right is not None else '—'}")

    def _right_limiter_here(self, position, status=None):
        """o (fenêtre principale, éditeur MIDI) : limiteur droit à la
        position, EXCLUE (interne = position − 1 ; 4d1, § 4a L2) ; refusé
        si la plage serait vide (au limiteur gauche ou avant, 1:1:1 sans
        limiteur gauche), avec le bip d'alerte. True si posé."""
        status = status or self._show_status
        te = self._track_editor
        if position <= (te._lim_left or 0):
            from .ui_beep import alert
            alert(self)
            status("Limiteur droit refusé : il doit être après le limiteur gauche")
            return False
        self._set_limiters_undo(te._lim_left, position - 1)
        status(f"Limiteur Droit: {self._lim_bbt(position)}")
        return True

    def _set_limiters_undo(self, left, right, title=None):
        """Pose les deux limiteurs (pas, base 0, ou None), avec une entrée
        d'Undo si l'un change (U3) ; True si quelque chose a changé."""
        te = self._track_editor
        if (left, right) == (te._lim_left, te._lim_right):
            return False
        self._add_undo(title or self._limiters_title(left, right))
        te._lim_left, te._lim_right = left, right
        return True

    # --- dialogue Sélection des limiteurs (Ctrl+Shift+I) ---------------

    def _limiter_select_dialog(self, parent=None, status=None):
        """Ctrl+Shift+I (fenêtre principale et éditeur MIDI, § 3g3 R2) : les
        deux limiteurs ; un point d'Undo, rien si rien ne change."""
        from .dialogs_temporal import LimiterSelectDialog
        p, te = self._player, self._track_editor
        pat = p._pattern
        status = status or self._show_status
        dlg = LimiterSelectDialog(
            parent or self, pat._num_bars, pat._num_beats, pat._num_steps,
            int(p._current_offset()), te._lim_left, te._lim_right,
            pat._loop_start, pat._loop_end, on_play_toggle=self._play_toggle)
        ok = dlg.ShowModal() == wx.ID_OK
        left, end = dlg.get_start_step(), dlg.get_end_step()     # fin exclue (4d1)
        dlg.Destroy()
        if not ok:
            return False
        text = f"Limiteurs : {self._lim_bbt(left)} à {self._lim_bbt(end)}"
        self._set_limiters_undo(left, end - 1, text)
        status(text)
        return True
