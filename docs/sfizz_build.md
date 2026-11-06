# Compiler et installer libsfizz (lecteur SFZ)

Phase 8 étape 7a1. Procédure complète, de A à Z, suivie le 2026-11-04 sur
la machine de développement, puis **rejouée à blanc** dans un dossier
neuf pour vérifier chaque commande (durées mesurées ci-dessous). Les deux
compilations ont donné le même résultat : mêmes tests verts, et
`tools/sfizz_probe.py` passe sur chacune des deux bibliothèques.

libsfizz est la bibliothèque C/C++ du projet [sfizz](https://sfz.tools/sfizz/)
(sfztools, licence BSD 2 clauses). Elle lit les instruments au format
**SFZ** (un fichier texte qui décrit des régions de samples WAV/FLAC…).
L'appli la chargera par **ctypes**, comme libfluidsynth (Phase 7
étape 17), derrière l'interface `BankEngine` ; la future version C/C++
la liera directement.

**Pourquoi la compiler** : libsfizz n'est **pas** dans les dépôts de
Debian 13 (trixie). FluidSynth, lui, est fourni compilé par Debian
(`libfluidsynth3`).

---

## 1. Environnement de référence

| Élément | Version |
|---|---|
| Système | Debian 13 (trixie), x86_64, noyau 6.12 |
| Compilateur | GCC / g++ 14.2.0 |
| CMake | 3.31.6 |
| Git | 2.47.3 |
| Processeur | 8 cœurs (compilation en `-j8`) |
| sfizz | branche par défaut au commit `f5c6e29` (2025-03-17), bibliothèque **1.2.3** |

## 2. Prérequis

Paquets Debian nécessaires (tous déjà installés sur la machine) :

```sh
sudo apt install build-essential cmake git pkg-config
```

- Aucune autre bibliothèque n'est **requise** : sfizz embarque ses
  dépendances (abseil-cpp, simde, filesystem, dr_libs pour WAV/FLAC/MP3,
  libaiff, wavpack, pugixml, kiss_fft, Catch2…) en sous-modules Git ou
  dans `external/`.
- `libsamplerate` (`libsamplerate0-dev`) est trouvée si elle est
  présente (0.2.2 ici) : elle sert à `sfizz_render`, pas à la bibliothèque.
- `libsndfile1-dev` et JACK n'ont **pas** servi (options laissées à
  `OFF`, voir § 4).
- Place disque : environ **210 Mo** (sources, sous-modules et dossier de
  compilation).

## 3. Récupérer les sources (git clone)

```sh
mkdir -p /home/com/build
cd /home/com/build
git clone --recursive --depth 1 --shallow-submodules \
    https://github.com/sfztools/sfizz.git
cd sfizz
git log -1 --format='%h %cd'      # f5c6e29 Mon Mar 17 21:18:36 2025 +0100
```

- `--recursive` est **indispensable** : sans les sous-modules, CMake
  s'arrête (contrôle `SFIZZ_GIT_SUBMODULE_CHECK`).
- `--depth 1 --shallow-submodules` : seulement la dernière version, sans
  l'historique (plus rapide, plus léger).
- Durée mesurée : **53 s** (réseau).
- Sous-modules récupérés (commit abrégé) :

| Sous-module | Commit |
|---|---|
| `external/abseil-cpp` | `4a2c63365e` |
| `external/filesystem` | `8a2edd6d92` |
| `external/invoke.hpp` (+ `vendors/doctest`) | `2c1eabc2e2` (`86892fc480`) |
| `external/simde` (+ `test/munit`) | `2bf459d4ed` (`da8f734129`) |
| `external/st_audiofile/thirdparty/dr_libs` (+ miniaudio) | `e4a7765e59` (`d1a166c83a`) |
| `external/st_audiofile/thirdparty/libaiff` | `78864a4a2e` |
| `external/st_audiofile/thirdparty/wavpack` | `07ffb331d2` |

Pour figer **exactement** la même version plus tard (un clone sans
`--depth` est alors nécessaire) :

```sh
git clone --recursive https://github.com/sfztools/sfizz.git
cd sfizz
git checkout f5c6e29
git submodule update --init --recursive
```

## 4. Configurer (CMake)

```sh
cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=$HOME/.local \
    -DSFIZZ_SHARED=ON \
    -DSFIZZ_JACK=OFF \
    -DSFIZZ_RENDER=ON \
    -DSFIZZ_TESTS=ON
```

