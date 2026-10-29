# Spécifications — GroovyboxIt

Application desktop Python permettant de jouer des sons via le pavé numérique, de séquencer des patterns et des songs.

**Note architecture** : prototype Python. Si le test est concluant, les parties nécessitant plus de performances (moteur audio, pitch shifting) seront réécrites en C/C++.

---

## État d'avancement

| Phase | Description | État |
|---|---|---|
| Phase 1 | Lecture directe (mode Drum basique) | ✓ |
| Phase 2 | Séquenceur, patterns, grille, BPM | ✓ |
| Phase 3 | MIDI, Keyboard/Synth, pitch shifting, presets, explorateur | ✓ |
| Phase 4 | SoundDeviceDriver, AudioSampler, Transport avancé, MIDI CC/Pitch Bend/Mod Wheel | ✓ |
| Phase 5 | Mode Song, UndoManager, ProjectManager, TrackEditor, LoopSelectDialog, cache disque, Tap Tempo | ✓ |
| Phase 6 | Éditeur MIDI (MidiEditorWindow), QuantizeDialog avancée, GridDialog | en cours |
| Phase 7 | Standardisation TapeEvent, parser MIDI, CC/PGM/Bend dans `_tape`, découpage du player, 16 pistes et canal par piste, export MIDI (.mid), conversion GM des notes de kit, courbe de volume GM et réglages GM par slot, Undo du mixage (mute, solo, volume, pan), volume et pan globaux sauvegardés, Undo des boucles, point propre de l'Undo, slot Banque FluidSynth (SF2/SF3, modèle « orchestre » : le canal est l'instrument), import MIDI (.mid → pattern) | en cours |

---

## Stack technique

