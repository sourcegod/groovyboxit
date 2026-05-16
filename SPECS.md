# Spécifications — Groovebox

Application desktop Python permettant de jouer des sons via le pavé numérique et de séquencer des patterns et des songs.

**Note architecture** : il s'agit d'un prototype Python. Si le test est concluant, les parties nécessitant plus de performances (notamment le Moteur Audio) seront réécrites en C/C++.

---

## Phase 1 — Lecture directe (Mode Drum basique) ✓

### Entrée clavier
- Écoute exclusive du **pavé numérique physique** (NumPad 1–8, ou 9-16).
- Les touches Numpad_Plus et Numpad_Minus du Pavé Numérique, permet de switcher les pads de (1-8, à 9-16).
- Comportement indépendant du NumLock.
- Par la suite, Entrée Midi, écoute des Pads par un Clavier Midi externe.

### Audio
- Format : **WAV uniquement**.
- 16 fichiers fixés à l'avance, placés dans un dossier `samples/`, nommés `1.wav` à `16.wav`.
- Comportement **one-shot** : chaque pression relance le son depuis le début (une nouvelle instance est créée).
- **Polyphonie** : plusieurs sons peuvent jouer simultanément, y compris plusieurs instances du même pad.

---

## Modes d'entrée (transversaux à toutes les phases)

Chaque piste dispose d'un **mode d'entrée** sélectionnable via une liste déroulante ou les raccourcis Ctrl+1/2/3/4 :

| Raccourci | Mode | Description |
|---|---|---|
| Ctrl+1 | **Pad** | Chaque NumPad déclenche un son indépendant (mode Drum Phase 1) |
| Ctrl+2 | **Keyboard** | Chaque NumPad joue une note d'une gamme (mode Synthé) |
| Ctrl+3 | **Chord** | Chaque NumPad joue un accord de la gamme courante |
| Ctrl+4 | **Steps** | Grille pas-à-pas (séquenceur, comme la grille actuelle) |

---

## Mode Synthé — Keyboard

### Principe
- Un **Patch** (instrument) est chargé sur la piste courante.
- Les touches NumPad 1–16 jouent les 16 notes consécutives d'une gamme choisie.
- Le pitch est pur : **pas de changement de durée** (algorithme phase vocoder / WSOLA via `pyrubberband`).
- **Polyphonie** maintenue.

### Gammes disponibles
- Chromatique (12 demi-tons)
- Majeur
- Mineur naturel
- Pentatonique majeur
- Pentatonique mineur
- *(extensible)*

### Navigation clavier en mode Keyboard
- **NumPad 1–8 / 9-16** : jouer les notes de la gamme (positions 1–16)
- **NumPad+** : décaler le clavier vers le haut (octave ou demi-ton selon config)
- **NumPad-** : décaler le clavier vers le bas
- **`/`** : changer de gamme (sens --)
- **`*`** : changer de gamme (sens ++)

### Pré-calcul du pitch
- Au chargement d'un patch, les N sons nécessaires sont **pré-calculés en mémoire** (latence zéro à la frappe).
- Le calcul se base sur les WAVs du patch et la configuration du clavier courant (gamme + octave).
- Si la configuration change (`/`, `*`, NumPad+/-), le pré-calcul est relancé.

---

## Mode Synthé — Chord

### Principe (inspiré du Maschine+)
- Chaque NumPad joue un **accord majeur** par défaut, construit sur la note de la gamme courante.
- Si une note de la **gamme mineure** est ajoutée simultanément, l'accord est altéré en **mineur**.
- Si une **septième mineure** est ajoutée, l'accord devient **accord de septième mineur**.
- Le mode Chord respecte la gamme et le patch chargés sur la piste.

---

## Patches (instruments Synthé)

### Structure d'un patch
Un patch = un sous-répertoire de `synths/`, nommé par l'instrument :

```
synths/
├── Piano/
│   ├── patch.json
│   ├── C2.wav
│   ├── G2.wav
│   ├── C3.wav
│   ├── G3.wav
│   └── C4.wav
├── Rhodes/
│   ├── patch.json
│   ├── C2.wav
│   └── ...
├── Organ/
│   └── ...
```

