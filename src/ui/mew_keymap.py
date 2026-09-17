import wx


class KeymapMixin:
    """MidiEditorWindow — dispatch clavier (_on_key)."""

    def _on_key(self, evt):
        key   = evt.GetKeyCode()
        ukey  = evt.GetUnicodeKey()
        ctrl  = evt.ControlDown()
        shift = evt.ShiftDown()
        alt   = evt.AltDown()

        if key == wx.WXK_ESCAPE:
            self.Close()
            return

        # Ctrl+1 : mode notes de la piste courante
        if ctrl and not shift and (ukey == ord('1') or key == ord('1')):
            self._view_mode = self.MODE_NOTES
            self._parent._midi_editor_view_mode = self.MODE_NOTES
            self._refresh()
            self._set_status("Mode : Notes de la piste courante")
            return

        # Ctrl+2 : mode tous les événements
        if ctrl and not shift and (ukey == ord('2') or key == ord('2')):
            self._view_mode = self.MODE_ALL
            self._parent._midi_editor_view_mode = self.MODE_ALL
            self._refresh()
            self._set_status("Mode : Tous les événements MIDI")
            return

        # ←/→ : navigation entre groupes temporels — MODE_NOTES uniquement ;
        # en MODE_ALL (liste plate, Ctrl+2) la navigation se fait au ↑/↓ seul.
        if not ctrl and not shift and key == wx.WXK_LEFT:
            if self._view_mode == self.MODE_NOTES:
                self._move_left()
            return
        if not ctrl and not shift and key == wx.WXK_RIGHT:
            if self._view_mode == self.MODE_NOTES:
                self._move_right()
            return

        # Shift+←/→ : navigation + sélection du groupe
        if not ctrl and shift and key == wx.WXK_LEFT:
            self._select_move_left()
            return
        if not ctrl and shift and key == wx.WXK_RIGHT:
            self._select_move_right()
            return

        # ↑/↓ : MODE_NOTES = navigation dans l'accord courant (groupée) ;
        # MODE_ALL = navigation événement par événement dans la liste plate
        # (sans regroupement), met à jour l'index affiché en tête de ligne.
        # MODE_ALL : liste plate == exactement la navigation native d'une
        # ListBox (une ligne à la fois), donc on laisse GTK naviguer
        # nativement (evt.Skip()) plutôt que d'appeler SetSelection() par
        # programme — un SetSelection() programmatique sous EVT_CHAR_HOOK
        # (niveau fenêtre) n'est PAS annoncé par Orca pour cette ListBox,
        # même combiné à SetString() (essayé et écarté, cf. mémoire
        # accessibilité), alors que la navigation native déclenche
        # EVT_LISTBOX ET l'annonce Orca correctement (même trick que le
        # clavier virtuel 7f, _on_vk_listbox_select). MODE_NOTES garde la
        # navigation groupée par accord (SetSelection() programmatique
        # nécessaire ici car le comportement diffère du pas-à-pas natif :
        # Haut/Bas reste dans l'accord, Gauche/Droite change de groupe) —
        # annoncée via le canal de secours _set_status (cf. SPECS.md
        # accessibilité).
        if not ctrl and not shift and key == wx.WXK_UP:
            if self._vk_lb.HasFocus() or self._view_mode == self.MODE_ALL:
                evt.Skip()
            else:
                self._move_up_in_group()
            return
        if not ctrl and not shift and key == wx.WXK_DOWN:
            if self._vk_lb.HasFocus() or self._view_mode == self.MODE_ALL:
                evt.Skip()
            else:
                self._move_down_in_group()
            return

        # Shift+↑/↓ : navigation + sélection — MODE_NOTES = regroupée par
        # accord (_select_move_up/down) ; MODE_ALL = liste plate, un
        # événement à la fois (_select_move_up_flat/down_flat).
        if not ctrl and shift and key == wx.WXK_UP:
            if self._view_mode == self.MODE_ALL:
                self._select_move_up_flat()
            else:
                self._select_move_up()
            return
        if not ctrl and shift and key == wx.WXK_DOWN:
            if self._view_mode == self.MODE_ALL:
                self._select_move_down_flat()
            else:
                self._select_move_down()
            return

        # Ctrl+A : sélectionner tout
        if ctrl and not shift and (ukey == ord('a') or ukey == ord('A')):
            self._select_all()
            return

        # Ctrl+Shift+A : désélectionner tout
        if ctrl and shift and (ukey == ord('a') or ukey == ord('A')):
            self._deselect_all()
            return

        # Ctrl+C : copier
        if ctrl and not shift and (ukey == ord('c') or ukey == ord('C')):
            self._copy_events()
            return

        # Ctrl+X : couper
        if ctrl and not shift and (ukey == ord('x') or ukey == ord('X')):
            self._cut_events()
            return

        # Ctrl+V : coller
        if ctrl and not shift and (ukey == ord('v') or ukey == ord('V')):
            self._paste_events()
            return

        # Ctrl+Z : annuler
        if ctrl and not shift and (ukey == ord('z') or ukey == ord('Z')):
            self._undo_action()
            return

        # Shift+Z : refaire
        if not ctrl and shift and (ukey == ord('z') or ukey == ord('Z')):
            self._redo_action()
            return

        # Ctrl+Shift+Z : historique undo
        if ctrl and shift and (ukey == ord('z') or ukey == ord('Z')):
            self._undo_history_dialog()
            return

        # Entrée : éditer la note sélectionnée
        if not ctrl and not shift and key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._edit_note_dialog()
            return

        # Suppr / Backspace : supprimer l'événement sélectionné
        if not ctrl and key in (wx.WXK_DELETE, wx.WXK_BACK):
            self._delete_event()
            return

        # D : dupliquer (accord empilé) + avancer le playhead d'une grille
        # Shift+D : dupliquer sans bouger le playhead (étape 7i)
        if not ctrl and not shift and (ukey == ord('d') or key == ord('D')):
            self._duplicate_event(True)
            return
        if not ctrl and shift and (ukey == ord('d') or key == ord('D')):
            self._duplicate_event(False)
            return

        # Ctrl+I : insérer une note (instrument de la piste) + avancer le
        # playhead d'une grille. Alt+I : insérer sans avancer (Shift+I est
        # déjà pris par le limiteur gauche début de pattern, voir plus bas).
        # Ctrl+Shift+I : dialog note/durée/vélocité (étape 7i).
        if ctrl and shift and (ukey == ord('i') or key == ord('I')):
            self._insert_dialog()
            return
        if ctrl and not shift and (ukey == ord('i') or key == ord('I')):
            self._quick_insert(True)
            return
        if not ctrl and not shift and alt and (ukey == ord('i') or key == ord('I')):
            self._quick_insert(False)
            return

        # A : insérer une note entre l'événement courant et le suivant,
        # curseur sur la nouvelle note (étape 7n)
        if not ctrl and not shift and not alt and (ukey == ord('a') or key == ord('A')):
            self._insert_between()
            return

        # Numpad 1/3 : raccourcir/rallonger la durée (KIT/PATCH uniquement)
        if not ctrl and not shift and key == wx.WXK_NUMPAD1:
            self._numpad_shorten()
            return
        if not ctrl and not shift and key == wx.WXK_NUMPAD3:
            self._numpad_lengthen()
            return

        # Numpad 4/6 : reculer/avancer d'une valeur de la grille courante
        if not ctrl and not shift and key == wx.WXK_NUMPAD4:
            self._numpad_move(-1)
            return
        if not ctrl and not shift and key == wx.WXK_NUMPAD6:
            self._numpad_move(1)
            return

        # Numpad 7/9 : vélocité -1/+1
        if not ctrl and not shift and key == wx.WXK_NUMPAD7:
            self._numpad_velocity(-1)
            return
        if not ctrl and not shift and key == wx.WXK_NUMPAD9:
            self._numpad_velocity(1)
            return

        # Numpad 2/8 : ±1 demi-ton ; Ctrl+Numpad 2/8 : ±1 octave
        if not shift and not alt and key == wx.WXK_NUMPAD2:
            self._numpad_pitch(-12 if ctrl else -1)
            return
        if not shift and not alt and key == wx.WXK_NUMPAD8:
            self._numpad_pitch(12 if ctrl else 1)
            return

        # Alt+Numpad 2/8 : ±1 demi-ton sur le clavier virtuel (7f) — raccourci
        # global, utilisable même si la ListBox du clavier virtuel n'a pas le focus.
        # (Shift+Numpad2/8 est impossible à distinguer de Shift+Flèche Bas/Haut :
        # avec Verr. Num actif, Maj+pavé numérique est traduit en touche de
        # navigation au niveau clavier/X11, avant même d'atteindre l'appli.)
        if not ctrl and not shift and alt and key == wx.WXK_NUMPAD2:
            self._vk_move(-1)
            return
        if not ctrl and not shift and alt and key == wx.WXK_NUMPAD8:
            self._vk_move(1)
            return

        # Numpad 5 : position courante ; Ctrl+Numpad 5 : valeur de grille courante
        if not shift and key == wx.WXK_NUMPAD5:
            if ctrl:
                self._show_grid_value()
            else:
                self._show_cursor_position()
            return

        # Numpad - / + : diminuer/augmenter la valeur de la grille courante
        if not ctrl and not shift and key == wx.WXK_NUMPAD_SUBTRACT:
            self._change_grid_idx(-1)
            return
        if not ctrl and not shift and key == wx.WXK_NUMPAD_ADD:
            self._change_grid_idx(1)
            return

        # R : rafraîchir
        if not ctrl and not shift and (ukey == ord('r') or key == ord('R')):
            self._refresh()
            self._set_status("Rafraîchi")
            return

        # S : solo piste(s)
        if not ctrl and not shift and (ukey == ord('s') or key == ord('S')):
            self._toggle_track_solo()
            return

        # X : mute piste(s)
        if not ctrl and not shift and (ukey == ord('x') or key == ord('X')):
            self._toggle_track_mute()
            return

        # i : limiteur gauche à la position du playhead
        if not ctrl and not shift and (ukey == ord('i') or ukey == ord('I')):
            step = int(self._parent._player._current_offset())
            self._set_lim_left(step)
            return

        # o : limiteur droit à la position du playhead
        if not ctrl and not shift and (ukey == ord('o') or ukey == ord('O')):
            step = int(self._parent._player._current_offset())
            self._set_lim_right(step)
            return

        # Shift+I : limiteur gauche au début du pattern
        if not ctrl and shift and (ukey == ord('i') or ukey == ord('I')):
            self._set_lim_left(0)
            return

        # Shift+O : limiteur droit à la fin du pattern
        if not ctrl and shift and (ukey == ord('o') or ukey == ord('O')):
            pat  = self._parent._player._pattern
            step = pat._num_bars * pat._num_steps - 1
            self._set_lim_right(step)
            return

        # Home : premier événement de la liste filtrée
        if not ctrl and not shift and key == wx.WXK_HOME:
            self._go_first_event()
            return

        # End : dernier événement de la liste filtrée
        if not ctrl and not shift and key == wx.WXK_END:
            self._go_last_event()
            return

        # Ctrl+Home : réinitialise les limiteurs + premier événement
        if ctrl and not shift and key == wx.WXK_HOME:
            self._reset_lims()
            self._go_first_event()
            return

        # Ctrl+End : réinitialise les limiteurs + dernier événement
        if ctrl and not shift and key == wx.WXK_END:
            self._reset_lims()
            self._go_last_event()
            return

        # Ctrl+Shift+Q : boite de quantisation (même dialog que le pattern)
        if ctrl and shift and (ukey == ord('q') or ukey == ord('Q')):
            self._quantize_dialog()
            return

        # Ctrl+Q : quantiser depuis la grille courante (sans dialog)
        if ctrl and not shift and (ukey == ord('q') or ukey == ord('Q')):
            self._quantize_from_grid()
            return

        # Shift+Q : quantiser avec les derniers paramètres (sans dialog)
        if not ctrl and shift and (ukey == ord('q') or ukey == ord('Q')):
            self._quantize_with_last_params()
            return

        # Ctrl+Shift+G : boite de résolution de grille (même raccourci que la
        # fenêtre principale) — avant le transport partagé, qui a sa propre
        # version (obsolète) de Ctrl+G/Ctrl+Shift+G.
        if ctrl and shift and (ukey == ord('g') or ukey == ord('G')):
            self._grid_dialog()
            return

        # Ctrl+G : boite "Aller à" (même raccourci que la fenêtre principale)
        if ctrl and not shift and (ukey == ord('g') or ukey == ord('G')):
            self._goto_dialog()
            return

        # Ctrl+Shift+F : boite de filtre d'événements (même raccourci que la
        # fenêtre principale)
        if ctrl and shift and (ukey == ord('f') or ukey == ord('F')):
            self._filter_dialog()
            return

        # Transport partagé (Space/P, V, G, Shift+G, PageUp/Down…)
        if self._parent._key_manager.handle_transport(evt):
            pat   = self._parent._player._pattern
            step  = int(self._parent._player._current_offset())
            ns    = pat._num_steps
            spb   = max(1, ns // pat._num_beats)
            total = pat._num_bars * ns
            bbt   = self._parent._track_editor.fmt_bbt(step, ns, spb, total)
            wx.CallAfter(self._set_status, f"Position: {bbt}")
            return

        evt.Skip()
