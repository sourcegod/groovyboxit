#python3
"""
    File: src/ui/mw_devices.py
    Mixin MainWindow — périphériques MIDI des Préférences (Phase 8 étape
    11d1, docs/DESIGN.md § Phase 8 étape 11a H6, H8, H9, H12, H14, H15) :
    entrées et sorties cochées ouvertes au démarrage (introuvables : boîte
    « Périphérique introuvable »), Shift+F12 (connecter / déconnecter les
    entrées), Ctrl+Shift+F12 (tout réinitialiser), A4 d'une seconde sur une sortie,
    écoute de la prochaine note d'une entrée. Les ports passent par le
    paquet autonome devices.midi_device.
    Date: Wed, 11/11/2026
    Author: Coolbrother
"""
import threading

import numpy as np
import wx

from app_config import AppConfig
from devices import audio_device
from devices import midi_device


class DevicesMixin:

    SYNTH_OUTPUT = AppConfig.MIDI_SYNTH_OUTPUT     # « Synthé FluidSynth » (interne)
    TEST_SYNTH_SECONDS = 1.5                        # A4 d'une seconde + relâchement

    # ------------------------------------------------------------------
    # Ouverture des ports cochés
    # ------------------------------------------------------------------

    def _open_midi_devices(self):
        """Ouvre les entrées et les sorties MIDI cochées (H12). Retourne
        (ouvertes, notes) : noms des ports ouverts, messages des ports
        introuvables (« Entrée MIDI introuvable : X. »)."""
        cfg = self._cfg
        opened, missing = self._midi.open_names(cfg.midi_inputs)
        notes = [f"Entrée MIDI introuvable : {name}." for name in missing]
        outs = getattr(self, "_midi_outs", None)
        if outs is None:
            outs = self._midi_outs = {}
        for name in cfg.midi_outputs:
            if name == self.SYNTH_OUTPUT or name in outs:
                if name in outs:
                    opened.append(name)
                continue
            try:
                outs[name] = midi_device.open_output(name)
                opened.append(name)
            except midi_device.MidiDeviceError:
                notes.append(f"Sortie MIDI introuvable : {name}.")
        return opened, notes

    def _close_midi_devices(self):
        self._midi.close()
        for out in getattr(self, "_midi_outs", {}).values():
            try:
                out.close_port()
            except Exception:
                pass
        self._midi_outs = {}

    def _warn_track_midi_outs(self):
        """Pistes du pattern courant dont la sortie MIDI externe n'est pas
        ouverte : elles jouent le son interne de leur slot (Phase 8 étape
        12b1, § 12a T10) ; avertissement une fois par port et par session —
        boîte « Périphérique introuvable » avec bip et barre d'état, ou, au
        démarrage, ajouté aux notes de la boîte de démarrage."""
        router = getattr(self, "_router", None)
        if router is None or not hasattr(router, "missing_midi_outs"):
            return []
        warned = getattr(self, "_warned_midi_outs", None)
        if warned is None:
            warned = self._warned_midi_outs = set()
        by_port = {}
        for t, name in router.missing_midi_outs():
            if name not in warned:
                by_port.setdefault(name, []).append(t + 1)
        notes = []
        for name, tracks in by_port.items():
            warned.add(name)
            label = "Piste" if len(tracks) == 1 else "Pistes"
            notes.append(f"Sortie MIDI introuvable : {name}. {label} "
                         f"{', '.join(map(str, tracks))} : son interne.")
        if notes:
            if getattr(self, "_started", False):
                self._show_status(" ".join(notes))
                self._show_device_notes(notes)
            else:
                self._device_notes.extend(notes)
        return notes

    def _hardware(self):
        return HardwareAccess(self)

    def _apply_midi_devices(self):
        """Entrées et sorties MIDI cochées changées dans les Préférences :
        tout fermé puis rouvert tout de suite (11f1) ; retourne les notes des
        ports introuvables (boîte bloquante)."""
        self._close_midi_devices()
        _opened, notes = self._open_midi_devices()
        if notes:
            self._show_device_notes(notes)
        return notes

    def _toggle_midi_inputs(self):
        """Shift+F12 : déconnecte les entrées ouvertes, sinon connecte les entrées
        cochées dans les Préférences (onglet Matériel)."""
        if self._midi.is_open():
            self._midi.close()
            return
        names = self._cfg.midi_inputs
        if not names:
            self._show_status("MIDI : aucune entrée cochée — Alt+Shift+P, onglet Matériel")
            return
        opened, missing = self._midi.open_names(names)
        if missing:
            self._show_status("MIDI : introuvable" + ("s" if len(missing) > 1 else "")
                              + " : " + ", ".join(missing))
            self._show_device_notes([f"Entrée MIDI introuvable : {name}." for name in missing])

    def _reconnect_midi(self):
        """Ctrl+Shift+F12 (H15) : relit les ports, ferme puis rouvre toutes les
        entrées et sorties MIDI cochées ; annonce le résultat."""
        self._close_midi_devices()
        opened, notes = self._open_midi_devices()
        if not self._cfg.midi_inputs and not self._cfg.midi_outputs:
            msg = "MIDI : aucun périphérique coché dans les Préférences"
        else:
            msg = "MIDI reconnecté : " + (", ".join(opened) if opened else "aucun port")
            if notes:
                msg += " — " + " ".join(notes)
        self._show_status(msg)
        if notes:                                  # boîte bloquante et bip, comme l'audio
            self._show_device_notes(notes)
        return msg

    # ------------------------------------------------------------------
    # Tester (H14)
    # ------------------------------------------------------------------

    def _test_midi_output(self, name):
        """A4 d'une seconde sur la sortie nommée ; retourne le résultat."""
        label = midi_device.note_name(midi_device.TEST_NOTE)
        if name == self.SYNTH_OUTPUT:
            return self._test_synth_output(label)
        out = getattr(self, "_midi_outs", {}).get(name)
        try:
            temporary = out is None
            if temporary:
                out = midi_device.open_output(name)
            midi_device.send_test_note(out)
            if temporary:
                threading.Timer(midi_device.TEST_SECONDS + 0.2, out.close_port).start()
        except midi_device.MidiDeviceError as e:
            return f"Sortie MIDI {name} : {e}"
        return f"Sortie MIDI {name} : note {label} envoyée pendant une seconde"

    def _test_synth_output(self, label):
        """A4 sur un FluidSynth à part (soundfont par défaut, programme 1),
        branché au pilote le temps de la note : l'état des slots Banque n'est
        pas touché."""
        from audio.engines.fluidsynth_engine import FluidSynthEngine, FluidSynthUnavailable
        try:
            eng = FluidSynthEngine(samplerate=self._audio_driver.samplerate,
                                   gain=self._cfg.fluidsynth_gain)
        except FluidSynthUnavailable:
            return f"{self.SYNTH_OUTPUT} : bibliothèque FluidSynth absente"
        if not eng.load(0, self._gm_soundfont) or not eng.select(0, 0, 0, 0):
            eng.close()
            return f"{self.SYNTH_OUTPUT} : soundfont introuvable — {self._gm_soundfont}"
        driver = self._audio_driver
        driver.add_render_source(eng.render)
        eng.note_on(0, midi_device.TEST_NOTE, midi_device.TEST_VELOCITY)
        threading.Timer(midi_device.TEST_SECONDS,
                        eng.note_off, args=(0, midi_device.TEST_NOTE)).start()

        def finish():
            driver.remove_render_source(eng.render)
            eng.close()
        threading.Timer(self.TEST_SYNTH_SECONDS, finish).start()
        return f"{self.SYNTH_OUTPUT} : note {label} jouée pendant une seconde"

    def _listen_midi_input(self, name, done, timeout=midi_device.LISTEN_SECONDS):
        """Écoute la prochaine note de l'entrée nommée, dans un fil ; done(message)
        est appelé dans le fil de l'interface."""
        def run():
            try:
                got = midi_device.wait_note(name, timeout)
            except midi_device.MidiDeviceError as e:
                msg = f"Entrée MIDI {name} : {e}"
            else:
                if got is None:
                    msg = f"Entrée MIDI {name} : aucune note reçue en {timeout:g} secondes"
                else:
                    note, vel, chan = got
                    msg = (f"Entrée MIDI {name} : note {midi_device.note_name(note)}, "
                           f"vélocité {vel}, canal {chan + 1}")
            wx.CallAfter(done, msg)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread


class HardwareAccess:
    """Le matériel vu par l'onglet Matériel des Préférences (Phase 8 étape
    11f1, prefs_hardware.HardwarePage) : listes par le paquet devices,
    tests et relectures par la fenêtre principale."""

    def __init__(self, win):
        self._win = win

    # -- listes ----------------------------------------------------------

    def hostapis(self):
        return audio_device.hostapis()

    def default_hostapi(self):
        return audio_device.default_hostapi()

    def audio_devices(self, hostapi, kind):
        """Sans les greffons ALSA (lavrate, speex, upmix…, essai de 11f1)."""
        return audio_device.devices(hostapi, kind, hide_plugins=True)

    def midi_inputs(self):
        return midi_device.input_ports()

    def midi_outputs(self):
        """« Synthé FluidSynth » (si la bibliothèque est là, H8), puis les
        ports de sortie."""
        from audio.engines.fluidsynth_engine import fluidsynth_available
        synth = [DevicesMixin.SYNTH_OUTPUT] if fluidsynth_available() else []
        return synth + midi_device.output_ports()

    # -- Détecter (H5, H9) -----------------------------------------------

    def detect_audio(self):
        """Relit PortAudio : flux arrêté le temps de la relecture, puis
        rouvert sur la même sortie, retrouvée par son nom."""
        driver = getattr(self._win, "_audio_driver", None)
        name = ""
        if driver is not None and hasattr(driver, "stop_stream"):
            name = audio_device.device_name(driver.device)
            driver.stop_stream()
        try:
            audio_device.rescan()
        finally:
            if driver is not None and hasattr(driver, "start_stream"):
                api = self._win._cfg.audio_hostapi or audio_device.default_hostapi()
                idx = audio_device.find_device(name, api, audio_device.OUTPUT) if name else None
                try:
                    driver.start_stream(idx)
                except Exception:
                    driver.start_stream(None)
        n = sum(len(audio_device.devices(api, kind)) for api in audio_device.hostapis()
                for kind in (audio_device.INPUT, audio_device.OUTPUT))
        return f"Périphériques audio relus : {n} entrées et sorties"

    def detect_midi(self):
        ins, outs = midi_device.input_ports(), midi_device.output_ports()
        return f"Périphériques MIDI relus : {len(ins)} entrées, {len(outs)} sorties"

    # -- Tester (H14) ----------------------------------------------------

    def test_audio_output(self, hostapi, name):
        """La 440 Hz d'une seconde : par le pilote de l'appli si c'est sa
        sortie (périphérique déjà ouvert), sinon directement."""
        from audio.sound_device_driver import SdSound
        idx = audio_device.find_device(name, hostapi, audio_device.OUTPUT)
        if idx is None:
            return f"Sortie audio {name} : introuvable"
        driver = getattr(self._win, "_audio_driver", None)
        try:
            if driver is not None and idx == getattr(driver, "device", "?"):
                sr = driver.samplerate
                driver.play(SdSound(audio_device.tone(sr), sr))
            else:
                audio_device.play_tone(idx)
        except Exception as e:                      # AudioDeviceError, PortAudioError
            return f"Sortie audio {name} : refusée ({e})"
        return f"Sortie audio {name} : La 440 Hz joué pendant une seconde"

    def test_audio_input(self, hostapi, name, done):
        """Trois secondes d'écoute dans un fil, diagnostic (silence, bloqué,
        présent) avec niveau moyen et crête, puis réécoute de ce qui a été
        capté sur la sortie principale si un signal est présent (essai de
        11f1 : la crête seule ne disait rien) ; done(message) dans le fil de
        l'interface."""
        from audio.sound_device_driver import SdSound
        driver = getattr(self._win, "_audio_driver", None)
        sr = driver.samplerate if driver is not None else 44100

        def run():
            idx = audio_device.find_device(name, hostapi, audio_device.INPUT)
            if idx is None:
                msg = f"Entrée audio {name} : introuvable"
            else:
                try:
                    data = audio_device.record_input(idx, samplerate=sr)
                except audio_device.AudioDeviceError as e:
                    msg = f"Entrée audio {name} : refusée ({e})"
                else:
                    verdict, rms, peak = audio_device.analyse_input(data)
                    msg = f"Entrée audio {name} : " + audio_device.describe_input(verdict, rms, peak)
                    if verdict == audio_device.PRESENT and driver is not None:
                        driver.play(SdSound(audio_device.to_stereo(data), sr))
                        msg += " ; réécoute des 3 secondes captées"
            wx.CallAfter(done, msg)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def test_midi_output(self, name):
        return self._win._test_midi_output(name)

    def test_midi_input(self, name, done):
        return self._win._listen_midi_input(name, done)
