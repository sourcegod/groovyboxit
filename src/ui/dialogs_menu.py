#python3
"""
    File: src/ui/dialogs_menu.py
    Dialogues des menus (Phase 9 étape 3d1, docs/DESIGN.md § Phase 9 étapes
    3a et 3b2) :
    - ValueDialog : « Régler… » un volume ou un pan (Mixer) ;
    - PatternChoiceDialog : « Choisir un pattern… » (Pattern > Changer de
      pattern) ;
    - ResizePatternDialog : « Redimensionner le pattern… » (mesures,
      résolution) ;
    - TempoSetDialog : « Régler le tempo… » (Transport > Métronome) : le
      premier tempo, touches ( ) et H, bouton Tap Tempo, case Click,
      résultat en lecture seule ; entendu en direct (essai de 3d1), tous
      les tempos changent dans la même proportion.
    Accessibilité : chaque libellé est créé AVANT son champ (Orca le lit),
    Entrée valide (bouton par défaut ; liste : EVT_LISTBOX_DCLICK), le
    clavier du dialogue ne prend que ses propres touches.
    Date: Tue, 24/11/2026
    Author: Coolbrother
"""
import wx

from .gtk_listbox import select_with_cursor


def _buttons(dlg):
    sizer = wx.StdDialogButtonSizer()
    ok = wx.Button(dlg, wx.ID_OK, "OK")
    ok.SetDefault()
    sizer.AddButton(ok)
    sizer.AddButton(wx.Button(dlg, wx.ID_CANCEL, "Annuler"))
    sizer.Realize()
    return sizer


def _spin(dlg, value, lo, hi, name):
    spin = wx.SpinCtrl(dlg, min=lo, max=hi, initial=max(lo, min(hi, int(value))),
                       style=wx.SP_ARROW_KEYS | wx.TE_PROCESS_ENTER)
    spin.SetName(name)
    spin.Bind(wx.EVT_TEXT_ENTER, lambda e: dlg.EndModal(wx.ID_OK))
    return spin


