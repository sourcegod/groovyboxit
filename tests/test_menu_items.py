#python3
"""
    File: tests/test_menu_items.py
    Nouveaux éléments de menus (Phase 9 étape 3c1, docs/DESIGN.md § Phase 9
    étapes 3a, 3b2, 3b4) :
    - description : Edition (sous-menu Sélection), Transport (Métronome,
      Limiteurs), Aller à, Piste, menus Pattern et Mixer, raccourcis
      retirés (Ctrl+P, Shift+P), pas des éléments = pas des raccourcis ;
    - run avec arguments, Supprimer rejoué dans l'éditeur MIDI ;
    - vraie fenêtre principale (une pour le module) : éléments par méthode
      quel que soit le focus (piste et pattern précédents / suivants,
      sélection, volumes et pans, remises, Mute / Solo, Tap Tempo), Undo de
      Suppr et de Vider le pattern, limiteurs ↔ boucle (Alt+Début /
      Alt+Fin), BPM annoncé, éléments rejoués par le vrai clavier.
    Date: Tue, 24/11/2026
    Author: Coolbrother
"""
import os

import pytest
import wx

from ui import menu_bar
from ui.menu_bar import MENUS, SEP, Submenu

DOC = os.path.join(os.path.dirname(__file__), "..", "docs", "shortcuts.md")


def _menu(title):
    return dict((t, i) for t, _l, i in MENUS)[title]


def _sub(items, text):
    return [it for it in items if isinstance(it, Submenu) and it.text() == text][0]


def _flat(items):
    for it in items:
        if isinstance(it, Submenu):
            yield from _flat(it.items)
        elif it is not SEP:
            yield it


def _all():
    return [it for _t, _l, items in MENUS for it in _flat(items)]


def _find(text):
    return [it for it in _all() if it.text() == text][0]


def _row(items):
    """[(texte, raccourci, méthode, arguments)] des éléments d'un menu."""
    return [(it.text(), it.accel, it.call, it.args) for it in items if it is not SEP
            and not isinstance(it, Submenu)]


# ----------------------------------------------------------------------
# Description
# ----------------------------------------------------------------------

def test_edition_items():
    ed = _menu("Edition")
    accels = {it.text(): it.accel for it in _flat(ed)}
    assert {k: accels[k] for k in ("Couper", "Copier", "Coller", "Coller par fusion",
                                   "Supprimer", "Supprimer avec presse-papier",
                                   "Effacer sans presse-papier", "Sélectionner tout",
                                   "Tout désélectionner")} == {
        "Couper": "Ctrl+X", "Copier": "Ctrl+C", "Coller": "Ctrl+V",
        "Coller par fusion": "Shift+V", "Supprimer": "Suppr",
        "Supprimer avec presse-papier": "Ctrl+D", "Effacer sans presse-papier": "Ctrl+Suppr",
        "Sélectionner tout": "Ctrl+A", "Tout désélectionner": "Ctrl+Shift+A"}
    delete = _find("Supprimer")
    assert delete.call == "_menu_delete" and set(delete.windows) == {menu_bar.MAIN, menu_bar.MIDI}
    assert _row(_sub(ed, "Sélection").items) == [
        ("Sélectionner la piste courante", "Shift+Espace", "_menu_select_track", (True,)),
        ("Désélectionner la piste courante", "Shift+Espace", "_menu_select_track", (False,)),
        ("Sélection des pistes…", "Ctrl+Entrée", "_track_select_dialog", ())]


def test_transport_metronome_and_limiters():
    tr = _menu("Transport")
    assert _row(_sub(tr, "Métronome").items) == [
        ("Click On / Off", "C", None, ()), ("Tap Tempo", "H", "_menu_tap_tempo", ()),
        ("BPM +5", "(", None, ()), ("BPM −5", ")", None, ())]
    assert _row(_sub(tr, "Limiteurs").items) == [
        ("Limiteur gauche ici", "I", None, ()), ("Limiteur droit ici", "O", None, ()),
        ("Limiteur gauche au début", "Shift+I", None, ()),
        ("Limiteur droit à la fin", "Shift+O", None, ()),
        ("Assigner la boucle aux limiteurs", "Alt+Début", None, ()),
        ("Assigner les limiteurs à la boucle", "Alt+Fin", None, ())]
    assert not [it for it in tr if it is not SEP and not isinstance(it, Submenu)
                and "Limiteur" in it.text()]                      # tous dans le sous-menu


def test_goto_limiters_and_loop():
    accels = {it.text(): it.accel for it in _flat(_menu("Aller à"))}
    assert [accels[t] for t in ("Au limiteur gauche", "Au limiteur droit",
                                "Au début de la boucle", "À la fin de la boucle")] == [
        "Début", "Fin", "Shift+Début", "Shift+Fin"]


