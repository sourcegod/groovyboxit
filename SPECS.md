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
| Phase 4 | Mode Song, synchronisation MIDI Clock | — |

---

## Stack technique

| Rôle | Bibliothèque |
|---|---|
| GUI | `wxPython` |
| Audio (one-shot, kit) | `pygame.mixer` |
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
│   ├── audio_tools.py    # Détection de points de bouclage (AudioTools)
│   ├── drum_player.py    # Séquenceur : lecture, enregistrement, note repeat
│   ├── midi_manager.py   # Connexion ports MIDI in/out
│   ├── note.py           # Utilitaires note MIDI
│   ├── pattern.py        # Données pattern : grille, kit_tape, patch_tape
│   ├── rack.py           # Rack 16 slots + InstrumentType
│   ├── sound_manager.py  # Lecture WAV : kits, note_map, pad_sound
│   ├── synth_engine.py   # Moteur synthé : chargement patch, pitch shifting, cache
│   ├── track_router.py   # Routage piste→slot→SynthEngine, dispatch audio
│   ├── voice_manager.py  # Volume, pan, mute, solo, durée par pad
│   └── ui/
│       ├── dialogs.py    # Boîtes de dialogue
│       ├── key_manager.py # Gestion clavier (raccourcis)
│       ├── main_window.py # Fenêtre principale
│       └── midi_handler.py # Logique MIDI (séparée de MainWindow)
├── data/
│   ├── config.json       # Chemins configurables (voir §Configuration)
│   ├── kits/             # Fichiers kit JSON (ex. tr_707.json)
│   └── presets/          # Presets JSON (ex. preset_01.json)
├── media/                # Sons drum par défaut (1.wav … 16.wav) + métronome
├── tools/
│   ├── extract_gm_drums.py  # Script extraction drums GM depuis FluidSynth
│   └── find_loop_points.py  # Script détection points de bouclage
├── docs/
│   └── shortcuts.md      # Liste des raccourcis clavier
└── tests/
    ├── test_all.sh
    ├── test_app_launch.py
    ├── test_explorer_actions.py
    ├── test_explorer_dialog.py
    ├── test_key_manager.py
    ├── test_midi_manager.py
    ├── test_multitrack.py
    ├── test_pad_properties_dialog.py
    ├── test_pattern.py
    ├── test_pattern_properties_dialog.py
    ├── test_pattern_serialization.py
    ├── test_quantize.py
    ├── test_synth_engine.py
    ├── test_synth_utils.py
    ├── test_tape.py
    ├── test_track_properties_dialog.py
    ├── test_track_router.py
    └── test_voice_manager.py
