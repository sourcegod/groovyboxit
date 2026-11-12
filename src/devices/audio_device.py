#python3
"""
    File: src/devices/audio_device.py
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
INPUT_SECONDS = 3.0      # écoute d'une entrée (essai de 11f1 : 3 s, puis réécoute)
SILENCE_DB    = -70.0    # niveau moyen sous lequel l'entrée est muette
STUCK_RATIO   = 0.5      # part d'échantillons à pleine échelle : signal bloqué


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


# Greffons ALSA (convertisseurs, mixages) que PortAudio liste comme des
# périphériques : masqués des listes à cocher sur demande (essai de 11f1).
# Restent les cartes (« … (hw:1,0) ») et les serveurs de son.
ALSA_KEPT = ("default", "pipewire", "pulse")


def is_alsa_plugin(name, hostapi):
    """Vrai pour un greffon ALSA : ni une carte (« (hw:… ) »), ni default,
    pipewire, pulse ; toujours faux hors du pilote ALSA."""
    return hostapi == "ALSA" and "(hw:" not in name and name not in ALSA_KEPT


def devices(hostapi, kind, hide_plugins=False):
    """Noms des périphériques d'entrée ou de sortie du pilote ;
    hide_plugins : sans les greffons ALSA (is_alsa_plugin)."""
    names = [name for _, name in _devices(hostapi, kind)]
    if hide_plugins:
        names = [n for n in names if not is_alsa_plugin(n, hostapi)]
    return names


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


def device_name(index):
    """Nom du périphérique d'indice PortAudio index (None → "")."""
    if index is None:
        return ""
    try:
        return sd.query_devices(index)["name"]
    except (sd.PortAudioError, ValueError, IndexError):
        return ""


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


def record_input(device, seconds=INPUT_SECONDS, samplerate=44100):
    """Enregistre l'entrée pendant seconds (bloquant) : tableau float32
    (trames, 1 ou 2 canaux) ; AudioDeviceError si PortAudio la refuse."""
    try:
        channels = min(2, int(sd.query_devices(device)["max_input_channels"])) \
            if device is not None else 1
        return sd.rec(int(samplerate * seconds), samplerate=samplerate,
                      channels=max(1, channels), dtype="float32",
                      device=device, blocking=True)
    except (sd.PortAudioError, ValueError) as e:
        raise AudioDeviceError(str(e)) from e


def input_peak_db(device, seconds=INPUT_SECONDS, samplerate=44100):
    """Crête en dBFS d'une écoute de l'entrée (record_input)."""
    return peak_db(record_input(device, seconds, samplerate))


def rms_db(data):
    """Niveau moyen (RMS) d'un tampon en dBFS (−inf pour un silence)."""
    if not len(data):
        return float("-inf")
    rms = float(np.sqrt(np.mean(np.square(data, dtype=np.float64))))
    return 20.0 * math.log10(rms) if rms > 0.0 else float("-inf")


SILENT, STUCK, PRESENT = "silence", "bloqué", "présent"


def analyse_input(data):
    """(diagnostic, niveau moyen dB, crête dB) d'un enregistrement :
    SILENT (niveau moyen sous SILENCE_DB), STUCK (plus de la moitié des
    échantillons à pleine échelle : entrée saturée, ou tenue par un autre
    programme), PRESENT sinon. La crête seule ne suffit pas : un pic de
    souffle la porte près de 0 dB (essai de 11f1)."""
    rms, peak = rms_db(data), peak_db(data)
    if len(data) and np.mean(np.abs(data) >= 0.999) > STUCK_RATIO:
        return STUCK, rms, peak
    if rms < SILENCE_DB:
        return SILENT, rms, peak
    return PRESENT, rms, peak


def describe_input(verdict, rms, peak):
    """Phrase du diagnostic : « signal présent — niveau moyen −19 dB, crête
    −4 dB »."""
    if verdict == SILENT:
        return "silence (rien ne rentre)"
    if verdict == STUCK:
        return "signal bloqué à pleine échelle : entrée saturée ou inutilisable"
    return f"signal présent — niveau moyen {format_db(rms)}, crête {format_db(peak)}"


def to_stereo(data):
    """Tampon (trames, 1 ou 2) → stéréo float32 contigu (réécoute)."""
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    return np.ascontiguousarray(data[:, :2])


def format_db(db):
    """« −18 dB », « silence »."""
    if db == float("-inf"):
        return "silence"
    return f"{db:.0f} dB".replace("-", "−")