def test_track_menu():
    rows = _row(_menu("Piste"))
    assert rows[:2] == [("Piste précédente", None, "_menu_step_track", (-1,)),
                        ("Piste suivante", None, "_menu_step_track", (1,))]
    texts = [r[0] for r in rows]
    assert texts.index("Désactiver tous les Solos") < texts.index("Mute exclusif")
    assert [r[1:3] for r in rows if r[0] in ("Mute de la piste", "Démuter toutes les pistes",
                                              "Solo de la piste", "Désactiver tous les Solos")] == [
        ("X", "_menu_track_mute"), ("Shift+X", "_menu_unmute_all"),
        ("S", "_menu_track_solo"), ("Shift+S", "_menu_unsolo_all")]


def test_pattern_menu_and_file_without_pattern_items():
    pat = _menu("Pattern")
    assert _row(_sub(pat, "Changer de pattern").items) == [
        ("Pattern précédent", None, "_menu_step_pattern", (-1,)),
        ("Pattern suivant", None, "_menu_step_pattern", (1,))]
    assert _row(pat) == [
        ("Propriétés du pattern…", "Alt+Entrée", "_pattern_properties_dialog", ()),
        ("Enregistrer le pattern", "Ctrl+W", None, ()),
        ("Dupliquer le pattern…", "Ctrl+Shift+W", None, ())]
    assert _row(_sub(pat, "Redimensionner").items) == [
        ("Doubler", "Ctrl+F", None, ()), ("Diviser", "Shift+F", None, ()),
        ("Vider le pattern", "Shift+Suppr", "_menu_reset_pattern", ())]
    assert all("pattern" not in it.text() for it in _flat(_menu("Fichier")))
    assert all(set(it.windows) == {menu_bar.MAIN} for it in _flat(pat))


def test_mixer_steps_are_those_of_the_shortcuts():
    mixer = _menu("Mixer")
    assert [s.text() for s in mixer if isinstance(s, Submenu)] == ["Volume", "Pan"]
    assert _row(_sub(mixer, "Volume").items) == [
        ("Volume global +1", "Ctrl+Haut", None, ()),
        ("Volume global −1", "Ctrl+Bas", None, ()),
        ("Volume de la piste +5", "Alt+Haut", "_menu_track_volume", (5,)),
        ("Volume de la piste −5", "Alt+Bas", "_menu_track_volume", (-5,))]
    assert _row(_sub(mixer, "Pan").items) == [
        ("Pan global à droite +1", "Ctrl+Droite", None, ()),
        ("Pan global à gauche −1", "Ctrl+Gauche", None, ()),
        ("Pan de la piste à droite +10", "Alt+Droite", "_menu_track_pan", (10,)),
        ("Pan de la piste à gauche −10", "Alt+Gauche", "_menu_track_pan", (-10,))]
    assert _row(mixer) == [
        ("Volume et pan globaux normaux", "Ctrl+Retour arrière", "_menu_master_mix_reset", ()),
        ("Volume et pan de la piste normaux", "Shift+Retour arrière",
         "_menu_track_mix_reset", ())]


def test_demo_and_random_pattern_are_gone():
    accels = {it.accel for it in _all()}
    assert not {"Ctrl+P", "Shift+P"} & accels
    with open(DOC, encoding="utf-8") as f:
        doc = f.read()
    assert "pattern de démonstration" not in doc and "pattern aléatoire" not in doc


def test_help_tells_the_new_letters_and_shortcuts():
    with open(DOC, encoding="utf-8") as f:
        doc = f.read()
    assert "P Pattern" in doc and "M Mixer" in doc
    assert "Alt+Début" in doc and "Alt+Fin" in doc


# ----------------------------------------------------------------------
# run, Supprimer dans l'éditeur
# ----------------------------------------------------------------------

class _Win(menu_bar.MenuBarMixin, wx.EvtHandler):
    _menu_kind = menu_bar.MIDI

    def __init__(self):
        wx.EvtHandler.__init__(self)
        self.keys, self.calls, self.msgs = [], [], []

    def __bool__(self):
        return True

    def _on_key(self, evt):
        self.keys.append(menu_bar.accel_of(evt))

    def _set_status(self, msg):
        self.msgs.append(msg)

    def _menu_step_track(self, delta):
        self.calls.append(delta)


def test_run_passes_the_arguments():
    win = _Win()
    menu_bar.run(win, _find("Piste suivante"))
    menu_bar.run(win, _find("Piste précédente"))
    assert win.calls == [1, -1] and win.keys == []


def test_delete_replays_suppr_in_the_midi_editor():
    win = _Win()
    menu_bar.run(win, _find("Supprimer"))
    assert win.keys == ["Suppr"] and win.msgs == []


