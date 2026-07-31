import os
import threading
import wx
from sound_manager import SoundManager
from sound_device_driver import SoundDeviceDriver
from drum_player import DrumPlayer
from pattern import Pattern
from rack import Rack, InstrumentType
from song import Song
from synth_engine import midi_to_note_name, SCALE_NAMES, SCALE_LABELS
from track_router import TrackRouter
from app_config import AppConfig
import sound_cache
from ui.dialogs import (
    KeyboardHelpDialog,
    GenRowDialog,
    GotoDialog,
    QuantizeDialog,
    SavePatternDialog,
    SaveSongDialog,
    TrackPropertiesDialog,
    TrackSelectDialog,
    PatternPropertiesDialog,
    PadPropertiesDialog,
    ExplorerDialog,
    LoopSelectDialog,
)
from ui.key_manager import KeyManager
from ui.midi_handler import MidiHandler
from ui.song_window import SongWindow
from ui.mw_patterns    import PatternMixin
from ui.mw_songs       import SongMixin
from ui.mw_project     import ProjectMixin
from ui.mw_tracks      import TrackMixin
from ui.mw_pads        import PadMixin
from ui.mw_midi_editor import MidiEditorMixin
from midi_manager import MidiManager
from track_editor import TrackEditor
from project_manager import ProjectManager
from undo_manager import UndoManager


class _LoadingDialog(wx.Dialog):
    """Fenêtre modale 'Chargement…' affichée pendant le préchargement des sons."""

    def __init__(self, parent, router):
        super().__init__(parent, title="GroovyboxIt",
                         style=wx.CAPTION | wx.STAY_ON_TOP)
        self._router = router
        label = wx.StaticText(self, label="Chargement, veuillez patienter…")
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(label, 0, wx.ALL | wx.ALIGN_CENTER, 24)
        self.SetSizer(sizer)
        self.Fit()
        self.Centre()
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick, self._timer)
        self._timer.Start(100)

    def _on_tick(self, _event):
        if all(not t.is_alive() for t in self._router._load_threads):
            self._timer.Stop()
            self.EndModal(wx.ID_OK)