| Rôle | Bibliothèque |
|---|---|
| GUI | `wxPython` |
| Audio (kit et synthé) | `sounddevice` + `numpy` (SoundDeviceDriver — seul driver utilisé par l'application) |
| Audio (ancien driver, optionnel) | `pygame.mixer` (PygameDriver) — non requis pour lancer l'application, utilisé seulement par des tests et `tools/bench_latency.py` |
| Pitch shifting | `pyrubberband` (bindings Python de Rubber Band C++) |
| Lecture WAV | `soundfile` |
| Traitement audio | `numpy` |
| MIDI in/out | `rtmidi` (via `python-rtmidi`) |
| Fichiers MIDI (.mid) | `mido` — export du pattern (Phase 7 étape 10h1), import (Phase 7 étape 18b1) |
| Effets (futur) | `pedalboard` (Spotify) |

---

## Structure du projet

```
groovyboxit/
├── main.py               # Point d'entrée
├── requirements.txt      # Dépendances (pip3 install -r requirements.txt --break-system-packages)
├── src/
│   ├── app_config.py     # Chargement data/config.json, chemins configurables
│   ├── audio_sampler.py  # AudioSampler : boucle, crossfade, ADSR, pitch shifting
│   ├── audio_tools.py    # Détection de points de bouclage (AudioTools)
│   ├── bend_log.py       # Traces pitch bend dans bend_log.txt (si GROOVY_BEND_LOG=1)
│   ├── engines/          # Moteurs de banque (Phase 7 étape 17)
│   │   ├── bank_engine.py      # BankEngine : interface (emplacements, canaux, rendu)
│   │   └── fluidsynth_engine.py # FluidSynthEngine : FluidSynth par ctypes (SF2/SF3)
│   ├── loop_manager.py   # LoopManager + LoopWindow : fenêtre de boucle pattern
│   ├── main.py           # Point d'entrée secondaire (importé par main.py racine)
│   ├── metronome.py      # Classe Metronome isolée
│   ├── note.py           # Utilitaires note MIDI
│   ├── pattern.py        # Données pattern : grille, _tape (TapeEvent G/K/P)
│   ├── project_manager.py # Chargement/sauvegarde .gvp (JSON)
│   ├── pygame_driver.py  # PygameDriver : backend audio pygame.mixer
│   ├── quantize_manager.py # QuantizeManager : quantisation grille/tape, double/halve
│   ├── rack.py           # Rack 16 slots + InstrumentType
│   ├── song.py           # Données Song : séquence ordonnée de patterns
│   ├── sound_cache.py    # Cache disque sons pré-calculés (.npz sha256)
│   ├── sound_device_driver.py # SoundDeviceDriver : backend audio polyphonique
│   ├── sound_manager.py  # Lecture WAV : kits, note_map, pad_sound
│   ├── synth_engine.py   # Moteur synthé : chargement patch, pitch shifting, cache
│   ├── track_editor.py   # TrackEditor : sélection multi-pistes, limiteurs, clipboard
│   ├── track_router.py   # Routage piste→slot→SynthEngine, dispatch audio
│   ├── undo_manager.py   # UndoManager : historique annulations/rétablissements
│   ├── voice_manager.py  # Volume, pan, mute, solo, durée par pad
│   ├── midi/             # MIDI (Phase 7 étape 3, export en Phase 7 étape 10, import en Phase 7 étape 18)
│   │   ├── midi_constants.py # Noms CC, GM, kits GM2 ; guess_gm_program
│   │   ├── midi_editor.py    # MidiEditor : logique événements MIDI (lecture, édition)
│   │   ├── midi_export.py    # Export du pattern en fichier .mid (mido, SMF type 1)
│   │   ├── midi_import.py    # Import d'un fichier .mid en pattern (Phase 7 étape 18b1)
│   │   ├── midi_manager.py   # Connexion ports MIDI in/out
│   │   └── midi_parser.py    # Décodage des messages MIDI temps réel
│   ├── player/           # Séquenceur DrumPlayer (Phase 7 étape 8)
│   │   ├── drum_player.py  # DrumPlayer : état (__init__), propriétés, délégations quantisation
│   │   ├── dp_transport.py # Mixin : thread, play/stop/pause, song, click, BPM
│   │   ├── dp_position.py  # Mixin : position du playhead, statut, déplacements
│   │   ├── dp_playback.py  # Mixin : boucle de lecture _run_thread et ses 3 étapes
│   │   ├── dp_live.py      # Mixin : jeu live des pads, Note Repeat, volume, pan
│   │   ├── dp_recording.py # Mixin : enregistrement (record_*), positions de capture
│   │   └── dp_erase.py     # Mixin : mode Erase
│   └── ui/
│       ├── dialogs.py          # Boîtes de dialogue (explorateur)
│       ├── dialogs_bank.py     # BankSlotDialog : fichier et emplacement d'un slot Banque
│       ├── dialogs_properties.py # Boîtes de propriétés (Pad, Track, Pattern, GridDialog)
│       ├── dialogs_simple.py   # Boîtes simples (GenRow, Save, Rename…)
│       ├── dialogs_temporal.py # Boîtes temporelles (LoopSelectDialog, GotoDialog, QuantizeDialog)
│       ├── key_handler_alt.py  # Raccourcis Alt+*
│       ├── key_handler_chars.py # Raccourcis caractères (H, R, E, Q…)
│       ├── key_handler_ctrl.py # Raccourcis Ctrl+*
│       ├── key_handler_navigation.py # Navigation (flèches, Home/End, PgUp/Dn)
│       ├── key_handler_numpad.py # Pavé numérique
│       ├── key_manager.py      # Gestion clavier (dispatch vers mixins)
│       ├── key_transport.py    # Raccourcis transport partagés (Play, Stop, Goto…)
│       ├── main_window.py      # Fenêtre principale (mixins)
│       ├── midi_editor_window.py # Fenêtre Éditeur MIDI (Alt+4)
│       ├── midi_handler_window.py # Logique MIDI (séparée de MainWindow)
│       ├── mw_midi_editor.py   # Mixin MainWindow : ouverture éditeur MIDI
│       ├── mw_pads.py          # Mixin MainWindow : pads et grille
│       ├── mw_patterns.py      # Mixin MainWindow : gestion patterns
│       ├── mw_project.py       # Mixin MainWindow : projet (sauvegarde, chargement)
│       ├── mw_songs.py         # Mixin MainWindow : fenêtre Songs
│       ├── mw_tracks.py        # Mixin MainWindow : pistes et dispatch
│       └── song_window.py      # Fenêtre Songs (Alt+5)
├── data/
│   ├── config.json       # Chemins configurables (voir §Configuration)
│   ├── kits/             # Fichiers kit JSON (ex. tr_707.json)
│   ├── presets/          # Presets JSON (ex. preset_01.json)  [ancien format]
│   └── PROJECTS/         # Projets .gvp (ex. project_01.gvp)
├── media/                # Sons drum par défaut (1.wav … 16.wav) + métronome
├── tools/
│   ├── bench_latency.py      # Comparaison latence PygameDriver vs SoundDeviceDriver
│   ├── check_specs_tests.py  # Vérifie que SPECS.md liste tous les tests/test_*.py
│   ├── diag_loop.py          # Diagnostic points de bouclage
│   ├── extract_gm_drums.py   # Script extraction drums GM depuis FluidSynth
│   ├── extract_instruments_sf2.py # Exporteur général d'instruments SF2
│   ├── extract_organ_sf2.py  # Extraction samples orgue depuis SF2
│   └── find_loop_points.py   # Détection points de bouclage
├── docs/
│   └── shortcuts.md      # Liste des raccourcis clavier
└── tests/
    ├── test_all.sh
    ├── conftest.py
    ├── test_app_config.py
    ├── test_app_launch.py
    ├── test_audio_sampler.py
    ├── test_bank_dialogs.py
    ├── test_bank_slot.py
    ├── test_bend_log.py
    ├── test_cc_event_edit_dialog.py
    ├── test_check_specs_tests.py
    ├── test_event_filter_dialog.py
    ├── test_explorer_actions.py
    ├── test_explorer_dialog.py
    ├── test_fluidsynth_engine.py
    ├── test_gm_program.py
    ├── test_gm_slot_export.py
    ├── test_key_manager.py
    ├── test_kit_channel_migration.py
    ├── test_live_take.py
    ├── test_load_project_cache.py
    ├── test_loop_points_pattern.py
    ├── test_loop_points_player.py
    ├── test_loop_select_dialog.py
    ├── test_loop_undo.py
    ├── test_master_mix.py
    ├── test_midi_constants.py
    ├── test_midi_editor.py
    ├── test_midi_editor_filter.py
    ├── test_midi_editor_window.py
    ├── test_midi_export.py
    ├── test_midi_export_mix.py
    ├── test_midi_export_ui.py
    ├── test_midi_import.py
    ├── test_midi_import_ui.py
    ├── test_midi_handler_window.py
    ├── test_midi_manager.py
    ├── test_midi_parser.py
    ├── test_midi_virtual_keyboard.py
    ├── test_mix_undo.py
    ├── test_multitrack.py
    ├── test_mute_groups.py
    ├── test_pad_properties_dialog.py
    ├── test_pattern.py
    ├── test_pattern_grid_api.py
    ├── test_pattern_properties_bug.py
    ├── test_pattern_properties_dialog.py
    ├── test_pattern_serialization.py
    ├── test_playback_loop.py
    ├── test_pygame_driver.py
    ├── test_quantize.py
    ├── test_rename.py
    ├── test_save_confirm_dialog.py
    ├── test_sixteen_tracks.py
    ├── test_song.py
    ├── test_song_serialization.py
    ├── test_sound_cache.py
    ├── test_sound_device_driver.py
    ├── test_sound_manager.py
    ├── test_step_duration.py
    ├── test_synth_engine.py
    ├── test_synth_utils.py
    ├── test_tap_tempo.py
    ├── test_tape.py
    ├── test_track_channels.py
    ├── test_track_editor.py
    ├── test_track_properties_dialog.py
    ├── test_track_router.py
    ├── test_track_select_dialog.py
    ├── test_transport.py
    ├── test_undo_clean_point.py
    ├── test_undo_manager.py
    └── test_voice_manager.py
```

---

## Configuration (`data/config.json`)

```json
{
  "patches_dir":  "/chemin/vers/PATCHS",
  "samples_dir":  "/chemin/vers/SAMPLES",
  "kits_dir":     "/chemin/vers/KITS",
  "presets_dir":  "/chemin/vers/PRESETS",
  "media_lst":    ["/chemin/son1.wav", "/chemin/son2.wav"],
  "click1":       "/chemin/click_downbeat.wav",
  "click2":       "/chemin/click_beat.wav",
  "sound_cache_dir": "/chemin/cache_npz",
  "exports_dir":  "/chemin/vers/EXPORTS",
  "master_volume": 100,
  "master_pan":    0,
  "soundfonts_dir":   "/usr/share/sounds/sf2",
  "gm_soundfont":     "FluidR3_GM.sf2",
  "midi_bank_select": "gs",
  "fluidsynth_gain":  0.4
}
```

Slot Banque (Phase 7 étape 17) : `soundfonts_dir` (dossier ouvert par
« Parcourir… », défaut `/usr/share/sounds/sf2`), `gm_soundfont` (fichier
proposé pour un emplacement vide, absolu ou relatif à `soundfonts_dir`,
défaut `FluidR3_GM.sf2`), `midi_bank_select` (`"gs"` : le MSB seul choisit
la banque ; `"mma"` : banque = MSB × 128 + LSB), `fluidsynth_gain` (0.0 à
10.0, défaut 0.4 : sans écrêtage sur un orchestre GM importé, Phase 7 étape
18d4 ; 1.0 avant).

`master_volume` (0..100, défaut 100) et `master_pan` (−100..100, défaut 0) sont le volume et le pan globaux **par défaut** (Phase 7 étape 15d1) : ils servent au lancement, à Ctrl+N, et à l'ouverture d'un ancien projet qui n'a pas sa clé `master`. Un projet garde ensuite ses propres valeurs. Une valeur hors bornes est bornée ; une valeur invalide donne le défaut. L'appli n'écrit jamais `config.json` : on le modifie à la main (un dialogue de réglage est prévu plus tard).

`exports_dir` (export MIDI, Alt+Shift+E ; premier dossier proposé par l'import, Alt+Shift+I) vaut par défaut le dossier `EXPORTS`
voisin du dossier des projets (`/home/com/groovybox/EXPORTS`).

Chaque clé est facultative : si absente ou vide, le chemin correspondant tombe en fallback sur un sous-dossier relatif à la racine du projet (`patches/`, `samples/`, `kits/`, `presets/`).

Chargement via `AppConfig(base_dir)` au démarrage.

---

## Rack d'instruments

Le Rack est **global et partagé par tous les patterns**. Il contient 16 slots.

### Types d'instrument (`InstrumentType`)

| Constante | Valeur | Description |
|---|---|---|
| `KIT` | `"kit"` | 16 WAVs indépendants, mappés par note MIDI |
| `SYNTH` | `"synth"` | Patch multi-samples + pitch shifting |
| `LOOP` | `"loop"` | WAV synchronisé BPM (prévu) |
| `AUDIO` | `"audio"` | WAV one-shot libre (prévu) |
| `MIDI_FILE` | `"midi_file"` | Fichier MIDI .mid (prévu) |
| `MIDI_PORT` | `"midi_port"` | Port MIDI externe (prévu) |
| `BANK` | `"bank"` | Banque de sons SF2/SF3 jouée par FluidSynth (Phase 7 étape 17) |

*Implémentés et opérationnels : KIT, SYNTH et BANK.*

### Structure d'un slot

```
Slot
  ├── index   : int (0–15)
  ├── type    : InstrumentType.* (ou None si vide)
  ├── name    : str  (ex. "TR-707", "Piano")
  └── config  : dict
        KIT   → { "kit": "/chemin/vers/kit.json" }
        SYNTH → { "patch": "/chemin/vers/dossier_patch" }
        BANK  → { "bank_slot": 0..3 }  emplacement de banque ; le slot porte
                le nom du fichier ; l'instrument appartient au canal
                (voir « Banques de sons »)
        + "gm_program" (0..127, facultatif) : instrument GM (synthé) ou kit
          GM2 (kit) écrit en Program Change à l'export ; absent → déduit du
          nom du slot (guess_gm_program). Réglable dans les propriétés de piste.
        + "gm_transpose" (-24..+24, facultatif, synthé seulement) : demi-tons
          ajoutés aux notes du synthé à l'export (ex. DrawbarOrgan +24, le
          preset FluidR3 sonnant deux octaves sous la note écrite)
        + "gm_gain_db" (-40..0, facultatif, tout slot non vide) : atténuation
          des CC7 de la piste à l'export, pour compenser la normalisation
          des échantillons de l'appli
        Les trois réglages GM ne touchent que l'export ; ils sont réglables
        dans les propriétés de piste et partagés par les pistes du slot.
```

### Sérialisation Rack

`Rack.to_dict()` / `Rack.from_dict(data)` — inclus dans le preset JSON sous la clé `"rack"`.
Le Rack porte aussi `bank_files` : le fichier de chacun des 4 emplacements de
banque (chemin ou `null`), absent des projets d'avant la Phase 7 étape 17
(emplacements vides).

---

## Banques de sons (type BANK, FluidSynth)

Phase 7 étape 17 (docs/DESIGN.md § 17a1, 17e3). Principe : retrouver les
habitudes d'un séquenceur comme Sonar devant un module General MIDI.

- **Moteur** : `FluidSynthEngine` (FluidSynth par ctypes, une seule
  instance, 16 canaux), rendu ajouté au mixage du pilote audio avant le
  volume global ; muet si `libfluidsynth` est absente. Lit SF2 et SF3
  (pas le SFZ).
- **4 emplacements** : un fichier chargé une seule fois, partagé par les
  slots Banque qui le désignent ; dialogue **« Banque »** de l'Explorateur
  (Alt+X) pour le slot courant (emplacement, fichier).
- **Le canal est l'instrument** : chacun des 16 canaux a un programme et
  une banque (MSB / LSB), entendus par toutes les pistes de ce canal ;
  sans Program Change : programme 0, banque 0. **Canal 10 = batterie**
  (banque 128 de la soundfont, MSB et LSB sans effet).
- **Programme et banque sont des événements de la piste** : CC0 (MSB),
  CC32 (LSB) et Program Change de `_tape`. L'**entête** d'une piste = ces
  trois événements à 1.1.1. Un Program Change porte un canal : la piste
  passe sur ce canal (changer d'instrument en cours de morceau) ; CC0 et
  CC32 vont à leur propre canal.
- **Poursuite** : au démarrage de la lecture, à chaque saut de position,
  au changement de pattern, à l'avance du song et après Undo, chaque
  canal retrouve le dernier programme et la dernière banque rencontrés
  avant la position, chaque piste le canal de son dernier Program Change.
- **Contrôleur** : un Program Change ou un Bank Select reçu hors
  enregistrement ne change que le son ; la relance de la lecture rejoue
  la piste. Enregistrés, ils sont remis au canal de la piste.
- **Propriétés de piste (Alt+Entrée)** sur une banque, en direct : liste
  « Programme du canal N » (128 programmes, noms lus dans la soundfont,
  « (vide) »), Banque MSB et LSB ; changer de canal fait entendre
  l'instrument de ce canal ; chaque changement réécrit l'entête de la
  piste (et des autres pistes du canal qui en ont un), joue une note
  d'aperçu (do central, grosse caisse au canal 10) et survit au
  bouclage ; Annuler remet les pistes d'origine.
- **Notes** : grille → gamme du pattern (36 + pad au canal 10) ; KIT et
  PATCH telles quelles ; volume et pan de piste → CC7 et CC10 du canal,
  pan global ajouté.
- **Deux pistes d'un même canal sur deux emplacements** : avertissement,
  la dernière l'emporte.
- **Pédale, Pitch Bend, modulation** (Phase 7 étape 18d3, comme Sonar) :
  la pédale (CC64) d'une piste ne tient que son canal, même piste muette
  (sur un synthé WAV, elle reste globale) ; à l'arrêt, à la pause et en
  fin de lecture, pédale, Pitch Bend et modulation sont remis à zéro sur
  les 16 canaux (« Zero Controllers When Play Stops ») ; la poursuite
  reprend aussi la dernière pédale, le dernier Pitch Bend et la dernière
  modulation de chaque canal avant la position, sinon zéro (« MIDI Event
  Chase on Play »).
- **Événements simultanés** rejoués dans l'ordre de la piste (Phase 7
  étape 18d3) : un Reset All Controllers (CC121) suivi d'une pédale
  enfoncée laisse la pédale enfoncée.

---

## Kits (type KIT)

### Fichier kit JSON

```json
{
  "name": "TR-707",
  "pads": [
    { "pad": 1, "note": 35, "filename": "/chemin/35_BassDrum2.wav", "label": "Kick 2", "mute_group": 0 },
    { "pad": 2, "note": 36, "filename": "/chemin/36_BassDrum1.wav", "label": "Kick 1", "mute_group": 0 },
    { "pad": 5, "note": 46, "filename": "/chemin/46_HiHatOpen.wav", "label": "HH Open", "mute_group": 1 },
    { "pad": 6, "note": 42, "filename": "/chemin/42_HiHatClosed.wav", "label": "HH Closed", "mute_group": 1 },
    ...
    { "pad": 15, "note": 49, "filename": "/chemin/49_CowBell.wav", "label": "Cowbell", "gm_note": 56 },
    { "pad": 16, "filename": "", "label": "---" }
  ]
}
```

- `base_note` (facultatif, défaut 36) : note du pad 1 pour `shift_kit` et
  pour un pad sans `note`
- `gm` (facultatif, au niveau du kit) : `true` si le kit est déjà rangé
  selon la table de batterie GM ; ses notes sont alors exportées telles
  quelles (`data/kits/gm.json`)
- `note` : note MIDI du son dans le kit (pas forcément la note GM),
  utilisée pour le mapping MIDI et le pitch
- `gm_note` (facultatif, 35–81) : note GM écrite à l'export MIDI ;
  prioritaire sur `gm` et sur la note devinée d'après `label`
- `filename` : chemin absolu ou relatif au JSON
- `label` : nom affiché dans la liste des pads
- `mute_group` : groupe de mute exclusif (0 = aucun, ≥1 = groupe partagé). Au sein d'un même groupe, jouer un son coupe les voix actives du même groupe (comportement hihat open/closed TR-style)

### SoundManager — API Kit

| Méthode | Description |
|---|---|
| `load_kit(json_path)` | Charge le kit, construit `drum_sounds[16]`, `note_map`, `pad_notes` et `gm_note_map` |
| `load_pad_sound(pad_idx, wav_path)` | Remplace un son individuel dans `drum_sounds` |
| `load_sounds()` | Charge les sons par défaut depuis `media/` |
| `play_sound(index, vol, pan)` | Joue `drum_sounds[index]` |
| `play_note(midi_note, vol, pan)` | Joue via `note_map[midi_note]` |
| `shift_kit(delta)` | Décale `kit_offset` de ±8 (plage : 0 — max notes du kit) |
| `set_pad_mute_group(pad_idx, group)` | Définit le mute_group d'un pad (synchronisé avec VoiceManager) |

- `drum_sounds` : liste de 16 `pygame.Sound`, reconstruite à partir de `note_map` + `kit_base` + `kit_offset`
- `note_map` : `{midi_note: pygame.Sound}` — tous les sons du kit avec champ `"note"`
- `mute_groups` : liste de 16 entiers (0 = aucun groupe)
- `pad_notes` : note de kit du son de chaque pad (`note` de l'entrée du
  pad, ou `kit_base + kit_offset + i` après `shift_kit`) — Phase 7 étape 11
- `gm_note_map` : `{note du kit: note GM}` pour l'export MIDI, par ordre de
  priorité : `gm_note`, `"gm": true` (identité), note devinée d'après
  `label` (`midi_constants.guess_gm_drum_note`) ; une note sans
  correspondance est absente

---

## Patches (type SYNTH)

### Structure d'un patch

Un patch = un répertoire contenant `patch.json` et des fichiers WAV :

```
/PATCHS/Piano/
  ├── patch.json
  ├── 01_C1.wav
  ├── 02_C2.wav
  └── ...
```

### Fichier `patch.json`

```json
{
  "name": "Piano",
  "loop": false,
  "loop_start": null,
  "loop_end": null,
  "samples": [
    { "file": "01_C1.wav", "root": "C1" },
    { "file": "02_C2.wav", "root": "C2" }
  ]
}
```

- `root` : note racine du sample (`"C3"`, `"A4"`, etc.)
- `loop` : `true` → boucle en sustain (orgue, cordes) ; `false` → one-shot (piano, percussions)
- `loop_start` / `loop_end` : secondes (par sample ou au niveau racine). Calculés automatiquement par `find_loop_points.py`
- Rétrocompatibilité : `"sounds"` accepté comme alias de `"samples"`, `"rootnote"` comme alias de `"root"`

### SynthEngine — comportement

- Chargement du patch → lecture de chaque WAV avec `soundfile`
- `precompute(notes)` : pré-calcule les notes MIDI demandées via `pyrubberband` et les met en cache comme `pygame.Sound`
- `play(midi_note, vol, pan, duration_ms)` : lecture depuis le cache (latence nulle)
- Cache : `{(midi_note, duration_ms): pygame.Sound}`
- Pré-calcul en arrière-plan (`threading.Thread`)
- `load_single_sample(wav_path, root_midi)` : charge un seul sample (mode Kit pitché)

---

## Backends audio

### SoundDeviceDriver (driver par défaut)

Moteur audio polyphonique bas niveau, remplace pygame.mixer pour la lecture des sons one-shot et pitchés. Utilise `sounddevice` + `numpy` en streaming.

- `play(data, samplerate, vol, pan)` : lecture d'un tableau numpy (stéréo ou mono)
- Polyphonie illimitée : toutes les voix actives sont mixées dans un callback audio
- Latence faible : pas de conversion pygame.Sound, lecture directe du PCM numpy

### PygameDriver (backend alternatif)

Wrapper `pygame.mixer` conservé pour compatibilité et benchmarks. Injecté dans `SoundManager` au démarrage si explicitement demandé.

### AudioSampler

Classe d'échantillonnage complète pour les instruments nécessitant boucle et ADSR (orgue, cordes…).

```
AudioSampler
  ├── data            np.ndarray (PCM stéréo float32)
  ├── samplerate      int
  ├── mode            PlayMode.ONE_SHOT | LOOP | PING_PONG
  ├── loop_start      float (secondes)
  ├── loop_end        float (secondes)
  ├── crossfade_ms    float
  └── adsr            (attack_ms, decay_ms, sustain_lvl, release_ms)
```

Méthodes principales :

| Méthode | Description |
|---|---|
| `from_file(wav_path)` | Chargement WAV, lecture chunk `smpl` si présent |
| `set_mode(mode)` | ONE_SHOT / LOOP / PING_PONG |
| `set_loop(start, end, crossfade_ms)` | Définit les points de bouclage et cross-fade |
| `set_adsr(attack, decay, sustain, release)` | Enveloppe ADSR en ms + niveau sustain |
| `pitch_shift(n_steps)` | Décalage en demi-tons (Rubber Band / WSOLA / phase vocoder) |
| `render(duration_ms)` | Produit le tableau PCM final (avec ADSR, boucle, crossfade) |
| `snap_to_zero_crossing(pos)` | Alignement sur le passage à zéro le plus proche |

- Lit le chunk `smpl` des fichiers WAV (loop points embarqués, ex. sortie FluidSynth)
- Cross-fade FluidSynth-style aux points de bouclage
- Trois algorithmes de pitch shifting : Rubber Band (C++), WSOLA, phase vocoder

### Cache disque (`sound_cache.py`)

Cache persistant des sons pré-calculés pour éviter de recalculer le pitch shifting à chaque démarrage.

- Clé : hash SHA-256 du chemin WAV + mtime + paramètres (n_steps, duration_ms, loop_start, loop_end)
- Format : fichier `.npz` (numpy compressé) par clé
- `init(cache_dir)` : initialisation avec le répertoire configuré dans `AppConfig.sound_cache_dir`
- `load(key)` / `save_async(key, data, loop_start, loop_end)` : lecture/écriture
- Éviction automatique si le cache dépasse la taille limite

---

## Gammes disponibles

Définies dans `synth_engine.SCALES`, accessible via `SCALE_NAMES` :

| Clé | Nom affiché | Intervalles |
|---|---|---|
| `chromatic` | Chromatique | 0 1 2 3 4 5 6 7 8 9 10 11 |
| `major` | Majeur | 0 2 4 5 7 9 11 |
| `minor_nat` | Mineur naturel | 0 2 3 5 7 8 10 |
| `minor_harm_1` | Mineur harmonique | 0 2 3 5 7 8 11 |
| `pentatonic_major` | Penta majeur | 0 2 4 7 9 |
| `pentatonic_minor` | Penta mineur | 0 3 5 7 10 |

`scale_midi_notes(scale, root_midi, count)` → liste de `count` notes MIDI.

---

## Modes de jeu

### Mode Pad (Ctrl+1)

- NumPad 1–8 / 9–16 déclenche le son du kit chargé sur la piste courante
- NumPad+ : passer aux pads 9–16 / NumPad- : revenir aux pads 1–8
- Mode MIDI : chaque note entrante est mappée directement sur un pad via `note_map`

### Mode Keyboard (Ctrl+2)

Deux comportements selon le type du slot courant :

**Slot SYNTH** :
- NumPad 1–8 joue les 8 premières notes de la gamme courante (pré-calculées)
- NumPad+ : octave suivante / NumPad- : octave précédente
- NumPad/ : gamme précédente / NumPad* : gamme suivante
- Clavier MIDI : 25 notes de gamme (`kb_notes`), précalculées
- NumPad joue sur 16 notes (`kb_notes_input`), transposables indépendamment

**Slot KIT** (batterie pitchée, style Maschine+) :
- Le dernier pad joué est pitché sur les notes de la gamme
- NumPad 1–8 joue le pad source pitché sur 8 notes de la gamme
- Root C4 = pitch original du son
- NumPad+/- décale l'octave, NumPad/* change de gamme

### TrackRouter — routage audio multi-piste

```
TrackRouter
  ├── _track_slots[16]    slot assigné à chaque piste (défaut : slot 0)
  ├── _track_channels[16] canal MIDI de chaque piste (0..15, export MIDI)
  ├── _track_cur_channels[16] canal courant d'une piste Banque (dernier Program Change)
  ├── _chan_prog/_msb/_lsb[16] instrument de chaque canal (slot Banque)
  ├── bank_engine         moteur de banque (FluidSynthEngine ou None)
  ├── _slot_synths        {slot_idx: SynthEngine} — un moteur par slot SYNTH commis
  ├── _synth              moteur de preview interactive (slot courant)
  ├── _kit_synth          moteur dédié au mode Keyboard/KIT pitché
  ├── kb_notes[25]        notes MIDI de gamme pour le clavier MIDI
  └── kb_notes_input[16]  notes MIDI de gamme pour le Numpad (transposables)
```

`on_play(track, pad, vol, pan, dur)` :
- Slot KIT → `sound_manager.play_sound(pad_idx)`
- Slot SYNTH → `_slot_synths[slot_idx].play(kb_notes[pad_idx])`
- Slot BANK → note au moteur de banque sur le canal courant de la piste
  (`chase(tape, pos)` rétablit instruments et canaux, voir « Banques de sons »)

---

## Patterns

### Structure

```
Pattern
  ├── _name          str
  ├── _bpm           float (tempo)
  ├── _num_bars      int (1–999)
  ├── _num_steps     int (16, 32, 64, 128 — pas par mesure)
  ├── _start_bar     int (première mesure jouée)
  ├── _looping       bool
  ├── _loop_start    int | None (step de début de boucle ; None = début du pattern)
  ├── _loop_end      int | None (step de fin de boucle ; None = fin du pattern)
  ├── _loop_count    int (répétitions : 0 = infini)
  ├── _track_slots   [int × 16]  slot assigné à chaque piste
  ├── _track_mutes   [bool × 16]
  ├── _track_solos   [bool × 16]
  ├── _track_volumes [int × 16]  0..100
  ├── _track_pans    [int × 16]  -100..+100
  ├── _track_channels [int × 16] canal MIDI 0..15 (piste N → canal N ; kit → 10)
  ├── _voices        [dict × 16] volume, pan, mute, solo, durée par pad
  └── _tape          {(track, bar, step): [TapeEvent]}  capture unifiée
```

- 99 patterns disponibles (Pattern 01–99)
- 16 pistes par pattern (une par canal MIDI ; les presets à 8 pistes sont complétés au chargement, Phase 7 étape 10d1)
- 16 pads par piste
- Pas : vélocité 0 (inactif) ou 1–127 (actif avec vélocité)

### TapeEvent — capture MIDI unifiée

```python
TapeEvent(etype, dur=0, channel=0, payload={...}, time=pas)   # + id unique
```

| `etype` | Source | `payload` |
|---|---|---|
| `ETYPE_GRID` | Grille | `{"pad", "vel"}` |
| `ETYPE_KIT` | Kit MIDI | `{"note", "vel"}` — note MIDI brute (indépendante du kit_offset) |
| `ETYPE_PATCH` | Patch SYNTH | `{"note", "vel"}` — note MIDI absolue + durée réelle (`dur`) |
| `ETYPE_CC` | Control Change | `{"cc_num", "value"}` |
| `ETYPE_PGM` | Program Change | `{"program"}` |
| `ETYPE_BEND` | Pitch Bend | `{"value"}` -8192..+8191 |

Toutes les sources sont stockées dans `_tape[track] = [TapeEvent, …]` (liste
plate par piste, `time` en pas cumulés ; flottant non quantifié pour CC et
Pitch Bend). La grille (`ETYPE_GRID`) remplace l'ancien `_curpattern` comme
structure canonique. Une note PATCH ne porte plus de bend (Phase 7 étape 7) :
voir Pitch Bend temps réel.

### Quantisation

Valeurs disponibles (`Pattern.QUANT_STEPS`) :
`[1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128]`

Résolutions de grille (`Pattern.GRID_RESOLUTIONS`) :

| Label | Type | Description |
|---|---|---|
| 4 mes. | bars | 4 mesures par snap |
| 3 mes. | bars | 3 mesures par snap |
| 2 mes. | bars | 2 mesures par snap |
| 1 mes. | snaps | 1 mesure = 1 division |
| 1/2 … 1/128 | snaps | Division de mesure |

Résolution par défaut : 1/16 (index 10). Modifiable via GridDialog (Ctrl+Shift+G).

---

## QuantizeManager — quantisation avancée

`apply_quant_to_pattern(quant_idx, force_idx, swing_idx, window_idx, quant_starts, quant_durations, direction_idx)`

| Paramètre | Valeurs | Description |
|---|---|---|
| `quant_idx` | index dans QUANT_STEPS | Division cible |
| `force_idx` | 0..4 → 0/25/50/75/100 % | Attraction vers la grille |
| `swing_idx` | 0..4 → 0/25/50/75/100 % | Décalage des temps impairs (swing) |
| `window_idx` | 0..4 → 0/25/50/75/100 % | Fenêtre de capture (0% = tout, 100% = demi-division) |
| `quant_starts` | bool | Aligner les débuts de notes |
| `quant_durations` | bool | Aligner les durées (K/P uniquement) |
| `direction_idx` | 0/1/2 | 0=Proche, 1=Précédente, 2=Suivante |

- La grille intègre le swing : les temps impairs sont décalés de `swing_pct × step_size/2`
- La fenêtre de capture définit la zone où une note est attirée (au-delà = ignorée)
- La direction détermine si la note est snapée sur le point de grille le plus proche, le précédent ou le suivant

Raccourcis :
- `Ctrl+Q` : quantiser le pattern depuis les paramètres de la grille courante (sans dialog)
- `Shift+Q` : quantiser avec les derniers paramètres mémorisés (sans dialog)
- `Ctrl+Shift+Q` : ouvrir QuantizeDialog

---

## LoopManager — fenêtre de boucle pattern

Gère la répétition d'une sous-section du pattern pendant la lecture :

```
LoopWindow
  ├── start   int  (step absolu de début)
  ├── end     int  (step absolu de fin, exclu)
  └── count   int  (répétitions restantes ; 0 = infini)
```

- `_loop_start` / `_loop_end` : définis via LoopSelectDialog (Ctrl+Shift+L) ou raccourcis (Ctrl+L / Shift+L)
- `Alt+L` : réinitialise (supprime les points de boucle)
- `Shift+Début` / `Shift+Fin` : naviguer au début/fin de la boucle

---

## Vélocité MIDI en entrée (Vel Level)

5 niveaux de quantification de la vélocité entrante :

| Niveau | Comportement |
|---|---|
| Full Level | Toutes les notes à 127 |
| 4 Levels | Paliers de 32 (4 valeurs) |
| 8 Levels | Paliers de 16 (8 valeurs) |
| 16 Levels | Paliers de 8 (16 valeurs) |
| No Level | Vélocité brute (pas de quantification) |

### Courbe de volume (Phase 7 étape 12b1)

Le facteur de volume d'une note (vélocité × volume du pad × volume de
piste, borné à 0..1) est élevé au carré juste avant le driver
(`midi_constants.gm_gain`, dans `SoundManager.play_sound`, `play_note` et
`SynthEngine.play`) : c'est la courbe d'un lecteur GM (`40·log10`), de
sorte qu'un fichier exporté sonne avec le même équilibre. Une case de
grille garde son échelle /100 (vélocité 100 = maximum). Le métronome et le
volume général ne sont pas concernés.

---

## Note Repeat

- Touche `Q` : activer/désactiver le mode Note Repeat
- En mode actif, appuyer sur un pad déclenche le son en répétition au taux choisi
- Touches 1–8 (clavier) : taux binaires (1/1 à 1/128)
- Touche 9 : basculer binaire ↔ ternaire
- Touches 1–6 (ternaire) : 1/3 à 1/96
- Les répétitions peuvent être enregistrées dans le pattern (si Rec actif)

---

## Enregistrement

### Mode Overdub (R)
- Ajoute les nouvelles notes sans effacer les existantes
- Démarre aussi la lecture si elle n'est pas active

### Mode Remplacement (Shift+R)
- Efface les notes au fil du playback, remplacées par les nouvelles frappes

### Count-In (Ctrl+R)
- 1 mesure de métronome, puis Rec+Play démarre automatiquement
- La première frappe pendant le Count-In est capturée sur le premier temps
- Démarre depuis la position courante du playhead

### Mode Erase (E)
- NumPad 1–8 : efface l'événement le plus proche du temps d'appui sur ce pad
- Fonctionne en temps réel pendant la lecture
- Prend en charge la plage de notes MIDI tenues (effacement par plage)

### Prise et Undo (Phase 7 étape 10d2)
- R, Shift+R, Ctrl+R et l'activation d'Erase ouvrent une prise : un point
  d'Undo est posé avant, le projet est marqué modifié
- À l'arrêt, si `_tape` n'a pas changé, ce point est retiré et l'état
  « modifié » rétabli ; sinon Ctrl+Z annule toute la prise d'un coup
- Effacer sans rien jouer (Remplacement, Erase) compte comme une modification

---

## Transport avancé

Le transport est partagé entre la fenêtre principale, l'éditeur MIDI (Alt+4) et la fenêtre Songs (Alt+5).

### Modes lecture

| Touche | Action |
|---|---|
| Espace / P | Play / Pause (reprend depuis la position pausée) |
| Ctrl+Space | Goto Start + Play immédiat |
| V | Stop All (sons + pattern + Rec + Erase + reset position) |
| g | Goto Start |
| Shift+G | Goto End |
| l | Toggle boucle On/Off |
| U | Afficher l'état (Lecture/Pause/Arrêt) et la position (bar:beat:tick) |

### Navigation temporelle

| Touche | Déplacement |
|---|---|
| PageDown / PageUp | ±1 mesure |
| Ctrl+PageDown / Up | ±1 battement |
| Shift+PageDown / Up | ±1 tick (pas) |
| w / b | ±1 seconde |
| Ctrl+G | Boîte de dialogue Aller à (Unité + Valeur, affiche bar:beat:tick) |

### Position et unités

- Position interne en **ticks absolus** (offset flottant)
- `move_by_ticks/beats/bars/seconds` : déplacements relatifs avec clamp
- `navigate_bar` : snap sur la mesure la plus proche (fenêtre 100 ms, style DAW)
- Affichage : `bar:beat:tick / total` dans la barre de statut

### Panic (Ctrl+F12)

Arrêt immédiat de tous les sons + envoi CC#120 (All Sounds Off) + CC#121 (Reset All Controllers).

### MIDI CC supportés

| CC | Nom | Comportement |
|---|---|---|
| #1 | Mod Wheel | LFO vibrato : profondeur max ±2 demi-tons sur le pitch |
| #7 | Volume | Volume pad ou piste selon le focus |
| #10 | Pan | Pan pad ou piste selon le focus |
| #64 | Sustain Pedal | Sustain/release différé des notes actives |
| #120 | All Sounds Off | Arrêt immédiat de toutes les voix |
| #121 | Reset All Controllers | Réinitialisation (Mod, Sustain…) |
| #123 | All Notes Off | Arrêt propre de toutes les voix |

Depuis la Phase 7 étape 4, **tout** CC reçu (y compris ceux sans effet câblé)
est capturé pendant Rec dans `_tape` (etype `ETYPE_CC`, payload
`{"cc_num", "value"}`), affichable/filtrable/éditable dans la liste Ctrl+2 de
l'éditeur MIDI, en temps flottant non quantifié (Phase 7 étape 5b — un
contrôleur continu ne se tasse pas sur la grille). À la lecture, un CC
capturé rejoue le même effet que sa réception live, appliqué à la piste
d'origine de l'événement (`TrackRouter.on_cc_tape`) — CC#64/120/121/123
restent globaux. CC#1 (Mod Wheel) n'a plus qu'une seule copie, dans `_tape` :
la structure historique dédiée `_mod_tape` a été supprimée (Phase 7 étape 5h).

