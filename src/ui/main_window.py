import json
import os
import wx
from sound_manager import SoundManager
from drum_player import DrumPlayer
from pattern import Pattern
from rack import Rack, InstrumentType
from synth_engine import midi_to_note_name, SCALE_NAMES, SCALE_LABELS
from track_router import TrackRouter
from app_config import AppConfig
from ui.dialogs import (
    KeyboardHelpDialog,
    GenRowDialog,
    QuantizeDialog,
    SavePatternDialog,
    TrackPropertiesDialog,
    PatternPropertiesDialog,
    PadPropertiesDialog,
)
from ui.key_manager import KeyManager
from ui.midi_handler import MidiHandler
from midi_manager import MidiManager


class MainWindow(wx.Frame):
    ROWS = 16
    COLS = 16
    # Indices dans QUANT_LIST pour les touches 1-8 (binaire) et 1-6 (ternaire)
    NR_BINARY  = [0, 1, 3, 5, 7, 9, 11, 13]   # 1/1,1/2,1/4,1/8,1/16,1/32,1/64,1/128
    NR_TERNARY = [2, 4, 6,  8, 10, 12]          # 1/3,1/6,1/12,1/24,1/48,1/96

    # Niveaux de quantification de vélocité MIDI en entrée
    VEL_LEVEL_LABELS = [
        "Level_01 - Full Level",   # → 127 fixe
        "Level_02 - 4 Levels",     # paliers de 32
        "Level_03 - 8 Levels",     # paliers de 16
        "Level_04 - 16 Levels",    # paliers de 8
        "Level_05 - No Level",     # vélocité brute
    ]
    _VEL_STEPS = [None, 32, 16, 8, None]  # None = cas spéciaux (Full / No Level)

    def __init__(self):
        super().__init__(None, title="GroovyboxIt")
        self._cur_row = 0
        self._cur_col = 0
        self._cells = []
        self._shift_pad = 0   # 0 → pads 1-8 (indices 0-7), 8 → pads 9-16 (indices 8-15)
        self._autoplay  = True
        self._note_repeat      = False
        self._nr_active_key    = None   # touche NumPad tenue (effacée par timer)
        self._nr_prev_key      = None   # dernière touche NumPad ayant démarré le NR
        self._nr_release_timer = None
        self._nr_rate_idx      = 7      # indice QUANT_LIST courant (défaut 1/16)
        self._nr_ternary       = False  # False=binaire, True=ternaire
        self._nr_midi_note     = None   # note MIDI tenue en mode Note Repeat
        self._kb_scale     = "major"
        self._kb_play_root = 48   # C3 — root de lecture, stable (non affectée par Numpad+/-)
        self._kb_root_midi = 48   # C3 — root d'entrée, transposable avec Numpad+/-
        self._input_mode       = "pad"   # "pad" | "keyboard"
        self._vel_level        = 4      # 0=Full,1=4Lev,2=8Lev,3=16Lev,4=No Level
        self._init_sound()
        self._synths_dir  = os.path.join(self._base_dir, "synths")
        cfg = AppConfig(self._base_dir)
        self._patches_dir = cfg.patches_dir
        self._samples_dir = cfg.samples_dir
        self._kits_dir    = cfg.kits_dir
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
        )
        self._player._on_track_play_cb = self._router.on_play
        self._player._on_kit_tape_cb    = self._router.on_kit_tape
        self._player._on_patch_tape_cb  = self._router.on_patch_tape
        self._router.update_kb_notes(self._kb_scale, self._kb_play_root)
        self._pattern_list = [Pattern() for _ in range(99)]
        self._cur_pattern_idx = 0
        self._preset_path = os.path.join(self._base_dir, "data", "presets", "preset_01.json")
        self._midi_handler = MidiHandler(self)
        self._midi = MidiManager(
            on_note_on  = lambda n, v, c: wx.CallAfter(self._midi_handler.on_note_on, n, v, c),
            on_note_off = lambda n, c:    wx.CallAfter(self._midi_handler.on_note_off, n, c),
            on_status   = lambda msg:     wx.CallAfter(self._show_status, msg),
        )
        self._build_ui()
        self._load_kit_slot(0)
        self._load_preset()
        self._router.load_slot_preview(1)   # pré-chargement A440 en arrière-plan
        self._key_manager = KeyManager(self)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Centre()

    def _init_sound(self):
        ui_dir = os.path.dirname(os.path.abspath(__file__))
        self._base_dir = os.path.dirname(os.path.dirname(ui_dir))
        base_dir = self._base_dir
        media_dir = os.path.join(base_dir, "media")
        self._media_dir = media_dir
        media_lst = [os.path.join(media_dir, f"{i}.wav") for i in range(1, 17)]
        click1 = os.path.join(media_dir, "hi_wood_block_mono.wav")
        click2 = os.path.join(media_dir, "low_wood_block_mono.wav")
        self._media_lst = media_lst
        self._snd = SoundManager(media_lst, click1, click2)
        # Les sons du kit sont chargés plus tard par _load_kit_slot()
        self._player = DrumPlayer(self._snd)
        self._player._on_recorded_cb = lambda pad, bar, step: wx.CallAfter(
            self._on_nr_recorded, pad, bar, step
        )
        self._player._on_replaced_cb = lambda pad, bar, step: wx.CallAfter(
            self._on_note_replaced, pad, bar, step
        )
        self._player._on_count_in_done_cb = lambda: wx.CallAfter(self._on_count_in_done)
        # _on_track_play_cb est enregistré après la création de _router (voir __init__)

    def _build_ui(self):
        panel = wx.Panel(self)

        self._status_ctrl = wx.TextCtrl(
            panel,
            style=wx.TE_READONLY | wx.TE_LEFT | wx.BORDER_SIMPLE,
        )
        self._status_ctrl.SetValue("ShiftPad: 1/8")

        bpm_label = wx.StaticText(panel, label="BPM:")
        self._bpm_ctrl = wx.SpinCtrl(panel, min=5, max=600, initial=self._player.bpm, size=(80, -1))
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
            choices=DrumPlayer.QUANT_LABELS,
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

        # --- Barre 2 : Mode / Gamme / Slot ---
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
        self._slot_choice.Bind(wx.EVT_LISTBOX_DCLICK, self._on_listbox_play_activate)

        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        hbox2.Add(mode_label,         0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox2.Add(self._mode_choice,  0, wx.EXPAND | wx.RIGHT, 8)
        hbox2.Add(scale_label,        0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox2.Add(self._scale_choice, 0, wx.EXPAND | wx.RIGHT, 8)
        hbox2.Add(slot_label,         0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox2.Add(self._slot_choice,  0, wx.EXPAND)

        # --- Barre 3 : Pistes + Pads ---
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
        self._midi_port_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_listbox_play_activate)

        hbox3 = wx.BoxSizer(wx.HORIZONTAL)
        hbox3.Add(track_label,           0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox3.Add(self._track_list,      0, wx.EXPAND | wx.RIGHT, 8)
        hbox3.Add(pad_label,             0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox3.Add(self._pad_list,        0, wx.EXPAND | wx.RIGHT, 8)
        hbox3.Add(vel_label,             0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox3.Add(self._vel_list,        0, wx.EXPAND | wx.RIGHT, 8)
        hbox3.Add(midi_label,            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox3.Add(self._midi_port_list,  0, wx.EXPAND)

        # Panneau voix : M / S / SpinVol / SpinPan par ligne
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

        # Ordre de navigation Tab/Shift+Tab entre les widgets principaux.
        # La grille (cells) est le point de départ/arrivée implicite aux extrémités.
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
            self._midi_port_list,   # juste avant la grille
        ]

        self.Fit()
        self._cells[0][0].SetFocus()

    def _set_cursor(self, row, col):
        self._cur_row = row
        self._cur_col = col
        self._pad_list.SetSelection(row)

    def _set_cell(self, row, col, value):
        self._cells[row][col].SetValue(bool(value))
        self._player._pattern._curpattern[self._player._cur_track][row][0][col] = \
            100 if value else 0
        self._player.float_offsets[row] = [
            float(c) for c in range(self.COLS) if self._player._pattern._curpattern[self._player._cur_track][row][0][c]
        ]

    def _on_checkbox(self, row, col):
        self._player._pattern._curpattern[self._player._cur_track][row][0][col] = \
            100 if self._cells[row][col].GetValue() else 0
        self._player.float_offsets[row] = [
            float(c) for c in range(self.COLS) if self._player._pattern._curpattern[self._player._cur_track][row][0][c]
        ]

    def _refresh_grid(self):
        for r in range(self.ROWS):
            for c in range(self.COLS):
                self._cells[r][c].SetValue(self._player._pattern._curpattern[self._player._cur_track][r][0][c])
        self._player._compute_offsets()

    def _on_pattern_select(self, event):
        self._switch_pattern(self._pattern_listbox.GetSelection())

    def _pattern_label(self, idx):
        pat = self._pattern_list[idx]
        if pat._name:
            return f"Pat_{idx + 1:02d} - {pat._name}"
        if pat.is_empty():
            return f"Pat_{idx + 1:02d} (Unused)"
        return f"Pat_{idx + 1:02d}"

    def _refresh_pattern_listbox(self):
        sel = self._pattern_listbox.GetSelection()
        self._pattern_listbox.Set([self._pattern_label(i) for i in range(99)])
        self._pattern_listbox.SetSelection(sel if sel != wx.NOT_FOUND else 0)

    def _switch_pattern(self, idx):
        cur = self._pattern_list[self._cur_pattern_idx]
        cur._voices        = self._player.voice_manager.to_list()
        cur._track_slots   = self._router._track_slots[:]
        cur._track_mutes   = self._router._track_mutes[:]
        cur._track_solos   = self._router._track_solos[:]
        cur._track_volumes = self._router._track_volumes[:]
        cur._track_pans    = self._router._track_pans[:]
        cur._kit_tape      = dict(self._player._pattern._kit_tape)
        cur._patch_tape    = dict(self._player._pattern._patch_tape)
        self._cur_pattern_idx = idx
        new = self._pattern_list[idx]
        self._player._pattern.load_pattern(new._curpattern)
        self._player._pattern._looping   = new._looping
        self._player._pattern._kit_tape   = dict(new._kit_tape)
        self._player._pattern._patch_tape = dict(new._patch_tape)
        self._player.voice_manager.from_list(new._voices)
        self._router._track_slots[:]   = new._track_slots
        self._router._track_mutes[:]   = new._track_mutes
        self._router._track_solos[:]   = new._track_solos
        self._router._track_volumes[:] = new._track_volumes
        self._router._track_pans[:]    = new._track_pans
        self._player._compute_offsets()
        self._refresh_grid()
        self._refresh_all_voice_display()
        self._refresh_track_list()
        self._refresh_pad_list()
        self._show_status(f"Pattern {idx + 1:02d}")

    def _save_pattern(self):
        pat = self._pattern_list[self._cur_pattern_idx]
        pat.load_pattern(self._player._pattern._curpattern)
        pat._track_slots   = self._router._track_slots[:]
        pat._track_mutes   = self._router._track_mutes[:]
        pat._track_solos   = self._router._track_solos[:]
        pat._track_volumes = self._router._track_volumes[:]
        pat._track_pans    = self._router._track_pans[:]
        pat._kit_tape      = dict(self._player._pattern._kit_tape)
        pat._patch_tape    = dict(self._player._pattern._patch_tape)
        self._refresh_pattern_listbox()
        self._show_status(f"Pattern {self._cur_pattern_idx + 1:02d} sauvegardé")

    def _save_pattern_as(self):
        cur_name = self._pattern_list[self._cur_pattern_idx]._name
        dlg = SavePatternDialog(self, self._cur_pattern_idx, cur_name)
        if dlg.ShowModal() == wx.ID_OK:
            idx  = dlg.get_selection()
            name = dlg.get_name()
            pat  = self._pattern_list[idx]
            pat.load_pattern(self._player._pattern._curpattern)
            pat._name          = name
            pat._track_slots   = self._router._track_slots[:]
            pat._track_mutes   = self._router._track_mutes[:]
            pat._track_solos   = self._router._track_solos[:]
            pat._track_volumes = self._router._track_volumes[:]
            pat._track_pans    = self._router._track_pans[:]
            pat._kit_tape      = dict(self._player._pattern._kit_tape)
            pat._patch_tape    = dict(self._player._pattern._patch_tape)
            self._refresh_pattern_listbox()
            self._show_status(f"Pattern {idx + 1:02d} sauvegardé")
        dlg.Destroy()

    def _save_preset(self):
        cur = self._pattern_list[self._cur_pattern_idx]
        cur._voices        = self._player.voice_manager.to_list()
        cur._track_slots   = self._router._track_slots[:]
        cur._track_mutes   = self._router._track_mutes[:]
        cur._track_solos   = self._router._track_solos[:]
        cur._track_volumes = self._router._track_volumes[:]
        cur._track_pans    = self._router._track_pans[:]
        cur._kit_tape      = dict(self._player._pattern._kit_tape)
        cur._patch_tape    = dict(self._player._pattern._patch_tape)
        os.makedirs(os.path.dirname(self._preset_path), exist_ok=True)
        data = {"version": 1, "patterns": [pat.to_dict() for pat in self._pattern_list]}
        with open(self._preset_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self._show_status(f"Preset sauvegardé : {os.path.basename(self._preset_path)}")

    def _save_preset_as(self):
        presets_dir = os.path.dirname(self._preset_path)
        os.makedirs(presets_dir, exist_ok=True)
        dlg = wx.FileDialog(
            self,
            message="Enregistrer le preset sous…",
            defaultDir=presets_dir,
            defaultFile=os.path.basename(self._preset_path),
            wildcard="Preset JSON (*.json)|*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._preset_path = dlg.GetPath()
            self._save_preset()
        dlg.Destroy()

    def _load_preset(self):
        if not os.path.exists(self._preset_path):
            return
        with open(self._preset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for i, p in enumerate(data.get("patterns", [])):
            if i >= len(self._pattern_list):
                break
            self._pattern_list[i].from_dict(p)
        self._refresh_pattern_listbox()
        # Restaure le pattern 0 directement sans écraser ses _track_slots chargés
        self._cur_pattern_idx = 0
        new = self._pattern_list[0]
        self._player._pattern.load_pattern(new._curpattern)
        self._player._pattern._looping    = new._looping
        self._player._pattern._kit_tape   = dict(new._kit_tape)
        self._player._pattern._patch_tape = dict(new._patch_tape)
        self._player.voice_manager.from_list(new._voices)
        self._router._track_slots[:]   = new._track_slots
        self._router._track_mutes[:]   = new._track_mutes
        self._router._track_solos[:]   = new._track_solos
        self._router._track_volumes[:] = new._track_volumes
        self._router._track_pans[:]    = new._track_pans
        for track_idx, slot_idx in enumerate(new._track_slots):
            slot = self._rack.get_slot(slot_idx)
            if slot.type == InstrumentType.SYNTH:
                self._router.assign_slot(track_idx, slot_idx)
        self._player._compute_offsets()
        self._refresh_grid()
        self._refresh_all_voice_display()
        self._refresh_track_list()
        self._refresh_pad_list()

    def _on_quant_select(self, event):
        self._player.quant_idx = self._quant_list.GetSelection()
        self._apply_quant()

    def _apply_quant(self):
        row       = self._cur_row
        quant_idx = self._quant_list.GetSelection()
        self._player.quant_idx = quant_idx
        self._player.apply_quant_row(quant_idx, row)
        pad = self._player._pattern._curpattern[self._player._cur_track][row][0]
        for c in range(self.COLS):
            self._cells[row][c].SetValue(bool(pad[c]))
        self._show_status(f"Ligne {row + 1}: {DrumPlayer.QUANT_LIST[quant_idx]} coché")

    def _quantize_pattern(self):
        self._player.apply_quant_to_pattern()
        self._refresh_grid()
        self._show_status(f"Pattern quantisé: {DrumPlayer.QUANT_LIST[self._player.quant_idx]}")

    def _gen_row_dialog(self):
        dlg    = GenRowDialog(self, self._cur_row, self._player.quant_idx, self.ROWS)
        result = dlg.ShowModal()
        if result in (wx.ID_OK, wx.ID_APPLY):
            row       = dlg.get_row()
            quant_idx = dlg.get_quant_idx()
            self._player.quant_idx    = quant_idx
            self._quant_list.SetSelection(quant_idx)
            if result == wx.ID_APPLY:
                self._player.apply_quant_row(quant_idx, row)
                pad = self._player._pattern._curpattern[self._player._cur_track][row][0]
                for c in range(self.COLS):
                    self._cells[row][c].SetValue(bool(pad[c]))
                self._show_status(
                    f"Ligne {row + 1}: {DrumPlayer.QUANT_LIST[quant_idx]} généré"
                )
            else:
                self._show_status(
                    f"Défaut: ligne {row + 1}, quant {DrumPlayer.QUANT_LIST[quant_idx]}"
                )
        dlg.Destroy()

    def _show_keyboard_help(self):
        dlg = KeyboardHelpDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def _quantize_pattern_dialog(self):
        dlg    = QuantizeDialog(self, self._player.quant_idx, self._player._quant_in_recording)
        result = dlg.ShowModal()
        if result in (wx.ID_OK, wx.ID_APPLY):
            idx = dlg.get_selection()   # -1 = None, 0..13 = résolution
            self._player._quant_in_recording = dlg.get_quant_in_recording()
            self._player.quant_idx = idx   # -1 (None) ou 0..13
            if idx >= 0:
                self._quant_list.SetSelection(idx)
            else:
                self._quant_list.SetSelection(wx.NOT_FOUND)
            if result == wx.ID_APPLY and idx >= 0:
                self._player.apply_quant_to_pattern()
                self._refresh_grid()
                self._show_status(f"Pattern quantisé: {DrumPlayer.QUANT_LIST[idx]}")
            elif idx >= 0:
                self._show_status(f"Quant par défaut: {DrumPlayer.QUANT_LIST[idx]}")
            else:
                self._show_status("Quant: désactivée")
        dlg.Destroy()

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
        self._midi.close()
        event.Skip()

    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Mode Keyboard
    # ------------------------------------------------------------------

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
                import threading
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

    def _assign_track_slot(self):
        """Ctrl+T : assigne le slot courant à la piste courante."""
        track_idx = self._player._cur_track
        slot_idx  = self._cur_slot
        self._router.assign_slot(track_idx, slot_idx)
        self._refresh_track_list()
        slot = self._rack.get_slot(slot_idx)
        self._show_status(
            f"Piste {track_idx + 1} → Slot_{slot_idx + 1:02d} ({slot.name})"
        )

    def _track_properties_dialog(self):
        """Ctrl+Shift+T : propriétés de la piste courante."""
        tidx = self._player._cur_track
        orig = dict(
            slot   = self._router.slot_for_track(tidx),
            volume = self._router.get_track_volume(tidx),
            pan    = self._router.get_track_pan(tidx),
            mute   = self._router._track_mutes[tidx],
            solo   = self._router._track_solos[tidx],
        )

        def apply(slot, vol, pan, mute, solo):
            if slot != self._router.slot_for_track(tidx):
                self._router.assign_slot(tidx, slot)
                self._cur_slot = slot
                self._slot_choice.SetSelection(slot)
            self._router.set_track_volume(tidx, vol)
            self._router.set_track_pan(tidx, pan)
            self._router._track_mutes[tidx] = mute
            self._router._track_solos[tidx] = solo
            self._refresh_track_list()

        def play_toggle():
            if self._player.playing:
                self._player.stop_pattern()
            else:
                self._player.play_pattern()

        dlg    = TrackPropertiesDialog(
            self, tidx, self._rack,
            orig['slot'], orig['volume'], orig['pan'], orig['mute'], orig['solo'],
            on_change=apply, on_play_toggle=play_toggle,
        )
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            apply(dlg.get_slot_idx(), dlg.get_volume(), dlg.get_pan(),
                  dlg.get_mute(), dlg.get_solo())
            self._show_status(f"Piste {tidx + 1}: propriétés mises à jour")
        else:
            apply(orig['slot'], orig['volume'], orig['pan'], orig['mute'], orig['solo'])
            self._show_status(f"Piste {tidx + 1}: modifications annulées")
        dlg.Destroy()

    def _track_label(self, idx):
        slot_idx  = self._router.slot_for_track(idx)
        slot_name = self._router.slot_name(idx)
        label = f"Track_{idx + 1:02d} - Slot_{slot_idx + 1:02d} - {slot_name}"
        if self._player._cur_track == idx and self._player.recording:
            label += " [REC]"
        if self._router._track_mutes[idx]:
            label += " [M]"
        if self._router._track_solos[idx]:
            label += " [S]"
        return label

    def _refresh_track_list(self):
        sel = self._track_list.GetSelection()
        self._track_list.Set([self._track_label(i) for i in range(8)])
        self._track_list.SetSelection(sel if sel != wx.NOT_FOUND else 0)

    def _on_track_list_activate(self, event):
        """Alt+Entrée ou double-clic sur la liste des pistes → propriétés."""
        if wx.GetKeyState(wx.WXK_ALT):
            self._track_properties_dialog()
        else:
            self._play(self._cur_row)

    def _on_pattern_list_activate(self, event):
        """Alt+Entrée ou double-clic sur la liste des patterns → propriétés."""
        if wx.GetKeyState(wx.WXK_ALT):
            self._pattern_properties_dialog()
        else:
            self._play(self._cur_row)

    def _on_listbox_play_activate(self, event):
        """Enter/double-clic sur une listbox sans handler spécifique → joue le pad courant."""
        self._play(self._cur_row)

    def _on_pad_select(self, event):
        idx = self._pad_list.GetSelection()
        if idx < 0:
            return
        self._cur_row = idx

    def _on_pad_list_key_nav(self, event):
        """Appelé après navigation clavier dans la liste des Pads (autoplay)."""
        idx = self._pad_list.GetSelection()
        if idx < 0:
            return
        self._cur_row = idx
        if self._autoplay:
            self._play(idx)

    def _on_pad_list_activate(self, event):
        """Enter/double-clic → joue le pad; Alt+Entrée → PadPropertiesDialog."""
        if wx.GetKeyState(wx.WXK_ALT):
            self._pad_properties_dialog()
        else:
            self._play(self._cur_row)

    def _pad_label(self, pad_idx):
        name = self._player.voice_manager.get_name(pad_idx)
        if name:
            return f"Pad_{pad_idx + 1:02d} - {name}"
        return f"Pad_{pad_idx + 1:02d}"

    def _refresh_pad_list(self):
        sel = self._pad_list.GetSelection()
        self._pad_list.Set([self._pad_label(i) for i in range(self.ROWS)])
        self._pad_list.SetSelection(sel if sel != wx.NOT_FOUND else 0)

    def _pad_properties_dialog(self):
        pad_idx = self._cur_row
        vm      = self._player.voice_manager
        v       = vm.get_voice(pad_idx)
        orig    = dict(
            volume      = v.volume,
            pan         = v.pan,
            mute        = v.mute,
            solo        = v.solo,
            duration_ms = v.duration_ms,
        )

        def apply(vol, pan, mute, solo, dur):
            vm.set_volume(pad_idx, vol)
            vm.set_pan(pad_idx, pan)
            vm.set_mute(pad_idx, mute)
            vm.set_solo(pad_idx, solo)
            vm.set_duration_ms(pad_idx, dur)
            self._refresh_voice_display(pad_idx)

        def play_pad():
            self._play(pad_idx)

        def play_toggle():
            if self._player.playing:
                self._player.stop_pattern()
            else:
                self._player.play_pattern()

        dlg = PadPropertiesDialog(
            self, pad_idx,
            orig['volume'], orig['pan'],
            orig['mute'], orig['solo'], orig['duration_ms'],
            on_change=apply, on_play=play_pad, on_play_toggle=play_toggle,
        )
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            apply(dlg.get_volume(), dlg.get_pan(),
                  dlg.get_mute(), dlg.get_solo(), dlg.get_duration_ms())
            self._show_status(f"Pad {pad_idx + 1}: propriétés mises à jour")
        else:
            apply(orig['volume'], orig['pan'],
                  orig['mute'], orig['solo'], orig['duration_ms'])
            self._show_status(f"Pad {pad_idx + 1}: modifications annulées")
        dlg.Destroy()

    def _pattern_properties_dialog(self):
        """Alt+Entrée depuis la liste des patterns : propriétés du pattern courant."""
        pat  = self._pattern_list[self._cur_pattern_idx]
        live = self._player._pattern

        def play_toggle():
            if self._player.playing:
                self._player.stop_pattern()
            else:
                self._player.play_pattern()

        dlg = PatternPropertiesDialog(
            self,
            self._cur_pattern_idx,
            pat._name,
            pat._start_bar,
            live._num_bars,
            live._num_steps,
            pat._looping,
            Pattern.MAX_BARS,
            Pattern.VALID_NUM_STEPS,
            on_play_toggle=play_toggle,
        )
        result = dlg.ShowModal()

        if result == wx.ID_OK:
            name      = dlg.get_name()
            start_bar = dlg.get_start_bar()
            num_bars  = dlg.get_num_bars()
            num_steps = dlg.get_num_steps()
            looping   = dlg.get_looping()
            action    = dlg.get_action()

            pat._name      = name
            pat._start_bar = start_bar
            pat._looping   = looping
            live._looping  = looping

            if action == "Nouveau":
                pat.new_pattern(num_bars, num_steps)
                live.new_pattern(num_bars, num_steps)
                self._player._compute_offsets()
                self._refresh_grid()
                self._show_status(f"Pattern {self._cur_pattern_idx + 1:02d}: nouveau")
            elif action == "Doubler":
                if self._player.double_pattern():
                    pat.load_pattern(live._curpattern)
                    self._refresh_grid()
                    self._show_status(
                        f"Pattern {self._cur_pattern_idx + 1:02d}: doublé — {live._num_bars} mesures"
                    )
                else:
                    self._show_status("Impossible de doubler (limite atteinte)")
            elif action == "Diviser par 2":
                if self._player.halve_pattern():
                    pat.load_pattern(live._curpattern)
                    self._refresh_grid()
                    self._show_status(
                        f"Pattern {self._cur_pattern_idx + 1:02d}: divisé — {live._num_bars} mesures"
                    )
                else:
                    self._show_status("Impossible de diviser (1 mesure minimum)")
            else:  # "Courant"
                self._resize_live_pattern(num_bars, num_steps)
                self._refresh_grid()
                self._show_status(f"Pattern {self._cur_pattern_idx + 1:02d}: mis à jour")

            self._refresh_pattern_listbox()

        dlg.Destroy()

    def _resize_live_pattern(self, num_bars, num_steps):
        live = self._player._pattern
        live.resize(num_bars, num_steps)
        self._pattern_list[self._cur_pattern_idx].load_pattern(live._curpattern)
        self._player._compute_offsets()

    def _on_track_select(self, event):
        idx = self._track_list.GetSelection()
        if idx < 0:   # EVT_LISTBOX peut se déclencher avec NO_SELECTION sur GTK
            return
        if self._player.recording or self._player._count_in > 0:
            self._track_list.SetSelection(self._player._cur_track)
            self._show_status("Changement de piste interdit pendant l'enregistrement")
            return
        self._player._cur_track = idx
        self._cur_slot = self._router.slot_for_track(idx)
        self._slot_choice.SetSelection(self._cur_slot)
        self._router.reset_kit_pad()
        self._refresh_grid()
        slot = self._rack.get_slot(self._cur_slot)
        self._show_status(f"Piste {idx + 1} — {slot.name}")
        if slot.type == InstrumentType.SYNTH:
            self._router.load_slot_preview(self._cur_slot)
        elif slot.type == InstrumentType.KIT:
            self._load_kit_slot(self._cur_slot)

    def _on_slot_choice(self, event):
        """Changement de slot : preview uniquement, sans modifier l'assignation de la piste.
        Appuyer Ctrl+T pour confirmer l'assignation."""
        self._cur_slot = self._slot_choice.GetSelection()
        slot = self._rack.get_slot(self._cur_slot)
        if slot.is_empty:
            self._show_status(f"Slot {self._cur_slot + 1:02d}: vide — Alt+X pour charger")
        else:
            self._show_status(f"Slot {self._cur_slot + 1:02d}: {slot.name} (Ctrl+T pour assigner)")
            if slot.type == InstrumentType.SYNTH:
                self._router.load_slot_preview(self._cur_slot)
            elif slot.type == InstrumentType.KIT:
                self._load_kit_slot(self._cur_slot)

    def _update_slot_list(self):
        self._slot_choice.Set(self._rack.labels())
        self._slot_choice.SetSelection(self._cur_slot)

    def _debug_pad_status(self, pad_idx, midi_note_in=None):
        """Affiche pad, note MIDI et shift dans la barre de status et le terminal."""
        slot = self._rack.get_slot(self._cur_slot)
        parts = [f"Pad {pad_idx + 1}"]
        if midi_note_in is not None:
            parts.append(f"MIDI in: {midi_note_in}")
        if slot.type == InstrumentType.KIT and self._snd.note_map:
            # MIDI in → note kit directe ; numpad → dérivée du pad dans la fenêtre
            kit_note = midi_note_in if midi_note_in is not None \
                       else self._snd.kit_base + self._snd.kit_offset + pad_idx
            parts.append(f"kit_note: {kit_note}")
        parts.append(f"shift_pad: {self._shift_pad}")
        msg = " | ".join(parts)
        print(msg)
        self._show_status(msg)

    def _kit_status(self):
        """Retourne la chaîne de status du kit courant."""
        base   = self._snd.kit_base + self._snd.kit_offset
        offset = self._snd.kit_offset
        sign   = f"+{offset}" if offset >= 0 else str(offset)
        return (f"Kit: {self._snd._kit_name} | "
                f"Pads 1-16 → notes {base}–{base + 15} | "
                f"shift: {sign}")

    def _shift_kit(self, delta):
        """Décale la fenêtre de 16 sons du kit courant de delta demi-tons."""
        new_labels = self._snd.shift_kit(delta)
        for i, label in enumerate(new_labels):
            self._player.voice_manager.set_name(i, label)
        self._refresh_pad_list()
        msg = self._kit_status()
        print(msg)
        self._show_status(msg)

    def _load_kit_slot(self, slot_idx):
        """Charge le kit JSON du slot KIT donné et met à jour les sons et les noms de pads.
        Fallback sur les sons media/ si le JSON est absent ou invalide."""
        slot = self._rack.get_slot(slot_idx)
        if slot.type != InstrumentType.KIT:
            return
        kit_path = slot.config.get("kit", "")
        if kit_path and os.path.isfile(kit_path):
            try:
                labels, wav_paths = self._snd.load_kit(kit_path)
                self._media_lst = wav_paths
                for i, label in enumerate(labels):
                    self._player.voice_manager.set_name(i, label)
                self._refresh_pad_list()
                self._show_status(self._kit_status())
                return
            except Exception as e:
                self._show_status(f"Erreur kit JSON: {e}")
        # Fallback : sons media/ numérotés
        self._snd.load_sounds()
        self._show_status("Kit: sons media par défaut")

    def _open_explorer(self):
        start = self._patches_dir if os.path.isdir(self._patches_dir) \
                else (self._synths_dir if os.path.isdir(self._synths_dir) else os.path.expanduser("~"))
        dlg = wx.FileDialog(self, "Choisir un fichier patch (*.json)",
                            defaultDir=start,
                            wildcard="Patch JSON (*.json)|*.json",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            json_path  = dlg.GetPath()
            patch_name = os.path.splitext(os.path.basename(json_path))[0]
            self._rack.set_slot(self._cur_slot, InstrumentType.SYNTH,
                                patch_name, {"patch": json_path})
            self._update_slot_list()
            self._router.load_slot_preview(self._cur_slot)
        dlg.Destroy()

    def _refresh_voice_display(self, pad_idx):
        vm = self._player.voice_manager
        v  = vm.get_voice(pad_idx)
        self._mute_btns[pad_idx].SetValue(v.mute)
        self._solo_btns[pad_idx].SetValue(v.solo)
        self._vol_ctrls[pad_idx].SetValue(v.volume)
        self._pan_ctrls[pad_idx].SetValue(v.pan)

    def _on_vol_spin(self, pad_idx):
        val = self._vol_ctrls[pad_idx].GetValue()
        self._player.voice_manager.set_volume(pad_idx, val)
        self._show_status(f"Pad {pad_idx + 1}: Volume {val}")

    def _on_pan_spin(self, pad_idx):
        val = self._pan_ctrls[pad_idx].GetValue()
        self._player.voice_manager.set_pan(pad_idx, val)
        self._show_status(f"Pad {pad_idx + 1}: Pan {val}")

    def _refresh_all_voice_display(self):
        for r in range(self.ROWS):
            self._refresh_voice_display(r)

    def _on_mute_btn(self, pad_idx):
        muted = self._player.voice_manager.toggle_mute(pad_idx)
        self._mute_btns[pad_idx].SetValue(muted)
        self._show_status(f"Pad {pad_idx + 1}: Mute {'On' if muted else 'Off'}")

    def _on_solo_btn(self, pad_idx):
        soloed = self._player.voice_manager.toggle_solo(pad_idx)
        self._solo_btns[pad_idx].SetValue(soloed)
        self._show_status(f"Pad {pad_idx + 1}: Solo {'On' if soloed else 'Off'}")

    def _show_status(self, msg):
        focused = wx.Window.FindFocus()
        self._status_ctrl.SetValue(msg)
        if focused:
            wx.CallAfter(focused.SetFocus)

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

    def _play_kit_pitched(self, note_idx):
        last    = self._player.last_played_pad
        pad_idx = last if last is not None else (self._cur_row + self._shift_pad)
        wav_path = self._media_lst[pad_idx] if pad_idx < len(self._media_lst) else None
        self._router.play_kit_pitched(
            note_idx, pad_idx, wav_path, self._player.play_sound
        )

    def _nr_arm_release(self):
        if self._nr_release_timer:
            self._nr_release_timer.cancel()
        import threading as _t
        self._nr_release_timer = _t.Timer(
            0.050, lambda: wx.CallAfter(setattr, self, '_nr_active_key', None)
        )
        self._nr_release_timer.start()

    def _nr_cancel_release(self):
        if self._nr_release_timer:
            self._nr_release_timer.cancel()
            self._nr_release_timer = None

    def _on_tab_order(self, shift):
        """
        Navigue vers le widget suivant ou précédent de self._tab_order.
        Quand le focus est sur la grille (ou un widget hors liste) :
          Tab       → premier widget de la liste
          Shift+Tab → dernier widget de la liste
        Aux extrémités de la liste :
          Tab depuis le dernier  → grille
          Shift+Tab depuis le premier → grille
        """
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
        self._key_manager.handle(event)

