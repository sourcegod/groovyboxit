#python3
"""
    File: src/midi_parser.py
    Parser MIDI dédié : décodage bas niveau des messages temps réel
    (Note On/Off, Control Change, Program Change, Pitch Bend) et
    fonctions de description texte (notes, CC, programs GM). Aucune
    dépendance à rtmidi ni wx — pur et testable sans port MIDI ni
    interface graphique.

    CVoice/CMeta : taxonomie des statuts MIDI temps réel et des
    méta-événements de fichier SMF (.mid) — double emploi, seul CVoice
    est décodé dans ce chantier (Phase 7 étape 2d), CMeta pose les
    fondations pour un futur import/export .mid.
    Date: Mon, 21/09/2026
    Author: Coolbrother
"""
from synth_engine import midi_to_note_name
from midi.midi_constants import CC_NAMES, GM_PATCH_NAMES, GM2_DRUMKIT_NAMES


class CVoice:
    NoteOff               = 0x80
    NoteOn                = 0x90
    PolyphonicKeyPressure = 0xA0   # note aftertouch
    ControllerChange      = 0xB0
    ProgramChange         = 0xC0
    ChannelPressure       = 0xD0
    PitchBend             = 0xE0


class CMeta:
    FileMetaEvent              = 0xFF
    SMPTEOffsetMetaEvent       = 0x54
    SystemExclusive            = 0xF0
    SystemExclusivePacket      = 0xF7
    SequenceNumber             = 0x00
    TextMetaEvent              = 0x01
    CopyrightMetaEvent         = 0x02
    TrackName                  = 0x03
    InstrumentName             = 0x04
    Lyric                      = 0x05
    Marker                     = 0x06
    CuePoint                   = 0x07
    ChannelPrefix              = 0x20
    MidiPort                   = 0x21
    EndTrack                   = 0x2F
    SetTempo                   = 0x51
    TimeSignature              = 0x58
    KeySignature               = 0x59
    SequencerSpecificMetaEvent = 0x7F


class MidiMessage:
    """Message MIDI décodé : mtype (constante CVoice), channel (0-15),
    payload (champs propres au type — {"note":,"vel":} pour NoteOn/NoteOff,
    {"cc_num":,"value":} pour ControllerChange, {"program":} pour
    ProgramChange, {"bend":} pour PitchBend)."""

    __slots__ = ("mtype", "channel", "payload")

    def __init__(self, mtype, channel, payload=None):
        self.mtype   = mtype
        self.channel = channel
        self.payload = dict(payload) if payload is not None else {}

    def __eq__(self, other):
        if not isinstance(other, MidiMessage):
            return NotImplemented
        return (self.mtype == other.mtype and self.channel == other.channel
                and self.payload == other.payload)

    def __repr__(self):
        return (f"MidiMessage(mtype={self.mtype:#04x}, channel={self.channel!r}, "
                f"payload={self.payload!r})")


def decode_message(data):
    """Décode un message MIDI brut (liste/bytes d'octets, status en premier)
    en MidiMessage. Reconnaît Note On, Note Off, Control Change, Program
    Change, Pitch Bend. Retourne None pour tout autre statut (Poly
    Aftertouch, Channel Pressure, Meta/SysEx : constantes CVoice/CMeta
    posées mais décodage hors périmètre de ce chantier) ou si `data` est
    vide/tronqué pour son type. Ne réinterprète pas Note On vel=0 en Note
    Off : décodage littéral, laissé à l'appelant."""
    if not data:
        return None

    status = data[0]
    mtype  = status & 0xF0
    chan   = status & 0x0F

    if mtype == CVoice.NoteOn:
        if len(data) < 3:
            return None
        return MidiMessage(CVoice.NoteOn, chan, {"note": data[1], "vel": data[2]})

    if mtype == CVoice.NoteOff:
        if len(data) < 3:
            return None
        return MidiMessage(CVoice.NoteOff, chan, {"note": data[1], "vel": data[2]})

    if mtype == CVoice.ControllerChange:
        if len(data) < 3:
            return None
        return MidiMessage(CVoice.ControllerChange, chan,
                            {"cc_num": data[1], "value": data[2]})

    if mtype == CVoice.ProgramChange:
        if len(data) < 2:
            return None
        return MidiMessage(CVoice.ProgramChange, chan, {"program": data[1]})

    if mtype == CVoice.PitchBend:
        if len(data) < 3:
            return None
        # 14 bits : LSB (data[1]) + MSB (data[2]), centre = 8192
        bend = ((data[2] << 7) | data[1]) - 8192
        return MidiMessage(CVoice.PitchBend, chan, {"bend": bend})

    return None


# ---------------------------------------------------------------------------
# Descriptions texte (statut live, UI) — tables dans midi_constants.py
# ---------------------------------------------------------------------------

def describe_note(note):
    """60 -> 'C4'. Délègue à synth_engine (pas de table dupliquée)."""
    return midi_to_note_name(note)


def describe_cc(cc_num):
    """Nom standard MIDI 1.0 du CC, ou None si non répertorié."""
    return CC_NAMES.get(cc_num)


def describe_program(program, is_drum=False):
    """Nom General MIDI du program : patch mélodique (GM1) ou kit de
    batterie (GM2) si is_drum. is_drum n'est jamais deviné ici — c'est
    l'appelant qui sait qu'un canal/piste est un kit de batterie
    (typiquement canal 10). Retourne None si program hors 0-127 ou si
    l'index n'a pas de nom défini (kit GM2 non standard)."""
    table = GM2_DRUMKIT_NAMES if is_drum else GM_PATCH_NAMES
    if program < 0 or program >= len(table):
        return None
    name = table[program]
    return name if isinstance(name, str) else None