### Program Change

Capturé dans `_tape` (etype `ETYPE_PGM`, payload `{"program"}`). Effet
**provisoire**, live et à la lecture : réassigne le slot du Rack de la piste
(`assign_slot(track, program % 16)`), en attendant le mode Rack Synth/GM
(16 canaux MIDI → 16 slots avec leurs patchs, lecture de fichiers `.mid`),
où le format MIDI permet un Program Change à tout moment pendant la lecture.
Sur une piste **Banque** (Phase 7 étape 17), le Program Change change
l'instrument de son canal, où passe la piste ; voir « Banques de sons ».

### Pitch Bend temps réel

- `phase_incr` flottant dans le driver audio pour un pitch bend sans artefact
- Automation : enregistrement de la trajectoire complète pendant Rec, relecture exacte
- Capturé dans `_tape` (etype `ETYPE_BEND`, payload `{"value"}` -8192..+8191,
  canal MIDI d'origine), en temps flottant non quantifié comme les CC
  (Phase 7 étape 6). Relecture via `TrackRouter.on_bend_tape`. La structure
  historique dédiée `_bend_tape` a été supprimée (Phase 7 étape 6h1) ; un
  ancien `.gvp` qui en contient est converti à l'ouverture (canal 0).
- Suit le copier/couper/coller de piste et l'effacement par limiteurs comme
  les autres événements de `_tape`.
- Capturé même si aucun synthé n'est prêt sur la piste courante (comme les
  CC) ; statut « Pitch Bend: +N » (valeur brute) dans ce cas, en demi-tons
  sinon (Phase 7 étape 7d1).
