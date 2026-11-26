#python3
"""
    File: tests/test_grid_notes_128.py
    Notes de grille sur 128 notes et écoute de la grille (Phase 9 étape 5c1,
    tests de 5b1 et 5b3 ; docs/DESIGN.md § Phase 9 étapes 5a et 5b2) :
    - MidiEditor.convert_grid_to_patch (modèle) ;
    - éditeur MIDI d'une vraie fenêtre principale : dialogue à 128 notes
      (note jouée présélectionnée, préécoute), note gardée dans la grille si
      un pad joue la hauteur, sinon convertie (durée du pad, annonce), Num 2
      / 8 et Ctrl+Num 2 / 8, pistes de kit inchangées, Undo, grille de la
      fenêtre principale qui suit ;
    - écoute de la grille : instrument de la piste (TrackRouter.on_play,
      audition même muette), jeu direct inchangé.
    Date: Thu, 26/11/2026
    Author: Coolbrother
"""
import pytest
import wx

from midi.midi_editor import MidiEditor
from pattern import ETYPE_GRID, ETYPE_PATCH, Pattern
from ui import menu_bar


# ----------------------------------------------------------------------
# Modèle
# ----------------------------------------------------------------------

def _grid_ev(pat, track=0, pad=2, bar=0, step=0, vel=100):
    pat.set_cell(track, pad, bar, step, vel)
    return {"type": "note", "etype": ETYPE_GRID, "track": track, "pad": pad, "bar": bar,
            "step": step, "offset": bar * pat._num_steps + step, "vel": vel, "dur": 321,
            "dur_override": 0, "channel": 4}


def test_convert_grid_to_patch_keeps_position_velocity_channel_and_duration():
    pat = Pattern()
    ev = _grid_ev(pat)
    new = MidiEditor().convert_grid_to_patch(pat, ev, 75)
    assert new["etype"] == ETYPE_PATCH and new["pad"] == 75
    assert (new["bar"], new["step"], new["vel"], new["dur"], new["channel"]) == (0, 0, 100, 321, 4)
    assert not pat.get_cell(0, 2, 0, 0)                           # case retirée
    patch = [e for e in pat._tape[0] if e.etype == ETYPE_PATCH]
    assert len(patch) == 1 and patch[0].payload == {"note": 75, "vel": 100}
    assert patch[0].dur == 321 and patch[0].channel == 4


def test_convert_grid_to_patch_refuses_bad_values():
    pat = Pattern()
    me = MidiEditor()
    ev = _grid_ev(pat)
    assert me.convert_grid_to_patch(pat, ev, 128) is None
    assert me.convert_grid_to_patch(pat, dict(ev, etype=ETYPE_PATCH), 60) is None
    assert me.convert_grid_to_patch(pat, ev, 60, new_bar=pat._num_bars) is None
    assert pat.get_cell(0, 2, 0, 0)                               # rien n'a bougé


# ----------------------------------------------------------------------
# Vraie fenêtre principale et son éditeur MIDI
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


SYNTH, KIT = 0, 1                                                 # pistes 1 et 2 du projet neuf


@pytest.fixture
def editor(main_win, monkeypatch):
    from rack import InstrumentType
    w = main_win
    assert w._router._eff_slot(SYNTH)[1].type == InstrumentType.SYNTH
    assert w._router._eff_slot(KIT)[1].type == InstrumentType.KIT
    monkeypatch.setattr(w, "_show_status", lambda m: None)
    w._undo.clear()
    w._open_midi_editor_window()
    ed = w._midi_editor_window
    status, played = [], []
    monkeypatch.setattr(ed, "_set_status", status.append)
    monkeypatch.setattr(ed, "_play_event", lambda e: played.append((e["etype"], e["pad"])))
    ed.status, ed.played = status, played
    yield ed
    ed.Destroy()
    w._midi_editor_window = None


def _scale(w):
    return w._router.playback_kb_notes()


def _put(w, ed, track, pad, step=0):
    """Une note de grille posée, l'éditeur sur cette note (piste courante)."""
    w._go_to_track(track)
    _clean(w, track)                                              # piste vide d'abord
    w._player._pattern.set_cell(track, pad, 0, step, 100)
    ed._refresh()
    i = [k for k, e in enumerate(ed._events) if e["etype"] == ETYPE_GRID
         and e["pad"] == pad and e["bar"] == 0 and e["step"] == step][0]
    ed._navigate_to(i)
    ed._selected_indices = set()
    return ed._events[i]