```

---

## Configuration (`data/config.json`)

```json
{
  "patches_dir":  "/chemin/vers/PATCHS",
  "samples_dir":  "/chemin/vers/SAMPLES",
  "kits_dir":     "/chemin/vers/KITS",
  "presets_dir":  "/chemin/vers/PRESETS"
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
    { "pad": 1, "note": 35, "filename": "/chemin/35_BassDrum2.wav", "label": "Kick 2" },
    { "pad": 2, "note": 36, "filename": "/chemin/36_BassDrum1.wav", "label": "Kick 1" },
    ...
    { "pad": 16, "filename": "", "label": "---" }
  ]
}
```

- `note` : note MIDI GM (35–81), utilisée pour le mapping MIDI et le pitch
- `filename` : chemin absolu ou relatif au JSON
- `label` : nom affiché dans la liste des pads

### SoundManager — API Kit

| Méthode | Description |
|---|---|
| `load_kit(json_path)` | Charge le kit, construit `drum_sounds[16]` et `note_map` |
| `load_pad_sound(pad_idx, wav_path)` | Remplace un son individuel dans `drum_sounds` |
| `load_sounds()` | Charge les sons par défaut depuis `media/` |
| `play_sound(index, vol, pan)` | Joue `drum_sounds[index]` |
| `play_note(midi_note, vol, pan)` | Joue via `note_map[midi_note]` |
| `shift_kit(delta)` | Décale `kit_offset` de ±8 (plage : 0 — max notes du kit) |

- `drum_sounds` : liste de 16 `pygame.Sound`, reconstruite à partir de `note_map` + `kit_base` + `kit_offset`
- `note_map` : `{midi_note: pygame.Sound}` — tous les sons du kit avec champ `"note"`

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
- Le dernier pad joué est pitcher sur les notes de la gamme
- NumPad 1–8 joue le pad source pitché sur 8 notes de la gamme
- Root C4 = pitch original du son
- NumPad+/- décale l'octave, NumPad/*  change de gamme

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
  ├── _track_slots   [int × 8]   slot assigné à chaque piste
  ├── _track_mutes   [bool × 8]
  ├── _track_solos   [bool × 8]
  ├── _track_volumes [int × 8]   0..100
  ├── _track_pans    [int × 8]   -100..+100
  ├── _voices        [dict × 16] volume, pan, mute, solo, durée par pad
  ├── _curpattern    [8 pistes × 16 pads × N mesures × N pas]  valeurs = vélocité (0 ou 0..127)
  ├── _kit_tape      {(track,bar,step): [(note,vel,dur)…]}  notes MIDI brutes (kit)
  └── _patch_tape    {(track,bar,step): [(note,vel,dur)…]}  notes MIDI brutes (synth)
```

- 99 patterns disponibles (Pattern 01–99)
- 8 pistes par pattern
- 16 pads par piste
- Pas : vélocité 0 (inactif) ou 1–127 (actif avec vélocité)
- `_kit_tape` : capture MIDI brute pour les pistes KIT (note MIDI réelle, indépendante du kit_offset)
- `_patch_tape` : capture MIDI brute pour les pistes SYNTH (note MIDI absolue + durée réelle)

### Quantisation

Valeurs disponibles (`Pattern.QUANT_STEPS`) :
`[1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128]`

La quantisation s'applique à l'enregistrement (caler les hits sur la grille) et à la relecture (appliquer au pattern).

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

### Mode Erase (E)
- NumPad 1–8 : efface l'événement le plus proche du temps d'appui sur ce pad
- Fonctionne en temps réel pendant la lecture
- Prend en charge la plage de notes MIDI tenues (effacement par plage)

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

## BPM

- Plage : non bornée en code (valeur par défaut 100)
- Raccourcis : `(` ou `5` → BPM+5 ; `)` → BPM-5
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

### Script `tools/find_loop_points.py`
- Analyse tous les samples d'un patch et met à jour `patch.json` (`loop_start`/`loop_end` par sample)
- Option `--dry-run` : affiche les résultats sans modifier le fichier
- Options : `--tail`, `--min-corr`

*Statut : détection implémentée, cross-fade appliqué dans SynthEngine. Interface graphique d'édition manuelle non terminée.*

---

## Sérialisations — Fichiers JSON