### Convention de nommage des WAVs
- Nom = note racine du fichier : `C3.wav`, `G#2.wav`, `Bb4.wav`…
- La note racine est lue depuis le nom du fichier (pas besoin de l'indiquer séparément).
- Au minimum **un fichier WAV par octave** pour une qualité de rééchantillonnage acceptable.

### Fichier `patch.json`
```json
{
  "name": "Piano",
  "loop": false,
  "loop_start": null,
  "loop_end": null,
  "samples": [
    { "file": "C2.wav", "root": "C2" },
    { "file": "G2.wav", "root": "G2" },
    { "file": "C3.wav", "root": "C3" }
  ]
}
```

### One-shot vs Loop
- **One-shot** (joué une fois) : Piano, Rhodes, Cloche, tout instrument à attaque percussive.
- **Loop** (boucle en sustain) : Orgue, Saxophone, Violon, tout instrument à son tenu.
- Le champ `loop` dans `patch.json` détermine le comportement.
- Les points de bouclage (`loop_start`, `loop_end`) sont définis dans le JSON.
- *À terme* : librairie de détection automatique de points de bouclage.

### Liste des patches
- Visible dans l'interface (liste déroulante ou ListBox), comme la liste des patterns.
- Chargeable sur la piste courante.

---

## Stack technique

| Rôle | Bibliothèque | Justification |
|---|---|---|
| GUI | `wxPython` | Robuste, accessibilité lecteur d'écran |
| Audio Phase 1 | `pygame.mixer` | Simple, polyphonie intégrée |
| Pitch shifting | `pyrubberband` | Bindings Python de Rubber Band (C++), pitch pur sans changement de durée |
| Chargement WAV | `soundfile` ou `scipy.io.wavfile` | Lecture dans un tableau numpy |
| Traitement audio | `numpy` | Manipulation des tableaux audio |
| Effets (futur) | `pedalboard` (Spotify) | Chaîne d'effets audio |
| Audio (futur C++) | `sounddevice` | Contrôle fin du timing et du streaming |

---

## Mode Séquence / Pattern

- **99 séquences** disponibles (Seq 01–99).
- Chaque séquence contient **8 pistes** (extensible à 16).
- Chaque séquence a un tempo (BPM) propre.
- Chaque piste peut être de 3 types :
  - **Drum** (par défaut) : chaque Pad = un son différent.
  - **Synthé** : chaque Pad = une hauteur différente (Pitch) du patch chargé.
  - **Midi** : chaque Pad peut être joué par un périphérique MIDI externe.
- Chaque piste contient **de 1 à 128 mesures**.
- Chaque mesure contient **de 16 à 128 Pas** (16, 32, 64, 128).
- Chaque Pas peut être : actif ou inactif, avec vélocité et (en mode Synthé) hauteur.
- Les pistes d'une même séquence peuvent avoir des longueurs différentes (polymétrisme optionnel).

---

## Mode Song

- **16 songs** disponibles (Song 01–16).
- Chaque song est une liste ordonnée de séquences à enchaîner.
- Lecture linéaire ; bouclage optionnel.

---

## Structure de données clés

### TNote — structure de base d'une note

Unité fondamentale commune aux patterns et aux patches. Inspirée du format MIDI.

```
TNote
  ├── position  : float   position dans la mesure, en pas (0.0 = début)
  ├── channel   : int     canal MIDI (0–15)
  ├── pitch     : int     hauteur MIDI (0–127, 60 = Do4)
  ├── velocity  : int     vélocité (0–127)
  └── length    : float   durée en pas (ex. 1.0 = un pas, 4.0 = noire à 1/16)
```

- En mode **Drum** : `pitch` = index du pad (0–15), `length` = durée du son (souvent 1 pas).
- En mode **Synthé** : `pitch` = note MIDI absolue (calculée depuis gamme + octave).
- En mode **Midi** : tous les champs transmis tels quels au périphérique MIDI.
- Compatible export/import MIDI standard (SMF).

### Rack d'instruments (global)

Le Rack est **global et partagé par tous les patterns**. Il persiste indépendamment des patterns, comme dans Maschine+.

```
Rack
  └── slots[16]           Inst 01 – Inst 16
        ├── index         : int (0–15)
        ├── type          : kit | synth | loop | audio | midi_file | midi_port
        ├── name          : str          (ex. "808 Kit", "Piano", "Synth ext.")
        └── config        : dict         (dépend du type)

  Type kit       → { "samples": ["1.wav", …, "16.wav"] }
  Type synth     → { "patch": "Piano",
                     "scale": "major", "root_note": "C3",
                     "cache": {(scale, octave): [pygame.Sound × 16]} }
  Type loop      → { "file": "bassline.wav", "sync_bpm": true }
  Type audio     → { "file": "vocal.wav", "loop": false }
  Type midi_file → { "file": "bassline.mid" }
  Type midi_port → { "port": "Synth MIDI Out", "channel": 0 }
```

**Correspondance type Instrument ↔ type Track :**

Le `track_type` d'une piste correspond au type de l'instrument chargé dans son slot. Les 6 types sont communs aux deux :

| Type | Instrument (Rack) | Comportement NumPad / lecture |
|---|---|---|
| **kit** | 16 WAVs indépendants | chaque pad = son différent |
| **synth** | Patch + pitch shifting | chaque pad = hauteur de gamme |
| **loop** | WAV synchronisé BPM | lecture / stop de la boucle |
| **audio** | WAV one-shot ou libre | déclenche le sample |
| **midi_file** | Fichier MIDI (.mid) | lit le fichier sur la piste |
| **midi_port** | Port MIDI externe | envoie TNote au périphérique |

**Règles du Rack :**
- On peut charger un nouvel instrument dans un slot **sans modifier les données des patterns**.
- Pour les slots `synth` : seule la gamme/octave active est pré-calculée ; les autres sont calculées à la demande et mises en cache.

**Hiérarchie de chargement :**

| Action | Slots affectés | Patterns affectés |
|---|---|---|
| Charger un instrument | **1 slot** seulement | aucun |
| Charger un pattern | Les slots référencés par ses pistes | 1 pattern |
| Charger un projet | **Les 16 slots** (Rack complet) | tous les patterns |

### Structures patterns et projet

```
Patch (descripteur d'un instrument Synth sur disque)
  ├── name        : str
  ├── loop        : bool
  ├── loop_start  : float | None   (secondes)
  ├── loop_end    : float | None
  └── samples[]
        ├── file  : str            (ex. "C3.wav")
        └── root  : str            (note racine MIDI, ex. "C3" = 48)

Pattern (Séquence)
  ├── id          : 1–99
  ├── bpm         : float
  └── tracks[8]
        ├── instrument_slot : int  (0–15, référence dans le Rack global)
        ├── track_type      : kit | synth | loop | audio | midi_file | midi_port
        ├── mode            : pad | keyboard | chord | steps
        ├── scale           : str  (si keyboard/chord, peut surcharger le slot)
        ├── root_note       : str  (si keyboard/chord)
        └── measures[1–128]
              └── notes[]   : list[TNote]  (liste libre, non limitée à num_steps)

Song
  ├── id          : 1–16
  └── sequence_ids[] : liste ordonnée de Pattern.id
```

> La grille 16×16 de l'interface (mode Steps) est une **vue quantisée** de la liste `notes[]`.
> Cocher une case = ajouter un TNote à `position` correspondante.
> Décocher = supprimer le TNote à cette position.

### Fichier projet (`.grp`)

Extension propriétaire `.grp` (GroovyboxIt Project), format JSON interne.

```json
{
  "version": 1,
  "rack": {
    "slots": [
      { "index": 0, "type": "kit",       "name": "808 Kit",
        "config": { "samples": ["1.wav", "..."] } },
      { "index": 1, "type": "synth",     "name": "Piano",
        "config": { "patch": "Piano", "scale": "major", "root_note": "C3" } },
      { "index": 2, "type": "loop",      "name": "Bass loop",
        "config": { "file": "bassline.wav", "sync_bpm": true } },
      { "index": 3, "type": "midi_file", "name": "Seq MIDI",
        "config": { "file": "sequence.mid" } },
      { "index": 4, "type": "midi_port", "name": "Synth ext.",
        "config": { "port": "Synth MIDI Out", "channel": 0 } }
    ]
  },
  "patterns": [
    {
      "id": 1, "bpm": 120,
      "tracks": [
        { "instrument_slot": 0, "track_type": "kit",  "mode": "steps",
          "measures": [ { "notes": [
            { "pos": 0, "ch": 0, "pitch": 36, "vel": 100, "len": 1 }
          ]} ] },
        { "instrument_slot": 1, "track_type": "synth", "mode": "keyboard",
          "scale": "major", "root_note": "C3",
          "measures": [ { "notes": [] } ] }
      ]
    }
  ],
  "songs": []
}
```

---

## Organisation des fichiers source (cible)

```
groovyboxit/
├── media/              # sons drum + métronome
├── synths/             # patches synthé (Piano/, Rhodes/, Organ/…)
├── main.py
├── src/
│   ├── pattern.py
│   ├── drum_player.py
│   ├── sound_manager.py
│   ├── voice_manager.py
│   ├── synth_engine.py     # pitch shifting, gestion patches
│   └── ui/
│       ├── main_window.py
│       └── dialogs.py
└── data/
    └── presets/        # presets JSON
```

---

## Sauvegarde des données
- Persistance : presets JSON (patterns + voix + patches chargés par piste).

## Interface
- Grille 16×16 de cases à cocher (accessibilité lecteur d'écran).
- Mode d'entrée sélectionnable par liste déroulante + Ctrl+1/2/3/4.
- Liste de patches (comme la liste de patterns).
- Navigation clavier complète (flèches, Entrée, raccourcis).

## Points ouverts
- **MIDI** : entrée pad MIDI externe, MIDI Clock entrant/sortant.
- **Détection de points de bouclage** : librairie à identifier.
- **Mode Chord** : définition précise des voicings et inversions d'accords.
- **Synchronisation** : MIDI Clock entrant/sortant.