- Le bend est un **état de canal**, comme en MIDI : une note PATCH ne porte
  plus de bend (Phase 7 étape 7f1) et joue avec l'état courant du moteur.
  Une molette tenue au note-on pendant Rec pose un point `ETYPE_BEND` au
  temps de la note si l'état de la piste y diffère (bend tenu avant
  d'armer l'enregistrement conservé, sans doublon). À temps égal, le bend
  est rejoué avant la note. Conséquence : deux notes qui se chevauchent
  partagent le même bend.
- Ancien champ `bend` par note (presets sauvés avant la Phase 7 étape 7h1) :
  converti à l'ouverture en points `ETYPE_BEND` selon la même règle, puis
  retiré des notes.

### Mod Wheel CC#1 — LFO vibrato

- Profondeur maximale configurable : ±2 demi-tons
- Automation : capturée dans `_tape` comme n'importe quel CC générique
  (Phase 7 étape 5h, `_mod_tape` supprimé), relecture via
  `TrackRouter.on_cc_tape` → `on_mod_tape`, synchronisée

---

## Volume et Pan

### Global
- Volume global : 0..100 (Ctrl+↑/↓, `+`/`-`, champ « Vol: ») : volume maître du pilote audio, appliqué à tout le mixage
- Pan global : -100..+100 (Ctrl+←/→, Ctrl+0 pour centrer, champ « Pan: ») : décalage ajouté au pan de chaque pad joué
- Une valeur par projet, sauvegardée dans la clé `master` du `.gvp` ; défauts dans `data/config.json` (`master_volume`, `master_pan`), appliqués au pilote dès le lancement (Phase 7 étape 15d1)

### Par pad (Voice Manager)
- Volume : 0..100 (Alt+↑/↓)
- Pan : -100..+100 (Alt+←/→, Alt+0)
- Mute / Solo (X, S)
- Durée en ms (configurable via PadPropertiesDialog)

### Par piste (TrackRouter)
- Volume : 0..100 (Alt+↑/↓ depuis la liste des pistes)
- Pan : -100..+100 (Alt+←/→)
- Mute (X) / Solo (S) par piste
- Appliqués en facteur multiplicatif lors du dispatch audio
- Canal MIDI : Alt+Entrée sur la piste (propriétés), liste Canal ; piste N →
  canal N par défaut, un slot kit assigné met la piste sur le canal 10

---

## BPM et Tap Tempo

- Plage : 1–600 BPM
- Raccourcis : `(` ou `5` → BPM+5 ; `)` → BPM-5
- **Tap Tempo (H)** : 4 frappes minimum pour émettre le BPM ; pause > 2 s repart de zéro
- Stocké par pattern dans `_bpm`
- Affiché et éditable via PatternPropertiesDialog

---

## Pitch Shifting (`pyrubberband`)

- Algorithme : Rubber Band (C++), bindings Python via `pyrubberband`
- Pitch pur : **pas de changement de durée** (phase vocoder / WSOLA)
- Pré-calcul de toutes les notes de la gamme au chargement d'un patch
- Si la gamme ou l'octave change, le pré-calcul est relancé en arrière-plan
- Cache par `(midi_note, duration_ms)` → `pygame.Sound`

---

## Points de bouclage et cross-fading

### Détection (`AudioTools.find_loop_points`)
- Analyse la fin du sample (queue) par corrélation avec le reste du signal
- Paramètres : `tail_ratio` (part analysée, défaut 15%) et `min_corr` (seuil, défaut 0.98)
- Retourne `(loop_start, loop_end)` en secondes, ou `None` si aucun point valide
- Cross-fade aux points de bouclage : appliqué lors du pré-calcul dans `SynthEngine`

### Chunk `smpl` dans les fichiers WAV
- Certains fichiers WAV (sortie FluidSynth, Kontakt…) embarquent des loop points dans le chunk `smpl`
- `AudioSampler.from_file()` lit ce chunk automatiquement

### Script `tools/find_loop_points.py`
- Analyse tous les samples d'un patch et met à jour `patch.json` (`loop_start`/`loop_end` par sample)
- Option `--dry-run` : affiche les résultats sans modifier le fichier
- Options : `--tail`, `--min-corr`

*Statut : détection implémentée, cross-fade FluidSynth-style appliqué dans AudioSampler. Interface graphique d'édition manuelle non terminée.*

---

## Export MIDI (Alt+Shift+E)

Exporte le pattern courant en fichier MIDI standard (`src/midi/midi_export.py`,
Phase 7 étape 10), depuis la fenêtre principale ou l'éditeur MIDI. Un
dialogue propose `Pat_NN[_nom].mid` dans `exports_dir`.

- SMF de type 1, 480 ticks par noire ; piste conductor : nom, tempo
  (un temps = 60/BPM, quel que soit le nombre de pas), signature 4/4
- Une piste SMF par piste non vide et audible, nommée d'après son slot, sur
  le canal de la piste ; en tête : Program Change du slot, volume (CC7,
  atténué du gain GM du slot), pan (CC10), reverb et chorus à 0 (CC91,
  CC93)
- Mute et solo suivis comme au rejeu (Phase 7 étape 12f2) : une piste
  muette ou hors solo n'est pas exportée ; les cases de grille d'un pad
  muet ou hors solo non plus
- Vélocité d'une case de grille = gain joué :
  `round(127 · min(1, vel/100 · volume du pad/100))` (une case par défaut
  sort à 127) ; KIT et PATCH gardent leur vélocité
- Notes d'un synthé transposées de la transposition GM du slot
- Le fichier finit pile à la fin du pattern (Phase 7 étape 12i2) : une
  note qui déborde est coupée, un événement hors du pattern est omis
- Notes : grille (gamme du pattern pour un synthé, note du son du pad
  pour un kit), KIT, PATCH ; les PATCH d'une piste sans synthé, muettes au
  rejeu, ne sont pas écrites ; CC, Program Change et Pitch Bend capturés
- Notes de kit converties en GM (Phase 7 étape 11) : grille d'une piste
  kit et KIT, via `gm_note_map` du kit chargé ; un son sans
  correspondance garde sa note et est signalé au statut
  (`— non converti en GM : Libellé (note)`)
- Non exportés : pan des pads, canal d'origine des événements, résonance
  des notes au-delà de la fin du pattern
- Un seul kit chargé à la fois : toutes les pistes kit sont converties
  avec la table du kit du slot courant
- Un ancien projet sans canaux enregistrés s'ouvre avec ses pistes kit sur
  le canal 10
- Piste sur slot Banque (Phase 7 étape 17) : banque et programme viennent
  de ses événements (entête) ; à tick égal, CC0 et CC32 avant le Program
  Change ; chaque événement sur le canal courant de la piste ; nom de
  piste = nom du preset ; notes KIT non converties

---

## Import MIDI (Alt+Shift+I)

Importe un fichier MIDI standard dans le **pattern courant**
(`src/midi/midi_import.py`, Phase 7 étape 18, docs/DESIGN.md § 18a1),
depuis la fenêtre principale ou l'éditeur MIDI. Un `.mid` = un pattern ;
l'import est l'inverse de l'export, et un aller-retour rend le même
pattern (pan à ±1 près).

- **Dialogue** : `*.mid` et `*.midi`, ouvert dans le dernier dossier
  validé de la session, sinon `exports_dir`. Le fichier est lu avant toute
  question : un fichier illisible n'est signalé qu'au statut. Lecture
  tolérante (octet de données hors 0..127 ramené à 127). SMF de type 2
  refusé.
- **Pattern courant remplacé** : confirmation Oui / Non (Non par défaut)
  s'il n'est pas vide ; lecture arrêtée, lecteur remis à 1.1.1, Undo
  « Import MIDI : nom.mid ». Nom du pattern = nom de la piste conductor,
  sinon nom du fichier (type 0 : nom de son unique piste) ; boucle, mute,
  solo et voix d'un pattern neuf.
- **Slot** : toutes les pistes importées vont sur le premier slot Banque
  du Rack ; sans slot Banque, l'import en crée un dans le premier slot
  vide, avec `gm_soundfont` (emplacement qui la tient déjà, sinon premier
  emplacement libre, sinon le premier) ; Rack plein sans slot Banque :
  import refusé.
