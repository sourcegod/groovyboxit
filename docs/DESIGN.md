# Design — GroovyboxIt

Historique des plans de conception discutés avant implémentation, chantier
par chantier. Complète `SPECS.md` (état d'avancement) et les commits (le
« comment ») en gardant la trace du « pourquoi » et des alternatives écartées.

---

## Phase 7 étape 1a — Standardisation de `TapeEvent`

### Origine du besoin

`TapeEvent = namedtuple("etype", "note", "vel", "dur", "bend")` (`pattern.py`)
traite GRID différemment de KIT/PATCH : la durée d'une note GRID vient de
`voice_manager.get_duration_ms(pad)` (réglage global de la voix, partagé par
toutes ses occurrences dans tout pattern qui utilise ce banc de voix), pas
d'un champ propre à l'événement — contrairement à KIT/PATCH où `dur` est un
champ par-événement. Ça a bloqué Numpad1/3 (raccourcir/rallonger une note
dans l'éditeur MIDI, Phase 6 étape 7d) sur les notes GRID.

Par ailleurs, un champ « canal » MIDI manque à tous les `etype` (utile pour
la conformité norme MIDI et un futur Import/Export MIDI).

Décision du 2026-07-24 : reporter volontairement ce chantier ("nettement
plus tard"), terminer l'étape 7 sans durée par-événement pour GRID,
documenter le manque, ne pas relancer tant que l'utilisateur ne le
redemande pas lui-même. Remis sur la table le 2026-09-17, juste après la
clôture de la Phase 6 étape 12a (refactorisation `midi_editor_window.py`).

### État des lieux constaté en code (2026-09-18)

- `_tape = {(track, bar, step): [TapeEvent, ...]}` — la position est la
  **clé du dict**, pas un champ de l'événement.
- `_bend_tape`/`_mod_tape` utilisent déjà un modèle différent : liste plate
  par piste de tuples `(offset_float, valeur)` — le temps est un **champ**,
  offset cumulé sur tout le pattern (`bar * num_steps + step`), pas un
  couple `(bar, step)` séparé.
- L'éditeur MIDI (`midi_editor.py`, mode « Tous les événements ») a déjà une
  3ᵉ représentation : des dicts `{"etype":, "pad"/"note":, "vel":, "dur":,
  "bend":...}` utilisés pour l'édition avant reconversion en `TapeEvent`.
- `dialogs_temporal.py` (`_EVT_TYPE_LABELS`) anticipe déjà 5 types futurs :
  CC générique, Program Change, Poly Aftertouch, Channel Pressure,
  SysEx/Meta — la nouvelle structure doit les accueillir sans nouveau
  refactor.
- 58 sites de construction/lecture de `TapeEvent`, répartis sur 6 fichiers
  source (`pattern.py`, `drum_player.py`, `track_editor.py`,
  `midi_editor.py`, `quantize_manager.py`, `ui/mw_project.py`) + 8 fichiers
  de tests.
- Aucun champ `channel` nulle part actuellement.

### Décisions de design validées

**1. Modèle de stockage `_tape`** → passer à des **listes plates par
piste**, alignées sur le modèle déjà utilisé par `_bend_tape`/`_mod_tape`
(temps = champ `time`, pas une clé de dict). `time` = offset flottant
cumulé sur tout le pattern, même convention que `_bend_tape`/`_mod_tape`.

Alternative écartée : garder le dict `{(track,bar,step): [...]}` en
ajoutant juste `channel` sur `TapeEvent` — changement minimal, mais `time`
resterait implicite (clé du dict), ce qui ne répond pas vraiment à la
demande d'un champ `time` uniforme sur tout événement.

Conséquence à traiter en implémentation : `get_cell`/`set_cell` (accès
grille 16×16, très fréquents côté UI) perdent le lookup O(1) par clé dict
direct. Prévoir un **index secondaire** `{(track, time): [événements]}`
maintenu à côté de la liste plate (reconstruit incrémentalement à
l'insertion/suppression, jamais recalculé en entier sauf
`copy_from`/`load_pattern`), pour ne pas introduire de régression de perf
sur la grille.

**Écart constaté à l'implémentation (étape 1c, 2026-09-19)** : l'index
secondaire n'a PAS été construit. Pendant 1c, l'analyse du vrai périmètre
(correctif 1b ci-dessous) a montré que `_tape` est pokée directement en
style dict par de nombreux fichiers (pas seulement via `get_cell`/`set_cell`)
— un index tenu à jour de façon incrémentale serait désynchronisé à chaque
poke direct externe (`pattern._tape[t].append(...)`, filtrage in-place,
etc.), ce qui aurait introduit des bugs de correction silencieux, pires
qu'une régression de perf. Choix fait : `get_cell`/`set_cell`/etc. font un
scan linéaire de la liste de la piste (`O(événements de la piste)` au lieu
de `O(1)`). Accepté comme compromis pragmatique pour une appli desktop
Python (pas de contrainte temps réel dur sur le rendu de grille) ; à
reconsidérer seulement si un vrai problème de perf est mesuré — la bonne
prochaine étape serait alors de centraliser les mutations de `_tape`
derrière une API `Pattern` unique (au lieu du style actuel où les fichiers
consommateurs accèdent à l'attribut directement) avant de pouvoir tenir un
index de façon sûre.

**2. Structure Python de l'événement** → **dataclass** avec champs communs
+ payload en dict :

```python
@dataclass
class TapeEvent:
    time: float                    # offset en steps cumulés (piste)
    etype: str                     # ETYPE_GRID / ETYPE_KIT / ETYPE_PATCH / futurs
    dur: float = 0
    channel: int = 0
    payload: dict = field(default_factory=dict)
    # ex. payload GRID:  {"pad": int, "vel": int}
    #     payload KIT:   {"note": int, "vel": int}
    #     payload PATCH: {"note": int, "vel": int, "bend": int}
    #     futurs CC/Aftertouch/SysEx : champs propres dans payload
```

Alternatives écartées : namedtuple élargi (s'alourdirait à chaque type
futur, champs `None` non pertinents selon le type) ; dict à deux niveaux
`{"time":, "payload": {...}}` (cohérent avec la représentation déjà
utilisée dans `midi_editor.py`, mais perd l'accès par attribut `ev.note`
utilisé partout ailleurs dans le code).

**3. Précédence durée GRID** → la **voix reste la référence par défaut**
(`dur=0`/`None` sur l'événement → fallback `voice_manager.get_duration_ms(pad)`
comme aujourd'hui) ; si l'événement porte une durée explicite (réglée via
Numpad1/3 dans l'éditeur), elle prime **pour cette occurrence uniquement**.
Rétrocompatible avec le comportement actuel (changer la durée du pad
change toujours toutes ses occurrences par défaut) et débloque Numpad1/3
sur GRID.

Alternative écartée : l'événement copie systématiquement la durée de la
voix à sa création — romprait le comportement actuel où changer la durée
du pad affecte toutes ses occurrences déjà posées.

**4. Identifiant unique `id` (ajouté 2026-09-19, demande explicite)** →
`TapeEvent` porte un `id` auto-incrémenté à la création (`TapeEvent._counter`,
même convention que `Pattern._id`). Décisions validées avec l'utilisateur :
- **Jamais préservé** lors d'une reconstruction représentant la même note
  modifiée (quantize déplace, resize retemporise, l'éditeur MIDI change
  durée/vélocité/pitch/position) : chaque construction obtient un id neuf,
  comme `Pattern._id` qui n'est jamais préservé non plus entre deux
  instances. Alternative écartée : préserver l'id à travers ces
  reconstructions pour une identité de note stable — aurait demandé de
  retoucher tous les sites qui reconstruisent un `TapeEvent` (quantize,
  resize, double_bars, édition), pour un besoin qui n'existe pas
  aujourd'hui (rien dans l'architecture actuelle ne dépend d'une identité
  stable across edits — les appelants se resynchronisent déjà via les
  dicts `event_info` retournés par les méthodes d'édition).
- **Jamais sérialisé** dans `.gvp`/`tape_v2` — identifiant de session
  uniquement, comme `Pattern._id`.
- `__eq__`/`__hash__` ignorent `id` (et `time`) : la comparaison reste par
  valeur, comme avant.
- Motivation explicite de l'utilisateur : une bonne partie du cœur
  audio/MIDI sera réimplémentée en C/C++ plus tard pour la performance —
  choisir des structures faciles à porter sans trop casser la
  compatibilité. Un entier auto-incrémenté est l'équivalent direct d'une
  clé d'entité dans une table/array C (`static uint64_t next_id; id =
  next_id++;`), contrairement par exemple à l'identité d'objet Python.
  Appliqué immédiatement : `drum_player.py` suivait les notes patch en
  cours d'enregistrement (`_pending_patch`, note_on → note_off) par
  identité d'objet Python (`is`) — remplacé par un suivi par `id`, qui a un
  sens dans un futur portage C/C++.
- Reste un point de vigilance général pour la suite du chantier (pas
  retouché aujourd'hui) : `payload` en dict Python (clé→valeur arbitraire)
  est un choix pratique côté Python mais n'a pas d'équivalent direct en C
  (qui préférerait une union taguée ou des champs fixes par type) — à
  garder en tête si/quand le portage C/C++ du cœur audio/MIDI est
  réellement entrepris, sans le anticiper inutilement maintenant.

### Portée explicitement exclue de ce chantier

Les nouveaux types eux-mêmes (CC générique, Program Change, Poly
Aftertouch, Channel Pressure, SysEx/Meta) ne sont **pas** dans le périmètre
de cette standardisation — juste s'assurer que la structure les accueille
sans nouveau refactor plus tard.

### Suite prévue (après ce chantier)

Revenir sur l'affichage de la liste d'événements de `MidiEditorWindow`
(mode Ctrl+2 « Tous les événements ») pour la mettre à jour — notamment le
format de ligne par type (note/CC/etc.) et le champ « canal », qui n'existe
pas encore dans le modèle actuel. Ne pas retravailler ce format avant que
cette standardisation soit faite.

---

## Phase 7 étape 1b — Format `.gvp` et découpage en commits

### Format `.gvp` (nouveau)

- Nouvelle clé `"tape_v2"` : liste par piste (même convention que
  `bend_tape`/`mod_tape`), chaque piste = liste d'événements
  `[time, etype, dur, channel, payload]`.
- `payload` est un dict JSON-natif : `{"pad": int, "vel": int}` pour GRID,
  `{"note": int, "vel": int}` pour KIT, `{"note": int, "vel": int, "bend":
  int}` pour PATCH.
- `to_dict()` n'écrit **plus** `curpattern`/`kit_tape`/`patch_tape` une fois
  la bascule faite — un seul format en écriture, pas de dual-write
  permanent.
- `from_dict()` : si `"tape_v2"` présent → chargement direct. Sinon (vieux
  fichier) → upgrade en mémoire depuis `curpattern`/`kit_tape`/`patch_tape`
  comme aujourd'hui, avec `channel=0` et la même règle `dur=0` pour GRID
  (fallback voix).

### Découpage en commits (version initiale — voir correction ci-dessous)

| Étape | Contenu | Fichiers/tests touchés |
|---|---|---|
| **1c** | `Pattern` : dataclass `TapeEvent` + `_tape` → liste plate par piste + index `{(track,time): [...]}` pour perf grille. API publique de `Pattern` inchangée en signature (aucun appelant externe cassé à ce stade). | `pattern.py`, `test_pattern.py`, `test_pattern_grid_api.py`, `test_pattern_properties_bug.py`, `test_tape.py` |
| **1d** | `to_dict`/`from_dict` : écriture `tape_v2`, lecture rétrocompat ancien format + test explicite de rétrocompat (charger un vieux dict/fichier). | `pattern.py` + fixture de test dédiée |
| **1e** | Migration des 5 consommateurs directs (`ev.note`/`ev.vel`/`ev.bend` → `ev.payload[...]`, nouveau `ev.channel`), un fichier à la fois, tests après chacun. | `drum_player.py`, `track_editor.py`, `midi_editor.py`, `quantize_manager.py`, `ui/mw_project.py` + `test_midi_editor.py`, `test_quantize.py`, `test_track_editor.py`, `test_transport.py` |
| **1f** | Brancher `channel` côté UI là où c'est pertinent (à évaluer une fois 1c-1e faits). | à déterminer |
| **1g** | Durée GRID par événement (override Numpad1/3) — le vrai déclencheur initial de ce chantier (étape 7d, 2026-07-24). | `midi_editor.py` + `mew_numpad.py` |

### Correction du découpage (2026-09-18, avant le début du code)

Au moment d'attaquer 1c, vérification de l'empreinte réelle de l'accès
direct à `_tape` en style dict (`_tape[(track,bar,step)]`, `.setdefault`,
`.items()`, `.get()`, `del`, `in`, `.pop()`, `.keys()`) — pas seulement les
appels au constructeur `TapeEvent(...)` comptés dans le tableau ci-dessus.
Résultat : bien plus large que prévu.

- **6 fichiers source** : `pattern.py`, `midi_editor.py`, `track_editor.py`,
  `quantize_manager.py`, `drum_player.py`, **`ui/mw_project.py`** (via
  `cb.tape` — presse-papier `TrackEditor`, même structure dict-keyée,
  non identifié dans le découpage initial).
- **7 fichiers de tests** : `test_pattern.py`, `test_pattern_grid_api.py`,
  `test_pattern_properties_bug.py`, `test_tape.py` (à lui seul ~90
  occurrences), `test_track_editor.py`, `test_midi_editor.py`,
  `test_quantize.py`.

Décision (2026-09-18) : élargir 1c à tous les fichiers source touchés par
le changement de stockage (pas seulement `pattern.py`), et séparer
clairement Implémentation / Tests à chaque étape — rythme déjà utilisé en
Phase 6 (ex. étapes 10e/10f, 11a-11c). `ev.note`/`ev.vel`/`ev.bend` restent
lisibles via des propriétés de compatibilité sur `TapeEvent` pendant la
transition (voir design de la dataclass ci-dessus) : la migration réelle
des accès (`ev.note` → `ev.payload["note"]`) dans les fichiers consommateurs
reste une étape séparée (1g), et n'est donc pas bloquée par l'élargissement
de 1c.

**Découpage en commits (version corrigée, à suivre) :**

| Étape | Contenu | Fichiers touchés |
|---|---|---|
| **1c** | Implémentation — `Pattern` : dataclass `TapeEvent` (constructeur compatible avec l'ancien positionnel + propriétés `note`/`vel`/`bend` de compat) + `_tape` → liste plate par piste + index `{(track,time): [...]}` ; adaptation des accès directs dict-style à `_tape`/`cb.tape` dans les 5 autres fichiers source touchés. Signatures publiques de `Pattern` inchangées. | `pattern.py`, `midi_editor.py`, `track_editor.py`, `quantize_manager.py`, `drum_player.py`, `ui/mw_project.py` |
| **1d** | Tests — adaptation des 7 fichiers de tests à la nouvelle structure de `_tape`/`cb.tape`. | `test_pattern.py`, `test_pattern_grid_api.py`, `test_pattern_properties_bug.py`, `test_tape.py`, `test_track_editor.py`, `test_midi_editor.py`, `test_quantize.py` |
| **1e** | Implémentation — `to_dict`/`from_dict` : écriture `tape_v2`, lecture rétrocompat ancien format. | `pattern.py` |
| **1f** | Tests — rétrocompat de chargement (vieux dict/fichier `.gvp`), tests `to_dict`/`from_dict`. | `test_pattern.py` + fixture dédiée |
| **1g** | Implémentation — migration réelle des consommateurs (`ev.note`/`ev.vel`/`ev.bend` → `ev.payload[...]`, `ev.channel`), suppression des propriétés de compat une fois tout migré. | `drum_player.py`, `track_editor.py`, `midi_editor.py`, `quantize_manager.py`, `ui/mw_project.py` |
| **1h** | Tests — ajustements suite à 1g. | fichiers de tests correspondants |
| **1i** | Implémentation — brancher `channel` côté UI. | à déterminer |
| **1j** | Tests — idem. | à déterminer |
| **1k** | Implémentation — durée GRID par événement (override Numpad1/3), le vrai déclencheur initial (étape 7d, 2026-07-24). | `midi_editor.py`, `mew_numpad.py` |
| **1l** | Tests — idem. | fichiers de tests correspondants |

### Avancement (mise à jour 2026-09-19)

1c–1j **FAITS** (commits `ed07a52` à `25b4aa7`, 1487 tests passed). 1i a
été précisé en deux passes avec l'utilisateur au moment de coder :
- Portée : capture (canal MIDI entrant, déjà parsé par `midi_manager.py`
  mais jeté par `midi_handler.py`) + affichage (liste Ctrl+2, remplace le
  placeholder `track+1`) + édition (`SpinCtrl` dans `_NoteEditDialog`/
  `_MidiEventEditDialog`).
- Numérotation 0-15 (pas 1-16), cohérente avec `midi_manager.py`/`note.py`.
  Pas d'option « tous les canaux » dans les dialogs d'édition (une note a
  toujours exactement un canal) ; pas de nouveau filtre canal dans
  `EventFilterDialog` ni d'UI pour `MidiManager.channel` (gap préexistant
  découvert en creusant, séparé de ce chantier).
- Bugs de perte de canal trouvés et corrigés en vérifiant la chaîne
  complète : `track_editor.py` `paste_events` et `ui/mw_project.py`
  `_clipboard_to_dict`/`_clipboard_from_dict`.

**1k/1l FAITS** (commits `45559cc`, `793489d`, 1497 tests passed) —
**chantier Phase 7 complet (1a–1l)**. `Pattern.set_cell` gagne `dur=0`
(0 = pas d'override) ; `midi_editor.py` expose `"dur"` (effective :
override sinon voix) et `"dur_override"` (brut, pour préservation à
travers les autres edits) ; `change_duration` accepte `ETYPE_GRID` en plus
de `ETYPE_KIT`/`ETYPE_PATCH` ; `drum_player.py` fait primer l'override sur
`voice_manager.get_duration_ms` à la lecture. Décision explicite :
`insert_note` (GRID) ne pose jamais d'override — seule l'édition d'une
note existante (Numpad1/3) en pose un, pour éviter qu'une simple insertion
écrase silencieusement le réglage de voix.

### Conformité avec le but final (Import/Export MIDI)

Vérifié le 2026-09-18, à la demande de l'utilisateur, que ce redesign sert
bien l'objectif final (non encore formalisé comme phase dans `SPECS.md`)
d'import/export de fichiers MIDI standard (SMF), sans refactoriser le
format général des données de `Pattern` au-delà du nécessaire :

- Un SMF stocke, par piste, des événements avec un **delta-time
  arbitraire** (ticks), jamais quantifié sur une grille fixe. Le modèle
  actuel de `_tape` (clé `(track,bar,step)`) force chaque événement sur une
  division de `num_steps` — incompatible avec un import fidèle d'un fichier
  à timing libre. `time` en champ flottant par événement (liste plate) est
  le changement minimal qui débloque ça.
- `channel` est un concept MIDI de premier niveau, nécessaire à l'import
  (préserver le canal d'origine) et à l'export.
- `payload` en dict permet à chaque type (CC, Program Change, Aftertouch,
  SysEx — déjà anticipés dans `dialogs_temporal.py`) de porter exactement
  ses propres champs.

Ce qui reste **hors périmètre** de ce chantier, pour un import/export MIDI
complet (à traiter plus tard, séparément) :
- Tempo/signature rythmique variables en cours de pattern (SMF permet des
  meta-événements tempo/signature à tout moment ; `Pattern` n'a qu'un
  BPM/signature unique) — nécessiterait une automation dédiée, sur le
  modèle `bend_tape`/`mod_tape`.
- Le mapping d'un fichier MIDI de durée/nombre de pistes arbitraires sur la
  structure fixe de Groovebox (99 patterns × 999 mesures × 8 pistes) — un
  sujet d'orchestration séparé, pas un sujet `TapeEvent`.
- Le codec SMF lui-même (lecture/écriture du fichier `.mid`) — pas encore
  implémenté, pas dans ce chantier.

Ce qui **ne change pas** dans `Pattern` (pas de refactor du format
général) : `num_bars`, `num_steps`, `bpm`, `voices`, loop points, structure
`Song`/`ProjectManager` — tous inchangés.

---

## Phase 7 étape 2a — Fondations d'un parser MIDI dédié (`midi_parser.py` + `midi_constants.py`)

### Origine du besoin

`EventFilterDialog` (`dialogs_temporal.py`) liste depuis longtemps 5 types
d'événements marqués « (à venir) » dans `_EVT_TYPE_LABELS` : CC générique,
Program Change, Poly Aftertouch, Channel Pressure, SysEx/Meta —
sélection bloquée (`_TYPES_TO_COME`, snap-back sur le dernier type valide).
[[project_event_list_window_todo]] notait déjà « reste reporté :
canal/CC arbitraire » (canal fait en Phase 7 étape 1i). L'utilisateur a
demandé de compléter ce filtre avec ces messages reportés.

### État des lieux constaté en code (2026-09-20)

Aucun des 5 types n'existe à un seul niveau de la chaîne aujourd'hui :

- **`midi_manager.py::_callback`** décode les octets bruts **inline**
  (pas de module dédié) et ne reconnaît que 4 types de statut MIDI :
  `0x90` (Note On), `0x80` (Note Off), `0xB0` (Control Change), `0xE0`
  (Pitch Bend). `0xC0` (Program Change), `0xA0` (Poly Aftertouch), `0xD0`
  (Channel Pressure) ne sont **pas reconnus** — messages silencieusement
  ignorés. Pire pour SysEx : `self._midi_in.ignore_types(sysex=True, ...)`
  est posé à l'ouverture du port — ces messages sont jetés par `rtmidi`
  **avant même** d'atteindre `_callback`.
- **CC générique** est le type le plus proche d'être prêt : le parsing
  `0xB0` existe déjà et `midi_handler.py::on_cc` reçoit **tout** `cc_num`,
  mais seuls CC#1/7/10/64/120/121/123 ont un effet câblé en dur, et seul
  CC#1 (mod wheel) est **enregistré** (dans `_mod_tape`, séparé de
  `_tape`). Un CC arbitraire reçu aujourd'hui ne fait rien et n'est jamais
  capturé.
- **Program Change** : aucune notion de « program » MIDI dans l'app (le
  `Rack` a des slots d'instrument, pas des program numbers GM) — aucun
  effet live possible, capture pure si implémenté.
- **Poly Aftertouch / Channel Pressure** : parsing absent ; incertain que
  le MPK mini Plus envoie même de l'aftertouch (à vérifier avant d'y
  investir du temps).
- **SysEx/Meta** : bloqué au niveau `rtmidi`, valeur d'usage la plus
  incertaine des 5 dans cette app (pas de sortie MIDI, pas de moteur
  consommateur).
- **Descriptions existantes** : `midi_handler.py` a déjà un dict
  `CC_NAMES` (partiel, noms CC standard MIDI 1.0) utilisé uniquement pour
  le statut MIDI live (`format_midi_status`/`_notify_editor_midi`).
  `synth_engine.py::midi_to_note_name` donne déjà les noms de note
  (`60 → "C4"`). Aucune table General MIDI (noms des 128 programs)
  n'existe nulle part — fournie par l'utilisateur pour ce chantier (voir
  Conception ci-dessous).

### Décision : construire un module `midi_parser.py` dédié, fondations d'abord

Décision de l'utilisateur (2026-09-20) : commencer par les **fondations
d'un parser MIDI** plutôt que par le branchement direct
capture/stockage/filtre. Proposition initiale de l'utilisateur pour la
taxonomie, reprise telle quelle :

```python
class CVoice:
    NoteOff               = 0x80
    NoteOn                = 0x90
    PolyphonicKeyPressure = 0xA0   # note aftertouch
    ControllerChange      = 0xB0
    ProgramChange         = 0xC0
    ChannelPressure       = 0xD0
    PitchBend             = 0xE0


class CMeta:
    FileMetaEvent              = 0xFF
    SMPTEOffsetMetaEvent       = 0x54
    SystemExclusive            = 0xF0
    SystemExclusivePacket      = 0xF7
    SequenceNumber             = 0x00
    TextMetaEvent              = 0x01
    CopyrightMetaEvent         = 0x02
    TrackName                  = 0x03
    InstrumentName             = 0x04
    Lyric                      = 0x05
    Marker                     = 0x06
    CuePoint                   = 0x07
    ChannelPrefix              = 0x20
    MidiPort                   = 0x21
    EndTrack                   = 0x2F
    SetTempo                   = 0x51
    TimeSignature              = 0x58
    KeySignature               = 0x59
    SequencerSpecificMetaEvent = 0x7F
```

`CMeta` reprend la taxonomie standard des méta-événements d'un fichier
MIDI (SMF) — ce qui confirme que ce module sert **double emploi** :
décodage des messages MIDI temps réel reçus aujourd'hui (`CVoice`), et
fondation pour la lecture/écriture d'un fichier `.mid` plus tard
(`CMeta`), sans dupliquer la taxonomie entre les deux usages.

**Portée retenue pour ce module** (ce que 2a couvre vraiment, vs. les
fondations posées sans implémentation) :

| Catégorie | Dans ce chantier | Détail |
|---|---|---|
| Notes | Description seulement | Réutilise `synth_engine.midi_to_note_name` (pas de duplication) ; le décodage `0x80`/`0x90` reste largement ce qui existe déjà. |
| CC (Control Change) | Parsing + descriptions | `CC_NAMES` déplacé (pas dupliqué) depuis `midi_handler.py`. |
| Program Change | Parsing nouveau + descriptions GM | Tables fournies par l'utilisateur (patchs mélodiques + kits GM2), voir Conception. |
| Pitch Bend | Parsing (déjà fait) centralisé | Décodage 14 bits déplacé dans le module dédié. |
| Poly Aftertouch, Channel Pressure | **Fondations seulement** | Constantes `CVoice` posées ; pas de décodage ni de capture dans ce chantier. |
| Meta, SysEx, Text | **Fondations seulement** | Constantes `CMeta` posées ; `ignore_types(sysex=True)` **pas retiré** dans ce chantier. |

### Conception

**Deux fichiers séparés** (données vs. logique) :

- **`src/midi_constants.py`** (nouveau) : tables de description pures,
  aucune dépendance. Contenu :
  - `CC_NAMES` : fusionné (déplacé, pas dupliqué) depuis
    `midi_handler.py`.
  - `GM_PATCH_NAMES` : 128 noms d'instruments General MIDI (liste fournie
    par l'utilisateur, `_gm_patch_lst` renommé selon la convention du
    projet).
  - `GM2_DRUMKIT_NAMES` : noms des kits de batterie GM2 par program
    number (liste fournie par l'utilisateur, `_gm2_drumkit` renommé) —
    seuls certains index ont un nom ; les autres restent l'entier
    lui-même (convention reprise telle quelle de la source fournie).
- **`src/midi_parser.py`** (nouveau) : logique de décodage, aucune
  dépendance à `rtmidi` ni `wx` — pur et testable unitairement sans port
  MIDI ni interface graphique (alternative écartée : garder le décodage
  inline dans `midi_manager.py::_callback` comme aujourd'hui — pas
  réutilisable pour un futur import `.mid`, pas testable isolément).
  - `CVoice`/`CMeta` : classes-namespaces de constantes, telles que
    proposées par l'utilisateur.
  - Fonction(s) de décodage bas niveau : prennent les octets bruts d'un
    message et retournent une structure décrivant le message (type,
    canal, données) — remplace la logique actuellement inline dans
    `MidiManager._callback` pour les 4 types déjà gérés, **plus**
    `ProgramChange` (nouveau).
  - Importe les tables de description depuis `midi_constants.py` (ne les
    redéfinit pas).
  - Note : `GM2_DRUMKIT_NAMES` n'est consulté que si l'appelant sait déjà
    qu'un canal/piste est un kit de batterie (typiquement canal 10) —
    `midi_parser.py` ne devine pas ça tout seul à ce stade ; c'est
    `describe_program(program, is_drum=False)` (ou équivalent) qui
    choisit la table.

### Intégration avec l'existant

- `midi_manager.py::_callback` délègue le décodage octet-par-octet à
  `midi_parser.py` ; garde la gestion de port `rtmidi`, le threading, le
  filtrage de canal (`self.channel`).
- Nouveau callback `on_program_change(program, chan)` (miroir de
  `on_note_on`/`on_cc`/`on_pitch_bend`), câblé dans `midi_handler.py`.
- `midi_handler.py::CC_NAMES` supprimé au profit de l'import depuis
  `midi_constants.py` (`format_midi_status` l'utilise déjà pour le statut
  live — comportement inchangé, juste la source de la table qui change).
- Program Change reçu : au minimum, statut live affiché (comme les autres
  types déjà gérés par `_notify_editor_midi`) ; la **capture/stockage**
  dans `_tape` (nouveau `ETYPE_PROGRAM_CHANGE`, payload `{"program": int}`,
  cohérent avec la conception `TapeEvent` de la Phase 7 1a-1l) et le
  branchement `EventFilterDialog`/affichage Ctrl+2 sont un **chantier
  séparé, ultérieur** (à numéroter une fois le parser posé — pas dans
  2a-2i).

### Portée explicitement exclue de ce chantier

- Retirer `ignore_types(sysex=True)` et décoder les SysEx.
- Décoder Poly Aftertouch / Channel Pressure.
- Décoder les méta-événements SMF (`CMeta`) — les constantes existent,
  rien ne les lit encore (utile seulement quand le codec `.mid`
  lecture/écriture sera entrepris).
- Câbler la capture (`_tape`), l'affichage (liste Ctrl+2) et le filtre
  (`EventFilterDialog`) de Program Change/CC générique — fondations du
  parser uniquement dans ce chantier ; le branchement est un chantier
  séparé qui suivra.

### Découpage en commits proposé (à valider avant de coder)

| Étape | Contenu | Fichiers |
|---|---|---|
| **2a** | Doc — ce plan. | `docs/DESIGN.md` |
| **2b** | Implémentation — `midi_constants.py` : `CC_NAMES` (fusionné), `GM_PATCH_NAMES`, `GM2_DRUMKIT_NAMES`. | `midi_constants.py` (nouveau) |
| **2c** | Tests — `midi_constants.py` (tailles de table, quelques valeurs connues). | `test_midi_constants.py` (nouveau) |
| **2d** | Implémentation — `midi_parser.py` : `CVoice`/`CMeta`, décodage bas niveau (Note On/Off, CC, Program Change, Pitch Bend), fonctions de description important `midi_constants.py`. | `midi_parser.py` (nouveau) |
| **2e** | Tests — `midi_parser.py` en isolation (pas de dépendance rtmidi/wx, tests purs sur des octets construits à la main). | `test_midi_parser.py` (nouveau) |
| **2f** | Implémentation — `midi_manager.py` délègue à `midi_parser.py` ; ajoute la reconnaissance `0xC0` + callback `on_program_change`. | `midi_manager.py` |
| **2g** | Tests — mise à jour/ajout pour la délégation + Program Change. | `test_midi_manager.py` |
| **2h** | Implémentation — `midi_handler.py` : câble `on_program_change` (statut live minimum), retire `CC_NAMES` local au profit de l'import. | `midi_handler.py` |
| **2i** | Tests — idem. | `test_midi_handler.py` |

Suite (hors périmètre 2a-2i, à renuméroter plus tard) : capture/stockage
de Program Change et CC générique dans `_tape` + branchement
`EventFilterDialog`/affichage Ctrl+2 — une fois le parser posé.

**2b-2i FAITS** (commits `2a98f2f`..`4382a9b`, 1549 tests passed) —
**chantier Phase 7 complet (2a-2i)**. `midi_constants.py` (CC_NAMES
déplacé, GM_PATCH_NAMES/GM2_DRUMKIT_NAMES = tables standard officielles,
faute de liste spécifique fournie — voir commit `2a98f2f`) ;
`midi_parser.py` (CVoice/CMeta, `decode_message` littéral,
`describe_note`/`describe_cc`/`describe_program`) ; `MidiManager._callback`
délègue à `decode_message` et reconnaît Program Change ; `MidiHandler`
câble `on_program_change` (statut live minimum, `_tape` hors périmètre).

---

## Phase 7 étape 3a — Réorganisation des fichiers MIDI (`src/midi/`)

### Origine du besoin

Après les étapes 2a-2j, 4 fichiers MIDI « cœur » (logique, hors UI)
cohabitent en vrac à la racine de `src/` avec des fichiers non-MIDI
(`pattern.py`, `synth_engine.py`, etc.) : `midi_constants.py`,
`midi_editor.py`, `midi_manager.py`, `midi_parser.py`. L'utilisateur
demande de les regrouper dans un nouveau dossier `src/midi/` pour mieux
ranger le code.

### Décision de scope (utilisateur, 2026-09-21)

- **4 fichiers déplacés** : `midi_constants.py`, `midi_editor.py`,
  `midi_manager.py` (inclus après clarification — même domaine « cœur
  MIDI non-UI » que les 3 cités initialement), `midi_parser.py`.
- **Fichiers `ui/*.py` liés au MIDI laissés en place** (`midi_handler.py`,
  `midi_editor_window.py`, `mw_midi_editor.py`, `midi_editor_dialogs.py`,
  `midi_virtual_keyboard.py`) : la convention existante range tout le GUI
  wx sous `src/ui/` indépendamment du domaine métier — pas de mélange
  UI/logique dans `src/midi/`.
- **Pas de renommage de fichier** : seul le dossier change
  (`src/midi_parser.py` → `src/midi/midi_parser.py`), même convention que
  `src/ui/` lors du refactor Phase 6 (fichiers déplacés tels quels).

### Conception : package `src/midi/`, imports absolus pointés

- Nouveau `src/midi/__init__.py` (vide) — même convention que
  `src/ui/__init__.py` (vide, package pur, pas de ré-export).
- Tous les imports vers ces 4 fichiers passent de la forme plate
  (`from midi_parser import X`, `import midi_manager as mm`) à la forme
  pointée `from midi.midi_parser import X`, `import midi.midi_manager as
  mm` — même convention que `src/ui/` (`from ui.midi_handler import
  MidiHandler`), **pas d'imports relatifs** (`.xxx`).
- Imports internes entre les 4 fichiers déplacés (`midi_parser.py` →
  `midi_constants.py`, `midi_manager.py` → `midi_parser.py`) : même forme
  pointée `from midi.midi_constants import ...`, pas de raccourci
  relatif — cohérent avec le style du reste du projet.

### État des lieux des importeurs (avant déplacement)

| Fichier déplacé | Importé par (code) | Importé par (tests) |
|---|---|---|
| `midi_constants.py` | `src/midi_parser.py`, `src/ui/midi_handler.py` | `tests/test_midi_constants.py` |
| `midi_parser.py` | `src/midi_manager.py`, `src/ui/midi_handler.py` | `tests/test_midi_parser.py` |
| `midi_manager.py` | `src/ui/main_window.py` | `tests/test_midi_manager.py` |
| `midi_editor.py` | `src/ui/midi_editor_window.py`, `src/ui/dialogs_temporal.py` (import local différé dans une méthode) | `tests/test_midi_editor.py`, `tests/test_midi_editor_filter.py` |

### Ordre de déplacement (dépendances internes)

`midi_constants.py` (aucune dépendance `midi_*`) → `midi_parser.py`
(dépend de `midi_constants`) → `midi_manager.py` (dépend de
`midi_parser`) → `midi_editor.py` (indépendant, dépend seulement de
`pattern.py` — déplacé en dernier, aucune contrainte d'ordre avec les 3
autres).

### Découpage en commits proposé (à valider avant de coder)

| Étape | Contenu | Fichiers |
|---|---|---|
| **3a** | Doc — ce plan. | `docs/DESIGN.md` |
| **3b** | Implémentation — `src/midi/__init__.py` + déplace `midi_constants.py` ; met à jour les imports non-tests (`src/midi_parser.py`, `src/ui/midi_handler.py`). | `src/midi/__init__.py` (nouveau), `src/midi/midi_constants.py` (déplacé), `src/midi_parser.py`, `src/ui/midi_handler.py` |
| **3c** | Tests — `tests/test_midi_constants.py` (import pointé `midi.midi_constants`), suite verte. | `tests/test_midi_constants.py` |
| **3d** | Implémentation — déplace `midi_parser.py` ; met à jour les imports non-tests (`src/midi_manager.py`, `src/ui/midi_handler.py`). | `src/midi/midi_parser.py` (déplacé), `src/midi_manager.py`, `src/ui/midi_handler.py` |
| **3e** | Tests — `tests/test_midi_parser.py` (import pointé), suite verte. | `tests/test_midi_parser.py` |
| **3f** | Implémentation — déplace `midi_manager.py` ; met à jour l'import non-test (`src/ui/main_window.py`). | `src/midi/midi_manager.py` (déplacé), `src/ui/main_window.py` |
| **3g** | Tests — `tests/test_midi_manager.py` (import pointé), suite verte. | `tests/test_midi_manager.py` |
| **3h** | Implémentation — déplace `midi_editor.py` ; met à jour les imports non-tests (`src/ui/midi_editor_window.py`, `src/ui/dialogs_temporal.py`). | `src/midi/midi_editor.py` (déplacé), `src/ui/midi_editor_window.py`, `src/ui/dialogs_temporal.py` |
| **3i** | Tests — `tests/test_midi_editor.py`, `tests/test_midi_editor_filter.py` (imports pointés), suite verte. | `tests/test_midi_editor.py`, `tests/test_midi_editor_filter.py` |
| **3j** | Implémentation — renomme `src/ui/midi_handler.py` en `src/ui/midi_handler_window.py` ; met à jour l'import non-test (`src/ui/main_window.py`). | `src/ui/midi_handler_window.py` (déplacé), `src/ui/main_window.py` |
| **3k** | Tests — renomme `tests/test_midi_handler.py` en `tests/test_midi_handler_window.py` (import pointé), suite verte. | `tests/test_midi_handler_window.py` (déplacé) |
| **3l** | Doc — chantier complet (3a-3k). | `docs/DESIGN.md` |

**Extension de scope (décision utilisateur, 2026-09-21)** : une fois
les 4 fichiers regroupés sous `src/midi/`, `src/midi/midi_manager.py`
et `src/ui/midi_handler.py` sont apparus comme deux noms trop proches
pour être distingués d'un coup d'œil (aucune collision réelle — modules
`midi.midi_manager` et `ui.midi_handler` distincts — mais confusion
plausible). Décision : renommer `src/ui/midi_handler.py` en
`src/ui/midi_handler_window.py` (3j/3k, ajoutés après coup). Seul le
nom de fichier change — la classe `MidiHandler` et l'attribut
`win._midi_handler` ne sont pas renommés (hors scope, aucune ambiguïté
sur ces deux-là).

**Remarque sur les commits impl-only (3b/3d/3f/3h)** : chaque commit
d'implémentation laisse volontairement le(s) fichier(s) de test
correspondant(s) rouge(s) (`ModuleNotFoundError` sur l'ancien import
plat) jusqu'au commit Tests qui suit immédiatement — titré en
conséquence (« travail incomplet — tests à suivre »), même convention
que Phase 7 étape 1k (commit `45559cc`). La suite complète (`pytest
tests/`) n'est vérifiée verte qu'à l'issue de chaque paire impl+tests,
jamais laissée rouge entre deux paires distinctes.

### Portée explicitement exclue de ce chantier

- Renommer les 4 fichiers déplacés eux-mêmes (ex. `midi_parser.py` →
  `parser.py`) : seul le dossier change. Ne s'applique pas à
  `src/ui/midi_handler.py` → `midi_handler_window.py` (3j/3k) : ce
  fichier n'est pas déplacé, seulement renommé, pour lever l'ambiguïté
  avec `src/midi/midi_manager.py` (voir Extension de scope ci-dessus).
- Déplacer les fichiers MIDI de `src/ui/` (`midi_handler_window.py`,
  `midi_editor_window.py`, `mw_midi_editor.py`, `midi_editor_dialogs.py`,
  `midi_virtual_keyboard.py`) : restent sous `src/ui/` (décision
  utilisateur).
- Toute modification de comportement : chantier de rangement pur, aucun
  changement fonctionnel attendu (suite de tests inchangée en
  nombre/contenu, seuls les imports changent).

**3b-3k FAITS** (commits `c0e88af`..`9fe5055`, 1549 tests passed) —
**chantier Phase 7 complet (3a-3l)**. `midi_constants.py`,
`midi_parser.py`, `midi_manager.py`, `midi_editor.py` regroupés sous
`src/midi/` (nouveau package, `src/midi/__init__.py` vide) ; tous les
imports pointent `midi.midi_xxx`, aucun import plat résiduel.
`src/ui/midi_handler.py` renommé en `midi_handler_window.py` (3j/3k,
extension de scope décidée en cours de chantier) pour lever
l'ambiguïté avec `src/midi/midi_manager.py` — classe `MidiHandler` et
attribut `win._midi_handler` inchangés. Comportement inchangé
(rangement/renommage purs), suite verte à l'issue de chaque paire
impl+tests.

Point de process noté : le commit `83c2e38` (3k) a d'abord manqué 2
lignes (docstring + import) à cause d'un `git add -A <chemins
explicites>` lancé juste après un `git mv` sans re-vérifier le statut —
la suite tournait verte sur le fichier de travail non committé,
masquant l'écart. Corrigé par un commit correctif immédiat (`9fe5055`)
plutôt qu'un `--amend`. Réflexe à prendre : après `git mv` + édition,
toujours `git status`/`git diff HEAD` avant de committer, pas seulement
lancer la suite de tests.

---

## Phase 7 étape 4a — Capture, filtre et affichage de CC générique / Program Change

### Origine du besoin

Suite directe de [[project_midi_parser_todo]] (2a-2j, parser dédié) et
[[project_midi_files_reorg]] (3a-3l, rangement sans lien fonctionnel).
`midi_manager.py`/`midi_parser.py` reconnaissent déjà Program Change
(`on_program_change`) et tout Control Change (`on_cc`) — mais aucun des
deux n'est capturé dans `_tape`, ni filtrable dans `EventFilterDialog`
(`_TYPES_TO_COME` bloque encore leurs entrées), ni affiché dans la liste
Ctrl+2. Décidé en 2a : « branchement capture/stockage/filtre : chantier
séparé, ultérieur » (voir docs/DESIGN.md § Phase 7 étape 2a, section
« Intégration avec l'existant »). C'est ce chantier.

### État des lieux constaté en code (2026-09-21) — un piège identifié

Un `else` catch-all traite aujourd'hui silencieusement **tout** etype de
`_tape` différent de `ETYPE_GRID`/`ETYPE_KIT` comme un `ETYPE_PATCH` :

- `drum_player.py` (~L474, boucle de lecture) : `else: events.append((…
  self.PATCH_TAPE_EVENT, (t_idx, ev.payload.get("note"), …,
  ev.payload.get("bend", 0)), …))`. Un `ETYPE_PGM`/`ETYPE_CC` non
  reconnu explicitement y serait lu comme une note PATCH avec
  `note=None`, `bend=0` — au mieux un événement fantôme silencieux, au
  pire un plantage en aval (`TrackRouter.on_patch_tape` attend un
  `midi_note` entier).
- `midi/midi_editor.py::get_note_events` (~L72) : même `else`, avec en
  plus `events.sort(key=lambda e: (e["offset"], e["pad"]))` (L88) — un
  `pad=None` ferait lever un `TypeError` dès qu'il faut comparer `None`
  à un entier (liste mixte).
- `ui/mw_project.py::_clipboard_to_dict`/`_clipboard_from_dict`
  (~L274-309, presse-papier `TrackEditor` cross-pattern Ctrl+C/X/V) :
  même schéma `if GRID / elif KIT / else PATCH`.

Chaque nouveau etype introduit ici **doit** donc remplacer ces `else`
par un `elif ETYPE_PATCH` explicite avant d'ajouter ses propres
branches — pas une option, un correctif de sécurité préalable.

Points sans piège (déjà sûrs par inclusion, pas par exclusion) :
`quantize_manager.py` (`if etype not in (KIT, PATCH): continue`) et
`track_editor.py::paste_events` (`elif etype in (KIT, PATCH)`) ignorent
déjà silencieusement tout etype inconnu — pas de correctif requis, mais
CC/Program Change y resteront non quantifiables et non collables via
Ctrl+V « niveau événement » (`copy_events`/`paste_events`) tant qu'ils
n'y sont pas explicitement ajoutés (voir Portée exclue).

### Décisions validées (utilisateur, 2026-09-21)

1. **CC#1 dupliqué, migration notée pour plus tard.** Le nouveau
   « CC générique » capture **tous** les CC reçus, y compris CC#1 — en
   plus de `_mod_tape` (qui continue, inchangé, à piloter le vibrato en
   lecture via `on_mod_tape`). Doublon assumé : `_mod_tape` est
   candidat à être remplacé par une lecture de `_tape`/`ETYPE_CC`
   filtrée sur `cc_num==1` dans un chantier ultérieur (non fait ici).
2. **Effet réellement rejoué à la lecture (Play), pas seulement une
   capture passive** — pour CC générique **et** pour Program Change.
   Revient sur la position prise en 2a (« aucun effet live possible »
   pour Program Change) : c'était une simplification volontaire pour
   avancer sur les fondations du parser, pas une limite définitive.
   Décision révisée (2026-09-21) : en attendant le vrai mode Rack
   Synth/GM (16 canaux MIDI → 16 slots avec leurs patchs, lecture de
   fichiers `.mid` — chantier futur distinct, motivant de garder la
   souplesse du format MIDI, qui peut envoyer un Program Change à tout
   moment), Program Change pilote **provisoirement** le `Rack` existant
   à 16 slots :
   - CC générique capturé → même effet que sa réception live via
     `on_cc` (volume/pan/sustain/mod wheel/all-notes-off/all-sounds-off/
     reset), appliqué à la piste d'origine (pas à la piste/pad ayant le
     focus UI — cette notion de focus n'existe pas pendant la lecture).
   - Program Change (live **et** rejoué à la lecture) → réassigne le
     slot du `Rack` de la piste concernée : `TrackRouter.assign_slot(
     track_idx, program % 16)` (`assign_slot` existe déjà — chargement
     du `SynthEngine`/patch en tâche de fond si le slot est SYNTH, non
     bloquant). Valeurs 16-127 repliées par modulo 16 en attendant le
     vrai adressage par canal du futur mode GM. Live : cible la piste
     courante (`win._player._cur_track`, comme les autres effets CC
     live) ; lecture : cible `track_idx`, la piste d'origine de
     l'événement (comme `on_cc_tape`).
3. **Édition via Entrée (Ctrl+2) incluse dans ce chantier**, en
   réutilisant `_CcEventEditDialog` (déjà utilisé pour bend/mod) :
   valeur éditable pour CC générique et pour Program Change ; le numéro
   de CC (`cc_num`) reste non éditable dans ce chantier (seule sa
   valeur l'est, comme le pad/note n'est pas éditable pour bend/mod
   aujourd'hui).
4. **Groupe de plage dédié dans `EventFilterDialog`**, symétrique à
   Pitch Bend : un groupe « CC générique » (Numéro CC Bas/Haut + Valeur
   Bas/Haut, sur le modèle Notes qui combine déjà deux paires
   Note/Vélocité) et un groupe « Program Change » (Program Bas/Haut,
   sur le modèle Pitch Bend à une seule paire).

### Conception

**Deux nouveaux etypes dans `_tape`** (pattern.py), cohérents avec la
conception `TapeEvent` unifiée de la Phase 7 1a-1l — pas de structure
parallèle façon `_bend_tape`/`_mod_tape` :

```python
ETYPE_CC  = "CC"    # payload {"cc_num": int, "value": int}, dur=0
ETYPE_PGM = "PGM"   # payload {"program": int},              dur=0
```

Pas de dédoublonnage à la capture (contrairement à
`record_kit_note`/`record_patch_note` qui évitent les doublons exacts à
la même position) : deux CC de même valeur au même tick sont des
données valides (un contrôleur physique peut légitimement renvoyer deux
fois la même valeur), donc simple `append`.

**Capture** (`drum_player.py`, miroir de `record_kit_note`) :
- `record_cc(cc_num, value, channel=0)` → `TapeEvent(ETYPE_CC, …)`
  append dans `_tape[cur_track]`.
- `record_program_change(program, channel=0)` → `TapeEvent(ETYPE_PGM,
  …)` append dans `_tape[cur_track]`.

Branchées dans `midi_handler_window.py` :
- `on_cc` : ajoute `if win._player.recording:
  win._player.record_cc(cc_num, value, channel)`, **avant ou après**
  les branches d'effet existantes (7/10/64/120/121/123/1) — celles-ci
  restent inchangées pour la réception live, la capture est
  orthogonale.
- `on_program_change` : ajoute l'appel `record_program_change`
  équivalent, **et** l'effet live (décision 2 révisée) :
  `win._router.assign_slot(win._player._cur_track, program % 16)` —
  le commentaire actuel (« aucun effet live possible, capture pure »)
  est obsolète et à retirer.

**Lecture (rejeu de l'effet, décision 2)** — deux nouveaux marqueurs
internes `DrumPlayer.CC_TAPE_EVENT`/`PGM_TAPE_EVENT`, deux nouveaux
callbacks `_on_cc_tape_cb`/`_on_program_change_tape_cb` (même
convention que `_on_bend_tape_cb`), wirés dans `main_window.py` vers
deux nouvelles méthodes `TrackRouter.on_cc_tape`/`on_program_change_tape` :
- `on_cc_tape(track_idx, cc_num, value)` : CC#64/120/121/123 → effet
  global (sustain/all sounds off/reset/all notes off), indépendant de
  `track_idx`. CC#1 → délègue à `on_mod_tape` existant (même moteur
  cible que le vibrato live). CC#7/10 → `set_track_volume`/
  `set_track_pan` **de `track_idx`** (pas de piste focus à la lecture).
  Piste non audible (`_track_is_audible`) → ignoré, sauf les 4 effets
  globaux.
- `on_program_change_tape(track_idx, program)` : `assign_slot(track_idx,
  program % 16)` (décision 2 révisée) — même appel que l'effet live,
  ciblant la piste d'origine de l'événement plutôt que la piste
  courante.

**Filtre/sélection/affichage** — le point délicat est `event_idx` :
`_delete_tape_event`/`edit_tape_note` le résolvent comme *position
parmi tous les événements de `_tape[track]` au même `time`, tous etypes
confondus* (`matches = [i for i,e in enumerate(track_list) if e.time ==
time]`), exactement la construction déjà faite par
`get_note_events::by_time`. Pour que CC/PGM restent éditables/
supprimables avec la même convention d'index, `get_all_events` ne doit
**pas** re-scanner `_tape[t]` indépendamment pour CC/PGM (ça
recalculerait un `event_idx` local à CC/PGM seul, incohérent avec
`_delete_tape_event`) : il doit dériver ses entrées "cc"/"pgm" de la
**même** construction `by_time` que `get_note_events`, avec le même `i`
partagé entre tous les etypes présents à cet offset.
→ Refactor proposé : extraire de `get_note_events` la construction
`by_time` (groupement `_tape[track_idx]` par `.time`, tous etypes) dans
un petit helper privé partagé, réutilisé par `get_note_events` (filtre
GRID/KIT/PATCH, comportement inchangé) et par une nouvelle collecte
CC/PGM appelée depuis `get_all_events` (filtre CC/PGM, même `i`).

Nouveaux champs d'event dict : `{"type": "cc", "track", "bar", "step",
"offset", "cc_num", "value", "channel", "event_idx"}` et `{"type":
"pgm", "track", "bar", "step", "offset", "program", "channel",
"event_idx"}`.

`MidiEditor` : deux nouvelles méthodes `edit_cc_event`/`edit_pgm_event`
(miroir de `edit_tape_note`, retrouvent l'événement via
`time`+`event_idx` dans `_tape[track]`, remplacent `value`/`program`
et/ou repositionnent). `delete_event` couvre déjà CC/PGM sans
changement (`_delete_tape_event` est générique par `event_idx`).

**Correction en cours de chantier (4i)** : la phrase ci-dessus était
fausse — `delete_event` commence par `if ev.get("type") != "note":
return False`, donc un CC/PGM était rejeté avant même d'atteindre
`_delete_tape_event` (lui bien générique). Corrigé en 4i : dispatch sur
`ev["type"]`, les types `"cc"`/`"pgm"` passant par `_delete_tape_event`
comme les notes KIT/PATCH.

`filter_events` : nouvelles clés critères `cc_num_lo/hi`, `cc_val_lo/hi`,
`pgm_lo/hi` ; nouvelles branches `e["type"] == "cc"`/`"pgm"` bornées en
plus du test `etype_filter`.

`EventFilterDialog` (`dialogs_temporal.py`) : `_EVT_TYPE_LABELS`
perd ses deux entrées « (à venir) » pour CC générique/Program Change
(sortent de `_TYPES_TO_COME`, qui garde Poly Aftertouch/Channel
Pressure/SysEx-Meta) ; nouveaux `_TYPE_CC`/`_TYPE_PGM` + entrées
`_TYPE_KEY` ; deux nouveaux `StaticBoxSizer` (« CC générique » : Numéro
CC Bas/Haut + Valeur Bas/Haut ; « Program Change » : Program Bas/Haut),
activés/désactivés dans `_update_group_enabled` comme les groupes
existants ; `_type_unavailable` étendu pour bloquer aussi CC/PGM en
mode Notes (`view_mode == 0`), comme Bend/Mod aujourd'hui.

`mew_display.py` (`_event_label_all`, liste Ctrl+2) : deux nouvelles
branches `elif e["type"] == "cc"`/`"pgm"` (format `"Canal {ch}, CC,
Numéro {cc_num}, Valeur {value}"` / `"Canal {ch}, Program Change,
Program {program} ({nom GM si connu via describe_program})"` —
réutilise `midi.midi_parser.describe_program`, pas de table dupliquée).

`mew_editing.py::_edit_note_dialog` : le test `ev.get("type") in
("bend", "mod")` devient `("bend", "mod", "cc", "pgm")`, délégué à
`_edit_cc_dialog` généralisé (dispatch par `ev["type"]` plutôt que le
booléen `is_bend` actuel, vers `edit_bend_event`/`edit_mod_event`/
`edit_cc_event`/`edit_pgm_event`).

`midi_editor_dialogs.py::_CcEventEditDialog` : `is_bend` (booléen)
remplacé par dispatch sur `ev["type"]` (4 branches titre+label+bornes ;
CC générique reprend les bornes 0-127 déjà utilisées pour Mod, Program
Change ajoute une borne 0-127 avec le libellé « Program »).

**Persistance (`.gvp`) et presse-papier `TrackEditor`** :
- `pattern.py::to_dict`/`from_dict` sérialisent déjà `_tape` de façon
  générique par `TapeEvent` (etype/dur/channel/payload) — à vérifier
  qu'aucun filtre implicite sur les 3 etypes existants n'y traîne
  (lecture rapide du code de sauvegarde needed avant 4h, voir
  découpage).
- `ui/mw_project.py::_clipboard_to_dict`/`_clipboard_from_dict` : le
  `else → PATCH` (piège identifié plus haut) devient `elif ETYPE_PATCH`
  + deux nouvelles branches CC/PGM (format `[ETYPE_CC, t, b, s, cc_num,
  value, channel]` / `[ETYPE_PGM, t, b, s, program, channel]`).

### Portée explicitement exclue de ce chantier

- Éditer `cc_num` d'un événement CC générique existant (seule sa valeur
  l'est, décision 3).
- Migrer `_mod_tape`/`on_mod_tape` pour qu'il lise `_tape`/`ETYPE_CC`
  au lieu de sa structure dédiée (doublon CC#1 assumé, décision 1) —
  chantier ultérieur distinct.
- Le vrai mode Rack Synth/GM (adressage par canal MIDI plutôt que par
  piste, lecture de fichiers `.mid` sur 16 canaux avec leurs patchs) —
  `assign_slot(track_idx, program % 16)` n'est qu'un pont provisoire
  vers le `Rack` existant (décision 2 révisée), pas ce mode complet.
- `copy_events`/`paste_events` (presse-papier « niveau événement »,
  Ctrl+C/V dans la liste Ctrl+2, distinct du presse-papier
  `TrackEditor`) : reste limité à `ETYPE_GRID`/`KIT`/`PATCH` comme
  aujourd'hui — CC/PGM non copiables-collables à ce niveau dans ce
  chantier (silencieusement ignorés par le filtre `in (ETYPE_KIT,
  ETYPE_PATCH)` existant, pas de régression, juste pas d'extension).
- Quantisation (`quantize_manager.py`) de CC/PGM — reste hors du filtre
  `(ETYPE_KIT, ETYPE_PATCH)` existant, sans changement.
- Poly Aftertouch / Channel Pressure / SysEx-Meta — toujours hors
  périmètre (constantes `CVoice`/`CMeta` posées en 2a, décodage non
  fait), restent dans `_TYPES_TO_COME`.

### Découpage en commits proposé (à valider avant de coder)

| Étape | Contenu | Fichiers |
|---|---|---|
| **4a** | Doc — ce plan. | `docs/DESIGN.md` |
| **4b** | Implémentation — `pattern.py` : `ETYPE_CC`/`ETYPE_PGM` ; vérifie que `to_dict`/`from_dict` les sérialisent sans changement (générique par construction). | `pattern.py` |
| **4c** | Tests — `pattern.py` (round-trip `to_dict`/`from_dict` avec un `TapeEvent` CC et un PGM). | `test_pattern.py` |
| **4d** | Implémentation — `drum_player.py` : `record_cc`/`record_program_change` ; corrige le piège `else→PATCH` de la boucle de lecture (`elif ETYPE_PATCH` explicite) ; ajoute `CC_TAPE_EVENT`/`PGM_TAPE_EVENT` + callbacks. | `drum_player.py` |
| **4e** | Tests — capture (`record_cc`/`record_program_change`) + non-régression boucle de lecture (un `ETYPE_PGM`/`ETYPE_CC` dans `_tape` ne casse plus la lecture d'un `ETYPE_PATCH` voisin). | `test_pattern.py` ou nouveau `test_drum_player_cc.py` |
| **4f** | Implémentation — `midi_handler_window.py` : branche `record_cc`/`record_program_change` dans `on_cc`/`on_program_change`, **et** l'effet live Program Change (`assign_slot(cur_track, program % 16)`). | `midi_handler_window.py` |
| **4g** | Implémentation — `track_router.py` + `main_window.py` : `on_cc_tape`/`on_program_change_tape` (celui-ci appelle aussi `assign_slot`), wiring des callbacks. | `track_router.py`, `main_window.py` |
| **4h** | Tests — `on_cc_tape` (volume/pan/sustain/mod/all-notes-off/all-sounds-off/reset appliqués correctement, piste non audible ignorée sauf effets globaux) ; `on_program_change_tape` (`assign_slot` appelé avec le bon slot, modulo 16) ; effet live Program Change dans `on_program_change`. | `test_track_router.py`, `test_midi_handler_window.py` |
| **4i** | Implémentation — `midi_editor.py` : refactor `by_time` partagé, `get_note_events` restreint à GRID/KIT/PATCH, collecte CC/PGM dans `get_all_events` (même `event_idx`), `filter_events` étendu, `edit_cc_event`/`edit_pgm_event`. | `midi/midi_editor.py` |
| **4j** | Tests — `get_all_events` (event_idx cohérent avec un GRID+CC au même offset), `filter_events` (cc/pgm), `edit_cc_event`/`edit_pgm_event`, `delete_event` sur CC/PGM. | `test_midi_editor.py` |
| **4k** | Implémentation — `dialogs_temporal.py` (`EventFilterDialog`) : sort `_TYPES_TO_COME`, groupes CC générique/Program Change, `_type_unavailable`. | `ui/dialogs_temporal.py` |
| **4l** | Tests — `EventFilterDialog` (sélection type CC/PGM disponible, groupes activés/désactivés, critères transmis). | `test_*` (dialog existant) |
| **4m** | Implémentation — `mew_display.py` (labels Ctrl+2), `mew_editing.py` (dispatch 4 types), `midi_editor_dialogs.py` (`_CcEventEditDialog` généralisé). | `ui/mew_display.py`, `ui/mew_editing.py`, `ui/midi_editor_dialogs.py` |
| **4n** | Tests — affichage Ctrl+2 (labels CC/PGM), édition via Entrée (valeur CC, valeur Program). | `test_midi_editor_window.py` |
| **4o** | Implémentation — `mw_project.py` : corrige le piège `else→PATCH` du presse-papier `TrackEditor` (`elif ETYPE_PATCH` + branches CC/PGM). | `ui/mw_project.py` |
| **4p** | Tests — presse-papier `TrackEditor` (Ctrl+C/X/V) avec un CC/PGM dans la plage copiée. | `test_track_editor.py` |
| **4q** | Doc — mise à jour mémoire (chantier clos), `pytest tests/` complet vérifié vert. | — |

**4b-4q FAITS** (commits `8547793`..`c309bac`, 1649 tests passed) —
**chantier Phase 7 étape 4 complet**. CC générique et Program Change sont
capturés dans `_tape` (`ETYPE_CC`/`ETYPE_PGM`), rejoués à la lecture avec
leur effet réel, filtrables par type et par plage (numéro/valeur de CC,
numéro de program), affichés dans la liste Ctrl+2 avec leur vrai canal et
leur nom MIDI/GM, éditables par Entrée, et traversent la sérialisation
`.gvp` (pattern et presse-papier `TrackEditor`). Suite verte à l'issue de
chaque paire impl+tests.

Les **trois pièges `else → PATCH`** annoncés en tête de ce plan ont tous
été corrigés avant d'introduire les nouveaux etypes : `drum_player.py`
(boucle de lecture, 4d), `midi/midi_editor.py::get_note_events` (4i) et
`ui/mw_project.py` (presse-papier, 4o). Deux corrections de plan notées en
cours de route : `delete_event` ne couvrait pas CC/PGM contrairement à ce
qu'affirmait la section Conception (corrigé en 4i, voir la note dédiée), et
l'effet live de Program Change a été décidé après coup (décision 2
révisée) alors que 2a l'avait écarté.

Point de conception à retenir pour la suite : `event_idx` compte parmi
**tous** les etypes d'une même position de `_tape`. C'est pour ça que les
notes et les CC/PGM dérivent du même helper `_events_by_time` — toute
nouvelle famille d'etype ajoutée à `_tape` devra faire pareil, sous peine
de viser le mauvais événement à la suppression/édition.

---

## Phase 7 étape 5a — Migration `_mod_tape` → `_tape`/`ETYPE_CC` (CC#1)

### Origine du besoin

Décision 1 de la Phase 7 étape 4a : CC#1 (Mod Wheel) est capturé **deux
fois** depuis l'étape 4f — dans `_mod_tape` (structure historique dédiée)
et dans `_tape` sous forme d'`ETYPE_CC` `cc_num=1`. Doublon assumé à
l'époque, migration notée comme chantier ultérieur (demandée le
2026-10-15). But : une seule source de vérité pour le mod wheel, comme
GRID/KIT/PATCH l'ont déjà pour les notes.

### État des lieux constaté en code (2026-10-16, 1649 tests verts)

**Où vit `_mod_tape`** (liste par piste de tuples `(float_offset, value)`,
pas de `TapeEvent`, pas de canal) :
- `pattern.py` : `__init__` (L161), `copy_from`, `new_pattern`,
  `reset_pattern`, `clear_track`, `double_bars`, `halve_bars`, `resize`,
  `to_dict` (clé `"mod_tape"`), `from_dict` (lecture tolérante, clé
  absente → listes vides).
- `drum_player.py` : `MOD_TAPE_EVENT = -5`, `_on_mod_tape_cb`, boucle
  `_run_thread` qui construit les `MOD_TAPE_EVENT` (L495-501) et les
  dispatche (L569-572), `record_mod()` (L1053).
- `ui/main_window.py:132` : `_on_mod_tape_cb = self._router.on_mod_tape`.
- `ui/midi_handler_window.py::on_cc` : `record_cc` pour **tous** les CC
  (L213), **plus** `record_mod(value)` dans la branche CC#1 (L238).
- `track_editor.py::_erase_tape_range` : efface la plage dans `_mod_tape`.
- `midi/midi_editor.py` : `get_all_events` produit des entrées
  `type="mod"` depuis `_mod_tape` en plus des `type="cc"` depuis `_tape`
  (donc **chaque mouvement de molette apparaît deux fois** dans Ctrl+2) ;
  `edit_mod_event` ; `filter_events` (`etype_filter="mod"`) ;
  `delete_event` ne gère pas `"mod"` (point mod non supprimable, alors
  que son jumeau `"cc"` l'est depuis 4i).
- UI : `mew_display.py` (2 branches `"mod"`), `mew_editing.py` (dispatch
  `"mod"` → `edit_mod_event`), `midi_editor_dialogs.py::_CcEventEditDialog`
  (branche `"mod"`), `dialogs_temporal.py::EventFilterDialog` (`_TYPE_MOD`,
  entrée « Mod Wheel (CC1) »).
- Tests : ~20 tests `_mod_tape` dans `test_tape.py` (L1401-1643), plus
  `test_pattern_properties_bug.py`, `test_pattern_grid_api.py`,
  `test_track_editor.py`, `test_midi_editor.py`, `test_midi_editor_filter.py`,
  `test_cc_event_edit_dialog.py`, `test_midi_editor_window.py`,
  `test_event_filter_dialog.py`.

**Lecture : CC#1 déjà rejoué deux fois.** `TrackRouter.on_cc_tape` délègue
CC#1 à `on_mod_tape` (4g) ; la boucle rejoue donc chaque point une fois
via `MOD_TAPE_EVENT` et une fois via `CC_TAPE_EVENT`. Inoffensif (même
valeur, même moteur) mais confirme que `_tape` suffit déjà à piloter le
vibrato : supprimer `MOD_TAPE_EVENT` ne demande **aucun** changement dans
`TrackRouter`.

**Le vrai piège : la résolution temporelle.** Les deux copies n'ont pas
la même précision :
- `record_mod` (comme `record_bend`) stocke l'offset **flottant brut**
  (sous-pas), jamais quantifié.
- `record_cc` passe par `_compute_record_offset` et stocke
  `_bar_step_to_time(bar_idx, step_idx)` — un **pas entier**, arrondi au
  plus proche, et en plus quantifié à la grille si
  `_quant_in_recording` est actif.

Conséquence : un balayage de molette (des dizaines de valeurs par pas)
est aujourd'hui fidèle dans `_mod_tape`, mais tassé sur la copie
`ETYPE_CC` : tous les points d'un même pas tombent au même instant à la
lecture → seule la dernière valeur est audible, effet « escalier ».
Supprimer `_mod_tape` sans traiter ça serait une **régression audible**.

Or plusieurs chemins supposent aujourd'hui un `TapeEvent.time` entier, et
perdraient ou rateraient une partie fractionnaire :
- `MidiEditor._delete_tape_event` / `_replace_tape_event` : retrouvent
  l'événement par `time = _bar_step_to_time(ev["bar"], ev["step"])` puis
  `e.time == time` → un CC à `time=3.4` serait **introuvable** (ou pire,
  `event_idx` résolu parmi les événements du temps 3).
- `Pattern.resize` : `divmod(int(ev.time), old_steps)` puis ré-encodage
  `bar*num_steps+step` → fraction perdue.
- `TrackEditor._extract`/`paste` (clé `(rel, bar, step)` puis
  `_bar_step_to_time`) et `ui/mw_project.py::_clipboard_to_dict`/
  `_clipboard_from_dict` (enregistrements `[etype, t, b, s, …]`) →
  fraction perdue au copier-coller de piste.
- Sans risque : `_run_thread` (utilise `ev.time` tel quel), `double_bars`/
  `halve_bars` (additions/comparaisons), `to_dict`/`from_dict` (`time`
  sérialisé tel quel en JSON), `_events_by_time` (groupe par `ev.time`
  exact, `_time_to_bar_step` fait `int()` pour l'affichage BBT).

### Décisions proposées (à valider par l'utilisateur)

1. **CC capturés en temps flottant non quantifié — pour tous les CC, pas
   seulement CC#1.** `record_cc` stocke l'offset brut de
   `_compute_record_offset` (sans arrondi au pas ni quantisation
   d'enregistrement), comme `record_bend`/`record_mod` aujourd'hui. Les
   CC sont des contrôleurs continus (volume, pan, mod…) : les tasser sur
   la grille n'a pas de sens musical, la quantisation reste réservée aux
   notes. `record_program_change` reste au pas entier (événement
   ponctuel, rien à lisser).
   - *Écarté* : garder CC au pas entier (régression audible du vibrato,
     voir ci-dessus) ; traiter CC#1 seul en flottant (deux règles pour un
     même etype, piège pour la future migration de `_bend_tape`).
   - Implique de rendre **sûrs vis-à-vis d'un `time` fractionnaire** les
     chemins listés plus haut : repérage par `ev["offset"]` (déjà fourni
     par `_events_by_time`, égal à `ev.time` exact) plutôt que par
     `bar/step` dans `_delete_tape_event`/`_replace_tape_event` ;
     conservation de la fraction dans `resize` et dans les deux
     presse-papiers `TrackEditor` (champ fraction optionnel en fin
     d'enregistrement, absent = 0, rétrocompatible).
   - Édition Entrée d'un CC (Ctrl+2) : si la position bar/step n'est pas
     changée, le `time` fractionnaire d'origine est conservé ; si elle
     l'est, l'événement est posé sur le pas entier choisi.
2. **Suppression complète de `_mod_tape`** : attribut, `record_mod`,
   `MOD_TAPE_EVENT`, `_on_mod_tape_cb` et son wiring, appel `record_mod`
   dans `on_cc`, branches `_mod_tape` de `Pattern`/`TrackEditor`.
   `TrackRouter.on_mod_tape` **reste** (appelé par `on_cc_tape` pour
   CC#1). Corrige au passage le double rejeu.
3. **Rétrocompatibilité `.gvp` : migration à l'ouverture.** `to_dict`
   n'écrit plus `"mod_tape"`. `from_dict`, si la clé est présente et
   non vide pour une piste, convertit chaque `(off, val)` en
   `TapeEvent(ETYPE_CC, channel=0, payload={"cc_num": 1, "value": val},
   time=off)` **et retire d'abord les `ETYPE_CC` `cc_num==1` déjà
   présents dans `tape_v2` pour cette piste** — les presets sauvés depuis
   4f contiennent les deux copies ; `_mod_tape` gagne car c'est la copie
   précise (temps flottant). Piste dont `mod_tape` est vide → ses
   `ETYPE_CC#1` sont gardés tels quels.
   - Limite assumée : un CC#1 supprimé à la main via Ctrl+2 (possible
     depuis 4i sur la copie `cc`) mais toujours présent dans `mod_tape`
     réapparaît à la première réouverture de ce preset ancien. Cas rare,
     une seule fois, documenté plutôt que traité.
   - *Écarté* : fusionner les deux sources (doublons garantis) ; ignorer
     `mod_tape` (perte de la précision temporelle des presets existants).
4. **Éditeur MIDI : un seul type `"cc"`.** `get_all_events` ne produit
   plus d'entrées `"mod"` ; un point de molette s'affiche comme n'importe
   quel CC (`describe_cc(1)` → « Modulation Wheel » déjà fourni par le
   libellé Ctrl+2 de 4m), est éditable par Entrée et supprimable.
   `edit_mod_event` et les branches `"mod"` de `mew_display`,
   `mew_editing`, `_CcEventEditDialog` disparaissent.
   - **`EventFilterDialog` garde l'entrée « Mod Wheel (CC1) »** comme
     raccourci de filtre : `etype_filter="mod"` est traduit dans
     `filter_events` en `type=="cc" and cc_num==1` (habitude conservée,
     pas besoin de passer par CC générique + numéro 1..1).
   - *Écarté* : retirer l'entrée du dialog (perte d'un raccourci
     accessible déjà connu, pour aucun gain).

### Portée explicitement exclue de ce chantier

- Migration de `_bend_tape` vers `_tape` (Pitch Bend n'a pas encore
  d'etype ; même schéma probable, que la décision 1 prépare) — chantier
  distinct.
- Quantisation des CC (`quantize_manager.py` les ignore toujours).
- Édition du `cc_num` d'un CC existant, `copy_events`/`paste_events`
  « niveau événement » pour CC/PGM (inchangé depuis 4a).
- Conversion du `time` flottant des CC déjà enregistrés au pas entier
  dans les presets existants (hors CC#1 remplacé par `mod_tape`) : ils
  restent tels quels.

### Découpage en commits proposé (à valider avant de coder)

| Étape | Contenu | Fichiers |
|---|---|---|
| **5a** | Doc — ce plan. | `docs/DESIGN.md` |
| **5b** | Implémentation — temps flottant des CC (décision 1) : `record_cc` non quantifié ; `_delete_tape_event`/`_replace_tape_event` repèrent par `ev["offset"]` ; `edit_cc_event` conserve la fraction si position inchangée ; `Pattern.resize` conserve la fraction. | `drum_player.py`, `midi/midi_editor.py`, `pattern.py` |
| **5c** | Tests — `record_cc` hors pas entier même avec quantisation active ; suppression/édition d'un CC à `time` fractionnaire (dont cohabitation avec une note au pas entier voisin) ; `resize` préserve la fraction. | `test_drum_player_cc.py`, `test_midi_editor.py`, `test_tape.py` |
| **5d** | Implémentation — presse-papiers `TrackEditor` (`_extract`/`paste`) et `mw_project` (`_clipboard_to_dict`/`_from_dict`) : fraction de `time` conservée (champ optionnel, rétrocompatible). | `track_editor.py`, `ui/mw_project.py` |
| **5e** | Tests — copier/coller de piste et round-trip dict avec un CC fractionnaire ; ancien format sans fraction relu à l'identique. | `test_track_editor.py` |
| **5f** | Implémentation — éditeur MIDI un seul type `"cc"` (décision 4) : `get_all_events` sans `"mod"`, `edit_mod_event` supprimé, alias `"mod"` dans `filter_events`, branches `"mod"` retirées de `mew_display`/`mew_editing`/`_CcEventEditDialog`. | `midi/midi_editor.py`, `ui/mew_*.py`, `ui/midi_editor_dialogs.py` |
| **5g** | Tests — Ctrl+2 ne montre plus de doublon CC#1 ; filtre « Mod Wheel » = CC#1 seul ; tests `"mod"` existants adaptés. | `test_midi_editor*.py`, `test_cc_event_edit_dialog.py`, `test_midi_editor_window.py`, `test_event_filter_dialog.py` |
| **5h** | Implémentation — suppression de `_mod_tape` (décision 2) + migration `.gvp` à l'ouverture (décision 3). Suite rouge jusqu'à 5i (tests `_mod_tape` de `test_tape.py` obsolètes) — à signaler dans le titre du commit. | `pattern.py`, `drum_player.py`, `ui/main_window.py`, `ui/midi_handler_window.py`, `track_editor.py` |
| **5i** | Tests — retrait/adaptation des tests `_mod_tape` ; migration `from_dict` (mod_tape seul, mod_tape + doublon CC#1, mod_tape vide qui garde les CC#1) ; `to_dict` sans `"mod_tape"` ; CC#1 rejoué une seule fois ; `on_cc` n'appelle plus `record_mod`. | `test_tape.py`, `test_pattern_*.py`, `test_track_editor.py`, `test_midi_handler_window.py` |
| **5j** | Doc — clôture (DESIGN.md, mémoire), `pytest tests/` complet vert. | `docs/DESIGN.md` |

**5b-5j FAITS** (commits `37e9441`..`4b85a6b`, 1656 tests passed) —
**chantier Phase 7 étape 5 complet**. Les 4 décisions sont en place : CC en
temps flottant non quantifié (5b/5c, `ev["offset"]` plutôt que bar/step
reconstruit partout où ça comptait) ; presse-papiers `TrackEditor`/
`mw_project.py` sûrs vis-à-vis de la fraction (5d/5e) ; éditeur MIDI un seul
type `"cc"`, `"mod"` devenu un simple alias de filtre (5f/5g) ;
`_mod_tape` entièrement supprimé avec migration `.gvp` à l'ouverture (5h/5i).
CC#1 (Mod Wheel) n'a plus qu'une seule source de vérité, dans `_tape`, comme
GRID/KIT/PATCH/PGM l'ont déjà pour le reste.

Deux pièges trouvés en cours de route, hors plan d'origine, tous deux
corrigés immédiatement :
- En 5d : le nettoyage en mode remplace/fusion des presse-papiers comparait
  `ev.time` par égalité exacte — un CC fractionnaire déjà présent à
  destination aurait survécu à un collage "remplace". Comparaison par pas
  entier (`int(ev.time) != time`) à la place.
- En 5i : `test_track_editor.py::_make_pattern` posait encore
  `p._mod_tape = [...]`, une assignation qui aurait recréé l'attribut sans
  lever (contrairement à une lecture) — repéré en relisant tout le dépôt
  après coup, pas par un échec de test. Réflexe à garder : `grep -rn` sur le
  nom complet de la structure supprimée avant de clore un chantier de ce
  genre, ne pas se fier uniquement à la suite de tests.

5h et 5i ont été committés séparément bien que faits dans la même session
(impl rouge connue, puis tests qui ramènent au vert), pour garder le
découpage du plan lisible dans l'historique — convention à reprendre pour
un futur chantier de suppression de structure. La migration de `_bend_tape`
vers `_tape` (même schéma probable) reste explicitement hors périmètre de
ce chantier (voir Portée exclue ci-dessus), à numéroter séparément si elle
est un jour entreprise.

---

## Phase 7 étape 6a1 — Migration `_bend_tape` → `_tape`/`ETYPE_BEND` (Pitch Bend)

### Numérotation des commits de ce chantier

À partir de ce chantier, chaque étape prévue porte un suffixe numérique :
`6a1`, `6b1`, `6c1`… Un commit non prévu qui s'avère nécessaire en cours
de route se range sous l'étape à laquelle il se rattache avec le suffixe
suivant (`6a2`, `6b2`, `6b3`…), sans décaler les lettres des étapes
suivantes (décidé le 2026-10-17).

### Origine du besoin

Suite directe de l'étape 5 (demandée le 2026-10-17) : après CC#1, le
Pitch Bend est la **dernière automation** qui vit hors de `_tape`, dans une
structure parallèle `_bend_tape`. But : une seule source de vérité pour
tous les événements d'une piste (GRID/KIT/PATCH/CC/PGM/BEND), préalable à
l'import/export MIDI.

Différence avec l'étape 5 : il n'existe **aucune copie** du Pitch Bend dans
`_tape` aujourd'hui (pas de doublon à arbitrer), mais **aucun etype** non
plus — il faut en créer un. Et le Pitch Bend n'est pas un CC (statut MIDI
`0xE0`, valeur 14 bits signée, pas de `cc_num`) : il ne peut pas se fondre
dans `ETYPE_CC` comme CC#1 l'a fait.

### État des lieux constaté en code (2026-10-17, 1656 tests verts)

**Où vit `_bend_tape`** (liste par piste de tuples `(float_offset, value)`,
`value` dans -8192..+8191, ni `TapeEvent`, ni canal, ni verrou) :
- `pattern.py` : `__init__` (L159), `copy_from`, `new_pattern`,
  `reset_pattern`, `clear_track`, `double_bars`, `halve_bars`, `resize`,
  `to_dict` (clé `"bend_tape"`), `from_dict` (lecture tolérante, complétée
  à `_num_tracks`).
- `drum_player.py` : `BEND_TAPE_EVENT = -4`, `_on_bend_tape_cb`, boucle
  `_run_thread` qui construit les `BEND_TAPE_EVENT` (L488-494) **hors du
  snapshot sous verrou** de `_tape`, et les dispatche (L558-561) ;
  `record_bend()` (L1030), sans canal ni verrou.
- `ui/main_window.py:131` : `_on_bend_tape_cb = self._router.on_bend_tape`.
- `ui/midi_handler_window.py::on_pitch_bend` (L203) : `record_bend(bend)`
  (le canal reçu n'est pas transmis).
- `track_router.py::on_bend_tape` (L396) : applique la valeur au moteur
  du slot de la piste — inchangé par ce chantier.
- `track_editor.py::_erase_tape_range` : efface la plage dans `_bend_tape`.
- `midi/midi_editor.py` : `get_all_events` produit des entrées
  `type="bend"` (sans `etype`, `channel` ni `event_idx`) ;
  `edit_bend_event` (chirurgie directe sur la liste de tuples) ;
  `filter_events` (`etype_filter="bend"`, bornes `bend_lo/hi`) ;
  `delete_event` **ne gère pas** `"bend"` (point non supprimable).
- UI : `mew_display.py` (2 branches `"bend"`, format Ctrl+2 sans index ni
  canal, contrairement à CC/PGM), `mew_editing.py` (dispatch
  `"bend"` → `edit_bend_event`), `midi_editor_dialogs.py::_CcEventEditDialog`
  (branche `"bend"`, bornes -8192..8191), `dialogs_temporal.py::EventFilterDialog`
  (`_TYPE_BEND`, groupe de bornes Pitch Bend Bas/Haut).
- Tests : ~25 tests `_bend_tape`/`record_bend` dans `test_tape.py`
  (L1166-1476), plus `test_pattern_properties_bug.py`,
  `test_pattern_grid_api.py`, `test_track_editor.py` (fixture
  `_make_pattern` qui **assigne** `p._bend_tape` — le même piège que
  `_mod_tape` en 5i), `test_midi_editor.py`, `test_midi_editor_filter.py`,
  `test_cc_event_edit_dialog.py`, `test_midi_editor_window.py`,
  `test_event_filter_dialog.py`.

**Hors `_bend_tape`, sans rapport avec ce chantier** : le champ `"bend"`
du payload `ETYPE_PATCH` (valeur du bend au moment du note-on, rejouée par
`on_patch_tape`) et le payload `{"bend":}` de `MidiMessage` PitchBend
(`midi_parser.py`). Restent tels quels.

**Bugs existants que la migration corrige d'elle-même** (constatés en
relisant, aucun test ne les couvre aujourd'hui) :
1. **`Pattern.resize` ne ré-encode pas `_bend_tape`** quand `num_steps`
   change : il filtre seulement `off < total_steps`. Passer de 16 à 32 pas
   par mesure déplace un bend posé à la mesure 2 pas 1 (`off=16`) vers la
   mesure 1 pas 17. `_tape` passe déjà par le décodage/ré-encodage bar/step
   avec fraction (5b).
2. **Ctrl+X avec limiteurs perd les bends** : `_erase_tape_range` les
   efface, mais `_extract` ne les met pas dans le presse-papier (il ne lit
   que `_tape`). Même chose pour Ctrl+C/Ctrl+V de piste : les bends ne
   suivent pas. Une fois dans `_tape`, `_extract`/`paste` (génériques par
   etype, fraction conservée depuis 5d) les prennent en charge.
3. **`edit_bend_event` perd la fraction même si la position ne change
   pas** : il recalcule toujours `n_off = bar*num_steps+step` (entier).
   `_replace_tape_event` conserve déjà le `time` d'origine dans ce cas (5b).
4. **Itération de `_bend_tape` sans verrou** dans `_run_thread` pendant
   que `record_bend` y ajoute : le snapshot sous `_pattern._lock` couvrira
   les bends comme le reste.

**Chemins génériques qui fonctionneront sans modification** (ils
recopient `ev.etype`/`ev.payload` sans dispatch) : `copy_from`,
`double_bars`, `halve_bars`, `resize`, `to_dict`/`from_dict` (`tape_v2`),
`clear_track`, `TrackEditor._extract`/`paste`/fusion,
`_erase_tape_range` (partie `_tape`), `_events_by_time`,
`quantize_manager` (ne traite que KIT/PATCH, ignore le reste).

**Chemins à dispatch explicite à compléter** :
- `drum_player._run_thread` : nouvelle branche `ETYPE_BEND`.
- `ui/mw_project.py::_clipboard_to_dict` (ignore silencieusement un etype
  inconnu → bend perdu à la sauvegarde du presse-papier) et
  `_clipboard_from_dict` (sa branche `else` finale traite tout etype
  inconnu comme KIT/PATCH → enregistrement BEND **mal relu**). Branches
  `ETYPE_BEND` explicites dans les deux.
- `midi/midi_editor.py` : `get_cc_pgm_events` (ou équivalent) pour
  remonter les `ETYPE_BEND`, `delete_event`, `edit_bend_event`.

**Changement de comportement assumé** : `Pattern.is_empty()` (`not
any(self._tape)`) deviendra faux pour un pattern ne contenant que du
Pitch Bend — cohérent avec CC/PGM, qui sont déjà dans ce cas.

### Décisions validées (utilisateur, 2026-10-17)

1. **Nouvel etype `ETYPE_BEND = "BEND"`, payload `{"value": bend}`**
   (-8192..+8191, 0 = centre), `dur=0`, `channel` = canal MIDI d'origine
   (comme CC/PGM). Pas de `cc_num`.
   - `"value"` plutôt que `"bend"` : même clé que `ETYPE_CC`, que le dict
     d'événement de l'éditeur (`e["value"]`, déjà utilisé par le filtre
     `bend_lo/hi` et `_CcEventEditDialog`), et que la future traduction
     export MIDI (etype → statut, `value` → octets de données). La clé
     `"bend"` reste réservée au payload PATCH (bend au note-on), ce qui
     évite toute confusion entre les deux.
   - *Écarté* : réutiliser `ETYPE_CC` avec un `cc_num` fictif (ex. -1 ou
     128) — fausserait le filtre CC 0..127, `describe_cc`, l'édition Entrée
     (bornes 0..127) et l'export MIDI ; le Pitch Bend est un type de
     message MIDI à part entière.
2. **Capture en temps flottant non quantifié** (règle de 5a décision 1,
   déjà celle de `record_bend` aujourd'hui) : `record_bend(bend, channel=0)`
   ajoute un `TapeEvent(ETYPE_BEND, …)` sous `_pattern._lock`. Le calcul
   de l'offset flottant (dont la garde `time_val >= total_steps` que
   `record_bend` n'a pas) est **factorisé** avec `record_cc` dans un helper
   privé `_compute_float_offset()` plutôt que dupliqué une troisième fois.
   `on_pitch_bend` transmet le canal reçu.
3. **Lecture : on garde `BEND_TAPE_EVENT`, `_on_bend_tape_cb` et
   `TrackRouter.on_bend_tape`** — seule la source change (branche
   `ETYPE_BEND` dans la boucle sur le snapshot de `_tape`, la boucle
   séparée sur `_bend_tape` disparaît). Aucun changement dans
   `TrackRouter` ni dans le câblage de `main_window`.
   - *Écarté* : router via `CC_TAPE_EVENT` (le Pitch Bend n'est pas un CC,
     voir décision 1).
4. **Suppression complète de `_bend_tape`** : attribut et toutes ses
   branches dans `Pattern`, `TrackEditor._erase_tape_range`,
   `drum_player._run_thread`, `MidiEditor`. Avant de clore : `grep -rn
   _bend_tape` sur **tout** le dépôt, tests compris (leçon de 5i).
5. **Rétrocompatibilité `.gvp` : migration à l'ouverture.** `to_dict`
   n'écrit plus `"bend_tape"`. `from_dict` convertit chaque `(off, val)`
   de `"bend_tape"` (si présente) en `TapeEvent(ETYPE_BEND, channel=0,
   payload={"value": val}, time=off)` ajouté à `_tape[t]`. Pas de doublon
   à retirer (contrairement à `mod_tape`) ; `channel=0` faute
   d'information dans l'ancien format.
6. **Éditeur MIDI : `"bend"` reste un type réel** (pas un alias comme
   `"mod"`) — le filtre `etype_filter="bend"` et ses bornes `bend_lo/hi`,
   le groupe Pitch Bend de `EventFilterDialog`, la branche `"bend"` de
   `_CcEventEditDialog` restent inchangés.
   - Les entrées `"bend"` sont produites depuis `_tape` (par la même
     passe `_events_by_time` que CC/PGM, donc `event_idx` cohérent tous
     etypes confondus) et gagnent `etype`, `channel`, `event_idx`.
   - `edit_bend_event` passe par `_replace_tape_event` (fraction
     conservée si position inchangée — corrige le bug 3).
   - `delete_event` accepte `"bend"` (via `_delete_tape_event`) : un
     point de bend devient supprimable, comme CC/PGM depuis 4i.
   - Ctrl+2 : la ligne bend adopte le format des autres types
     (« `i: position, Canal c, Pitch Bend, Valeur +v` ») au lieu de
     l'ancien `Tr01  Bend:+v` sans index ni canal. Le format Ctrl+1
     (mode Notes) n'affiche pas les bends, inchangé.

### Portée explicitement exclue de ce chantier

- Le champ `"bend"` du payload `ETYPE_PATCH` (bend figé au note-on) :
  inchangé, sa coexistence avec l'automation `ETYPE_BEND` est un sujet
  musical distinct.
- `TrackRouter.on_bend_tape` et le moteur synthé (application du bend).
- Quantisation des bends (comme les CC, ignorés par `quantize_manager`).
- `copy_events`/`paste_events` « niveau événement » pour bend/CC/PGM
  (inchangé depuis 4a, notes seulement).
- Changement de canal d'un bend existant à l'édition (comme CC/PGM).
- Bends déjà enregistrés dans des presets existants : migrés tels quels
  avec `channel=0`, aucun recalage.

### Découpage en commits

| Étape | Contenu | Fichiers |
|---|---|---|
| **6a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **6b1** | Implémentation — `ETYPE_BEND` (constante + docstring `TapeEvent`) ; helper `_compute_float_offset` partagé par `record_cc`/`record_bend` ; `record_bend(bend, channel)` écrit dans `_tape` ; `on_pitch_bend` passe le canal ; branche `ETYPE_BEND` dans `_run_thread` (boucle `_bend_tape` retirée). Suite rouge jusqu'à 6c1 (tests `record_bend`/`_run_thread` de `test_tape.py`) — à signaler dans le titre. | `pattern.py`, `drum_player.py`, `ui/midi_handler_window.py` |
| **6c1** | Tests — `record_bend` crée un `ETYPE_BEND` flottant non quantifié avec canal, sur la piste courante ; garde de fin de boucle ; `record_cc` inchangé après factorisation ; lecture d'un `ETYPE_BEND` → `_on_bend_tape_cb(track, value)` une seule fois ; adaptation des tests `record_bend` existants. | `test_tape.py`, `test_drum_player_cc.py`, `test_midi_handler_window.py` |
| **6d1** | Implémentation — éditeur MIDI (décision 6) : bends remontés depuis `_tape` avec `event_idx`/`channel`/`etype`, `edit_bend_event` via `_replace_tape_event`, `delete_event` accepte `"bend"`, nouveau format Ctrl+2. | `midi/midi_editor.py`, `ui/mew_display.py` |
| **6e1** | Tests — bend listé avec `event_idx` cohérent à côté d'une note/CC au même `time` ; édition valeur seule conserve la fraction ; déplacement → pas entier ; suppression ; filtre `"bend"` + bornes ; libellé Ctrl+2. Adaptation des tests qui posaient `_bend_tape` à la main. | `test_midi_editor*.py`, `test_cc_event_edit_dialog.py`, `test_midi_editor_window.py`, `test_event_filter_dialog.py` |
| **6f1** | Implémentation — presse-papiers `mw_project` : branches `ETYPE_BEND` dans `_clipboard_to_dict`/`_clipboard_from_dict` (avec fraction). | `ui/mw_project.py` |
| **6g1** | Tests — Ctrl+X/Ctrl+C/Ctrl+V de piste transportent les bends (fraction comprise, corrige le bug 2) ; round-trip dict du presse-papier avec un bend ; enregistrement BEND non relu comme KIT/PATCH. | `test_track_editor.py`, test presse-papier `mw_project` existant |
| **6h1** | Implémentation — suppression de `_bend_tape` (décision 4) + migration `.gvp` à l'ouverture (décision 5). Suite rouge jusqu'à 6i1 — à signaler dans le titre. | `pattern.py`, `track_editor.py`, `drum_player.py` |
| **6i1** | Tests — retrait/adaptation des tests `_bend_tape` (dont la fixture `test_track_editor.py::_make_pattern`) ; migration `from_dict` (`bend_tape` seul, avec notes/CC existants, absente) ; `to_dict` sans `"bend_tape"` ; `resize` 16→32 pas garde la position musicale d'un bend (corrige le bug 1) ; `double_bars`/`halve_bars`/`copy_from` sur `ETYPE_BEND`. | `test_tape.py`, `test_pattern_*.py`, `test_track_editor.py` |
| **6j1** | Doc — clôture (DESIGN.md, `docs/SPECS.md` si concerné, mémoire), `grep -rn _bend_tape` sur tout le dépôt, `pytest tests/` complet vert. | `docs/DESIGN.md` |

Ordre choisi : capture/lecture d'abord (6b1-6c1), pendant que `_bend_tape`
existe encore comme attribut vide — l'éditeur (6d1) et le presse-papier
(6f1) peuvent alors être testés sur `ETYPE_BEND` seul, et la suppression
de la structure (6h1) n'arrive qu'en dernier, comme en 5h.

### Avancement et écarts constatés

- **6b1** (`61eb827`) — conforme au plan.
- **6c1** — un écart : la garde « fin de boucle » de
  `_compute_float_offset` (`time_val >= total_steps` → 0.0) **n'est pas
  testée**. Une recherche numérique (tous les BPM entiers 40-300, et
  200 000 durées de pas aléatoires, avec la plus grande valeur flottante
  inférieure à la durée de boucle) n'a trouvé aucun cas où
  `((now-ref) % measure_secs) / step_duration` atteint `total_steps`. La
  garde reste en place par prudence (elle existait déjà dans `record_cc`),
  sans test qui la déclenche. Le rejeu est testé sur la vraie boucle
  `_run_thread` (`play_pattern` à 600 BPM), pas sur une copie de sa
  logique comme l'ancien test `test_run_thread_build_bend_tape_events`.
- **6d1-6g1** — conformes au plan. Constaté en 6d1 : Suppr dans l'interface
  de l'éditeur ne supprime que les notes (CC/PGM/bend supprimables
  seulement via `MidiEditor.delete_event`) — inchangé, hors périmètre.
- **6g2** (commit imprévu, correction + tests) — bug pré-existant trouvé en
  6g1 : le limiteur droit, censé inclure son pas, était comparé par
  `ev.time <= lim_r`. Un CC (depuis 5b) ou un bend à 5.4 avec limiteur
  droit sur 5 n'était ni effacé (`TrackEditor._erase_tape_range`) ni
  listé dans Ctrl+2 (`MidiEditor._events_by_time`) ; même défaut pour la
  borne `pos_to` de `filter_events`. Correction : comparaison au pas
  entier (`ev.time < lim_r + 1`, `offset >= int(pos_to) + 1`), même règle
  que le collage en 5d. Les notes (toujours au pas entier) ne changent
  pas de comportement.
- **6h1-6i1** — conformes au plan. En 6i1, vérifié en plus en lecture
  seule que les `.gvp`/preset du dépôt (`data/`) se chargent ; aucun ne
  contient de point `bend_tape`, la conversion n'est donc éprouvée que
  par les tests (`project_01.gvp` garde une clé `"bend_tape"` vide,
  convertie et retirée à sa prochaine sauvegarde).

### Clôture (6j1)

**6a1-6i1 FAITS** (commits `737497e`..`76cec7a`, 1689 tests passed) —
**chantier Phase 7 étape 6 complet**. Les 6 décisions sont en place :
`ETYPE_BEND` (payload `{"value"}` + canal) capturé en temps flottant via
`_compute_float_offset` partagé avec `record_cc` (6b1/6c1) ; rejoué par le
même chemin `BEND_TAPE_EVENT` → `on_bend_tape` depuis le snapshot sous verrou
de `_tape` ; éditeur MIDI sur `_tape`, `"bend"` type réel, supprimable,
même format Ctrl+2 que CC/PGM (6d1/6e1) ; presse-papier de piste et sa
sérialisation (6f1/6g1) ; `_bend_tape` supprimé + migration `.gvp` (6h1/6i1).

**Toutes les automations vivent désormais dans `_tape`** (GRID/KIT/PATCH/
CC/PGM/BEND) : plus aucune structure parallèle, préalable à l'import/export
MIDI.

Les 4 bugs pré-existants du plan sont corrigés et testés (resize 16→32 pas,
Ctrl+X avec limiteurs, fraction perdue à l'édition, itération sans verrou —
ce dernier par construction, sans test dédié). Un 5e, hors plan, corrigé en
6g2 (limiteur droit / `pos_to` excluant la fraction de leur pas).

`grep -rn _bend_tape` final sur tout le dépôt : dans `src/`, plus que des
commentaires historiques et la lecture de l'ancienne clé `"bend_tape"` par
`from_dict` ; dans `tests/`, idem plus les tests de migration ; aucune
assignation résiduelle (fixture `test_track_editor.py` nettoyée en 6i1).
`docs/SPECS.md` mis à jour (Pitch Bend, format Ctrl+2, édition, limiteurs).

**Restent hors périmètre** (inchangés, voir Portée exclue) : champ `"bend"`
des notes PATCH, Suppr de CC/PGM/bend depuis l'interface de l'éditeur,
`on_pitch_bend` qui ne capture rien si aucun synthé n'est prêt (retour
anticipé avant `record_bend`, comportement antérieur à ce chantier).

Convention de numérotation `6a1`/`6b1`… (suffixe numérique pour les commits
imprévus) éprouvée : un seul commit imprévu, `6g2`.

---

## Phase 7 étape 7a1 — Points restants du Pitch Bend : Suppr, capture sans synthé, champ `"bend"` des notes PATCH

### Numérotation des commits de ce chantier

Même convention qu'en 6 : `7a1`, `7b1`, `7c1`… ; un commit imprévu inséré
après `7b1` s'appelle `7b2`, `7b3`, etc.

### Origine du besoin

Le chantier 6 a laissé trois points hors périmètre (voir sa section
« Clôture (6j1) »). Ce chantier les traite, plus un bug trouvé en écrivant
ce plan.

### État des lieux constaté en code (2026-10-17, 1689 tests verts)

**Point 1 — Suppr dans l'éditeur MIDI** (`ui/mew_delete_clipboard.py::_delete_event`).
- Avec une sélection, seules les notes (`type == "note"`) sont gardées ;
  sinon le message est « Aucune note sélectionnée supprimable ».
- Sans sélection, c'est le groupe au même offset (`group_indices`), filtré
  sur les notes ; sinon le message est « Suppression non disponible pour ce
  type ».
- Pourtant, `MidiEditor.delete_event` sait déjà supprimer `"cc"`, `"pgm"` et
  `"bend"` (depuis 4i et 6d1). Il ne manque que l'interface.
- En Ctrl+1 (`MODE_NOTES`), la liste ne contient que des notes.
- En Ctrl+2 (`MODE_ALL`), elle contient aussi CC, PGM et Pitch Bend.
- Entrée en Ctrl+2 édite l'événement sous le curseur, quel que soit son type.

**Bug pré-existant trouvé (bug A) — suppression d'un accord KIT/PATCH.**
- `_delete_tape_event` retrouve un événement par `time` + `event_idx`.
  `event_idx` est sa position parmi tous les événements de la piste à ce
  `time`, dans l'ordre de `_tape`.
- `get_note_events` trie l'affichage par `(offset, pad)`, donc dans un ordre
  qui peut différer de `event_idx`.
- `_delete_event` supprime « à l'envers de l'affichage ». Après la première
  suppression, les `event_idx` restants sont décalés.
- Reproduit hors suite : deux notes PATCH au temps 0, 67 puis 60 dans
  `_tape`. Affichage : 60 (idx 1), 67 (idx 0). `delete_event` sur les deux
  à l'envers de l'affichage → `[True, False]`, **la note 60 reste**.
- Pas de souci pour les notes GRID seules (elles passent par `set_cell`,
  par pad). Mais un mélange GRID + KIT/PATCH, ou demain note + bend au
  même pas, est touché.

**Point 2 — `on_pitch_bend` sans synthé** (`ui/midi_handler_window.py`).
- `if not win._router.synth_ready(): return` arrive **avant**
  `record_bend`.
- Si la piste courante n'a pas de synthé chargé, la molette n'est donc pas
  enregistrée.
- À l'inverse, `on_cc` enregistre (`record_cc`) avant tout effet live.
- La relecture (`TrackRouter.on_bend_tape`) ignore déjà proprement une
  piste dont le slot n'est pas un synthé.

**Point 3 — champ `"bend"` des notes PATCH.**
- À la capture, `_handle_synth_note_on` lit `synth.pitch_bend` (0 si pas de
  synthé) et le passe à `record_patch_note(…, bend=)`, qui l'écrit dans le
  payload `{"note","vel","bend"}`.
- À la relecture, `_run_thread` le passe à `on_patch_tape(…, bend)`.
  `on_patch_tape` pose `engine.pitch_bend = bend` le temps du `play()`,
  puis **restaure l'ancienne valeur**. Le bend est donc propre à la note,
  pas un état de canal.
- Il y a deux sources de vérité pour le bend :
  - le payload de la note, valeur figée à son départ ;
  - les `ETYPE_BEND`, état du canal.
  Elles peuvent se contredire au même pas.
- Le MIDI ne connaît que l'état de canal : un fichier `.mid` n'a pas de
  bend par note. C'est un frein pour l'import/export et le mode Rack GM.
- Ordre de rejeu à `t_sec` égal : `events.sort()` trie sur le marqueur, donc
  `BEND_TAPE_EVENT` (-4) passe avant `PATCH_TAPE_EVENT` (-3). Un bend posé au
  même temps qu'une note s'applique donc avant elle.
- Autres porteurs du champ :
  - `MidiEditor` (dicts de notes, `edit_tape_note`, insertion,
    duplication) ;
  - presse-papier `mw_project` (`rec[7]` pour PATCH) ;
  - `TrackEditor` (collage) ;
  - `Pattern.from_dict` (ancien format `patch_tape`, `rec[6]`) ;
  - le docstring `TapeEvent`.
- Données réelles : les `.gvp` et le preset de `data/` ne contiennent
  **aucun** `"bend"` non nul.

### Décisions proposées (à valider par l'utilisateur)

**D1 — Suppr dans l'éditeur supprime tout type d'événement.**
- Avec une sélection : tous les événements sélectionnés sont supprimés,
  quel que soit leur type.
- Sans sélection, curseur sur une note : comportement inchangé, l'accord
  entier est supprimé. Les CC, PGM et bends au même offset sont conservés.
- Sans sélection, curseur sur un CC, un PGM ou un bend : seul cet événement
  est supprimé (même logique qu'Entrée, qui édite la ligne sous le
  curseur).
- Messages et libellés d'undo :
  - « Pitch Bend supprimé » ;
  - « CC#7 supprimé » ;
  - « Program Change supprimé » ;
  - « N événement(s) supprimé(s) » pour une sélection mixte ;
  - les messages actuels sont gardés quand la sélection ne contient que
    des notes.
- Correction du bug A au même endroit :
  - nouvelle méthode `MidiEditor.delete_events(pattern, evs)` ;
  - elle supprime dans l'ordre `(track, time, event_idx)` décroissant, si
    bien qu'aucune suppression ne décale un `event_idx` encore à traiter ;
  - elle s'applique aussi aux notes GRID (`set_cell` retire l'entrée `_tape`
    à son propre index) ;
  - elle retourne le nombre d'événements supprimés ;
  - `_delete_event` l'utilise dans les deux branches.

**D2 — `on_pitch_bend` enregistre même sans synthé.**
- `record_bend(bend, channel)` est appelé si `recording`, **avant** le test
  `synth_ready()`, comme dans `on_cc`.
- Sans synthé, le message de statut devient « Pitch Bend: +1234 » (valeur
  brute). Les demi-tons dépendent du moteur.
- L'effet live et le log sont inchangés quand un synthé est prêt.

**D3 — le bend devient un état de canal uniquement (option B, recommandée).**
- **Capture.** `record_patch_note` n'écrit plus `"bend"` dans le payload.
  Si la valeur de bend reçue diffère de l'état de bend de la piste à cet
  instant, il pose d'abord un `ETYPE_BEND` (même canal) **au temps de la
  note**. L'état de bend est la valeur du dernier `ETYPE_BEND` de la piste
  de temps ≤ celui de la note, ou 0 s'il n'y en a pas.
  - Un bend tenu *avant* d'armer l'enregistrement est ainsi conservé (c'est
    ce que le champ servait à faire).
  - Il n'y a pas de doublon quand `on_pitch_bend` (D2) a déjà enregistré
    la même valeur.
- **Relecture.**
  - `on_patch_tape` perd le paramètre `bend` et l'écrasement/restauration
    de `engine.pitch_bend` : la note joue avec l'état courant du moteur ;
  - le tuple `PATCH_TAPE_EVENT` de `_run_thread` perd le bend ;
  - l'ordre de tri (-4 avant -3) garantit qu'un bend au même temps
    s'applique avant la note.
- **Éditeur et presse-papier.**
  - Le champ `"bend"` disparaît des dicts de notes et des payloads créés
    par l'insertion, la duplication et l'édition.
  - Le presse-papier `mw_project` garde la même position d'enregistrement,
    pour lire un presse-papier sauvé avant ce chantier. Il y écrit 0 et
    ignore la valeur à la lecture.
  - Même chose pour le collage de `TrackEditor`.
- **Migration à l'ouverture (`from_dict`, `tape_v2` et ancien
  `patch_tape`).**
  - Pour chaque piste, on parcourt ses notes PATCH par temps croissant et on
    applique la même règle qu'à la capture. Les `ETYPE_BEND` qui
    reproduisent le bend de départ de chaque note sont posés : une note
    à 0 après une note pliée remet donc l'état à 0.
  - Puis `"bend"` est retiré des payloads.
  - Seule différence assumée : deux notes qui se chevauchent partagent
    désormais le même bend, comme en MIDI.
  - Aucune donnée réelle n'est concernée, la conversion n'est éprouvée que
    par les tests.

Alternatives écartées :
- **A — garder le champ tel quel.** Deux sources de vérité qui peuvent se
  contredire, et rien à exporter en MIDI.
- **C — retirer le champ sans poser de bend au note-on.** Un bend tenu avant
  d'armer l'enregistrement serait perdu, alors qu'il est capturé
  aujourd'hui.

### Portée explicitement exclue de ce chantier

- Suppr en Ctrl+1 (`MODE_NOTES`) : la liste ne contient que des notes, donc
  le comportement ne change pas (hors correction du bug A).
- `copy_events`/`paste_events` « niveau événement » de l'éditeur pour
  CC/PGM/bend (notes seulement depuis 4a).
- Quantisation des bends, `TrackRouter.on_bend_tape`, moteur synthé.
- Application live du bend à un moteur de slot quand aucun synthé n'est
  « courant » (D2 ne touche que la capture).
- Champ `"bend"` du `MidiMessage` du parser (c'est le message Pitch Bend
  lui-même, sans rapport).

### Découpage en commits proposé (à valider avant de coder)

| Étape | Contenu | Fichiers |
|---|---|---|
| **7a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **7b1** | Implémentation — D1 : `MidiEditor.delete_events` (ordre `event_idx` décroissant, corrige le bug A) ; `_delete_event` supprime tout type en sélection, et l'événement sous le curseur s'il n'est pas une note ; messages/undo. | `midi/midi_editor.py`, `ui/mew_delete_clipboard.py` |
| **7c1** | Tests — accord PATCH 67/60 entièrement supprimé (bug A) ; mélange GRID + PATCH + bend au même pas ; Suppr Ctrl+2 sur un bend/CC/PGM seul ; sélection mixte ; curseur sur une note avec bend au même offset (bend conservé) ; undo restaure ; messages. | `test_midi_editor.py`, `test_midi_editor_window.py` |
| **7d1** | Implémentation — D2 : `record_bend` avant `synth_ready()` dans `on_pitch_bend`, statut sans synthé. | `ui/midi_handler_window.py` |
| **7e1** | Tests — enregistrement sans synthé prêt (`ETYPE_BEND` créé, statut brut) ; pas d'enregistrement hors `recording` ; cas synthé prêt inchangé. | `test_midi_handler_window.py` |
| **7f1** | Implémentation — D3 capture/relecture : `record_patch_note` sans `"bend"` + pose d'un `ETYPE_BEND` si l'état de piste diffère ; `_run_thread`/`on_patch_tape` sans bend ; docstring `TapeEvent`. Suite rouge jusqu'à 7g1 — à signaler dans le titre. | `drum_player.py`, `track_router.py`, `pattern.py` |
| **7g1** | Tests — note avec bend tenu → un `ETYPE_BEND` au temps de la note, payload sans `"bend"` ; pas de doublon si l'état est déjà égal ; bend 0 sans état antérieur → aucun `ETYPE_BEND` ; rejeu réel : bend appliqué avant la note au même temps ; adaptation des tests existants. | `test_tape.py`, `test_midi_handler_window.py`, tests `on_patch_tape` |
| **7h1** | Implémentation — D3 éditeur/presse-papier/migration : champ retiré de `MidiEditor` et `TrackEditor`, presse-papier `mw_project` (position gardée, valeur ignorée), migration `from_dict` (`tape_v2` et `patch_tape`). Suite rouge jusqu'à 7i1 — à signaler dans le titre. | `midi/midi_editor.py`, `track_editor.py`, `ui/mw_project.py`, `pattern.py` |
| **7i1** | Tests — migration : notes pliées → `ETYPE_BEND` équivalents, retour à 0 sur la note suivante non pliée, payloads nettoyés, fichier sans bend inchangé ; presse-papier ancien format ; éditeur sans champ `"bend"` ; adaptation des tests existants. | `test_tape.py`, `test_pattern_*.py`, `test_midi_editor.py`, `test_track_editor.py` |
| **7j1** | Doc — clôture (DESIGN.md, `docs/SPECS.md` : Suppr, Pitch Bend), `grep -rn '"bend"'` sur tout le dépôt, `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

Ordre choisi :
- D1 d'abord : indépendant, et il corrige un bug.
- D2 avant D3, parce que la pose d'un bend au note-on (D3) complète la
  capture de la molette (D2) et que ses tests de non-doublon en dépendent.
- Dans D3, la capture/relecture passe avant la migration, comme en 6.

### Avancement et écarts constatés

- **7b1/7c1** (`87239f9`, `0f4d25b`) — conformes au plan. La contre-épreuve
  des tests de fenêtre sur le code d'avant 7b1 n'est pas possible (le
  fichier de tests ne s'importe pas sans `_deleted_name`) : le bug A reste
  démontré par la reproduction de 7a1 et par les tests de
  `MidiEditor.delete_events`.
- **7d1/7e1** (`e7bb8b3`, `4c99d05`) — conformes. Contre-épreuve : 3 tests
  rouges sur l'ancien code (capture sans synthé, statut brut, bout en bout
  avec un vrai `DrumPlayer`).
- **7f1/7g1** (`d8769a9`, `e5f4a76`) — conformes. La règle d'état est dans
  `Pattern._bend_state_at`/`_chase_bend`, partagée avec la migration.
  Point noté, non traité : à temps égal, `_bend_state_at` retient le
  dernier `ETYPE_BEND` dans l'ordre de `_tape`, alors que la relecture
  (`events.sort()` sur les tuples) les rejoue triés par valeur — deux bends
  différents exactement au même temps sur une piste peuvent donc laisser un
  état final différent de celui calculé. Cas non produit par la capture
  (temps flottants) ; à reprendre si l'import MIDI en crée.
- **7h1/7i1** (`e94603b`, `3efbb59`) — conformes. Les tests qui
  construisaient encore des notes PATCH avec `"bend"` (fixtures de
  `test_midi_editor.py`, `test_pattern_grid_api.py`,
  `test_pattern_properties_bug.py`, `test_transport.py`) sont passés au
  nouveau format ; l'ancien n'existe plus que via `_P_old` dans les tests
  de migration.

### Clôture (7j1)

**7a1-7i1 FAITS** (commits `7a289b9`..`3efbb59`, 1746 tests passed) —
**chantier Phase 7 étape 7 complet**. Les trois points laissés par le
chantier 6 sont résolus :

- **D1** — Suppr de l'éditeur MIDI supprime tout type d'événement
  (sélection ; curseur sur CC/PGM/bend → cet événement seul ; curseur sur
  une note → l'accord, bends du même pas conservés). Bug A corrigé :
  `MidiEditor.delete_events` supprime par `event_idx` décroissant, un
  accord KIT/PATCH n'est plus supprimé à moitié.
- **D2** — `on_pitch_bend` capture même sans synthé prêt.
- **D3** — le bend est un état de canal : plus de champ `"bend"` par note
  PATCH (capture, relecture, éditeur, presse-papier, collage), bend tenu au
  note-on reporté en `ETYPE_BEND`, anciens fichiers convertis à l'ouverture.
  Le bend n'a plus qu'une source de vérité, préalable à l'export MIDI.

`grep -rn '"bend"'` final sur tout le dépôt : dans `src/`, plus que la
migration (`Pattern.from_dict`/`_migrate_patch_note_bends`), la colonne
gardée du presse-papier (`mw_project`, écrite à 0) et des usages sans
rapport (message Pitch Bend du parser MIDI, type d'événement `"bend"` de
l'éditeur et du filtre) ; dans `tests/`, les tests de migration
(`_P_old`) et d'ancien presse-papier. `docs/SPECS.md` mis à jour (Pitch
Bend, Suppr, et description de `TapeEvent`/`_tape`/format `tape_v2`, qui
décrivait encore la structure d'avant la Phase 7).

Restent hors périmètre : copier/coller « niveau événement » de l'éditeur
pour CC/PGM/bend, quantisation des bends, le cas des bends à temps égal
ci-dessus.

---

## Phase 7 étape 8a1 — Découpage de `drum_player.py` en mixins

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 et 7 : `8a1`, `8b1`, `8c1`… ; un
commit imprévu inséré après `8b1` s'appelle `8b2`, `8b3`, etc.

### Origine du besoin

- `src/drum_player.py` fait 1148 lignes. C'est de loin le plus gros fichier
  de `src/` : le suivant, `pattern.py`, fait 635 lignes.
- Décision de l'utilisateur (2026-10-17) : découper ce fichier **avant** le
  chantier Import/Export MIDI, pour partir d'un code découpé.
- Précédents : Phase 5 étapes 11a–12a (gros fichiers éclatés en mixins ou
  par composition) et Phase 6 étape 12a (`midi_editor_window.py`, 2401 →
  101 lignes, 10 mixins `ui/mew_*.py`).

### État des lieux constaté en code (2026-10-18, 1746 tests verts)

**Une seule classe, `DrumPlayer`, plus un helper de module.**
- `_bend_log` (l. 13-22) : log pitch bend activé par `GROOVY_BEND_LOG=1`.
  Il est utilisé seulement par `record_patch_note`/`record_patch_note_off`.
  Trois autres copies identiques existent dans `track_router.py`,
  `synth_engine.py` et `ui/midi_handler_window.py`.
- Sept constantes de classe `*_EVENT` (l. 25-33). Elles ne servent qu'à
  `_run_thread`. Un test lit `DrumPlayer.GRID_EVENT`.
- `__init__` (l. 35-109) : environ 75 attributs d'état, partagés par toutes
  les responsabilités ci-dessous.
- Deux objets sont déjà extraits par composition : `QuantizeManager`
  (`self._qm`, qui reçoit le player comme `owner`) et `LoopManager`
  (`self._lm`). `Metronome` (`self._metro`) et `VoiceManager` aussi.

**Responsabilités repérées (lignes actuelles) :**

| Bloc | Méthodes | Lignes | Taille |
|---|---|---|---|
| Propriétés | `_loop_remaining`, `float_offsets`, `clicking`, `click_in_recording` | 112-145 | ~35 |
| Thread et transport | `start_thread`, `stop_thread`, `play_pattern`, `stop_pattern`, `play_song`, `pause_pattern`, `play_click`, `stop_click`, `stop_all`, `set_bpm` | 148-227, 389-419, 1129-1134 | ~120 |
| Position et navigation | `goto_start`, `goto_end`, `_go_to_offset`, `_current_offset`, `position_str`, `time_str`, `move_by_ticks/beats/seconds/bars`, `navigate_bar` | 229-387 | ~160 |
| Boucle de lecture | `_run_thread` (une seule méthode) | 422-669 | ~250 |
| Délégations quantisation | `apply_quant_row`, `double_pattern`, `halve_pattern`, `apply_quant_to_pattern`, `_compute_offsets`, `load_pattern` | 672-701 | ~30 |
| Jeu live et Note Repeat | `play_sound`, `start_note_repeat`, `stop_note_repeat`, `update_nr_rate`, `set_volume`, `set_pan`, `_mix_pan` | 705-744, 1137-1146 | ~55 |
| Enregistrement | `record_pattern`, `record_pattern_with_count_in`, `stop_record`, `start_replace_recording`, `_record_nr_hit`, `_compute_record_offset`, `_compute_float_offset`, `record_hit`, `record_patch_note`, `record_patch_note_off`, `record_bend`, `record_kit_note`, `record_cc`, `record_program_change` | 747-792, 897-915, 935-1127 | ~265 |
| Effacement (Erase) | `toggle_erase`, `_erase_tape_event`, `erase_hit`, `erase_patch_tape_note`, `_clear_offset` | 794-895, 917-933 | ~120 |

**Couplage avec le reste du code.**
- Deux importeurs dans `src/` (`ui/main_window.py`,
  `ui/midi_handler_window.py`) et huit fichiers de tests font
  `from drum_player import DrumPlayer`.
- L'interface accède à environ 70 attributs et méthodes différents de
  `_player` (`_pattern` et `_cur_track` 51 fois chacun, `voice_manager` 39
  fois, `_compute_offsets` 22 fois…). Les tests en touchent environ 150,
  dont beaucoup d'attributs privés (`_measure_start`, `_pending_patch`,
  `_count_in`…).
- Un seul patch de module dans les tests :
  `mock.patch("drum_player.time.perf_counter")`
  (`test_tape.py::test_compute_float_offset_shared_by_cc_and_bend`). Il
  vise `_compute_float_offset`, donc il cassera si cette méthode change de
  module.
- Toutes les méthodes lisent et écrivent l'état commun : `playing`,
  `recording`, `_measure_start`, `step_duration`, `_pattern`, `_wakeup`…

**`_run_thread` (250 lignes) mélange trois choses dans une seule boucle :**
1. construire la liste des événements de la mesure (tape, métronome, Note
   Repeat), l. 448-497 ;
2. attendre puis distribuer chaque événement selon son marqueur, l. 499-578 ;
3. gérer la fin de mesure : count-in, compteur de boucle, enchaînement
   des patterns d'un song, pause en fin de pattern, l. 579-669.

La variable locale `measure_start` est modifiée par les points 2 et 3, et
le `for … else` lie la fin de mesure au fait que la boucle d'événements
n'a pas été interrompue par `_wakeup`.

### Décisions validées (utilisateur, 2026-10-18)

**D1 — des mixins, pas de la composition.**
- Chaque bloc du tableau devient une classe mixin sans `__init__`, dans
  son propre fichier. `DrumPlayer` hérite de tous les mixins et garde
  `__init__`, les propriétés et les délégations de quantisation.
- L'état reste dans `DrumPlayer.__init__`, comme aujourd'hui. Les mixins
  lisent et écrivent `self.<attribut>` sans changement de code.
- L'interface publique et privée ne change pas. Aucun des ~70 accès de
  l'interface ni des ~150 accès des tests n'est à réécrire.
- C'est le modèle de `midi_editor_window.py` (Phase 6 étape 12a,
  `ui/mew_*.py`).

Alternative écartée — **composition** (un `Recorder`, un `Transport`…
qui reçoivent le player comme `owner`, comme `QuantizeManager`) :
- il faudrait des délégations pour chaque méthode publique, soit une
  trentaine de méthodes d'une ligne dans `DrumPlayer`, ou bien réécrire les
  appelants (`_player.recorder.record_hit(...)`) ;
- l'état étant entièrement partagé, chaque objet passerait son temps à
  lire `self._p.<attribut>` : la séparation ne serait que de façade.

**D2 — package `src/player/`, qui accueille aussi `drum_player.py` en fin
de chantier.**
- Les mixins vont dans un nouveau package `src/player/`, comme `src/midi/`
  (Phase 7 étape 3a) :

  | Fichier | Classe | Contenu |
  |---|---|---|
  | `player/dp_transport.py` | `TransportMixin` | thread, play/stop/pause, song, click, `stop_all`, `set_bpm` |
  | `player/dp_position.py` | `PositionMixin` | position, chaînes de statut, déplacements, `navigate_bar` |
  | `player/dp_playback.py` | `PlaybackLoopMixin` | `_run_thread` et les constantes `*_EVENT` |
  | `player/dp_live.py` | `LivePlayMixin` | `play_sound`, Note Repeat, volume, pan |
  | `player/dp_recording.py` | `RecordingMixin` | armement de l'enregistrement, calcul des positions, tous les `record_*`, `_record_nr_hit`, `_bend_log` |
  | `player/dp_erase.py` | `EraseMixin` | `toggle_erase`, effacement au passage et ciblé, `_clear_offset` |

- Pendant les déplacements des mixins, `src/drum_player.py` reste à sa
  place : les commits 8b1-8e1 ne touchent pas aux importeurs.
- **Dernier commit de code (8g1) : `drum_player.py` est déplacé dans
  `src/player/drum_player.py`** (`git mv`), pour le rangement. Il ne
  contient plus alors que la classe `DrumPlayer` (~200 lignes : imports,
  `__init__`, propriétés, délégations `_qm`). Les deux importeurs de
  `src/` et les huit fichiers de tests passent à
  `from player.drum_player import DrumPlayer`.
- Préfixe `dp_` : même logique que `mew_` (MidiEditorWindow) et `mw_`
  (MainWindow), il dit à quelle classe le mixin appartient.
- Noms de classe sans préfixe, comme les `mew_*` : `PositionMixin` plutôt
  que `NavigationMixin`, pour ne pas faire doublon avec
  `ui/mew_navigation.py::NavigationMixin`.
- Imports : absolus, comme le reste de `src/` (`from pattern import …`,
  `from player.dp_recording import RecordingMixin`).
- Les constantes `*_EVENT` passent dans `PlaybackLoopMixin` :
  `DrumPlayer.GRID_EVENT` reste accessible par héritage.

**D3 — déplacer d'abord, restructurer `_run_thread` ensuite, dans des
commits séparés.**
- Les commits de déplacement (8b1-8d1) copient le code **à l'identique** :
  pas de renommage, pas de reformatage, `git diff --color-moved` doit
  montrer des blocs déplacés et rien d'autre.
- Ensuite seulement (8e1), `_run_thread` est découpé en trois méthodes du
  même mixin, une par point de l'état des lieux :
  - `_build_measure_events(lp_start, lp_end, total_steps, loop_bars, elapsed)`
    → la liste triée ;
  - `_dispatch_event(track_or_type, evt_data, velocity, t_sec)` → le
    grand `if/elif` sur le marqueur ;
  - `_on_measure_end(measure_start, measure_secs, lp_start)` → retourne
    le nouveau `measure_start`, pour garder la variable locale
    explicite.
  - L'attente active (`while … sleep`) et le `for … else` restent dans
    `_run_thread`, qui retombe à ~50 lignes.
- Raison : un déplacement pur se relit en un coup d'œil ; un découpage de
  méthode demande une vraie relecture. Les mélanger cacherait un
  éventuel changement de comportement dans un gros diff.
- C'est aussi la zone que l'export MIDI devra comprendre (ordre de rejeu,
  temps des événements).

**D4 — les patchs de test suivent le code.**
- `mock.patch("drum_player.time.perf_counter")` devient
  `mock.patch("player.dp_recording.time.perf_counter")` dans le même
  commit que le déplacement de `_compute_float_offset` (8c1), pour garder
  la suite verte à chaque commit.
- Le déplacement de `drum_player.py` (8g1) met à jour les imports des
  tests dans le même commit. Vérifier le contenu indexé avant de
  committer : un `git add -A` après un `git mv` suivi d'éditions peut
  rater des lignes.

### Portée explicitement exclue de ce chantier

- Tout changement de comportement. La suite de tests existante (1746)
  doit passer à chaque commit sans autre modification que les patchs et
  imports de D4.
- **Rassembler les quatre copies de `_bend_log`** (`drum_player.py`,
  `track_router.py`, `synth_engine.py`, `ui/midi_handler_window.py`) dans
  un module commun : **reporté à une prochaine étape**, après ce
  chantier. Ici, la copie de `drum_player.py` suit simplement
  `RecordingMixin` dans `player/dp_recording.py`.
- Déplacer de l'état hors de `DrumPlayer.__init__` (par exemple l'état
  du song vers un objet `SongState`) : ce serait un changement de
  structure de données, pas un découpage de fichier.
- `QuantizeManager`, `LoopManager`, `Metronome` : déjà séparés, non
  touchés.
- L'Import/Export MIDI lui-même. Il ne s'ajoutera probablement pas à
  `DrumPlayer` : la lecture/écriture d'un `.mid` travaille sur un
  `Pattern`, elle ira plutôt dans `src/midi/`. Ce sera décidé dans son
  propre plan.

### Découpage en commits

| Étape | Contenu | Fichiers |
|---|---|---|
| **8a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **8b1** | Refactor — package `src/player/` (`__init__.py`), `TransportMixin` et `PositionMixin` déplacés à l'identique, `DrumPlayer` en hérite. | `drum_player.py`, `player/__init__.py`, `player/dp_transport.py`, `player/dp_position.py` |
| **8c1** | Refactor — `RecordingMixin` (avec `_bend_log`) et `EraseMixin` déplacés à l'identique ; patch de test de D4. | `drum_player.py`, `player/dp_recording.py`, `player/dp_erase.py`, `tests/test_tape.py` |
| **8d1** | Refactor — `LivePlayMixin` et `PlaybackLoopMixin` (avec les constantes `*_EVENT`) déplacés à l'identique. `drum_player.py` ne garde que `__init__`, les propriétés et les délégations. | `drum_player.py`, `player/dp_live.py`, `player/dp_playback.py` |
| **8e1** | Refactor — `_run_thread` découpé en `_build_measure_events`, `_dispatch_event`, `_on_measure_end` (D3). Comportement inchangé. | `player/dp_playback.py` |
| **8f1** | Tests — tests unitaires des trois nouvelles méthodes : liste d'événements (fenêtre de boucle, filtre `elapsed`, ordre bend avant note au même temps, Note Repeat) ; distribution vers les bons callbacks ; fin de mesure (count-in, compteur de boucle, enchaînement et bouclage de song, pause en fin de pattern). | `tests/test_playback_loop.py` (nouveau) |
| **8g1** | Refactor — `git mv src/drum_player.py src/player/drum_player.py` ; imports mis à jour (`from player.drum_player import DrumPlayer`). | `player/drum_player.py`, `ui/main_window.py`, `ui/midi_handler_window.py`, 8 fichiers de `tests/` |
| **8h1** | Doc — clôture (DESIGN.md, structure de `CLAUDE.md`/`docs/SPECS.md` si elle liste les fichiers), `grep -rn "drum_player"` sur tout le dépôt, `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, autres docs si besoin |

Ordre choisi :
- Deux mixins par commit, par paires de blocs voisins, pour garder des
  diffs lisibles.
- Transport/position d'abord : ce sont les blocs les moins couplés au
  reste (ils n'appellent que `start_thread`/`stop_thread` et
  `_current_offset`).
- `_run_thread` en dernier parmi les mixins : c'est lui qui appelle
  presque tous les autres blocs (`_clear_offset`, `_erase_tape_event`,
  `_record_nr_hit`, `_mix_pan`, `_compute_offsets`).
- Déplacement de `drum_player.py` après tout le reste : le fichier est
  alors petit, et le commit ne contient que le `git mv` et des lignes
  d'import.
- Chaque commit de 8b1 à 8g1 laisse la suite verte : pas de paire
  implémentation/tests rouge dans ce chantier (8e1 est couvert par les
  tests existants, 8f1 ajoute des tests).

### Avancement et écarts constatés

- **8b1** (`e7a444c`) — conforme. `import math`, devenu inutile dans
  `drum_player.py`, est retiré.
- **8c1** — un seul écart au déplacement à l'identique : `_BEND_LOG_PATH`
  est calculé depuis `dirname(__file__)`. Dans `src/player/dp_recording.py`,
  il faut un `".."` de plus pour que `bend_log.txt` reste à la racine du
  dépôt. `os` et `TapeEvent`, devenus inutiles dans `drum_player.py`, sont
  retirés.
- **8d1** — conforme. `drum_player.py` tombe à 165 lignes : imports,
  `__init__`, propriétés et délégations `_qm`. `DrumPlayer` reçoit une
  docstring qui renvoie aux mixins. `time` et les `ETYPE_*`, devenus
  inutiles, sont retirés. L'import `LoopWindow`, déjà inutilisé avant le
  chantier, est laissé tel quel.
- **8e1** — un écart à D3 : l'attente de **fin de mesure** part dans
  `_on_measure_end` au lieu de rester dans `_run_thread`.
  - Le bloc `else` du `for` enchaîne trois choses : le pré-armement du
    dernier count-in, qui doit se faire *avant* l'attente ; l'attente
    elle-même ; puis la décision (count-in, compteur de boucle, song,
    pause), qui se fait *après*.
  - Garder l'attente dans `_run_thread` aurait coupé la logique du count-in
    en deux et demandé une quatrième méthode.
  - L'attente de chaque **événement** et le `for … else` restent bien dans
    `_run_thread`, qui fait maintenant 56 lignes.
  - Les corps des trois méthodes sont repris à l'identique, à l'indentation
    près : la comparaison du diff avec `-w` ne montre que les appels, les
    signatures, les docstrings et les `return`.
- **8f1** — conforme. 31 tests dans `tests/test_playback_loop.py`, qui
  appellent les trois méthodes directement, sans lancer le thread
  (1777 tests au total).
  - Contre-épreuve par mutations volontaires de `dp_playback.py` : 9
    mutations sur 10 font échouer au moins un test (tolérance de 2 ms,
    vélocité, override de durée, filtre Note Repeat, avance du song, pause
    en fin de pattern, garde `_wakeup` du count-in, attente de fin de
    mesure…).
  - La seule non détectée retire la borne basse de la fenêtre de boucle
    (`lp_start <= float_off`). Elle est sans effet : un événement avant
    `lp_start` a un `t_sec` négatif, déjà exclu par le filtre
    `t_sec > elapsed - 0.002` puisque `elapsed >= 0`. Ce n'est donc pas un
    trou de couverture. Le code n'est pas modifié, ce chantier ne change
    pas le comportement.
- **8g1** — conforme. `git mv` à 100 % de similarité (contenu inchangé).
  12 imports dans 11 fichiers, au lieu des 10 prévus : 2 dans `src/ui/` et
  9 fichiers de tests, en comptant le nouveau `test_playback_loop.py` de
  8f1. `test_tape.py` a deux imports. Index vérifié avant le commit.
  Aucun test ne lit `drum_player.py` par son chemin.

### Clôture (8h1)

**8a1-8g1 FAITS** (commits `a0fe487`..`79e83b5`, 1777 tests passed) —
**chantier Phase 7 étape 8 complet**. Aucun changement de comportement :
les 1746 tests d'avant le chantier passent sans autre modification que
les imports et le patch `perf_counter`, et 31 tests ont été ajoutés.

Résultat, `src/drum_player.py` (1148 lignes) devient le package
`src/player/` :

| Fichier | Lignes | Contenu |
|---|---|---|
| `drum_player.py` | 165 | `DrumPlayer` : état (`__init__`), propriétés, délégations `_qm` |
| `dp_transport.py` | 126 | `TransportMixin` |
| `dp_position.py` | 164 | `PositionMixin` |
| `dp_playback.py` | 290 | `PlaybackLoopMixin` : `_run_thread` (56 lignes) et ses trois étapes |
| `dp_live.py` | 55 | `LivePlayMixin` |
| `dp_recording.py` | 278 | `RecordingMixin` et `_bend_log` |
| `dp_erase.py` | 126 | `EraseMixin` |

Écarts au plan, détaillés plus haut :
- 8c1 : chemin `_BEND_LOG_PATH` ;
- 8e1 : attente de fin de mesure dans `_on_measure_end` ;
- 8g1 : 12 imports au lieu de 10.

`grep -rn "drum_player"` final : hors cette section et les sections
historiques de ce fichier, il ne reste que les imports
`from player.drum_player import DrumPlayer` (2 dans `src/ui/`, 10 dans
`tests/`), le nom d'un test (`test_drum_player_has_no_mod_tape_remnants`)
et l'arborescence de `docs/SPECS.md`, qui liste maintenant `player/`.

Restent hors périmètre :
- rassembler les quatre copies de `_bend_log` (reporté à une prochaine
  étape) ;
- l'import inutilisé `LoopWindow` de `drum_player.py` ;
- la borne basse redondante de la fenêtre de boucle dans
  `_build_measure_events` (voir 8f1) ;
- le reste de l'arborescence de `docs/SPECS.md`, en retard sur la Phase 7
  étape 3 : `midi_editor.py` et `midi_manager.py` y sont encore listés
  dans `src/` au lieu de `src/midi/`, et `ui/midi_handler.py` sous son
  ancien nom ;
- l'arborescence de `CLAUDE.md`, qui décrit la structure prévue au départ
  du projet et non les fichiers actuels.

Suite : l'Import/Export MIDI, en commençant par l'export.

---

## Phase 7 étape 9a1 — Un seul `_bend_log` pour tout le projet

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 8 : `9a1`, `9b1`, `9c1`… ; un
commit imprévu inséré après `9b1` s'appelle `9b2`, `9b3`, etc.

### Origine du besoin

La Phase 7 étape 8a1 a relevé quatre copies de `_bend_log` et a reporté
leur regroupement à une étape suivante. C'est cette étape, demandée par
l'utilisateur le 2026-10-18.

### État des lieux constaté en code (2026-10-18, 1777 tests verts)

**Quatre copies du même helper.** Chacune a un drapeau, un chemin et une
fonction :

```python
_BEND_LOG = os.environ.get("GROOVY_BEND_LOG") == "1"
_BEND_LOG_PATH = os.path.join(os.path.dirname(__file__), <..>, "bend_log.txt")

def _bend_log(msg):
    if not _BEND_LOG:
        return
    ts = time.strftime("%H:%M:%S")
    with open(_BEND_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
```

| Fichier | Chemin vers la racine | Alias de `time` | Appels | Messages |
|---|---|---|---|---|
| `player/dp_recording.py` | `"..", ".."` | `time` | 2 | `REC note_on`, `REC note_off` |
| `track_router.py` | `".."` | `_time` | 2 | `PLAY`, `BEND_AUTO` |
| `synth_engine.py` | `".."` | `_time` | 2 | `ENGINE_PLAY` (deux variantes) |
| `ui/midi_handler_window.py` | `"..", ".."` | `_time` | 2 | `BEND_SET`, `REC_READ` |

- Les quatre copies écrivent dans le même fichier, `bend_log.txt` à la
  racine du dépôt. Seule la profondeur du fichier change le nombre de
  `".."`. C'est cette différence qui a demandé une correction en Phase 7
  étape 8c1, quand `dp_recording.py` a changé de dossier.
- Le drapeau est lu une fois, à l'import de chaque module.
- Imports qui ne servent qu'au log :
  - `track_router.py` : `os` et `_time` (`import os, time as _time`) ;
  - `ui/midi_handler_window.py` : `os` et `_time` ;
  - `synth_engine.py` : `_time` seulement, `os` sert ailleurs ;
  - `dp_recording.py` : `os` seulement, `time` sert ailleurs
    (`perf_counter`).
- Aucun test ne couvre le log, et aucun ne patche `_bend_log` ou
  `_BEND_LOG`.
- `bend_log.txt` n'est pas dans `.gitignore`. Il n'existe pas en ce moment
  dans le dépôt.
- Le projet n'utilise pas le module `logging` de Python.

### Décisions validées (utilisateur, 2026-10-18)

**D1 — un module `src/bend_log.py`, avec une fonction publique
`bend_log(msg)`.**
- Le module contient le drapeau `_ENABLED`, le chemin `_LOG_PATH` et
  `bend_log(msg)`, avec exactement le comportement actuel : même variable
  d'environnement, même fichier, même format `[HH:MM:SS] message`.
- Placé à la racine de `src/`, à côté de `app_config.py` : il n'appartient
  à aucun sous-package. Le chemin vers la racine du dépôt n'est donc
  écrit qu'une fois, `".."`.
- Les quatre fichiers font `from bend_log import bend_log`, et leurs 8
  appels passent de `_bend_log(...)` à `bend_log(...)`. Leurs copies et
  les imports qui ne servaient qu'au log sont retirés.
- Les messages ne changent pas.

Alternatives écartées :
- **Module `logging` de Python** (un logger `"groovy.bend"` avec un
  `FileHandler`). Ce serait plus standard, mais il faudrait configurer les
  handlers au démarrage, et le format changerait. Le besoin, un fichier de
  traces activé à la demande pour déboguer le pitch bend, ne le justifie
  pas.
- **Un log générique** `debug_log(channel, msg)`, prévu pour d'autres
  traces. Aucun autre besoin n'existe aujourd'hui. Il sera facile de
  généraliser `bend_log.py` le jour où il y en aura un.
- **Garder le nom `_bend_log` aux appels** (`from bend_log import
  bend_log as _bend_log`), pour un diff plus court. Un alias qui cache une
  fonction publique sous un nom privé rend le code moins clair, pour un
  gain de 8 lignes.

**D2 — lecture du drapeau inchangée, à l'import du module.**
- Comme aujourd'hui, `GROOVY_BEND_LOG=1` doit être posée avant de lancer
  l'application.
- Les tests changent `bend_log._ENABLED` et `bend_log._LOG_PATH` par
  `monkeypatch`, sans toucher à l'environnement.

**D3 — `bend_log.txt` ajouté à `.gitignore`.**
- C'est un fichier de traces local. Il ne doit pas être committé par
  erreur après une session de débogage.

### Portée explicitement exclue de ce chantier

- Le contenu et le nombre des messages de log.
- Les autres traces de débogage du projet (`print` éventuels) et toute
  adoption du module `logging`.
- Le reste de l'arborescence de `docs/SPECS.md`, en retard sur la Phase 7
  étape 3 (voir la clôture de la Phase 7 étape 8). Seule la ligne de
  `bend_log.py` y est ajoutée.

### Découpage en commits

| Étape | Contenu | Fichiers |
|---|---|---|
| **9a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **9b1** | Implémentation — `src/bend_log.py` (D1, D2) ; les quatre copies sont remplacées par l'import, 8 appels renommés, imports devenus inutiles retirés ; `bend_log.txt` dans `.gitignore` (D3). | `bend_log.py`, `player/dp_recording.py`, `track_router.py`, `synth_engine.py`, `ui/midi_handler_window.py`, `.gitignore` |
| **9c1** | Tests — drapeau éteint : aucun fichier créé ; drapeau allumé : une ligne `[HH:MM:SS] message` ajoutée par appel, à la suite des précédentes ; chemin par défaut à la racine du dépôt ; les quatre modules appellent la même fonction et n'ont plus de copie (`_BEND_LOG` absent). | `tests/test_bend_log.py` (nouveau) |
| **9d1** | Doc — clôture (DESIGN.md, ligne `bend_log.py` dans l'arborescence de `docs/SPECS.md`), `grep -rn "_bend_log\|_BEND_LOG"` sur tout le dépôt, `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- 9b1 laisse la suite verte, puisqu'aucun test ne touche le log : pas de
  paire implémentation/tests rouge dans ce chantier.
- Avant de committer 9b1, une vérification à la main : lancer un
  enregistrement avec `GROOVY_BEND_LOG=1` est impossible ici, faute de
  clavier MIDI. Elle est remplacée par un appel direct de chaque module
  avec le drapeau allumé, qui doit écrire dans le même fichier.

### Avancement et écarts constatés

- **9b1** — conforme. Avec `GROOVY_BEND_LOG=1`, les quatre modules
  pointent sur la même fonction et écrivent une ligne chacun dans
  `bend_log.txt` à la racine du dépôt. `git check-ignore` confirme que
  ce fichier est ignoré.
- **9c1** — conforme, avec un test de plus que prévu (texte non ASCII,
  les messages `ENGINE_PLAY` contiennent « → »). 9 tests dans
  `tests/test_bend_log.py`, 1786 au total.
  - Le fichier de log des tests va dans `tmp_path`, grâce au `monkeypatch`
    de `_ENABLED` et `_LOG_PATH` : les tests n'écrivent jamais à la racine
    du dépôt.
  - Contre-épreuve sur le code d'avant 9b1 : les tests ne s'importent pas,
    `bend_log.py` n'existant pas encore. C'est peu parlant, d'où une
    contre-épreuve par mutations volontaires de `bend_log.py`. Les 5 sont
    détectées : écriture en mode `"w"`, drapeau ignoré, horodatage retiré,
    chemin hors de la racine, encodage ASCII.

### Clôture (9d1)

**9a1-9c1 FAITS** (commits `943f351`..`abe04a9`, 1786 tests passed) —
**chantier Phase 7 étape 9 complet**.

- **D1** — `src/bend_log.py` remplace les quatre copies de `_bend_log` :
  un seul drapeau, un seul chemin, une seule fonction `bend_log(msg)`,
  utilisée par `player/dp_recording.py`, `track_router.py`,
  `synth_engine.py` et `ui/midi_handler_window.py`. Le comportement, le
  fichier et le format sont inchangés. Le code compte 10 lignes de moins.
- **D2** — le drapeau est toujours lu à l'import. Les tests le changent par
  `monkeypatch`.
- **D3** — `bend_log.txt` est dans `.gitignore`.

Le chemin vers la racine n'est plus écrit qu'une fois. Déplacer un
fichier qui utilise le log ne demande donc plus de le corriger, comme
il avait fallu le faire en Phase 7 étape 8c1.

`grep -rn "_bend_log\|_BEND_LOG"` final : hors des sections historiques
de ce fichier, ces noms n'apparaissent plus que dans les docstrings de
`bend_log.py` et de `test_bend_log.py`, et dans le test qui vérifie leur
absence (`test_no_local_copy_left`). `docs/SPECS.md` liste
`bend_log.py` dans son arborescence.

Rien n'est laissé hors périmètre en plus de ce que le plan excluait.

Suite : l'Import/Export MIDI, en commençant par l'export.

---

## Phase 7 étape 10a1 — Export MIDI (.mid) du pattern courant

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 9 : `10a1`, `10b1`, `10c1`… ; un
commit imprévu inséré après `10b1` s'appelle `10b2`, `10b3`, etc.

### Origine du besoin

C'est le but final annoncé dès la Phase 7 étape 1b (§ « Conformité avec le
but final ») : l'import et l'export de fichiers MIDI standard (SMF). Les
préalables sont faits :
- toutes les données d'un pattern vivent dans `_tape`, avec `time` flottant
  et `channel` (Phase 7 étapes 1, 4, 5, 6) ;
- le bend est un état de canal, porté par les seuls `ETYPE_BEND`, comme en
  MIDI (Phase 7 étape 7).

L'utilisateur a demandé le 2026-10-18 d'attaquer l'export en premier.
L'import fera l'objet d'une partie séparée. En validant le plan, il a
ajouté :
- un `requirements.txt` ;
- un canal réglable par piste ;
- des patterns à 16 pistes par défaut.

### État des lieux constaté en code (2026-10-18, 1786 tests verts)

**Les données.** `Pattern._tape[t]` est une liste plate de `TapeEvent` par
piste (`pattern.py:17`) :

| etype | payload | `dur` | Rejeu (`dp_playback.py`, `track_router.py`) |
|---|---|---|---|
| `GRID` | `pad`, `vel` (0..127, 100 par défaut) | ms, 0 = durée de la voix du pad | slot SYNTH : note `_kb_notes_play[pad]` ; sinon `drum_sounds[pad]` |
| `KIT` | `note`, `vel` | toujours 0 (one-shot, `record_kit_note`) | `snd.play_note(note)`, quel que soit le slot |
| `PATCH` | `note`, `vel` | ms, 0 = 500 ms | muet si le slot de la piste n'est pas SYNTH |
| `CC` | `cc_num`, `value` | 0 | 64/120/121/123 globaux ; 1, 7, 10 sur la piste |
| `PGM` | `program` | 0 | pont provisoire `assign_slot(track, program % 16)` |
| `BEND` | `value` (-8192..+8191) | 0 | moteur du slot SYNTH, plage ±2 demi-tons (`synth_engine.py:108`, défaut GM) |

- `channel` est le canal d'origine, capturé en live (`dp_recording.py`).
  Il vaut 0 pour tout ce qui vient de la grille ou du Numpad.
- La note jouée pour un `GRID` dépend de l'état hors `_tape` :
  - sur une piste SYNTH, `scale_midi_notes(pattern._kb_scale,
    pattern._kb_root_midi, 16)[pad]` (`track_router.py:91`, figé par
    pattern via `set_playback_kb`) ;
  - sur une piste kit, `drum_sounds[pad]`, c'est-à-dire la note
    `snd.kit_base + snd.kit_offset + pad` (`sound_manager.py:164`), et
    `kit_base` vient du kit chargé (36 par défaut).
- La durée par défaut d'un `GRID` vient du `VoiceManager` du player
  (`voice_manager.get_duration_ms(pad)`). Le nom d'une piste (F2) est
  stocké au même endroit, `voice_manager.get_name(track)`
  (`mw_tracks.py:78`).
- L'état de mixage de chaque piste vit dans `TrackRouter` :
  `_track_slots`, `_track_mutes`, `_track_solos`, `_track_volumes`,
  `_track_pans`. `Pattern` n'en garde une copie qu'au rangement dans le
  store (`mw_patterns.py`), et c'est cette copie qui est sérialisée.

**Nombre de pistes : 8, en dur à plusieurs endroits.**
- `Pattern._num_tracks = 8` (`pattern.py:130`), alors que
  `Pattern.MAX_TRACKS = 16`.
- `TrackRouter.NUM_TRACKS = 8` (`track_router.py:36`) dimensionne ses
  listes de pistes.
- La liste des pistes de la fenêtre principale : `range(8)`
  (`main_window.py:282`).
- `docs/SPECS.md` annonce « 8 pistes par pattern ».
- `from_dict` relit `num_tracks` (8 pour tout `.gvp` existant), et les
  listes `track_*` telles quelles.
- La plupart des autres lectures passent déjà par `pattern._num_tracks`.

**Ordre de rejeu à temps égal.** `_build_measure_events` trie des tuples
`(t_sec, marqueur, données, vélocité)`. Les marqueurs donnent l'ordre
`PGM (-8)`, `CC (-7)`, `GRID (-6)`, `BEND (-4)`, `PATCH (-3)`, `KIT (-2)` :
le bend passe avant les notes PATCH. Point resté ouvert en Phase 7
étape 7 : deux `BEND` au même temps sur une piste.
- Le tri compare ensuite `données = (t_idx, value)` : c'est la valeur la
  plus haute qui est appliquée en dernier.
- `Pattern._bend_state_at`, lui, retient le dernier dans l'ordre de `_tape`.
- Les deux peuvent donc différer.

**Le temps : une incohérence du lecteur.** Le pas réel est toujours une
double croche, quel que soit `_num_steps` :
- `step_duration = 60.0 / bpm / 4` est écrit à quatre endroits :
  `drum_player.py:40`, `dp_transport.py:125` (`set_bpm`), et
  `dp_playback.py:260` et `:275` (enchaînement du song) ;
- tout le reste place un temps tous les `_num_steps // _num_beats` pas :
  le métronome (`metronome.py:51`), la quantisation, les dialogues
  temporels, `dp_position.py` et l'éditeur MIDI.

Conséquence : un pattern de 32 pas en 4/4 dure deux fois plus longtemps
que ne l'annonce son BPM, et le métronome y bat à BPM/2 (BPM/4 pour 64 pas,
BPM/8 pour 128 pas).
- Le Note Repeat compense sans le savoir : `interval = 16.0 / denom` pas
  (`dp_playback.py:122`) suppose 16 pas par mesure.
- `_num_beats` vaut toujours 4. Il n'est ni sérialisé, ni copié par
  `copy_from`, ni modifiable dans l'UI.
- `_denumerator` n'est lu nulle part.
- `step_duration` n'est recalculé que par `set_bpm`. L'enchaînement du song
  ne le recalcule que si le BPM change (`if next_pat._bpm != self.bpm`).
- Les patterns de 16 pas, le cas par défaut, ne sont pas touchés : pour eux,
  la formule actuelle est juste.

**Les outils.** `mido` 1.3.3 est installé avec `python-rtmidi` 1.5.8, mais
le projet ne l'importe nulle part (`midi_manager.py` utilise `rtmidi`
directement).
- Il n'existe ni `requirements.txt` ni module d'écriture SMF.
- Dépendances tierces réellement importées par `src/` et `tools/` :
  `wx`, `pygame`, `sounddevice`, `numpy`, `soundfile`, `pyrubberband`,
  `rtmidi`.
- La table des dépendances est dans `docs/SPECS.md`.

**Raccourci.** Ctrl+Shift+E est pris (« Choisir la ligne + quant et générer
le motif », `key_handler_ctrl.py:143`). Alt+Shift+E est libre dans la
fenêtre principale, l'éditeur MIDI et la fenêtre Songs.

### Décisions validées (utilisateur, 2026-10-18)

**D1 — corriger d'abord le lecteur : un pas dure
`60 · num_beats / (bpm · num_steps)` secondes.**
- Un temps (une noire, `_denumerator` restant ignoré) dure exactement
  `60 / bpm`, quelle que soit la résolution. Le lecteur est alors d'accord
  avec le métronome, la quantisation et l'affichage.
- Pour 16 pas et 4 temps, la formule redonne `60 / bpm / 4` : les patterns
  par défaut ne changent pas.
- Une seule méthode `DrumPlayer._update_step_duration()` calcule la valeur
  à partir de `self.bpm` et du pattern live. Elle remplace les quatre
  copies de la formule, et elle est appelée :
  - par `set_bpm` ;
  - à chaque enchaînement de pattern du song, que le BPM change ou non ;
  - après un redimensionnement du pattern live
    (`mw_patterns._resize_live_pattern`).
- Le Note Repeat passe de `16.0 / denom` à `num_steps / denom` pas : une
  division `1/denom` reste une fraction de la mesure.
- Effet accepté : les patterns existants de 32, 64 ou 128 pas jouent 2, 4
  ou 8 fois plus vite qu'avant, désormais au tempo affiché. Les durées
  `dur`, en ms, ne bougent pas.

Alternatives écartées :
- **Garder le lecteur et exporter « son et mesures fidèles »** (tempo
  `4·bpm·num_beats/num_steps`). Le .mid sonnerait comme l'appli, mais le
  tempo écrit différerait du BPM affiché, et l'incohérence resterait.
- **Exporter tempo = BPM sans corriger le lecteur.** Le .mid sonnerait plus
  vite que l'appli dès 32 pas.

**D2 — 16 pistes par pattern par défaut.**
- On passe aux 16 canaux MIDI : `Pattern._num_tracks = 16`,
  `TrackRouter.NUM_TRACKS = 16`, et la liste des pistes de la fenêtre
  principale suit `_num_tracks`, sans `range(8)` en dur.
- **Migration** : `from_dict` porte tout pattern de moins de 16 pistes à 16.
  - `_tape` est complété par des pistes vides ;
  - chaque liste `track_*` est complétée par sa valeur par défaut (slot 0,
    pas de mute ni de solo, volume 100, pan 0, canal par défaut, D5).
  - Un `.gvp` existant s'ouvre donc avec 16 pistes, les 8 premières
    inchangées.
- Les autres lectures passent déjà par `pattern._num_tracks` : elles
  suivent sans changement.

Alternative écartée : garder 8 pistes pour les anciens patterns et 16 pour
les nouveaux. Le nombre de pistes varierait d'un pattern à l'autre, alors
que `TrackRouter` a des listes de taille fixe.

**D3 — portée : le pattern courant.**
- On exporte le pattern live (`player._pattern`), avec l'état courant de
  `TrackRouter` et du `VoiceManager`, même s'il n'est pas encore rangé dans
  le store.
- Toute la longueur est exportée, de la mesure 1 à `_num_bars`, sans tenir
  compte des loop points, de `_loop_count` ni de `_start_bar`.
- Le song viendra dans une étape ultérieure, avec le même moteur : on
  enchaînera les patterns et on posera un meta tempo à chaque changement de
  BPM.

Alternatives écartées : pattern et song dès le départ, ou projet entier.
Le song et le projet posent d'autres questions (tempo variable,
organisation des pistes), qu'il vaut mieux traiter une fois le moteur
éprouvé.

**D4 — SMF de type 1, PPQ = 480.**
- **Piste 0 (conductor)** à tick 0 :
  - `track_name` = nom du pattern, ou `Pattern_NN` s'il n'en a pas ;
  - `set_tempo` = `bpm2tempo(bpm)`, exact grâce à D1 ;
  - `time_signature` = `num_beats/4`.
- **Une piste SMF par piste Groovebox non vide**, dans l'ordre, avec
  `track_name` = nom de la piste (F2), ou `Track NN` (numéro d'origine,
  1-based). Les pistes vides sont omises.
- Chaque piste se termine par `end_of_track` au plus tard de deux instants :
  la fin du pattern (`num_bars · num_steps` pas) ou le dernier note-off.
  Ainsi la longueur du pattern est conservée même si sa dernière mesure
  est vide.
- Avec 480 ticks par noire, l'écart reste sous 0,3 ms à 120 BPM pour les
  `time` flottants de la capture live.

Alternatives écartées :
- **Type 0** : une seule piste, et l'import ne retrouverait pas le découpage
  en pistes.
- **PPQ 96 ou 960** : 96 est trop grossier pour le timing libre, 960
  n'apporte rien d'audible.

**D5 — canal MIDI de chaque piste : un canal stocké par piste, piste N →
canal N par défaut, réglable dans les propriétés de la piste.** Cette
décision a été simplifiée par l'utilisateur le 2026-10-20 (Phase 7 étape
10a2). La version de 10a1 est rappelée dans les alternatives écartées.

Chaque piste porte un canal, une valeur stockée et non recalculée, et
l'export y écrit tous ses événements, quel que soit leur etype.

- **Défaut** : la piste N reçoit le canal N, pour N de 1 à 16. La piste 10
  est donc sur le canal 10, celui de la batterie GM. Toute piste au-delà de
  la 16e reçoit le canal 16. Ce cas n'existe pas encore, puisque
  `MAX_TRACKS = 16`, mais la règle est posée pour l'avenir.
- **Assigner un slot kit à une piste** la met sur le canal 10. C'est le cas
  par le choix du slot de la fenêtre principale (`_assign_track_slot`) et
  par `TrackPropertiesDialog`.
- **Assigner un slot qui n'est pas un kit** (synthé, vide ou autre) à une
  piste dont le canal est 10 la ramène à son canal par défaut. La piste 10
  reste donc sur le canal 10. Un autre canal choisi à la main n'est pas
  touché.
  - Limite assumée : aucun drapeau ne retient si le canal 10 a été choisi
    à la main ou posé par un kit. Un 10 choisi à la main sur une piste
    autre que la 10 revient donc lui aussi au défaut dès qu'on lui assigne
    un synthé.
- **Ce qui ne change pas le canal** :
  - le pont provisoire Program Change → `assign_slot` (live et rejeu) ;
  - la restauration des slots au chargement d'un projet ;
  - le chargement d'un kit dans un slot.
  
  Pour cela, la règle est appliquée dans les deux actions utilisateur
  ci-dessus, et non dans `TrackRouter.assign_slot`.
- **Choix manuel** : `TrackPropertiesDialog` gagne une `ListBox` « Canal »
  de 16 entrées, `Canal 1` à `Canal 16`.
  - Elle se place après Slots dans l'ordre Tab.
  - Elle a le même aperçu en temps réel et le même Annuler que les autres
    champs.
  - L'action entre dans l'Undo comme les autres propriétés de piste.
  - Changer de slot dans le dialogue applique la règle du kit et met à jour
    la sélection de la liste Canal. L'utilisateur peut ensuite la changer.
  - Aucune vérification de collision : deux pistes sur un même canal le
    partagent, c'est le choix de l'utilisateur.
- **Données** : `_track_channels`, une liste d'entiers 0..15, avec
  `min(t, 15)` pour la piste `t` (0-based) par défaut.
  - Comme les autres réglages de piste, elle vit dans `TrackRouter`, est
    copiée dans `Pattern` au rangement, et est sérialisée dans le `.gvp`
    sous `track_channels`.
  - Clé absente, cas d'un ancien `.gvp`, ou liste trop courte (migration
    D2) : on complète avec le défaut par index.
  - La règle du kit n'est pas rejouée sur les slots existants : un ancien
    projet s'ouvre comme un nouveau pattern, canal N pour la piste N.
  - Un nouveau pattern a aussi le canal N sur la piste N, bien que ses 16
    pistes pointent par défaut sur le slot 1, qui est un kit (TR-707,
    `main_window.py:112`). Seule une assignation explicite déclenche la
    règle.
- **Portée** : le canal de piste ne sert qu'à l'export pour l'instant. Le
  rejeu et la capture ne changent pas, et `ev.channel` reste le canal
  d'origine capturé. Ce réglage prépare l'adressage par canal du mode Rack
  GM.
- `ev.channel` n'est pas écrit dans le fichier : c'est une perte assumée.
- Un événement `KIT` est écrit sur le canal de sa piste comme tout le
  reste, même si la piste n'est pas sur le canal 10. Il n'y a pas
  d'exception par etype.

Exemple : piste 1 sur un kit (assigné), pistes 2 et 4 sur un même synthé,
piste 3 sur un autre synthé. On obtient piste 1 → 10, piste 2 → 2,
piste 3 → 3, piste 4 → 4. Pour que les pistes 2 et 4 partagent un canal,
on règle la piste 4 sur le canal 2 dans ses propriétés.

Alternatives écartées :
- **Canal automatique calculé à l'export (version 10a1)**. Un canal par slot
  SYNTH distinct, partagé par les pistes du même synthé, kit sur 10, avec
  une surcharge manuelle `None`/0..15. Écartée le 2026-10-20 par
  l'utilisateur, au profit d'une règle plus simple et visible : le canal
  est une valeur de la piste, que l'utilisateur voit et règle, au lieu d'un
  résultat recalculé selon les autres pistes.
- **Le canal d'origine `ev.channel`**, fidèle et utile à l'aller-retour.
  Mais tout ce qui vient de la grille est sur le canal 1.
- **Canal = numéro de slot du Rack** : il s'appuie sur le pont
  `assign_slot`, qui est provisoire.

**D6 — notes, vélocités, durées.**
- **Note d'un `GRID`** : sur une piste SYNTH,
  `scale_midi_notes(pattern._kb_scale, pattern._kb_root_midi, 16)[pad]` ;
  sur une piste kit, `kit_note_base + pad`, avec
  `kit_note_base = snd.kit_base + snd.kit_offset`, l'état courant, comme
  au rejeu.
- **`KIT` et `PATCH`** : la note du payload.
- **Vélocité** : celle du payload, bornée à 1..127, une vélocité 0 valant
  note-off en MIDI.
- **Durées** :
  - `GRID` : `dur` s'il est positif, sinon la durée de la voix du pad
    (`voice_manager`) ;
  - `PATCH` : `dur` s'il est positif, sinon 500 ms, comme au rejeu ;
  - `KIT` : un pas (one-shot), puisque `dur` y vaut toujours 0. Un lecteur
    GM ignore de toute façon le note-off sur le canal 10.
- **Conversions** :
  - temps : `tick = round(time · PPQ · num_beats / num_steps)` ;
  - durée : `ticks = round(dur_ms / 1000 · bpm / 60 · PPQ)`, au minimum
    1 tick ;
  - c'est cohérent avec D1 : un temps dure `60 / bpm` secondes.
- **Notes qui se chevauchent** : une même note sur un même canal, rejouée
  avant son note-off, recevrait ce note-off au milieu de la note suivante.
  Le note-off de la première est donc avancé juste avant le note-on
  suivant, comme le ferait un clavier. Cette règle vaut à l'intérieur d'une
  piste SMF. Entre pistes qui partagent un canal (D5), le cas est laissé au
  lecteur.

**D7 — ordre d'écriture à tick égal.**
- L'ordre est : note-off, `PGM`, `CC`, `BEND`, note-on. C'est celui du
  rejeu (PGM, CC, bend, notes), avec les note-off d'abord, pour qu'une note
  qui finit libère la place avant celle qui commence.
- À catégorie égale, le tri est stable sur l'ordre de `_tape`. Deux `BEND`
  au même temps : le dernier dans `_tape` gagne, comme dans
  `_bend_state_at` (donc l'éditeur et le chase du bend). L'écart avec le
  tri du rejeu (valeur la plus haute en dernier) est noté hors périmètre.

**D8 — `mido` pour écrire le fichier, et un `requirements.txt`.**
- `mido` est déjà installé et servira aussi à l'import. Le code à écrire et
  à tester se limite à la traduction `_tape` → messages, sans codec SMF
  maison.
- **`requirements.txt`** à la racine du dépôt, avec les dépendances
  tierces réellement importées. On y met un plancher de version, celui
  installé le 2026-10-18 :
  ```
  wxPython>=4.2.3
  pygame>=2.6.1
  sounddevice>=0.5.5
  numpy>=2.4.3
  soundfile>=0.13.1
  pyrubberband>=0.4.0
  python-rtmidi>=1.5.8
  mido>=1.3.3
  ```
  - `pytest` sert seulement aux tests. Il est indiqué en commentaire dans
    le fichier, avec la commande d'installation Debian
    (`pip3 install ... --break-system-packages`), plutôt que d'être exigé.
  - `pedalboard`, marqué « futur » dans `docs/SPECS.md`, n'y est pas.
- `mido` est ajouté à la table des dépendances de `docs/SPECS.md`.

Alternative écartée : écrire le SMF à la main (MThd/MTrk, delta-times en
VLQ). Aucune dépendance, mais il y aurait plus de code et de tests, et un
parseur à écrire aussi pour l'import.

**D9 — un module `src/midi/midi_export.py`, sans wx ni player.**
- `build_pattern_midi(pattern, track_channels, track_is_synth,
  track_names, kit_note_base, voice_durations) -> mido.MidiFile` contient
  toute la logique de D4, D6 et D7.
  - `track_channels` est la liste stockée de `TrackRouter` (D5).
  - Les états hors `Pattern` lui sont passés en paramètres : type de slot
    de chaque piste, noms des pistes, `kit_base + kit_offset`, durées des
    voix.
- `export_pattern(path, ...)` appelle `build_pattern_midi`, puis
  `MidiFile.save(path)`.
- Lecture de `_tape` sous `pattern._lock`, sur une copie, comme
  `_build_measure_events`.
- La fonction se teste sans wx, en relisant le fichier avec `mido`.

**D10 — UI : Alt+Shift+E.**
- Dans la fenêtre principale et dans l'éditeur MIDI (même pattern live),
  Alt+Shift+E ouvre un `wx.FileDialog` d'enregistrement :
  - filtre `*.mid` ;
  - nom proposé : le libellé du pattern, nettoyé, plus `.mid` ;
  - dossier proposé : `AppConfig.exports_dir`, nouvelle clé `exports_dir`,
    qui vaut par défaut le dossier `EXPORTS` voisin de `projects_dir` et
    est créé au besoin ;
  - `wx.FD_OVERWRITE_PROMPT`.
- Le résultat s'affiche dans la barre de statut : `Pattern NN exporté :
  <fichier>`, ou le message d'erreur. Orca l'annonce.
- La fenêtre Songs n'a pas d'export dans ce chantier : il viendra avec le
  song (D3).
- `docs/shortcuts.md` est mis à jour.

### Portée explicitement exclue de ce chantier

- L'export d'un song ou du projet entier, et le tempo variable (D3).
- L'import MIDI.
- L'effet du canal de piste sur le rejeu ou la capture live (D5). Il ne
  sert qu'à l'export en attendant le mode Rack GM.
- Le volume et le pan des pistes (CC7/CC10 initiaux) : plusieurs pistes
  peuvent partager un canal (D5), et leurs réglages entreraient en
  conflit. Mute et solo sont ignorés : toutes les pistes non vides sont
  exportées.
- Le canal d'origine `ev.channel`, perdu à l'export (D5). L'aller-retour
  export/import sans perte sera à revoir avec l'import.
- La plage de bend (RPN 0) : elle vaut ±2 demi-tons, le défaut GM, donc
  rien à écrire tant qu'elle n'est pas réglable.
- `_denumerator` et un `_num_beats` réglable (D1 garde la noire comme
  temps).
- L'écart du rejeu sur deux `BEND` au même temps (D7) : c'est un correctif
  séparé de `_build_measure_events`, s'il est voulu.
- L'export depuis la fenêtre Songs (D10).
- Le passage de 16 à 128 pads (chantier futur séparé).

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **10a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **10a2** | Doc — D5 simplifiée : piste N → canal N, kit assigné → canal 10, réglage manuel. | `docs/DESIGN.md` |
| **10b1** | Implémentation — `_update_step_duration()` (D1) remplace les quatre formules ; appels dans `set_bpm`, l'enchaînement du song (sans condition) et `_resize_live_pattern` ; Note Repeat en `num_steps / denom`. | `player/drum_player.py`, `player/dp_transport.py`, `player/dp_playback.py`, `ui/mw_patterns.py` |
| **10c1** | Tests — durée du pas pour 16/32/64/128 pas ; 16 pas inchangé ; recalcul à l'enchaînement du song à BPM égal mais à `num_steps` différent ; recalcul au redimensionnement ; métronome à un clic par `60/bpm` ; intervalle du Note Repeat. Mise à jour des tests existants qui supposaient `60/bpm/4` avec un `num_steps` autre que 16, s'il y en a. | `tests/test_transport.py`, `tests/test_playback_loop.py`, … |
| **10d1** | Implémentation — 16 pistes par défaut (D2) : `Pattern`, `TrackRouter.NUM_TRACKS`, liste des pistes de la fenêtre principale, migration dans `from_dict`. | `pattern.py`, `track_router.py`, `ui/main_window.py`, `docs/SPECS.md` |
| **10e1** | Tests — nouveau pattern à 16 pistes ; ancien `.gvp` à 8 pistes porté à 16, avec ses 8 premières pistes et ses `track_*` inchangés ; navigation et sélection jusqu'à la piste 16 ; mise à jour des tests qui supposaient 8 pistes. | `tests/test_pattern.py`, `tests/test_pattern_serialization.py`, `tests/test_track_router.py`, … |
| **10f1** | Implémentation — canal de piste (D5) : `_track_channels` dans `TrackRouter` et `Pattern` (défaut par index, rangement, chargement, sérialisation `track_channels`, complétion des listes courtes) ; règle du kit (canal 10, retour au défaut) dans `_assign_track_slot` et le dialogue ; `ListBox` Canal dans `TrackPropertiesDialog`, aperçu, Annuler et Undo. | `track_router.py`, `pattern.py`, `ui/dialogs_properties.py`, `ui/mw_tracks.py`, `ui/mw_patterns.py` |
| **10g1** | Tests — défaut piste N → canal N ; assigner un kit → 10 ; puis un synthé → retour au défaut (piste 10 reste sur 10, canal manuel autre que 10 conservé) ; Program Change et chargement de projet sans effet sur le canal ; sérialisation (clé absente ou liste courte = défaut) ; dialogue : choix, règle du kit au changement de slot, Annuler, Undo. | `tests/test_track_channels.py` (nouveau), `tests/test_track_properties_dialog.py`, `tests/test_pattern_serialization.py` |
| **10h1** | Implémentation — `src/midi/midi_export.py` (D4, D6, D7, D9) ; `requirements.txt` (D8). | `midi/midi_export.py` (nouveau), `requirements.txt` (nouveau), `docs/SPECS.md` (dépendance `mido`) |
| **10i1** | Tests — relecture par `mido` : en-tête type 1 et PPQ ; conductor (nom, tempo, signature) ; une piste par piste non vide, avec son nom ; chaque événement sur le canal de sa piste (D5), `KIT` compris ; notes GRID synth/kit, KIT, PATCH ; vélocités bornées ; durées par défaut ; conversions de temps à 16 et 32 pas ; chevauchement ; ordre à tick égal et deux BEND au même temps ; CC/PGM/BEND ; `end_of_track` à la fin du pattern ; pattern vide. | `tests/test_midi_export.py` (nouveau) |
| **10j1** | Implémentation — Alt+Shift+E dans la fenêtre principale et l'éditeur MIDI ; `FileDialog` ; `AppConfig.exports_dir` ; statut (D10). | `ui/key_handler_alt.py`, `ui/mew_keymap.py`, `ui/mw_project.py`, `app_config.py`, `docs/shortcuts.md` |
| **10k1** | Tests — `exports_dir` (défaut, valeur relative, valeur absolue) ; le handler appelle l'export avec les bons paramètres (FileDialog simulé) ; Annuler n'écrit rien ; erreur d'écriture affichée. | `tests/test_app_config.py`, `tests/test_midi_export_ui.py` (nouveau) |
| **10l1** | Doc — clôture (DESIGN.md, `docs/SPECS.md` : arborescence, 16 pistes, canal de piste, export MIDI), `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- 10b1 et 10d1 peuvent casser des tests existants, qui figent `60/bpm/4`
  sur plus de 16 pas, ou 8 pistes. Si `pytest` est rouge à l'un de ces
  commits, le titre le dira, et le commit de tests suivant le réparera.
- Avant de committer 10b1 : une écoute à la main d'un pattern de 32 pas,
  dont le métronome doit battre au BPM affiché.
- Avant de committer 10d1 : ouvrir un `.gvp` existant et vérifier que les
  8 premières pistes jouent comme avant.
- Avant de committer 10h1 : un fichier exporté est ouvert dans un lecteur
  externe (`timidity` ou un DAW, s'il y en a un), pour vérifier qu'il se
  lit, le tempo, et la batterie sur le canal 10.

### Avancement et écarts constatés

- **10b1** — conforme à D1, avec deux appels de plus que prévu.
  `_num_steps` du pattern live change aussi à deux autres endroits :
  - l'action « Nouveau » du dialogue de propriétés du pattern
    (`mw_patterns.py`, `live.new_pattern(num_bars, num_steps)`) ;
  - `DrumPlayer.load_pattern` (matrice dense).

  Les deux appellent désormais `_update_step_duration()`.
  - L'annulation passe par `_apply_pattern_from_store` → `set_bpm`, et
    l'ouverture d'un projet aussi : elles sont déjà couvertes.
  - `step_duration` reste un attribut, et non une propriété calculée :
    plusieurs tests l'affectent directement.

  À 120 BPM, une mesure de 4 temps dure 2,0 s pour 16, 32, 64 et 128 pas.
  `pytest tests/` est resté vert (1786) : aucun test existant ne figeait
  `60/bpm/4` sur un pattern de plus de 16 pas.
- **10c1** — conforme. `tests/test_step_duration.py` contient 24 tests, ce
  qui porte le total à 1810. Ils couvrent :
  - la formule à 16, 32, 64 et 128 pas, et 16 pas inchangé à plusieurs BPM ;
  - `set_bpm` et `load_pattern` ;
  - l'enchaînement du song et son retour au début, à BPM égal mais avec une
    résolution différente ;
  - Redimensionner (`_resize_live_pattern`), et les actions « Courant » et
    « Nouveau » du dialogue de propriétés, simulé ;
  - le métronome à un clic toutes les `60/bpm` secondes ;
  - le Note Repeat en 1/16, qui donne 16 doubles croches par mesure quelle
    que soit la résolution.

  Pendant l'écoute de 10b1, le Note Repeat a semblé ne pas réagir aux
  touches 1 à 9. La cause était le focus resté sur la liste des patterns
  (exclusion volontaire, `key_handler_chars.py:261`), et non le code de
  10b1. Ce comportement reste hors de ce chantier.
  - Aucun test existant n'avait à changer.
  - Contre-épreuve par 7 mutations volontaires, toutes détectées :
    - l'ancienne formule `60/bpm/4` ;
    - le recalcul conditionné au BPM, aux deux points du song ;
    - le Note Repeat en `16/denom` ;
    - un appel `_update_step_duration()` retiré, tour à tour dans
      Redimensionner, Nouveau et `load_pattern`.
- **10d1** — conforme. `Pattern._extend_tracks(n)` est appelé en fin de
  `from_dict`. Il reconstruit les listes au lieu de les étendre en place, car
  elles peuvent venir du dict de l'appelant (cache d'undo).
  - Vérifié sur les trois `project_0N.gvp`, encore à l'ancien format
    `curpattern`, 8 pistes. Après chargement, ils ont 16 pistes, les 8
    premières inchangées, et le dict d'origine n'est pas modifié.
  - L'utilisateur a validé à la main : 16 pistes, rejeu inchangé.
  - Suite rouge, comme prévu : 15 tests figent 8 pistes, à réparer en 10e1.
- **10d2** — commit imprévu, validé à la main par l'utilisateur (les quatre scénarios : prise vide, prise jouée, Remplacement à vide, Erase) : une prise live marque le projet modifié et
  s'annule d'un bloc.
  - **Constat de l'utilisateur pendant la vérification de 10d1** : après un
    enregistrement live, la fermeture ne proposait pas d'enregistrer. Le
    bug existait avant ce chantier. Seul `_add_undo` appelle
    `_mark_modified`, et rien sur le chemin de l'enregistrement live (R,
    Shift+R, Ctrl+R, Erase, notes du pavé numérique ou du clavier MIDI)
    n'appelle `_add_undo`. Une prise n'était donc ni signalée à la
    fermeture, ni annulable par Ctrl+Z.
  - **Décision de l'utilisateur, 2026-10-20** : un Undo avant la prise, retiré
    à la fin si rien n'a été enregistré. Enregistrer « du vide » pour
    effacer une partie de piste doit compter comme une modification.
  - **Mise en œuvre** (`ui/mw_project.py`) :
    - `_take_begin(title)` appelle `_add_undo` (titres « Enregistrement
      piste N », « Remplacement piste N », « Erase piste N ») et retient la
      signature de `_tape` du pattern live, l'état « modifié » d'avant, et
      l'entrée d'Undo créée.
    - `_take_end_if_idle()` ferme la prise dès que le player n'enregistre
      plus, n'efface plus et n'est plus en décompte. Si `_tape` est
      identique et que l'entrée de la prise est toujours la dernière de
      l'historique, elle est retirée, et l'état « modifié » est rétabli :
      `was_modified and modifié actuel`, pour qu'une sauvegarde faite
      pendant la prise reste prise en compte.
    - Une prise déjà ouverte n'en ouvre pas une seconde : un Erase pendant
      un Rec fait partie de la même prise.
  - **Effacer sans jouer est couvert par construction** : en Remplacement
    ou en Erase, les notes effacées au passage changent `_tape`, donc la
    prise est gardée.
  - **Ouvertures** : R, Shift+R, Ctrl+R (`key_handler_chars.py`,
    `key_handler_ctrl.py`) et l'activation d'Erase.
  - **Fermetures** : après chaque touche traitée par la fenêtre principale
    (`MainWindow._on_char_hook`), ce qui couvre tous les arrêts au clavier
    (R, Shift+R, E, V, Ctrl+F12…). Aussi au début de `_on_close`, de
    `_new_project` et de `_open_project`.
    - `_take` est remis à `None` au chargement et à la création d'un
      projet.
    - Un arrêt fait depuis l'éditeur MIDI ou la fenêtre Songs
      (`handle_transport`) ne ferme la prise qu'à la touche suivante dans
      la fenêtre principale, ou à la fermeture. Dans ce cas, une prise vide
      peut garder le projet marqué modifié : c'est un faux positif sans
      perte de données, accepté.
  - **`UndoManager.last_entry()`** est une nouvelle méthode de lecture, qui
    ne retire rien.
  - Les tests de `test_key_manager.py` qui appuient sur R, Shift+R, Ctrl+R
    ou E échouent à ce commit, car leur `FakeWindow` n'a pas `_take_begin`.
    Ils sont réparés en 10d3, avec les tests de la prise.
- **10d3** — tests de la prise. 21 nouveaux tests, 1830 au total, dont 15
  encore rouges, ceux de 10d1, à réparer en 10e1.
  - `tests/test_live_take.py`, 16 tests sur une fenêtre factice qui utilise
    les vrais `_add_undo`, `_take_begin` et `_take_end_if_idle` :
    - prise vide retirée, que le projet ait été modifié avant ou non ;
    - prise jouée gardée ;
    - Remplacement et Erase qui effacent sans rien jouer : prise gardée ;
    - payload modifié : prise gardée ;
    - pas de fermeture pendant Rec, Erase ou décompte ;
    - deuxième ouverture pendant une prise : un seul Undo ;
    - sauvegarde pendant une prise vide ;
    - autre action annulable pendant la prise ;
    - entrée de la prise déjà annulée par Ctrl+Z ;
    - changement de pattern pendant la prise ;
    - branchement dans `MainWindow._on_char_hook` et `_on_close`.
  - `test_key_manager.py` : la `FakeWindow` gagne `_take_begin`, qui note
    l'état du player au moment de l'appel. On vérifie ainsi que R,
    Shift+R, Ctrl+R et E ouvrent la prise avant de lancer le Rec ou
    l'Erase. Les arrêts n'ouvrent pas de prise. Un nouveau test couvre E
    quand Erase est déjà actif.
  - `test_undo_manager.py` : 3 tests de `last_entry`.
  - Contre-épreuve par 14 mutations volontaires de 10d2, toutes détectées :
    - signature ignorée, entrée jamais retirée, pas d'attente du repos ;
    - sauvegarde ignorée, entrée non vérifiée, deuxième prise ouverte ;
    - payload hors signature ;
    - prise ouverte après le Rec, prise ouverte aussi à la désactivation
      d'Erase ;
    - Ctrl+R sans prise, Shift+R sans prise ;
    - `_on_char_hook` sans fermeture, `_on_close` sans fermeture ;
    - `last_entry` qui renvoie la première entrée.
  - Écart corrigé avant le commit : le test de `_on_char_hook` dépendait de
    l'ordre des tests, car `wx.Window.FindFocus` exige un `wx.App`. Il est
    maintenant remplacé par `monkeypatch`.
- **10e1** — tests des 16 pistes. La suite redevient verte : 1841 tests.
  - **15 tests existants mis à jour.** Ils figeaient 8 pistes et lisent
    maintenant `Pattern.DEFAULT_NUM_TRACKS` ou `TrackRouter.NUM_TRACKS` au
    lieu d'un `8` en dur.
    - `test_track_router.py` : 6 tests.
    - `test_pattern_serialization.py` : 7 tests, et son `NUM_TRACKS` suit
      la constante.
    - `test_pattern.py` : 2 tests.

    Aucune assertion n'a changé de sens.
  - **Nouveau fichier `tests/test_sixteen_tracks.py`**, 11 tests :
    - valeurs par défaut à 16 pistes, router aligné ;
    - migration d'un preset `tape_v2` à 8 pistes : 8 premières pistes
      inchangées, pistes 9 à 16 vides avec les réglages par défaut ;
    - migration de l'ancien format `curpattern` à 8 pistes ;
    - preset sans clés `track_*` ;
    - dict de l'appelant intact, listes non partagées ;
    - preset à 16 pistes relu tel quel ;
    - preset migré réécrit à 16 pistes ;
    - grille et tape de la piste 16 conservées ;
    - solo sur la piste 16 ;
    - sélection Shift+↓ jusqu'à la piste 16, puis Ctrl+A.
  - **Contre-épreuve par 6 mutations volontaires de 10d1** :
    - détectées : `DEFAULT_NUM_TRACKS = 8`, migration non appelée, listes
      étendues en place, `_tape` non complété, `TrackRouter.NUM_TRACKS = 8` ;
    - non détectée : « `_tracks` non complété ».
  - **Écart avec 10d1, corrigé** : la mutation non détectée a montré que la
    ligne de `_extend_tracks` qui complétait `_tracks` était du code mort.
    - `Pattern.__init__` crée déjà 16 objets `Track`, `from_dict` ne réduit
      jamais cette liste, et rien d'autre ne la lit.
    - La ligne est retirée de `pattern.py` dans ce commit.
  - Non couvert par un test automatique : la liste des pistes de la
    fenêtre principale, dimensionnée par `_num_tracks`, parce qu'il faudrait
    construire la vraie `MainWindow`. Elle a été vérifiée à la main par
    l'utilisateur en 10d1.
- **10f1** — canal de piste, validé à la main par l'utilisateur (ordre Tab, règle du kit dans le dialogue, Ok/Ctrl+Z, Annuler sans étoile, aller-retour .gvp), conforme à D5 (version 10a2), avec trois
  précisions.
  - **Données** :
    - `Pattern.KIT_CHANNEL = 9` et `Pattern.default_channel(t) = min(t, 15)`,
      le canal par défaut selon l'index ;
    - `Pattern._track_channels` est sérialisé sous `track_channels` ;
    - `_extend_tracks` complète cette liste avec le canal par défaut de
      chaque index ;
    - `TrackRouter._track_channels` est synchronisé comme les autres
      réglages de piste : `_flush_pattern_to_store`,
      `_apply_pattern_from_store`, et l'enchaînement du song dans
      `mw_songs.py`.
  - **Règle du kit** :
    - `TrackRouter.channel_after_slot(track, slot, channel)` est la fonction
      pure : kit → 9 ; autre slot sur 9 → défaut ; sinon inchangé ;
    - `assign_slot_by_user` combine `assign_slot` et la règle ;
    - `_assign_track_slot` l'utilise, et son message de statut annonce le
      nouveau canal. Le pont Program Change et le chargement de projet
      gardent `assign_slot`, sans effet sur le canal.
  - **Dialogue** : `TrackPropertiesDialog` gagne les paramètres `channel` et
    `channel_after_slot`, avec une `ListBox` « Canal 1 » à « Canal 16 »
    placée après Slots dans l'ordre Tab.
    - Changer de slot applique la règle et met à jour la sélection du
      canal.
    - `on_change` reçoit le canal en sixième argument.
    - Nouvelle méthode `get_channel()`.
  - **Précision 1, l'Undo** : contrairement à ce que disait D5 (« comme les
    autres propriétés de piste »), le dialogue de propriétés de piste
    n'avait aucun Undo, et un changement de slot, de volume ou de pan ne
    marquait pas le projet modifié.
    - Il pose maintenant un Undo avant de s'ouvrir, sur le schéma de F2.
    - Cet Undo est retiré si l'on annule ou si rien n'a changé, et l'état
      « modifié » d'avant est alors rétabli.
    - Cela vaut pour toutes les propriétés, pas seulement le canal.
  - **Précision 2** : le choix du slot dans la fenêtre principale
    (`_assign_track_slot`) n'a toujours pas d'Undo. Ce comportement
    préexistant est laissé tel quel, hors chantier.
  - **Précision 3** : le test `test_on_change_receives_initial_values` de
    `test_track_properties_dialog.py` attend 5 arguments. Il est rouge à ce
    commit et sera mis à jour en 10g1.
- **10g1** — tests du canal de piste. La suite redevient verte : 1866
  tests.
  - **`tests/test_track_channels.py`**, 18 tests :
    - défaut piste N → canal N, plafonné à 16 ;
    - aller-retour `to_dict`/`from_dict` ;
    - clé absente ;
    - liste courte complétée selon l'index, dict de l'appelant intact ;
    - `set_track_channel` borné ;
    - règles de `channel_after_slot` : kit → 10, retour au défaut, piste 10
      sur 10, canal manuel gardé, slot vide ;
    - `assign_slot_by_user` ;
    - `assign_slot` seul et le pont Program Change ne touchent pas au
      canal ;
    - synchronisation par `_flush_pattern_to_store`,
      `_apply_pattern_from_store` et l'enchaînement du song ;
    - Ctrl+T : le statut annonce le canal ;
    - dialogue de propriétés simulé : canal et règle transmis, Ok avec
      changement, Ok sans changement et Annuler.
  - **`test_track_properties_dialog.py`**, 7 tests ajoutés, et le test
    `on_change` passe à 6 valeurs :
    - liste de 16 canaux ;
    - ordre Tab Slots → Canal → Volume ;
    - `on_change` reçoit le canal ;
    - règle appliquée au changement de slot, aller et retour ;
    - sans règle, le canal ne change pas ;
    - le choix manuel n'appelle pas la règle.
  - **Écart avec 10f1, corrigé dans ce commit** (`pattern.py`). Le test de la
    clé absente a montré un vrai bug :
    - `from_dict` gardait les canaux déjà présents dans l'objet quand
      `track_channels` manquait ;
    - or Ctrl+O recharge un projet dans les `Pattern` existants
      (`mw_project.py`, `self._pattern_list[i].from_dict(p)`) ;
    - ouvrir un `.gvp` d'avant 10f1, c'est-à-dire tous les projets
      existants, gardait donc les canaux du projet précédent.

    Désormais, une clé absente remet les canaux par défaut. Les autres
    clés `track_*` ont le même comportement depuis toujours. Il n'est pas
    corrigé ici, car tous les `.gvp` existants contiennent ces clés.
  - **Contre-épreuve par 21 mutations volontaires** de 10f1 et du
    correctif, toutes détectées. Une première version de la mutation
    « Canal créé après Pan » était mal construite. Elle a été refaite, et
    elle est détectée.
- **10h1** — `src/midi/midi_export.py` et `requirements.txt`, avec quatre
  écarts au plan.
  - **Écart 1, signature** : le pattern live ne porte ni la gamme, ni le
    nom, ni le BPM, car `copy_from` ne recopie que les dimensions et
    `_tape`. D6 calculait la note d'une case de grille synthé à partir de
    `pattern._kb_scale`, ce qui aurait donné la gamme par défaut.
    - `build_pattern_midi(pattern, *, name, bpm, track_channels,
      track_is_synth, track_names, kit_note_base, synth_grid_notes,
      voice_durations)` reçoit donc ces valeurs en arguments nommés.
    - `synth_grid_notes` est la liste de lecture du router
      (`_kb_notes_play`), exactement ce que joue le rejeu.
  - **Écart 2, canaux** : un événement `KIT` est écrit sur le canal de sa
    piste, comme le veut D5 révisée en 10a2. Le texte de D6 et D9, écrit
    avant 10a2, ne le précisait pas.
  - **Écart 3, doublons** : D6 ne traitait pas le cas d'une même note
    jouée deux fois au même tick. Elle est écrite une seule fois, faute de
    quoi un note-off serait placé avant son propre note-on.
  - **Écart 4, `requirements.txt` sans pygame**, sur remarque de
    l'utilisateur.
    - Vérifié : avec `pygame` bloqué à l'import, `main`,
      `ui.main_window`, le player et le MIDI se chargent.
    - Seuls `src/pygame_driver.py` (ancien driver, plus importé par
      l'application), `tests/test_pygame_driver.py`,
      `tests/test_sound_manager.py` et `tools/bench_latency.py` l'utilisent.
    - pygame est cité en commentaire avec pytest, comme dépendance
      facultative.
    - La table des dépendances de `docs/SPECS.md` est corrigée : elle
      donnait encore pygame pour l'audio des kits. La ligne `mido` y est
      ajoutée.
  - **Vérification avant commit** : les patterns 1 et 2 de
    `project_01.gvp` ont été exportés par un script, puisque l'interface
    n'arrive qu'en 10j1. Les pistes sur un slot kit ont été mises sur le
    canal 10, comme après une assignation.
    - Relecture par mido : type 1, 480 ticks par noire, une piste
      conductor puis une piste par piste non vide, canaux 1, 3, 4 et 10,
      note-on et note-off appariés.
    - Rendu sans erreur par FluidSynth (FluidR3_GM).
    - Écoute par l'utilisateur : les deux fichiers se lisent, les notes des instruments et la batterie sont reconnaissables. Mais sans Program Change, toutes les pistes mélodiques jouent le son de piano par défaut. Ce manque est traité en 10h2 et suivantes.
  - **Constat à trancher, hors de ce commit** : le nom de piste exporté
    vient de `voice_manager.get_name(t)`. C'est le même stockage que le
    nom F2 et que l'affichage de la liste des pistes. Or ce stockage est
    indexé par pad, et il contient les libellés du kit (« Kick 2 »,
    « Kick 1 »…). Les pistes SMF portent donc ces noms tant qu'aucune
    piste n'a été renommée.

### Phase 7 étape 10h2 — Plan complémentaire : Program Change par slot (instrument GM ou kit GM2), noms de pistes

**Origine.** Écoute de 10h1 par l'utilisateur, le 2026-10-20. Sans Program
Change, un lecteur GM joue toutes les pistes mélodiques avec son programme
par défaut, le piano. Il faut écrire en tête de chaque piste l'instrument
voulu. L'écoute a aussi montré des pistes SMF nommées d'après des pads
(« Kick 2 »…).

**État des lieux.**
- Les patches (`PATCHS/*.json`) ne portent aucun numéro de programme GM :
  seulement `name`, `loop` et `sounds` ou `samples`.
- `InstrumentSlot.config` est un dict libre, sérialisé tel quel dans le
  `.gvp` (`rack.to_dict`).
- `midi_constants.GM_PATCH_NAMES` donne les 128 noms GM, l'index étant le
  numéro de programme.
- `midi_constants.GM2_DRUMKIT_NAMES` donne les 9 kits GM2 nommés, aux
  programmes 0, 8, 16, 24, 25, 32, 40, 48 et 56. Les autres index ne sont
  pas des noms.
- Aucune boîte ne règle un slot : la liste des slots sert seulement à
  choisir et assigner.
- Le nom F2 d'une piste est stocké dans `voice_manager`, au même endroit
  que les noms de pads. On ne peut donc pas savoir si une piste a été
  renommée.

**Décisions validées (utilisateur, 2026-10-20).**

**D11 — un programme par slot : instrument GM pour un synthé, kit GM2
pour un kit.** Pour les kits, c'est une suggestion de l'utilisateur après
la première version de ce plan.
- **Stockage** : `InstrumentSlot.config["gm_program"]`, de 0 à 127. Il
  est sérialisé avec le Rack, sans changement de format.
- **Clé absente**, cas de tous les slots existants : le programme est
  déduit du nom du slot par `guess_gm_program(name, drums=False)`, une
  fonction pure placée dans `midi_constants.py`. Avec `drums=True`, la
  comparaison se fait avec les 9 kits GM2 au lieu des 128 instruments. La
  déduction fonctionne ainsi :
  - les mots du nom sont normalisés (minuscules, `_` et camelCase
    séparés, chiffres ignorés) ;
  - on retient le nom GM qui partage le plus de mots avec eux ;
  - à égalité, le plus petit numéro l'emporte ;
  - sans aucun mot commun, le programme 0 (Acoustic Grand Piano, ou
    Standard Kit pour un kit).

  Les chiffres sont ignorés : sinon « Piano 1 » donnerait « Electric
  Piano 1 ». En contrepartie, « My 808 » donne Standard Kit.

  Sur les patches existants, cela donne :
  - « Piano 1 », « Yamaha Grand Piano » → 0, Acoustic Grand Piano ;
  - « Acoustic Guitar 1 » → 24, Acoustic Guitar (nylon) ;
  - « DrawbarOrgan » et « organ_b3_basic_fast » → 16 ;
  - « Percussive Organ » → 17, « Rock Organ » → 18, « Church Organ » → 19,
    « Reed Organ » → 20 ;
  - kits : « TR-707 » → 25, TR-808 Kit, grâce au mot « tr » ;
    « GM (FluidR3) » → 0, Standard Kit.
- **Kits** : le programme choisit le kit GM2 ou GS. Un lecteur GM1 strict
  peut l'ignorer et garder son kit standard, sans dommage.
- **Export** : nouveau paramètre `track_programs`, avec par piste un
  programme ou `None`.
  - Un `program_change` est écrit au tick 0 sur le canal de la piste,
    avant tout événement de `_tape`. Un `ETYPE_PGM` capturé au tick 0
    passe donc après, et l'emporte.
  - L'appelant donne le programme du slot de la piste si ce slot est un
    synthé ou un kit. Pour un slot vide ou d'un autre type, il donne
    `None`.
- **Rejeu** : il ne change pas, puisque le son vient des échantillons. Le
  programme ne sert qu'à l'export et au futur mode Rack GM.

**D12 — nom de piste exporté = nom du slot.**
- La piste SMF prend `InstrumentSlot.name`, par exemple « Acoustic
  Guitar 1 » ou « TR-707 », et « Track NN » si le slot est vide.
- Le nom F2 n'est pas utilisé tant qu'il est mêlé aux noms de pads.
  Séparer les deux dans les données est un chantier distinct, hors
  chantier 10.
- Le module ne change pas, puisque `track_names` est déjà un paramètre :
  c'est l'appelant (10j1) qui lui passe les noms de slots.

**D13 — interface dans les propriétés de la piste.**
- `TrackPropertiesDialog` gagne une `ListBox` « Programme GM du slot » de
  128 entrées, « 1 - Acoustic Grand Piano » à « 128 - Gunshot », placée
  après Canal dans l'ordre Tab.
  - Elle montre le programme du slot sélectionné dans le dialogue.
  - **Son contenu suit le type du slot.** Pour un synthé : les 128
    instruments GM. Pour un kit : les 9 kits GM2, par exemple « 1 -
    Standard Kit » ou « 26 - TR-808 Kit ». Le numéro affiché est le
    programme + 1.
  - Elle est désactivée pour un slot vide ou d'un autre type.
  - Changer de slot dans le dialogue recharge la liste (instruments ou
    kits) et y sélectionne le programme du nouveau slot.
- Modifier le programme modifie le slot, donc toutes les pistes qui le
  jouent, avec aperçu immédiat comme les autres champs.
  - Annuler rétablit le programme d'origine de chaque slot touché.
  - L'Undo du dialogue (10f1) couvre ce changement, car
    `_capture_state` sérialise le Rack.
  - Valider sans rien changer, programme compris, retire l'Undo comme
    avant.

**Alternatives écartées** :
- un programme par piste, car deux pistes du même synthé pourraient
  alors avoir deux instruments ;
- une clé dans le fichier patch, qui obligerait à éditer les `.json` des
  patches ;
- une nouvelle boîte de propriétés du slot, qui ajouterait une boîte et
  un raccourci ;
- « Track NN » comme nom de piste par défaut, moins parlant que le nom de
  l'instrument.

**Hors périmètre** :
- la séparation entre noms de pistes et noms de pads ;
- la banque (CC0/CC32) ;
- l'écriture de `gm_program` par l'outil d'extraction SF2 ;
- les kits GS au-delà des 9 kits GM2 nommés.

**Découpage inséré** (avant 10i1, inchangé) :

| Étape | Contenu | Fichiers |
|---|---|---|
| **10h2** | Doc — ce plan complémentaire. | `docs/DESIGN.md` |
| **10h3** | Implémentation — `guess_gm_program(name, drums)` ; `slot_gm_program(slot)` (config ou déduction, instruments ou kits selon le type) ; paramètre `track_programs` de l'export ; `ListBox` Programme dans `TrackPropertiesDialog` (instruments ou kits selon le slot), avec aperçu, Annuler et Undo, branchée dans `mw_tracks.py`. | `midi/midi_constants.py`, `rack.py`, `midi/midi_export.py`, `ui/dialogs_properties.py`, `ui/mw_tracks.py` |
| **10h4** | Tests — déduction sur les noms GM, les kits GM2, les patches et kits existants ; `program_change` au tick 0 avant un `ETYPE_PGM`, kit compris ; `None` → rien d'écrit ; dialogue (128 instruments ou 9 kits selon le slot, ordre Tab, désactivé pour un slot vide, rechargé au changement de slot) ; Ok, Annuler et inchangé dans `mw_tracks`. | `tests/test_gm_program.py` (nouveau), `tests/test_track_properties_dialog.py`, `tests/test_track_channels.py` |

Avant de committer 10h3, il faudra réécouter un export des patterns 1 et 2
de `project_01.gvp`, cette fois avec leurs programmes, le kit TR-808
compris.
- **10h3** — conforme au plan 10h2, avec un point de vigilance et une
  limite.
  - **Ce qui est livré** :
    - `midi_constants.py` : `GM2_DRUMKITS`, c'est-à-dire les 9 kits nommés
      sous forme de couples (programme, nom), et
      `guess_gm_program(name, drums)` ;
    - `InstrumentSlot.gm_program()` lit la config si elle est valide,
      sinon déduit le programme ; il renvoie `None` hors synthé et kit ;
    - `InstrumentSlot.set_gm_program()` ;
    - le paramètre `track_programs` de l'export : un `program_change` au
      tick 0, de rang -1, donc avant un `ETYPE_PGM` capturé au même tick ;
    - la `ListBox` « Programme GM du slot » de `TrackPropertiesDialog`.
      Elle prend un nouveau paramètre `slot_program(slot)` qui renvoie
      (genre, programme) et une méthode `get_program()`. `on_change`
      reçoit 7 valeurs.
  - **Point de vigilance, l'Undo** : `InstrumentSlot.to_dict` renvoie le
    dict `config` lui-même, si bien que les instantanés d'Undo
    (`_capture_state` → `rack.to_dict()`) le partagent. Modifier `config`
    sur place aurait aussi modifié l'état mémorisé pour Ctrl+Z.
    - `set_gm_program` remplace donc `config` par un nouveau dict.
    - Pour Annuler, `mw_tracks` garde le dict d'origine de chaque slot
      touché et le remet en place.
  - **Limite** : changer le programme d'un slot A dans le dialogue, puis
    choisir un slot B et valider, garde le nouveau programme de A. C'est
    cohérent avec « modifier le programme modifie le slot ».
  - **Vérification d'export** : patterns 1 et 2 de `project_01.gvp`,
    relus par mido.
    - Pistes nommées « Acoustic Guitar 1 » (canal 1, programme 25),
      « TR-707 » (canal 10, TR-808 Kit, 26), « DrawbarOrgan » (canal 3,
      17), « Piano 1 » (canal 4, 1). Tous les programmes sont au tick 0.
    - Numéros affichés de 1 à 128.
  - **Écoute par l'utilisateur** : instruments et kit reconnus. L'orgue
    semblait absent du pattern 1. Vérification faite, le Program Change
    était bien appliqué : les rendus avec les programmes 1 et 17
    diffèrent. L'orgue sortait au même niveau que le piano, mais couvert
    par la guitare et la batterie. L'utilisateur l'a confirmé à l'oreille
    sur la piste seule.
  - **Constats de l'écoute**, pour la suite :
    - les volumes de piste ne sont pas exportés : ce sera l'étape 10h5,
      volume et pan, à la demande de l'utilisateur ;
    - un ancien projet garde sa piste kit sur le canal N, par exemple 2.
      Le Program Change du kit y choisit alors un instrument mélodique :
      sur le canal 2, la TR-707 joue en Acoustic Guitar (steel). La
      réponse viendra plus tard : soit migrer en passant les kits sur 10,
      soit réassigner le kit à la main.
  - **Suite rouge à ce commit**, 6 tests de l'ancienne interface du
    dialogue, à mettre à jour en 10h4 :
    - le `FakeDlg` de `test_track_channels.py` n'a pas `get_program` ;
    - `on_change` passe à 7 valeurs ;
    - l'ordre Tab est désormais Canal → Programme → Volume.
- **10h4** — tests du Program Change par slot. La suite redevient verte :
  1893 tests.
  - **Les 6 tests rouges de 10h3 sont réparés.**
    - Le `FakeDlg` de `test_track_channels.py` a maintenant
      `get_program`, et des valeurs à 7 éléments.
    - `on_change` passe à 7 valeurs.
    - L'ordre Tab est vérifié dans l'ordre de création. La liste
      Programme, désactivée sans `slot_program`, n'accepte pas le focus.
  - **`test_track_properties_dialog.py`**, 8 tests ajoutés :
    - 128 instruments pour un synthé, avec les libellés « 1 - … » à
      « 128 - Gunshot » ;
    - 9 kits pour un kit ;
    - liste vide et désactivée pour un slot vide ou sans `slot_program` ;
    - programme inconnu : aucune sélection ;
    - ordre Tab Canal → Programme → Volume ;
    - liste rechargée au changement de slot, synthé ↔ kit ↔ vide ;
    - `on_change` reçoit le numéro de kit et non l'index.
  - **Nouveau fichier `tests/test_gm_program.py`**, 19 tests :
    - déduction sur les 128 noms GM, les patches et les kits existants,
      les chiffres ignorés, les noms vides ou inconnus ;
    - `gm_program` : config, valeur invalide, types sans programme ;
    - `set_gm_program` remplace `config` et borne la valeur. Un
      instantané `rack.to_dict()` reste intact ;
    - export : `program_change` en premier au tick 0 sur le canal de la
      piste, rien si `None`, avant un `ETYPE_PGM` au tick 0, valeur
      bornée ;
    - `mw_tracks`, avec un dialogue factice qui joue l'aperçu : Ok avec
      un autre programme, Annuler (les dicts `config` d'origine sont
      remis, même pour un slot visité puis quitté), Ok sans changement,
      programme changé puis rétabli, kit GM2 choisi sur un slot kit.
  - **Écart avec 10h3, corrigé dans ce commit** (`midi_constants.py`). Le
    test sur les 128 noms GM a révélé un défaut :
    - « Electric Piano 1 » donnait Electric Grand Piano (2), qui partage
      les mêmes 2 mots, au lieu d'Electric Piano 1 (4) ;
    - une correspondance exacte des mots passe désormais avant le compte
      des mots communs ;
    - « Piano 1 » donne toujours 0, aucun nom GM ne se réduisant au seul
      mot « piano » ;
    - les exemples de D11 sont inchangés.
  - **Contre-épreuve par 22 mutations volontaires**, toutes détectées :
    - déduction : chiffres gardés, camelCase non coupé, correspondance
      exacte ignorée, égalité inversée, table GM utilisée pour les kits ;
    - `gm_program` et `set_gm_program` : config ignorée, bornes, kit
      traité comme un synthé, tout type accepté, modification sur place ;
    - export : Program Change mal placé ou sur le mauvais canal ;
    - dialogue : liste, libellés, désactivation, rechargement, index ;
    - `mw_tracks` : programme non écrit, Annuler sans restauration, kit
      vu comme un synthé.