def test_replay_announces_a_skipped_key():
    class _S(_Win):
        def _on_key(self, evt):
            evt.Skip()
    win = _S()
    menu_bar.replay(win, "Suppr", "Supprimer")
    assert win.msgs == ["Supprimer : sans effet ici"]


# ----------------------------------------------------------------------
# Vraie fenêtre principale (une pour le module)
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def main_win():
    from ui.main_window import MainWindow
    win = MainWindow()
    yield win
    win._router.wait_loaded()
    win._close_midi_devices()
    win._audio_driver.close()
    win.Destroy()


@pytest.fixture
def win(main_win, monkeypatch):
    """La fenêtre, focus hors de ses listes (sur la grille, dirait-on), barre
    d'état enregistrée, piste et pattern 1."""
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: None))
    w = main_win
    if w._cur_pattern_idx:
        w._switch_pattern(0)
    w._go_to_track(0)
    w._track_editor.clear_selection()
    w._track_editor.reset_lims()
    status = []
    monkeypatch.setattr(w, "_show_status", status.append)
    w.status = status
    return w


def _titles(w):
    return [e.title for e in w._undo.history_list()]


def _run(w, text):
    w.status.clear()
    menu_bar.run(w, _find(text))
    return w.status[-1] if w.status else None


@pytest.mark.gui
def test_next_and_previous_track_keep_the_focus_and_move_the_list(win):
    from ui.gtk_listbox import cursor_row
    _run(win, "Piste suivante")
    assert win._player._cur_track == 1
    assert win._track_list.GetSelection() == 1
    assert cursor_row(win._track_list) in (1, None)           # None : liste sans GTK
    _run(win, "Piste précédente")
    assert win._player._cur_track == 0
    assert _run(win, "Piste précédente") == "Piste 1: première piste"
    win._go_to_track(win._track_list.GetCount() - 1)
    n = win._track_list.GetCount()
    assert _run(win, "Piste suivante") == f"Piste {n}: dernière piste"
    assert win._player._cur_track == n - 1


@pytest.mark.gui
def test_next_track_keeps_the_selection(win):
    win._track_editor.toggle_track(0)
    _run(win, "Piste suivante")
    assert win._track_editor.is_selected(0)


@pytest.mark.gui
def test_next_and_previous_pattern(win):
    _run(win, "Pattern suivant")
    assert win._cur_pattern_idx == 1 and win._pattern_listbox.GetSelection() == 1
    _run(win, "Pattern précédent")
    assert win._cur_pattern_idx == 0
    assert _run(win, "Pattern précédent") == "Pattern 01: premier pattern"


@pytest.mark.gui
def test_select_and_deselect_the_current_track(win):
    te = win._track_editor
    assert _run(win, "Sélectionner la piste courante") == "Sélection: Piste 1"
    assert te.is_selected(0)
    assert _run(win, "Sélectionner la piste courante") == "Piste 1: déjà sélectionnée"
    assert _run(win, "Désélectionner la piste courante") == "Piste 1: désélectionnée"
    assert not te.is_selected(0)
    assert _run(win, "Désélectionner la piste courante") == \
        "Piste 1: déjà hors de la sélection"


@pytest.mark.gui
def test_track_volume_and_pan_from_the_grid(win):
    """Focus sur la grille : Alt+flèches agiraient sur le pad ; l'élément
    agit sur la piste courante."""
    r = win._router
    r.set_track_volume(0, 90)
    r.set_track_pan(0, 0)
    pad_volume = win._player.voice_manager.get_voice(win._cur_row).volume
    assert _run(win, "Volume de la piste +5") == "Piste 1: Volume 95"
    assert _run(win, "Pan de la piste à gauche −10") == "Piste 1: Pan -10"
    assert (r.get_track_volume(0), r.get_track_pan(0)) == (95, -10)
    assert win._player.voice_manager.get_voice(win._cur_row).volume == pad_volume
    assert _titles(win)[0] == "Pan piste 1: -10"
    assert _run(win, "Volume et pan de la piste normaux") == "Piste 1: Volume 100, Pan 0 (centre)"
    assert (r.get_track_volume(0), r.get_track_pan(0)) == (100, 0)


@pytest.mark.gui
def test_global_volume_pan_and_reset(win):
    vol0 = win._player.volume
    _run(win, "Volume global +1")
    assert win._player.volume == vol0 + 1
    _run(win, "Pan global à droite +1")
    assert win._player.pan == 1
    assert "(préférences)" in _run(win, "Volume et pan globaux normaux")
    assert (win._player.volume, win._player.pan) == win._master_defaults


