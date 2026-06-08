class Song:
    MAX_SONGS = 16

    def __init__(self, idx=0):
        self._idx      = idx
        self._name     = ""
        self._sequence = []  # liste d'indices 0-based dans _pattern_list (0..98)

    def label(self):
        base = self._name if self._name else f"Song_{self._idx + 1:02d}"
        n = len(self._sequence)
        return f"{base} ({n})" if n else base

    def to_dict(self):
        return {"name": self._name, "sequence": self._sequence[:]}

    def from_dict(self, d):
        self._name     = d.get("name", "")
        self._sequence = [int(i) for i in d.get("sequence", [])]
