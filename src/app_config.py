#python3
"""
    File: src/app_config.py
    Chargement de la configuration applicative depuis data/config.json.
    Les chemins manquants tombent back sur des sous-dossiers relatifs au projet.
    Date: Mon, 26/05/2026
    Author: Coolbrother
"""
import os
import json


class AppConfig:
    """
    Charge data/config.json depuis la racine du projet.
    Fournit les chemins configurables avec fallback relatif si absent.
    """

    CONFIG_RELATIVE = os.path.join("data", "config.json")

    def __init__(self, base_dir):
        self._base_dir = base_dir
        self._data = {}
        config_path = os.path.join(base_dir, self.CONFIG_RELATIVE)
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

    def _get_dir(self, key, default_name):
        """Retourne le chemin pour 'key'.

        - Chemin absolu → utilisé tel quel.
        - Chemin relatif → résolu depuis base_dir.
        - Clé absente ou vide → <base_dir>/<default_name>.
        """
        value = self._data.get(key, "").strip()
        if not value:
            return os.path.join(self._base_dir, default_name)
        if os.path.isabs(value):
            return value
        return os.path.join(self._base_dir, value)

    def _get_file(self, key):
        """Retourne le chemin de fichier pour 'key'.

        - Chemin absolu dans config.json → utilisé tel quel.
        - Chemin relatif → résolu depuis base_dir (racine du projet).
        - Clé absente ou vide → retourne "".
        """
        value = self._data.get(key, "").strip()
        if not value:
            return ""
        if os.path.isabs(value):
            return value
        return os.path.join(self._base_dir, value)

    @property
    def media_dir(self):
        return self._get_dir("media_dir", "media")

    @property
    def patches_dir(self):
        return self._get_dir("patches_dir", "patches")

    @property
    def samples_dir(self):
        return self._get_dir("samples_dir", "samples")

    @property
    def kits_dir(self):
        return self._get_dir("kits_dir", "kits")

    @property
    def presets_dir(self):
        return self._get_dir("presets_dir", "presets")

    @property
    def projects_dir(self):
        value = self._data.get("projects_dir", "").strip()
        if not value:
            return "/home/com/groovybox/PROJECTS"
        if os.path.isabs(value):
            return value
        return os.path.join(self._base_dir, value)

    @property
    def exports_dir(self):
        """Dossier proposé pour l'export MIDI (Phase 7 étape 10j1).

        Défaut : EXPORTS, à côté du dossier des projets.
        Configurable via la clé "exports_dir" de config.json (absolu, ou
        relatif à base_dir).
        """
        value = self._data.get("exports_dir", "").strip()
        if not value:
            return os.path.join(os.path.dirname(os.path.normpath(self.projects_dir)), "EXPORTS")
        if os.path.isabs(value):
            return value
        return os.path.join(self._base_dir, value)

    @property
    def sound_cache_dir(self):
        """Répertoire du cache disque des sons pré-calculés.

        Défaut : ~/.cache/groovyboxit/precompute
        Configurable via la clé "sound_cache_dir" dans config.json.
        """
        value = self._data.get("sound_cache_dir", "").strip()
        if not value:
            return os.path.join(os.path.expanduser("~"), ".cache", "groovyboxit", "precompute")
        if os.path.isabs(value):
            return value
        return os.path.join(self._base_dir, value)

    @property
    def click1_file(self):
        return self._get_file("click1_file")

    @property
    def click2_file(self):
        return self._get_file("click2_file")

    # Volume et pan globaux par défaut (Phase 7 étape 15d1, docs/DESIGN.md
    # § 15a1 D3, avenant 15a2) : pour un nouveau projet, ou un projet sans
    # clé "master". L'appli n'écrit jamais config.json.

    MASTER_VOLUME_DEFAULT = 100
    MASTER_PAN_DEFAULT    = 0

    def _get_int(self, key, default, lo, hi):
        """Entier borné à lo..hi ; défaut si la clé manque ou est invalide."""
        value = self._data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return max(lo, min(hi, int(value)))

    @property
    def master_volume(self):
        return self._get_int("master_volume", self.MASTER_VOLUME_DEFAULT, 0, 100)

    @property
    def master_pan(self):
        return self._get_int("master_pan", self.MASTER_PAN_DEFAULT, -100, 100)

    # Slot Banque (Phase 7 étape 17b1, docs/DESIGN.md § 17a1 D7, D17).

    SOUNDFONTS_DIR_DEFAULT   = "/usr/share/sounds/sf2"
    GM_SOUNDFONT_DEFAULT     = "FluidR3_GM.sf2"
    MIDI_BANK_SELECT_DEFAULT = "gs"
    FLUIDSYNTH_GAIN_DEFAULT  = 0.4     # 1.0 écrêtait un orchestre GM importé (18d4)

    def _get_str(self, key):
        value = self._data.get(key, "")
        return value.strip() if isinstance(value, str) else ""

    @property
    def soundfonts_dir(self):
        """Dossier des soundfonts (absolu, ou relatif à base_dir)."""
        value = self._get_str("soundfonts_dir")
        if not value:
            return self.SOUNDFONTS_DIR_DEFAULT
        if os.path.isabs(value):
            return value
        return os.path.join(self._base_dir, value)

    @property
    def gm_soundfont(self):
        """Soundfont proposée par défaut au slot Banque (absolue, ou
        relative à soundfonts_dir)."""
        value = self._get_str("gm_soundfont") or self.GM_SOUNDFONT_DEFAULT
        if os.path.isabs(value):
            return value
        return os.path.join(self.soundfonts_dir, value)

    @property
    def midi_bank_select(self):
        """"gs" (le MSB seul choisit la banque) ou "mma" (MSB × 128 + LSB)."""
        value = self._get_str("midi_bank_select").lower()
        return value if value in ("gs", "mma") else self.MIDI_BANK_SELECT_DEFAULT

    @property
    def fluidsynth_gain(self):
        """Gain de FluidSynth (synth.gain, 0.0..10.0) ; défaut 0.4."""
        value = self._data.get("fluidsynth_gain", self.FLUIDSYNTH_GAIN_DEFAULT)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return self.FLUIDSYNTH_GAIN_DEFAULT
        return max(0.0, min(10.0, float(value)))