@pytest.mark.gui
def test_track_mute_and_solo_from_the_grid(win):
    r = win._router
    r.unmute_all_tracks()
    r.unsolo_all_tracks()
    assert _run(win, "Mute de la piste").startswith("Piste 1: Mute On")
    assert r._track_mutes[0] and not win._player.voice_manager.any_mute()
    assert _titles(win)[0] == "Mute piste 1"
    assert _run(win, "Solo de la piste").startswith("Piste 1: Solo On")
    assert _run(win, "Démuter toutes les pistes").startswith("Toutes les Pistes: Démutées")
    assert _run(win, "Désactiver tous les Solos").startswith("Toutes les Pistes: Désolotées")
    assert not any(r._track_mutes) and not any(r._track_solos)


@pytest.mark.gui
def test_delete_and_empty_pattern_can_be_undone(win):
    win._set_cell(0, 0, True)
    assert _run(win, "Supprimer") == "Effacé: Piste 1"
    assert _titles(win)[0] == "Effacer piste 1"
    assert not win._cells[0][0].GetValue()
    win._undo_action()
    assert win._cells[0][0].GetValue()
    assert _run(win, "Vider le pattern") == "Pattern réinitialisé"
    assert _titles(win)[0] == "Vider le pattern"
    win._undo_action()
    assert win._cells[0][0].GetValue()
    win._set_cell(0, 0, False)


@pytest.mark.gui
def test_limiters_to_loop_and_back(win):
    pat, te = win._player._pattern, win._track_editor
    pat._loop_start = pat._loop_end = None
    total = pat._num_bars * pat._num_steps
    te.set_lim_left(pat._num_steps)
    te.set_lim_right(2 * pat._num_steps - 1)
    msg = _run(win, "Assigner les limiteurs à la boucle")
    assert msg.startswith("Boucle : 2:1:1 à ")
    assert (pat._loop_start, pat._loop_end) == (pat._num_steps, 2 * pat._num_steps - 1)
    saved = win._pattern_list[win._cur_pattern_idx]
    assert (saved._loop_start, saved._loop_end) == (pat._loop_start, pat._loop_end)
    undo_count = len(_titles(win))
    _run(win, "Assigner les limiteurs à la boucle")           # rien ne change : pas d'Undo
    assert len(_titles(win)) == undo_count
    te.reset_lims()
    assert _run(win, "Assigner la boucle aux limiteurs").startswith("Limiteurs : 2:1:1 à ")
    assert (te._lim_left, te._lim_right) == (pat._num_steps, 2 * pat._num_steps - 1)
    win._undo_action()                                         # la boucle d'avant
    pat = win._player._pattern
    assert (pat._loop_start, pat._loop_end) == (None, None)
    te.reset_lims()                                            # absents : tout le pattern
    _run(win, "Assigner les limiteurs à la boucle")
    assert (pat._loop_start, pat._loop_end) == (None, None)
    _run(win, "Assigner la boucle aux limiteurs")
    assert (te._lim_left, te._lim_right) == (0, total - 1)


@pytest.mark.gui
def test_limiters_to_loop_refused_when_crossed(win):
    pat, te = win._player._pattern, win._track_editor
    pat._loop_start = pat._loop_end = None
    te.set_lim_left(20)
    te.set_lim_right(5)
    assert _run(win, "Assigner les limiteurs à la boucle") == \
        "Boucle : limiteur gauche après le limiteur droit"
    assert (pat._loop_start, pat._loop_end) == (None, None)


@pytest.mark.gui
@pytest.mark.parametrize("accel, msg", [("Alt+Début", "Limiteurs : "), ("Alt+Fin", "Boucle : ")])
def test_alt_home_and_end_no_longer_do_home_and_end(win, accel, msg):
    win._player._pattern._loop_start = win._player._pattern._loop_end = None
    win.status.clear()
    win._key_manager.handle(menu_bar.key_event(accel))
    assert win.status[-1].startswith(msg)


@pytest.mark.gui
def test_bpm_steps_are_announced(win):
    bpm = round(win._player.tempo_at())
    assert _run(win, "BPM +5") == f"BPM: {bpm + 5}"
    assert _run(win, "BPM −5") == f"BPM: {bpm}"


@pytest.mark.gui
def test_tap_tempo_item_calls_the_shared_tap(win, monkeypatch):
    taps = []
    monkeypatch.setattr(win._key_manager, "tap_tempo", lambda: taps.append(1))
    _run(win, "Tap Tempo")
    assert taps == [1]


@pytest.mark.gui
def test_replayed_items_go_through_the_real_keyboard(win):
    te = win._track_editor
    assert _run(win, "Sélectionner tout").startswith("Toutes les pistes sélectionnées")
    assert _run(win, "Tout désélectionner").startswith("Sélection effacée")
    assert _run(win, "Limiteur gauche au début") == "Limiteur Gauche: 1:1:1"
    assert te._lim_left == 0
    assert _run(win, "Click On / Off") == "Click: On"
    assert _run(win, "Click On / Off") == "Click: Off"
