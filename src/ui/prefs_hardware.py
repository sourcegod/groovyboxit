#python3
"""
    File: src/ui/prefs_hardware.py
    Onglet Matériel des Préférences (Phase 8 étape 11f1, docs/DESIGN.md
    § Phase 8 étape 11a H2-H17) : pilote audio, entrées et sorties audio,
    sortie principale, entrées et sorties MIDI (listes à cases à cocher :
    les périphériques cochés sont ouverts au démarrage et proposés aux
    pistes), boutons Tester et Détecter, champ « Résultat du test » (le
    focus reste sur le bouton).
    Le matériel passe par un objet « hardware » (mw_devices.HardwareAccess
    dans l'appli, factice dans les tests) :
        hostapis(), default_hostapi(), audio_devices(pilote, sens),
        midi_inputs(), midi_outputs(), detect_audio(), detect_midi(),
        test_audio_output(pilote, nom), test_audio_input(pilote, nom, done),
        test_midi_output(nom), test_midi_input(nom, done)
    (les deux tests d'entrée rendent leur résultat plus tard par done(msg)).
    Ordre de Tab (H13) : Pilote, Entrées audio, Tester l'entrée, Sorties
    audio, Tester la sortie, Sortie principale, Détecter audio, Entrées MIDI,
    Tester l'entrée MIDI, Sorties MIDI, Tester la sortie MIDI, Détecter MIDI,
    Résultat du test, Valeurs par défaut. Chaque libellé est créé juste avant
    son champ (lu par Orca).
    Date: Wed, 11/11/2026
    Author: Coolbrother
"""
import wx

INPUT, OUTPUT = "input", "output"
MAIN_DEFAULT_LABEL = "Défaut du pilote"
ABSENT_SUFFIX = " — absent"


class _CheckList:
    """wx.CheckListBox dont les lignes portent un nom, précédées de
    « (Aucun) » (essai de 11f1 : GTK place le curseur sur la première ligne
    en entrant dans la liste, Tester écoutait alors une entrée non
    choisie). « (Aucun) » est coché quand rien d'autre ne l'est ; le cocher
    décoche tout ; Tester sur lui ne fait rien. Les noms cochés mais absents
    du système restent affichés (« — absent ») et cochés, pour ne pas les
    perdre (périphérique débranché)."""

    NONE_LABEL = "(Aucun)"

    def __init__(self, panel, on_change=None):
        """on_change() : appelé après chaque case cochée ou décochée, une fois
        « (Aucun) » mis à jour (la page y relit la sortie principale)."""
        self.ctrl = wx.CheckListBox(panel, size=(420, 90))
        self.names = []
        self._on_change = on_change
        self.ctrl.Bind(wx.EVT_CHECKLISTBOX, self._on_check)

    def fill(self, present, checked):
        """Lignes : (Aucun), périphériques présents, puis cochés absents ;
        une sélection faite est gardée par nom, sinon (Aucun)."""
        keep = self.selected()
        names = list(present) + [n for n in checked if n not in present]
        self.names = names
        self.ctrl.Set([self.NONE_LABEL] +
                      [n if n in present else n + ABSENT_SUFFIX for n in names])
        for i, n in enumerate(names):
            self.ctrl.Check(i + 1, n in checked)
        self._sync_none()
        self.ctrl.SetSelection(names.index(keep) + 1 if keep in names else 0)

    def _sync_none(self):
        self.ctrl.Check(0, not self.checked())

    def _on_check(self, event):
        if event.GetInt() == 0:                     # (Aucun) : tout décocher
            for i in range(1, len(self.names) + 1):
                self.ctrl.Check(i, False)
        self._sync_none()
        if self._on_change is not None:
            self._on_change()

    def checked(self):
        return [n for i, n in enumerate(self.names) if self.ctrl.IsChecked(i + 1)]

    def set_checked(self, checked):
        for i, n in enumerate(self.names):
            self.ctrl.Check(i + 1, n in checked)
        self._sync_none()

    def selected(self):
        """Ligne sélectionnée (sous le curseur), cochée ou non : on peut
        tester un périphérique avant de le cocher ; None sur (Aucun) ou sans
        sélection."""
        i = self.ctrl.GetSelection() - 1
        return self.names[i] if 0 <= i < len(self.names) else None


