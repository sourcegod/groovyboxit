#python3
"""
    File: src/ui/mw_tempo.py
    Méthodes MainWindow de la carte de tempo (Phase 7 étape 19f1,
    docs/DESIGN.md § 19a1 T8, T9, § 19d2 R3) : dialogue Tempo (Alt+Shift+T),
    insertion, modification et suppression d'un tempo avec Undo, partagées
    avec la liste des événements de l'éditeur MIDI.
    Date: Thu, 29/10/2026
    Author: Coolbrother
"""
from tempo_map import format_bpm


class TempoMixin:
    """Tempos du pattern courant : le player les applique (position gardée
    en lecture), la fenêtre pose l'Undo et rafraîchit l'affichage."""

    def _tempo_dialog(self, parent=None):
        """Alt+Shift+T : dialogue Tempo, ouvert sur le tempo en vigueur."""
        from ui.dialogs_tempo import TempoDialog
        dlg = TempoDialog(parent or self, self)
        dlg.ShowModal()
        dlg.Destroy()
        self._update_bpm_display()

    def _tempo_pos_str(self, pos):
        """Position en 'mesure:temps:pas' 1-based (fraction de pas ignorée)."""
        pat = self._player._pattern
        spb = max(1, int(pat.steps_per_beat()))
        bar, rem   = divmod(int(pos), pat._num_steps)
        beat, tick = divmod(rem, spb)
        return f"{bar + 1}:{beat + 1}:{tick + 1}"

    def _tempo_item_label(self, idx, pos, bpm):
        """« 1:1:1, 92 BPM, départ » / « 33:1:1, 80 BPM »."""
        label = f"{self._tempo_pos_str(pos)}, {format_bpm(bpm)} BPM"
        return label + ", départ" if idx < 0 else label

    def _tempo_changed(self, msg):
        """Après un changement de la carte : champ BPM, statut, éditeur MIDI."""
        self._update_bpm_display()
        self._show_status(msg)
        if getattr(self, "_midi_editor_window", None) is not None:
            self._midi_editor_window.refresh()

    def _tempo_insert(self, pos, bpm):
        title = f"Tempo : insérer {format_bpm(bpm)} BPM à {self._tempo_pos_str(pos)}"
        self._add_undo(title)
        if not self._player.insert_tempo(pos, bpm):
            self._pop_last_undo()
            self._show_status("Tempo : inchangé (égal au tempo précédent)")
            return False
        self._tempo_changed(title)
        return True

    def _tempo_modify(self, idx, pos, bpm, scope="recent"):
        """scope : DrumPlayer.SCOPE_RECENT, SCOPE_SET_ALL ou SCOPE_SCALE_ALL."""
        player = self._player
        if scope == player.SCOPE_SCALE_ALL:
            title = f"Tempo : tous les tempos proportionnellement, {format_bpm(bpm)} BPM " \
                    f"au lieu de {format_bpm(player.tempo_items()[idx + 1][2])}"
        elif scope == player.SCOPE_SET_ALL:
            title = f"Tempo : tous les tempos à {format_bpm(bpm)} BPM"
        else:
            title = f"Tempo : {format_bpm(bpm)} BPM à {self._tempo_pos_str(pos)}"
        self._add_undo(title)
        if not player.modify_tempo(idx, pos, bpm, scope):
            self._pop_last_undo()
            self._show_status("Tempo : inchangé")
            return False
        self._tempo_changed(title)
        return True

    def _tempo_tap(self, idx):
        """Une frappe du bouton « Tap Tempo » du dialogue (Phase 7 étape
        19i1) : mécanique de H (Metronome.tap : 4 frappes au moins, pause de
        plus de 2 s = nouvelle série, un Undo par série) ; le tempo idx
        prend la valeur tapée et tous les autres suivent dans la même
        proportion. Retourne le BPM appliqué, ou None (pas encore assez de
        frappes)."""
        player = self._player
        metro  = player._metro
        _i, pos, old = player.tempo_items()[idx + 1]
        if metro.is_fresh_sequence():
            self._add_undo(f"Tap Tempo (BPM: {format_bpm(old)})")
        bpm = metro.tap()
        if bpm is None:
            return None
        player.modify_tempo(idx, pos, bpm, player.SCOPE_SCALE_ALL)
        self._tempo_changed(f"Tap Tempo: {format_bpm(bpm)} BPM")
        return bpm

    def _tempo_delete(self, idx):
        _i, pos, bpm = self._player.tempo_items()[idx + 1]
        title = f"Tempo : supprimer {format_bpm(bpm)} BPM à {self._tempo_pos_str(pos)}"
        self._add_undo(title)
        if not self._player.delete_tempo(idx):
            self._pop_last_undo()
            return False
        self._tempo_changed(title)
        return True
