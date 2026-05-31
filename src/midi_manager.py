#python3
"""
    File: src/midi_manager.py
    Gestionnaire d'entrée MIDI externe (python-rtmidi).
    Reçoit les messages Note On / Note Off d'un clavier ou pad MIDI
    et les transmet via callbacks découplés de l'interface graphique.
    Date: Fri, 23/05/2026
    Author: Coolbrother
"""

try:
    import rtmidi
    _RTMIDI_AVAILABLE = True
except ImportError:
    _RTMIDI_AVAILABLE = False


class MidiManager:
    """
    Gestionnaire d'entrée MIDI.

    Callbacks:
        on_note_on(note, velocity, channel)   — Note On  (velocity > 0)
        on_note_off(note, channel)            — Note Off (velocity == 0 ou 0x8n)
        on_status(message: str)               — événement texte (connexion, erreur…)

    Filtrage de canal : si self.channel est None, tous les canaux sont acceptés ;
    sinon seul le canal correspondant (0–15) est traité.
    """

    def __init__(self, on_note_on=None, on_note_off=None, on_status=None,
                 on_cc=None, on_pitch_bend=None):
        self._on_note_on    = on_note_on
        self._on_note_off   = on_note_off
        self._on_status     = on_status
        self._on_cc         = on_cc
        self._on_pitch_bend = on_pitch_bend

        self.channel    = None   # None = tous les canaux, 0–15 = filtre
        self._midi_in   = None
        self._port_idx  = None
        self._port_name = None

        if not _RTMIDI_AVAILABLE:
            self._notify("python-rtmidi non disponible — entrée MIDI désactivée")

    # ------------------------------------------------------------------
    # Énumération des ports

    def list_ports(self):
        """Retourne la liste des noms de ports MIDI d'entrée disponibles."""
        if not _RTMIDI_AVAILABLE:
            return []
        tmp = rtmidi.MidiIn()
        ports = tmp.get_ports()
        del tmp
        return ports

    # ------------------------------------------------------------------
    # Connexion / déconnexion

    def open(self, port_index):
        """Ouvre le port MIDI d'entrée par index. Ferme le port précédent si ouvert."""
        if not _RTMIDI_AVAILABLE:
            return False
        self.close()
        ports = self.list_ports()
        if port_index < 0 or port_index >= len(ports):
            self._notify(f"Port MIDI {port_index} introuvable")
            return False
        self._midi_in = rtmidi.MidiIn()
        self._midi_in.open_port(port_index)
        self._midi_in.set_callback(self._callback)
        self._midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
        self._port_idx  = port_index
        self._port_name = ports[port_index]
        self._notify(f"MIDI connecté : {self._port_name}")
        return True

    def open_by_name(self, name):
        """Ouvre le premier port dont le nom contient 'name' (insensible à la casse)."""
        for i, p in enumerate(self.list_ports()):
            if name.lower() in p.lower():
                return self.open(i)
        self._notify(f"Port MIDI '{name}' introuvable")
        return False

    def open_first(self):
        """Ouvre le premier port disponible."""
        ports = self.list_ports()
        if not ports:
            self._notify("Aucun port MIDI d'entrée disponible")
            return False
        return self.open(0)

    def close(self):
        """Ferme le port MIDI et libère les ressources."""
        if self._midi_in is not None:
            self._midi_in.close_port()
            del self._midi_in
            self._midi_in   = None
            self._port_idx  = None
            self._port_name = None
            self._notify("MIDI déconnecté")

    def is_open(self):
        return self._midi_in is not None

    @property
    def port_name(self):
        return self._port_name or ""

    # ------------------------------------------------------------------
    # Callback interne rtmidi

    def _callback(self, event, _data):
        """Appelé par rtmidi dans son propre thread à chaque message reçu."""
        message, _delta = event
        if not message:
            return

        status  = message[0]
        msg_type = status & 0xF0
        chan     = status & 0x0F

        if self.channel is not None and chan != self.channel:
            return

        if msg_type == 0x90:                  # Note On
            note     = message[1]
            velocity = message[2]
            if velocity == 0:                  # Note On vel=0 = Note Off
                if self._on_note_off:
                    self._on_note_off(note, chan)
            else:
                if self._on_note_on:
                    self._on_note_on(note, velocity, chan)

        elif msg_type == 0x80:                # Note Off explicite
            note = message[1]
            if self._on_note_off:
                self._on_note_off(note, chan)

        elif msg_type == 0xB0:                # Control Change
            cc_num = message[1]
            value  = message[2]
            if self._on_cc:
                self._on_cc(cc_num, value, chan)

        elif msg_type == 0xE0:                # Pitch Bend
            # 14 bits : LSB (message[1]) + MSB (message[2]), centre = 8192
            bend = ((message[2] << 7) | message[1]) - 8192
            if self._on_pitch_bend:
                self._on_pitch_bend(bend, chan)

    # ------------------------------------------------------------------
    # Utilitaire interne

    def _notify(self, message):
        if self._on_status:
            self._on_status(message)

    # ------------------------------------------------------------------

    def __del__(self):
        self.close()


# ======================================================================
# Test autonome
# ======================================================================

if __name__ == "__main__":
    import time

    def on_note_on(note, vel, chan):
        print(f"  NOTE ON  note={note:3d}  vel={vel:3d}  chan={chan}")

    def on_note_off(note, chan):
        print(f"  NOTE OFF note={note:3d}             chan={chan}")

    def on_cc(cc_num, value, chan):
        print(f"  CC       cc={cc_num:3d}  val={value:3d}  chan={chan}")

    def on_status(msg):
        print(f"[MIDI] {msg}")

    mgr = MidiManager(on_note_on=on_note_on, on_note_off=on_note_off,
                      on_status=on_status, on_cc=on_cc)

    ports = mgr.list_ports()
    print(f"Ports disponibles : {ports}")

    if ports:
        mgr.open(0)
        print("En écoute — Ctrl+C pour quitter")
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        mgr.close()
    else:
        print("Aucun port MIDI — test terminé")
