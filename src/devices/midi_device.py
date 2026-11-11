#python3
"""
    File: src/devices/midi_device.py
    Ports MIDI d'entrée et de sortie, par nom (Phase 8 étape 11d1,
    docs/DESIGN.md § Phase 8 étape 11a H6, H8, H9, H12, H14, H15) : plusieurs
    entrées ouvertes ensemble, sorties ouvertes par nom, note de test (A4
    d'une seconde), écoute de la prochaine note reçue.
    Module AUTONOME du paquet devices (aucun import de l'appli : seulement
    python-rtmidi), réutilisable par d'autres applications MIDI.
    - input_ports(), output_ports() ;
    - MidiInputs(callback) : open_names(noms) → (ouverts, absents), close_all(),
      names, is_open() ; callback(message, nom du port) dans le fil de rtmidi ;
    - open_output(nom) → rtmidi.MidiOut ouvert, ou MidiDeviceError ;
    - send_test_note(out) : A4 (69) d'une seconde, sans attendre ;
    - wait_note(nom, timeout) : prochaine Note On reçue sur ce port ;
    - note_name(69) → « A4 ».
    Date: Wed, 11/11/2026
    Author: Coolbrother
"""
import re
import threading

try:
    import rtmidi
except ImportError:          # appli utilisable sans MIDI
    rtmidi = None

TEST_NOTE     = 69           # A4, 440 Hz
TEST_VELOCITY = 100
TEST_SECONDS  = 1.0
TEST_CHANNEL  = 0
LISTEN_SECONDS = 5.0

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


class MidiDeviceError(Exception):
    """Port introuvable, ou refusé par rtmidi."""


def available():
    """Vrai si python-rtmidi est installé."""
    return rtmidi is not None


def note_name(note):
    """Nom anglais d'une note MIDI, octave 4 = do central (60 → « C4 »,
    69 → « A4 »)."""
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------

def input_ports():
    """Noms des ports MIDI d'entrée (relus à chaque appel)."""
    if rtmidi is None:
        return []
    return list(rtmidi.MidiIn().get_ports())


def output_ports():
    """Noms des ports MIDI de sortie (relus à chaque appel)."""
    if rtmidi is None:
        return []
    return list(rtmidi.MidiOut().get_ports())


# Sous ALSA, rtmidi termine le nom par « client:port » (« … MIDI 1 20:0 ») :
# numéros donnés au branchement, qui peuvent changer. Un nom enregistré
# retrouve son port même si ces numéros ont changé.
_ALSA_ADDRESS = re.compile(r"\s+\d+:\d+$")


def base_name(name):
    """Nom sans l'adresse ALSA finale (« MPK mini Plus:MPK mini Plus MIDI 1 »)."""
    return _ALSA_ADDRESS.sub("", name)


def _index(ports, name):
    """Indice du port nommé : nom exact d'abord, sinon même nom sans
    l'adresse ALSA (numéros changés au rebranchement) ; None sinon."""
    if name in ports:
        return ports.index(name)
    base = base_name(name)
    for i, port in enumerate(ports):
        if base_name(port) == base:
            return i
    return None


def find_port(ports, name):
    """Nom actuel du port qui correspond à name (même règle que _index),
    ou None."""
    idx = _index(ports, name)
    return None if idx is None else ports[idx]


# ---------------------------------------------------------------------------
# Entrées : plusieurs ports ouverts ensemble
# ---------------------------------------------------------------------------

class MidiInputs:
    """Ports d'entrée ouverts ensemble ; chaque message va à
    callback(message, nom du port), dans le fil de rtmidi. Les messages
    système exclusif, d'horloge et de détection active sont ignorés."""

    def __init__(self, callback):
        self._callback = callback
        self._ports = {}                 # nom → rtmidi.MidiIn

    @property
    def names(self):
        """Noms des ports ouverts, dans l'ordre d'ouverture."""
        return list(self._ports)

    def is_open(self):
        return bool(self._ports)

    def open_names(self, names):
        """Ouvre les ports nommés (ceux déjà ouverts sont gardés). Retourne
        (ouverts, absents) : listes de noms ; un port refusé par rtmidi
        compte comme absent."""
        if rtmidi is None:
            return [], list(names)
        ports = input_ports()
        opened, missing = [], []
        for name in names:
            if name in self._ports:
                opened.append(name)
                continue
            idx = _index(ports, name)
            if idx is None:
                missing.append(name)
                continue
            midi_in = rtmidi.MidiIn()
            try:
                midi_in.open_port(idx)
            except Exception:            # rtmidi.SystemError, InvalidPortError…
                missing.append(name)
                continue
            midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
            midi_in.set_callback(self._on_message, name)
            self._ports[name] = midi_in
            opened.append(name)
        return opened, missing

    def close(self, name):
        midi_in = self._ports.pop(name, None)
        if midi_in is not None:
            midi_in.cancel_callback()
            midi_in.close_port()

    def close_all(self):
        for name in list(self._ports):
            self.close(name)

    def _on_message(self, event, name):
        message, _delta = event
        if message:
            self._callback(message, name)


# ---------------------------------------------------------------------------
# Sorties
# ---------------------------------------------------------------------------

def open_output(name):
    """rtmidi.MidiOut ouvert sur le port nommé ; MidiDeviceError s'il est
    introuvable ou refusé."""
    if rtmidi is None:
        raise MidiDeviceError("python-rtmidi absent")
    idx = _index(output_ports(), name)
    if idx is None:
        raise MidiDeviceError(f"port de sortie introuvable : {name}")
    out = rtmidi.MidiOut()
    try:
        out.open_port(idx)
    except Exception as e:
        raise MidiDeviceError(str(e)) from e
    return out


def send_test_note(out, note=TEST_NOTE, velocity=TEST_VELOCITY,
                   seconds=TEST_SECONDS, channel=TEST_CHANNEL):
    """Note On tout de suite, Note Off après seconds (minuterie), sans
    attendre ; retourne la minuterie. out : tout objet qui a
    send_message(liste d'octets)."""
    out.send_message([0x90 | channel, note, velocity])
    timer = threading.Timer(seconds, out.send_message, args=([0x80 | channel, note, 0],))
    timer.daemon = True
    timer.start()
    return timer


# ---------------------------------------------------------------------------
# Écoute de la prochaine note
# ---------------------------------------------------------------------------

def is_note_on(message):
    return len(message) >= 3 and message[0] & 0xF0 == 0x90 and message[2] > 0


def wait_note(name, timeout=LISTEN_SECONDS):
    """Attend (bloquant) la prochaine Note On reçue sur le port d'entrée
    nommé ; retourne (note, vélocité, canal), ou None après timeout.
    Ouvre son propre accès au port : sous ALSA, un port déjà ouvert par
    l'appli peut l'être une seconde fois. MidiDeviceError si le port est
    introuvable ou refusé."""
    got = threading.Event()
    result = []

    def on_message(message, _port):
        if not result and is_note_on(message):
            result.append((message[1], message[2], message[0] & 0x0F))
            got.set()

    inputs = MidiInputs(on_message)
    opened, missing = inputs.open_names([name])
    if missing:
        raise MidiDeviceError(f"port d'entrée introuvable : {name}")
    try:
        got.wait(timeout)
    finally:
        inputs.close_all()
    return result[0] if result else None
