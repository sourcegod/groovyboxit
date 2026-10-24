#python3
"""
    File: rack.py
    Rack — 16 slots d'instruments globaux partagés par tous les patterns.
    Types : kit | synth | loop | audio | midi_file | midi_port
    Date: Fri, 16/05/2026
    Author: Coolbrother
"""


class InstrumentType:
    KIT       = "kit"
    SYNTH     = "synth"
    LOOP      = "loop"
    AUDIO     = "audio"
    MIDI_FILE = "midi_file"
    MIDI_PORT = "midi_port"

    ALL = (KIT, SYNTH, LOOP, AUDIO, MIDI_FILE, MIDI_PORT)


class InstrumentSlot:
    """Un slot du Rack : type, nom, config spécifique au type."""

    def __init__(self, index=0):
        self.index  = index
        self.type   = None   # InstrumentType.* ou None si vide
        self.name   = ""
        self.config = {}     # dict dépendant du type
        # Objet audio chargé en mémoire (géré par SynthEngine / SoundManager)
        self._loaded = None

    # ------------------------------------------------------------------

    @property
    def is_empty(self):
        return self.type is None

    # ------------------------------------------------------------------

    def label(self):
        """Étiquette pour la liste déroulante : 'Slot_01 - Piano' ou 'Slot_01 - Empty'."""
        num = self.index + 1
        if self.is_empty:
            return f"Slot_{num:02d} - Empty"
        return f"Slot_{num:02d} - {self.name}"

    # ------------------------------------------------------------------

    def gm_program(self):
        """Programme GM du slot (Phase 7 étape 10h3) : instrument GM pour un
        synthé, kit GM2 pour un kit ; config["gm_program"] s'il est réglé,
        sinon déduit du nom. None pour un slot vide ou d'un autre type."""
        if self.type not in (InstrumentType.SYNTH, InstrumentType.KIT):
            return None
        program = self.config.get("gm_program")
        if isinstance(program, int) and 0 <= program <= 127:
            return program
        from midi.midi_constants import guess_gm_program
        return guess_gm_program(self.name, drums=self.type == InstrumentType.KIT)

    def set_gm_program(self, program):
        """Règle config["gm_program"]. config est remplacé, jamais modifié en
        place : to_dict le partage avec les instantanés d'Undo."""
        self.config = {**self.config, "gm_program": max(0, min(127, int(program)))}

    # Réglages d'export GM du slot (Phase 7 étape 12f1, docs/DESIGN.md
    # § 12a2 D4, D5) : sans effet sur l'appli.
    GM_TRANSPOSE_MIN, GM_TRANSPOSE_MAX = -24, 24
    GM_GAIN_DB_MIN,   GM_GAIN_DB_MAX   = -40, 0

    def _config_int(self, key, lo, hi):
        value = self.config.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return max(lo, min(hi, value))
        return 0

    def gm_transpose(self):
        """Transposition GM en demi-tons (config["gm_transpose"], borné à
        ±24), appliquée à l'export aux notes d'un synthé. 0 pour un slot qui
        n'est pas un synthé ou sans réglage."""
        if self.type != InstrumentType.SYNTH:
            return 0
        return self._config_int("gm_transpose", self.GM_TRANSPOSE_MIN, self.GM_TRANSPOSE_MAX)

    def set_gm_transpose(self, semitones):
        """Règle config["gm_transpose"] ; config est remplacé (voir set_gm_program)."""
        value = max(self.GM_TRANSPOSE_MIN, min(self.GM_TRANSPOSE_MAX, int(semitones)))
        self.config = {**self.config, "gm_transpose": value}

    def gm_gain_db(self):
        """Gain GM en dB (config["gm_gain_db"], borné à -40..0), appliqué
        à l'export aux CC7 de la piste. 0 pour un slot vide ou sans réglage."""
        if self.is_empty:
            return 0
        return self._config_int("gm_gain_db", self.GM_GAIN_DB_MIN, self.GM_GAIN_DB_MAX)

    def set_gm_gain_db(self, db):
        """Règle config["gm_gain_db"] ; config est remplacé (voir set_gm_program)."""
        value = max(self.GM_GAIN_DB_MIN, min(self.GM_GAIN_DB_MAX, int(db)))
        self.config = {**self.config, "gm_gain_db": value}

    # ------------------------------------------------------------------

    def clear(self):
        self.type    = None
        self.name    = ""
        self.config  = {}
        self._loaded = None

    # ------------------------------------------------------------------

    def to_dict(self):
        return {
            "index":  self.index,
            "type":   self.type,
            "name":   self.name,
            "config": self.config,
        }

    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d):
        slot        = cls(d.get("index", 0))
        slot.type   = d.get("type",   None)
        slot.name   = d.get("name",   "")
        slot.config = d.get("config", {})
        return slot

    # ------------------------------------------------------------------

    def __repr__(self):
        return f"InstrumentSlot({self.label()})"


# ======================================================================


class Rack:
    """Rack global de 16 slots d'instruments, partagé par tous les patterns."""

    NUM_SLOTS = 16

    def __init__(self):
        self._slots = [InstrumentSlot(i) for i in range(self.NUM_SLOTS)]

    # ------------------------------------------------------------------

    def get_slot(self, index):
        return self._slots[index]

    # ------------------------------------------------------------------

    def set_slot(self, index, slot_type, name, config=None):
        s         = self._slots[index]
        s.type    = slot_type
        s.name    = name
        s.config  = config or {}
        s._loaded = None

    # ------------------------------------------------------------------

    def clear_slot(self, index):
        self._slots[index].clear()

    # ------------------------------------------------------------------

    def labels(self):
        """Liste des étiquettes pour la liste déroulante."""
        return [s.label() for s in self._slots]

    # ------------------------------------------------------------------

    def to_dict(self):
        return {"slots": [s.to_dict() for s in self._slots]}

    # ------------------------------------------------------------------

    def from_dict(self, data):
        for d in data.get("slots", []):
            idx = d.get("index", 0)
            if 0 <= idx < self.NUM_SLOTS:
                self._slots[idx] = InstrumentSlot.from_dict(d)

    # ------------------------------------------------------------------

    def __repr__(self):
        filled = sum(1 for s in self._slots if not s.is_empty)
        return f"Rack({filled}/{self.NUM_SLOTS} slots chargés)"

#=========================================

if __name__ == "__main__":
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT,   "808 Kit", {"samples": ["1.wav"]})
    rack.set_slot(1, InstrumentType.SYNTH, "Piano",   {"patch": "Piano", "scale": "major", "root_note": "C3"})
    print(rack)
    for label in rack.labels():
        print(label)
    d = rack.to_dict()
    rack2 = Rack()
    rack2.from_dict(d)
    print(rack2)
    input("OK")