### Preset (`presets/preset_01.json`)

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
      "track_slots":   [0, 0, 0, 0, 0, 0, 0, 0],
      "track_mutes":   [false, …],
      "track_solos":   [false, …],
      "track_volumes": [100, …],
      "track_pans":    [0, …],
      "curpattern":    [[[[0, 0, …], …], …], …],
      "voices":        [{ "name": "", "volume": 100, "pan": 0, "mute": false,
                          "solo": false, "duration_ms": 500 }, …],
      "kit_tape":   [[track, bar, step, note_midi, vel, dur_ms], …],
      "patch_tape": [[track, bar, step, note_midi, vel, dur_ms], …]
    },
    …
  ]
}
```

- Le preset sauvegarde l'intégralité des 99 patterns + le rack complet.
- Chargé au démarrage via `_load_preset()`, sauvegardé via `_save_preset()` (Alt+W).

### Kit (`data/kits/tr_707.json`)

```json
{
  "name": "TR-707",
  "pads": [
    { "pad": 1, "note": 35, "filename": "/chemin/35_BassDrum2.wav", "label": "Kick 2" },
    …
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
    …
  ]
}
```

---

## Interface graphique

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

### Grille (séquenceur)

- 16 lignes (pads) × 16 colonnes (pas)
- Cases à cocher — accessibles au lecteur d'écran
- Navigation clavier : flèches, Entrée (cocher/décocher + jouer la ligne), Shift+Entrée (décocher + jouer)
- Autoplay : cocher/décocher une case rejoue automatiquement la ligne courante
- La valeur d'une case = vélocité (0 ou 1–127)

### Gestion du focus et Enter sur ListBox (GTK)

Sur Linux/GTK, la touche Entrée sur une `wx.ListBox` est interceptée par GTK et transformée en `EVT_LISTBOX_DCLICK` **avant** qu'elle n'atteigne `EVT_CHAR_HOOK`. Solution utilisée : handler `EVT_LISTBOX_DCLICK` avec `wx.GetKeyState(wx.WXK_RETURN)` pour distinguer Entrée d'un vrai double-clic.

---

## Boîtes de dialogue

| Classe | Déclencheur | Description |
|---|---|---|
| `KeyboardHelpDialog` | F1 | Aide raccourcis clavier |
| `GenRowDialog` | Ctrl+Shift+E | Générer un motif sur la ligne + choisir la quant |
| `QuantizeDialog` | Ctrl+Shift+Q | Choisir la valeur de quantisation + appliquer au pattern |
| `SavePatternDialog` | Ctrl+Shift+W | Sauvegarder le pattern sous un nouveau nom |
| `TrackPropertiesDialog` | Ctrl+T / Entrée sur piste | Propriétés de la piste (slot, volume, pan, mute, solo) |
| `PatternPropertiesDialog` | Alt+Entrée sur pattern | Propriétés du pattern (nom, BPM, mesures, pas) |
| `PadPropertiesDialog` | Alt+Entrée sur grille | Propriétés du pad (volume, pan, mute, solo, durée) |
| `ExplorerDialog` | Alt+X | Sélection du type de ressource à charger |

### ExplorerDialog (Alt+X)

ListBox avec 4 items :
- **Preset** : ouvre un FileDialog dans `presets_dir`, charge le fichier `.json` sélectionné
- **Kit** : ouvre un FileDialog dans `kits_dir`, affecte le kit au slot courant
- **Patch** : ouvre un FileDialog dans `patches_dir`, affecte le patch au slot courant (SYNTH)
- **Sound** : ouvre un FileDialog dans `samples_dir`, remplace le WAV du pad courant

Le double-clic sur un item valide directement la sélection (`EVT_LISTBOX_DCLICK → EndModal(ID_OK)`).

---

## Chargement des ressources

### Preset
1. `rack.from_dict(data["rack"])` — restaure les 16 slots
2. `_pattern_list[i].from_dict(p)` pour chaque pattern
3. Pour chaque slot KIT distinct utilisé par les pistes : `_load_kit_slot(slot_idx)`
4. Pour le slot de la piste courante si SYNTH : `_router.load_slot_preview(cur_slot)`
5. `_router.clear_slot_synths()` — invalide le cache des moteurs SYNTH

### Kit
- `sound_manager.load_kit(json_path)` → met à jour `drum_sounds[16]` et `note_map`
- Labels des pads mis à jour dans `voice_manager`

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

### kit_tape / patch_tape
- Capture MIDI brute pendant l'enregistrement
- `kit_tape` : note MIDI brute (indépendante du kit_offset) → `play_note(midi_note)`
- `patch_tape` : note MIDI absolue + durée réelle → `engine.play(midi_note, dur)`

---

## Raccourcis clavier

Liste complète dans `docs/shortcuts.md`.

Catégories principales :
- Preset (Alt+W, Alt+Shift+W)
- Pattern (Ctrl+W/D/P/F/Shift+P/F)
- Quantisation (Ctrl+E/Q, Shift+E/Q)
- Lecture (Espace, P, V, C, Q)
- Mute/Solo pads et pistes (X, S, Shift+X/S)
- Volume/Pan pad (Alt+flèches)
- Enregistrement (R, Shift+R, Ctrl+R)
- Erase (E)
- Note Repeat (Q, touches 1–9)
- BPM/Volume/Pan global
- Navigation grille (flèches, Entrée)
- NumPad (1–9, Entrée, 0, +, -)
- Mode Keyboard (Ctrl+1/2, NumPad+/-/×/÷)
- Patterns (Alt+Entrée, double-clic)
- Slots (double-clic)
- Pistes (Ctrl+T, Shift+D, Entrée)
- MIDI (Alt+M, Alt+Shift+M)
- Aide (F1)

---

## Tests unitaires

Tous les tests sont dans `tests/`. Exécution globale : `bash tests/test_all.sh`

| Fichier | Couvre |
|---|---|
| `test_app_launch.py` | Démarrage de l'application |
| `test_explorer_actions.py` | Actions explorer : Preset, Kit, Patch, Sound (OK + annulation) |
| `test_explorer_dialog.py` | ExplorerDialog : ITEMS, sélection, double-clic |
| `test_key_manager.py` | Raccourcis clavier, Shift+D, Enter grille, Enter ListBox |
| `test_midi_manager.py` | MidiManager : connexion, déconnexion, ports |
| `test_multitrack.py` | Dispatch audio multi-piste (mute, solo, volume, pan) |
| `test_pad_properties_dialog.py` | PadPropertiesDialog : valeurs initiales, callbacks, durée |
| `test_pattern.py` | Pattern : création, reset, resize, double/halve, random |
| `test_pattern_properties_dialog.py` | PatternPropertiesDialog : BPM, mesures, pas |
| `test_pattern_serialization.py` | to_dict / from_dict (round-trip) |
| `test_quantize.py` | Quantisation : apply_quant_row, apply_quant_to_pattern |
| `test_synth_engine.py` | SynthEngine : chargement patch, pré-calcul, lecture |
| `test_synth_utils.py` | Utilitaires : scale_midi_notes, midi_to_note_name |
| `test_tape.py` | kit_tape / patch_tape : enregistrement, sérialisation |
| `test_track_properties_dialog.py` | TrackPropertiesDialog : slot, volume, pan |
| `test_track_router.py` | TrackRouter : routing, mute/solo, SynthEngine cache |
| `test_voice_manager.py` | VoiceManager : volume, pan, mute, solo, durée |

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

### `tools/find_loop_points.py`

Détecte les points de bouclage d'un patch et met à jour `patch.json`.

```
Usage:
  python3 tools/find_loop_points.py synths/Organ_B3
  python3 tools/find_loop_points.py synths/Organ_B3 --dry-run
  python3 tools/find_loop_points.py synths/Organ_B3 --tail 0.20 --min-corr 0.95
```

- Analyse chaque sample via `AudioTools.find_loop_points()`
- Met à jour `loop_start` / `loop_end` dans `patch.json` par sample
- Si au moins un point trouvé, passe `"loop": true`

---

## Points ouverts / Phase 4

- **Mode Song** : liste ordonnée de patterns à enchaîner
- **MIDI Clock** : synchronisation entrante/sortante
- **Slots LOOP / AUDIO / MIDI_FILE / MIDI_PORT** : types définis, non implémentés
- **Mode Chord** : voicings d'accords sur la gamme courante
- **Explorateur graphique avancé** : navigation arborescente par type, preview sonore
- **Interface édition points de bouclage** : visualisation forme d'onde, édition manuelle loop_start/loop_end
