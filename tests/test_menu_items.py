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
        ("BPM +5", "(", None, ()), ("BPM −5", ")", None, ()),
        ("Régler le tempo…", None, "_menu_set_tempo", ())]
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
        ("Pattern suivant", None, "_menu_step_pattern", (1,)),
        ("Choisir un pattern…", None, "_menu_choose_pattern", ())]
    assert _row(pat) == [
        ("Propriétés du pattern…", "Alt+Entrée", "_pattern_properties_dialog", ()),
        ("Enregistrer le pattern", "Ctrl+W", None, ()),
        ("Dupliquer le pattern…", "Ctrl+Shift+W", None, ())]
    assert _row(_sub(pat, "Redimensionner").items) == [
        ("Doubler", "Ctrl+F", None, ()), ("Diviser", "Shift+F", None, ()),
        ("Vider le pattern", "Shift+Suppr", "_menu_reset_pattern", ()),
        ("Redimensionner le pattern…", None, "_menu_resize_pattern", ())]
    assert all("pattern" not in it.text() for it in _flat(_menu("Fichier")))
    assert all(set(it.windows) == {menu_bar.MAIN} for it in _flat(pat))


def test_mixer_steps_are_those_of_the_shortcuts():
    mixer = _menu("Mixer")
    assert [s.text() for s in mixer if isinstance(s, Submenu)] == ["Volume", "Pan"]
    assert _row(_sub(mixer, "Volume").items) == [
        ("Volume global +1", "Ctrl+Haut", None, ()),
        ("Volume global −1", "Ctrl+Bas", None, ()),
        ("Régler le volume global…", None, "_menu_set_master_volume", ()),
        ("Volume de la piste +5", "Alt+Haut", "_menu_track_volume", (5,)),
        ("Volume de la piste −5", "Alt+Bas", "_menu_track_volume", (-5,)),
        ("Régler le volume de la piste…", None, "_menu_set_track_volume", ())]
    assert _row(_sub(mixer, "Pan").items) == [
        ("Pan global à droite +1", "Ctrl+Droite", None, ()),
        ("Pan global à gauche −1", "Ctrl+Gauche", None, ()),
        ("Régler le pan global…", None, "_menu_set_master_pan", ()),
        ("Pan de la piste à droite +10", "Alt+Droite", "_menu_track_pan", (10,)),
        ("Pan de la piste à gauche −10", "Alt+Gauche", "_menu_track_pan", (-10,)),
        ("Régler le pan de la piste…", None, "_menu_set_track_pan", ())]
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
    win._menu_kind = menu_bar.MAIN                 # éléments de la principale (3f3)
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


# ----------------------------------------------------------------------
# Dialogues des menus (Phase 9 étape 3e1, tests de 3d1)
# ----------------------------------------------------------------------

def _children(dlg):
    return [c for c in dlg.GetChildren() if c.IsShown()]


def _label_before(dlg, field):
    """Libellé créé juste avant le champ (Orca le lit, recette des dialogues)."""
    kids = list(dlg.GetChildren())
    prev = kids[kids.index(field) - 1]
    assert isinstance(prev, wx.StaticText)
    return prev.GetLabel()


@pytest.fixture
def parent():
    frame = wx.Frame(None)
    yield frame
    frame.Destroy()


@pytest.mark.gui
def test_value_dialog_bounds_label_and_value(parent):
    from ui.dialogs_menu import ValueDialog
    dlg = ValueDialog(parent, "Régler le pan global", "Pan global", 250, -100, 100)
    try:
        assert dlg.GetTitle() == "Régler le pan global"
        assert _label_before(dlg, dlg._spin) == "Pan global (-100 à 100) :"
        assert dlg._spin.GetName() == "Pan global (-100 à 100) :"
        assert (dlg._spin.GetMin(), dlg._spin.GetMax()) == (-100, 100)
        assert dlg.get_value() == 100                                # borné
        ok = [c for c in dlg.GetChildren() if isinstance(c, wx.Button)
              and c.GetId() == wx.ID_OK][0]
        assert ok.IsDefault() if hasattr(ok, "IsDefault") else True
    finally:
        dlg.Destroy()


