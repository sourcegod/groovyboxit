#python3
"""
    File: src/midi/midi_constants.py
    Tables de description MIDI pures (aucune dépendance rtmidi/wx) :
    noms des Control Change, noms des patchs General MIDI 1,
    noms des kits de batterie General MIDI 2.
    Date: Mon, 21/09/2026
    Author: Coolbrother
"""

# Noms des Control Change standard MIDI 1.0 (CC non listés : sans nom).
# Déplacé depuis src/ui/midi_handler.py (Phase 7 étape 2b).
CC_NAMES = {
    0: "Bank Select", 1: "Modulation Wheel", 2: "Breath Controller",
    4: "Foot Controller", 5: "Portamento Time", 6: "Data Entry MSB",
    7: "Channel Volume", 8: "Balance", 10: "Pan", 11: "Expression Controller",
    12: "Effect Control 1", 13: "Effect Control 2",
    16: "General Purpose 1", 17: "General Purpose 2",
    18: "General Purpose 3", 19: "General Purpose 4",
    32: "Bank Select LSB", 33: "Modulation Wheel LSB",
    34: "Breath Controller LSB", 36: "Foot Controller LSB",
    37: "Portamento Time LSB", 38: "Data Entry LSB",
    39: "Channel Volume LSB", 40: "Balance LSB", 42: "Pan LSB",
    43: "Expression Controller LSB",
    64: "Sustain Pedal", 65: "Portamento On/Off", 66: "Sostenuto",
    67: "Soft Pedal", 68: "Legato Footswitch", 69: "Hold 2",
    70: "Sound Variation", 71: "Timbre/Harmonic Intensity",
    72: "Release Time", 73: "Attack Time", 74: "Brightness",
    75: "Sound Controller 6", 76: "Sound Controller 7",
    77: "Sound Controller 8", 78: "Sound Controller 9",
    79: "Sound Controller 10",
    80: "General Purpose 5", 81: "General Purpose 6",
    82: "General Purpose 7", 83: "General Purpose 8",
    84: "Portamento Control", 88: "High Resolution Velocity Prefix",
    91: "Reverb Depth", 92: "Tremolo Depth", 93: "Chorus Depth",
    94: "Detune Depth", 95: "Phaser Depth",
    96: "Data Increment", 97: "Data Decrement",
    98: "NRPN LSB", 99: "NRPN MSB", 100: "RPN LSB", 101: "RPN MSB",
    120: "All Sound Off", 121: "Reset All Controllers", 122: "Local Control",
    123: "All Notes Off", 124: "Omni Mode Off", 125: "Omni Mode On",
    126: "Mono Mode On", 127: "Poly Mode On",
}


# Les 128 noms de patch General MIDI 1 (program number 0-127, index = program).
GM_PATCH_NAMES = [
    # Piano (0-7)
    "Acoustic Grand Piano", "Bright Acoustic Piano", "Electric Grand Piano",
    "Honky-tonk Piano", "Electric Piano 1", "Electric Piano 2",
    "Harpsichord", "Clavinet",
    # Chromatic Percussion (8-15)
    "Celesta", "Glockenspiel", "Music Box", "Vibraphone",
    "Marimba", "Xylophone", "Tubular Bells", "Dulcimer",
    # Organ (16-23)
    "Drawbar Organ", "Percussive Organ", "Rock Organ", "Church Organ",
    "Reed Organ", "Accordion", "Harmonica", "Tango Accordion",
    # Guitar (24-31)
    "Acoustic Guitar (nylon)", "Acoustic Guitar (steel)",
    "Electric Guitar (jazz)", "Electric Guitar (clean)",
    "Electric Guitar (muted)", "Overdriven Guitar",
    "Distortion Guitar", "Guitar Harmonics",
    # Bass (32-39)
    "Acoustic Bass", "Electric Bass (finger)", "Electric Bass (pick)",
    "Fretless Bass", "Slap Bass 1", "Slap Bass 2",
    "Synth Bass 1", "Synth Bass 2",
    # Strings (40-47)
    "Violin", "Viola", "Cello", "Contrabass",
    "Tremolo Strings", "Pizzicato Strings", "Orchestral Harp", "Timpani",
    # Ensemble (48-55)
    "String Ensemble 1", "String Ensemble 2", "Synth Strings 1",
    "Synth Strings 2", "Choir Aahs", "Voice Oohs", "Synth Voice",
    "Orchestra Hit",
    # Brass (56-63)
    "Trumpet", "Trombone", "Tuba", "Muted Trumpet",
    "French Horn", "Brass Section", "Synth Brass 1", "Synth Brass 2",
    # Reed (64-71)
    "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax",
    "Oboe", "English Horn", "Bassoon", "Clarinet",
    # Pipe (72-79)
    "Piccolo", "Flute", "Recorder", "Pan Flute",
    "Blown Bottle", "Shakuhachi", "Whistle", "Ocarina",
    # Synth Lead (80-87)
    "Lead 1 (square)", "Lead 2 (sawtooth)", "Lead 3 (calliope)",
    "Lead 4 (chiff)", "Lead 5 (charang)", "Lead 6 (voice)",
    "Lead 7 (fifths)", "Lead 8 (bass + lead)",
    # Synth Pad (88-95)
    "Pad 1 (new age)", "Pad 2 (warm)", "Pad 3 (polysynth)",
    "Pad 4 (choir)", "Pad 5 (bowed)", "Pad 6 (metallic)",
    "Pad 7 (halo)", "Pad 8 (sweep)",
    # Synth Effects (96-103)
    "FX 1 (rain)", "FX 2 (soundtrack)", "FX 3 (crystal)",
    "FX 4 (atmosphere)", "FX 5 (brightness)", "FX 6 (goblins)",
    "FX 7 (echoes)", "FX 8 (sci-fi)",
    # Ethnic (104-111)
    "Sitar", "Banjo", "Shamisen", "Koto",
    "Kalimba", "Bag pipe", "Fiddle", "Shanai",
    # Percussive (112-119)
    "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock",
    "Taiko Drum", "Melodic Tom", "Synth Drum", "Reverse Cymbal",
    # Sound Effects (120-127)
    "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet",
    "Telephone Ring", "Helicopter", "Applause", "Gunshot",
]


# Noms des kits de batterie General MIDI 2 par program number (0-127),
# sélectionnés sur le canal percussion (généralement canal 10) via
# Program Change. Seuls certains index ont un nom standard GM2 ; les
# autres restent l'entier lui-même (pas de nom défini par le standard).
GM2_DRUMKIT_NAMES = list(range(128))
GM2_DRUMKIT_NAMES[0]  = "Standard Kit"
GM2_DRUMKIT_NAMES[8]  = "Room Kit"
GM2_DRUMKIT_NAMES[16] = "Power Kit"
GM2_DRUMKIT_NAMES[24] = "Electronic Kit"
GM2_DRUMKIT_NAMES[25] = "TR-808 Kit"
GM2_DRUMKIT_NAMES[32] = "Jazz Kit"
GM2_DRUMKIT_NAMES[40] = "Brush Kit"
GM2_DRUMKIT_NAMES[48] = "Orchestra Kit"
GM2_DRUMKIT_NAMES[56] = "SFX Kit"
