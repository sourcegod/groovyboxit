#python3
"""
    python3 -m devices [--tone NOM] [--input NOM] [--pilote NOM]
                       [--note PORT] [--listen PORT]
    Liste les pilotes et les périphériques audio vus par PortAudio, puis les
    ports MIDI, par nom ; --tone joue le La 440 Hz d'une seconde sur une
    sortie audio, --input mesure la crête d'une entrée audio pendant une
    seconde (Phase 8 étape 11b1) ; --note envoie un A4 d'une seconde sur une
    sortie MIDI, --listen attend la prochaine note d'une entrée MIDI
    pendant 5 secondes (Phase 8 étape 11d1).
    À lancer depuis src/ : cd src && python3 -m devices
    Date: Wed, 11/11/2026
    Author: Coolbrother
"""
import argparse
import sys
import time

from devices import audio_device as audio
from devices import midi_device as midi


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m devices",
                                     description="Périphériques audio vus par PortAudio.")
    parser.add_argument("--pilote", default="", help="pilote (défaut : celui de la sortie par défaut)")
    parser.add_argument("--tone", metavar="SORTIE", help="joue le La 440 Hz d'une seconde")
    parser.add_argument("--input", metavar="ENTRÉE", help="crête d'une seconde d'écoute")
    parser.add_argument("--note", metavar="PORT", help="A4 d'une seconde sur une sortie MIDI")
    parser.add_argument("--listen", metavar="PORT", help="prochaine note d'une entrée MIDI")
    args = parser.parse_args(argv)

    if args.note or args.listen:
        return _midi(args)

    api = args.pilote or audio.default_hostapi()
    if not (args.tone or args.input):
        print("Pilotes :", ", ".join(audio.hostapis()) or "aucun",
              f"(défaut : {audio.default_hostapi() or 'aucun'})")
        for name in audio.hostapis():
            print(f"\n== {name} ==")
            for kind, label in ((audio.INPUT, "Entrées"), (audio.OUTPUT, "Sorties")):
                default = audio.default_device(name, kind)
                print(f"{label} ({len(audio.devices(name, kind))}) :")
                for dev in audio.devices(name, kind):
                    print(f"  - {dev}" + ("  [défaut]" if dev == default else ""))
        if midi.available():
            print("\n== MIDI ==")
            for label, ports in (("Entrées", midi.input_ports()), ("Sorties", midi.output_ports())):
                print(f"{label} ({len(ports)}) :")
                for port in ports:
                    print(f"  - {port}")
        else:
            print("\nMIDI : python-rtmidi absent")
        return 0
    try:
        if args.tone:
            idx = audio.find_device(args.tone, api, audio.OUTPUT)
            if idx is None:
                print(f"Sortie « {args.tone} » introuvable dans {api}")
                return 1
            audio.play_tone(idx)
            time.sleep(audio.TONE_SECONDS + 0.2)
            print(f"La 440 Hz joué sur « {args.tone} »")
        if args.input:
            idx = audio.find_device(args.input, api, audio.INPUT)
            if idx is None:
                print(f"Entrée « {args.input} » introuvable dans {api}")
                return 1
            print(f"Entrée « {args.input} » : crête {audio.format_db(audio.input_peak_db(idx))}")
    except audio.AudioDeviceError as e:
        print(f"Refusé par PortAudio : {e}")
        return 1
    return 0


def _midi(args):
    try:
        if args.note:
            out = midi.open_output(args.note)
            timer = midi.send_test_note(out)
            timer.join()
            out.close_port()
            print(f"Note {midi.note_name(midi.TEST_NOTE)} envoyée sur « {args.note} »")
        if args.listen:
            print(f"Joue une note sur « {args.listen} » (5 secondes)…")
            got = midi.wait_note(args.listen)
            if got is None:
                print("Aucune note reçue")
            else:
                note, vel, chan = got
                print(f"Note {midi.note_name(note)}, vélocité {vel}, canal {chan + 1}")
    except midi.MidiDeviceError as e:
        print(f"MIDI : {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
