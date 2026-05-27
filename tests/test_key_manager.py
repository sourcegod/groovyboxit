#python3
"""
    File: tests/test_key_manager.py
    Tests unitaires de KeyManager : dispatch vers les groupes de touches.
    Date: Thu, 21/05/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from ui.key_manager import KeyManager


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeWidget:
    """Stub générique pour les widgets wx (focalisable + méthodes simples)."""
    def SetValue(self, v):     pass
    def GetValue(self):        return 0
    def SetSelection(self, v): pass
    def GetSelection(self):    return 0
    def GetCount(self):        return 0


class FakeCell:
    def __init__(self, value=False):
        self.value = value
    def GetValue(self):       return self.value
    def SetValue(self, v):    self.value = v


class FakeVoice:
    def __init__(self, volume=100, pan=0):
        self.volume = volume
        self.pan    = pan


class FakeVoiceManager:
    def __init__(self):
        self._v    = [FakeVoice() for _ in range(16)]
        self.calls = []

    def get_voice(self, i):   return self._v[i]
    def get_pan(self, i):     return self._v[i].pan

    def set_volume(self, i, v):
        self.calls.append(('set_volume', i, v))
        self._v[i].volume = v

    def set_pan(self, i, v):
        self.calls.append(('set_pan', i, v))
        self._v[i].pan = v

    def toggle_mute(self, i):
        self.calls.append(('toggle_mute', i));  return True

    def toggle_solo(self, i):
        self.calls.append(('toggle_solo', i));  return True

    def set_mute_all(self, v): self.calls.append(('set_mute_all', v))
    def set_solo_all(self, v): self.calls.append(('set_solo_all', v))


class FakePattern:
    def __init__(self):
        self._num_bars  = 2
        self._num_steps = 16
        self.calls      = []

    def reset_pattern(self):      self.calls.append('reset_pattern')
    def build_pattern_01(self):   self.calls.append('build_pattern_01')
    def gen_pattern(self, t):     self.calls.append(('gen_pattern', t))


class FakePlayer:
    def __init__(self):
        self._pattern            = FakePattern()
        self._cur_track          = 0
        self._count_in           = 0
        self._note_repeat_active = False
        self.voice_manager       = FakeVoiceManager()
        self.playing             = False
        self.recording           = False
        self.replace_recording   = False
        self.erasing             = False
        self.clicking            = False
        self.last_played_pad     = None
        self.count_in_bars       = 0
        self.bpm                 = 120
        self.volume              = 75
        self.calls               = []

    def play_pattern(self):
        self.calls.append('play_pattern');    self.playing = True
    def stop_pattern(self):
        self.calls.append('stop_pattern');    self.playing = False
    def stop_all(self):
        self.calls.append('stop_all');        self.playing = False
    def record_pattern(self):
        self.calls.append('record_pattern');  self.recording = True
    def stop_record(self):
        self.calls.append('stop_record');     self.recording = False
    def start_replace_recording(self):
        self.calls.append('start_replace_recording'); self.replace_recording = True
    def play_click(self):
        self.calls.append('play_click');      self.clicking = True
    def stop_click(self):
        self.calls.append('stop_click');      self.clicking = False
    def toggle_erase(self):
        self.calls.append('toggle_erase');    self.erasing = not self.erasing; return self.erasing
    def double_pattern(self):
        self.calls.append('double_pattern');  return True
    def halve_pattern(self):
        self.calls.append('halve_pattern');   return True
    def record_pattern_with_count_in(self):
        self.calls.append('record_pattern_with_count_in')
    def stop_note_repeat(self):
        self.calls.append('stop_note_repeat')
    def set_bpm(self, v):
        self.calls.append(('set_bpm', v));    self.bpm = v
    def set_volume(self, v):
        self.calls.append(('set_volume', v)); self.volume = v
    def _compute_offsets(self):
        self.calls.append('_compute_offsets')


class FakeRouter:
    def __init__(self):
        self._track_volumes = [100] * 8
        self._track_pans    = [0]   * 8
        self.calls          = []

    def get_track_volume(self, i): return self._track_volumes[i]
    def get_track_pan(self, i):    return self._track_pans[i]

    def set_track_volume(self, i, v):
        self.calls.append(('set_track_volume', i, v))
    def set_track_pan(self, i, v):
        self.calls.append(('set_track_pan', i, v))
    def toggle_track_mute(self, i):
        self.calls.append(('toggle_track_mute', i)); return True
    def toggle_track_solo(self, i):
        self.calls.append(('toggle_track_solo', i)); return True
    def unmute_all_tracks(self): self.calls.append('unmute_all_tracks')
    def unsolo_all_tracks(self): self.calls.append('unsolo_all_tracks')
    def slot_name(self, i):      return f"Slot_{i + 1}"
    def update_kb_notes(self, scale, root): self.calls.append(('update_kb_notes', scale, root))
    def update_input_kb(self, root):        self.calls.append(('update_input_kb', root))


class _FakeSlot:
    type = None   # ni KIT ni SYNTH → branche else dans numpad+/-

class FakeRack:
    def get_slot(self, idx): return _FakeSlot()

class FakeSnd:
    note_map = {}   # vide → branche KIT ignorée dans numpad+/-

class FakeMidiHandler:
    def __init__(self, win):
        self._win = win
    def toggle(self):          self._win.calls.append('_midi_toggle')
    def refresh_ports(self):   self._win.calls.append('_refresh_midi_ports')
    def toggle_erase(self):
        self._win.calls.append('_toggle_erase')
        return self._win._player.toggle_erase()


class FakeWindow:
    ROWS       = 16
    COLS       = 16
    NR_BINARY  = [0, 1, 3, 5, 7, 9, 11, 13]
    NR_TERNARY = [2, 4, 6, 8, 10, 12]

    def __init__(self):
        # Widgets (FakeWidget est unique par instance → FindFocus()==None ne matche pas)
        self._quant_list      = FakeWidget()
        self._pattern_listbox = FakeWidget()
        self._bpm_ctrl        = FakeWidget()
        self._volume_ctrl     = FakeWidget()
        self._pan_ctrl        = FakeWidget()
        self._mode_choice     = FakeWidget()
        self._scale_choice    = FakeWidget()
        self._slot_choice     = FakeWidget()
        self._track_list      = FakeWidget()
        self._pad_list        = FakeWidget()
        self._vel_list        = FakeWidget()
        self._midi_port_list  = FakeWidget()
        self._vol_ctrls       = [FakeWidget() for _ in range(16)]
        self._pan_ctrls       = [FakeWidget() for _ in range(16)]
        self._cells           = [[FakeCell() for _ in range(self.COLS)]
                                 for _ in range(self.ROWS)]
        # État clavier
        self._cur_row       = 0
        self._cur_col       = 0
        self._shift_pad     = 0
        self._input_mode    = "pad"
        self._note_repeat   = False
        self._nr_active_key = None
        self._nr_prev_key   = None
        self._nr_midi_note  = None
        self._nr_rate_idx   = 7
        self._nr_ternary    = False
        self._kb_root_midi  = 48
        self._kb_play_root  = 48
        self._kb_scale      = "major"
        self._cur_slot      = 0
        # Données
        self._player       = FakePlayer()
        self._router       = FakeRouter()
        self._rack         = FakeRack()
        self._snd          = FakeSnd()
        self._midi_handler = FakeMidiHandler(self)
        # Journal des appels sur FakeWindow elle-même
        self.calls = []

    # Méthodes enregistrées
    def _save_preset(self):               self.calls.append('_save_preset')
    def _save_preset_as(self):            self.calls.append('_save_preset_as')
    def _save_pattern(self):              self.calls.append('_save_pattern')
    def _save_pattern_as(self):           self.calls.append('_save_pattern_as')
    def _open_explorer(self):             self.calls.append('_open_explorer')
    def _show_keyboard_help(self):        self.calls.append('_show_keyboard_help')
    def _show_status(self, msg):          self.calls.append(('_show_status', msg))
    def _refresh_grid(self):              self.calls.append('_refresh_grid')
    def _refresh_voice_display(self, i):  self.calls.append(('_refresh_voice_display', i))
    def _refresh_all_voice_display(self): self.calls.append('_refresh_all_voice_display')
    def _refresh_track_list(self):        self.calls.append('_refresh_track_list')
    def _apply_quant(self):               self.calls.append('_apply_quant')
    def _gen_row_dialog(self):            self.calls.append('_gen_row_dialog')
    def _quantize_pattern(self):          self.calls.append('_quantize_pattern')
    def _quantize_pattern_dialog(self):   self.calls.append('_quantize_pattern_dialog')
    def _track_properties_dialog(self):   self.calls.append('_track_properties_dialog')
    def _assign_track_slot(self):         self.calls.append('_assign_track_slot')
    def _move(self, dr, dc):              self.calls.append(('_move', dr, dc))
    def _on_tab_order(self, shift):       self.calls.append(('_on_tab_order', shift))
    def _on_track_select(self, ev):       self.calls.append('_on_track_select')
    def _play(self, idx):                 self.calls.append(('_play', idx))
    def _play_kit_pitched(self, idx):     self.calls.append(('_play_kit_pitched', idx))
    def _nr_arm_release(self):            self.calls.append('_nr_arm_release')
    def _nr_cancel_release(self):         self.calls.append('_nr_cancel_release')
    def _update_bpm_display(self):        self.calls.append('_update_bpm_display')

    def _set_input_mode(self, mode):
        self.calls.append(('_set_input_mode', mode))
        self._input_mode = mode

    def _set_cell(self, r, c, val):
        self.calls.append(('_set_cell', r, c, val))
        self._cells[r][c].value = val


class FakeEvent:
    def __init__(self, key=0, ukey=0, ctrl=False, shift=False, alt=False):
        self._key   = key
        self._ukey  = ukey   # 0 simule GTK/EVT_CHAR_HOOK : GetUnicodeKey() non fiable
        self._ctrl  = ctrl
        self._shift = shift
        self._alt   = alt
        self.skipped = False

    def GetKeyCode(self):    return self._key
    def GetUnicodeKey(self): return self._ukey
    def ControlDown(self):   return self._ctrl
    def ShiftDown(self):     return self._shift
    def AltDown(self):       return self._alt
    def Skip(self):          self.skipped = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_km():
    app = wx.App(False)
    win = FakeWindow()
    km  = KeyManager(win)
    return app, win, km


def teardown(app):
    app.Destroy()


# ---------------------------------------------------------------------------
# F1 / touche inconnue
# ---------------------------------------------------------------------------

def test_f1_shows_keyboard_help():
    app, win, km = make_km()
    km.handle(FakeEvent(key=wx.WXK_F1))
    assert '_show_keyboard_help' in win.calls
    teardown(app)
    print("  F1 → _show_keyboard_help() : OK")

def test_unknown_key_skips_event():
    app, win, km = make_km()
    ev = FakeEvent(key=0)
    km.handle(ev)
    assert ev.skipped
    teardown(app)
    print("  Touche inconnue → event.Skip() : OK")


# ---------------------------------------------------------------------------
# Groupe Alt
# ---------------------------------------------------------------------------

def test_alt_w_saves_preset():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('W'), alt=True))
    assert '_save_preset' in win.calls
    teardown(app)
    print("  Alt+W → _save_preset() : OK")

def test_alt_shift_w_saves_preset_as():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('W'), alt=True, shift=True))
    assert '_save_preset_as' in win.calls
    teardown(app)
    print("  Alt+Shift+W → _save_preset_as() : OK")

def test_alt_x_opens_explorer():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('X'), alt=True))
    assert '_open_explorer' in win.calls
    teardown(app)
    print("  Alt+X → _open_explorer() : OK")

def test_alt_up_increments_pad_volume():
    app, win, km = make_km()
    win._cur_row = 3
    km.handle(FakeEvent(key=wx.WXK_UP, alt=True))
    assert ('set_volume', 3, 105) in win._player.voice_manager.calls
    teardown(app)
    print("  Alt+↑ → voice_manager.set_volume(row, vol+5) : OK")

def test_alt_down_decrements_pad_volume():
    app, win, km = make_km()
    win._cur_row = 0
    km.handle(FakeEvent(key=wx.WXK_DOWN, alt=True))
    assert ('set_volume', 0, 95) in win._player.voice_manager.calls
    teardown(app)
    print("  Alt+↓ → voice_manager.set_volume(row, vol-5) : OK")

def test_alt_left_decrements_pad_pan():
    app, win, km = make_km()
    win._cur_row = 2
    km.handle(FakeEvent(key=wx.WXK_LEFT, alt=True))
    assert ('set_pan', 2, -10) in win._player.voice_manager.calls
    teardown(app)
    print("  Alt+← → voice_manager.set_pan(row, pan-10) : OK")

def test_alt_right_increments_pad_pan():
    app, win, km = make_km()
    win._cur_row = 0
    km.handle(FakeEvent(key=wx.WXK_RIGHT, alt=True))
    assert ('set_pan', 0, 10) in win._player.voice_manager.calls
    teardown(app)
    print("  Alt+→ → voice_manager.set_pan(row, pan+10) : OK")

def test_alt_0_resets_pad_pan():
    app, win, km = make_km()
    win._cur_row = 1
    km.handle(FakeEvent(key=ord('0'), alt=True))
    assert ('set_pan', 1, 0) in win._player.voice_manager.calls
    teardown(app)
    print("  Alt+0 → voice_manager.set_pan(row, 0) : OK")


# ---------------------------------------------------------------------------
# Groupe Ctrl
# ---------------------------------------------------------------------------

def test_ctrl_w_saves_pattern():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('W'), ctrl=True))
    assert '_save_pattern' in win.calls
    teardown(app)
    print("  Ctrl+W → _save_pattern() : OK")

def test_ctrl_shift_w_saves_pattern_as():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('W'), ctrl=True, shift=True))
    assert '_save_pattern_as' in win.calls
    teardown(app)
    print("  Ctrl+Shift+W → _save_pattern_as() : OK")

def test_ctrl_d_resets_pattern():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('D'), ctrl=True))
    assert 'reset_pattern' in win._player._pattern.calls
    assert '_refresh_grid' in win.calls
    teardown(app)
    print("  Ctrl+D → reset_pattern() + _refresh_grid() : OK")

def test_ctrl_p_loads_demo_pattern():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('P'), ctrl=True))
    assert 'build_pattern_01' in win._player._pattern.calls
    assert '_refresh_grid' in win.calls
    teardown(app)
    print("  Ctrl+P → build_pattern_01() + _refresh_grid() : OK")

def test_ctrl_f_doubles_pattern():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('F'), ctrl=True))
    assert 'double_pattern' in win._player.calls
    teardown(app)
    print("  Ctrl+F → double_pattern() : OK")

def test_ctrl_e_applies_quant():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('E'), ctrl=True))
    assert '_apply_quant' in win.calls
    teardown(app)
    print("  Ctrl+E → _apply_quant() : OK")

def test_ctrl_shift_e_opens_gen_row_dialog():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('E'), ctrl=True, shift=True))
    assert '_gen_row_dialog' in win.calls
    teardown(app)
    print("  Ctrl+Shift+E → _gen_row_dialog() : OK")

def test_ctrl_1_sets_pad_mode():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('1'), ctrl=True))
    assert ('_set_input_mode', 'pad') in win.calls
    teardown(app)
    print("  Ctrl+1 → _set_input_mode('pad') : OK")

def test_ctrl_2_sets_keyboard_mode():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('2'), ctrl=True))
    assert ('_set_input_mode', 'keyboard') in win.calls
    teardown(app)
    print("  Ctrl+2 → _set_input_mode('keyboard') : OK")

def test_ctrl_shift_q_opens_quantize_dialog():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('Q'), ctrl=True, shift=True))
    assert '_quantize_pattern_dialog' in win.calls
    teardown(app)
    print("  Ctrl+Shift+Q → _quantize_pattern_dialog() : OK")

def test_ctrl_t_assigns_track_slot():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('T'), ctrl=True))
    assert '_assign_track_slot' in win.calls
    teardown(app)
    print("  Ctrl+T → _assign_track_slot() : OK")

def test_ctrl_shift_t_opens_track_properties():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('T'), ctrl=True, shift=True))
    assert '_track_properties_dialog' in win.calls
    teardown(app)
    print("  Ctrl+Shift+T → _track_properties_dialog() : OK")

def test_ctrl_r_starts_count_in():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('R'), ctrl=True))
    assert 'record_pattern_with_count_in' in win._player.calls
    teardown(app)
    print("  Ctrl+R → record_pattern_with_count_in() : OK")


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def test_tab_calls_on_tab_order():
    app, win, km = make_km()
    km.handle(FakeEvent(key=wx.WXK_TAB))
    assert ('_on_tab_order', False) in win.calls
    teardown(app)
    print("  Tab → _on_tab_order(False) : OK")

def test_shift_tab_calls_on_tab_order_shift():
    app, win, km = make_km()
    km.handle(FakeEvent(key=wx.WXK_TAB, shift=True))
    assert ('_on_tab_order', True) in win.calls
    teardown(app)
    print("  Shift+Tab → _on_tab_order(True) : OK")

def test_up_arrow_moves_grid():
    app, win, km = make_km()
    km.handle(FakeEvent(key=wx.WXK_UP))
    assert ('_move', -1, 0) in win.calls
    teardown(app)
    print("  ↑ → _move(-1, 0) : OK")

def test_down_arrow_moves_grid():
    app, win, km = make_km()
    km.handle(FakeEvent(key=wx.WXK_DOWN))
    assert ('_move', 1, 0) in win.calls
    teardown(app)
    print("  ↓ → _move(1, 0) : OK")

def test_left_arrow_moves_grid():
    app, win, km = make_km()
    km.handle(FakeEvent(key=wx.WXK_LEFT))
    assert ('_move', 0, -1) in win.calls
    teardown(app)
    print("  ← → _move(0, -1) : OK")

def test_right_arrow_moves_grid():
    app, win, km = make_km()
    km.handle(FakeEvent(key=wx.WXK_RIGHT))
    assert ('_move', 0, 1) in win.calls
    teardown(app)
    print("  → → _move(0, 1) : OK")

def test_enter_checks_false_cell():
    app, win, km = make_km()
    win._cur_row = 0;  win._cur_col = 0
    win._cells[0][0].value = False
    km.handle(FakeEvent(key=wx.WXK_RETURN))
    assert ('_set_cell', 0, 0, True) in win.calls
    teardown(app)
    print("  Entrée sur cellule False → _set_cell(0,0,True) : OK")

def test_shift_enter_unchecks_cell():
    app, win, km = make_km()
    win._cur_row = 1;  win._cur_col = 2
    km.handle(FakeEvent(key=wx.WXK_RETURN, shift=True))
    assert ('_set_cell', 1, 2, False) in win.calls
    teardown(app)
    print("  Shift+Entrée → _set_cell(row, col, False) : OK")


# ---------------------------------------------------------------------------
# Pavé numérique
# ---------------------------------------------------------------------------

def test_numpad0_stops_all():
    app, win, km = make_km()
    km.handle(FakeEvent(key=wx.WXK_NUMPAD0))
    assert 'stop_all' in win._player.calls
    teardown(app)
    print("  NumPad0 → stop_all() : OK")

def test_numpad_add_increments_shift_pad():
    app, win, km = make_km()
    win._shift_pad = 0
    km.handle(FakeEvent(key=wx.WXK_NUMPAD_ADD))
    assert win._shift_pad == 8
    teardown(app)
    print("  NumPad+ → _shift_pad 0→8 : OK")

def test_numpad_subtract_decrements_shift_pad():
    app, win, km = make_km()
    win._shift_pad = 8
    km.handle(FakeEvent(key=wx.WXK_NUMPAD_SUBTRACT))
    assert win._shift_pad == 0
    teardown(app)
    print("  NumPad- → _shift_pad 8→0 : OK")

def test_numpad_add_clamps_at_8():
    app, win, km = make_km()
    win._shift_pad = 8
    km.handle(FakeEvent(key=wx.WXK_NUMPAD_ADD))
    assert win._shift_pad == 8   # min(8, 8+8) = 8
    teardown(app)
    print("  NumPad+ bloqué à 8 (déjà au max) : OK")

def test_numpad_subtract_clamps_at_0():
    app, win, km = make_km()
    win._shift_pad = 0
    km.handle(FakeEvent(key=wx.WXK_NUMPAD_SUBTRACT))
    assert win._shift_pad == 0   # max(0, 0-8) = 0
    teardown(app)
    print("  NumPad- bloqué à 0 (déjà au min) : OK")


# ---------------------------------------------------------------------------
# Touches caractères
# ---------------------------------------------------------------------------

def test_space_plays_pattern():
    app, win, km = make_km()
    win._player.playing = False
    km.handle(FakeEvent(key=wx.WXK_SPACE))
    assert 'play_pattern' in win._player.calls
    teardown(app)
    print("  Space → play_pattern() (si stoppé) : OK")

def test_space_stops_playing_pattern():
    app, win, km = make_km()
    win._player.playing = True
    km.handle(FakeEvent(key=wx.WXK_SPACE))
    assert 'stop_pattern' in win._player.calls
    teardown(app)
    print("  Space → stop_pattern() (si en lecture) : OK")

def test_p_plays_pattern():
    app, win, km = make_km()
    win._player.playing = False
    km.handle(FakeEvent(key=ord('P')))
    assert 'play_pattern' in win._player.calls
    teardown(app)
    print("  P → play_pattern() : OK")

def test_v_stops_all():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('V')))
    assert 'stop_all' in win._player.calls
    teardown(app)
    print("  V → stop_all() : OK")

def test_r_starts_recording():
    app, win, km = make_km()
    win._player.recording = False
    km.handle(FakeEvent(key=ord('R')))
    assert 'record_pattern' in win._player.calls
    teardown(app)
    print("  R → record_pattern() (si non en rec) : OK")

def test_r_stops_recording():
    app, win, km = make_km()
    win._player.recording = True
    km.handle(FakeEvent(key=ord('R')))
    assert 'stop_record' in win._player.calls
    teardown(app)
    print("  R → stop_record() (si en rec) : OK")

def test_shift_r_starts_replace_recording():
    app, win, km = make_km()
    win._player.replace_recording = False
    km.handle(FakeEvent(key=ord('R'), shift=True))
    assert 'start_replace_recording' in win._player.calls
    teardown(app)
    print("  Shift+R → start_replace_recording() : OK")

def test_shift_r_stops_replace_recording():
    app, win, km = make_km()
    win._player.replace_recording = True
    km.handle(FakeEvent(key=ord('R'), shift=True))
    assert 'stop_record' in win._player.calls
    teardown(app)
    print("  Shift+R (actif) → stop_record() : OK")

def test_q_enables_note_repeat():
    app, win, km = make_km()
    win._note_repeat = False
    km.handle(FakeEvent(key=ord('Q')))
    assert win._note_repeat is True
    teardown(app)
    print("  Q → _note_repeat = True : OK")

def test_q_disables_note_repeat():
    app, win, km = make_km()
    win._note_repeat = True
    km.handle(FakeEvent(key=ord('Q')))
    assert win._note_repeat is False
    assert 'stop_note_repeat' in win._player.calls
    teardown(app)
    print("  Q (NR actif) → _note_repeat = False + stop_note_repeat() : OK")

def test_c_plays_click():
    app, win, km = make_km()
    win._player.clicking = False
    km.handle(FakeEvent(key=ord('C')))
    assert 'play_click' in win._player.calls
    teardown(app)
    print("  C → play_click() : OK")

def test_c_stops_click():
    app, win, km = make_km()
    win._player.clicking = True
    km.handle(FakeEvent(key=ord('C')))
    assert 'stop_click' in win._player.calls
    teardown(app)
    print("  C (clicking) → stop_click() : OK")

def test_e_toggles_erase():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('E')))
    assert 'toggle_erase' in win._player.calls
    teardown(app)
    print("  E → toggle_erase() : OK")

def test_x_toggles_pad_mute():
    app, win, km = make_km()
    win._cur_row = 3
    km.handle(FakeEvent(key=ord('X')))
    assert ('toggle_mute', 3) in win._player.voice_manager.calls
    teardown(app)
    print("  X → toggle_mute(cur_row) : OK")

def test_s_toggles_pad_solo():
    app, win, km = make_km()
    win._cur_row = 2
    km.handle(FakeEvent(key=ord('S')))
    assert ('toggle_solo', 2) in win._player.voice_manager.calls
    teardown(app)
    print("  S → toggle_solo(cur_row) : OK")

def test_shift_x_unmutes_all_pads():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('X'), shift=True))
    assert ('set_mute_all', False) in win._player.voice_manager.calls
    teardown(app)
    print("  Shift+X → voice_manager.set_mute_all(False) : OK")

def test_shift_s_unsolos_all_pads():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('S'), shift=True))
    assert ('set_solo_all', False) in win._player.voice_manager.calls
    teardown(app)
    print("  Shift+S → voice_manager.set_solo_all(False) : OK")

def test_shift_f_halves_pattern():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('F'), shift=True))
    assert 'halve_pattern' in win._player.calls
    teardown(app)
    print("  Shift+F → halve_pattern() : OK")

def test_shift_q_quantizes_pattern():
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('Q'), shift=True))
    assert '_quantize_pattern' in win.calls
    teardown(app)
    print("  Shift+Q → _quantize_pattern() : OK")

def test_shift_e_unchecks_whole_row():
    app, win, km = make_km()
    win._cur_row = 0
    km.handle(FakeEvent(key=ord('E'), shift=True))
    assert all(('_set_cell', 0, c, False) in win.calls for c in range(win.COLS))
    teardown(app)
    print("  Shift+E → _set_cell(row, c, False) pour toutes les colonnes : OK")

def test_bpm_increase_via_key5():
    app, win, km = make_km()
    win._player.bpm = 120
    km.handle(FakeEvent(key=ord('5')))   # '5' AZERTY = '(' position US
    assert ('set_bpm', 125) in win._player.calls
    teardown(app)
    print("  Touche '5' → set_bpm(bpm+5) : OK")

def test_volume_decrease_via_key6():
    app, win, km = make_km()
    win._player.volume = 75
    km.handle(FakeEvent(key=ord('6')))   # '6' AZERTY = '-' position US
    assert ('set_volume', 74) in win._player.calls
    teardown(app)
    print("  Touche '6' → set_volume(vol-1) : OK")

def test_shift_p_does_not_play():
    # Shift+P génère un pattern aléatoire, ne doit pas déclencher play/stop
    app, win, km = make_km()
    win._player.playing = False
    km.handle(FakeEvent(key=ord('P'), shift=True))
    assert 'play_pattern' not in win._player.calls
    assert 'stop_pattern' not in win._player.calls
    teardown(app)
    print("  Shift+P ne déclenche pas play/stop : OK")

def test_ctrl_w_does_not_save_preset():
    # Ctrl+W → save_pattern, PAS save_preset
    app, win, km = make_km()
    km.handle(FakeEvent(key=ord('W'), ctrl=True))
    assert '_save_preset' not in win.calls
    assert '_save_pattern' in win.calls
    teardown(app)
    print("  Ctrl+W → _save_pattern() et non _save_preset() : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_key_manager ===")
    # F1 / touche inconnue
    test_f1_shows_keyboard_help()
    test_unknown_key_skips_event()
    # Alt
    test_alt_w_saves_preset()
    test_alt_shift_w_saves_preset_as()
    test_alt_x_opens_explorer()
    test_alt_up_increments_pad_volume()
    test_alt_down_decrements_pad_volume()
    test_alt_left_decrements_pad_pan()
    test_alt_right_increments_pad_pan()
    test_alt_0_resets_pad_pan()
    # Ctrl
    test_ctrl_w_saves_pattern()
    test_ctrl_shift_w_saves_pattern_as()
    test_ctrl_d_resets_pattern()
    test_ctrl_p_loads_demo_pattern()
    test_ctrl_f_doubles_pattern()
    test_ctrl_e_applies_quant()
    test_ctrl_shift_e_opens_gen_row_dialog()
    test_ctrl_1_sets_pad_mode()
    test_ctrl_2_sets_keyboard_mode()
    test_ctrl_shift_q_opens_quantize_dialog()
    test_ctrl_t_assigns_track_slot()
    test_ctrl_shift_t_opens_track_properties()
    test_ctrl_r_starts_count_in()
    # Navigation
    test_tab_calls_on_tab_order()
    test_shift_tab_calls_on_tab_order_shift()
    test_up_arrow_moves_grid()
    test_down_arrow_moves_grid()
    test_left_arrow_moves_grid()
    test_right_arrow_moves_grid()
    test_enter_checks_false_cell()
    test_shift_enter_unchecks_cell()
    # NumPad
    test_numpad0_stops_all()
    test_numpad_add_increments_shift_pad()
    test_numpad_subtract_decrements_shift_pad()
    test_numpad_add_clamps_at_8()
    test_numpad_subtract_clamps_at_0()
    # Touches caractères
    test_space_plays_pattern()
    test_space_stops_playing_pattern()
    test_p_plays_pattern()
    test_v_stops_all()
    test_r_starts_recording()
    test_r_stops_recording()
    test_shift_r_starts_replace_recording()
    test_shift_r_stops_replace_recording()
    test_q_enables_note_repeat()
    test_q_disables_note_repeat()
    test_c_plays_click()
    test_c_stops_click()
    test_e_toggles_erase()
    test_x_toggles_pad_mute()
    test_s_toggles_pad_solo()
    test_shift_x_unmutes_all_pads()
    test_shift_s_unsolos_all_pads()
    test_shift_f_halves_pattern()
    test_shift_q_quantizes_pattern()
    test_shift_e_unchecks_whole_row()
    test_bpm_increase_via_key5()
    test_volume_decrease_via_key6()
    test_shift_p_does_not_play()
    test_ctrl_w_does_not_save_preset()
    print("Tous les tests : OK")
