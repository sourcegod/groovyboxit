#python3
"""
    File: src/ui/midi_virtual_keyboard.py
    VirtualKeyboardMixin — clavier virtuel de MidiEditorWindow (Phase 6 étape 7f) :
    liste des notes MIDI C0..G10, lecture avec l'instrument (Pad/Kit/Patch) de
    la piste courante, raccourcis Haut/Bas (ListBox focus) et Alt+Numpad 2/8
    (global). Sert de source par défaut pour les insertions (étape 7g).
    Date: Fri, 24/07/2026
    Author: Coolbrother
"""
import wx
from rack import InstrumentType

_NOTE_NAMES_C0 = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NOTE_NAMES_FR = ["Do", "Do#", "Ré", "Ré#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si"]


def midi_display_name(midi):
    """Convention C0=MIDI 0 : C0…G10 (128 notes)."""
    return f"{_NOTE_NAMES_C0[midi % 12]}{midi // 12}"


def midi_display_label(midi):
    """Nom complet anglo + solfège FR pour la listbox du clavier virtuel : 'C#4: Do#4'."""
    octave = midi // 12
    return f"{_NOTE_NAMES_C0[midi % 12]}{octave}: {_NOTE_NAMES_FR[midi % 12]}{octave}"


class VirtualKeyboardMixin:
    """Mixin MidiEditorWindow — clavier virtuel (étape 7f)."""

    def _build_vk_ui(self, panel, vbox):
        vk_label = wx.StaticText(panel, label="Clavier virtuel :")
        vbox.Add(vk_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
        self._vk_lb = wx.ListBox(
            panel, choices=[midi_display_label(i) for i in range(128)],
            style=wx.LB_SINGLE, size=(-1, 110)
        )
        vbox.Add(self._vk_lb, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self._vk_lb.Bind(wx.EVT_LISTBOX, self._on_vk_listbox_select)
        self._vk_lb.SetSelection(self._vk_note)

    def _play_virtual_keyboard_note(self, midi):
        """Joue midi (note MIDI brute 0..127) avec l'instrument (Pad/Kit/Patch)
        de la piste courante. Silencieux si l'instrument ne supporte pas cette
        note (convention existante : SoundManager.play_note / bornes SYNTH)."""
        slot   = self._parent._rack.get_slot(self._parent._cur_slot)
        router = self._parent._router
        if slot.type == InstrumentType.SYNTH:
            if not router.synth_ready():
                router.load_slot_preview(self._parent._cur_slot)
                return
            router.synth.play(midi, maxtime_ms=500)
        elif slot.type == InstrumentType.KIT:
            if self._parent._snd.note_map:
                self._parent._snd.play_note(midi, 1.0)
            elif router.kit_synth and router.kit_synth.is_loaded():
                router.kit_synth.play(midi, maxtime_ms=500)

    def _vk_move(self, delta):
        """Change la note du clavier virtuel de ±delta (demi-ton), borné 0..127,
        joue le résultat et l'annonce."""
        new_note = max(0, min(127, self._vk_note + delta))
        if new_note == self._vk_note:
            self._set_status("Clavier virtuel: déjà à la borne")
            return
        self._vk_note = new_note
        self._skip_vk_announce = True
        self._vk_lb.SetSelection(new_note)
        # SetSelection() seul ne déclenche pas toujours NAME_CHANGE côté AT-SPI ;
        # SetString() sur la ligne sélectionnée force Orca à l'annoncer
        # (cf. SPECS.md "Astuces d'accessibilité").
        self._vk_lb.SetString(new_note, midi_display_label(new_note))
        self._play_virtual_keyboard_note(new_note)
        self._set_status(f"Clavier virtuel: ({midi_display_label(new_note)})")

    def _on_vk_listbox_select(self, evt):
        idx = self._vk_lb.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        self._vk_note = idx
        if self._skip_vk_announce:
            self._skip_vk_announce = False
            return
        self._play_virtual_keyboard_note(idx)
        self._set_status(f"Clavier virtuel: ({midi_display_label(idx)})")
