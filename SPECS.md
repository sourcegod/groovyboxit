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

---

## Stack technique

| Rôle | Bibliothèque |
|---|---|
| GUI | `wxPython` |
| Audio (one-shot, kit) | `pygame.mixer` (PygameDriver) |
| Audio polyphonique | `sounddevice` + `numpy` (SoundDeviceDriver — driver par défaut) |
| Pitch shifting | `pyrubberband` (bindings Python de Rubber Band C++) |
| Lecture WAV | `soundfile` |
| Traitement audio | `numpy` |
| MIDI in/out | `rtmidi` (via `python-rtmidi`) |
| Effets (futur) | `pedalboard` (Spotify) |

---

## Structure du projet

```
groovyboxit/
├── main.py               # Point d'entrée
├── src/
│   ├── app_config.py     # Chargement data/config.json, chemins configurables
│   ├── audio_sampler.py  # AudioSampler : boucle, crossfade, ADSR, pitch shifting
│   ├── audio_tools.py    # Détection de points de bouclage (AudioTools)
│   ├── drum_player.py    # Séquenceur : lecture, enregistrement, note repeat
│   ├── loop_manager.py   # LoopManager + LoopWindow : fenêtre de boucle pattern
│   ├── main.py           # Point d'entrée secondaire (importé par main.py racine)
│   ├── metronome.py      # Classe Metronome isolée
│   ├── midi_editor.py    # MidiEditor : logique événements MIDI (lecture, édition)
│   ├── midi_manager.py   # Connexion ports MIDI in/out
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
│   └── ui/
│       ├── dialogs.py          # Boîtes de dialogue (explorateur)
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
│       ├── midi_handler.py     # Logique MIDI (séparée de MainWindow)
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
    ├── test_app_launch.py
    ├── test_audio_sampler.py
    ├── test_explorer_actions.py
    ├── test_explorer_dialog.py
    ├── test_key_manager.py
    ├── test_loop_points_pattern.py
    ├── test_loop_points_player.py
    ├── test_loop_select_dialog.py
    ├── test_midi_editor.py
    ├── test_midi_manager.py
    ├── test_multitrack.py
    ├── test_mute_groups.py
    ├── test_pad_properties_dialog.py
    ├── test_pattern.py
    ├── test_pattern_properties_dialog.py
    ├── test_pattern_serialization.py
    ├── test_pygame_driver.py
    ├── test_quantize.py
    ├── test_rename.py
    ├── test_song.py
    ├── test_song_serialization.py
    ├── test_sound_cache.py
    ├── test_sound_device_driver.py
    ├── test_sound_manager.py
    ├── test_synth_engine.py
    ├── test_synth_utils.py
    ├── test_tap_tempo.py
    ├── test_tape.py
    ├── test_track_editor.py
    ├── test_track_properties_dialog.py
    ├── test_track_router.py
    ├── test_track_select_dialog.py
    ├── test_transport.py
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
  "sound_cache_dir": "/chemin/cache_npz"
}
```

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

*Implémentés et opérationnels : KIT et SYNTH.*

### Structure d'un slot

```
Slot
  ├── index   : int (0–15)
  ├── type    : InstrumentType.* (ou None si vide)
  ├── name    : str  (ex. "TR-707", "Piano")
  └── config  : dict
        KIT   → { "kit": "/chemin/vers/kit.json" }
        SYNTH → { "patch": "/chemin/vers/dossier_patch" }
```

### Sérialisation Rack

