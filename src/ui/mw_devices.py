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

import wx

from app_config import AppConfig
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

    def _toggle_midi_inputs(self):
        """Shift+F12 : déconnecte les entrées ouvertes, sinon connecte les entrées
        cochées dans les Préférences ; sans entrée cochée, le port choisi
        dans la liste « MIDI: » de la fenêtre principale (jusqu'à 11f1)."""
        if self._midi.is_open():
            self._midi.close()
            return
        names = self._cfg.midi_inputs
        if not names:
            self._midi_handler.connect()
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
