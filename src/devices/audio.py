#python3
"""
    File: src/devices/audio.py
    Pilotes et périphériques audio de PortAudio, par nom (Phase 8 étape
    11b1, docs/DESIGN.md § Phase 8 étape 11a H1-H5, H12-H16) : les numéros
    de PortAudio changent d'un lancement à l'autre, les noms restent.
    Module AUTONOME du paquet devices (aucun import de l'appli : seulement
    sounddevice et numpy), réutilisable par d'autres applications audio.
    - hostapis(), devices(hostapi, kind), default_device(hostapi, kind),
      find_device(name, hostapi, kind) ;
    - rescan() : relit les périphériques (carte branchée après le lancement)
      — PortAudio est réinitialisé : tout flux ouvert doit être arrêté avant ;
    - tone() : La 440 Hz d'une seconde (bouton Tester de la sortie) ;
      play_tone(device) ; input_peak_db(device) (Tester de l'entrée).
    kind : "input" ou "output". Prototype Python, cible C/C++ comme le reste
    du moteur audio.
    Date: Wed, 11/11/2026
    Author: Coolbrother
"""
import math

import numpy as np
import sounddevice as sd

INPUT, OUTPUT = "input", "output"
_CHANNELS = {INPUT: "max_input_channels", OUTPUT: "max_output_channels"}

TONE_FREQ    = 440.0      # La 440 Hz
TONE_SECONDS = 1.0
TONE_LEVEL   = 0.3        # environ −10 dBFS, fondu de 10 ms aux deux bouts
INPUT_SECONDS = 1.0


class AudioDeviceError(Exception):
    """Périphérique introuvable, ou refusé par PortAudio."""


# ---------------------------------------------------------------------------
# Pilotes et périphériques
# ---------------------------------------------------------------------------

def hostapis():
    """Noms des pilotes de PortAudio (« ALSA », « OSS »…), dans l'ordre."""
    return [h["name"] for h in sd.query_hostapis()]


def default_hostapi():
    """Pilote du périphérique de sortie par défaut ; à défaut, le premier."""
    try:
        out = sd.default.device[1]
        if out is not None and out >= 0:
            return sd.query_hostapis(sd.query_devices(out)["hostapi"])["name"]
    except (sd.PortAudioError, ValueError, IndexError, TypeError):
        pass
    names = hostapis()
    return names[0] if names else ""


def _hostapi_index(hostapi):
    for i, h in enumerate(sd.query_hostapis()):
        if h["name"] == hostapi:
            return i
    return None


def _devices(hostapi, kind):
    """[(indice PortAudio, nom)] des périphériques du pilote qui ont des
    canaux dans le sens kind."""
    api = _hostapi_index(hostapi)
    if api is None:
        return []
    key = _CHANNELS[kind]
    return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
            if d["hostapi"] == api and d[key] > 0]


def devices(hostapi, kind):
    """Noms des périphériques d'entrée ou de sortie du pilote."""
    return [name for _, name in _devices(hostapi, kind)]


def default_device(hostapi, kind):
    """Nom du périphérique par défaut du pilote dans le sens kind, ou ""."""
    api = _hostapi_index(hostapi)
    if api is None:
        return ""
    idx = sd.query_hostapis(api)["default_" + kind + "_device"]
    if idx is None or idx < 0:
        return ""
    return sd.query_devices(idx)["name"]


def find_device(name, hostapi, kind):
    """Indice PortAudio du périphérique nommé dans ce pilote, ou None."""
    for idx, dev_name in _devices(hostapi, kind):
        if dev_name == name:
            return idx
    return None


def resolve_output(main_output, hostapi):
    """Sortie principale à ouvrir : (indice ou None, message). None = le
    défaut de PortAudio ; message non vide si le périphérique enregistré
    n'est plus là."""
    if not main_output:
        return None, ""
    idx = find_device(main_output, hostapi, OUTPUT)
    if idx is None:
        return None, f"Sortie audio introuvable : {main_output}. Sortie par défaut utilisée."
    return idx, ""


def rescan():
    """Relit les périphériques : PortAudio est réinitialisé (les flux ouverts
    doivent avoir été arrêtés et fermés avant)."""
    sd._terminate()
    sd._initialize()


# ---------------------------------------------------------------------------
# Tester
# ---------------------------------------------------------------------------

def tone(samplerate=44100, freq=TONE_FREQ, seconds=TONE_SECONDS, level=TONE_LEVEL):
    """La 440 Hz d'une seconde, stéréo float32, fondus de 10 ms (sans clic)."""
    n = int(round(samplerate * seconds))
    t = np.arange(n, dtype=np.float64) / samplerate
    wave = level * np.sin(2.0 * math.pi * freq * t)
    fade = min(n // 2, int(samplerate * 0.01))
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade)
        wave[:fade] *= ramp
        wave[n - fade:] *= ramp[::-1]
    return np.column_stack([wave, wave]).astype(np.float32)


def play_tone(device, samplerate=44100):
    """Joue tone() sur le périphérique (indice PortAudio, None = défaut),
    sans attendre ; AudioDeviceError si PortAudio le refuse."""
    try:
        sd.play(tone(samplerate), samplerate=samplerate, device=device)
    except (sd.PortAudioError, ValueError) as e:
        raise AudioDeviceError(str(e)) from e


def peak_db(data):
    """Crête d'un tampon en dBFS (−inf pour un silence)."""
    peak = float(np.max(np.abs(data))) if len(data) else 0.0
    return 20.0 * math.log10(peak) if peak > 0.0 else float("-inf")


def input_peak_db(device, seconds=INPUT_SECONDS, samplerate=44100):
    """Écoute l'entrée pendant seconds (bloquant) et retourne sa crête en
    dBFS ; AudioDeviceError si PortAudio la refuse."""
    try:
        channels = min(2, int(sd.query_devices(device)["max_input_channels"])) \
            if device is not None else 1
        data = sd.rec(int(samplerate * seconds), samplerate=samplerate,
                      channels=max(1, channels), dtype="float32",
                      device=device, blocking=True)
    except (sd.PortAudioError, ValueError) as e:
        raise AudioDeviceError(str(e)) from e
    return peak_db(data)


def format_db(db):
    """« −18 dB », « silence »."""
    if db == float("-inf"):
        return "silence"
    return f"{db:.0f} dB".replace("-", "−")
