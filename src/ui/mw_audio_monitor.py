#python3
"""
    File: src/ui/mw_audio_monitor.py
    Mixin MainWindow — monitoring de l'entrée audio (Phase 8 étape 20d1,
    docs/DESIGN.md § Phase 8 étape 20a, M1-M7) : case « Monitoring de
    l'entrée » des Options de l'enregistrement (record_options["monitor"],
    gardée dans le projet), F8 pour la basculer. Case cochée : l'entrée de
    la piste courante, si c'est une piste audio, s'entend à l'arrêt, pendant
    la lecture et pendant une prise, au volume et au pan de la piste (muette
    si la piste l'est).
    Mise à jour : _update_monitor() tout de suite (F8, Ctrl+Shift+R, Ctrl+Z,
    Ctrl+N / Ctrl+O, début de prise) et par une minuterie de MONITOR_TICK_MS
    (piste courante, pattern, type et entrée de piste, volume, pan, Mute,
    Solo, fin de prise) : un seul endroit plutôt qu'un appel dans chacun des
    chemins qui changent la piste courante. Le flux d'entrée ne s'ouvre que
    si la piste ou son entrée change ; une entrée refusée n'est pas
    redemandée avant un changement (un seul bip).
    Date: Sat, 21/11/2026
    Author: Coolbrother
"""
import wx

from audio.input_monitor import InputMonitor
from devices import audio_device as audio_devices