| Option | Valeur | Pourquoi |
|---|---|---|
| `CMAKE_BUILD_TYPE` | `Release` | optimisé (LTO activé automatiquement) |
| `CMAKE_INSTALL_PREFIX` | `$HOME/.local` | installation sans `sudo`, dans le dossier de l'utilisateur |
| `SFIZZ_SHARED` | `ON` | produit `libsfizz.so`, celle que ctypes charge |
| `SFIZZ_JACK` | `OFF` | le client JACK autonome est inutile : l'appli rend le son elle-même |
| `SFIZZ_RENDER` | `ON` | `sfizz_render` : rend un `.mid` à travers un `.sfz` en WAV, utile pour comparer à l'écoute |
| `SFIZZ_TESTS` | `ON` | compile la suite de tests de sfizz (§ 6) |
| `SFIZZ_USE_SNDFILE` | `OFF` (défaut) | les décodeurs embarqués (dr_libs) suffisent |

Résumé affiché par CMake (extrait) : C++14, Release, LTO `ON`,
bibliothèque partagée `ON`, JACK `OFF`, render `ON`, tests `ON`,
sndfile `OFF`, toutes les dépendances embarquées (« Use system … :
OFF »), préfixe `/home/sam/.local`.

**Avertissements sans conséquence** pendant la configuration :
- abseil-cpp : « A future Abseil release will default
  ABSL_PROPAGATE_CXX_STD to ON » ;
- « Could not find a package configuration file provided by "Qt5" » :
  Qt5 ne sert qu'aux outils de développement (`SFIZZ_DEVTOOLS=OFF`).

Durée : 3 s.

## 5. Compiler

```sh
cmake --build build -j8
```

- Durée mesurée : **1 min 58 s** sur 8 cœurs (11 min 28 s de temps
  processeur), tests et `sfizz_render` compris.
- 134 avertissements du compilateur, tous bénins (surtout
  `-Wunused-parameter`) ; code de sortie 0.
- Produits, dans `build/library/` :
  - `lib/libsfizz.so.1.2.3` (+ liens `libsfizz.so.1`, `libsfizz.so`) ;
  - `bin/sfizz_render` ;
  - `bin/sfizz_tests`.

## 6. Lancer les tests de sfizz

Les tests s'exécutent **depuis le dossier `tests/`** des sources (ils y
trouvent leurs fichiers `TestFiles/*.sfz` et `*.wav`) :

```sh
cd tests
../build/library/bin/sfizz_tests
cd ..
```

Résultat attendu, dernière ligne :

```
All tests passed (52206 assertions in 477 test cases)
```

- Durée : 1 s.
- Deux lignes `Parse error in "." at line 1: Cannot open file for
  reading:` apparaissent avant : elles viennent de tests qui vérifient
  **volontairement** le refus d'un fichier introuvable. Ce n'est pas une
  erreur.
- On peut aussi passer par CTest : `ctest --test-dir build`.

## 7. Installer

```sh
cmake --install build
```

Fichiers installés :

```
~/.local/lib/libsfizz.so.1.2.3
~/.local/lib/libsfizz.so.1 -> libsfizz.so.1.2.3
~/.local/lib/libsfizz.so   -> libsfizz.so.1
~/.local/include/sfizz.h          # API C (celle de ctypes)
~/.local/include/sfizz.hpp        # API C++ (future version C/C++)
~/.local/include/sfizz_message.h
~/.local/lib/pkgconfig/sfizz.pc
~/.local/bin/sfizz_render
```

- `~/.local/lib` n'est **pas** dans le chemin de recherche du système
  (`ldconfig`) : l'appli et `tools/sfizz_probe.py` chargent la
  bibliothèque par son **chemin complet**
  (`~/.local/lib/libsfizz.so.1`), puis essaient le système.
- `sfizz_render` est lié à sfizz en statique : il marche sans
  `LD_LIBRARY_PATH`.
- Pour désinstaller : supprimer les fichiers listés dans
  `build/install_manifest.txt` (`xargs rm < build/install_manifest.txt`).

## 8. Essayer la bibliothèque par ctypes (outil maison)

```sh
python3 tools/sfizz_probe.py
python3 tools/sfizz_probe.py --lib /chemin/libsfizz.so.1
python3 tools/sfizz_probe.py --keep /tmp/sfz_essai   # garde WAV et .sfz
```

L'outil `tools/sfizz_probe.py` déclare les fonctions C utilisées
(`argtypes` / `restype`, comme `src/audio/engines/fluidsynth_engine.py`),
fabrique dans un dossier temporaire des WAV synthétiques (cosinus à 440
et 660 Hz) et deux petits `.sfz`, puis vérifie ce dont le futur moteur
SFZ de l'appli aura besoin. Code de sortie : 0 si tout passe, 1 en cas
d'échec, 2 si la bibliothèque est introuvable.

Résultat du 2026-11-04 (machine au repos) :

