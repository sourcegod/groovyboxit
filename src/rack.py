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
        """Étiquette pour la liste déroulante : '01 - Piano' ou '01 - Empty'."""
        num = self.index + 1
        if self.is_empty:
            return f"{num:02d} - Empty"
        return f"{num:02d} - {self.name}"

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