class ValueDialog(wx.Dialog):
    """Une valeur entière bornée : « Volume global (0 à 200) : ». get_value."""

    def __init__(self, parent, title, label, value, lo, hi):
        super().__init__(parent, title=title)
        text = f"{label} ({lo} à {hi}) :"
        lbl = wx.StaticText(self, label=text)               # avant le champ (Orca)
        self._spin = _spin(self, value, lo, hi, text)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(lbl, 0, wx.ALL, 6)
        box.Add(self._spin, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        box.Add(_buttons(self), 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizerAndFit(box)
        self._spin.SetFocus()

    def get_value(self):
        return self._spin.GetValue()


class PatternChoiceDialog(wx.Dialog):
    """Liste des patterns, le courant sélectionné ; Entrée choisit.
    get_index."""

    def __init__(self, parent, labels, current):
        super().__init__(parent, title="Choisir un pattern")
        lbl = wx.StaticText(self, label="Patterns :")
        self._list = wx.ListBox(self, choices=labels, style=wx.LB_SINGLE, size=(320, 260))
        select_with_cursor(self._list, current)
        self._list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(lbl, 0, wx.ALL, 6)
        box.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        box.Add(_buttons(self), 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizerAndFit(box)
        self._list.SetFocus()

    def get_index(self):
        return self._list.GetSelection()


class ResizePatternDialog(wx.Dialog):
    """Nombre de mesures et résolution du pattern. get_num_bars,
    get_resolution."""

    RESOLUTION_NAMES = {16: "double croche", 32: "triple croche",
                        64: "quadruple croche", 128: "quintuple croche"}

    def __init__(self, parent, num_bars, max_bars, resolution, resolutions):
        super().__init__(parent, title="Redimensionner le pattern")
        self._resolutions = list(resolutions)
        bars_lbl = wx.StaticText(self, label=f"Mesures (1 à {max_bars}) :")
        self._bars = _spin(self, num_bars, 1, max_bars, f"Mesures (1 à {max_bars})")
        res_lbl = wx.StaticText(self, label="Résolution :")
        self._res = wx.ListBox(
            self, style=wx.LB_SINGLE,
            choices=[f"1/{r} ({self.RESOLUTION_NAMES.get(r, '')})" for r in self._resolutions])
        select_with_cursor(self._res, self._resolutions.index(resolution)
                           if resolution in self._resolutions else 0)
        self._res.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))
        box = wx.BoxSizer(wx.VERTICAL)
        for w in (bars_lbl, self._bars, res_lbl, self._res):
            box.Add(w, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        box.Add(_buttons(self), 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizerAndFit(box)
        self._bars.SetFocus()

    def get_num_bars(self):
        return self._bars.GetValue()

    def get_resolution(self):
        return self._resolutions[max(0, self._res.GetSelection())]


class TempoSetDialog(wx.Dialog):
    """Le premier tempo du pattern : champ BPM, ( et ) = ±5, H ou le bouton =
    une frappe de Tap Tempo, résultat en lecture seule. tap() rend le BPM
    tapé, ou None tant que les frappes ne suffisent pas ; taps() le nombre
    de frappes de la série ; on_change(bpm) fait entendre le tempo, dialogue
    ouvert ; click : (état(), basculer(actif)) pour la case Click, qui fait
    entendre le résultat du Tap Tempo (essai de 3d1). get_value."""

    def __init__(self, parent, bpm, tap, taps=lambda: 0, on_change=None, click=None):
        super().__init__(parent, title="Régler le tempo")
        self._origin, self._tap, self._taps = int(round(bpm)), tap, taps
        self._on_change, self._heard = on_change, self._origin
        lbl = wx.StaticText(self, label="Premier tempo, BPM (1 à 600) :")
        self._spin = _spin(self, self._origin, 1, 600, "Premier tempo, BPM (1 à 600)")
        self._spin.Bind(wx.EVT_SPINCTRL, lambda e: self._show())
        self._spin.Bind(wx.EVT_TEXT, lambda e: self._show())
        self._tap_btn = wx.Button(self, label="&Tap Tempo")
        self._tap_btn.Bind(wx.EVT_BUTTON, lambda e: self.tap())
        self._click = wx.CheckBox(self, label="&Click (métronome)")
        self._click_ctl = click
        if click:
            self._click.SetValue(bool(click[0]()))
            self._click.Bind(wx.EVT_CHECKBOX, lambda e: click[1](self._click.GetValue()))
        else:
            self._click.Hide()
        res_lbl = wx.StaticText(self, label="Résultat :")
        self._result = wx.TextCtrl(self, style=wx.TE_READONLY, size=(320, -1))
        self._result.SetName("Résultat")
        box = wx.BoxSizer(wx.VERTICAL)
        for w in (lbl, self._spin, self._tap_btn, self._click, res_lbl, self._result):
            box.Add(w, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        box.Add(_buttons(self), 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizerAndFit(box)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._show()
        self._spin.SetFocus()

    def _on_char_hook(self, event):
        """( et ) : ±5 ; H : une frappe — comme dans la fenêtre principale.
        Toute autre touche suit son chemin (Entrée, Tab, chiffres)."""
        key, ukey = event.GetKeyCode(), event.GetUnicodeKey()
        if event.ControlDown() or event.AltDown():
            event.Skip()
            return
        if ukey == ord("(") or key == ord("("):
            self.step(5)
        elif ukey == ord(")") or key == ord(")"):
            self.step(-5)
        elif ukey in (ord("h"), ord("H")) or key == ord("H"):
            self.tap()
        else:
            event.Skip()

    def step(self, delta):
        self._spin.SetValue(max(1, min(600, self._spin.GetValue() + delta)))
        self._show()

    def tap(self):
        bpm = self._tap()
        if bpm is None:
            n = self._taps()
            self._result.SetValue(f"Tap Tempo : frappe {n}, continuez (4 frappes au moins)")
            return
        self._spin.SetValue(int(round(bpm)))
        self._show(tapped=True)

    def _show(self, tapped=False):
        v = self._spin.GetValue()
        if self._on_change and v != self._heard:          # entendu aussitôt
            self._heard = v
            self._on_change(v)
        text = f"Premier tempo : {v} BPM (avant : {self._origin})"
        if v != self._origin:
            text += f", tous les tempos × {v / self._origin:.2f}".replace(".", ",")
        self._result.SetValue(("Tap Tempo — " if tapped else "") + text)

    def get_value(self):
        return self._spin.GetValue()

    def get_result(self):
        return self._result.GetValue()
