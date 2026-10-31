#python3
"""
    File: src/sound_manager.py
    Gestion des sons : chargement kits/pads, lecture, métronome.
    Le backend audio est injecté via un driver (SoundDeviceDriver par défaut).
    PygameDriver reste disponible dans pygame_driver.py comme backend optionnel.
    Date: Thu, 28/05/2026
    Author: Coolbrother
"""
import os
import copy
import json
import numpy as np

from midi.midi_constants import gm_gain


class SoundManager(object):
    """Gestionnaire de sons — indépendant du backend audio."""

    def __init__(self, media_lst, click_name1, click_name2, driver=None):
        if driver is None:
            from sound_device_driver import SoundDeviceDriver
            driver = SoundDeviceDriver()

        self._driver     = driver
        self.media_lst   = media_lst
        self.drum_sounds = []
        self.note_map    = {}   # {midi_note: sound} — tous les sons du kit
        self.mute_groups = [0] * 16  # mute_group par pad — pour sync VoiceManager au chargement
        self._sound_group  = {}  # {id(sound): group_id} — index audio unifié
        self._group_sounds = {}  # {group_id: set(sounds)} — pairs à stopper
        self.kit_base    = 36  # première note du kit (note MIDI)
        self.kit_offset  = 0   # décalage courant en demi-tons (multiples de 8)
        # Note de kit du son de chaque pad (Phase 7 étape 11d1, D1) et
        # {note de kit: note GM} pour l'export MIDI (D2)
        self.pad_notes   = [self.kit_base + i for i in range(16)]
        self.gm_note_map = {}

        self.sound_click1 = self._driver.load(click_name1)
        self.sound_click2 = self._driver.load(click_name2)

    # ------------------------------------------------------------------
    # Chargement
    # ------------------------------------------------------------------

    def load_sounds(self):
        self.drum_sounds = [self._driver.load(item) for item in self.media_lst]
        self.pad_notes   = [self.kit_base + i for i in range(16)]
        self.gm_note_map = {}

    def load_pad_sound(self, pad_idx, wav_path):
        """Remplace le son du pad pad_idx par le WAV donné."""
        snd = self._driver.load(wav_path)
        while len(self.drum_sounds) <= pad_idx:
            self.drum_sounds.append(self._silent_sound())
        self.drum_sounds[pad_idx] = snd

    def _silent_sound(self):
        """Son silencieux pour pad sans fichier."""
        return self._driver.make_silent()

    def load_kit(self, json_path):
        """Charge un kit depuis un fichier JSON.

        Chaque entrée peut avoir :
          "pad"        (1-16)  → son assigné au Numpad
          "note"       (MIDI)  → son déclenché par note MIDI (note_map)
          "mute_group" (int)   → groupe mute exclusif (0 = aucun)
          "gm_note"    (35-81) → note GM à l'export, prioritaire
          "filename" et "label"
        Au niveau du kit, "gm": true garde chaque note telle quelle à
        l'export (kit déjà rangé selon GM).

        Retourne (labels, wav_paths) — deux listes de 16 éléments (pads Numpad).
        Construit aussi self.note_map {midi_note: sound} pour le routage MIDI,
        self._sound_group / self._group_sounds pour le mute exclusif, et
        self.pad_notes / self.gm_note_map pour l'export MIDI.
        """
        json_path = os.path.abspath(json_path)
        json_dir  = os.path.dirname(json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        # Cache son par chemin WAV pour éviter de charger deux fois le même fichier
        sound_cache = {}

        def _load_sound(filename):
            if not filename:
                return None, ""
            wav_path = os.path.normpath(os.path.join(json_dir, filename))
            if not os.path.exists(wav_path):
                return None, wav_path
            if wav_path not in sound_cache:
                sound_cache[wav_path] = self._driver.load(wav_path)
            return sound_cache[wav_path], wav_path

        pad_map = {p["pad"]: p for p in meta.get("pads", []) if "pad" in p}

        # ── Pads Numpad (1-16) ──────────────────────────────────────────
        labels      = []
        wav_paths   = []
        new_sounds  = []
        mute_groups = []
        for i in range(1, 17):
            entry    = pad_map.get(i, {})
            label    = entry.get("label", f"Pad {i:02d}")
            sound, wav_path = _load_sound(entry.get("filename", ""))
            labels.append(label)
            wav_paths.append(wav_path)
            new_sounds.append(sound if sound else self._silent_sound())
            mute_groups.append(max(0, int(entry.get("mute_group", 0))))

        self.drum_sounds = new_sounds
        self.media_lst   = wav_paths
        self.mute_groups = mute_groups   # conservé pour sync VoiceManager

        # ── note_map + note_labels ───────────────────────────────────────
        self.note_map    = {}
        self.note_labels = {}
        for entry in meta.get("pads", []):
            note = entry.get("note")
            if note is None:
                continue
            label = entry.get("label", f"Note {note}")
            sound, _ = _load_sound(entry.get("filename", ""))
            if sound:
                self.note_map[note]    = sound
                self.note_labels[note] = label

        # ── Index mute exclusif — un seul point de vérité ───────────────
        # Les sons drum_sounds et note_map partagent les objets via sound_cache ;
        # on indexe par identité d'objet → mute group unifié quel que soit
        # le chemin de déclenchement (pad numpad, séquenceur, note MIDI live).
        self._sound_group  = {}
        self._group_sounds = {}
        for entry in meta.get("pads", []):
            group    = max(0, int(entry.get("mute_group", 0)))
            filename = entry.get("filename", "")
            if not group or not filename:
                continue
            wav_path = os.path.normpath(os.path.join(json_dir, filename))
            sound    = sound_cache.get(wav_path)
            if sound is None:
                continue
            self._sound_group[id(sound)] = group
            self._group_sounds.setdefault(group, set()).add(sound)

        self._kit_name  = meta.get("name", "")
        self.kit_base   = meta.get("base_note", 36)
        self.kit_offset = 0

        # ── Notes des pads et correspondance GM (Phase 7 étape 11d1) ────
        # docs/DESIGN.md § 11a1 D1 : note du son réellement joué par le pad ;
        # D2 : gm_note, puis "gm": true, puis devinette d'après le libellé.
        kit_is_gm = meta.get("gm") is True
        self.pad_notes   = []
        self.gm_note_map = {}
        for entry in meta.get("pads", []):
            note = entry.get("note")
            if note is None:
                continue
            gm = self._entry_gm_note(entry, note, kit_is_gm)
            if gm is not None:
                self.gm_note_map[note] = gm
        for i in range(1, 17):
            entry = pad_map.get(i, {})
            note  = entry.get("note")
            if note is None:
                note = self.kit_base + i - 1
                if note not in self.gm_note_map:
                    gm = self._entry_gm_note(entry, note, kit_is_gm)
                    if gm is not None:
                        self.gm_note_map[note] = gm
            self.pad_notes.append(note)
        return labels, wav_paths

    @staticmethod
    def _entry_gm_note(entry, note, kit_is_gm):
        """Note GM d'une entrée de kit (docs/DESIGN.md § 11a1 D2) : sa clé
        "gm_note" (35-81) ; sinon `note` elle-même si le kit est GM ; sinon
        la note devinée d'après le libellé ; None si rien ne correspond."""
        from midi.midi_constants import (GM_DRUM_FIRST, GM_DRUM_LAST,
                                         guess_gm_drum_note)
        gm = entry.get("gm_note")
        if (isinstance(gm, int) and not isinstance(gm, bool)
                and GM_DRUM_FIRST <= gm <= GM_DRUM_LAST):
            return gm
        if kit_is_gm:
            return note
        return guess_gm_drum_note(entry.get("label", ""), note)

    # ------------------------------------------------------------------
    # Décalage du kit
    # ------------------------------------------------------------------

    def shift_kit(self, delta):
        """Décale la fenêtre de 16 pads de delta demi-tons.
        Retourne la liste des 16 nouveaux labels.
        """
        notes = sorted(self.note_map.keys())
        if not notes:
            return [f"Pad {i:02d}" for i in range(1, 17)]
        min_note = notes[0]
        max_note = notes[-1]
        new_offset = self.kit_offset + delta
        new_offset = max(min_note - self.kit_base, new_offset)
        new_offset = min(max_note - self.kit_base - 15, new_offset)
        self.kit_offset = new_offset
        return self._rebuild_drum_sounds()

    def _rebuild_drum_sounds(self):
        """Reconstruit drum_sounds[16] à partir de note_map selon kit_base+kit_offset."""
        labels = []
        for i in range(16):
            note  = self.kit_base + self.kit_offset + i
            sound = self.note_map.get(note)
            self.pad_notes[i] = note
            self.drum_sounds[i] = sound if sound else self._silent_sound()
            labels.append(self.note_labels.get(note, f"Note {note}"))
        return labels

    def render_copy(self, driver):
        """Copie qui joue sur driver (le Mixer du rendu hors temps réel de
        l'export WAV, Phase 8 étape 1d1, docs/DESIGN.md § Phase 8 étape 1a,
        W7). Les sons sont partagés, pas rechargés ; les tables (sons, notes,
        groupes de mute) sont copiées : un kit chargé pendant le rendu ne
        change pas la copie."""
        c = copy.copy(self)
        c._driver       = driver
        c.drum_sounds   = list(self.drum_sounds)
        c.note_map      = dict(self.note_map)
        c.mute_groups   = list(self.mute_groups)
        c._sound_group  = dict(self._sound_group)
        c._group_sounds = {g: set(snds) for g, snds in self._group_sounds.items()}
        c.pad_notes     = list(self.pad_notes)
        c.gm_note_map   = dict(self.gm_note_map)
        return c

    # ------------------------------------------------------------------
    # Mute exclusif — point central
    # ------------------------------------------------------------------

    def _apply_mute_group(self, sound):
        """Stoppe les peers actifs du même groupe avant de jouer sound.
        No-op si sound est None ou n'appartient à aucun groupe."""
        if sound is None:
            return
        group = self._sound_group.get(id(sound), 0)
        if group:
            for peer in self._group_sounds.get(group, ()):
                if peer is not sound:
                    self._driver.stop_sound(peer)

    def set_pad_mute_group(self, pad_idx, group):
        """Met à jour le groupe mute d'un pad dans l'index audio.
        Hook pour l'UI (PadPropertiesDialog) — à appeler avec
        VoiceManager.set_mute_group() pour garder les deux en sync."""
        if pad_idx >= len(self.drum_sounds):
            return
        sound     = self.drum_sounds[pad_idx]
        old_group = self._sound_group.pop(id(sound), 0)
        if old_group:
            peers = self._group_sounds.get(old_group)
            if peers:
                peers.discard(sound)
                if not peers:
                    del self._group_sounds[old_group]
        group = max(0, int(group))
        if group:
            self._sound_group[id(sound)] = group
            self._group_sounds.setdefault(group, set()).add(sound)
        if pad_idx < len(self.mute_groups):
            self.mute_groups[pad_idx] = group

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def play_note(self, midi_note, volume_factor=1.0, pan=0):
        """Joue un son par note MIDI (utilise note_map).
        Applique automatiquement le mute exclusif de groupe. volume_factor
        linéaire, passé au driver selon la courbe GM (gm_gain, Phase 7
        étape 12b1)."""
        sound = self.note_map.get(midi_note)
        if sound is None:
            return
        self._apply_mute_group(sound)
        self._driver.play(sound, gm_gain(volume_factor), pan)

    def play_sound(self, index, volume_factor=1.0, pan=0):
        """Joue drum_sounds[index].
        Applique automatiquement le mute exclusif de groupe. volume_factor
        linéaire, passé au driver selon la courbe GM (gm_gain, Phase 7
        étape 12b1)."""
        sound = self.drum_sounds[index]
        self._apply_mute_group(sound)
        self._driver.play(sound, gm_gain(volume_factor), pan)

    def preview_sound(self, sound_name):
        if sound_name in self.drum_sounds:
            self._driver.play(self.drum_sounds[sound_name])

    def play_metronome(self, beat_counter):
        """Joue le son du métronome."""
        if beat_counter == 0:
            self._driver.play(self.sound_click1)
        else:
            self._driver.play(self.sound_click2)

    # ------------------------------------------------------------------
    # Contrôle
    # ------------------------------------------------------------------

    def stop_all(self):
        self._driver.stop_all()

    def set_volume(self, volume):
        """Règle le volume global (0..100).
        - SoundDeviceDriver : applique via set_master_volume.
        - PygameDriver (optionnel) : applique le volume sur chaque son individuellement.
        """
        vol_norm = volume / 100.0
        self._driver.set_master_volume(volume)
        for sound in self.drum_sounds:
            self._driver.set_sound_volume(sound, vol_norm)
        self._driver.set_sound_volume(self.sound_click1, vol_norm)
        self._driver.set_sound_volume(self.sound_click2, vol_norm)


if __name__ == "__main__":
    input("It's OK...")