@pytest.mark.gui
def test_enter_in_the_field_validates(parent, monkeypatch):
    from ui.dialogs_menu import ValueDialog
    dlg = ValueDialog(parent, "t", "Volume", 10, 0, 100)
    try:
        ended = []
        monkeypatch.setattr(dlg, "EndModal", ended.append)
        dlg._spin.ProcessEvent(wx.CommandEvent(wx.wxEVT_TEXT_ENTER, dlg._spin.GetId()))
        assert ended == [wx.ID_OK]
    finally:
        dlg.Destroy()


@pytest.mark.gui
def test_pattern_choice_dialog(parent, monkeypatch):
    from ui.dialogs_menu import PatternChoiceDialog
    dlg = PatternChoiceDialog(parent, ["Pat_01", "Pat_02 - Intro", "Pat_03"], 1)
    try:
        assert _label_before(dlg, dlg._list) == "Patterns :"
        assert dlg.get_index() == 1
        ended = []
        monkeypatch.setattr(dlg, "EndModal", ended.append)
        dlg._list.ProcessEvent(wx.CommandEvent(wx.wxEVT_LISTBOX_DCLICK, dlg._list.GetId()))
        assert ended == [wx.ID_OK]                      # Entrée sur la liste (GTK : DCLICK)
    finally:
        dlg.Destroy()


@pytest.mark.gui
def test_resize_dialog(parent):
    from ui.dialogs_menu import ResizePatternDialog
    dlg = ResizePatternDialog(parent, 4, 999, 32, (16, 32, 64, 128))
    try:
        assert _label_before(dlg, dlg._bars) == "Mesures (1 à 999) :"
        assert _label_before(dlg, dlg._res) == "Résolution :"
        assert (dlg.get_num_bars(), dlg.get_resolution()) == (4, 32)
        assert dlg._res.GetString(1) == "1/32 (triple croche)"
    finally:
        dlg.Destroy()


def _key(ch, ctrl=False):
    evt = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    evt.SetKeyCode(ord(ch.upper()) if ch.isalpha() else ord(ch))
    evt.SetUnicodeKey(ord(ch))
    evt.SetControlDown(ctrl)
    return evt


@pytest.mark.gui
def test_tempo_dialog_keys_tap_click_and_live_tempo(parent):
    from ui.dialogs_menu import TempoSetDialog
    heard, taps, clicks = [], iter([None, None, 132.4]), []
    state = {"click": False}
    dlg = TempoSetDialog(parent, 100.4, lambda: next(taps), lambda: 2, on_change=heard.append,
                         click=(lambda: state["click"], clicks.append))
    try:
        assert _label_before(dlg, dlg._spin) == "Premier tempo, BPM (1 à 600) :"
        assert dlg.get_value() == 100 and heard == []
        assert dlg.get_result() == "Premier tempo : 100 BPM (avant : 100)"
        for ch in "((":
            dlg._on_char_hook(_key(ch))
        dlg._on_char_hook(_key(")"))
        assert dlg.get_value() == 105 and heard == [105, 110, 105]      # entendu en direct
        assert dlg.get_result() == "Premier tempo : 105 BPM (avant : 100), tous les tempos × 1,05"
        dlg._on_char_hook(_key("h"))
        assert dlg.get_result() == "Tap Tempo : frappe 2, continuez (4 frappes au moins)"
        dlg.tap()
        dlg.tap()                                                 # le BPM tapé arrive
        assert dlg.get_value() == 132 and heard[-1] == 132
        assert dlg.get_result().startswith("Tap Tempo — Premier tempo : 132 BPM")
        other = _key("h", ctrl=True)                              # Ctrl+H : pas une frappe
        dlg._on_char_hook(other)
        assert other.GetSkipped()
        digit = _key("7")
        dlg._on_char_hook(digit)
        assert digit.GetSkipped()                                 # le champ le prend
        assert dlg._click.IsShown() and not dlg._click.GetValue()
        dlg._click.SetValue(True)
        dlg._click.ProcessEvent(wx.CommandEvent(wx.wxEVT_CHECKBOX, dlg._click.GetId()))
        assert clicks == [True]
        dlg.step(1000)
        assert dlg.get_value() == 600                             # borné
    finally:
        dlg.Destroy()


@pytest.mark.gui
def test_tempo_dialog_without_click_hides_the_box(parent):
    from ui.dialogs_menu import TempoSetDialog
    dlg = TempoSetDialog(parent, 90, lambda: None)
    try:
        assert not dlg._click.IsShown()
    finally:
        dlg.Destroy()


