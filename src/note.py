#python3
"""
    File: note.py
    TNote — unité fondamentale d'une note (position, channel, pitch, velocity, length).
    Commune aux modes Drum, Synth, Loop, Audio, Midi.
    Date: Fri, 16/05/2026
    Author: Coolbrother
"""

__slots__ = ()


class TNote:
    """Note MIDI-compatible : position en pas, canal, pitch, vélocité, durée."""

    __slots__ = ("position", "channel", "pitch", "velocity", "length")

    def __init__(self, position=0.0, channel=0, pitch=60, velocity=100, length=1.0):
        self.position = float(position)  # position dans la mesure, en pas
        self.channel  = int(channel)     # canal MIDI 0-15
        self.pitch    = int(pitch)       # note MIDI 0-127 (60 = Do4)
        self.velocity = int(velocity)    # vélocité 0-127
        self.length   = float(length)    # durée en pas

    # ------------------------------------------------------------------

    def to_dict(self):
        return {
            "pos": self.position,
            "ch":  self.channel,
            "pit": self.pitch,
            "vel": self.velocity,
            "len": self.length,
        }

    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d):
        return cls(
            position = d.get("pos", 0.0),
            channel  = d.get("ch",  0),
            pitch    = d.get("pit", 60),
            velocity = d.get("vel", 100),
            length   = d.get("len", 1.0),
        )

    # ------------------------------------------------------------------

    def __repr__(self):
        return (f"TNote(pos={self.position}, ch={self.channel}, "
                f"pit={self.pitch}, vel={self.velocity}, len={self.length})")

    # ------------------------------------------------------------------

    def copy(self):
        return TNote(self.position, self.channel, self.pitch, self.velocity, self.length)

#=========================================

if __name__ == "__main__":
    n = TNote(position=0.0, pitch=60, velocity=100, length=1.0)
    print(n)
    d = n.to_dict()
    print(d)
    n2 = TNote.from_dict(d)
    print(n2)
    input("OK")
