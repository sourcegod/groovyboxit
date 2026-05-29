#!/usr/bin/env python3
"""
    File: tools/test_loop.py
    Écoute des points de bouclage d'un patch (orgue, cordes, etc.).
    Joue une ou plusieurs notes en boucle et attend Entrée pour passer
    à la suivante — permet de détecter les clics sur les loop points.

    Usage:
        python3 tools/test_loop.py
        python3 tools/test_loop.py --patch /chemin/vers/patch.json
        python3 tools/test_loop.py --note C4 --duration 10

    Date: Thu, 29/05/2026
    Author: Coolbrother
"""
import sys
import os
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sound_device_driver import SoundDeviceDriver
from synth_engine import SynthEngine, note_name_to_midi, midi_to_note_name


PATCH_DEFAULT = "/home/com/groovybox/PATCHS/organ_b3_basic_fast.json"
NOTES_DEFAULT = ["C3", "C4", "C5"]
DURATION_S    = 20   # durée de lecture par note (secondes)


def _loop_diag(sound, sr):
    """Retourne une ligne de diagnostic pour un SdSound bouclant."""
    if sound.loop_start is None:
        return "(one-shot)"
    ls, le, xf = sound.loop_start, sound.loop_end, sound.xf_samples
    llen = le - ls
    llen_ms = llen / sr * 1000
    xf_ms   = xf   / sr * 1000
    return (f"ls={ls} le={le} llen={llen}smp/{llen_ms:.1f}ms "
            f"xf={xf}smp/{xf_ms:.1f}ms")


def play_note(engine, driver, note_name, duration_s):
    midi        = note_name_to_midi(note_name)
    duration_ms = int(duration_s * 1000)
    sound = engine.get_sound(midi, duration_ms=duration_ms)
    if sound is None:
        print(f"  ✗ pas de son pour {note_name} (MIDI {midi})")
        return

    diag = _loop_diag(sound, driver._sr)
    print(f"  ♩ {note_name} (MIDI {midi})  {diag}", flush=True)
    print(f"    → écoute {duration_s}s …", flush=True)
    driver.play(sound, vol=0.8, pan=0)
    time.sleep(duration_s)
    driver.stop_all()
    time.sleep(0.05)


def main():
    ap = argparse.ArgumentParser(
        description="Test écoute des points de bouclage d'un patch."
    )
    ap.add_argument("--patch",    default=PATCH_DEFAULT,
                    help="Chemin vers patch.json")
    ap.add_argument("--notes",    nargs="+", default=NOTES_DEFAULT,
                    metavar="NOTE", help="Notes à jouer (ex: C3 C4 G4)")
    ap.add_argument("--duration", type=float, default=DURATION_S,
                    metavar="SEC", help="Durée par note en secondes")
    ap.add_argument("--interactive", action="store_true",
                    help="Appuyer sur Entrée entre chaque note")
    args = ap.parse_args()

    if not os.path.isfile(args.patch):
        print(f"Patch introuvable : {args.patch}")
        sys.exit(1)

    print(f"\nChargement : {args.patch}")
    driver = SoundDeviceDriver()
    engine = SynthEngine(os.path.dirname(args.patch), driver=driver)
    engine.load_patch(args.patch)
    print(f"Patch chargé : {engine}")

    # Afficher les infos de bouclage
    print("\nPoints de bouclage :")
    for entry in engine._samples:
        s = entry["sampler"]
        if s.is_looping:
            ls_ms = s._loop_start * 1000
            le_ms = s._loop_end   * 1000
            print(f"  root={midi_to_note_name(entry['root_midi']):4s}  "
                  f"loop {ls_ms:.0f}ms → {le_ms:.0f}ms  "
                  f"xf={s._crossfade_ms}ms")
        else:
            print(f"  root={midi_to_note_name(entry['root_midi']):4s}  one-shot")

    print(f"\n{'─'*50}")
    print("Écoute des notes — chercher des clics/discontinuités")
    print(f"{'─'*50}")

    for note in args.notes:
        if args.interactive:
            input(f"\n  [Entrée] pour jouer {note} …")
        play_note(engine, driver, note, args.duration)

    # Pré-calcul de toutes les notes d'une octave pour test rapide
    if not args.interactive:
        print(f"\n{'─'*50}")
        print("Test rapide chromatique C3→C4 (2s par note)")
        print(f"{'─'*50}")
        chromatic = [f"{n}{o}" for o in (3, 4)
                     for n in ("C","C#","D","D#","E","F","F#","G","G#","A","A#","B")]
        for note in chromatic[:13]:
            play_note(engine, driver, note, 2.0)

    driver.close()
    print("\nFin du test.")


if __name__ == "__main__":
    main()
