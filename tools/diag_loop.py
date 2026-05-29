#!/usr/bin/env python3
"""
    File: tools/diag_loop.py
    Diagnostic des points de bouclage sans lecture audio.
    Pour chaque note, récupère les valeurs des samples aux positions critiques
    et calcule des métriques prédictives de clics/battements.

    Métriques
    ---------
    amp_ls     : |data[ls]|         — amplitude au début de boucle (→ 0 idéal)
    amp_le1    : |data[le-1]|       — amplitude avant le saut (→ 0 idéal)
    jump       : |data[le-1] - data[ls]|  — discontinuité brute au saut
    corr_loop    : corrélation de Pearson entre data[le-xf:le] et data[ls-xf:ls]
                 → 1.0 = signaux en phase (aucun battement)
                 → < 0.9 = battement probable
    frac_period: reste fractionnaire (le-ls)/période (→ 0 idéal)

    Usage:
        python3 tools/diag_loop.py
        python3 tools/diag_loop.py --patch /chemin/patch.json
        python3 tools/diag_loop.py --notes C3 G4 F5 G5 A5 C6
        python3 tools/diag_loop.py --all    # toutes les notes C0..C8

    Date: Thu, 29/05/2026
    Author: Coolbrother
"""
import sys
import os
import argparse
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from audio_tools import AudioTools
from sound_device_driver import SoundDeviceDriver
from synth_engine import SynthEngine, note_name_to_midi, midi_to_note_name, scale_midi_notes

PATCH_DEFAULT = "/home/com/groovybox/PATCHS/organ_b3_basic_fast.json"
NOTES_DEFAULT = ["C3", "D3", "E3", "F3", "G3", "A3", "B3",
                 "C4", "D4", "E4", "F4", "G4", "A4", "B4",
                 "C5", "D5", "E5", "F5", "G5", "A5", "B5",
                 "C6"]

# Seuils de risque
THRESH_JUMP    = 0.05   # |data[le-1] - data[ls]| > seuil → risque clic
THRESH_AMP     = 0.05   # |data[ls]| ou |data[le-1]| > seuil → pas sur un zéro
THRESH_CORR    = 0.90   # corrélation < seuil → risque battement
THRESH_FRAC    = 0.05   # reste fractionnaire > seuil → risque battement


# ---------------------------------------------------------------------------
# Métriques
# ---------------------------------------------------------------------------

def pearson_corr(a, b):
    """Corrélation de Pearson entre deux tableaux 1D."""
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    a = a - np.mean(a)
    b = b - np.mean(b)
    denom = np.std(a) * np.std(b)
    if denom < 1e-12:
        return float("nan")
    return float(np.mean(a * b) / denom)