- **Pistes** : une piste par couple (piste SMF, canal), dans l'ordre du
  fichier (un type 0 donne une piste par canal) ; au-delà de 16, les
  pistes d'un même canal sont fusionnées. Canal de la piste = canal MIDI ;
  nom SMF → nom de la piste (nom du pad de même numéro).
- **Entête** : Program Change, CC0 et CC32 placés avant la première note
  d'une piste vont à 1.1.1 (CC0, CC32, Program Change ; le dernier de
  chaque type l'emporte). CC7 et CC10 placés avant la première note
  règlent le volume et le pan de la piste.
- **Événements** : notes → PATCH (durée en ms au BPM du pattern ; note on
  de vélocité 0 = note off ; note jamais fermée fermée à la fin de sa
  piste) ; CC, Pitch Bend, Program Change à leur position exacte (temps
  flottant), sur leur canal. Ignorés et comptés : aftertouch, SysEx,
  métas autres que nom, tempo, signature, fin de piste.
- **Temps** : notes **arrondies au pas** : le plus petit nombre de pas
  par mesure (16, 32, 64, 128) qui les place toutes exactement, sinon 128
  et arrondi. Une mesure = 4 noires (autre signature lue en 4/4). BPM =
  premier tempo (120 sans tempo), changements suivants ignorés. Longueur
  = fin la plus tardive, arrondie à la mesure, 1 à 999 mesures. Une
  mesure vide au début est gardée (TiMidity, lui, la saute par défaut).
- **Compte rendu** au statut : pistes, mesures, BPM, pas, slot créé, notes
  déplacées, changements de tempo, signature, fusion, événements perdus,
  messages ignorés.
- Pas encore : notes en temps flottant, carte de tempo (chantiers à
  venir).

---

## Mode Song

### Structure d'un Song

```
Song
  ├── MAX_SONGS   16
  ├── _idx        int (0–15)
  ├── _name       str
  ├── _sequence   [int]  indices 0-based dans _pattern_list (0..98)
  └── _looping    bool
```

- 16 songs disponibles (Song_01–Song_16)
- Chaque song = une liste ordonnée de patterns (un pattern peut apparaître plusieurs fois)
- `label()` : `"Nom (n)"` avec le nombre d'entrées dans la séquence

### SongWindow (Alt+5)

Fenêtre dédiée à la composition de songs :
- **Liste Patterns disponibles** : 99 patterns (Entrée ou double-clic pour ajouter à la fin ; Ctrl+Entrée pour insérer avant la position)
- **Séquence** : liste ordonnée des patterns du song courant (Suppr pour retirer, Alt+↑/↓ pour réordonner)
- **Liste Songs** : 16 songs (sélection du song courant)
- Transport Song-aware : Play/Pause, Goto Start/End, navigate_bar inter-patterns
- Persistance du song courant (`cur_song`) dans le projet

### Lecture Song

- Le player enchaîne les patterns dans l'ordre de la séquence
- `navigate_bar` fonctionne en mode song : si en fin de pattern, passe au pattern suivant/précédent
- PageDown/PageUp naviguent mesure par mesure entre les patterns
- La boucle (`l`) s'applique au song entier

---

## TrackEditor — édition multi-pistes

### Sélection de pistes

```
TrackEditor
  ├── _sel_tracks    set[int]   pistes sélectionnées
  ├── _lim_left      int | None step de début de plage temporelle
  └── _lim_right     int | None step de fin de plage temporelle
```

| Raccourci | Action |
|---|---|
| Ctrl+A | Sélectionner toutes les pistes + limiteurs sur plage complète |
| Ctrl+Shift+A | Désélectionner tout + réinitialiser les limiteurs |
| Shift+Espace | Ajouter/retirer la piste courante de la sélection (non-adjacente) |
| Shift+↑/↓ | Étendre la sélection vers le haut/bas (adjacentes) |
| ↑/↓ | Naviguer entre les pistes (sélection multi-pistes préservée) |

### Limiteurs temporels (in/out points)

| Raccourci | Action |
|---|---|
| i | Poser le limiteur gauche (In) à la position courante du playhead |
| o | Poser le limiteur droit (Out) à la position courante du playhead |
| Shift+I | Limiteur gauche au début du pattern (step 0) |
| Shift+O | Limiteur droit à la fin du pattern (dernier step) |
| Début (Home) | Aller au limiteur gauche |
| Fin (End) | Aller au limiteur droit |
| Shift+Début | Aller au début de la boucle |
| Shift+Fin | Aller à la fin de la boucle |
| Ctrl+Début | Aller au début absolu du pattern (step 0) |
| Ctrl+Fin | Aller à la fin absolue du pattern (dernier step) |

### Presse-papier pistes

| Raccourci | Action |
|---|---|
| Ctrl+C | Copier les pistes sélectionnées (dans la plage limiteurs) |
| Ctrl+X | Erase : copie → presse-papier + efface grille (+ tape si limiteurs) |
| Ctrl+D | Delete : copie → presse-papier + efface grille et tape |
| Ctrl+V | Coller sur la piste courante (depuis la position courante) |
| Shift+V | Coller par fusion (grille max + tape union) |
| Ctrl+Suppr | Effacer grille et tape sans presse-papier |
| Suppr | Effacer pistes sélectionnées sans presse-papier |
| Shift+Suppr | Réinitialiser le pattern entier |

Le presse-papier est **cross-pattern** : on peut copier d'un pattern et coller dans un autre.

---

## UndoManager

Historique des annulations avec pile future (redo).

```
UndoManager
  ├── MAX_HISTORY     50
  ├── _history        deque[UndoEntry]
  └── _future         list[UndoEntry]
```

| Raccourci | Action |
|---|---|
| Ctrl+Z | Annuler (Undo) |
| Shift+Z | Refaire (Redo) |
| Ctrl+Shift+Z | Afficher l'historique des annulations (dialog) |