class MainWindow(PatternMixin, SongMixin, ProjectMixin, TrackMixin, PadMixin,
                 MidiEditorMixin, wx.Frame):
    ROWS = 16
    COLS = 16
    NR_BINARY  = [0, 1, 3, 5, 7, 9, 11, 13]
    NR_TERNARY = [2, 4, 6,  8, 10, 12]

    VEL_LEVEL_LABELS = [
        "Level_01 - Full Level",
        "Level_02 - 4 Levels",
        "Level_03 - 8 Levels",
        "Level_04 - 16 Levels",
        "Level_05 - No Level",
    ]
    _VEL_STEPS = [None, 32, 16, 8, None]

    def __init__(self):
        super().__init__(None, title="GroovyboxIt")
        self._cur_row = 0
        self._cur_col = 0
        self._cells = []
        self._shift_pad = 0
        self._autoplay  = True
        self._note_repeat      = False
        self._nr_active_key    = None
        self._nr_prev_key      = None
        self._nr_release_timer = None
        self._nr_rate_idx      = 7
        self._nr_ternary       = False
        self._nr_midi_note     = None
        self._kb_scale     = "chromatic"
        self._kb_play_root = 48
        self._kb_root_midi = 48
        self._input_mode       = "pad"
        self._vel_level        = 4
        self._init_sound()
        self._synths_dir  = os.path.join(self._base_dir, "synths")
        cfg = AppConfig(self._base_dir)
        self._patches_dir  = cfg.patches_dir
        self._samples_dir  = cfg.samples_dir
        self._kits_dir     = cfg.kits_dir
        self._presets_dir  = cfg.presets_dir
        self._projects_dir = cfg.projects_dir
        sound_cache.init(cfg.sound_cache_dir)
        self._rack = Rack()
        self._rack.set_slot(0, InstrumentType.KIT, "TR-707",
                            {"kit": os.path.join(self._kits_dir, "tr_707.json")})
        self._rack.set_slot(1, InstrumentType.SYNTH, "Acoustic Guitar 1",
                            {"patch": os.path.join(self._patches_dir, "accoustic_guitar_1.json")})
        self._rack.set_slot(2, InstrumentType.SYNTH, "Piano 1",
                            {"patch": os.path.join(self._patches_dir, "piano_01.json")})
        self._rack.set_slot(3, InstrumentType.SYNTH, "Organ B3 Basic Fast",
                            {"patch": os.path.join(self._patches_dir, "organ_b3_basic_fast.json")})
        self._rack.set_slot(4, InstrumentType.KIT, "GM (FluidR3)",
                            {"kit": os.path.join(self._kits_dir, "gm.json")})
        self._cur_slot = 0
        self._router = TrackRouter(
            self._rack, self._synths_dir, self._snd,
            lambda msg: wx.CallAfter(self._show_status, msg),
            driver=self._audio_driver,
        )
        self._player._on_track_play_cb = self._router.on_play
        self._player._on_kit_tape_cb    = self._router.on_kit_tape
        self._player._on_patch_tape_cb  = self._router.on_patch_tape
        self._player._on_bend_tape_cb   = self._router.on_bend_tape
        self._player._on_mod_tape_cb    = self._router.on_mod_tape
        self._router.update_kb_notes(self._kb_scale, self._kb_play_root)
        self._pattern_list = [Pattern() for _ in range(99)]
        self._cur_pattern_idx = 0
        self._song_list = [Song(i) for i in range(Song.MAX_SONGS)]
        self._cur_song_idx = 0
        self._song_window         = None
        self._midi_editor_window  = None
        self._midi_editor_view_mode = 0   # dernier mode utilisé (0=notes piste, 1=tous)
        self._pre_song_pattern_idx = 0
        self._player._pattern_list_ref     = self._pattern_list
        self._player._on_song_advance_cb   = lambda idx: wx.CallAfter(self._on_song_advance, idx)
        self._player._on_song_cross_nav_cb = self._on_song_cross_nav
        self._project_path     = self._resolve_project_path()
        self._project_modified = False
        self._midi_handler = MidiHandler(self)
        self._midi = MidiManager(
            on_note_on    = lambda n, v, c:  wx.CallAfter(self._midi_handler.on_note_on, n, v, c),
            on_note_off   = lambda n, c:     wx.CallAfter(self._midi_handler.on_note_off, n, c),
            on_status     = lambda msg:      wx.CallAfter(self._show_status, msg),
            on_cc         = lambda cc, v, c: wx.CallAfter(self._midi_handler.on_cc, cc, v, c),
            on_pitch_bend = lambda b, c:     wx.CallAfter(self._midi_handler.on_pitch_bend, b, c),
        )
        self._track_editor = TrackEditor()
        self._undo = UndoManager()
        self._pattern_cache       = [None] * len(self._pattern_list)
        self._pattern_cache_dirty = set(range(len(self._pattern_list)))
        self._skip_next_track_select = False
        self._build_ui()
        self._update_title()
        self._load_kit_slot(0)
        self._load_project()
        self._router.load_slot_preview(1)
        self._key_manager = KeyManager(self)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Centre()

    def wait_loaded(self):
        """Affiche 'Chargement…' et bloque jusqu'à ce que tous les sons soient prêts."""
        if any(t.is_alive() for t in self._router._load_threads):
            dlg = _LoadingDialog(self, self._router)
            dlg.ShowModal()
            dlg.Destroy()
        self._router.wait_loaded()

    def _init_sound(self):
        ui_dir = os.path.dirname(os.path.abspath(__file__))
        self._base_dir = os.path.dirname(os.path.dirname(ui_dir))
        base_dir = self._base_dir
        cfg = AppConfig(base_dir)
        media_dir = cfg.media_dir
        media_lst = [os.path.join(media_dir, f"{i}.wav") for i in range(1, 17)]
        self._audio_driver = SoundDeviceDriver()
        self._snd = SoundManager(media_lst, cfg.click1_file, cfg.click2_file,
                                 driver=self._audio_driver)
        self._player = DrumPlayer(self._snd)
        self._player._on_recorded_cb = lambda pad, bar, step: wx.CallAfter(
            self._on_nr_recorded, pad, bar, step
        )
        self._player._on_replaced_cb = lambda pad, bar, step: wx.CallAfter(
            self._on_note_replaced, pad, bar, step
        )
        self._player._on_count_in_done_cb = lambda: wx.CallAfter(self._on_count_in_done)

    def _build_ui(self):
        panel = wx.Panel(self)

        self._status_ctrl = wx.ListBox(
            panel,
            choices=["ShiftPad: 1/8"],
            style=wx.LB_SINGLE,
        )

        bpm_label = wx.StaticText(panel, label="BPM:")
        self._bpm_ctrl = wx.SpinCtrl(panel, min=1, max=600, initial=self._player.bpm, size=(80, -1))
        self._bpm_ctrl.Bind(wx.EVT_SPINCTRL, self._on_bpm_spin)

        vol_label = wx.StaticText(panel, label="Vol:")
        self._volume_ctrl = wx.SpinCtrl(panel, min=0, max=100, initial=self._player.volume, size=(70, -1))
        self._volume_ctrl.Bind(wx.EVT_SPINCTRL, self._on_volume_spin)

        pan_label = wx.StaticText(panel, label="Pan:")
        self._pan_ctrl = wx.SpinCtrl(panel, min=-100, max=100, initial=self._player.pan, size=(70, -1))
        self._pan_ctrl.Bind(wx.EVT_SPINCTRL, self._on_pan_spin)

        quant_label = wx.StaticText(panel, label="Quant:")
        self._quant_list = wx.ListBox(
            panel,
            choices=Pattern.QUANT_LABELS,
            style=wx.LB_SINGLE,
        )
        self._quant_list.SetSelection(self._player.quant_idx)
        self._quant_list.Bind(wx.EVT_LISTBOX,        self._on_quant_select)
        self._quant_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_listbox_play_activate)

        pattern_label = wx.StaticText(panel, label="Pat:")
        self._pattern_listbox = wx.ListBox(
            panel,
            choices=[self._pattern_label(i) for i in range(99)],
            style=wx.LB_SINGLE,
        )
        self._pattern_listbox.SetSelection(0)
        self._pattern_listbox.Bind(wx.EVT_LISTBOX,        self._on_pattern_select)
        self._pattern_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_pattern_list_activate)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(self._status_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        hbox.Add(bpm_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox.Add(self._bpm_ctrl, 0, wx.EXPAND | wx.RIGHT, 8)
        hbox.Add(vol_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox.Add(self._volume_ctrl, 0, wx.EXPAND | wx.RIGHT, 8)
        hbox.Add(pan_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox.Add(self._pan_ctrl, 0, wx.EXPAND | wx.RIGHT, 8)
        hbox.Add(quant_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox.Add(self._quant_list, 0, wx.EXPAND | wx.RIGHT, 8)
        hbox.Add(pattern_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox.Add(self._pattern_listbox, 0, wx.EXPAND)

        mode_label = wx.StaticText(panel, label="Mode:")
        self._mode_choice = wx.ListBox(panel, choices=["Mode: Pad", "Mode: Keyboard"], style=wx.LB_SINGLE)
        self._mode_choice.SetSelection(0)
        self._mode_choice.Bind(wx.EVT_LISTBOX,        self._on_mode_choice)
        self._mode_choice.Bind(wx.EVT_LISTBOX_DCLICK, self._on_listbox_play_activate)

        scale_label = wx.StaticText(panel, label="Gamme:")
        self._scale_choice = wx.ListBox(panel, choices=SCALE_LABELS, style=wx.LB_SINGLE)
        self._scale_choice.SetSelection(SCALE_NAMES.index(self._kb_scale))
        self._scale_choice.Bind(wx.EVT_LISTBOX,        self._on_scale_choice)
        self._scale_choice.Bind(wx.EVT_LISTBOX_DCLICK, self._on_listbox_play_activate)

        slot_label = wx.StaticText(panel, label="Slot:")
        self._slot_choice = wx.ListBox(panel, choices=self._rack.labels(), style=wx.LB_SINGLE)
        self._slot_choice.SetSelection(0)
        self._slot_choice.Bind(wx.EVT_LISTBOX,        self._on_slot_choice)
        self._slot_choice.Bind(wx.EVT_LISTBOX_DCLICK, self._on_slot_list_activate)

        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        hbox2.Add(mode_label,         0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox2.Add(self._mode_choice,  0, wx.EXPAND | wx.RIGHT, 8)
        hbox2.Add(scale_label,        0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox2.Add(self._scale_choice, 0, wx.EXPAND | wx.RIGHT, 8)
        hbox2.Add(slot_label,         0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox2.Add(self._slot_choice,  0, wx.EXPAND)

        track_label = wx.StaticText(panel, label="Piste:")
        self._track_list = wx.ListBox(
            panel,
            choices=[self._track_label(i) for i in range(8)],
            style=wx.LB_SINGLE,
        )
        self._track_list.SetSelection(0)
        self._track_list.Bind(wx.EVT_LISTBOX,        self._on_track_select)
        self._track_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_track_list_activate)

        pad_label = wx.StaticText(panel, label="Pad:")
        self._pad_list = wx.ListBox(
            panel,
            choices=[self._pad_label(i) for i in range(self.ROWS)],
            style=wx.LB_SINGLE,
        )
        self._pad_list.SetSelection(0)
        self._pad_list.Bind(wx.EVT_LISTBOX,        self._on_pad_select)
        self._pad_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_pad_list_activate)

        vel_label = wx.StaticText(panel, label="Vel:")
        self._vel_list = wx.ListBox(
            panel,
            choices=self.VEL_LEVEL_LABELS,
            style=wx.LB_SINGLE,
        )
        self._vel_list.SetSelection(self._vel_level)
        self._vel_list.Bind(wx.EVT_LISTBOX, self._midi_handler.on_vel_level_select)

        midi_label = wx.StaticText(panel, label="MIDI:")
        self._midi_port_list = wx.ListBox(
            panel,
            choices=self._midi.list_ports() or ["(aucun port)"],
            style=wx.LB_SINGLE,
        )
        if self._midi.list_ports():
            self._midi_port_list.SetSelection(0)
        self._midi_port_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_midi_port_activate)

        hbox3 = wx.BoxSizer(wx.HORIZONTAL)
        hbox3.Add(track_label,           0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox3.Add(self._track_list,      0, wx.EXPAND | wx.RIGHT, 8)
        hbox3.Add(pad_label,             0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox3.Add(self._pad_list,        0, wx.EXPAND | wx.RIGHT, 8)
        hbox3.Add(vel_label,             0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox3.Add(self._vel_list,        0, wx.EXPAND | wx.RIGHT, 8)
        hbox3.Add(midi_label,            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox3.Add(self._midi_port_list,  0, wx.EXPAND)

        self._mute_btns = []
        self._solo_btns = []
        self._vol_ctrls = []
        self._pan_ctrls = []
        voice_grid = wx.FlexGridSizer(self.ROWS, 4, 2, 2)
        for r in range(self.ROWS):
            m_btn   = wx.ToggleButton(panel, label="M", size=(26, -1))
            s_btn   = wx.ToggleButton(panel, label="S", size=(26, -1))
            vol_sp  = wx.SpinCtrl(panel, min=0,    max=100,  initial=100, size=(60, -1))
            pan_sp  = wx.SpinCtrl(panel, min=-100, max=100,  initial=0,   size=(68, -1))
            m_btn.Bind(wx.EVT_TOGGLEBUTTON, lambda e, r=r: self._on_mute_btn(r))
            s_btn.Bind(wx.EVT_TOGGLEBUTTON, lambda e, r=r: self._on_solo_btn(r))
            vol_sp.Bind(wx.EVT_SPINCTRL, lambda e, r=r: self._on_vol_spin(r))
            pan_sp.Bind(wx.EVT_SPINCTRL, lambda e, r=r: self._on_pan_spin(r))
            voice_grid.Add(m_btn,  0, wx.EXPAND)
            voice_grid.Add(s_btn,  0, wx.EXPAND)
            voice_grid.Add(vol_sp, 0, wx.EXPAND)
            voice_grid.Add(pan_sp, 0, wx.EXPAND)
            self._mute_btns.append(m_btn)
            self._solo_btns.append(s_btn)
            self._vol_ctrls.append(vol_sp)
            self._pan_ctrls.append(pan_sp)

        grid = wx.GridSizer(self.ROWS, self.COLS, 2, 2)
        for r in range(self.ROWS):
            row = []
            for c in range(self.COLS):
                cb = wx.CheckBox(panel, label=f"Pad{r + 1}/{c + 1}")
                cb.Bind(wx.EVT_CHECKBOX, lambda e, r=r, c=c: self._on_checkbox(r, c))
                cb.Bind(wx.EVT_SET_FOCUS, lambda e, r=r, c=c: self._set_cursor(r, c))
                grid.Add(cb, 0, wx.EXPAND)
                row.append(cb)
            self._cells.append(row)

        content_hbox = wx.BoxSizer(wx.HORIZONTAL)
        content_hbox.Add(voice_grid, 0, wx.EXPAND | wx.RIGHT, 4)
        content_hbox.Add(grid,       1, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(hbox,         0, wx.EXPAND | wx.ALL, 4)
        vbox.Add(hbox2,        0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        vbox.Add(hbox3,        0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        vbox.Add(content_hbox, 1, wx.EXPAND)
        panel.SetSizer(vbox)

        self._tab_order = [
            self._status_ctrl,
            self._bpm_ctrl,
            self._volume_ctrl,
            self._pan_ctrl,
            self._quant_list,
            self._pattern_listbox,
            self._mode_choice,
            self._scale_choice,
            self._slot_choice,
            self._track_list,
            self._pad_list,
            self._vel_list,
            self._midi_port_list,
        ]

        self.Fit()
        self._cells[0][0].SetFocus()

    def _set_cursor(self, row, col):
        self._cur_row = row
        self._cur_col = col
        self._pad_list.SetSelection(row)

    def _set_cell(self, row, col, value):
        self._cells[row][col].SetValue(bool(value))
        self._player._pattern.set_cell(
            self._player._cur_track, row, 0, col, 100 if value else 0
        )
        self._player.float_offsets[row] = [
            float(c) for c in range(self.COLS)
            if self._player._pattern.get_cell(self._player._cur_track, row, 0, c)
        ]

    def _on_checkbox(self, row, col):
        self._add_undo(f"Cellule {row + 1}/{col + 1}")
        self._player._pattern.set_cell(
            self._player._cur_track, row, 0, col,
            100 if self._cells[row][col].GetValue() else 0,
        )
        self._player.float_offsets[row] = [
            float(c) for c in range(self.COLS)
            if self._player._pattern.get_cell(self._player._cur_track, row, 0, c)
        ]

    def _on_bpm_spin(self, event):
        bpm = self._bpm_ctrl.GetValue()
        self._player.set_bpm(bpm)
        self._show_status(f"BPM: {bpm}")

    def _on_volume_spin(self, event):
        vol = self._volume_ctrl.GetValue()
        self._player.set_volume(vol)
        self._show_status(f"Volume: {vol}")

    def _on_pan_spin(self, event):
        pan = self._pan_ctrl.GetValue()
        self._player.set_pan(pan)
        self._show_status(f"Pan Global: {pan}")

    def _on_close(self, event):
        if self._project_modified:
            dlg = wx.MessageDialog(
                self,
                "Le projet a été modifié.\nEnregistrer avant de quitter ?",
                "Quitter",
                wx.YES_NO | wx.CANCEL | wx.YES_DEFAULT | wx.ICON_QUESTION,
            )
            resp = dlg.ShowModal()
            dlg.Destroy()
            if resp == wx.ID_CANCEL:
                event.Veto()
                return
            if resp == wx.ID_YES:
                self._save_project()
        self._midi.close()
        self._audio_driver.close()
        event.Skip()

    def _update_bpm_display(self):
        self._bpm_ctrl.SetValue(self._player.bpm)

    def _on_nr_recorded(self, pad_idx, bar_idx, step_idx):
        if bar_idx == 0 and step_idx < self.COLS:
            self._cells[pad_idx][step_idx].SetValue(True)

    def _on_note_replaced(self, pad_idx, bar_idx, step_idx):
        if bar_idx == 0 and step_idx < self.COLS:
            self._cells[pad_idx][step_idx].SetValue(False)

    def _on_count_in_done(self):
        self._refresh_track_list()
        track_idx = self._player._cur_track
        self._show_status(f"Rec: Piste {track_idx + 1} — {self._router.slot_name(track_idx)}")

    def _set_input_mode(self, mode):
        modes = ["pad", "keyboard"]
        if mode not in modes:
            return
        self._input_mode = mode
        self._mode_choice.SetSelection(modes.index(mode))
        if mode == "keyboard":
            self._router.update_kb_notes(self._kb_scale, self._kb_play_root)
            self._router.update_input_kb(self._kb_root_midi)
            self._show_status(
                f"Mode: Keyboard — {self._kb_scale} @ {midi_to_note_name(self._kb_root_midi)}"
            )
            if self._router.synth_ready():
                engine = self._router.synth
                def _precache():
                    engine.precompute(list(range(36, 97)), duration_ms=0)
                threading.Thread(target=_precache, daemon=True).start()
        else:
            self._show_status("Mode: Pad")

    def _on_mode_choice(self, event):
        modes = ["pad", "keyboard"]
        self._set_input_mode(modes[self._mode_choice.GetSelection()])

    def _on_scale_choice(self, event):
        self._kb_scale = SCALE_NAMES[self._scale_choice.GetSelection()]
        self._router.update_kb_notes(self._kb_scale, self._kb_play_root)
        self._router.update_input_kb(self._kb_root_midi)
        self._show_status(
            f"Gamme: {self._kb_scale} @ {midi_to_note_name(self._kb_root_midi)}"
        )

    def _show_status(self, msg):
        self._status_ctrl.SetString(0, msg)

    def _move(self, dr, dc):
        r = max(0, min(self.ROWS - 1, self._cur_row + dr))
        c = max(0, min(self.COLS - 1, self._cur_col + dc))
        if r == self._cur_row and c == self._cur_col:
            wx.Bell()
        else:
            if dr != 0 and self._autoplay:
                self._play(r)
        self._cells[r][c].SetFocus()

    def _play(self, idx):
        slot = self._rack.get_slot(self._cur_slot)
        if self._input_mode == "keyboard" and slot.type == InstrumentType.SYNTH \
                and self._router.synth_ready() and idx < len(self._router.kb_notes_input):
            midi = self._router.kb_notes_input[idx]
            self._router.synth.play(midi)
            self._router.kb_last_midi = midi
        else:
            self._player.play_sound(idx)

    def _nr_arm_release(self):
        if self._nr_release_timer:
            self._nr_release_timer.cancel()
        self._nr_release_timer = threading.Timer(
            0.050, lambda: wx.CallAfter(setattr, self, '_nr_active_key', None)
        )
        self._nr_release_timer.start()

    def _nr_cancel_release(self):
        if self._nr_release_timer:
            self._nr_release_timer.cancel()
            self._nr_release_timer = None

    def _on_tab_order(self, shift):
        focused = wx.Window.FindFocus()
        order   = self._tab_order
        if focused in order:
            idx = order.index(focused)
            if shift:
                target = self._cells[self._cur_row][self._cur_col] if idx == 0 \
                         else order[idx - 1]
            else:
                target = self._cells[self._cur_row][self._cur_col] if idx == len(order) - 1 \
                         else order[idx + 1]
        else:
            target = order[0] if not shift else order[-1]
        target.SetFocus()

    def _on_char_hook(self, event):
        focused = wx.Window.FindFocus()
        if focused and focused.GetTopLevelParent() is not self:
            event.Skip()
            return
        self._key_manager.handle(event)
