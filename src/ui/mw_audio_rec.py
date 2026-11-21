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
    Boucle (Phase 8 étape 14g2, § 14f1 R1, R2) : la prise continue d'une
    traite dans un seul fichier ; juste avant chaque retour, le passage qui
    finit devient un clip (fenêtre start / length), joué dès le passage
    suivant depuis la mémoire (pin_clip) tant que le fichier est ouvert.
    Overdub : les passages se superposent. Remplacer : chaque passage
    découpe sa plage dans les clips plus anciens de la piste ; pendant
    l'enregistrement la piste se tait dans la plage remplacée (choix de
    l'utilisateur) ; au Stop, la fin non enregistrée revient.
    Date: Mon, 16/11/2026
    Author: Coolbrother
"""
import os

import wx

from audio import audio_takes
from audio import audio_recorder
from devices import audio_device as audio_devices
from pattern import TapeEvent, ETYPE_AUDIO, TRACK_AUDIO, clip_payload, clip_window


class AudioRecMixin:

    _audio_recorder_factory = audio_recorder.AudioRecorder     # remplacé en test

    def _init_audio_rec(self):
        # prise ouverte : {"track", "rel", "recorder", "replace", "base"
        # (Remplacer : clips de la piste sans la plage en cours), "clips"
        # (passages déjà posés, par numéro)} ou None
        self._audio_rec = None
        p = self._player
        p._on_audio_take_end_cb = self._on_audio_take_end
        p._on_bars_changed_cb = lambda: wx.CallAfter(self._on_take_bars_changed)
        p._on_audio_anchor_cb = lambda: wx.CallAfter(self._on_audio_anchor)       # 14g2
        p._on_audio_wrap_cb = lambda at: wx.CallAfter(self._on_audio_wrap, at)

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

    def _project_needs_name(self):
        """Projet encore sans nom choisi (§ 14a A4) : noname_NNN jamais
        enregistré. Un nom confirmé tel quel (noname_001 gardé) ou un projet
        déjà sur le disque n'est plus redemandé (essai de 14g2 : le dialogue
        revenait à chaque R, avec « Remplacer ? »), même après Ctrl+Z."""
        return audio_takes.is_unnamed(self._project_path) and \
            not os.path.exists(self._project_path)

    def _audio_rec_prepare(self, replace=False, mpc=False):
        """Avant R / Shift+R / Ctrl+R sur une piste audio : nomme le projet si
        besoin, ouvre la prise et arme le lecteur. replace : Shift+R (14g2) ;
        mpc : Mode MPC, Remplacer au premier passage puis Overdub (16d1).
        False = pas d'enregistrement (Annuler, entrée refusée)."""
        if self._audio_rec is not None:
            return True
        if self._project_needs_name():
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
        if hasattr(self, "_monitor_release"):          # un seul flux par entrée (20d1, M5)
            self._monitor_release()
        try:
            recorder.start(path, device, self._audio_driver.samplerate,
                           audio_devices.input_channels(device))
        except Exception as e:                 # PortAudio, disque
            self._alert_beep()
            self._show_status(f"ERREUR prise audio ({name}) : {e}")
            if os.path.exists(path):
                os.remove(path)
            return False
        self._audio_rec = {"track": t, "rel": rel, "recorder": recorder,
                           "replace": bool(replace), "mpc": bool(replace and mpc),
                           "base": None, "clips": {}, "base_before": {}}
        self._player.arm_audio_take()
        if hasattr(self, "_update_monitor"):           # la prise relaie le monitoring
            self._update_monitor()
        self._audio_rec_note = f"Prise audio piste {t + 1} — {name}" + (f" ({note})" if note else "")
        return True

    # ------------------------------------------------------------------
    # Géométrie de la prise
    # ------------------------------------------------------------------

    def _audio_latency_secs(self):
        """Latence de sortie du flux + compensation manuelle (Préférences)."""
        driver = getattr(self, "_audio_driver", None)
        out = getattr(driver, "output_latency", 0.0) or 0.0
        return float(out) + self._cfg.audio_latency_ms / 1000.0

    def _step_at(self, lp_start, offset_secs):
        """Pas atteint offset_secs secondes après le pas lp_start."""
        tm = self._player.tempo_map()
        return tm.steps(tm.secs(lp_start) + offset_secs)

    def _carve_events(self, events, a, b):
        """Remplacer (R2) : les clips hors de la plage [a, b[ en pas (b None :
        jusqu'à la fin) ; un clip non touché garde son événement (son id)."""
        rec = self._audio_rec
        tm = self._player.tempo_map()
        out = []
        for ev in events:
            rel = ev.payload.get("file", "")
            start, length = clip_window(ev.payload)
            if rec is not None and rel == rec["rel"]:            # passage de cette prise
                sr = rec["recorder"].samplerate
            else:
                info = self._router.clip_file_info(rel)
                if info is None:
                    out.append(ev)
                    continue
                sr = info[1]
                if length is None:
                    length = max(0, info[0] - start)
            if length is None or length <= 0:
                out.append(ev)
                continue
            parts = audio_recorder.carve(ev.time, start, length, sr, a, b, tm.secs, tm.steps)
            if parts == [(ev.time, start, length)]:
                out.append(ev)
                continue
            gain = ev.payload.get("gain", 1.0)
            out += [TapeEvent(ETYPE_AUDIO, payload=clip_payload(rel, gain, s, n), time=t)
                    for t, s, n in parts]
        return out

    def _track_split(self, t):
        """(clips audio de la piste, autres événements)."""
        events = self._player._pattern._tape[t]
        clips = [ev for ev in events if ev.etype == ETYPE_AUDIO]
        return clips, [ev for ev in events if ev.etype != ETYPE_AUDIO]

    def _range_end(self, anchor):
        """Fin de la plage remplacée, en pas : fin de la boucle, None sans."""
        measure_start, lp_start, _, window_end = anchor
        return None if window_end is None else self._step_at(lp_start, window_end - measure_start)

    # ------------------------------------------------------------------
    # Pendant la prise (boucle, Remplacer)
    # ------------------------------------------------------------------

    def _on_audio_anchor(self):
        """Ancre posée : Remplacer fait taire la piste dans la plage (14g2)."""
        rec, take = self._audio_rec, self._player._audio_take
        if rec is None or take is None or take["anchor"] is None or not rec["replace"] \
                or rec["base"] is not None:
            return
        measure_start, lp_start, t_start, _ = take["anchor"]
        t = rec["track"]
        pat = self._player._pattern
        with pat._lock:
            clips, others = self._track_split(t)
            rec["base"] = clips
            pat._tape[t] = others + self._carve_events(
                clips, self._step_at(lp_start, t_start - measure_start), self._range_end(take["anchor"]))
        # les événements du passage en cours étaient déjà prêts (ancre posée au
        # début du passage) : voix de la piste coupées, événements refaits sans
        # les clips découpés (essai de 14g2 : la piste sonnait au 1er passage)
        stop_clips = getattr(self._router, "stop_audio_clips", None)
        if stop_clips is not None:
            stop_clips(t)
        self._player._wakeup.set()

    def _on_audio_wrap(self, wrap_at):
        """Peu avant un retour de boucle (14g2) : le passage qui finit devient
        un clip, joué dès le passage suivant (depuis la mémoire)."""
        rec, take = self._audio_rec, self._player._audio_take
        if rec is None or take is None or take["anchor"] is None:
            return None
        measure_start, lp_start, t_start, window_end = take["anchor"]
        recorder = rec["recorder"]
        if window_end is None or recorder.t0 is None:
            return None
        window = window_end - measure_start
        k = int(round((wrap_at - measure_start) / window)) - 1
        if k < 0 or k in rec["clips"]:
            return None
        sr = recorder.samplerate
        start, length, offset = audio_recorder.pass_window(
            k, recorder.t0 - self._audio_latency_secs(), sr, t_start, measure_start, window)
        if length <= 0:
            return None
        self._router.pin_clip(rec["rel"], start, length, recorder.live_range(start, length))
        clip = TapeEvent(ETYPE_AUDIO, payload=clip_payload(rec["rel"], 1.0, start, length),
                         time=self._step_at(lp_start, offset))
        rec["clips"][k] = clip
        t = rec["track"]
        pat = self._player._pattern
        end = self._range_end(take["anchor"])
        with pat._lock:
            if self._pass_replaces(rec, k):
                if rec["base"] is None:
                    rec["base"] = self._track_split(t)[0]
                rec["base_before"][k] = rec["base"]          # Stop juste après : refaire
                rec["base"] = self._carve_events(rec["base"], clip.time, end) + [clip]
                others = self._track_split(t)[1]
                if rec.get("mpc"):
                    # Mode MPC (16d1) : la suite s'ajoute — la piste rejoue ce
                    # qui reste, dont le passage qui vient de remplacer
                    pat._tape[t] = others + rec["base"]
                else:
                    # passage suivant : la piste se tait dans toute la boucle
                    pat._tape[t] = others + self._carve_events(rec["base"], lp_start, end)
            else:
                pat._tape[t].append(clip)
        return clip

    @staticmethod
    def _pass_replaces(rec, k):
        """Le passage k remplace-t-il ? Remplacer : tous ; Mode MPC (16d1) :
        le premier seulement ; Overdub : aucun."""
        return rec["replace"] and (not rec.get("mpc") or k == 0)

    # ------------------------------------------------------------------
    # Fin de la prise
    # ------------------------------------------------------------------

    def _on_audio_take_end(self, take):
        if not wx.IsMainThread():
            wx.CallAfter(self._on_audio_take_end, take)
            return
        self._finish_audio_take(take)

    def _take_passes(self, take, result):
        """[(numéro, start, length, pas de départ, pas de fin)] de la prise
        terminée : un seul passage sans boucle (14f1), un par passage en
        boucle (14g2)."""
        anchor = take.get("anchor")
        if anchor is None or result.t0 is None or result.frames <= 0:
            return []
        measure_start, lp_start, t_start, window_end = anchor
        heard_at = result.t0 - self._audio_latency_secs()
        sr = result.samplerate
        if window_end is None:
            tm = self._player.tempo_map()
            placed = audio_recorder.place_take(heard_at, result.frames, sr, t_start,
                                               measure_start, lp_start, tm.secs, tm.steps)
            if placed is None:
                return []
            step, start, length, end_step = placed
            return [(0, start, length, step, end_step)]
        return [(k, a, n, self._step_at(lp_start, off), self._step_at(lp_start, off + n / float(sr)))
                for k, a, n, off in audio_recorder.loop_passes(
                    heard_at, result.frames, sr, t_start, measure_start, window_end - measure_start)]

    def _finish_audio_take(self, take):
        """Ferme le fichier et pose les clips (ou rien si la prise est vide)."""
        rec, self._audio_rec = self._audio_rec, None
        if rec is None:
            return None
        t, rel, recorder = rec["track"], rec["rel"], rec["recorder"]
        result = recorder.stop()
        passes = self._take_passes(take, result)
        pat = self._player._pattern
        self._audio_rec = rec                         # _carve_events : passages de la prise
        try:
            with pat._lock:
                if not passes:
                    clips, others = self._track_split(t)
                    keep = rec["base"] if rec["base"] is not None else \
                        [ev for ev in clips if ev.payload.get("file") != rel]
                    pat._tape[t] = others + keep
                    pat.set_bar_count(take.get("bars", pat._num_bars))
                else:
                    self._apply_passes(rec, passes, take)
        finally:
            self._audio_rec = None
        self._router.unpin_clips(rel)                 # relu dans le fichier fermé
        if not passes:
            if os.path.exists(result.path):
                os.remove(result.path)
            self._show_status("Prise audio vide : rien d'enregistré")
            return None
        self._update_title()
        self._refresh_track_list()
        k, start, length, step, end_step = passes[0]
        secs = sum(p[2] for p in passes) / float(result.samplerate)
        msg = f"Prise audio piste {t + 1} : {os.path.basename(result.path)}, {secs:.1f} s, "
        msg += f"mesure {int(step // pat._num_steps) + 1}" if len(passes) == 1 else \
            f"{len(passes)} passages" + (" (le premier remplace)" if rec.get("mpc") else
                                     " (le dernier remplace)" if rec["replace"] else "")
        if pat._num_bars != take.get("bars", pat._num_bars):
            msg += f" ; pattern : {pat._num_bars} mesures"
        if recorder.errors:
            msg += f" ; {len(recorder.errors)} anomalie(s) du flux d'entrée"
        self._show_status(msg)
        return [rec["clips"][p[0]] for p in passes]

    def _apply_passes(self, rec, passes, take):
        """Clips des passages posés sur la piste (verrou du pattern tenu) :
        les passages déjà posés en boucle gardent leur événement (une voix
        qui sonne n'est pas relancée), leur fenêtre est mise à jour."""
        t, rel = rec["track"], rec["rel"]
        pat = self._player._pattern
        clips, others = self._track_split(t)
        base = rec["base"] if rec["base"] is not None else clips
        extras = []                                   # Mode MPC : passages suivants (16d1)
        for k, start, length, step, end_step in passes:
            replaces = self._pass_replaces(rec, k)
            clip = rec["clips"].get(k)
            if clip is not None:                      # déjà posé pendant la boucle
                shorter = clip_window(clip.payload)[1] != length
                clip.payload = clip_payload(rel, 1.0, start, length)
                if replaces and shorter and k in rec["base_before"]:
                    # Stop peu après la pose : seule la partie enregistrée
                    # remplace, la fin du passage précédent revient
                    base = self._carve_events(rec["base_before"][k], step, end_step) + [clip]
                elif not replaces and rec["replace"]:
                    extras.append(clip)
                elif not replaces and clip not in clips:
                    clips.append(clip)
                continue
            clip = TapeEvent(ETYPE_AUDIO, payload=clip_payload(rel, 1.0, start, length), time=step)
            rec["clips"][k] = clip
            if replaces:
                base = self._carve_events(base, step, end_step) + [clip]
            elif rec["replace"]:
                extras.append(clip)
            else:
                clips.append(clip)
        pat._tape[t] = others + (base + extras if rec["replace"] else clips)
        if take.get("anchor") is not None and take["anchor"][3] is None:     # sans boucle (R3)
            end_step = max(p[4] for p in passes)
            pat.set_bar_count(max(take.get("bars", 1),
                                  audio_recorder.bars_for(end_step, pat._num_steps)))

    def _on_take_bars_changed(self):
        """Pattern allongé pendant la prise (R3) : annoncé."""
        self._show_status(f"Prise audio : pattern {self._player._pattern._num_bars} mesures")
