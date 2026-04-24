# Spécifications — Groovebox

Application desktop Python permettant de jouer des sons via le pavé numérique et, à terme, de séquencer des patterns et des songs.

---

## Phase 1 — Lecture directe (Mode Drum basique)

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

## Modes futurs

### Mode Drum
Lecture de chaque son à chaque pression sur une touche du pavé (comportement identique à la Phase 1, intégré dans l'interface modale).

### Mode Synthé
- L'utilisateur choisit un fichier WAV comme source sonore.
- Les touches NumPad 1–16 jouent ce son à **16 hauteurs (pitchs) différentes**.
- Les hauteurs sont configurables (ex. gamme diatonique, chromatique, libre).
- Polyphonie maintenue.

### Mode Séquence / Pattern
- **99 séquences** disponibles (Seq 01–99).
- Chaque séquence contient **8 pistes** (qui peut changer en 16 pistes plus tard), (une par pad / son).
- Chaque séquence a un tempo (BPM) propre à elle. 
- Chaque piste peut être de de 3 types différents: 
  -- Type Drum: (par défaut), chaque  Pad contient un Son différent.
  -- Type Synthé: chaque Pad est une hauteur différente (Pitch) du son choisi.
  -- Type Midi: chaque Pad peut être joué par une entrée Midi d'un périphérique externe.

- Chaque piste contient **de 1 à 128 mesures**.
- Chaque mesure contient **de 16 à 128 Pas**, soit (16, 32, 64, 128 Pas).
- Le nombre de Pas dans une mesure, est le nombre de division de temps par mesure.
- Exemple 4 Pas: => 1/4 par mesure, => 4 Noires par mesure.
- 16 Pas: => 1/16 par mesure, => 16 Double Croches par mesure.
- 32 Pas: => 1/32 par mesure, => 32 Tripple Croches par mesure. ETC...

- Chaque Pas peut être : actif ou inactif, avec vélocité et (en mode Synthé) hauteur.
- Lecture en boucle à un **tempo en BPM** global.
- Les pistes d'une même séquence peuvent avoir des longueurs de mesure différentes (polymétrisme optionnel).

### Mode Song
- **16 songs** disponibles (Song 01–16).
- Chaque song est une liste ordonnée de séquences à enchaîner.
- Lecture linéaire ; le bouclage de la song entière est optionnel.

---

 Architecture technique

 
### Stack Python recommandée

| Rôle | Bibliothèque | Justification |
|---|---|---|
| GUI | `WxPython` | Robuste, extensible, gestion native des événements clavier | Accessibilité sur plusieurs plateformes
| Audio (Phase 1) | `pygame.mixer` | Simple, polyphonie intégrée, latence acceptable |
| Audio (Synthé / Séquenceur) | `sounddevice` + `numpy` | Contrôle fin du pitch et du timing |

### Structure de données clés

```
DrumBank
  └── [16] → chemin fichier WAV

SynthBank
  └── [16] → chemin fichier WAV


Pattern (Séquence)
  ├── id          : 1–99
  ├── bpm         : float
  └── tracks[8]
        ├── track_type  : [drum_type, synth_type, midi_type]
        ├── sample_id  : ref [DrumBank, SynthBank]
        └── measures[1–128]
              └── steps[16–128]
                    ├── active   : bool
                    ├── velocity : 0–127
                    └── pitch    : demi-tons (0 = original)

Song
  ├── id          : 1–16
  └── sequence_ids[] : liste ordonnée de Pattern.id
```

### Organisation des fichiers source (cible)

```
groovebox/
├── drums/          # 1.wav … 16.wav
├── synths/          # 1.wav … 16.wav
├── main.py           # Point d'entrée, initialisation Qt
├── audio/
│   ├── engine.py     # Gestion de la polyphonie et du pitch
│   └── sequencer.py  # Horloge BPM, lecture des patterns
├── ui/
│   ├── main_window.py
│   └── pads.py       # Widget des 8 pads (affichage + état)
└── data/
    ├── drum_bank.py
    ├── synth_bank.py
    ├── pattern.py
    └── song.py
```

---

### Sauvegarde des données
- **Persistance** : les séquences et songs sont-elles sauvegardées sur disque (JSON).

### Interface
- **Interface** : affichage minimal (fenêtre + retour visuel par pad).
- La fenêtre principale (Main Window), est représentée par une grille de 16 / 16, dont chaque colone est une (Case à cocher, pour l'accessibilité des lecteurs d'écran).
- Chaque ligne représente le Pad (donc un son) à jouer, qui peut être atteinte par les touches (Flèches Haut / Bas)
- Chaque colone représente un Pas, qui peut être atteinte par les touches(Flèches Gauche / Droite).
- Chaque colone est étiquettée par son numéro de ligne et de colone, (Ex: 1/1, 1/16, 16/1, 16/16).
- Chaque colone est une (Case à cocher), que l'on peut activer ou désactiver par la touche Entrée.
- On peut désactiver n'importe quelle colone par les touches (Shift+Enter).

### Points Ouverts (à voir plus tard).
- **Synchronisation** : MIDI Clock entrant/sortant envisagé.