`_add_undo(title)` est appelé avant ~20 actions destructives (cocher/décocher cellule, modifier BPM, renommer, quantiser, dupliquer, coller, etc.). Depuis les Phase 7 étapes 13 et 15, les réglages de mixage et les boucles y passent aussi, et marquent le projet modifié :
- **mute et solo** des pistes et des pads : X, S, Shift+X et Shift+S, sur la liste des pistes, sur les pads et dans l'éditeur MIDI (une seule entrée pour toutes les pistes sélectionnées), et les boutons Mute et Solo des pads ;
- **volume et pan** des pistes et des pads : Alt+↑/↓, Alt+←/→, Alt+0, les CC7 et CC10 du contrôleur, les SpinCtrl Volume et Pan des pads ;
- **volume et pan globaux** : Ctrl+↑/↓, Ctrl+←/→, Ctrl+0, `+`/`-`, les champs « Vol: » et « Pan: » ;
- **points de boucle** : Ctrl+L, Shift+L, Alt+L, le dialogue Ctrl+Shift+L ; et la case **« Boucler » d'un song** ;
- les dialogues de propriétés de piste et de pad (entrée retirée si Annuler ou si rien n'a changé).

Rien n'est enregistré si la valeur ne change pas (volume déjà à 100, Alt+0 sur un pan centré, Shift+X sans rien de muet, Ok du dialogue de boucle sans changement).

`_add_mix_undo(title, key)` : les changements successifs d'un même volume ou pan (même `key`, moins de 1 s entre deux, sans autre action entre eux) ne forment qu'une entrée, dont le titre suit la valeur atteinte (`Volume piste 2: 80`, `Pan pad 5: -20`, `Volume global: 75`). Un tour de bouton rotatif s'annule ainsi d'un seul Ctrl+Z. Les bascules et les boucles font une entrée chacune (`Début de boucle: 2:2:1`, `Song 03: boucle On`).

`pop_last_undo()` : retire la dernière entrée — utilisé après annulation d'un dialog (Cancel ou valeur inchangée). L'état « modifié » d'avant est rétabli (Phase 7 étape 16d1).

**Point propre** (Phase 7 étape 16) : `UndoManager` numérote les états (`current_id`, `saved_id`, `state_id` de chaque entrée). Le projet est « modifié » (astérisque du titre, sauvegarde proposée à la fermeture) quand l'état courant n'est pas celui du fichier :
- revenir par Ctrl+Z à l'état sauvegardé efface l'astérisque, et la fermeture ne propose rien ;
- Ctrl+Z au-delà d'une sauvegarde, ou Shift+Z, remet l'astérisque ;
- une annulation (dialogue annulé, F2 inchangé, prise live sans effet) rétablit l'état d'avant.

L'historique appartient au projet : **Ctrl+O et Ctrl+N le vident** (Undo et Redo).

---

## ProjectManager — Fichier projet `.gvp`

Format `.gvp` (JSON renommé) : regroupe le rack, les 99 patterns et les 16 songs dans un seul fichier.

```json
{
  "version": 1,
  "rack":     { ... },
  "patterns": [ ... ],
  "songs":    [ ... ],
  "cur_song": 0,
  "master":   { "volume": 100, "pan": 0 }
}
```

| Raccourci | Action |
|---|---|
| Ctrl+N | Nouveau projet (demande confirmation si modifié ; vide l'historique d'Undo) |
| Ctrl+O | Ouvrir un projet (.gvp ou .json ; vide l'historique d'Undo) |
| Ctrl+S | Enregistrer le projet |
| Ctrl+Shift+S | Enregistrer sous… |
| Ctrl+Shift+W | Dupliquer le pattern courant vers un autre slot |

- Les projets sont créés dans le répertoire `data/PROJECTS/` (créé si absent)
- Le titre de la fenêtre principale affiche le nom du projet courant
- Le song courant (`cur_song`) est persisté dans le projet
- Le volume et le pan globaux (`master`) sont persistés dans le projet ; un ancien projet sans la clé prend les défauts de `data/config.json`

---

## Renommage (F2)

`F2` renomme l'élément courant selon le focus :
- Focus liste des pistes → renomme la piste
- Focus liste des patterns → renomme le pattern
- Depuis SongWindow → renomme le song courant
- Focus ailleurs → renomme le pattern courant

Un `_add_undo` est posé avant le dialog ; si l'utilisateur annule ou laisse le nom inchangé, `pop_last_undo()` retire l'entrée.

---

## Sérialisations — Fichiers JSON

### Projet (`.gvp` ou `preset_*.json`)

```json
{
  "version": 1,
  "rack": {
    "slots": [
      { "index": 0, "type": "kit",   "name": "TR-707",
        "config": { "kit": "/chemin/tr_707.json" } },
      { "index": 1, "type": "synth", "name": "Piano",
        "config": { "patch": "/chemin/Piano" } },
      { "index": 5, "type": "bank",  "name": "FluidR3_GM",
        "config": { "bank_slot": 0 } }
    ],
    "bank_files": ["/usr/share/sounds/sf2/FluidR3_GM.sf2", null, null, null]
  },
  "patterns": [
    {
      "name": "",
      "bpm": 100,
      "num_bars": 1,
      "num_steps": 16,
      "start_bar": 0,
      "looping": true,
      "loop_start": null,
      "loop_end": null,
      "loop_count": 0,
      "track_slots":   [0, 0, 0, 0, 0, 0, 0, 0],
      "track_mutes":   [false, "…"],
      "track_solos":   [false, "…"],
      "track_volumes": [100, "…"],
      "track_pans":    [0, "…"],
      "voices":        [{ "name": "", "volume": 100, "pan": 0, "mute": false,
                          "solo": false, "duration_ms": 500 }, "…"],
      "tape_v2":       [[[time, etype, dur_ms, channel, payload], "…"], "… (une liste par piste)"]
    },
    "…"
  ],
  "songs": [
    { "name": "", "sequence": [0, 2, 1], "looping": false },
    "…"
  ],
  "cur_song": 0,
  "master":   { "volume": 100, "pan": 0 }
}
```

- Le projet sauvegarde l'intégralité des 99 patterns + le rack complet + les 16 songs.
- `tape` remplace les anciens `kit_tape` / `patch_tape` / `curpattern` ; les trois etypes G/K/P sont sérialisés en une seule liste.

### Kit (`data/kits/tr_707.json`)

```json
{
  "name": "TR-707",
  "pads": [
    { "pad": 1, "note": 35, "filename": "/chemin/35_BassDrum2.wav", "label": "Kick 2", "mute_group": 0 },
    "…"
  ]
}
```

### Patch (`/PATCHS/Piano/patch.json`)

```json
{
  "name": "Piano",
  "loop": false,
  "loop_start": null,
  "loop_end": null,
  "samples": [
    { "file": "01_C1.wav", "root": "C1" },
    "…"
  ]
}
```

---

## Interface graphique

### Fenêtres

| Raccourci | Fenêtre | Description |
|---|---|---|
| (principale) | MainWindow | Grille séquenceur + listes + contrôles |
| Alt+4 | MidiEditorWindow | Éditeur MIDI événements (Phase 6) |
| Alt+5 | SongWindow | Composition de songs |

### Fenêtre principale — widgets

| Widget | Type | Description |
|---|---|---|
| Grille | CheckBox 16×16 | Séquenceur pas-à-pas |
| Liste Quantisation | ListBox | Valeurs de quant (1/1 à 1/128) |
| Liste Patterns | ListBox | 99 patterns (Pattern 01–99) |
| Liste Mode | ListBox | Mode Pad / Mode Keyboard |
| Liste Gammes | ListBox | Gammes disponibles |
| Liste Slots | ListBox | 16 slots du Rack |
| Liste Pistes | ListBox | 16 pistes du pattern courant |
| Liste Pads | ListBox | 16 pads de la piste courante |
| Liste Vel Level | ListBox | Niveaux de quantification vélocité MIDI |
| Liste MIDI Ports | ListBox | Ports MIDI in disponibles |
| Barre de statut | ListBox (1 item) | Messages d'état accessibles |

### Grille (séquenceur)

- 16 lignes (pads) × 16 colonnes (pas)
- Cases à cocher — accessibles au lecteur d'écran
- Navigation clavier : flèches, Entrée (cocher/décocher + jouer la ligne), Shift+Entrée (décocher + jouer)
- Autoplay : cocher/décocher une case rejoue automatiquement la ligne courante
- La valeur d'une case = vélocité (0 ou 1–127)

### Éditeur MIDI — MidiEditorWindow (Alt+4)

Fenêtre d'édition liste des événements MIDI du pattern courant.

**Modes d'affichage :**
- Ctrl+1 (MODE_NOTES, mode par défaut) : piste courante seulement, groupée par
  accord (format historique : `BBT  TrNN  Nom  Vel:NNN  [Dur:NNNms]`)
- Ctrl+2 (MODE_ALL) : tous les événements des pistes sélectionnées (grille +
  tape KIT/PATCH + CC/Program Change/Pitch Bend), en **liste plate, sans
  regroupement**, un événement par ligne :
  - Note : `index: position, Canal N, Note, numéro (nom), Durée NNNms, Vel NNN`
  - CC générique : `index: position, Canal N, CC, Numéro NN (nom), Valeur NNN`
  - Program Change : `index: position, Canal N, Program Change, Program NN (nom)`
  - Pitch Bend : `index: position, Canal N, Pitch Bend, Valeur +NNN`
    (même format que les autres types depuis la Phase 7 étape 6d1)
  - `index` = position 1-based de la ligne dans la liste affichée (pas un
    compteur d'accord) ; `Canal` = canal MIDI réel de l'événement
    (`TapeEvent.channel`, 0-15)

**Navigation :**
- Mode Notes (Ctrl+1) : ←/→ = groupe temporel (accord) précédent/suivant
  (joue la note) ; ↑/↓ = note précédente/suivante dans l'accord courant
- Mode Tous les événements (Ctrl+2) : ←/→ inactifs (pas de notion de groupe
  en liste plate) ; ↑/↓ = navigation **native** de la ListBox (`evt.Skip()`,
  pas de `SetSelection()` programmatique — nécessaire pour qu'Orca annonce
  la ligne, cf. section accessibilité ci-dessous) — événement précédent/
  suivant un par un, index affiché en tête de ligne mis à jour par la
  navigation elle-même ; `EVT_LISTBOX` (`_on_listbox_select`) synchronise le
  playhead et joue la note si l'événement en est une, silencieux sinon
  (CC/Bend)
- Home/End : premier/dernier événement (les deux modes)

**Sélection :**
- Ctrl+A : sélectionner tout / Ctrl+Shift+A : désélectionner
- Mode Notes (Ctrl+1) : Shift+←/→ = sélectionner/désélectionner le groupe (accord)
  + avancer ; Shift+↑/↓ = sélectionner une note individuelle dans l'accord
- Mode Tous les événements (Ctrl+2, liste plate) : Shift+↑/↓ = sélectionner/
  désélectionner l'événement précédent/suivant, un à la fois, **sans**
  regroupement par offset (`_select_move_up_flat`/`_select_move_down_flat` —
  la version groupée par accord ne convient pas à une liste plate). Shift+←/→
  non adapté pour ce mode (←/→ déjà neutralisés hors sélection, cf. Navigation
  ci-dessus) — pas de besoin identifié pour l'instant.
  **Ancrage** : si l'événement courant n'est pas encore sélectionné (première
  pression, ou après une navigation libre sans Shift), il est d'abord
  sélectionné sans déplacer le curseur, avant que les pressions suivantes
  n'étendent la sélection événement par événement — sinon le tout premier
  événement visité n'est jamais inclus dans la sélection (bug corrigé).
- Ctrl+Shift+F : EventFilterDialog — filtre = mécanisme de sélection (pas un affichage
  séparé) ; type (Notes/Pitch Bend/Mod Wheel/CC générique/Program Change ; Poly AT/
  Channel Pressure/SysEx toujours reportés), note/vélocité/pitch bend/numéro et valeur
  de CC/numéro de program/position ; Ok/Appliquer remplacent la sélection,
  Ajouter/Supprimer la modifient, Réinitialiser la vide, Effacer le filtre remet les
  critères à un état permissif. Dernier état mémorisé en session
  (`DrumPlayer._event_filter_state`, comme les derniers paramètres de quantisation :
  survit à l'undo/redo, pas écrit dans le .gvp)

**Édition :**
- Entrée sur une note : dialog pitch / position (Bar/Beat/Tick) / longueur / vélocité
  (`_MidiEventEditDialog`) — le listbox de note/pad reflète la même convention que
  la liste (`_dialog_note_choices`) : PATCH → note MIDI brute, KIT → nom de pad,
  GRID → résolu selon le slot (pitch réel si synthé, nom de pad sinon)
- Entrée sur un événement Pitch Bend, CC ou Program Change, en MODE_ALL
  (Ctrl+2) uniquement : dialog dédié position (Bar/Beat/Tick) + valeur
  (`_CcEventEditDialog`, bend -8192..8191, CC/program 0..127) —
  `edit_bend_event`/`edit_cc_event`/`edit_pgm_event` dans `MidiEditor`. Valeur
  seule modifiée → position exacte (fraction de pas) conservée ; position
  modifiée → posé sur le pas entier choisi
- Suppr : supprimer l'élément courant ou la sélection (Phase 7 étape 7b1)
  - sélection : tous les événements sélectionnés, quel que soit leur type
    (notes, CC, Program Change, Pitch Bend)
  - sans sélection, curseur sur une note : l'accord entier (les CC/PGM/bends
    du même pas sont conservés)
  - sans sélection, curseur sur un CC, un Program Change ou un Pitch Bend
    (Ctrl+2) : cet événement seul
- Limiteurs (i/o) : le limiteur droit inclut tout son pas, fraction comprise
  (un CC/bend à 5.4 est dans une plage qui finit au pas 5 — Phase 7 étape 6g2)
- Ctrl+C/X/V : presse-papier événements (cross-pistes)
- Ctrl+Z / Shift+Z : Undo/Redo
- Ctrl+Shift+Q : QuantizeDialog
- Ctrl+Q / Shift+Q : quantiser sans dialog

**Limiteurs :** i/o posent In/Out ; Shift+I/O pour début/fin du pattern.

**Transport partagé :** Espace, g, Shift+G, PageDown/Up, w, b, l, U, Ctrl+G, Ctrl+Shift+G, Ctrl+F12 identiques à la fenêtre principale.

Le mode d'affichage (piste seule / tout) est mémorisé entre les ouvertures (Alt+4 rouvre dans le dernier mode).

**Statut MIDI live :** `_midi_status_ctrl` (ListBox à un item, distincte de
`_status_ctrl` utilisée pour les annonces de navigation/sélection) affiche en
temps réel le dernier message MIDI reçu du clavier externe (Note On/Off, CC,
Pitch Bend), tant que la fenêtre est ouverte. `format_midi_status()`/
`CC_NAMES`/`MidiHandler._notify_editor_midi()` dans `ui/midi_handler.py`,
branché en tête de `on_note_on`/`on_note_off`/`on_cc`/`on_pitch_bend`. Chan
1-based ; `Num` affiche le nom standard MIDI 1.0 du contrôleur entre
parenthèses s'il est connu (`CC_NAMES`), sinon le numéro seul :
- Note On  : `Note: On, Chan: 10, Pitch: 48 (C4), Vel: 100`
- Note Off : `Note: Off, Chan: 1, Pitch: 60 (C4)` (pas de vélocité — non transmise par `MidiManager`)
- CC       : `CC, Chan: 1, Num: 64 (Sustain Pedal), Val: 126`
- Pitch Bend : `Pitch Bend, Chan: 1, Val: +500`

### Gestion du focus et Enter sur ListBox (GTK)

Sur Linux/GTK, la touche Entrée sur une `wx.ListBox` est interceptée par GTK et transformée en `EVT_LISTBOX_DCLICK` **avant** qu'elle n'atteigne `EVT_CHAR_HOOK`. Solution utilisée : handler `EVT_LISTBOX_DCLICK` avec `wx.GetKeyState(wx.WXK_RETURN)` pour distinguer Entrée d'un vrai double-clic.

### Astuces d'accessibilité (Orca / AT-SPI)

#### ListBox : mettre à jour un label sans casser AT-SPI

Utiliser `SetString(i, label)` plutôt que `Set([...])` pour mettre à jour les labels d'une `wx.ListBox` déjà construite.

- `Set([...])` détruit et recrée tous les objets ATK → Orca perd le contexte, aucune annonce.
- `SetString(i, label)` met à jour le texte **in-place** → AT-SPI émet `NAME_CHANGE` sur l'objet conservé → Orca annonce immédiatement le nouveau label de l'item sélectionné.

```python
# À éviter (casse AT-SPI) :
self._track_list.Set([self._label(i) for i in range(n)])
self._track_list.SetSelection(sel)

# À privilégier :
for i in range(self._track_list.GetCount()):
    self._track_list.SetString(i, self._label(i))
```

S'applique à toute `wx.ListBox` ou `wx.CheckListBox` dont le contenu est mis à jour dynamiquement (liste des pistes, liste des patterns, liste des songs, etc.).

#### SpinCtrl : seul widget annoncé en temps réel

`wx.SpinCtrl` est le seul widget wxPython/GTK annoncé par Orca lors de chaque changement de valeur, même par programme. À préférer pour tout paramètre numérique éditable (BPM, volume, pan…).

Un `SpinCtrl` isolé n'annonce que sa valeur, jamais le `wx.StaticText` voisin
— quand plusieurs `SpinCtrl` se suivent dans le même groupe (ex. Bar/Beat/Tick
dans `_MidiEventEditDialog`/`_CcEventEditDialog`), donner un nom accessible
distinct à chacun via `SetName("Bar")`/`SetName("Beat")`/`SetName("Tick")`.

#### EVT_CHAR_HOOK sur un dialog à boutons : Entrée casse l'activation native

Un `wx.Dialog` avec `EVT_CHAR_HOOK` bindé au niveau du dialog (ex. pour des
raccourcis lettres sur ses boutons — `SaveConfirmDialog`, Oui/Non/Annuler)
**empêche l'activation native du bouton focusé par Entrée**, même en
appelant `evt.Skip()` pour les touches non gérées explicitement : sur GTK,
`EVT_CHAR_HOOK` intercepte la touche avant que le bouton focusé (ou le
bouton par défaut via `SetDefault()`) ne la reçoive, et `Skip()` ne restaure
pas ce chemin natif de façon fiable.

**Fix :** gérer Entrée (`wx.WXK_RETURN`/`wx.WXK_NUMPAD_ENTER`) explicitement
dans le handler `EVT_CHAR_HOOK` — retrouver le bouton qui a le focus via
`wx.Window.FindFocus()` et terminer le dialog avec son ID, plutôt que de
compter sur le fallback natif :

```python
if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
    focus = wx.Window.FindFocus()
    for btn in (self._yes_btn, self._no_btn, self._cancel_btn):
        if focus is btn:
            self._end(btn.GetId())
            return
    self._end(wx.ID_YES)   # aucun bouton focus : action par défaut
    return
```

**Garde-fou complémentaire :** faire passer clic ET raccourcis clavier par
une méthode `_end(result_id)` unique avec un flag `self._answered` évite
qu'un double événement (quasi simultané, ou résiduel du bug ci-dessus)
n'écrase silencieusement le résultat déjà renvoyé par `ShowModal()`.

**Why:** Bug d'origine de `SaveConfirmDialog` (introduit étape 7l, jamais
couvert par des tests) signalé par l'utilisateur (Phase 6 étape 11) : Entrée
ne validait aucun bouton, seuls Y/N fonctionnaient au clavier mais sans
appliquer l'action attendue, et les raccourcis français (o/a) manquaient.

#### Barre de statut — `wx.ListBox` à un item + `SetString`

`wx.TextCtrl(style=wx.TE_READONLY)` ne convient **pas** pour une barre de statut accessible : `SetValue()` n'émet aucun événement AT-SPI, Orca n'annonce rien sans déplacer le focus.

**Solution retenue :** remplacer le `TextCtrl` par une `wx.ListBox` à un seul item, et mettre à jour via `SetString(0, msg)`.

- `SetString(0, msg)` émet `NAME_CHANGE` sur l'item ATK existant → Orca annonce le nouveau texte **immédiatement**, sans déplacement de focus.
- Les touches fléchées doivent être absorbées quand ce widget a le focus (GTK tenterait de naviguer dans la liste, mais il n'y a qu'un item ; le `key_manager` consomme l'événement sans propager).

```python
# Déclaration
self._status_ctrl = wx.ListBox(panel, choices=["…"], style=wx.LB_SINGLE)

# Mise à jour (dans _show_status)
self._status_ctrl.SetString(0, msg)

# Absorption des flèches dans key_manager (_handle_navigation)
if ctx.on_status_ctrl:
    return True
```

#### ListBox navigable au clavier : ne pas intercepter Haut/Bas, laisser GTK naviguer nativement

Piège différent du précédent : ici la ListBox a plusieurs items et DOIT rester
navigable par l'utilisateur (pas une barre de statut à un seul item). Si un
handler global (`EVT_CHAR_HOOK` sur la fenêtre) intercepte Haut/Bas pour cette
ListBox quand elle a le focus, et répercute le changement par un
`SetSelection(idx)` **programmatique** — même accompagné d'un `SetString(idx, label)`
pour forcer un `NAME_CHANGE` (cf. astuce précédente) — **Orca n'annonce rien**.
Ni `SetSelection()` seul, ni `SetSelection()` + `SetString()`, ne remplacent
une vraie navigation clavier native GTK pour l'accessibilité.

**Cause :** `SetSelection()` déplace la sélection au niveau wx/interne, mais
ne déclenche pas forcément les mêmes signaux GTK internes qu'une vraie
navigation clavier native dans le widget — Orca n'a donc pas toujours le
contexte nécessaire pour annoncer le changement de façon fiable.

**Solution retenue :** quand la ListBox concernée a le focus, ne pas consommer
Haut/Bas — `evt.Skip()` pour laisser GTK naviguer nativement. GTK déplace
alors la sélection ET déclenche `wx.EVT_LISTBOX` sur ce widget ; c'est CE
handler qui doit faire tout le travail (jouer un son, mettre à jour un état,
annoncer via la barre de statut) — pas le handler de touche global.

```python
# Dans le handler EVT_CHAR_HOOK de la fenêtre :
if key == wx.WXK_UP or key == wx.WXK_DOWN:
    if self._ma_listbox.HasFocus():
        evt.Skip()          # laisse GTK naviguer nativement + déclenche EVT_LISTBOX
    else:
        ...                 # comportement custom pour les autres widgets
    return

# Bind sur la ListBox elle-même — la vraie logique vit ICI :
self._ma_listbox.Bind(wx.EVT_LISTBOX, self._on_ma_listbox_select)

def _on_ma_listbox_select(self, event):
    idx = self._ma_listbox.GetSelection()
    ...                     # jouer le son / mettre à jour l'état / self._set_status(...)
```

**Quand un `SetSelection()` programmatique reste nécessaire malgré tout :**
uniquement pour un raccourci qui n'a **pas** de rapport avec une navigation
native dans CE widget (ex. un raccourci global type Alt+X, utilisable même
quand le widget n'a pas le focus). Dans ce cas précis, il n'y a pas d'autre
choix — accompagner alors le `SetSelection(idx)` d'un `SetString(idx, label)`
(même texte inchangé, juste pour forcer le `NAME_CHANGE`) **et** annoncer
explicitement le résultat soi-même via la barre de statut (`_set_status`) :
ne pas compter sur une annonce native de la ListBox dans ce cas-là.

**Repère utile :** dans ce projet, `mw_tracks.py`/`_track_list` a toujours
suivi cette règle (il ne consomme jamais Haut/Bas pour lui-même) — c'est en
comparant avec ce widget que le bug a été identifié.

S'applique à toute `wx.ListBox` navigable au clavier (pas les barres de statut
à un seul item, qui suivent l'astuce précédente).

**Autres applications dans ce projet :** clavier virtuel de `MidiEditorWindow`
(`_vk_lb`, étape 7f) ; `_event_lb` en mode Ctrl+2 « Tous les événements »
(étape 10c, liste plate — navigation strictement pas-à-pas, cas pur de
`evt.Skip()`). Le mode Ctrl+1 « Notes » (piano roll) du même `_event_lb`
reste dans le cas précédent (`SetSelection()` nécessaire) car Haut/Bas doit
rester **dans** l'accord courant (Gauche/Droite change de groupe) — un
comportement qui diffère volontairement du pas-à-pas natif.

---

## Boîtes de dialogue

| Classe | Module | Déclencheur | Description |
|---|---|---|---|
| `KeyboardHelpDialog` | dialogs_simple | F1 | Aide raccourcis clavier |
| `GenRowDialog` | dialogs_simple | Ctrl+Shift+E | Générer un motif sur la ligne + choisir la quant |
| `QuantizeDialog` | dialogs_temporal | Ctrl+Shift+Q | Quant + force, swing, fenêtre, direction, débuts/durées |
| `GridDialog` | dialogs_properties | Ctrl+Shift+G | Résolution de grille (4 mes. à 1/128) |
| `GotoDialog` | dialogs_temporal | Ctrl+G | Aller à une position (bar:beat:tick) |
| `LoopSelectDialog` | dialogs_temporal | Ctrl+Shift+L | Points de boucle (début, fin, répétitions) |
| `EventFilterDialog` | dialogs_temporal | Ctrl+Shift+F | Filtre/sélection d'événements MIDI par type, note, vélocité, pitch bend, position |
| `SavePatternDialog` | dialogs_simple | (interne) | Sauvegarder le pattern sous un nouveau nom |
| `RenameDialog` | dialogs_simple | F2 | Renommer piste, pattern ou song |
| `TrackPropertiesDialog` | dialogs_properties | Alt+Entrée (ou Ctrl+Maj+T) sur piste | Propriétés de la piste (slot, canal, programme, transposition et gain GM du slot, volume, pan, mute, solo ; sur une banque : programme du canal, banque MSB / LSB, en direct) |
| `TrackSelectDialog` | dialogs_properties | Ctrl+Entrée (liste pistes) | Sélection de pistes + plage BBT |
| `PatternPropertiesDialog` | dialogs_properties | Alt+Entrée sur pattern | Propriétés du pattern (nom, BPM, mesures, pas) |
| `PadPropertiesDialog` | dialogs_properties | Alt+Entrée sur grille | Propriétés du pad (volume, pan, mute, solo, durée, mute_group) |
| `UndoHistoryDialog` | dialogs_simple | Ctrl+Shift+Z | Historique des annulations |
| `ExplorerDialog` | dialogs | Alt+X | Sélection du type de ressource à charger |
| `BankSlotDialog` | dialogs_bank | Alt+X → Banque | Emplacement (1 à 4) et fichier SF2/SF3 du slot courant |

### ExplorerDialog (Alt+X)

ListBox avec 6 items :
- **Projects** : ouvre un projet `.gvp` dans `projects_dir`
- **Preset** : ouvre un FileDialog dans `presets_dir`, charge le fichier `.json` sélectionné
- **Kit** : ouvre un FileDialog dans `kits_dir`, affecte le kit au slot courant
- **Patch** : ouvre un FileDialog dans `patches_dir`, affecte le patch au slot courant (SYNTH)
- **Sound** : ouvre un FileDialog dans `samples_dir`, remplace le WAV du pad courant
- **Banque** : `BankSlotDialog` — le slot courant devient un slot Banque
  (emplacement, fichier ; nom du slot = nom du fichier ; Undo)

Le double-clic sur un item valide directement la sélection (`EVT_LISTBOX_DCLICK → EndModal(ID_OK)`).

---

## Chargement des ressources

### Projet
1. `rack.from_dict(data["rack"])` — restaure les 16 slots
2. `_pattern_list[i].from_dict(p)` pour chaque pattern
3. `_song_list[i].from_dict(s)` pour chaque song
4. Pour chaque slot KIT distinct utilisé par les pistes : `_load_kit_slot(slot_idx)`
5. Pour le slot de la piste courante si SYNTH : `_router.load_slot_preview(cur_slot)`
6. `_router.clear_slot_synths()` — invalide le cache des moteurs SYNTH

### Kit
- `sound_manager.load_kit(json_path)` → met à jour `drum_sounds[16]` et `note_map`
- Labels des pads mis à jour dans `voice_manager`
- `mute_groups` synchronisés entre `SoundManager` et `VoiceManager`

### Patch
- `_router.reload_slot(slot_idx)` → invalide l'ancien moteur, crée un `SynthEngine`, pré-calcule
- Toutes les pistes utilisant ce slot bénéficient du nouveau moteur

### Sound (sample individuel)
- `sound_manager.load_pad_sound(pad_idx, wav_path)` → remplace `drum_sounds[pad_idx]`
- `voice_manager.set_name(pad_idx, nom)` + mise à jour de `_media_lst`

---

## Gestion MIDI

### MidiManager
- Détection et connexion des ports MIDI in via `rtmidi`
- Callback `on_note_on(note, velocity, channel)` / `on_note_off(note, channel)`
- Thread de lecture MIDI indépendant

### MidiHandler (logique extraite de MainWindow)
- `on_note_on` / `on_note_off` : dispatch selon le mode (Pad, Keyboard)
- Mode Pad : mapping note MIDI → pad via `note_map` du SoundManager
- Mode Keyboard : jeu sur les notes de la gamme (`kb_notes`)
- Note Repeat MIDI : répétition au taux sélectionné
- Erase MIDI : effacement par plage de notes tenues
- Vel Level : quantification de la vélocité entrante
- CC : dispatch vers les handlers volume, pan, sustain, all-off, mod wheel, pitch bend

### _tape (capture MIDI unifiée)
- `_tape[track] = [TapeEvent, …]` (liste plate par piste)
- `TapeEvent(etype, dur, channel, payload, time)` — etype GRID/KIT/PATCH/CC/PGM/BEND
- Protégé par `threading.RLock` pour accès thread-safe (lecture MIDI + thread player)

---

## Raccourcis clavier

Liste complète dans `docs/shortcuts.md`.

Catégories principales :
- Projet (Ctrl+N/O/S/Shift+S)
- Pattern (Ctrl+W/D/P/F/Shift+P/F, Ctrl+Shift+W)
- Quantisation (Ctrl+E/Q, Shift+E/Q, Ctrl+Shift+Q, Ctrl+Shift+G)
- Lecture (Espace, P, V, Ctrl+Space, g, Shift+G, l, U)
- Transport (PageUp/Down, Ctrl+PageUp/Down, Shift+PageUp/Down, w, b, Ctrl+G)
- Mute/Solo pads et pistes (X, S, Shift+X/S)
- Volume/Pan pad (Alt+flèches)
- Enregistrement (R, Shift+R, Ctrl+R)
- Erase (E)
- Note Repeat (Q, touches 1–9)
- BPM/Volume/Pan global
- Tap Tempo (H)
- Navigation grille (flèches, Entrée)
- NumPad (1–9, Entrée, 0, +, -)
- Mode Keyboard (Ctrl+1/2, NumPad+/-/×/÷)
- Sélection multi-pistes (Ctrl+A, Shift+Espace, Shift+↑/↓)
- Limiteurs temporels (i, o, Shift+I/O)
- Navigation limiteurs (Home/End, Shift+Home/End, Ctrl+Home/End)
- Loop points (Ctrl+L, Shift+L, Ctrl+Shift+L, Alt+L)
- Presse-papier pistes (Ctrl+C/X/D/V, Shift+V, Ctrl+Suppr, Suppr)
- Patterns (Alt+Entrée, double-clic)
- Slots (double-clic)
- Pistes (Ctrl+T, Ctrl+Entrée, Entrée, F2)
- MIDI (Alt+M, Alt+Shift+M)
- Undo/Redo (Ctrl+Z, Shift+Z, Ctrl+Shift+Z)
- Éditeur MIDI (Alt+4, ←/→/↑/↓, Ctrl+A, Shift+←/→/↑/↓, Numpad édition, D/Shift+D, Ctrl+I/Alt+I/Ctrl+Shift+I, A, Ctrl+G/Ctrl+Shift+G)
- Songs (Alt+5, Entrée, Ctrl+Entrée, Suppr, Alt+↑/↓)
- Aide (F1)
- Renommer (F2)
- Panic (Ctrl+F12)

---

## Tests unitaires

Tous les tests sont dans `tests/`. Exécution globale : `bash tests/test_all.sh`

Cette table et l'arborescence plus haut doivent lister chaque `tests/test_*.py` : à vérifier avec `python3 tools/check_specs_tests.py` avant de committer un nouveau fichier de tests, et à chaque clôture de chantier.

| Fichier | Couvre |
|---|---|
| `test_app_config.py` | Clés de config.json du slot Banque : soundfonts_dir, gm_soundfont, midi_bank_select, fluidsynth_gain |
| `test_app_launch.py` | Démarrage de l'application |
| `test_audio_sampler.py` | AudioSampler : boucle, crossfade, ADSR, pitch shift |
| `test_bank_dialogs.py` | Slot Banque, dialogues : entête de piste, propriétés de piste en direct (liste du canal, MSB / LSB, le canal impose son instrument, piste temporaire, autres pistes du canal, note d'aperçu, Annuler, Undo, aller-retour de canal), dialogue Banque de l'Explorateur |
| `test_bank_slot.py` | Slot Banque, modèle « orchestre » : Rack et .gvp (slot = emplacement), instrument par canal, Program Change et Bank Select (canal de l'événement, la piste suit), poursuite, le canal impose son instrument, canal 10 = batterie, rejeu, jeu direct, poursuite par le player, export (Bank Select avant le programme, canal courant) ; pédale au canal de la piste, Zero Controllers à l'arrêt, poursuite de la pédale, du Pitch Bend et de la modulation, rappel de fin de lecture |
| `test_bend_log.py` | bend_log partagé : drapeau, format des lignes, chemin par défaut |
| `test_cc_event_edit_dialog.py` | _CcEventEditDialog : bend/mod/CC générique/Program Change, champ Canal + dispatch d'édition, piste Banque suivie (19 tests) |
| `test_check_specs_tests.py` | tools/check_specs_tests.py sur un faux dépôt : absents, disparus, ligne proposée, code de sortie |
| `test_event_filter_dialog.py` | EventFilterDialog : critères, types (dont CC/Program Change) et "à venir", Tab order, on_action (51 tests) |
| `test_explorer_actions.py` | Actions explorer : Preset, Kit, Patch, Sound (OK + annulation) |
| `test_explorer_dialog.py` | ExplorerDialog : ITEMS, sélection, double-clic |
| `test_fluidsynth_engine.py` | Moteur de banque : BankEngine (GS/MMA), FluidSynthEngine sur FluidR3_GM (TimGM6mb en repli : emplacements, presets, canaux, rendu), branchement MainWindow ; sautés sans libfluidsynth |
| `test_gm_program.py` | Program Change par slot : guess_gm_program, gm_program, export au tick 0, propriétés de piste (aperçu, Annuler, Undo, transposition et gain GM) |
| `test_gm_slot_export.py` | Transposition et gain GM d'un slot : accesseurs, sérialisation du Rack, effet à l'export |
| `test_key_manager.py` | Raccourcis clavier, transport, ProjectManager |
| `test_kit_channel_migration.py` | Migration des canaux : pistes kit sur le canal 10 à l'ouverture d'un ancien projet |
| `test_live_take.py` | Prise d'enregistrement live : Undo avant la prise, retiré si _tape n'a pas changé |
| `test_load_project_cache.py` | Non-régression : Ctrl+O invalide le cache des patterns sérialisés de l'Undo |
| `test_loop_points_pattern.py` | Loop points : données Pattern (29 tests) |
| `test_loop_points_player.py` | Loop points : DrumPlayer (21 tests) |
| `test_loop_select_dialog.py` | LoopSelectDialog (42 tests) |
| `test_loop_undo.py` | Undo des points de boucle (Ctrl+L, Shift+L, Alt+L, dialogue) et de la case Boucler du song |
| `test_master_mix.py` | Volume et pan globaux : défauts de config.json, clé « master » du .gvp, Nouveau projet, Undo, raccourcis et champs |
| `test_midi_constants.py` | midi_constants : tables CC/GM/GM2, noms des percussions GM, note GM devinée, courbe gm_gain |
| `test_midi_editor.py` | MidiEditor : get_note_events, get_cc_pgm_events, sélection, édition |
| `test_midi_editor_filter.py` | MidiEditor.filter_events : type/note/vélocité/bend/CC/program/position (30 tests) |
| `test_midi_editor_window.py` | MidiEditorWindow : solo/mute des pistes (avec Undo), statut MIDI live |
| `test_midi_export.py` | Export MIDI : fichier relu par mido, pistes, canaux, notes GRID/KIT/PATCH, CC/PGM/BEND, conversion GM, mute/solo, fin pile |
| `test_midi_export_mix.py` | Export MIDI : volume et pan de piste (CC7/CC10), notes PATCH sans synthé omises, CC91/CC93 à 0 |
| `test_midi_export_ui.py` | Interface de l'export MIDI : exports_dir, paramètres, nom de fichier, FileDialog, Alt+Shift+E |
| `test_midi_import.py` | Import MIDI : nom, tempo, signature, longueur, pas et arrondi des notes, durées, pistes par canal, type 0, fusion, entête, volume / pan, CC / Bend, ignorés, compte rendu, aller-retour, fichier abîmé |
| `test_midi_import_ui.py` | Interface de l'import MIDI : slot Banque trouvé ou créé, dossier du dialogue, annulation, erreur de lecture, confirmation, remplacement du pattern, noms de pistes, Undo, compte rendu, Alt+Shift+I |
| `test_midi_handler_window.py` | Statut MIDI live de l'éditeur : format_midi_status, _notify_editor_midi |
| `test_midi_manager.py` | MidiManager : connexion, déconnexion, ports |
| `test_midi_parser.py` | midi_parser en isolation : decode_message, describe_note/cc/program |
| `test_midi_virtual_keyboard.py` | VirtualKeyboardMixin : clavier virtuel de l'éditeur MIDI |
| `test_mix_undo.py` | Undo du mute, du solo et du volume : regroupement < 1 s, chaque chemin, dialogue du pad (40 tests) |
| `test_multitrack.py` | Dispatch audio multi-piste (mute, solo, volume, pan) |
| `test_mute_groups.py` | Groupes mute exclusif (AudioSampler + SoundManager) |
| `test_pad_properties_dialog.py` | PadPropertiesDialog : valeurs initiales, callbacks, durée |
| `test_pattern.py` | Pattern : création, reset, resize, double/halve, random |
| `test_pattern_grid_api.py` | API grille de Pattern (get_cell, set_cell, iter_grid, copy_from…) au-dessus de _tape ; grid_row en un passage |
| `test_pattern_properties_bug.py` | Non-régression : Doubler/Diviser/Redimensionner gardent grille et _tape synchronisées |
| `test_pattern_properties_dialog.py` | PatternPropertiesDialog : BPM, mesures, pas |
| `test_pattern_serialization.py` | to_dict / from_dict (round-trip) |
| `test_playback_loop.py` | Boucle de lecture : _build_measure_events (ordre de _tape à temps égal), _dispatch_event, _on_measure_end (rappel de fin de lecture) |
| `test_pygame_driver.py` | PygameDriver : play, stop, volume, pan |
| `test_quantize.py` | Quantisation : apply_quant_row, apply_quant_to_pattern, force/swing/fenêtre/direction |
| `test_rename.py` | Renommage F2 : piste, pattern, song (18 tests) |
| `test_save_confirm_dialog.py` | SaveConfirmDialog : Entrée sur le bouton focus, raccourcis O/Y/N/A/C, garde-fou EndModal |
| `test_sixteen_tracks.py` | 16 pistes par pattern : défauts, migration des presets à 8 pistes, sérialisation |
| `test_song.py` | Song : création, séquence, label |
| `test_song_serialization.py` | to_dict / from_dict Song (16 tests) |
| `test_sound_cache.py` | sound_cache : init, load, save_async, hash (21 tests) |
| `test_sound_device_driver.py` | SoundDeviceDriver : play, mix, polyphonie |
| `test_sound_manager.py` | SoundManager : load_kit, mute_groups, play_note |
| `test_step_duration.py` | Durée du pas indépendante de la résolution : set_bpm, load_pattern, song, métronome, Note Repeat |
| `test_synth_engine.py` | SynthEngine : chargement patch, pré-calcul, lecture |
| `test_synth_utils.py` | Utilitaires : scale_midi_notes, midi_to_note_name |
| `test_tap_tempo.py` | Tap Tempo : BPM, TAP_MIN_TAPS, timeout (20 tests) |
| `test_tape.py` | _tape (TapeEvent G/K/P) : enregistrement, sérialisation |
| `test_track_channels.py` | Canal MIDI par piste : défauts, migration, règle du kit, Ctrl+T et propriétés de piste (Undo) |
| `test_track_editor.py` | TrackEditor : sélection multi-pistes, limiteurs, clipboard |
| `test_track_properties_dialog.py` | TrackPropertiesDialog : slot, volume, pan |
| `test_track_router.py` | TrackRouter : routing, mute/solo, SynthEngine cache |
| `test_track_select_dialog.py` | TrackSelectDialog : checkboxes, plage BBT (33 tests) |
| `test_transport.py` | Transport : navigate_bar, move_by_*, GotoDialog |
| `test_undo_clean_point.py` | Point propre de l'Undo : Ctrl+Z jusqu'à l'état sauvegardé, annulations, prise live, historique vidé par Ctrl+O/Ctrl+N |
| `test_undo_manager.py` | UndoManager : add, undo, redo, pop_last |
| `test_voice_manager.py` | VoiceManager : volume, pan, mute, solo, durée, mute_group |

---

## Outils

### `tools/check_specs_tests.py`

Vérifie que `docs/SPECS.md` liste tous les fichiers `tests/test_*.py`, dans l'arborescence du projet et dans la table « Tests unitaires » (Phase 7 étape 14c1).

```
Usage:
  python3 tools/check_specs_tests.py
  python3 tools/check_specs_tests.py --root /autre/dépôt
```

- Signale les fichiers absents de l'arborescence, ceux absents de la table, et ceux cités mais qui n'existent plus
- Pour un fichier absent de la table, propose une ligne prête à coller, tirée de la première phrase de son docstring
- Code de sortie : 0 si tout est à jour, 1 sinon

### `tools/extract_gm_drums.py`

Extrait les 47 sons de batterie GM (notes 35–81) depuis un soundfont SF2 via FluidSynth, et génère le fichier kit JSON correspondant.

```
Usage:
  python3 tools/extract_gm_drums.py
  python3 tools/extract_gm_drums.py --sf2 /chemin/soundfont.sf2
  python3 tools/extract_gm_drums.py --out /répertoire/sortie
  python3 tools/extract_gm_drums.py --duration 3000
```

- SF2 par défaut : `/usr/share/sounds/sf2/FluidR3_GM.sf2`
- Génère : un WAV par note + un fichier `kit_gm.json`

### `tools/extract_instruments_sf2.py`

Exporteur général d'instruments depuis un soundfont SF2 : patches mélodiques ou batteries. Génère WAV + JSON.

### `tools/extract_organ_sf2.py`

Extraction des samples d'orgue depuis un soundfont SF2 (B3, Farfisa…). Génère le dossier patch avec `patch.json`.

### `tools/find_loop_points.py`

Détecte les points de bouclage d'un patch et met à jour `patch.json`.

```
Usage:
  python3 tools/find_loop_points.py synths/Organ_B3
  python3 tools/find_loop_points.py synths/Organ_B3 --dry-run
  python3 tools/find_loop_points.py synths/Organ_B3 --tail 0.20 --min-corr 0.95
  python3 tools/find_loop_points.py synths/Organ_B3 --json-only
```

- Analyse chaque sample via `AudioTools.find_loop_points()`
- Met à jour `loop_start` / `loop_end` dans `patch.json` par sample
- Si au moins un point trouvé, passe `"loop": true`
- `--json-only` : met à jour uniquement la clé `"loop"` sans toucher aux offsets

### `tools/bench_latency.py`

Comparaison de la latence entre PygameDriver et SoundDeviceDriver.

### `tools/diag_loop.py`

Outil de diagnostic des points de bouclage : affiche les paramètres, aligne les périodes pour les notes root.

---

## Points ouverts / Phase suivante

- **Éditeur MIDI (Phase 6)** : en cours — MidiEditorWindow opérationnel, QuantizeDialog avancée opérationnelle ; intégration cross-fenêtres et sauvegarde projets en cours de finalisation
- **Format JSON `.gvp` — unification `tape`** : `to_dict()`/`from_dict()` sérialisent encore séparément `curpattern`/`kit_tape`/`patch_tape` (rétrocompatibilité des presets existants) ; le format cible documenté plus haut (une seule liste `tape` avec `etype`) reste à implémenter dans une session dédiée
- **AudioSampler — UI groupes mute exclusif** : logique FAITE, PadPropertiesDialog à compléter
- **Slots LOOP / AUDIO / MIDI_FILE / MIDI_PORT** : types définis, non implémentés
- **Mode Chord** : voicings d'accords sur la gamme courante
- **Explorateur graphique avancé** : navigation arborescente par type, preview sonore
- **Interface édition points de bouclage** : visualisation forme d'onde, édition manuelle loop_start/loop_end
- **MIDI Clock** : synchronisation entrante/sortante
- **Multi-fenêtres supplémentaires** : Piano Roll graphique (Alt+3)