`Rack.to_dict()` / `Rack.from_dict(data)` — inclus dans le preset JSON sous la clé `"rack"`.

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
    { "pad": 16, "filename": "", "label": "---" }
  ]
}
```

- `note` : note MIDI GM (35–81), utilisée pour le mapping MIDI et le pitch
- `filename` : chemin absolu ou relatif au JSON
- `label` : nom affiché dans la liste des pads
- `mute_group` : groupe de mute exclusif (0 = aucun, ≥1 = groupe partagé). Au sein d'un même groupe, jouer un son coupe les voix actives du même groupe (comportement hihat open/closed TR-style)

### SoundManager — API Kit

| Méthode | Description |
|---|---|
| `load_kit(json_path)` | Charge le kit, construit `drum_sounds[16]` et `note_map` |
| `load_pad_sound(pad_idx, wav_path)` | Remplace un son individuel dans `drum_sounds` |
| `load_sounds()` | Charge les sons par défaut depuis `media/` |
| `play_sound(index, vol, pan)` | Joue `drum_sounds[index]` |
| `play_note(midi_note, vol, pan)` | Joue via `note_map[midi_note]` |
| `shift_kit(delta)` | Décale `kit_offset` de ±8 (plage : 0 — max notes du kit) |
| `set_pad_mute_group(pad_idx, group)` | Définit le mute_group d'un pad (synchronisé avec VoiceManager) |

- `drum_sounds` : liste de 16 `pygame.Sound`, reconstruite à partir de `note_map` + `kit_base` + `kit_offset`
- `note_map` : `{midi_note: pygame.Sound}` — tous les sons du kit avec champ `"note"`
- `mute_groups` : liste de 16 entiers (0 = aucun groupe)

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
  ├── _track_slots[8]     slot assigné à chaque piste (défaut : slot 0)
  ├── _slot_synths        {slot_idx: SynthEngine} — un moteur par slot SYNTH commis
  ├── _synth              moteur de preview interactive (slot courant)
  ├── _kit_synth          moteur dédié au mode Keyboard/KIT pitché
  ├── kb_notes[25]        notes MIDI de gamme pour le clavier MIDI
  └── kb_notes_input[16]  notes MIDI de gamme pour le Numpad (transposables)
```

`on_play(track, pad, vol, pan, dur)` :
- Slot KIT → `sound_manager.play_sound(pad_idx)`
- Slot SYNTH → `_slot_synths[slot_idx].play(kb_notes[pad_idx])`

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
  ├── _track_slots   [int × 8]   slot assigné à chaque piste
  ├── _track_mutes   [bool × 8]
  ├── _track_solos   [bool × 8]
  ├── _track_volumes [int × 8]   0..100
  ├── _track_pans    [int × 8]   -100..+100
  ├── _voices        [dict × 16] volume, pan, mute, solo, durée par pad
  └── _tape          {(track, bar, step): [TapeEvent]}  capture unifiée