# --- Actions de la fenêtre principale ---------------------------------

def _answer(monkeypatch, cls, setup, rc=wx.ID_OK):
    """ShowModal du dialogue cls : setup(dlg) puis rc (dialogue réel, non
    affiché)."""
    def show(dlg):
        setup(dlg)
        return rc
    monkeypatch.setattr(cls, "ShowModal", show)


@pytest.mark.gui
@pytest.mark.parametrize("text, value, check, announce", [
    ("Régler le volume global…", 150, lambda w: w._player.volume, "Volume Global: 150"),
    ("Régler le pan global…", -30, lambda w: w._player.pan, "Pan Global: -30"),
    ("Régler le volume de la piste…", 70, lambda w: w._router.get_track_volume(0),
     "Piste 1: Volume 70"),
    ("Régler le pan de la piste…", 40, lambda w: w._router.get_track_pan(0), "Piste 1: Pan 40"),
])
def test_set_value_items(win, monkeypatch, text, value, check, announce):
    from ui.dialogs_menu import ValueDialog
    before, count = check(win), len(_titles(win))
    _answer(monkeypatch, ValueDialog, lambda d: d._spin.SetValue(before), wx.ID_CANCEL)
    assert _run(win, text) is None and check(win) == before         # Annuler
    _answer(monkeypatch, ValueDialog, lambda d: d._spin.SetValue(value))
    assert _run(win, text).startswith(announce)
    assert check(win) == value and len(_titles(win)) == count + 1
    _run(win, text)                                                  # inchangé : pas d'Undo
    assert len(_titles(win)) == count + 1
    win._undo_action()
    assert check(win) == before


@pytest.mark.gui
def test_value_dialog_opens_on_the_current_value(win, monkeypatch):
    from ui.dialogs_menu import ValueDialog
    seen = []
    win._router.set_track_pan(0, -20)
    _answer(monkeypatch, ValueDialog, lambda d: seen.append(
        (d.get_value(), d._spin.GetMin(), d._spin.GetMax())), wx.ID_CANCEL)
    _run(win, "Régler le pan de la piste…")
    _run(win, "Régler le volume global…")
    assert seen[0] == (-20, -100, 100)
    assert seen[1] == (win._player.volume, 0, win.MASTER_VOLUME_MAX)
    win._router.set_track_pan(0, 0)


@pytest.mark.gui
def test_choose_pattern(win, monkeypatch):
    from ui.dialogs_menu import PatternChoiceDialog
    seen = []

    def pick(d):
        seen.append((d._list.GetCount(), d.get_index(), d._list.GetString(0)))
        d._list.SetSelection(4)
    _answer(monkeypatch, PatternChoiceDialog, pick)
    assert _run(win, "Choisir un pattern…").startswith("Pattern 05")
    assert seen == [(99, 0, win._pattern_label(0))]
    assert win._cur_pattern_idx == 4 and win._pattern_listbox.GetSelection() == 4
    _answer(monkeypatch, PatternChoiceDialog, lambda d: None)        # le courant
    assert _run(win, "Choisir un pattern…") == "Pattern 05: déjà le pattern courant"
    _answer(monkeypatch, PatternChoiceDialog, lambda d: d._list.SetSelection(0), wx.ID_CANCEL)
    _run(win, "Choisir un pattern…")
    assert win._cur_pattern_idx == 4