def _clean(w, track):
    pat = w._player._pattern
    with pat._lock:
        pat._tape[track] = []
    w._refresh_grid()


def _notes(ed):
    return [(e["etype"], e["pad"]) for e in ed._events if e["type"] == "note"]


@pytest.mark.gui
def test_dialog_offers_128_notes_with_the_played_one(main_win, editor):
    ev = _put(main_win, editor, SYNTH, 2)
    try:
        choices, sel = editor._dialog_note_choices(ev, main_win._player._pattern)
        assert len(choices) == 128 and sel == _scale(main_win)[2]
    finally:
        _clean(main_win, SYNTH)


@pytest.mark.gui
def test_kit_track_keeps_its_16_pads(main_win, editor):
    ev = _put(main_win, editor, KIT, 3)
    try:
        choices, sel = editor._dialog_note_choices(ev, main_win._player._pattern)
        assert len(choices) == main_win._player._pattern._num_pads and sel == 3
        editor._numpad_pitch(1)                                    # pad suivant
        assert _notes(editor) == [(ETYPE_GRID, 4)]
    finally:
        _clean(main_win, KIT)


@pytest.mark.gui
def test_dialog_preview_plays_the_chosen_note(main_win, editor):
    from ui.midi_editor_dialogs import _MidiEventEditDialog
    ev = _put(main_win, editor, SYNTH, 2)
    try:
        dlg = _MidiEventEditDialog(editor, ev, main_win._player._pattern)
        dlg._note_lb.SetSelection(90)
        dlg._on_note_select(None)
        dlg.Destroy()
        assert editor.played == [(ETYPE_PATCH, 90)]
    finally:
        _clean(main_win, SYNTH)


def _answer(monkeypatch, note):
    from ui.midi_editor_dialogs import _MidiEventEditDialog

    def show(dlg):
        dlg._note_lb.SetSelection(note)
        return wx.ID_OK
    monkeypatch.setattr(_MidiEventEditDialog, "ShowModal", show)


@pytest.mark.gui
def test_dialog_note_of_the_grid_stays_on_the_grid(main_win, editor, monkeypatch):
    _put(main_win, editor, SYNTH, 2)
    try:
        _answer(monkeypatch, _scale(main_win)[7])
        editor._edit_note_dialog()
        assert _notes(editor) == [(ETYPE_GRID, 7)]
        assert "hors grille" not in editor.status[-1]
    finally:
        _clean(main_win, SYNTH)


@pytest.mark.gui
def test_dialog_note_outside_the_grid_is_converted(main_win, editor, monkeypatch):
    _put(main_win, editor, SYNTH, 2)
    outside = next(n for n in range(30, 128) if n not in _scale(main_win))
    try:
        assert main_win._cells[2][0].GetValue()
        _answer(monkeypatch, outside)
        editor._edit_note_dialog()
        assert _notes(editor) == [(ETYPE_PATCH, outside)]
        assert editor.status[-1].endswith("hors grille : note enregistrée")
        assert not main_win._cells[2][0].GetValue()                # la grille suit
        dur = main_win._player.voice_manager.get_duration_ms(2)
        assert [e["dur"] for e in editor._events if e["type"] == "note"] == [dur]
        assert [e.title for e in main_win._undo.history_list()] == ["Éditer note Tr1 B1:S1"]
        main_win._undo_action()
        editor._refresh()
        assert _notes(editor) == [(ETYPE_GRID, 2)] and main_win._cells[2][0].GetValue()
    finally:
        _clean(main_win, SYNTH)


@pytest.mark.gui
def test_numpad_pitch_converts_beyond_the_grid_notes(main_win, editor):
    last = main_win._player._pattern._num_pads - 1
    _put(main_win, editor, SYNTH, last)
    top = _scale(main_win)[last]
    try:
        editor._numpad_pitch(1)
        assert _notes(editor) == [(ETYPE_PATCH, top + 1)]
        assert editor.status[-1].endswith("hors grille : note enregistrée")
        editor._numpad_pitch(1)                                    # continue de monter
        assert _notes(editor) == [(ETYPE_PATCH, top + 2)]
        assert "hors grille" not in editor.status[-1]
    finally:
        _clean(main_win, SYNTH)


