import wx

from midi.midi_constants import GM_PATCH_NAMES, GM2_DRUMKITS
from pattern import Pattern


class TrackPropertiesDialog(wx.Dialog):
    _LIST_H = 90   # hauteur fixe de la liste des canaux

    def __init__(self, parent, track_idx, rack, cur_slot_idx, volume, pan, mute, solo,
                 on_change=None, on_play_toggle=None, channel=0, channel_after_slot=None,
                 slot_program=None, slot_gm_tuning=None, bank_info=None):
        """channel : canal MIDI 0..15 de la piste. channel_after_slot(slot_idx,
        channel) -> canal : règle appliquée quand l'utilisateur change de slot
        (kit → canal 10, Phase 7 étape 10f1) ; None = canal inchangé.
        slot_program(slot_idx) -> (genre, programme) : genre "synth"
        (instruments GM), "kit" (kits GM2) ou None (liste désactivée) —
        Phase 7 étape 10h3 ; None = liste toujours désactivée.
        slot_gm_tuning(slot_idx) -> (transposition, gain_db) du slot pour
        l'export GM, chacun None si le réglage ne s'applique pas (SpinCtrl
        grisé) — Phase 7 étape 12h1, docs/DESIGN.md § 12a2 D6 ; None = les
        deux grisés.
        bank_info(slot_idx, channel, msb, lsb) -> None (slot non Banque) ou
        dict names (128 noms ou None), program, msb, lsb (instrument du
        canal si msb est None : le canal impose son instrument), drums
        (canal 10), gs (mode Bank Select GS) — Phase 7 étape 17h1,
        docs/DESIGN.md § 17e3 O5 ; None = jamais de banque."""
        super().__init__(parent, title=f"Propriétés — Piste {track_idx + 1}")

        self._on_change          = on_change
        self._on_play_toggle     = on_play_toggle
        self._channel_after_slot = channel_after_slot
        self._slot_program       = slot_program
        self._program_values     = []   # programme de chaque entrée de la liste
        self._slot_gm_tuning     = slot_gm_tuning
        self._bank_info          = bank_info
        self._is_bank            = False

        # Ordre Tab : Mute → Solo → Slots → Canal → Programme → Banque MSB
        # → Banque LSB → Transposition → Gain → Volume → Pan
        self._mute = wx.CheckBox(self, label="Mute")
        self._mute.SetValue(mute)
        self._solo = wx.CheckBox(self, label="Solo")
        self._solo.SetValue(solo)

        slot_label  = wx.StaticText(self, label="Slot :")
        self._slots = wx.ListBox(self, choices=rack.labels(), style=wx.LB_SINGLE)
        self._slots.SetSelection(cur_slot_idx)

        channel_label  = wx.StaticText(self, label="Canal :")
        self._channels = wx.ListBox(
            self,
            choices=[f"Canal {c + 1}" for c in range(16)],
            style=wx.LB_SINGLE,
            size=(-1, self._LIST_H),
        )
        self._channels.SetSelection(channel)

        self._program_label = wx.StaticText(self, label="Programme GM du slot :")
        self._programs = wx.ListBox(self, style=wx.LB_SINGLE, size=(-1, self._LIST_H))

        # Banque MSB (CC0) / LSB (CC32) du canal, slot Banque seulement
        # (17h1) ; grisés au canal 10 (batterie, banque 128)
        msb_label      = wx.StaticText(self, label="Banque MSB (CC0) :")
        self._msb      = wx.SpinCtrl(self, min=0, max=127, initial=0)
        self._msb.SetName("Banque MSB")
        self._lsb_label = wx.StaticText(self, label="Banque LSB (CC32) :")
        self._lsb      = wx.SpinCtrl(self, min=0, max=127, initial=0)
        self._lsb.SetName("Banque LSB")
        self._load_programs(cur_slot_idx)

        transpose_label  = wx.StaticText(self, label="Transposition GM du slot (demi-tons) :")
        self._transpose  = wx.SpinCtrl(self, min=-24, max=24, initial=0)
        gain_label       = wx.StaticText(self, label="Gain GM du slot (dB) :")
        self._gain       = wx.SpinCtrl(self, min=-40, max=0, initial=0)
        self._load_gm_tuning(cur_slot_idx)

        vol_label  = wx.StaticText(self, label="Volume :")
        self._vol  = wx.SpinCtrl(self, min=0, max=100, initial=volume)

        pan_label  = wx.StaticText(self, label="Pan :")
        self._pan  = wx.SpinCtrl(self, min=-100, max=100, initial=pan)

        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        check_sizer = wx.BoxSizer(wx.HORIZONTAL)
        check_sizer.Add(self._mute, 0, wx.RIGHT, 16)
        check_sizer.Add(self._solo, 0)

        grid = wx.FlexGridSizer(rows=2, cols=2, vgap=6, hgap=8)
        grid.Add(vol_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._vol,  0, wx.EXPAND)
        grid.Add(pan_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._pan,  0, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(slot_label,  0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        vbox.Add(self._slots, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(channel_label,  0, wx.LEFT | wx.RIGHT, 8)
        vbox.Add(self._channels, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(self._program_label, 0, wx.LEFT | wx.RIGHT, 8)
        vbox.Add(self._programs, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        bank = wx.FlexGridSizer(rows=2, cols=2, vgap=6, hgap=8)
        bank.Add(msb_label,       0, wx.ALIGN_CENTER_VERTICAL)
        bank.Add(self._msb,       0, wx.EXPAND)
        bank.Add(self._lsb_label, 0, wx.ALIGN_CENTER_VERTICAL)
        bank.Add(self._lsb,       0, wx.EXPAND)
        vbox.Add(bank, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        tuning = wx.FlexGridSizer(rows=2, cols=2, vgap=6, hgap=8)
        tuning.Add(transpose_label, 0, wx.ALIGN_CENTER_VERTICAL)
        tuning.Add(self._transpose, 0, wx.EXPAND)
        tuning.Add(gain_label,      0, wx.ALIGN_CENTER_VERTICAL)
        tuning.Add(self._gain,      0, wx.EXPAND)
        vbox.Add(tuning, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(check_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(grid,        0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(btn_sizer,   0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()

        # Aperçu en temps réel
        self._mute.Bind(wx.EVT_CHECKBOX, self._on_widget_change)
        self._solo.Bind(wx.EVT_CHECKBOX, self._on_widget_change)
        self._slots.Bind(wx.EVT_LISTBOX, self._on_slot_change)
        self._channels.Bind(wx.EVT_LISTBOX, self._on_channel_change)
        self._programs.Bind(wx.EVT_LISTBOX, self._on_widget_change)
        self._msb.Bind(wx.EVT_SPINCTRL, self._on_bank_change)
        self._lsb.Bind(wx.EVT_SPINCTRL, self._on_bank_change)
        self._transpose.Bind(wx.EVT_SPINCTRL, self._on_widget_change)
        self._gain.Bind(wx.EVT_SPINCTRL,      self._on_widget_change)
        self._vol.Bind(wx.EVT_SPINCTRL,  self._on_widget_change)
        self._pan.Bind(wx.EVT_SPINCTRL,  self._on_widget_change)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        self._mute.SetFocus()

    def _load_programs(self, slot_idx):
        """Remplit la liste des programmes selon le genre du slot :
        programmes de la banque du canal (slot Banque, 17h1), 128
        instruments GM (synthé), kits GM2 (kit), vide et désactivée sinon."""
        info = self._bank_info(slot_idx, self._channels.GetSelection(), None, None) \
            if self._bank_info else None
        self._is_bank = info is not None
        if self._is_bank:
            self._msb.SetValue(info["msb"])
            self._lsb.SetValue(info["lsb"])
            self._show_bank(info, info["program"])
            return
        self._program_label.SetLabel("Programme GM du slot :")
        self._msb.Enable(False)
        self._lsb.Enable(False)
        kind, program = self._slot_program(slot_idx) if self._slot_program else (None, None)
        if kind == "synth":
            entries = list(enumerate(GM_PATCH_NAMES))
        elif kind == "kit":
            entries = GM2_DRUMKITS
        else:
            entries = []
        self._program_values = [p for p, _ in entries]
        self._programs.Set([f"{p + 1} - {n}" for p, n in entries])
        if program in self._program_values:
            self._programs.SetSelection(self._program_values.index(program))
        self._programs.Enable(bool(entries))

    def _show_bank(self, info, program):
        """Liste des 128 programmes de la banque du canal (noms lus dans le
        fichier, « (vide) » pour un numéro absent), MSB / LSB grisés au
        canal 10."""
        channel = self._channels.GetSelection()
        self._program_label.SetLabel(f"Programme du canal {channel + 1} :")
        self._program_values = list(range(128))
        self._programs.Set([f"{p + 1} - {name or '(vide)'}"
                            for p, name in enumerate(info["names"])])
        if program is not None:
            self._programs.SetSelection(max(0, min(127, program)))
        self._programs.Enable(True)
        self._msb.Enable(not info["drums"])
        self._lsb.Enable(not info["drums"])
        self._lsb_label.SetLabel("Banque LSB (CC32, sans effet en mode GS) :"
                                 if info["gs"] else "Banque LSB (CC32) :")

    def _on_channel_change(self, event):
        """Changement de canal : sur une banque, le canal impose son
        instrument (§ 17e3 O5, choix B) — liste, MSB et LSB rechargés."""
        if self._is_bank:
            self._load_programs(self._slots.GetSelection())
        self._on_widget_change(event)

    def _on_bank_change(self, event):
        """MSB / LSB changés : liste de la nouvelle banque, même programme."""
        if self._is_bank:
            info = self._bank_info(self._slots.GetSelection(), self._channels.GetSelection(),
                                   self._msb.GetValue(), self._lsb.GetValue())
            self._show_bank(info, self._programs.GetSelection())
        self._on_widget_change(event)

    def _load_gm_tuning(self, slot_idx):
        """Valeurs et grisage des SpinCtrl Transposition et Gain selon le
        slot (Phase 7 étape 12h1) : un réglage None est grisé, à 0."""
        transpose, gain = self._slot_gm_tuning(slot_idx) if self._slot_gm_tuning else (None, None)
        for ctrl, value in ((self._transpose, transpose), (self._gain, gain)):
            ctrl.SetValue(value if value is not None else 0)
            ctrl.Enable(value is not None)

    def _on_slot_change(self, event):
        """Changement de slot : règle du canal (kit → 10), liste des
        programmes du nouveau slot, puis aperçu."""
        slot_idx = self._slots.GetSelection()
        if self._channel_after_slot:
            self._channels.SetSelection(self._channel_after_slot(
                slot_idx, self._channels.GetSelection()))
        self._load_programs(slot_idx)      # après le canal : instrument du canal (17h1)
        self._load_gm_tuning(slot_idx)
        self._on_widget_change(event)

    def _on_widget_change(self, event):
        if self._on_change:
            self._on_change(
                self._slots.GetSelection(),
                self._vol.GetValue(),
                self._pan.GetValue(),
                self._mute.GetValue(),
                self._solo.GetValue(),
                self._channels.GetSelection(),
                self.get_program(),
                self.get_transpose(),
                self.get_gain_db(),
                self.get_msb(),
                self.get_lsb(),
            )
        event.Skip()

    def _on_key(self, event):
        if event.ControlDown() and event.GetKeyCode() == ord('P'):
            if self._on_play_toggle:
                self._on_play_toggle()
        else:
            event.Skip()

    def get_slot_idx(self): return self._slots.GetSelection()
    def get_volume(self):   return self._vol.GetValue()
    def get_pan(self):      return self._pan.GetValue()
    def get_mute(self):     return self._mute.GetValue()
    def get_solo(self):     return self._solo.GetValue()
    def get_channel(self):  return self._channels.GetSelection()

    def get_program(self):
        """Programme sélectionné (0-127), None si la liste est vide ou sans sélection."""
        sel = self._programs.GetSelection()
        return self._program_values[sel] if 0 <= sel < len(self._program_values) else None

    def get_transpose(self):
        """Transposition GM en demi-tons, None si grisée (slot non synthé)."""
        return self._transpose.GetValue() if self._transpose.IsEnabled() else None

    def get_gain_db(self):
        """Gain GM en dB, None si grisé (slot vide)."""
        return self._gain.GetValue() if self._gain.IsEnabled() else None

    def get_msb(self):
        """Banque MSB du canal (slot Banque, 17h1), None sinon."""
        return self._msb.GetValue() if self._is_bank else None

    def get_lsb(self):
        """Banque LSB du canal (slot Banque, 17h1), None sinon."""
        return self._lsb.GetValue() if self._is_bank else None


class PatternPropertiesDialog(wx.Dialog):
    _LIST_H  = 90   # hauteur fixe des ListBox à contenu long
    _ACTIONS = ["Courant", "Nouveau", "Doubler", "Diviser par 2"]

    # Signature et résolution (Phase 7 étape 20d1, docs/DESIGN.md § 20a1 S2,
    # S4, S7) : valeur du temps = dénominateur ; résolution = pas par ronde
    DENOMINATORS     = (2, 4, 8, 16)
    DENOMINATOR_NAMES = {2: "blanche", 4: "noire", 8: "croche", 16: "double croche"}
    RESOLUTION_NAMES  = {16: "double croche", 32: "triple croche",
                         64: "quadruple croche", 128: "quintuple croche"}

    def __init__(self, parent, pat_idx, name, start_bar, num_bars, num_steps,
                 looping, max_bars, valid_steps, on_play_toggle=None,
                 num_beats=4, denominator=4, tempo=120, on_tempo_change=None,
                 on_signature_change=None):
        """valid_steps : résolutions proposées (pas par ronde, 16 … 128) ;
        num_steps : pas par mesure actuels (la résolution s'en déduit avec la
        signature num_beats / denominator)."""
        super().__init__(parent, title=f"Propriétés — Pattern {pat_idx + 1:02d}")

        self._on_play_toggle = on_play_toggle
        self._max_bars       = max_bars
        self._resolutions    = list(valid_steps)
        self._sig            = (num_beats, denominator)   # signature affichée
        # Durée en pas (à la résolution d'ouverture), gardée exacte quand la
        # signature change en plusieurs étapes (6/4 puis 6/8)
        self._total_steps    = num_bars * num_steps

        # Ordre Tab : Nom → Début → Longueur → Tempo → Temps par mesure →
        # Valeur du temps → Résolution → Boucler → Actions

        name_label  = wx.StaticText(self, label="Nom :")
        self._name  = wx.TextCtrl(self, value=name)

        start_label  = wx.StaticText(self, label="Début :")
        self._start  = wx.ListBox(
            self,
            choices=[f"Mesure {i + 1}" for i in range(num_bars)],
            style=wx.LB_SINGLE,
            size=(-1, self._LIST_H),
        )
        self._start.SetSelection(min(start_bar, num_bars - 1))

        length_label  = wx.StaticText(self, label="Longueur :")
        self._length  = wx.ListBox(
            self,
            choices=[str(i) for i in range(1, max_bars + 1)],
            style=wx.LB_SINGLE,
            size=(-1, self._LIST_H),
        )
        self._length.SetSelection(num_bars - 1)
        self._length.Bind(wx.EVT_LISTBOX, self._on_length_change)

        # Tempo de départ, arrondi (Phase 7 étape 20e3, § 20e2 P1) : le
        # modifier change tous les tempos dans la même proportion
        tempo_label  = wx.StaticText(self, label="Tempo (BPM) :")
        self._tempo_initial = int(round(tempo))
        self._tempo  = wx.SpinCtrl(self, min=1, max=600, initial=self._tempo_initial,
                                   size=(80, -1))
        self._tempo.SetName("Tempo (BPM)")
        # Tempo entendu en direct, click compris (demandé à l'essai de 20e3) ;
        # on_tempo_change(bpm) — la fenêtre rétablit l'origine si Annuler
        self._on_tempo_change = on_tempo_change
        # Signature entendue en direct aussi (demandé à l'essai de 20e3) ;
        # on_signature_change(num, den)
        self._on_sig_change   = on_signature_change
        self._tempo.Bind(wx.EVT_SPINCTRL, self._on_tempo_spin)

        beats_label  = wx.StaticText(self, label="Signature, temps par mesure :")
        self._beats  = wx.SpinCtrl(self, min=1, max=16, initial=num_beats, size=(80, -1))
        self._beats.SetName("Signature, temps par mesure")
        den_label    = wx.StaticText(self, label="Signature, valeur du temps :")
        self._den    = wx.ListBox(
            self,
            choices=[f"{d} ({self.DENOMINATOR_NAMES[d]})" for d in self.DENOMINATORS],
            style=wx.LB_SINGLE,
        )
        self._den.SetSelection(self.DENOMINATORS.index(denominator))

        steps_label  = wx.StaticText(self, label="Résolution :")
        self._steps  = wx.ListBox(
            self,
            choices=[f"1/{r} ({self.RESOLUTION_NAMES.get(r, '')})" for r in self._resolutions],
            style=wx.LB_SINGLE,
        )
        resolution = round(num_steps * denominator / num_beats)
        self._steps.SetSelection(self._resolutions.index(resolution)
                                 if resolution in self._resolutions else 0)
        self._beats.Bind(wx.EVT_SPINCTRL, self._on_signature_change)
        self._den.Bind(wx.EVT_LISTBOX, self._on_signature_change)

        self._loop = wx.CheckBox(self, label="Boucler")
        self._loop.SetValue(looping)

        action_label   = wx.StaticText(self, label="Action :")
        self._actions  = wx.ListBox(
            self,
            choices=self._ACTIONS,
            style=wx.LB_SINGLE,
            size=(-1, self._LIST_H),
        )
        self._actions.SetSelection(0)   # "Courant" par défaut

        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        grid = wx.FlexGridSizer(rows=9, cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1)
        grid.Add(name_label,   0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._name,   0, wx.EXPAND)
        grid.Add(start_label,  0, wx.ALIGN_TOP | wx.TOP, 2)
        grid.Add(self._start,  0, wx.EXPAND)
        grid.Add(length_label, 0, wx.ALIGN_TOP | wx.TOP, 2)
        grid.Add(self._length, 0, wx.EXPAND)
        grid.Add(tempo_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._tempo,  0)
        grid.Add(beats_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._beats,  0)
        grid.Add(den_label,    0, wx.ALIGN_TOP | wx.TOP, 2)
        grid.Add(self._den,    0, wx.EXPAND)
        grid.Add(steps_label,  0, wx.ALIGN_TOP | wx.TOP, 2)
        grid.Add(self._steps,  0, wx.EXPAND)
        grid.Add(wx.StaticText(self, label=""), 0)
        grid.Add(self._loop,   0)
        grid.Add(action_label, 0, wx.ALIGN_TOP | wx.TOP, 2)
        grid.Add(self._actions, 0, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid,      0, wx.EXPAND | wx.ALL, 8)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()

        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self._name.SetFocus()

    def _on_length_change(self, event):
        self._set_length(event.GetSelection() + 1)
        self._total_steps = self.get_num_bars() * Pattern.steps_for(
            self.get_resolution(), *self._sig)

    def _set_length(self, new_bars):
        old_start = self._start.GetSelection()
        self._length.SetSelection(new_bars - 1)
        self._start.Set([f"Mesure {i + 1}" for i in range(new_bars)])
        self._start.SetSelection(min(old_start, new_bars - 1))

    def _on_signature_change(self, event):
        """Nouvelle signature : la longueur est recalculée pour garder la
        même durée (S3, comme Pattern.set_signature)."""
        new_sig = (self.get_num_beats(), self.get_denominator())
        if new_sig != self._sig:
            new = Pattern.steps_for(self.get_resolution(), *new_sig)
            self._set_length(max(1, min(self._max_bars, -(-self._total_steps // new))))
            self._sig = new_sig
            if self._on_sig_change:
                self._on_sig_change(*new_sig)
        event.Skip()

    def _on_key(self, event):
        if event.ControlDown() and event.GetKeyCode() == ord('P'):
            if self._on_play_toggle:
                self._on_play_toggle()
        else:
            event.Skip()

    def get_name(self):      return self._name.GetValue().strip()
    def get_start_bar(self): return self._start.GetSelection()          # 0-indexed
    def get_num_bars(self):  return self._length.GetSelection() + 1
    def _on_tempo_spin(self, event):
        if self._on_tempo_change:
            self._on_tempo_change(self._tempo.GetValue())
        event.Skip()

    def get_tempo(self):
        """Tempo choisi, ou None s'il n'a pas changé (§ 20e2 P2 : un départ
        décimal n'est pas arrondi)."""
        value = self._tempo.GetValue()
        return None if value == self._tempo_initial else value

    def get_num_beats(self):   return self._beats.GetValue()
    def get_denominator(self): return self.DENOMINATORS[max(0, self._den.GetSelection())]
    def get_resolution(self):  return self._resolutions[max(0, self._steps.GetSelection())]
    def get_num_steps(self):
        """Pas par mesure de la résolution et de la signature choisies."""
        return Pattern.steps_for(self.get_resolution(), self.get_num_beats(),
                                 self.get_denominator())
    def get_looping(self):   return self._loop.GetValue()
    def get_action(self):
        sel = self._actions.GetSelection()
        return self._ACTIONS[sel] if sel != wx.NOT_FOUND else "Courant"


class PadPropertiesDialog(wx.Dialog):
    def __init__(self, parent, pad_idx, volume, pan, mute, solo, duration_ms,
                 on_change=None, on_play=None, on_play_toggle=None):
        super().__init__(parent, title=f"Propriétés — Pad {pad_idx + 1}")

        self._on_change      = on_change
        self._on_play        = on_play
        self._on_play_toggle = on_play_toggle
        self._dur_prev       = duration_ms   # pour le pas directionnel de 100 ms

        # Ordre Tab : Mute/Solo → Volume → Pan → Durée
        self._mute = wx.CheckBox(self, label="Mute")
        self._mute.SetValue(mute)
        self._solo = wx.CheckBox(self, label="Solo")
        self._solo.SetValue(solo)

        vol_label = wx.StaticText(self, label="Volume :")
        self._vol = wx.SpinCtrl(self, min=0, max=100, initial=volume)

        pan_label = wx.StaticText(self, label="Pan :")
        self._pan = wx.SpinCtrl(self, min=-100, max=100, initial=pan)

        dur_label = wx.StaticText(self, label="Durée (ms) :")
        self._dur = wx.SpinCtrl(self, min=0, max=9900, initial=duration_ms)
        dur_hint  = wx.StaticText(self, label="(0 = fin du fichier WAV, pas de 100 ms)")

        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        check_sizer = wx.BoxSizer(wx.HORIZONTAL)
        check_sizer.Add(self._mute, 0, wx.RIGHT, 16)
        check_sizer.Add(self._solo, 0)

        grid = wx.FlexGridSizer(rows=3, cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1)
        grid.Add(vol_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._vol,  0, wx.EXPAND)
        grid.Add(pan_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._pan,  0, wx.EXPAND)
        grid.Add(dur_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._dur,  0, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(check_sizer, 0, wx.ALL, 8)
        vbox.Add(grid,        0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(dur_hint,    0, wx.LEFT | wx.BOTTOM, 8)
        vbox.Add(btn_sizer,   0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()

        self._mute.Bind(wx.EVT_CHECKBOX, self._on_check_change)
        self._solo.Bind(wx.EVT_CHECKBOX, self._on_check_change)
        self._vol.Bind(wx.EVT_SPINCTRL,  self._on_spin_change)
        self._pan.Bind(wx.EVT_SPINCTRL,  self._on_spin_change)
        self._dur.Bind(wx.EVT_SPINCTRL,  self._on_dur_spin)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        self._mute.SetFocus()

    def _notify_change(self):
        if self._on_change:
            self._on_change(
                self._vol.GetValue(),
                self._pan.GetValue(),
                self._mute.GetValue(),
                self._solo.GetValue(),
                self._dur.GetValue(),
            )

    def _on_check_change(self, event):
        self._notify_change()
        event.Skip()

    def _on_spin_change(self, event):
        self._notify_change()
        if self._on_play:
            self._on_play()
        event.Skip()

    def _on_dur_spin(self, event):
        """Pas de 100 ms : snap directionnel pour que flèche haut/bas avance de 100."""
        val  = self._dur.GetValue()
        prev = self._dur_prev
        if val > prev:
            snapped = ((val - 1) // 100 + 1) * 100   # arrondir vers le haut
        elif val < prev:
            snapped = (val // 100) * 100              # arrondir vers le bas
        else:
            snapped = val
        snapped = max(0, min(9900, snapped))
        self._dur_prev = snapped
        self._dur.SetValue(snapped)
        self._notify_change()
        if self._on_play:
            self._on_play()
        event.Skip()

    def _on_key(self, event):
        if event.ControlDown() and event.GetKeyCode() == ord('P'):
            if self._on_play_toggle:
                self._on_play_toggle()
        else:
            event.Skip()

    def get_volume(self):      return self._vol.GetValue()
    def get_pan(self):         return self._pan.GetValue()
    def get_mute(self):        return self._mute.GetValue()
    def get_solo(self):        return self._solo.GetValue()
    def get_duration_ms(self): return self._dur.GetValue()
