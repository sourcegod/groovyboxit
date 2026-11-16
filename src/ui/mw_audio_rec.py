#python3
"""
    File: src/ui/mw_audio_rec.py
    Mixin MainWindow — enregistrement d'une prise audio sur la piste audio
    courante (Phase 8 étape 14f1, docs/DESIGN.md § Phase 8 étape 14f1 —
    point préalable, décisions R3, R4, § 14a A4, A7, A12) :
    - R / Shift+R / Ctrl+R sur une piste audio : projet nommé d'abord s'il
      est encore sans nom (Enregistrer sous ; Annuler = pas de prise), entrée
      de la piste (vide : première entrée cochée dans l'onglet Matériel,
      sinon le défaut du système), prise suivante dans le dossier des
      prises, flux d'entrée ouvert avant la lecture (rien de perdu) ;
    - à la fin de l'enregistrement (rappel du lecteur) : fichier fermé, clip
      posé à la position entendue (latence de sortie + compensation manuelle
      des Préférences), ce qui précède le début effectif sauté par start ;
      pattern gardé aux mesures nécessaires ; Undo = la prise ouverte par
      _take_begin (le fichier reste sur le disque).
    Les modes de boucle (Overdub en clips superposés, Remplacer sur la plage
    enregistrée) viennent en 14f2 : ici la prise s'arrête à la fin de la
    fenêtre de boucle.
    Date: Mon, 16/11/2026
    Author: Coolbrother
"""
import os

import wx

from audio import audio_takes
from audio import audio_recorder
from devices import audio_device as audio_devices
from pattern import TapeEvent, ETYPE_AUDIO, TRACK_AUDIO, clip_payload


class AudioRecMixin:

    _audio_recorder_factory = audio_recorder.AudioRecorder     # remplacé en test

    def _init_audio_rec(self):
        self._audio_rec = None          # (piste, chemin relatif, AudioRecorder)
        self._player._on_audio_take_end_cb = self._on_audio_take_end
        self._player._on_bars_changed_cb = lambda: wx.CallAfter(self._on_take_bars_changed)

    # ------------------------------------------------------------------
    # Armement
    # ------------------------------------------------------------------

    def _cur_track_is_audio(self):
        t = self._player._cur_track
        kinds = self._router._track_kinds
        return 0 <= t < len(kinds) and kinds[t] == TRACK_AUDIO

    def _audio_input_for(self, track_idx):
        """(indice PortAudio ou None = défaut, nom annoncé, remarque) de
        l'entrée de la piste (R4)."""
        cfg = self._cfg
        hostapi = cfg.audio_hostapi or audio_devices.default_hostapi()
        name = self._router._track_audio_ins[track_idx] or \
            (cfg.audio_inputs[0] if cfg.audio_inputs else "")
        if not name:
            return None, audio_devices.default_device(hostapi, "input") or "entrée par défaut", ""
        index = audio_devices.find_device(name, hostapi, "input")
        if index is None:
            default = audio_devices.default_device(hostapi, "input") or "entrée par défaut"
            return None, default, f"entrée « {name} » introuvable, {default} à la place"
        return index, name, ""

    def _audio_rec_prepare(self):
        """Avant R / Shift+R / Ctrl+R sur une piste audio : nomme le projet si
        besoin, ouvre la prise et arme le lecteur. False = pas
        d'enregistrement (Annuler, entrée refusée)."""
        if self._audio_rec is not None:
            return True
        if audio_takes.is_unnamed(self._project_path):
            self._show_status("Première prise audio : choisir le nom du projet")
            if not self._save_project_as():
                self._show_status("Prise audio annulée : projet sans nom")
                return False
        t = self._player._cur_track
        device, name, note = self._audio_input_for(t)
        path, rel = audio_takes.next_take(self._project_path, self._cur_pattern_idx, t,
                                          self._audio_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        recorder = self._audio_recorder_factory()
        try:
            recorder.start(path, device, self._audio_driver.samplerate,
                           audio_devices.input_channels(device))
        except Exception as e:                 # PortAudio, disque
            self._alert_beep()
            self._show_status(f"ERREUR prise audio ({name}) : {e}")
            if os.path.exists(path):
                os.remove(path)
            return False
        self._audio_rec = (t, rel, recorder)
        self._player.arm_audio_take()
        self._audio_rec_note = f"Prise audio piste {t + 1} — {name}" + (f" ({note})" if note else "")
        return True

    # ------------------------------------------------------------------
    # Fin de la prise
    # ------------------------------------------------------------------

    def _on_audio_take_end(self, take):
        if not wx.IsMainThread():
            wx.CallAfter(self._on_audio_take_end, take)
            return
        self._finish_audio_take(take)

    def _audio_latency_secs(self):
        """Latence de sortie du flux + compensation manuelle (Préférences)."""
        driver = getattr(self, "_audio_driver", None)
        out = getattr(driver, "output_latency", 0.0) or 0.0
        return float(out) + self._cfg.audio_latency_ms / 1000.0

    def _finish_audio_take(self, take):
        """Ferme le fichier et pose le clip (ou rien si la prise est vide)."""
        rec, self._audio_rec = self._audio_rec, None
        if rec is None:
            return None
        t, rel, recorder = rec
        result = recorder.stop()
        pat = self._player._pattern
        anchor = take.get("anchor")
        placed = None
        if anchor is not None and result.t0 is not None and result.frames > 0:
            measure_start, lp_start, t_start, window_end = anchor
            tm = self._player.tempo_map()
            placed = audio_recorder.place_take(
                result.t0 - self._audio_latency_secs(), result.frames, result.samplerate,
                t_start, measure_start, lp_start, tm.secs, tm.steps, window_end)
        if placed is None:
            with pat._lock:
                pat.set_bar_count(take.get("bars", pat._num_bars))
            if os.path.exists(result.path):
                os.remove(result.path)
            self._show_status("Prise audio vide : rien d'enregistré")
            return None
        step, start, length, end_step = placed
        clip = TapeEvent(ETYPE_AUDIO, payload=clip_payload(rel, 1.0, start, length), time=step)
        with pat._lock:
            pat._tape[t].append(clip)
            pat.set_bar_count(max(take.get("bars", 1),
                                  audio_recorder.bars_for(end_step, pat._num_steps)))
        self._update_title()
        self._refresh_track_list()
        secs = length / float(result.samplerate)
        msg = (f"Prise audio piste {t + 1} : {os.path.basename(result.path)}, "
               f"{secs:.1f} s, mesure {int(step // pat._num_steps) + 1}")
        if pat._num_bars != take.get("bars", pat._num_bars):
            msg += f" ; pattern : {pat._num_bars} mesures"
        if recorder.errors:
            msg += f" ; {len(recorder.errors)} anomalie(s) du flux d'entrée"
        self._show_status(msg)
        return clip

    def _on_take_bars_changed(self):
        """Pattern allongé pendant la prise (R3) : annoncé."""
        self._show_status(f"Prise audio : pattern {self._player._pattern._num_bars} mesures")