def diag_note(engine, midi, xf_default=None):
    """Calcule les métriques de boucle pour une note MIDI.

    Retourne un dict ou None si le son n'est pas bouclant.
    """
    entry = engine._find_nearest_sample(midi)
    if entry is None or not entry["sampler"]._looping:
        return None

    n_steps = midi - entry["root_midi"]
    pitched = engine._get_pitched_sampler(midi)
    if pitched is None or not pitched._looping:
        return None

    sr   = pitched.samplerate
    data = pitched.data
    mono = data[:, 0]

    ls, le, xf = pitched.get_loop_params()
    if ls is None or le <= ls:
        return None
    llen = le - ls

    # ── Valeurs aux points critiques ─────────────────────────────────────
    amp_ls  = float(abs(mono[ls]))   if ls   < len(mono) else float("nan")
    amp_le1 = float(abs(mono[le-1])) if le-1 < len(mono) else float("nan")
    jump    = float(abs(mono[le-1] - mono[ls])) \
              if (le-1 < len(mono) and ls < len(mono)) else float("nan")

    # ── Corrélation DANS la boucle : data[le-P:le] vs data[ls:ls+P] ─────
    # Mesure si le signal est périodique (même phase) au point de jonction.
    # On utilise une période dans la ZONE DE BOUCLE (sustain, non attaque).
    period = AudioTools.find_fundamental_period(data, sr)
    if period and period >= 4:
        P = min(int(period * 2), llen // 2)   # 2 périodes max, dans la boucle
        if P >= 2 and le - P >= ls and ls + P <= le:
            corr = pearson_corr(mono[le - P : le], mono[ls : ls + P])
        else:
            corr = float("nan")
        frac = (llen / period) % 1.0
        frac = min(frac, 1.0 - frac)
    else:
        corr   = float("nan")
        frac   = float("nan")
        period = None

    return {
        "midi":        midi,
        "note":        midi_to_note_name(midi),
        "root":        midi_to_note_name(entry["root_midi"]),
        "n_steps":     n_steps,
        "ls":          ls,
        "le":          le,
        "llen":        llen,
        "llen_ms":     llen / sr * 1000,
        "xf":          xf,
        "xf_ms":       xf / sr * 1000,
        "period":      period,
        "amp_ls":      amp_ls,
        "amp_le1":     amp_le1,
        "jump":        jump,
        "corr_loop":   corr,
        "frac_period": frac,
    }


def risk_str(m):
    """Génère une chaine de risques en rouge ASCII."""
    risks = []
    if not np.isnan(m["amp_ls"])  and m["amp_ls"]  > THRESH_AMP:
        risks.append("amp_ls")
    if not np.isnan(m["amp_le1"]) and m["amp_le1"] > THRESH_AMP:
        risks.append("amp_le1")
    if not np.isnan(m["jump"])    and m["jump"]    > THRESH_JUMP:
        risks.append("JUMP")
    if not np.isnan(m["corr_loop"])    and m["corr_loop"]    < THRESH_CORR:
        risks.append("corr↓")
    if not np.isnan(m["frac_period"]) and m["frac_period"] > THRESH_FRAC:
        risks.append("frac")
    return ", ".join(risks) if risks else "OK"


def fmt(v, fmt_str=".4f"):
    return f"{v:{fmt_str}}" if not np.isnan(v) else "  n/a "


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Diagnostic des points de bouclage (valeurs samples, corrélation, période)."
    )
    ap.add_argument("--patch", default=PATCH_DEFAULT,
                    help="Chemin vers patch.json")
    ap.add_argument("--notes", nargs="+", default=NOTES_DEFAULT,
                    metavar="NOTE", help="Notes à analyser")
    ap.add_argument("--all", action="store_true",
                    help="Analyser toutes les notes C0..C8 (chromatique)")
    args = ap.parse_args()

    if not os.path.isfile(args.patch):
        print(f"Patch introuvable : {args.patch}")
        sys.exit(1)

    notes = args.notes
    if args.all:
        note_names = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
        notes = [f"{n}{o}" for o in range(0, 9) for n in note_names]

    # Charger le patch (driver muet — pas de sortie audio)
    driver = SoundDeviceDriver()
    engine = SynthEngine(os.path.dirname(args.patch), driver=driver)
    engine.load_patch(args.patch)
    print(f"\nPatch : {engine}")
    print(f"Seuils : jump>{THRESH_JUMP}  amp>{THRESH_AMP}  "
          f"corr<{THRESH_CORR}  frac>{THRESH_FRAC}\n")

    hdr = (f"{'Note':>5} {'Root':>5} {'st':>3}  "
           f"{'ls':>7} {'le':>7} {'llen_ms':>8}  "
           f"{'amp_ls':>7} {'amp_le1':>7} {'jump':>7}  "
           f"{'corr_loop':>8} {'frac':>6}  risque")
    print(hdr)
    print("─" * len(hdr))

    ok_count   = 0
    risk_count = 0

    for note_name in notes:
        try:
            midi = note_name_to_midi(note_name)
        except Exception:
            continue

        m = diag_note(engine, midi)
        if m is None:
            continue

        r = risk_str(m)
        tag = "✓" if r == "OK" else "✗"
        print(f"{tag} {m['note']:>4} {m['root']:>5} {m['n_steps']:>+3}  "
              f"{m['ls']:>7} {m['le']:>7} {m['llen_ms']:>7.1f}ms  "
              f"{fmt(m['amp_ls']):>7} {fmt(m['amp_le1']):>7} {fmt(m['jump']):>7}  "
              f"{fmt(m['corr_loop']):>8} {fmt(m['frac_period'], '.4f'):>6}  {r}")

        if r == "OK":
            ok_count   += 1
        else:
            risk_count += 1

    print("─" * len(hdr))
    print(f"\n{ok_count} notes propres, {risk_count} notes à risque\n")

    driver.close()


if __name__ == "__main__":
    main()
