class LivePlayMixin:
    """DrumPlayer — jeu live des pads, Note Repeat, volume et pan."""

    def play_sound(self, index, velocity=100):
        self.last_played_pad = index
        if self.voice_manager.is_audible(index):
            vol = min(1.0, self.voice_manager.get_volume_factor(index) * velocity / 100.0)
            self.sound_man.play_sound(
                index,
                vol,
                self._mix_pan(self.voice_manager.get_pan(index)),
            )

    #--------------------------------------------------------------------------

    def start_note_repeat(self, quant_idx, get_pad_func=None, play_cb=None):
        self._nr_quant_idx       = quant_idx
        self._nr_get_pad         = get_pad_func or (lambda: self.last_played_pad)
        self._nr_play_cb         = play_cb
        self._note_repeat_active = True
        if not (self._play_thread and self._play_thread.is_alive()):
            self.start_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def stop_note_repeat(self):
        self._note_repeat_active = False
        self._nr_play_cb         = None
        if not (self.playing or self.clicking):
            self.stop_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def update_nr_rate(self, quant_idx):
        """Change le taux NR à chaud sans modifier le pad en cours."""
        self._nr_quant_idx = quant_idx
        if self._note_repeat_active:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def set_volume(self, volume):
        if 0 <= volume <= 100:
            self.volume = volume
            self.sound_man.set_volume(volume)

    def set_pan(self, pan):
        self.pan = max(-100, min(100, int(pan)))

    def _mix_pan(self, pad_pan):
        return max(-100, min(100, self.pan + pad_pan))