class HardwarePage:
    """Champs de l'onglet Matériel, construits dans panel."""

    KEYS = ("audio_hostapi", "audio_inputs", "audio_outputs", "audio_main_output",
            "midi_inputs", "midi_outputs")

    def __init__(self, panel, cfg, hardware):
        self._hw = hardware
        self._panel = panel
        box = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(0, 2, 6, 8)
        grid.AddGrowableCol(1, 1)

        def label(text):
            grid.Add(wx.StaticText(panel, label=text), 0, wx.ALIGN_TOP | wx.TOP, 4)

        def button(text, handler):
            btn = wx.Button(panel, label=text)
            btn.Bind(wx.EVT_BUTTON, lambda e: handler())
            return btn

        def row_with_button(ctrl, btn):
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(ctrl, 1, wx.EXPAND)
            if btn is not None:
                row.Add(btn, 0, wx.LEFT | wx.ALIGN_TOP, 6)
            grid.Add(row, 1, wx.EXPAND)

        label("Pilote audio :")
        self.hostapi = wx.Choice(panel, choices=hardware.hostapis())
        grid.Add(self.hostapi, 0, wx.EXPAND)

        label("Entrées audio :")
        self.audio_in = _CheckList(panel)
        self.test_audio_in_btn = button("Tester l'entrée audio", self.test_audio_input)
        row_with_button(self.audio_in.ctrl, self.test_audio_in_btn)

        label("Sorties audio :")
        self.audio_out = _CheckList(panel, on_change=self._fill_main_output)
        self.test_audio_out_btn = button("Tester la sortie audio", self.test_audio_output)
        row_with_button(self.audio_out.ctrl, self.test_audio_out_btn)

        label("Sortie principale :")
        self.main_output = wx.Choice(panel)
        grid.Add(self.main_output, 0, wx.EXPAND)

        grid.Add((0, 0))
        self.detect_audio_btn = button("Détecter les périphériques audio", self.detect_audio)
        grid.Add(self.detect_audio_btn, 0)

        label("Entrées MIDI :")
        self.midi_in = _CheckList(panel)
        self.test_midi_in_btn = button("Tester l'entrée MIDI", self.test_midi_input)
        row_with_button(self.midi_in.ctrl, self.test_midi_in_btn)

        label("Sorties MIDI :")
        self.midi_out = _CheckList(panel)
        self.test_midi_out_btn = button("Tester la sortie MIDI", self.test_midi_output)
        row_with_button(self.midi_out.ctrl, self.test_midi_out_btn)

        grid.Add((0, 0))
        self.detect_midi_btn = button("Détecter les périphériques MIDI", self.detect_midi)
        grid.Add(self.detect_midi_btn, 0)

        label("Résultat du test :")
        self.result = wx.TextCtrl(panel, style=wx.TE_READONLY | wx.TE_MULTILINE,
                                  size=(420, 50))
        grid.Add(self.result, 1, wx.EXPAND)

        box.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        panel.SetSizer(box)

        self.hostapi.Bind(wx.EVT_CHOICE, lambda e: self._on_hostapi())
        self.show_values(self.values_of(cfg))

    # ------------------------------------------------------------------
    # Valeurs
    # ------------------------------------------------------------------

    def values_of(self, cfg):
        """Réglages d'une configuration, tels que les champs les montrent :
        pilote par défaut nommé, « Synthé FluidSynth » coché seulement s'il
        est proposé."""
        outputs = self._hw.midi_outputs()
        return {
            "audio_hostapi": cfg.audio_hostapi or self._hw.default_hostapi(),
            "audio_inputs": cfg.audio_inputs,
            "audio_outputs": cfg.audio_outputs,
            "audio_main_output": cfg.audio_main_output,
            "midi_inputs": cfg.midi_inputs,
            "midi_outputs": [n for n in cfg.midi_outputs
                             if n in outputs or n != cfg.MIDI_SYNTH_OUTPUT],
        }

    def values(self):
        main = self.main_output.GetSelection()
        names = getattr(self, "_main_names", [""])
        return {
            "audio_hostapi": self.hostapi.GetStringSelection(),
            "audio_inputs": self.audio_in.checked(),
            "audio_outputs": self.audio_out.checked(),
            "audio_main_output": names[main] if 0 <= main < len(names) else "",
            "midi_inputs": self.midi_in.checked(),
            "midi_outputs": self.midi_out.checked(),
        }

    def show_values(self, vals):
        if "audio_hostapi" in vals:
            api = vals["audio_hostapi"]
            if self.hostapi.FindString(api) == wx.NOT_FOUND:
                api = self._hw.default_hostapi()
            self.hostapi.SetStringSelection(api)
        api = self.hostapi.GetStringSelection()
        current = self.values() if hasattr(self, "_main_names") else {}
        ins = vals.get("audio_inputs", current.get("audio_inputs", []))
        outs = vals.get("audio_outputs", current.get("audio_outputs", []))
        self.audio_in.fill(self._hw.audio_devices(api, INPUT), ins)
        self.audio_out.fill(self._hw.audio_devices(api, OUTPUT), outs)
        self._fill_main_output(vals.get("audio_main_output",
                                        current.get("audio_main_output", "")))
        self.midi_in.fill(self._hw.midi_inputs(),
                          vals.get("midi_inputs", current.get("midi_inputs", [])))
        self.midi_out.fill(self._hw.midi_outputs(),
                           vals.get("midi_outputs", current.get("midi_outputs", [])))

    def _fill_main_output(self, keep=None):
        """Liste « Sortie principale » (H16) : les sorties cochées, ou « Défaut
        du pilote » quand aucune ne l'est (comme AppConfig.audio_main_output :
        sinon le dialogue montrerait un choix et l'appli en ferait un autre) ;
        garde le choix s'il est encore coché, sinon la première cochée."""
        if keep is None:
            sel = self.main_output.GetSelection()
            names = getattr(self, "_main_names", [])
            keep = names[sel] if 0 <= sel < len(names) else ""
        checked = self.audio_out.checked()
        self._main_names = checked or [""]
        self.main_output.Set(checked or [MAIN_DEFAULT_LABEL])
        self.main_output.SetSelection(self._main_names.index(keep)
                                      if keep in self._main_names else 0)

    def _on_hostapi(self):
        """Autre pilote : listes audio relues, cases gardées par nom."""
        self.show_values({})

    # ------------------------------------------------------------------
    # Résultat, Tester, Détecter (H5, H9, H14, H17)
    # ------------------------------------------------------------------

    def say(self, msg):
        """Résultat dans le champ, sans y déplacer le focus (essai de 11f1 :
        on reste sur le bouton ; l'énoncé viendra du futur module
        SpeechAccess) ; le champ garde la trace de ce qui s'est passé."""
        if not self.result:              # dialogue fermé avant la fin d'une écoute
            return
        self.result.SetValue(msg)

    def _selected(self, checklist, what):
        name = checklist.selected()
        if name is None:
            self.say(f"Choisissez d'abord {what} dans la liste.")
        return name

    def test_audio_output(self):
        name = self._selected(self.audio_out, "une sortie audio")
        if name is not None:
            self.say(self._hw.test_audio_output(self.hostapi.GetStringSelection(), name))

    def test_audio_input(self):
        name = self._selected(self.audio_in, "une entrée audio")
        if name is not None:
            self.say(f"Entrée audio {name} : parlez ou jouez pendant 3 secondes…")
            self._hw.test_audio_input(self.hostapi.GetStringSelection(), name, self.say)

    def test_midi_output(self):
        name = self._selected(self.midi_out, "une sortie MIDI")
        if name is not None:
            self.say(self._hw.test_midi_output(name))

    def test_midi_input(self):
        name = self._selected(self.midi_in, "une entrée MIDI")
        if name is not None:
            self.say(f"Entrée MIDI {name} : jouez une note (5 secondes)…")
            self._hw.test_midi_input(name, self.say)

    def detect_audio(self):
        msg = self._hw.detect_audio()
        self.show_values({})
        self.say(msg)

    def detect_midi(self):
        msg = self._hw.detect_midi()
        self.show_values({})
        self.say(msg)