@pytest.mark.gui
def test_numpad_pitch_inside_the_grid_notes_stays_on_the_grid(main_win, editor):
    _put(main_win, editor, SYNTH, 2)
    want = _scale(main_win)[2] + 1
    try:
        editor._numpad_pitch(1)
        pad = _scale(main_win).index(want) if want in _scale(main_win) else None
        expected = (ETYPE_GRID, pad) if pad is not None else (ETYPE_PATCH, want)
        assert _notes(editor) == [expected]
    finally:
        _clean(main_win, SYNTH)


@pytest.mark.gui
def test_ctrl_numpad_moves_an_octave(main_win, editor):
    _put(main_win, editor, SYNTH, 0)
    low = _scale(main_win)[0]
    try:
        editor._numpad_pitch(-12)
        assert _notes(editor) == [(ETYPE_PATCH, low - 12)]
    finally:
        _clean(main_win, SYNTH)


@pytest.mark.gui
def test_numpad_pitch_stops_at_the_midi_bounds(main_win, editor, monkeypatch):
    ev = _put(main_win, editor, SYNTH, 0)
    try:
        monkeypatch.setattr(editor, "_grid_note_of", lambda e: 127)
        assert editor._shift_pitch(main_win._player._pattern, ev, 1) is None
        monkeypatch.setattr(editor, "_grid_note_of", lambda e: 120)
        new = editor._shift_pitch(main_win._player._pattern, ev, 12)   # borné à 127
        assert (new["etype"], new["pad"]) == (ETYPE_PATCH, 127)
    finally:
        _clean(main_win, SYNTH)


# ----------------------------------------------------------------------
# Écoute de la grille (5b3)
# ----------------------------------------------------------------------

@pytest.mark.gui
def test_grid_row_is_played_by_the_track_instrument(main_win, monkeypatch):
    w = main_win
    calls = []
    monkeypatch.setattr(w._router, "on_play", lambda *a, **k: calls.append((a, k)))
    w._go_to_track(SYNTH)
    vm = w._player.voice_manager
    w._play_grid_row(4)
    (track, pad, vol, pan, dur), kw = calls[0]
    assert (track, pad, dur, kw) == (SYNTH, 4, vm.get_duration_ms(4), {"audition": True})
    assert vol == min(1.0, vm.get_volume_factor(4))
    assert pan == max(-100, min(100, w._player.pan + vm.get_pan(4)))


@pytest.mark.gui
def test_moving_and_enter_in_the_grid_use_the_track_instrument(main_win, monkeypatch):
    w = main_win
    rows, direct = [], []
    monkeypatch.setattr(w, "_play_grid_row", rows.append)
    monkeypatch.setattr(w, "_play", direct.append)
    monkeypatch.setattr(w, "_autoplay", True, raising=False)
    w._cur_row, w._cur_col = 5, 0
    w._move(1, 0)
    assert rows == [6] and direct == []
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: None))
    w._key_manager.handle(menu_bar.key_event("Entrée"))           # coche la case
    w._key_manager.handle(menu_bar.key_event("Entrée"))           # la décoche
    evt = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    evt.SetKeyCode(wx.WXK_NUMPAD_ENTER)
    w._key_manager.handle(evt)
    assert rows == [6, w._cur_row, w._cur_row, w._cur_row] and direct == []


@pytest.mark.gui
def test_a_muted_track_sounds_at_the_grid_but_not_in_playback(main_win, monkeypatch):
    r = main_win._router
    heard = []
    monkeypatch.setattr(r, "ext_grid", lambda *a: heard.append(a) or True)
    monkeypatch.setattr(r, "_track_is_audible", lambda t: False)
    r.on_play(SYNTH, 3, 1.0, 0, 200)                               # lecture : muette
    assert heard == []
    r.on_play(SYNTH, 3, 1.0, 0, 200, audition=True)                # écoute de la grille
    assert len(heard) == 1