class AudioMonitorMixin:

    MONITOR_TICK_MS = 100
    _input_monitor_factory = InputMonitor        # remplacé en test

    def _init_audio_monitor(self, timer=True):
        self._monitor = None            # InputMonitor, créé au premier besoin
        self._monitor_key = None        # ce qui est ouvert : (piste, entrée) ou ("rec", …)
        self._monitor_failed = None     # clé refusée par PortAudio (pas redemandée)
        self._monitor_timer = None
        if timer:
            # minuterie sans fenêtre propriétaire : ses événements vont à
            # elle-même, jamais à une fenêtre détruite (Destroy() ne la
            # supprime qu'au tour suivant de la boucle : un top déjà en file
            # visait une fenêtre morte → plantage) ; arrêtée à la destruction
            self._monitor_timer = wx.Timer()
            self._monitor_timer.Bind(wx.EVT_TIMER, self._on_monitor_tick)
            self.Bind(wx.EVT_WINDOW_DESTROY, self._on_monitor_destroy)
            self._monitor_timer.Start(self.MONITOR_TICK_MS)

    def _on_monitor_tick(self, event):
        if not self or self.IsBeingDeleted():       # fenêtre détruite ou en cours
            self._monitor_stop_all()
            return
        self._update_monitor()

    def _on_monitor_destroy(self, event):
        if event.GetEventObject() is self:
            self._monitor_stop_all()
        event.Skip()

    def _monitor_stop_all(self):
        """Minuterie arrêtée, monitoring coupé (fermeture de la fenêtre)."""
        timer, self._monitor_timer = getattr(self, "_monitor_timer", None), None
        if timer is not None:
            timer.Stop()
        if hasattr(self, "_monitor"):
            self._monitor_close()

    # ------------------------------------------------------------------
    # État
    # ------------------------------------------------------------------

    def _monitor_enabled(self):
        return bool(getattr(self, "_record_options", {}).get("monitor"))

    def _monitor_input_key(self, t):
        """Ce qui désigne l'entrée de la piste sans interroger PortAudio :
        (piste, nom de l'entrée de la piste ou première cochée, pilote)."""
        cfg = self._cfg
        name = self._router._track_audio_ins[t] or \
            (cfg.audio_inputs[0] if cfg.audio_inputs else "")
        return (t, name, cfg.audio_hostapi or "")

    def _monitor_gain(self, t):
        """(volume, pan) de la piste pour le monitoring : volume de piste,
        pan de piste + pan global (comme les clips, 18b1) ; 0 si la piste
        est muette ou hors solo."""
        r = self._router
        if not r._track_is_audible(t):
            return 0.0, 0
        pan = r._track_pans[t] + getattr(r, "master_pan", 0)
        return r._track_volumes[t] / 100.0, max(-100, min(100, pan))

    def monitor_heard_track(self):
        """Piste dont l'entrée s'entend, ou None."""
        if self._monitor is None or self._monitor_key is None:
            return None
        return self._monitor_key[1] if self._monitor_key[0] == "rec" else self._monitor_key[0]

    # ------------------------------------------------------------------
    # Mise à jour
    # ------------------------------------------------------------------

    def _monitor_get(self):
        driver = self._audio_driver
        mon = self._monitor
        if mon is None or mon.samplerate != driver.samplerate:
            self._monitor_close()
            mon = self._monitor = self._input_monitor_factory(driver.samplerate)
            driver.add_render_source(mon.render)
        return mon

    def _monitor_close(self):
        """Monitoring coupé : flux fermé, source retirée du mix, enregistreur
        détaché."""
        mon, self._monitor = self._monitor, None
        self._monitor_key = None
        rec = getattr(self, "_audio_rec", None)
        if rec is not None:
            rec["recorder"].on_block = None
        if mon is not None:
            mon.stop()
            driver = getattr(self, "_audio_driver", None)
            if driver is not None:
                driver.remove_render_source(mon.render)

    def _monitor_release(self):
        """Avant d'ouvrir l'entrée pour une prise : le flux propre se ferme
        (un seul flux par entrée) ; la prise le relaiera."""
        if self._monitor is not None and self._monitor.active:
            self._monitor.stop()
            self._monitor_key = None

    def _update_monitor(self):
        """Recalcule le monitoring (M3) : rien si la case est décochée, la
        piste courante pas audio, ou sans pilote ; pendant une prise sur la
        piste, les blocs viennent de l'enregistreur ; sinon flux propre sur
        l'entrée de la piste. Retourne la remarque d'une entrée remplacée
        (« entrée X introuvable, Y à la place ») ou ""."""
        driver = getattr(self, "_audio_driver", None)
        t = self._player._cur_track
        if driver is None or not self._monitor_enabled() or not self._cur_track_is_audio():
            if self._monitor is not None:
                self._monitor_close()
            self._monitor_failed = None
            return ""
        mon = self._monitor_get()
        mon.set_gain(*self._monitor_gain(t))
        rec = getattr(self, "_audio_rec", None)
        if rec is not None and rec["track"] == t:
            if self._monitor_key != ("rec", t):
                mon.stop()
                mon.clear()
                rec["recorder"].on_block = mon.feed
                self._monitor_key = ("rec", t)
            return ""
        key = self._monitor_input_key(t)
        if (mon.active and self._monitor_key == key) or self._monitor_failed == key:
            return ""
        device, name, note = self._audio_input_for(t)
        try:
            mon.start(device, audio_devices.input_channels(device))
        except Exception as e:                      # PortAudio : entrée occupée, absente
            self._monitor_key = None
            self._monitor_failed = key
            self._alert_beep()
            self._show_status(f"Monitoring de l'entrée : {name} refusée ({e})")
            return ""
        self._monitor_key = key
        self._monitor_failed = None
        return note

    # ------------------------------------------------------------------
    # F8
    # ------------------------------------------------------------------

    def _monitor_describe(self):
        """Annonce de l'état : « activé (piste 3 — Micro) », « activé (piste
        courante non audio) », « désactivé »."""
        if not self._monitor_enabled():
            return "Monitoring de l'entrée désactivé"
        t = self._player._cur_track
        if not self._cur_track_is_audio():
            return "Monitoring de l'entrée activé (piste courante non audio)"
        _device, name, _note = self._audio_input_for(t)
        return f"Monitoring de l'entrée activé (piste {t + 1} — {name})"

    def _toggle_monitor(self, status=None):
        """F8 : bascule la case (point d'Undo), annonce l'état."""
        say = status or self._show_status
        opts = dict(self._record_options)
        opts["monitor"] = not opts.get("monitor", False)
        self._add_undo("Monitoring de l'entrée " + ("activé" if opts["monitor"] else "désactivé"))
        self._apply_record_options(opts)
        self._update_title()
        msg = self._monitor_describe()
        if self._monitor_failed is not None:
            msg += " — entrée refusée"
        elif self._last_monitor_note:
            msg += f" ; {self._last_monitor_note}"
        say(msg)
        return opts["monitor"]

    _last_monitor_note = ""       # remarque du dernier _update_monitor par les options
