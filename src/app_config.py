#python3
"""
    File: src/app_config.py
    Chargement de la configuration applicative depuis data/config.json.
    Les chemins manquants tombent back sur des sous-dossiers relatifs au projet.
    Préférences de l'utilisateur (Phase 8 étape 10b1, docs/DESIGN.md § 10a
    P1) : ~/.config/groovyboxit/preferences.json, lu par-dessus
    data/config.json (valeurs par défaut, jamais écrit) ; seul le dialogue
    des Préférences l'écrit (save_preferences).
    Date: Mon, 26/05/2026
    Author: Coolbrother
"""
import os
import json
import tempfile


class AppConfig:
    """
    Charge data/config.json depuis la racine du projet, puis les préférences
    de l'utilisateur par-dessus (une clé de preferences.json l'emporte).
    Fournit les chemins configurables avec fallback relatif si absent.
    """

    CONFIG_RELATIVE = os.path.join("data", "config.json")

    # Préférences de l'utilisateur (10b1, P1). La variable d'environnement
    # GROOVYBOXIT_PREFS désigne un autre fichier (tests, essais).
    PREFS_ENV     = "GROOVYBOXIT_PREFS"
    PREFS_DEFAULT = os.path.join("~", ".config", "groovyboxit", "preferences.json")

    def __init__(self, base_dir, prefs_path=None):
        """prefs_path : fichier des préférences ; défaut : variable
        GROOVYBOXIT_PREFS, sinon ~/.config/groovyboxit/preferences.json."""
        self._base_dir = base_dir
        self._defaults = {}
        config_path = os.path.join(base_dir, self.CONFIG_RELATIVE)
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                self._defaults = json.load(f)
        if prefs_path is None:
            prefs_path = os.environ.get(self.PREFS_ENV) or self.PREFS_DEFAULT
        self._prefs_path = os.path.expanduser(prefs_path)
        self._prefs = self._read_prefs()
        self._data = {**self._defaults, **self._prefs}

    # ------------------------------------------------------------------
    # Préférences de l'utilisateur (10b1, P1)
    # ------------------------------------------------------------------

    @property
    def prefs_path(self):
        return self._prefs_path

    def _read_prefs(self):
        """Contenu de preferences.json ; {} s'il manque, ou s'il est illisible
        (JSON invalide, pas un objet)."""
        try:
            with open(self._prefs_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def preferences(self):
        """Copie des clés écrites par l'utilisateur."""
        return dict(self._prefs)

    def defaults_only(self):
        """Configuration sans les préférences de l'utilisateur : les valeurs
        de data/config.json et les défauts du code (bouton « Valeurs par
        défaut » des Préférences, Phase 8 étape 10f2)."""
        return AppConfig(self._base_dir, prefs_path=os.devnull)

    def default(self, key, fallback=None):
        """Valeur de data/config.json pour key (sans les préférences)."""
        return self._defaults.get(key, fallback)

    def save_preferences(self, values):
        """Écrit values dans preferences.json et les applique à cette
        instance. Une valeur None retire la clé (retour à la valeur de
        data/config.json). Les autres clés du fichier sont gardées, relues
        juste avant l'écriture ; un fichier illisible est gardé en .bak.
        Écriture sûre : fichier temporaire du même dossier, puis renommage.
        Retourne le chemin du fichier."""
        path = self._prefs_path
        folder = os.path.dirname(path) or "."
        os.makedirs(folder, exist_ok=True)
        current = self._read_prefs()
        if not current and os.path.isfile(path) and os.path.getsize(path) > 0:
            os.replace(path, path + ".bak")          # illisible : rien de perdu
        for key, value in values.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        fd, tmp = tempfile.mkstemp(prefix=".preferences-", suffix=".json", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        self._prefs = current
        self._data = {**self._defaults, **current}
        return path

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

    # Kits, patchs, samples (10b1, P8) : clé absente → sous-dossier du
    # parent des banques de l'utilisateur (user_banks_dir).

    def _user_bank_dir(self, key, subdir):
        if self._get_str(key):
            return self._get_dir(key, subdir)
        return os.path.join(self.user_banks_dir, subdir)

    @property
    def patches_dir(self):
        return self._user_bank_dir("patches_dir", "PATCHS")

    @property
    def samples_dir(self):
        return self._user_bank_dir("samples_dir", "SAMPLES")

    @property
    def kits_dir(self):
        return self._user_bank_dir("kits_dir", "KITS")

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

    MASTER_VOLUME_MAX = 200    # jusqu'à 200 (+6 dB, Phase 8 étape 8c1, L4)

    @property
    def master_volume(self):
        return self._get_int("master_volume", self.MASTER_VOLUME_DEFAULT, 0,
                             self.MASTER_VOLUME_MAX)

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
        """Dossier des soundfonts (absolu, ou relatif à base_dir). Défaut
        (10b1, P8) : <user_banks_dir>/banks/sf2 s'il existe, sinon l'ancien
        dossier système /usr/share/sounds/sf2 (fichiers pas encore rangés)."""
        value = self._get_str("soundfonts_dir")
        if not value:
            new = os.path.join(self.user_banks_dir, self.BANKS_SUBDIR, self.SF2_SUBDIR)
            return new if os.path.isdir(new) else self.SOUNDFONTS_DIR_DEFAULT
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

    # Slot Synth SFZ et moteurs optionnels (Phase 8 étape 7b1, docs/DESIGN.md
    # § 7a2 Z7, Z13).

    # 1.0 (7b1) sortait un peu moins fort que FluidR3 à 0.4 ; 1.5 un peu plus
    # fort, mais plus agréable et plus clair à l'écoute (essai de 7d1)
    SFIZZ_GAIN_DEFAULT = 1.5

    @property
    def legacy_sfz_dir(self):
        """Ancien dossier des SFZ (avant 10b1) : media/sfz à côté du dossier
        des projets (/home/com/groovybox/media/sfz)."""
        return os.path.join(os.path.dirname(os.path.normpath(self.projects_dir)),
                            "media", "sfz")

    @property
    def sfz_dir(self):
        """Dossier des instruments SFZ (absolu, ou relatif à base_dir).
        Défaut (10b1, P8) : <user_banks_dir>/banks/sfz s'il existe, sinon
        l'ancien media/sfz (legacy_sfz_dir, fichiers pas encore rangés)."""
        value = self._get_str("sfz_dir")
        if not value:
            new = os.path.join(self.user_banks_dir, self.BANKS_SUBDIR, self.SFZ_SUBDIR)
            return new if os.path.isdir(new) else self.legacy_sfz_dir
        if os.path.isabs(value):
            return value
        return os.path.join(self._base_dir, value)

    @property
    def sfizz_gain(self):
        """Gain appliqué au rendu de sfizz (0.0..10.0) ; défaut 1.5."""
        value = self._data.get("sfizz_gain", self.SFIZZ_GAIN_DEFAULT)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return self.SFIZZ_GAIN_DEFAULT
        return max(0.0, min(10.0, float(value)))

    def _get_bool(self, key, default):
        value = self._data.get(key, default)
        return value if isinstance(value, bool) else default

    @property
    def fluidsynth_enabled(self):
        """Clé "fluidsynth" (défaut true) : false = moteur FluidSynth coupé,
        slots Banque muets (Z7)."""
        return self._get_bool("fluidsynth", True)

    @property
    def live_limiter_enabled(self):
        """Clé "live_limiter" (défaut true) : false = pas de limiteur du mix à
        l'écoute, écrêtage seul (Phase 8 étape 8c1, docs/DESIGN.md § 8a L3)."""
        return self._get_bool("live_limiter", True)

    @property
    def sfizz_enabled(self):
        """Clé "sfizz" (défaut true) : false = moteur sfizz coupé, slots
        Synth SFZ muets (Z7)."""
        return self._get_bool("sfizz", True)

    # ------------------------------------------------------------------
    # Préférences du dialogue (Phase 8 étape 10b1, docs/DESIGN.md § 10a)
    # ------------------------------------------------------------------

    # Général (P5)
    STARTUP_LAST = "last"      # ouvrir le dernier projet (défaut)
    STARTUP_NEW  = "new"       # nouveau projet
    STARTUP_CHOICES = (STARTUP_LAST, STARTUP_NEW)

    @property
    def startup(self):
        """Clé "startup" : "last" (défaut) ou "new"."""
        value = self._get_str("startup").lower()
        return value if value in self.STARTUP_CHOICES else self.STARTUP_LAST

    @property
    def last_project(self):
        """Clé "last_project" : chemin du dernier projet ouvert ou enregistré
        (absolu ; "~" développé), ou "" ."""
        value = self._get_str("last_project")
        return os.path.expanduser(value) if value else ""

    @property
    def autoplay(self):
        """Clé "autoplay" (défaut true) : le pad joue en naviguant dans la
        grille et dans la liste des pads."""
        return self._get_bool("autoplay", True)

    @property
    def explorer_autoplay(self):
        """Clé "explorer_autoplay" (défaut true) : audition dans
        l'Explorateur (à construire)."""
        return self._get_bool("explorer_autoplay", True)

    # Projet (P8) : projets et banques de l'appli et de l'utilisateur
    BANKS_SUBDIR = "banks"     # sous user_banks_dir : SF2 et SFZ réunis
    SF2_SUBDIR   = "sf2"
    SFZ_SUBDIR   = "sfz"

    def _get_path(self, key, default):
        """Chemin de key : absolu tel quel ("~" développé), relatif à
        base_dir ; default si la clé manque ou est vide."""
        value = self._get_str(key)
        if not value:
            return default
        value = os.path.expanduser(value)
        if os.path.isabs(value):
            return value
        return os.path.join(self._base_dir, value)

    @property
    def app_projects_dir(self):
        """Démos de patterns livrées avec l'appli ; défaut <base_dir>/projects."""
        return self._get_path("app_projects_dir", os.path.join(self._base_dir, "projects"))

    @property
    def app_banks_dir(self):
        """Banques livrées avec l'appli ; défaut <base_dir>/banks."""
        return self._get_path("app_banks_dir", os.path.join(self._base_dir, "banks"))

    @property
    def user_banks_dir(self):
        """Parent des banques de l'utilisateur (KITS, PATCHS, SAMPLES,
        banks/sf2, banks/sfz) ; défaut : le parent du dossier des projets
        (/home/com/groovybox)."""
        return self._get_path("user_banks_dir",
                              os.path.dirname(os.path.normpath(self.projects_dir)))

    # Fichiers déplacés (P9)

    SF_EXTS = (".sf2", ".sf3")

    def relocate(self, path):
        """Chemin d'un fichier de banque (soundfont, source SFZ) enregistré
        dans un projet :
        - sous un ancien dossier (/usr/share/sounds/sf2 → soundfonts_dir,
          media/sfz → sfz_dir) : le même chemin relatif dans le nouveau
          dossier s'il s'y trouve, même si l'ancien fichier existe encore
          (soundfonts copiées, originaux du système laissés en place) ;
        - sinon tel quel s'il existe ;
        - sinon le même nom dans soundfonts_dir (soundfont) ou sfz_dir
          (autre) ; inchangé si rien n'est trouvé."""
        if not isinstance(path, str) or not path:
            return path
        norm = os.path.normpath(path)
        pairs = ((self.SOUNDFONTS_DIR_DEFAULT, self.soundfonts_dir),
                 (self.legacy_sfz_dir, self.sfz_dir))
        for old, new in pairs:
            old = os.path.normpath(old)
            if os.path.normpath(new) != old and norm.startswith(old + os.sep):
                cand = os.path.join(new, os.path.relpath(norm, old))
                if os.path.exists(cand):
                    return cand
        if os.path.exists(path):
            return path
        is_sf = os.path.splitext(norm)[1].lower() in self.SF_EXTS
        folder = self.soundfonts_dir if is_sf else self.sfz_dir
        cand = os.path.join(folder, os.path.basename(norm))
        return cand if os.path.exists(cand) else path