| Vérification | Résultat |
|---|---|
| Chargement d'un `.sfz` | OK, < 1 ms, 1 région, 1 sample préchargé |
| Opcode inconnu signalé (`sfizz_get_unknown_opcodes`) | OK (`foo_unknown`) |
| Fichier absent refusé | OK (sfizz écrit « Parse error … Cannot open file » sur la sortie d'erreur) |
| Silence avant toute note | OK |
| Note 69 = `pitch_keycenter` | 440,0 Hz |
| Une octave au-dessus / au-dessous (transposition par sfizz) | 880,0 Hz / 220,0 Hz |
| Vélocité 50 plus douce que 100 | OK : RMS 0,0146 contre 0,0582 (courbe quadratique, (50/100)² = 1/4) |
| Pitch Bend +8191 | 493,8 Hz = +2 demi-tons (défaut SFZ ±200 cents) |
| Note off : voix libérée après le release | OK, 0 voix |
| `note_on` avec `delay=300` | commence exactement à l'échantillon 300 du bloc |
| All Sound Off | OK, 0 voix |
| CC64 (pédale) | tient la note, la relâcher la libère |
| `group` / `off_by` (groupes exclusifs) | la note 61 coupe la note 60 |
| Deux instances | indépendantes : 440,0 Hz et 659,3 Hz |
| Coût : 32 voix tenues | **2,5 % du temps réel** (53 ms pour 2,13 s de son, blocs de 512 à 48 kHz) |

Mesures d'information (pas des vérifications) :
- **Niveau** : un cosinus d'amplitude 0,5 joué à vélocité 100 sort en RMS
  0,058 (crête 0,08) : un gain sera à régler à l'écoute dans l'appli,
  comme `fluidsynth_gain`.
- **CC répondus par défaut**, sans opcode dans le `.sfz` : CC7 (volume),
  CC11 (expression), CC10 (pan, loi à puissance constante), CC64
  (pédale). Le volume et le pan de piste de l'appli pourront donc passer
  par CC7 et CC10, comme pour FluidSynth.

## 9. Faits de l'API C qui pèsent sur la conception

Lus dans `sfizz.h` et confirmés par l'outil :

- **Une instance sfizz = un instrument, sans canal MIDI** : aucune
  fonction ne prend de canal. Plusieurs instruments = plusieurs instances
  (`sfizz_create_synth`).
- **Événements datés dans le bloc** : chaque envoi (`sfizz_send_note_on`,
  `_cc`, `_pitch_wheel`…) porte un `delay` en échantillons, compté dans
  le prochain `sfizz_render_block`. Le modèle naturel est une file
  d'événements datés vidée dans le callback audio.
- **Rendu en canaux séparés** : `sfizz_render_block(synth, float**
  canaux, 2, frames)` écrit L et R dans deux tampons (pas entrelacés,
  contrairement à `fluid_synth_write_float`) ; ils doivent être ajoutés
  au mixage.
- **Chargement bloquant** : `sfizz_load_file` lit le fichier et
  précharge le début de chaque sample (`sfizz_set_preload_size`), le
  reste étant lu sur le disque pendant le jeu. À faire dans un fil, sur
  une instance neuve, puis échanger.
- **Fréquence et taille de bloc** à donner avant le chargement
  (`sfizz_set_sample_rate`, `sfizz_set_samples_per_block`).
- Libérer avec `sfizz_free` ; les chaînes rendues par sfizz
  (`sfizz_get_unknown_opcodes`…) avec `sfizz_free_memory`.

## 10. Lancer l'appli sans sfizz (ni FluidSynth)

FluidSynth et sfizz dépendent de bibliothèques compilées : l'appli se
lance et reste **entièrement fonctionnelle sans elles** (Phase 8 étape 7) :

```sh
python3 main.py --no-sfizz                    # sans sfizz, pour ce lancement
python3 main.py --no-fluidsynth --no-sfizz    # sans les deux moteurs
```

ou, durablement, `"sfizz": false` / `"fluidsynth": false` dans
`data/config.json` (les options de lancement priment). Moteur coupé ou
bibliothèque absente : les slots Banque ou Synth SFZ sont gardés dans le
projet mais muets, la barre d'état le dit ; tout le reste marche, et les
tests qui dépendent du moteur sont sautés. Voir `docs/SPECS.md`
(Configuration, Instruments SFZ).

## 11. Mettre à jour sfizz plus tard

```sh
cd /home/com/build/sfizz
git pull --recurse-submodules        # (clone complet) ou reclonage
cmake --build build -j8
(cd tests && ../build/library/bin/sfizz_tests)
cmake --install build
python3 /home/com/backups/devel/claude_proj/groovyboxit/tools/sfizz_probe.py
```

Sur une autre plateforme (Windows, macOS), la même procédure CMake
s'applique, avec le compilateur du système ; la bibliothèque s'y appelle
`sfizz.dll` ou `libsfizz.dylib`.