```

- 99 patterns disponibles (Pattern 01–99)
- 8 pistes par pattern
- 16 pads par piste
- Pas : vélocité 0 (inactif) ou 1–127 (actif avec vélocité)

### TapeEvent — capture MIDI unifiée

```python
TapeEvent = namedtuple("TapeEvent", ["etype", "note", "vel", "dur", "bend"])
```

| `etype` | Source | Description |
|---|---|---|
| `"G"` | Grille | Pas issu de `_curpattern` (grille 16×16), note = numéro de pad |
| `"K"` | Kit MIDI | Note MIDI brute (indépendante du kit_offset), bend = 0 |
| `"P"` | Patch SYNTH | Note MIDI absolue + durée réelle + pitch bend en cents |

Toutes les sources sont stockées dans `_tape = {(track, bar, step): [TapeEvent, …]}`. La grille (`etype="G"`) remplace l'ancien `_curpattern` comme structure canonique.

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

### Pitch Bend temps réel

- `phase_incr` flottant dans le driver audio pour un pitch bend sans artefact
- Automation : enregistrement de la trajectoire complète pendant Rec, relecture exacte

### Mod Wheel CC#1 — LFO vibrato

- Profondeur maximale configurable : ±2 demi-tons
- Automation : enregistrement dans `_mod_tape`, relecture synchronisée

---

## Volume et Pan

### Global
- Volume global : 0..100 (Ctrl+↑/↓)
- Pan global : -100..+100 (Ctrl+←/→, Ctrl+0 pour centrer)

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

`_add_undo(title)` est appelé avant ~20 actions destructives (cocher/décocher cellule, modifier BPM, mute/solo, renommer, quantiser, dupliquer, coller, etc.).

`pop_last_undo()` : retire la dernière entrée — utilisé après annulation d'un dialog (Cancel ou valeur inchangée).

---

## ProjectManager — Fichier projet `.gvp`

Format `.gvp` (JSON renommé) : regroupe le rack, les 99 patterns et les 16 songs dans un seul fichier.

```json
{
  "version": 1,
  "rack":     { ... },
  "patterns": [ ... ],
  "songs":    [ ... ],
  "cur_song": 0
}
```

| Raccourci | Action |
|---|---|
| Ctrl+N | Nouveau projet (demande confirmation si modifié) |
| Ctrl+O | Ouvrir un projet (.gvp ou .json) |
| Ctrl+S | Enregistrer le projet |
| Ctrl+Shift+S | Enregistrer sous… |
| Ctrl+Shift+W | Dupliquer le pattern courant vers un autre slot |

- Les projets sont créés dans le répertoire `data/PROJECTS/` (créé si absent)
- Le titre de la fenêtre principale affiche le nom du projet courant
- Le song courant (`cur_song`) est persisté dans le projet

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
        "config": { "patch": "/chemin/Piano" } }
    ]
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
      "tape":          [[track, bar, step, etype, note, vel, dur_ms, bend], "…"]
    },
    "…"
  ],
  "songs": [
    { "name": "", "sequence": [0, 2, 1], "looping": false },
    "…"
  ],
  "cur_song": 0
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
| Liste Pistes | ListBox | 8 pistes du pattern courant |
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
- Ctrl+1 : piste courante seulement
- Ctrl+2 : tous les événements du pattern

**Navigation :**
- ←/→ : événement ou groupe temporel précédent/suivant (joue la note)
- ↑/↓ : naviguer dans un accord (notes simultanées)
- Home/End : premier/dernier événement

**Sélection :**
- Ctrl+A : sélectionner tout / Ctrl+Shift+A : désélectionner
- Shift+←/→ : sélectionner/désélectionner le groupe + avancer
- Shift+↑/↓ : sélectionner une note individuelle dans un accord

**Édition :**
- Entrée : éditer la note sélectionnée (dialog pitch / position / longueur / vélocité)
- Suppr : supprimer l'événement
- Ctrl+C/X/V : presse-papier événements (cross-pistes)
- Ctrl+Z / Shift+Z : Undo/Redo
- Ctrl+Shift+Q : QuantizeDialog
- Ctrl+Q / Shift+Q : quantiser sans dialog

**Limiteurs :** i/o posent In/Out ; Shift+I/O pour début/fin du pattern.

**Transport partagé :** Espace, g, Shift+G, PageDown/Up, w, b, l, U, Ctrl+G, Ctrl+Shift+G, Ctrl+F12 identiques à la fenêtre principale.

Le mode d'affichage (piste seule / tout) est mémorisé entre les ouvertures (Alt+4 rouvre dans le dernier mode).

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
| `SavePatternDialog` | dialogs_simple | (interne) | Sauvegarder le pattern sous un nouveau nom |
| `RenameDialog` | dialogs_simple | F2 | Renommer piste, pattern ou song |
| `TrackPropertiesDialog` | dialogs_properties | Ctrl+T / Entrée sur piste | Propriétés de la piste (slot, volume, pan, mute, solo) |
| `TrackSelectDialog` | dialogs_properties | Ctrl+Entrée (liste pistes) | Sélection de pistes + plage BBT |
| `PatternPropertiesDialog` | dialogs_properties | Alt+Entrée sur pattern | Propriétés du pattern (nom, BPM, mesures, pas) |
| `PadPropertiesDialog` | dialogs_properties | Alt+Entrée sur grille | Propriétés du pad (volume, pan, mute, solo, durée, mute_group) |
| `UndoHistoryDialog` | dialogs_simple | Ctrl+Shift+Z | Historique des annulations |
| `ExplorerDialog` | dialogs | Alt+X | Sélection du type de ressource à charger |

### ExplorerDialog (Alt+X)

ListBox avec 4 items :
- **Preset** : ouvre un FileDialog dans `presets_dir`, charge le fichier `.json` sélectionné
- **Kit** : ouvre un FileDialog dans `kits_dir`, affecte le kit au slot courant
- **Patch** : ouvre un FileDialog dans `patches_dir`, affecte le patch au slot courant (SYNTH)
- **Sound** : ouvre un FileDialog dans `samples_dir`, remplace le WAV du pad courant

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
- `_tape = {(track, bar, step): [TapeEvent, …]}`
- `TapeEvent(etype, note, vel, dur, bend)` — etype G/K/P
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

| Fichier | Couvre |
|---|---|
| `test_app_launch.py` | Démarrage de l'application |
| `test_audio_sampler.py` | AudioSampler : boucle, crossfade, ADSR, pitch shift |
| `test_explorer_actions.py` | Actions explorer : Preset, Kit, Patch, Sound (OK + annulation) |
| `test_explorer_dialog.py` | ExplorerDialog : ITEMS, sélection, double-clic |
| `test_key_manager.py` | Raccourcis clavier, transport, ProjectManager |
| `test_loop_points_pattern.py` | Loop points : données Pattern (29 tests) |
| `test_loop_points_player.py` | Loop points : DrumPlayer (21 tests) |
| `test_loop_select_dialog.py` | LoopSelectDialog (42 tests) |
| `test_midi_editor.py` | MidiEditor : get_note_events, sélection, édition |
| `test_midi_manager.py` | MidiManager : connexion, déconnexion, ports |
| `test_multitrack.py` | Dispatch audio multi-piste (mute, solo, volume, pan) |
| `test_mute_groups.py` | Groupes mute exclusif (AudioSampler + SoundManager) |
| `test_pad_properties_dialog.py` | PadPropertiesDialog : valeurs initiales, callbacks, durée |
| `test_pattern.py` | Pattern : création, reset, resize, double/halve, random |
| `test_pattern_properties_dialog.py` | PatternPropertiesDialog : BPM, mesures, pas |
| `test_pattern_serialization.py` | to_dict / from_dict (round-trip) |
| `test_pygame_driver.py` | PygameDriver : play, stop, volume, pan |
| `test_quantize.py` | Quantisation : apply_quant_row, apply_quant_to_pattern, force/swing/fenêtre/direction |
| `test_rename.py` | Renommage F2 : piste, pattern, song (18 tests) |
| `test_song.py` | Song : création, séquence, label |
| `test_song_serialization.py` | to_dict / from_dict Song (16 tests) |
| `test_sound_cache.py` | sound_cache : init, load, save_async, hash (21 tests) |
| `test_sound_device_driver.py` | SoundDeviceDriver : play, mix, polyphonie |
| `test_sound_manager.py` | SoundManager : load_kit, mute_groups, play_note |
| `test_synth_engine.py` | SynthEngine : chargement patch, pré-calcul, lecture |
| `test_synth_utils.py` | Utilitaires : scale_midi_notes, midi_to_note_name |
| `test_tap_tempo.py` | Tap Tempo : BPM, TAP_MIN_TAPS, timeout (20 tests) |
| `test_tape.py` | _tape (TapeEvent G/K/P) : enregistrement, sérialisation |
| `test_track_editor.py` | TrackEditor : sélection multi-pistes, limiteurs, clipboard |
| `test_track_properties_dialog.py` | TrackPropertiesDialog : slot, volume, pan |
| `test_track_router.py` | TrackRouter : routing, mute/solo, SynthEngine cache |
| `test_track_select_dialog.py` | TrackSelectDialog : checkboxes, plage BBT (33 tests) |
| `test_transport.py` | Transport : navigate_bar, move_by_*, GotoDialog |
| `test_undo_manager.py` | UndoManager : add, undo, redo, pop_last |
| `test_voice_manager.py` | VoiceManager : volume, pan, mute, solo, durée, mute_group |

---

## Outils

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
