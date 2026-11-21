#python3
"""
    File: src/audio/audio_beep.py
    Bips en dents de scie ou en onde carrée (Phase 8 étape 20b1, docs/DESIGN.md § Phase 8
    étape 20a, B0-B3) : plus audibles qu'un sinus ; carré par défaut, comme
    le bip historique du PC (haut-parleur interne, choisi à l'essai).
    Module AUTONOME (aucun import de l'appli : numpy seulement, sounddevice
    seulement par play() sans lecteur fourni), réutilisable par d'autres
    applications.
    - saw(freq, seconds, samplerate, level) : dents de scie à bande limitée
      (harmoniques sous Nyquist, amplitude 1/k : ni repliement ni
      sifflement), fondus aux deux bouts (sans clic) ;
    - square(…) : onde carrée à bande limitée (harmoniques impaires, 1/k) ;
    - beep(notes, samplerate, level, wave) : notes enchaînées, stéréo
      float32 ; wave = SAW ou SQUARE (WAVE par défaut) ;
    - ALERT (alertes et questions : montant), CONFIRM (confirmation, départ
      du test de l'entrée : descendant) — B0, sens à l'essai ;
    - duration(notes) ; play(notes, samplerate, player=None, device=None).
    Une note = (fréquence en Hz, durée en secondes).
    Écoute : python3 -m audio.audio_beep [alert|confirm] [saw|square]
    (depuis src/ ; sans argument : les quatre, pour comparer).
    Prototype Python, cible C/C++ comme le reste du moteur audio.
    Date: Fri, 20/11/2026
    Author: Coolbrother
"""
import math

import numpy as np

LEVEL   = 0.25          # crête d'environ −12 dBFS (dents de scie)
# Carré : crête plus basse, même niveau moyen (RMS) que les dents de scie —
# essai de 20d1 : le carré à la même crête était un peu fort aux haut-parleurs
SQUARE_LEVEL = 0.15
FADE_MS = 5.0           # fondu aux deux bouts de chaque note
NOTE_SECONDS = 0.12

SAW, SQUARE = "saw", "square"
WAVE = SQUARE           # forme d'onde par défaut (essai de 20b1 : carré, au même niveau de crête)

LOW, HIGH = 880.0, 1318.51          # La 5, Mi 6 (quinte)
ALERT   = ((LOW, NOTE_SECONDS), (HIGH, NOTE_SECONDS))      # montant
CONFIRM = ((HIGH, NOTE_SECONDS), (LOW, NOTE_SECONDS))      # descendant


def _band_limited(freq, seconds, samplerate, level, fade_ms, odd_only):
    """Somme des harmoniques k (impaires seulement si odd_only) sous Nyquist,
    amplitude 1/k, crête ramenée à level, fondus de fade_ms aux deux bouts."""
    n = int(round(samplerate * seconds))
    if n <= 0:
        return np.zeros(0)
    t = np.arange(n, dtype=np.float64) / samplerate
    wave = np.zeros(n)
    k = 1
    while k * freq < samplerate / 2.0:
        wave += np.sin(2.0 * math.pi * k * freq * t) / k
        k += 2 if odd_only else 1
    peak = float(np.max(np.abs(wave))) or 1.0
    wave *= level / peak
    fade = min(n // 2, int(samplerate * fade_ms / 1000.0))
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade)
        wave[:fade] *= ramp
        wave[n - fade:] *= ramp[::-1]
    return wave


def saw(freq, seconds, samplerate=44100, level=LEVEL, fade_ms=FADE_MS):
    """Dents de scie à bande limitée, mono float64, crête ≈ level."""
    return _band_limited(freq, seconds, samplerate, level, fade_ms, odd_only=False)


def square(freq, seconds, samplerate=44100, level=LEVEL, fade_ms=FADE_MS):
    """Onde carrée à bande limitée (harmoniques impaires), mono, crête ≈ level."""
    return _band_limited(freq, seconds, samplerate, level, fade_ms, odd_only=True)


_WAVES = {SAW: saw, SQUARE: square}


def default_level(wave=None):
    """Crête par défaut de la forme d'onde (même niveau moyen pour les deux)."""
    return SQUARE_LEVEL if (wave or WAVE) == SQUARE else LEVEL


def beep(notes=ALERT, samplerate=44100, level=None, wave=None):
    """Notes enchaînées en stéréo float32 contigu (frames, 2) ; wave : SAW
    ou SQUARE (None = WAVE) ; level : crête (None = default_level)."""
    gen = _WAVES[wave or WAVE]
    level = default_level(wave) if level is None else level
    parts = [gen(f, s, samplerate, level) for f, s in notes]
    mono = np.concatenate(parts) if parts else np.zeros(0)
    return np.ascontiguousarray(np.column_stack([mono, mono]).astype(np.float32))


def duration(notes):
    """Durée totale en secondes."""
    return float(sum(s for _f, s in notes))


def play(notes=ALERT, samplerate=44100, player=None, device=None, level=None,
         wave=None):
    """Joue le bip sans attendre : player(données, fréquence) s'il est fourni
    (le pilote d'une appli, sortie déjà ouverte), sinon sounddevice.play sur
    device (None = sortie par défaut). Les erreurs remontent à l'appelant."""
    data = beep(notes, samplerate, level, wave)
    if player is not None:
        player(data, samplerate)
    else:
        import sounddevice as sd
        sd.play(data, samplerate=samplerate, device=device)
    return data


def main(argv=None):
    """Écoute des bips : [alert|confirm] [saw|square] ; sans argument, les
    quatre (alerte puis confirmation, dents de scie puis carrée)."""
    import sys
    import time
    import sounddevice as sd
    args = list(sys.argv[1:] if argv is None else argv)
    kinds = [a for a in args if a in ("alert", "confirm")] or ["alert", "confirm"]
    waves = [a for a in args if a in (SAW, SQUARE)] or [SAW, SQUARE]
    named = {"alert": ALERT, "confirm": CONFIRM}
    for wave in waves:
        for kind in kinds:
            print(f"{kind} — {wave}")
            play(named[kind], wave=wave)
            sd.wait()
            time.sleep(0.8)


if __name__ == "__main__":
    main()
