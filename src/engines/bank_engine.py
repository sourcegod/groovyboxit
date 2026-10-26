#python3
"""
    File: src/engines/bank_engine.py
    Interface « moteur de banque » (Phase 7 étape 17b1, docs/DESIGN.md
    § 17a1 D1, D14) : un fichier de banque par emplacement (0..3), un
    instrument par canal MIDI (0..15), rendu stéréo ajouté au mixage du
    pilote audio. FluidSynth (SF2/SF3) maintenant, SFZ plus tard derrière
    la même interface.

    Volontairement proche d'une API C (entiers, pas d'objet Python dans
    les appels temps réel) : le moteur audio est un prototype, la cible
    est C/C++.
    Date: Mon, 26/10/2026
    Author: Coolbrother
"""


class BankEngine:
    """Contrat commun des moteurs de banque. Toutes les méthodes peuvent
    être appelées depuis l'UI, un threading.Timer ou le séquenceur ;
    render() l'est depuis le callback audio."""

    NUM_BANK_SLOTS = 4     # emplacements de banque fixes (D4)
    NUM_CHANNELS   = 16

    # Mode Bank Select (D17) : "gs" = le MSB seul choisit la banque ;
    # "mma" = banque MSB × 128 + LSB.
    BANK_SELECT_MODES = ("gs", "mma")

    def __init__(self, bank_select="gs"):
        self.bank_select = bank_select if bank_select in self.BANK_SELECT_MODES else "gs"

    def bank_number(self, msb, lsb):
        """Numéro de banque de la soundfont choisi par CC0 (MSB) et CC32
        (LSB), selon le mode Bank Select."""
        if self.bank_select == "mma":
            return (msb & 0x7F) * 128 + (lsb & 0x7F)
        return msb & 0x7F

    # -- banques ---------------------------------------------------------

    def load(self, slot, path):
        """Charge path dans l'emplacement slot (0..3), en remplaçant
        l'ancien fichier. Retourne False si le fichier est refusé."""
        raise NotImplementedError

    def unload(self, slot):
        raise NotImplementedError

    def loaded_path(self, slot):
        """Chemin du fichier chargé dans slot, ou None."""
        raise NotImplementedError

    def presets(self, slot):
        """[(banque, programme, nom)] lus dans la banque, triés (D6)."""
        raise NotImplementedError

    # -- canaux ----------------------------------------------------------

    def select(self, channel, slot, bank, program):
        """Instrument du canal : programme de la banque chargée dans slot.
        Retourne False si slot est vide ou le preset introuvable."""
        raise NotImplementedError

    def note_on(self, channel, note, velocity):
        raise NotImplementedError

    def note_off(self, channel, note):
        raise NotImplementedError

    def cc(self, channel, num, value):
        raise NotImplementedError

    def pitch_bend(self, channel, value):
        """value : -8192..+8191, 0 = centre (convention de SynthEngine)."""
        raise NotImplementedError

    def program_change(self, channel, program):
        raise NotImplementedError

    def all_notes_off(self):
        raise NotImplementedError

    def all_sounds_off(self):
        raise NotImplementedError

    def reset_controllers(self):
        raise NotImplementedError

    # -- rendu -----------------------------------------------------------

    def render(self, out):
        """Ajoute len(out) échantillons stéréo dans out, tableau numpy
        float32 (frames, 2) contigu — signature d'une source de rendu de
        SoundDeviceDriver.add_render_source."""
        raise NotImplementedError

    def close(self):
        raise NotImplementedError
