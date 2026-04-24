# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project — Groovebox

Application desktop Python permettant de jouer des sons via le pavé numérique, de séquencer des patterns et des songs.

Specs complètes : `SPECS.md`

---

## Stack technique

| Rôle | Bibliothèque |
|---|---|
| GUI | `wxPython` |
| Audio Phase 1 | `pygame.mixer` |
| Audio Synthé / Séquenceur | `sounddevice` + `numpy` |

---

## Structure du projet

```
groovebox/
├── drums/            # 1.wav … 16.wav
├── synths/           # 1.wav … 16.wav
├── main.py           # Point d'entrée
├── audio/
│   ├── engine.py     # Polyphonie et pitch
│   └── sequencer.py  # Horloge BPM, lecture des patterns
├── ui/
│   ├── main_window.py
│   └── pads.py       # Widget 8 pads
└── data/
    ├── drum_bank.py
    ├── synth_bank.py
    ├── pattern.py
    └── song.py
```

---

## Phases de développement

### Phase 1 — Mode Drum basique (en cours)
- Lecture WAV one-shot via NumPad 1–8 et 9–16
- NumPad `+` / `-` pour switcher entre les banques (1–8 / 9–16)
- Comportement indépendant du NumLock
- Polyphonie : plusieurs instances simultanées du même pad autorisées

### Phases futures
- **Mode Synthé** : 16 hauteurs (pitchs) configurables sur un même WAV
- **Mode Séquence** : 99 patterns, 8 pistes, 1–128 mesures, 16–128 pas/mesure, BPM par pattern
- **Mode Song** : 16 songs, liste ordonnée de patterns
- **MIDI** : entrée pad MIDI externe, MIDI Clock entrant/sortant

---

## Conventions importantes

- Samples : `drums/1.wav` … `drums/16.wav` et `synths/1.wav` … `synths/16.wav`
- Persistance : JSON pour séquences et songs
- Interface grille 16×16 (cases à cocher), navigation clavier (flèches, Entrée, Shift+Entrée)
- Chaque cellule étiquetée `ligne/colonne` (ex. `1/1`, `16/16`)