@pytest.mark.gui
def test_resize_pattern(win, monkeypatch):
    from ui.dialogs_menu import ResizePatternDialog
    live = win._player._pattern
    bars, steps = live._num_bars, live._num_steps
    seen = []

    def resize(d):
        seen.append((d.get_num_bars(), d.get_resolution()))
        d._bars.SetValue(3)
        d._res.SetSelection(d._resolutions.index(32))
    _answer(monkeypatch, ResizePatternDialog, resize)
    assert _run(win, "Redimensionner le pattern…") == "Pattern 01: 3 mesures, résolution 1/32"
    live = win._player._pattern
    assert (live._num_bars, live._num_steps) == (3, 32 * live._num_beats // live._denumerator)
    assert win._pattern_list[0]._num_bars == 3                       # pattern gardé aussi
    assert _titles(win)[0] == "Redimensionner pattern 01"
    assert seen[0] == (bars, round(steps * live._denumerator / live._num_beats))
    count = len(_titles(win))
    _answer(monkeypatch, ResizePatternDialog, lambda d: None)        # inchangé
    _run(win, "Redimensionner le pattern…")
    assert len(_titles(win)) == count
    win._undo_action()
    live = win._player._pattern
    assert (live._num_bars, live._num_steps) == (bars, steps)


@pytest.mark.gui
def test_resize_refuses_a_resolution_impossible_in_the_signature(win, monkeypatch):
    from pattern import Pattern
    from ui.dialogs_menu import ResizePatternDialog
    monkeypatch.setattr(Pattern, "steps_for", staticmethod(lambda *a: None))
    count = len(_titles(win))
    _answer(monkeypatch, ResizePatternDialog, lambda d: None)
    assert _run(win, "Redimensionner le pattern…").startswith("Résolution 1/")
    assert len(_titles(win)) == count


@pytest.mark.gui
def test_set_tempo_live_cancel_and_ok(win, monkeypatch):
    from ui.dialogs_menu import TempoSetDialog
    p = win._player
    start = round(p.tempo_at(0))
    heard = []

    def listen(d):
        d.step(10)
        heard.append(round(p.tempo_at(0)))                 # entendu, dialogue ouvert
    _answer(monkeypatch, TempoSetDialog, listen, wx.ID_CANCEL)
    count = len(_titles(win))
    _run(win, "Régler le tempo…")
    assert heard == [start + 10] and round(p.tempo_at(0)) == start   # Annuler rétablit
    assert len(_titles(win)) == count
    _answer(monkeypatch, TempoSetDialog, lambda d: None)              # OK sans changement
    _run(win, "Régler le tempo…")
    assert len(_titles(win)) == count                                 # pas d'Undo
    _answer(monkeypatch, TempoSetDialog, lambda d: d.step(5))
    assert _run(win, "Régler le tempo…") == f"Premier tempo : {start + 5} BPM"
    assert round(p.tempo_at(0)) == start + 5
    assert _titles(win)[0] == f"Tempo : {start + 5} BPM (tous les tempos en proportion)"
    assert len(_titles(win)) == count + 1
    win._undo_action()
    assert round(win._player.tempo_at(0)) == start


@pytest.mark.gui
def test_set_tempo_scales_every_tempo(win, monkeypatch):
    from ui.dialogs_menu import TempoSetDialog
    p = win._player
    start = p.tempo_at(0)
    p._pattern._tempo_changes = [(p._pattern._num_steps, start * 2)]
    _answer(monkeypatch, TempoSetDialog, lambda d: d._spin.SetValue(round(start) * 2) or d._show())
    _run(win, "Régler le tempo…")
    assert round(p.tempo_at(0)) == round(start) * 2
    assert round(p._pattern._tempo_changes[0][1]) == round(start * 2 * round(start) * 2 / start)
    win._undo_action()
    win._player._pattern._tempo_changes = []


@pytest.mark.gui
def test_set_tempo_click_box(win, monkeypatch):
    from ui.dialogs_menu import TempoSetDialog
    p = win._player
    if p.clicking:
        p.stop_click()

    def tick(d):
        d._click.SetValue(True)
        d._click.ProcessEvent(wx.CommandEvent(wx.wxEVT_CHECKBOX, d._click.GetId()))
    _answer(monkeypatch, TempoSetDialog, tick, wx.ID_CANCEL)
    _run(win, "Régler le tempo…")
    try:
        assert p.clicking                               # gardé après le dialogue
        assert "Click: On" in win.status
    finally:
        p.stop_click()


# ----------------------------------------------------------------------
# Éléments de l'éditeur MIDI (Phase 9 étape 3g1, tests de 3f1) et éléments
# indisponibles (3f3)
# ----------------------------------------------------------------------

EDITOR_ITEMS = [
    ("Insérer une note", "Ctrl+I", ("_quick_insert", True)),
    ("Insérer une note sans avancer", "Alt+I", ("_quick_insert", False)),
    ("Insérer une note avec dialogue…", "Ctrl+Shift+I", ("_insert_dialog",)),
    ("Insérer une note entre deux", "A", ("_insert_between",)),
    ("Dupliquer l'événement", "D", ("_duplicate_event", True)),
    ("Dupliquer sans avancer", "Shift+D", ("_duplicate_event", False)),
    ("Éditer l'événement…", "Entrée", ("_edit_note_dialog",)),
    ("Rafraîchir", "R", ("_refresh",)),
    ("Raccourcir", "Num 1", ("_numpad_shorten",)),
    ("Rallonger", "Num 3", ("_numpad_lengthen",)),
    ("Reculer", "Num 4", ("_numpad_move", -1)),
    ("Avancer", "Num 6", ("_numpad_move", 1)),
    ("Vélocité −", "Num 7", ("_numpad_velocity", -1)),
    ("Vélocité +", "Num 9", ("_numpad_velocity", 1)),
    ("Demi-ton −", "Num 2", ("_numpad_pitch", -1)),
    ("Demi-ton +", "Num 8", ("_numpad_pitch", 1)),
    ("Octave −", "Ctrl+Num 2", ("_numpad_pitch", -12)),
    ("Octave +", "Ctrl+Num 8", ("_numpad_pitch", 12)),
    ("Limiteur gauche au début", "Shift+I", ("_set_lim_left", 0)),
]


def test_editor_items_description():
    for text, accel, _call in EDITOR_ITEMS:
        it = _find(text)
        assert it.accel == accel, text
        expected = {menu_bar.MAIN, menu_bar.MIDI} if text.startswith("Limiteur") \
            else {menu_bar.MIDI}
        assert set(it.windows) == expected, text
    note = _sub(_sub(_menu("Traitement"), "Midi").items, "Note")
    assert [it.text() for it in note.items][:2] == ["Raccourcir", "Rallonger"]
    assert _find("Éditer l'événement…") in _menu("Edition")


@pytest.fixture
def editor(main_win, monkeypatch):
    """L'éditeur MIDI de la vraie fenêtre, ses commandes enregistrées."""
    main_win._open_midi_editor_window()
    ed = main_win._midi_editor_window
    calls = []
    for name in {c[0] for _t, _a, c in EDITOR_ITEMS}:
        monkeypatch.setattr(ed, name, lambda *a, n=name: calls.append((n,) + a))
    status = []
    monkeypatch.setattr(ed, "_set_status", status.append)
    ed.calls, ed.status = calls, status
    yield ed
    ed.Destroy()


@pytest.mark.gui
@pytest.mark.parametrize("text, accel, call", EDITOR_ITEMS)
def test_editor_items_replay_the_editor_keyboard(editor, text, accel, call):
    """Chaque élément rejoue sa touche par le vrai clavier de l'éditeur
    (Alt+I : insérer sans avancer, pas le menu Insertion — K3)."""
    menu_bar.run(editor, _find(text))
    assert editor.calls == [call]
    assert not any("sans effet" in m or "indisponible" in m for m in editor.status)


@pytest.mark.gui
def test_editor_items_unavailable_in_the_main_window(win):
    for text, _accel, _call in EDITOR_ITEMS:
        if text.startswith("Limiteur"):
            continue
        assert _run(win, text) == f"{text} : indisponible dans cette fenêtre"


@pytest.mark.gui
def test_main_items_unavailable_in_the_editor(editor):
    for text in ("Piste suivante", "Volume de la piste +5", "Choisir un pattern…",
                 "Assigner la boucle aux limiteurs"):
        editor.status.clear()
        menu_bar.run(editor, _find(text))
        assert editor.status == [f"{text} : indisponible dans cette fenêtre"]
    assert editor.calls == []


@pytest.mark.gui
def test_unavailable_labels_in_the_real_windows(main_win, editor):
    """Libellés réels : « (Indisponible) » dans la fenêtre où l'élément n'a
    pas d'objet, et là seulement ; tout élément reste actif."""
    def label(win, text):
        ids = [i for i, it in win._menu_items.items() if it.text() == text]
        mi = win.GetMenuBar().FindItemById(ids[0])
        assert mi.IsEnabled()
        return mi.GetItemLabelText()
    assert label(main_win, "Rafraîchir") == "Rafraîchir (Indisponible)"
    assert label(editor, "Rafraîchir") == "Rafraîchir"
    assert label(editor, "Piste suivante") == "Piste suivante (Indisponible)"
    assert label(main_win, "Piste suivante") == "Piste suivante"
