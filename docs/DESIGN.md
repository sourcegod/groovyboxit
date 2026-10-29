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
- **10h5** — implémentation : volume et pan de piste exportés, demandés
  par l'utilisateur après l'écoute de 10h3, et notes PATCH muettes omises.
  Cela lève l'exclusion « volume et pan des pistes » de D10.
  - **Découpage** : les tests sont dans un commit séparé, 10h6, à la
    demande de l'utilisateur (« quelle qu'en soit la taille »). La
    migration des kits annoncée en 10h6/10h7 devient donc **10h7/10h8**.
  - **Décisions** :
    - nouveaux paramètres `track_volumes` (0..100) et `track_pans`
      (-100..+100) de `build_pattern_midi`. L'appelant (10j1) passera les
      listes de `TrackRouter` ;
    - au tick 0 de chaque piste, l'ordre est : Program Change, puis CC7,
      puis CC10. Ils sont écrits pour toute piste non vide, kit compris, et
      même sans programme ;
    - un CC7 ou un CC10 capturé dans `_tape` au tick 0 vient après, et
      l'emporte ;
    - les conversions sont l'inverse de `TrackRouter.on_cc_tape` :
      `volume_to_cc7(v) = round(v·127/100)`, avec un aller-retour exact
      sur 0..100 ; `pan_to_cc10(p) = 64 + round(p·63/100)`, borné à
      1..127, avec −100, 0 et +100 donnant 1, 64 et 127 ;
    - pour le pan, l'aller-retour se fait à ±1 près, car le CC10 n'a que
      127 valeurs pour 201 positions. 74 positions sont touchées, 50 par
      exemple revenant à 51 ;
    - le volume 100 donne CC7 = 127, et non le 100 par défaut d'un lecteur
      GM : une piste à fond dans l'appli est à fond dans le fichier ;
    - canal partagé entre plusieurs pistes : chaque piste écrit ses
      valeurs, et le lecteur garde la dernière reçue. C'était la raison de
      l'exclusion initiale, acceptée désormais ;
    - toujours exclus : mute et solo, ainsi que le volume et le pan des
      pads (`voice_manager`), qui sont par pad et non par piste.
  - **Notes PATCH d'une piste sans slot synthé, non exportées.** Ce point
    a été demandé par l'utilisateur pendant l'écoute de 10h5.
    - Au rejeu, elles sont muettes (`TrackRouter.on_patch_tape`). Un
      lecteur GM les jouait pourtant, sur le canal du kit : la piste
      TR-707 du pattern 1 de `project_01.gvp` avait ainsi 15 notes PATCH,
      de 50 à 60, jouées en ride, chinese cymbal et toms aigus.
    - Ce comportement remplace la phrase de D6 « les données sont
      conservées », au nom du principe « le fichier sonne comme l'appli ».
    - Les notes GRID et KIT d'une piste kit restent exportées. Une piste
      qui n'aurait que des PATCH sur un kit garde sa piste SMF, sans note.
  - **Écoute par l'utilisateur** : la guitare, réglée à 45, est plus
    discrète, et l'orgue s'entend seul.
  - **Constats de l'écoute, hors du code de ce chantier** :
    - **Octave de l'orgue.** L'orgue sonnait une octave plus bas dans
      le fichier que dans l'appli. Le patch
      `PATCHS/DrawbarOrgan.json` déclarait la racine « C4 », alors que
      l'échantillon est mesuré à 523,5 Hz, soit C5 (note 72). L'appli
      jouait donc tout l'orgue une octave trop haut, et le fichier les
      notes réellement jouées.
      - Avec l'accord de l'utilisateur, la racine est corrigée en « C5 ».
      - Les parties d'orgue sont transposées de +12 : 31 notes dans
        `project_01.gvp` et 124 dans `project_03.gvp`, à l'ancien format,
        tous deux en pattern 1, piste 3.
      - Des sauvegardes ont été prises avant ces modifications.
      - Ces fichiers sont des données utilisateur, hors du dépôt.
    - **Kit non GM.** Le kit TR-707 n'est pas rangé selon la table GM.
      Sa note 49 est « Cowbell », mais en GM c'est une crash : ce sont les
      37 « cymbales très fortes » entendues. Une table de correspondance
      pad → note GM, déduite du libellé du pad, est proposée comme
      chantier séparé.
- **10h6** — tests de 10h5. Nouveau fichier `tests/test_midi_export_mix.py`,
  12 tests, 1905 au total.
  - **Conversions** :
    - bornes, et l'exemple 45 → 57 ;
    - aller-retour du volume exact sur 0..100 ;
    - aller-retour du pan à ±1 près, exact pour −100, 0 et +100. Pour 50,
      on obtient le CC 96, qui revient à 51.
  - **Export** :
    - Program Change, CC7 et CC10 au tick 0, dans cet ordre, sur le
      canal de la piste ;
    - CC7 et CC10 écrits même sans programme ;
    - `None` : rien d'écrit ;
    - un CC7 capturé au tick 0 est écrit après, et l'emporte ;
    - canal partagé : chaque piste écrit sa valeur.
  - **Notes PATCH** :
    - omises sur une piste kit, alors que GRID et KIT sont gardés ;
    - gardées sur une piste synthé ;
    - une piste kit qui n'a que des PATCH donne une piste SMF sans note.
  - **Contre-épreuve par 10 mutations volontaires de 10h5**, toutes
    détectées :
    - volume sur 100, volume tronqué ;
    - pan sans décalage, pan borné à partir de 0 ;
    - CC7 après les CC de `_tape`, CC10 avant CC7, CC7 avant le
      programme ;
    - canal 0 pour le volume, pan non écrit ;
    - PATCH toujours exportées.
- **10h7** — implémentation : à l'ouverture d'un projet sans canaux, les
  pistes kit passent sur le canal 10. C'est une décision de l'utilisateur
  du 2026-10-20, qui révise D5 : jusque-là, la règle du kit ne jouait qu'à
  une assignation explicite.
  - **Constat qui l'a motivée** : un ancien projet gardait sa piste kit sur
    le canal N. Le Program Change du kit y choisissait alors un instrument
    mélodique, par exemple Acoustic Guitar (steel) sur le canal 2.
  - **Mise en œuvre** :
    - `Pattern.from_dict` pose `_needs_kit_channels` quand la clé
      `track_channels` est absente. L'attribut est recalculé à chaque
      lecture, donc remis à `False` sur un `Pattern` réutilisé ;
    - `Pattern.apply_kit_channels(is_kit_slot)` met sur le canal 10 les
      pistes dont le slot est un kit, une seule fois, puis efface le
      drapeau ;
    - `mw_project._load_project` l'appelle juste après chaque
      `from_dict`. Le Rack est déjà lu à ce moment, et `Pattern` ne le
      connaît pas.
  - **Portée** :
    - seul `_load_project`, c'est-à-dire Ctrl+O et le démarrage, lit des
      fichiers ;
    - `_restore_state` (Undo) a toujours `track_channels`, il n'est donc
      pas concerné ;
    - un projet déjà enregistré avec ses canaux est laissé tel quel :
      `project_01.gvp` garde ses réglages.
  - **Effet à connaître** : les pistes vides passent aussi sur 10. Dans les
    anciens projets, elles pointent par défaut sur le slot 1, qui est un
    kit. Leur assigner un synthé les ramène à leur canal par défaut (règle
    de 10f1).
  - **Vérifié dans l'appli par l'utilisateur, et par script sur `project_02.gvp`** : dans les patterns 1 et 2, la piste 2
    (kit) passe sur 10 ; dans les patterns 3 à 5, la piste 1 (kit) passe
    sur 10. La piste synthé reste sur son canal.
- **10h8** — tests de 10h7. Nouveau fichier
  `tests/test_kit_channel_migration.py`, 7 tests, 1912 au total.
  - **Drapeau** : `_needs_kit_channels` n'est vrai que si la clé est
    absente, et il est remis à faux sur un `Pattern` réutilisé.
  - **Règle** : pistes kit sur 10, piste synthé gardée, pistes vides sur le
    slot kit.
  - **Une seule application** : `apply_kit_channels` n'agit qu'une fois.
  - **Canaux enregistrés** : intacts, y compris un kit laissé sur le canal
    2. Un projet migré puis réenregistré garde ses canaux.
  - **`_load_project` sur un vrai `.gvp` temporaire**, avec le vrai
    `ProjectMixin` et une fenêtre factice :
    - ancien projet migré, et le router reçoit le pattern migré ;
    - projet avec canaux laissé tel quel.
  - **Contre-épreuve par 7 mutations volontaires**, toutes détectées :
    - drapeau toujours faux, jamais remis, non effacé, ou non testé ;
    - kit ignoré, toutes les pistes passées sur 10 ;
    - chargement sans migration.
- **10h9** — correctif d'un bug antérieur à ce chantier, repéré en écrivant
  10h7 : après Ctrl+O, l'Undo pouvait réinjecter des patterns de l'ancien
  projet.
  - **Cause** :
    - `_capture_state` ne re-sérialise que les patterns marqués dans
      `_pattern_cache_dirty`, et le pattern courant ;
    - `_new_project` remet tout le cache à neuf, mais `_load_project` ne
      le faisait pas ;
    - après l'ouverture d'un projet B, le cache gardait donc les dicts du
      projet A pour tous les patterns sauf le courant ;
    - la première action annulable prenait alors un instantané mélangé, et
      un Ctrl+Z jusqu'à ce point remettait dans B des patterns de A.
  - **Reproduit par un script avant le correctif** : l'instantané pris
    après l'ouverture de B donnait les noms `['B', 'A', 'A']`, et
    `['B', 'B', 'B']` après.
  - **Correctif** : `_load_project` marque tous les patterns comme périmés
    (`_pattern_cache_dirty = set(range(...))`) juste après leur lecture.
  - **Hors périmètre** : l'historique d'Undo n'est pas vidé à l'ouverture
    d'un projet. Ctrl+Z juste après Ctrl+O revient à un état de l'ancien
    projet, comme avant ce chantier. C'est un comportement à discuter à
    part.
- **10h10** — tests de 10h9. Nouveau fichier
  `tests/test_load_project_cache.py`, 3 tests, 1915 au total. Ils
  utilisent les vrais `_capture_state`, `_add_undo` et `_load_project`
  sur un `.gvp` temporaire :
  - l'instantané pris après Ctrl+O ne contient que les patterns du projet
    ouvert ;
  - tous les patterns sont marqués à re-sérialiser ;
  - une entrée d'Undo prise après l'ouverture ne contient aucun pattern de
    l'ancien projet.

  **Contre-épreuve** : avec le code d'avant 10h9, les 3 tests échouent.
- **10i1** — tests du module d'export, conformes au plan. Nouveau fichier
  `tests/test_midi_export.py`, 18 tests, 1933 au total. Le fichier est
  relu par mido, en temps absolus. Le Program Change, le volume et le pan
  ont déjà leurs tests en 10h4 et 10h6.
  - **Fichier** :
    - écrit puis relu, type 1, 480 ticks par noire ;
    - conductor : nom, tempo, 4/4, fin à la fin du pattern ;
    - pattern vide : conductor seule ;
    - une piste SMF par piste non vide, avec son nom ou « Track NN » ;
    - fin de piste à la fin du pattern, ou au dernier note-off s'il
      déborde.
  - **Canaux et notes** :
    - tout est écrit sur le canal de la piste, `ev.channel` étant ignoré ;
    - GRID : gamme du router pour un synthé, `kit_note_base + pad` pour
      un kit ;
    - KIT et PATCH : note du payload ;
    - vélocités bornées à 1..127.
  - **Durées** :
    - GRID : sa `dur`, sinon la durée de la voix ;
    - PATCH sans `dur` : 500 ms ;
    - KIT : un pas ;
    - durée calculée selon le BPM, au minimum 1 tick.
  - **Temps** : à 16 et 32 pas, avec un temps flottant arrondi.
  - **Chevauchements** : la première note est coupée, et un doublon au
    même tick n'est écrit qu'une fois.
  - **Ordre à tick égal** : note-off, PGM, CC, bend, note-on. Deux bends
    au même tick restent dans l'ordre de `_tape`, le dernier l'emportant
    comme dans `_bend_state_at`.
  - **CC, PGM, bend** : valeurs, temps et bornes, y compris un numéro de CC
    négatif.
  - **Contre-épreuve par 24 mutations volontaires du module**, toutes
    détectées, dont :
    - type 0, PPQ 96, tempo et signature ;
    - pistes vides écrites, nom, canal ;
    - temps et durées, voix, KIT, PATCH ;
    - vélocité, chevauchement, doublon, ordre ;
    - bornes, fin de piste.

    La mutation « CC sans borne basse » n'était d'abord pas détectée. Un
    numéro de CC négatif a été ajouté au test, et elle l'est désormais.
- **10j1** — interface de l'export, conforme à D10. Validée au clavier par l'utilisateur : fenêtre principale, éditeur MIDI, Annuler, annonces Orca.
  - **`AppConfig.exports_dir`** : clé `exports_dir`, absolue ou relative
    à `base_dir`. Par défaut, c'est le dossier `EXPORTS` voisin de
    `projects_dir`, soit `/home/com/groovybox/EXPORTS`.
    `MainWindow._exports_dir` est lu au démarrage.
  - **`mw_project`** :
    - `_midi_export_params()` réunit les arguments de
      `build_pattern_midi` ; ils sont détaillés ci-dessous ;
    - `_midi_export_filename()` propose `Pat_NN.mid`, ou
      `Pat_NN_<nom>.mid` avec un nom nettoyé ;
    - `_export_midi(parent, status)` crée le dossier au besoin, ouvre un
      `wx.FileDialog` (`*.mid`, `FD_OVERWRITE_PROMPT`), ajoute `.mid` s'il
      manque, exporte le pattern live, puis annonce « Pattern NN
      exporté : <fichier> », « Export MIDI annulé » ou l'erreur.
  - **Arguments réunis par `_midi_export_params()`** :
    - nom du pattern, ou `Pat_NN` ;
    - BPM du player ;
    - canaux, volumes et pans de `TrackRouter` ;
    - type, nom et programme du slot de chaque piste ;
    - `snd.kit_base + kit_offset` ;
    - `router._kb_notes_play` ;
    - durées du `VoiceManager`.
  - **Raccourci Alt+Shift+E**, dans la fenêtre principale
    (`key_handler_alt.py`) et dans l'éditeur MIDI (`mew_keymap.py`). Dans
    l'éditeur, le dialogue et le statut sont ceux de sa fenêtre.
    `docs/shortcuts.md` est mis à jour.
  - **Écart au plan sur le nom** : la piste conductor et le fichier
    utilisent `Pat_NN`, la convention de la liste des patterns
    (`_pattern_label`), et non `Pattern_NN` comme l'écrivait D4.
  - **Essai réel, sans clavier** : une vraie `MainWindow` chargée sur
    `project_01.gvp`, avec un `FileDialog` simulé.
    - Nom proposé `Pat_01.mid`, dans `/home/com/groovybox/EXPORTS`.
    - Canaux 1, 10, 3, 4 ; programmes 24, 25, 16, 0 ; noms des slots ;
      kit 36 ; 100 BPM.
    - Fichier relu par mido : 5 pistes, 9,95 s.
    - Le dossier `EXPORTS` a été créé par cet essai.
- **10k1** — tests de l'interface d'export. Nouveau fichier
  `tests/test_midi_export_ui.py`, 12 tests, 1945 au total.
  - **`AppConfig.exports_dir`** :
    - par défaut, `EXPORTS` à côté du dossier des projets, qu'il soit
      absolu avec un `/` final ou relatif ;
    - valeur absolue, relative à `base_dir`, ou vide.
  - **`_midi_export_params`** : testé sur une fenêtre factice qui utilise
    le vrai `ProjectMixin`, avec de vrais `TrackRouter`, `Rack` et
    `VoiceManager`. Il prend :
    - les canaux, volumes et pans du router ;
    - le type, le nom et le programme des slots, y compris un programme
      réglé ;
    - `kit_base + kit_offset` ;
    - les notes de la gamme et les durées des voix ;
    - le BPM du player ;
    - le nom du pattern, ou `Pat_NN` ;
    - et ce sont des copies des listes.
  - **`_midi_export_filename`** : `Pat_NN.mid`, et un nom de pattern
    nettoyé.
  - **`_export_midi`**, avec un `FileDialog` simulé :
    - Ok : dossier créé, paramètres du dialogue (dossier, nom, filtre,
      `FD_SAVE | FD_OVERWRITE_PROMPT`, parent, `Destroy`), fichier relu
      avec les canaux et la note de kit tenant compte de l'offset, statut ;
    - extension `.mid` ajoutée si elle manque ;
    - Annuler : rien d'écrit ;
    - erreur d'écriture : annoncée, sans exception ;
    - parent et statut fournis par l'éditeur MIDI.
  - **Raccourcis** :
    - fenêtre principale : Alt+Shift+E exporte, Alt+E seul ne fait rien ;
    - éditeur MIDI : Alt+Shift+E exporte, avec le dialogue et le statut de
      l'éditeur.
  - **Contre-épreuve par 20 mutations volontaires de 10j1**, toutes
    détectées :
    - `exports_dir` : défaut, `normpath`, valeur relative ;
    - nom, BPM, canaux, offset du kit, noms, programmes, volumes, listes
      partagées ;
    - nettoyage du nom de fichier ;
    - `makedirs`, confirmation d'écrasement, parent, extension, erreur,
      statut ;
    - les deux raccourcis.

### Clôture (10l1)

**10a1-10k1 FAITS** (commits `7807389`..`7fd29c8`, 23 commits, 1945 tests
passed) — **chantier Phase 7 étape 10 complet**. Le pattern courant
s'exporte en fichier MIDI standard par Alt+Shift+E.

**Ce que le chantier a livré**, dans l'ordre des étapes :
- **Lecteur** (10b1-10c1) : un temps dure 60/BPM quel que soit le nombre
  de pas par mesure. `_update_step_duration` remplace les quatre formules
  `60/bpm/4`.
- **16 pistes par pattern** (10d1, 10e1). Les presets à 8 pistes sont
  complétés au chargement.
- **Prise live et Undo** (10d2-10d3), un bug préexistant : une prise
  marque le projet modifié et s'annule d'un bloc. Un Undo vide est retiré.
  Effacer à vide compte comme une modification.
- **Canal MIDI par piste** (10a2, 10f1-10g1) :
  - piste N → canal N par défaut ;
  - un kit assigné met la piste sur 10, un autre slot la ramène au
    défaut ;
  - liste Canal dans les propriétés de la piste ;
  - Program Change et chargement de projet sans effet ;
  - un `.gvp` sans canaux reçoit les canaux par défaut (correctif 10g1).
- **Module d'export** `src/midi/midi_export.py` (10h1, 10i1) :
  - SMF de type 1, PPQ 480, conductor ;
  - une piste SMF par piste non vide, sur le canal de la piste ;
  - notes, durées, chevauchements, ordre à tick égal, CC, PGM et bend ;
  - `requirements.txt`, sans pygame.
- **Program Change par slot** (10h2-10h4) :
  - instrument GM pour un synthé, kit GM2 pour un kit ;
  - déduit du nom, avec un nom GM exact prioritaire (correctif 10h4),
    réglable dans les propriétés de la piste ;
  - pistes SMF nommées d'après leur slot.
- **Volume et pan** en CC7 et CC10 (10h5-10h6). Les notes PATCH d'une
  piste sans synthé, muettes au rejeu, ne sont plus exportées.
- **Anciens projets** (10h7-10h8) : à l'ouverture d'un projet sans
  canaux, les pistes kit passent sur le canal 10.
- **Cache d'Undo à l'ouverture** (10h9-10h10), un bug préexistant : Ctrl+O
  ne mélange plus les patterns de l'ancien projet dans les instantanés.
- **Interface** (10j1-10k1) : Alt+Shift+E dans la fenêtre principale et
  l'éditeur MIDI, `AppConfig.exports_dir` (dossier `EXPORTS`), nom
  `Pat_NN[_nom].mid`, statut.

**Écarts au plan initial**, tous documentés dans les entrées
d'avancement ci-dessus :
- D5 simplifiée en 10a2, puis révisée en 10h7 ;
- Program Change, noms de slots, volume et pan ajoutés après les écoutes ;
- PATCH muettes omises ;
- `Pat_NN` au lieu de `Pattern_NN` ;
- le pattern live ne porte ni gamme, ni nom, ni BPM : l'export les reçoit
  en paramètres (10h1).

**Données utilisateur corrigées pendant le chantier**, hors dépôt, avec
l'accord de l'utilisateur :
- racine de `PATCHS/DrawbarOrgan.json` passée de C4 à C5 ;
- parties d'orgue transposées de +12 dans `project_01.gvp` et
  `project_03.gvp`.

Cause probable de l'erreur d'octave, à vérifier à part :
`tools/extract_organ_sf2.py` écrit la racine d'après l'`orig_pitch` du SF2
(60, C4), sans tenir compte d'un accordage de zone, alors que l'échantillon
sonne à 523 Hz (C5).

**`docs/SPECS.md` mis à jour** :
- ligne Phase 7 de l'état d'avancement ;
- arborescence : `requirements.txt` ; `src/midi/` avec ses cinq modules,
  corrigeant le retard de la Phase 7 étape 3 relevé en 8h1 ;
  `midi_handler_window.py` ;
- clé `exports_dir` ;
- `gm_program` des slots ;
- `_track_channels` du router et du pattern ;
- prise et Undo ;
- canal par piste ;
- nouvelle section « Export MIDI (Alt+Shift+E) ».

**Laissé hors périmètre, pour la suite** :
- **Conversion des notes des kits non GM** : une table pad → note GM
  d'après le libellé, par exemple Cowbell 49 de la TR-707 vers 56, au lieu
  de la crash 49 en GM. Décidée avec l'utilisateur comme prochaine étape
  séparée.
- Export d'un song ou du projet, tempo variable ; import MIDI.
- Séparation des noms de pistes (F2) et des noms de pads dans
  `voice_manager`.
- Historique d'Undo non vidé par Ctrl+O (10h9).
- Touches 1-9 du Note Repeat ignorées quand le focus est sur la liste des
  patterns (10c1).
- Écart du rejeu sur deux bends au même temps : le rejeu applique la
  valeur la plus haute, l'export et `_bend_state_at` le dernier dans
  `_tape`.
- Banque (CC0/CC32), kits GS non GM2, Undo du choix de slot par Ctrl+T.
- Vérification de `tools/extract_organ_sf2.py`.

---

## Phase 7 étape 11a1 — Conversion des notes des kits non GM à l'export MIDI

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 10 : `11a1`, `11b1`, `11c1`… ; un
commit imprévu inséré après `11b1` s'appelle `11b2`, `11b3`, etc.

### Origine du besoin

Relevé à l'écoute de l'export MIDI (Phase 7 étape 10, § Clôture 10l1). Le
kit TR-707 (`KITS/tr_707.json`) n'est pas rangé selon la table de batterie
GM :
- sa note 49 est « Cowbell », mais en GM c'est Crash Cymbal 1. Dans
  TiMidity, 37 coups de cowbell devenaient une crash très forte ;
- autres écarts : 44 HH Open (GM : Pedal Hi-Hat), 46 Crash (GM : Open
  Hi-Hat), 47 Ride (GM : Low-Mid Tom), 48 Tambourine (GM : Hi-Mid Tom).

L'utilisateur a décidé le 2026-10-21 d'en faire une étape séparée, et a
validé les décisions ci-dessous le 2026-10-23.

### État des lieux constaté en code (2026-10-23, 1945 tests verts)

**Le kit.** Un kit est un JSON de `KITS/` : `name`, `base_note` facultatif,
et `pads[]`, dont chaque entrée porte `pad` (1-16, facultatif), `note`
(facultatif), `filename`, `label` et `mute_group`.
- `gm.json` (GM FluidR3) est déjà rangé selon GM : `base_note` 36, pad N
  → note 35 + N, et 30 entrées sans `pad` pour les notes 35 et 52 à 81.
- `tr_707.json` n'a pas de `base_note`, et retombe donc sur 36. Ses pads
  1 à 15 portent les notes 35 à 49. Le pad 16 (`---`) n'a ni note ni son.

**Le chargement** (`SoundManager.load_kit`, `sound_manager.py:54`) :
- `drum_sounds[i]` est le son de l'entrée `"pad": i + 1` ;
- `note_map` et `note_labels` indexent tous les sons par leur `note` ;
- `kit_base = base_note` (36 par défaut) et `kit_offset = 0`.
- `shift_kit` reconstruit au contraire `drum_sounds[i]` à partir de
  `note_map[kit_base + kit_offset + i]` (`_rebuild_drum_sounds`).
- Il n'y a qu'un `SoundManager`, et donc un seul kit chargé à la fois :
  celui du slot courant (`mw_pads._load_kit_slot`).

**Ce que joue le rejeu.**
- `GRID` sur une piste kit : `play_sound(pad)`, c'est-à-dire
  `drum_sounds[pad]`.
- `KIT` : `play_note(note)`, c'est-à-dire `note_map[note]`. La note est
  celle reçue en MIDI à la capture (`record_kit_note`).

**Ce qu'écrit l'export** (`midi_export.build_pattern_midi`) :
- `GRID` sur une piste kit : `kit_note_base + pad`, avec
  `kit_note_base = kit_base + kit_offset` (`mw_project.py:90`) ;
- `KIT` : la note du payload, telle quelle.

**Bug constaté : la note GRID d'une piste kit ne suit pas le son joué.**
Juste après le chargement, le pad joue le son de son entrée `"pad"`, mais
l'export écrit `kit_base + pad`. Les deux ne coïncident que si les pads
sont rangés en notes consécutives à partir de `base_note`. C'est le cas de
`gm.json`, pas celui de la TR-707 :
- le pad 1, « Kick 2 » (note 35), est écrit 36 ;
- le pad 15, « Cowbell » (note 49), est écrit 50 (High Tom en GM).

Après un `shift_kit`, les deux concordent de nouveau.

**Les noms de batterie GM** (notes 35 à 81) ne sont pas dans
`midi_constants.py`. Le fichier contient `GM_PATCH_NAMES`,
`GM2_DRUMKIT_NAMES` et `guess_gm_program`, dont l'outil `_name_words`
(mots en minuscules, camelCase coupé, chiffres ignorés) peut servir ici.

### Décisions validées (utilisateur, 2026-10-23)

**D1 — la note exportée d'un `GRID` de piste kit est la note du son joué.**
C'est un correctif préalable, sans lequel la conversion partirait d'une
mauvaise note.
- `SoundManager` gagne `pad_notes`, une liste de 16 notes de kit, une par
  pad :
  - à `load_kit`, la `note` de l'entrée du pad, ou `kit_base + i` si
    l'entrée n'en a pas (pad 16 de la TR-707, ancien comportement) ;
  - à `_rebuild_drum_sounds` (`shift_kit`), `kit_base + kit_offset + i` ;
  - à `load_sounds` (pas de kit), `kit_base + i`.
- L'export reçoit `kit_pad_notes` à la place de `kit_note_base`.
- Le rejeu, l'affichage des pads et la correspondance d'une note MIDI
  entrante vers un pad (`midi_handler_window.py:415`) ne changent pas.

**D2 — la note GM d'un son se déduit de son libellé, avec deux
surcharges dans le JSON du kit.** Par ordre de priorité :
1. une clé `"gm_note"` (35-81) dans l'entrée du son ;
2. une clé `"gm": true` au niveau du kit : chaque note est déjà GM et
   reste telle quelle. On l'ajoute à `gm.json` ;
3. sinon, une devinette d'après le `label` (D3) ;
4. sinon, aucune correspondance (D4).

`SoundManager.load_kit` construit `gm_note_map`, un dict
`{note du kit: note GM}`, pour chaque entrée qui porte une `note`. Un pad
sans `note` reçoit son entrée sous la clé `pad_notes[i]`, si elle n'y est
pas déjà.

**D3 — devinette d'après le libellé : `guess_gm_drum_note(label,
kit_note)` dans `midi_constants.py`.**
- Une table `GM_DRUM_NAMES`, de 35 (Acoustic Bass Drum) à 81 (Open
  Triangle), avec les noms de la norme GM 1.
- Les mots du libellé et des noms GM sont normalisés avant comparaison :
  - `hi-hat`, `hi hat`, `hihat` et `hh` deviennent un seul mot `hihat`.
    Sinon, le « hi » de « Hi-Hat » se confondrait avec le « Hi » de
    « Hi Mid Tom » ;
  - puis quelques synonymes : `hi` → `high`, `kick` et `bd` → `bass drum`,
    `rimshot` et `rim` → `side stick`, `clap` → `hand clap`, `tamb` →
    `tambourine`, `med` → `mid`, `sd` → `snare`, `cym` → `cymbal`,
    `cb` → `cowbell`.
  - Les chiffres sont ignorés, comme dans `_name_words`.
- Chaque note GM reçoit un score, comparé dans cet ordre :
  1. le nombre de mots communs avec le libellé ;
  2. un bonus si c'est la note actuelle du son (`kit_note`). Un kit
     partiellement GM garde ainsi ses notes justes, et deux sons proches
     ne se replient pas sur une même note ;
  3. le moins de mots en trop dans le nom GM.
  
  À égalité, la plus petite note l'emporte. Aucun mot commun : `None`.
- Résultat attendu pour la TR-707 (il servira de test) :

  | Note | Libellé | GM | Nom GM |
  |---|---|---|---|
  | 35 | Kick 2 | 35 | Acoustic Bass Drum |
  | 36 | Kick 1 | 36 | Bass Drum 1 |
  | 37 | Rimshot | 37 | Side Stick |
  | 38 | Snare 1 | 38 | Acoustic Snare |
  | 39 | Hand Clap | 39 | Hand Clap |
  | 40 | Snare 2 | 40 | Electric Snare |
  | 41 | Tom Low | 41 | Low Floor Tom |
  | 42 | HH Closed | 42 | Closed Hi-Hat |
  | 43 | Tom Mid | 47 | Low-Mid Tom |
  | 44 | HH Open | 46 | Open Hi-Hat |
  | 45 | Tom Hi | 50 | High Tom |
  | 46 | Crash | 49 | Crash Cymbal 1 |
  | 47 | Ride | 51 | Ride Cymbal 1 |
  | 48 | Tambourine | 54 | Tambourine |
  | 49 | Cowbell | 56 | Cowbell |

  Les toms passent de 41/43/45 à 41/47/50. On garde ainsi l'ordre grave →
  aigu et des notes distinctes.

Alternatives écartées :
- **`gm_note` seule** : pas de devinette, mais un kit sans clé reste non
  converti, et il faudrait annoter chaque kit à la main.
- **Libellé seul** : un libellé ambigu ne pourrait pas être corrigé.

**D4 — un son sans équivalent GM garde sa note, et il est signalé.**
- L'export écrit la note du kit telle quelle.
- `build_pattern_midi` reçoit un paramètre facultatif `unmapped`, un
  `set` qu'il remplit avec les notes de kit écrites sans conversion.
  `export_pattern` le transmet.
- La barre de statut l'annonce après l'export, avec les libellés de
  `note_labels` :
  `Pattern 01 exporté : Pat_01.mid — non converti en GM : Zap (52)`.
  Orca l'annonce comme le reste du statut.

Alternatives écartées : omettre la note (le son disparaît du fichier) ;
une note de repli fixe (un son faux, sans le signaler).

**D5 — conversion à l'export seulement.**
- Sont convertis : les `GRID` d'une piste kit (via `pad_notes`, D1) et
  les `KIT`, sur toute piste, puisque leur note est toujours une note du
  kit.
- Les `PATCH` et les `GRID` d'une piste SYNTH ne sont pas touchés.
- `_tape`, le rejeu, la capture et le `.gvp` ne changent pas : aucune
  migration.
- Le paramètre `kit_gm_map` de `build_pattern_midi` reçoit
  `snd.gm_note_map`. S'il vaut `None`, les notes de kit sont écrites
  telles quelles : c'est utile aux tests existants.

Alternative écartée : stocker les `KIT` en GM dans `_tape`. Le rejeu
changerait et il faudrait migrer les `.gvp`, pour un besoin qui ne
concerne que le fichier exporté.

**D6 — pas d'interface.** On corrige une correspondance en ajoutant
`"gm_note"` dans le JSON du kit. Le format est documenté dans
`docs/SPECS.md`. Un dialogue d'édition pourra faire l'objet d'un chantier
séparé.

### Portée explicitement exclue de ce chantier

- **Plusieurs kits dans un même export** : il n'y a qu'un kit chargé à la
  fois. Toutes les pistes kit sont converties avec la table du kit du slot
  courant, comme `kit_note_base` aujourd'hui. Il faudra y revenir quand
  chaque slot gardera son kit chargé (mode Rack GM).
- La conversion pour un futur MIDI out, ou au rejeu.
- Un dialogue d'édition de la correspondance (D6).
- La correspondance d'une note MIDI entrante vers un pad
  (`kit_base + kit_offset`), qui ignore elle aussi les entrées `"pad"` :
  à vérifier à part.
- Le programme GM2 du kit (`guess_gm_program`), qui ne change pas.
- Le passage de 16 à 128 pads (chantier futur séparé).

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **11a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **11b1** | Implémentation — `GM_DRUM_NAMES`, normalisation et `guess_gm_drum_note` (D3). | `midi/midi_constants.py` |
| **11c1** | Tests — table GM 35-81 ; normalisation (hi-hat, hh, synonymes) ; tableau TR-707 de D3 ; bonus de la note actuelle ; égalités ; libellé inconnu → `None`. | `tests/test_midi_constants.py` |
| **11d1** | Implémentation — `pad_notes` (D1) et `gm_note_map` (D2) dans `SoundManager` ; `"gm": true` ajouté à `KITS/gm.json`, hors dépôt, avec l'accord de l'utilisateur. | `sound_manager.py` |
| **11e1** | Tests — `pad_notes` après `load_kit` (entrée `pad` avec ou sans `note`), après `shift_kit` et après `load_sounds` ; `gm_note_map` : `gm_note` prioritaire, `"gm": true` = identité, devinette, absence. JSON de test dans `tmp_path`. | `tests/test_sound_manager.py` |
| **11f1** | Implémentation — export : `kit_pad_notes` remplace `kit_note_base`, `kit_gm_map`, `unmapped` (D1, D4, D5) ; paramètres et statut dans `mw_project`. | `midi/midi_export.py`, `ui/mw_project.py` |
| **11g1** | Tests — GRID kit avec pads non consécutifs (bug de D1) ; KIT et GRID convertis ; PATCH et GRID synth intacts ; `kit_gm_map=None` ; `unmapped` rempli ; message de statut. Mise à jour des tests qui passent `kit_note_base`. | `tests/test_midi_export.py`, `tests/test_midi_export_ui.py`, `tests/test_midi_export_mix.py` |
| **11h1** | Doc — clôture (DESIGN.md ; `docs/SPECS.md` : clés `gm` et `gm_note` du JSON de kit, conversion à l'export), `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- 11f1 change la signature de `build_pattern_midi` : si `pytest` est rouge
  à ce commit, le titre le dira, et 11g1 réparera les tests.
- Avant de committer 11f1 : on exporte un pattern TR-707 et on l'écoute
  dans TiMidity. Le cowbell doit sonner cowbell, et le HH Open doit être
  une charleston ouverte.

### Avancement et écarts constatés

- **11b1** — conforme à D3. `GM_DRUM_NAMES` (47 noms, notes 35 à 81),
  `GM_DRUM_FIRST` et `GM_DRUM_LAST`, `_drum_words` (fusion hi-hat → `hihat`,
  puis synonymes) et `guess_gm_drum_note(label, kit_note=None)` dans
  `midi_constants.py`. Contrôle à la main : le tableau TR-707 de D3 est
  retrouvé note pour note. `---` et un libellé inconnu donnent `None`.
- **11c1** — tests dans `tests/test_midi_constants.py` (49 nouveaux,
  1994 tests verts) :
  - la table GM 35-81 ;
  - la normalisation (variantes de hi-hat, « Hi » → high, synonymes,
    chiffres, camelCase) ;
  - le tableau TR-707 de D3, avec des notes toutes distinctes ;
  - les 47 noms GM, qui retombent chacun sur leur propre note ;
  - le bonus de la note actuelle, les égalités, les mots en trop ;
  - les libellés inconnus, qui donnent `None`.
- **11d1** — conforme à D1 et D2. `SoundManager.pad_notes` (16 notes) et
  `gm_note_map`, construits par `load_kit` et réinitialisés par
  `load_sounds`. `_rebuild_drum_sounds` (`shift_kit`) met `pad_notes` à
  jour. La règle de D2 est dans `_entry_gm_note` : un `gm_note` hors 35-81
  ou non entier est ignoré, et la règle suivante s'applique.
  - Contrôle sur les vrais kits :
    - TR-707 : `pad_notes` = 35…49, puis 51 pour le pad 16 sans note
      (`kit_base + 15`, sans correspondance). La table GM est celle de D3.
    - `gm.json` : identité sur les 47 notes, et ce **même sans**
      `"gm": true`, puisque ses libellés reprennent les noms GM.
  - **Écart sur l'emplacement de `"gm": true`**, choisi par l'utilisateur.
    La clé est ajoutée à `data/kits/gm.json`, la copie déjà versionnée,
    synchronisée en Phase 5 étape 4d (`dbda7d5`). Le fichier est ensuite
    recopié dans `/home/com/groovybox/KITS/gm.json`, hors dépôt, le kit
    réellement chargé.
- **11e1** — 19 tests dans `tests/test_sound_manager.py` (2013 tests
  verts), sur des kits JSON écrits dans `tmp_path` :
  - `pad_notes` avant tout kit, d'après les entrées `pad` (TR-707), pour
    un pad sans note ou sans entrée, après `shift_kit` et après
    `load_sounds` ;
  - `gm_note_map` :
    - devinée d'après les libellés (tableau D3) ;
    - libellé inconnu absent ;
    - `gm_note` prioritaire, y compris sur `"gm": true` ;
    - `gm_note` invalide ignoré ;
    - `"gm": true` donne l'identité, mais `"yes"` ou `1` ne valent pas
      `true` ;
    - note sans fichier son ;
    - pad sans note ;
    - remise à zéro entre deux kits ;
  - `data/kits/gm.json` donne l'identité sur 35-81.
  
  **Constaté en passant, déjà présent et hors périmètre** : `load_kit`
  remplace `media_lst` par les chemins du kit, `''` compris pour un pad
  sans fichier. Un `load_sounds` appelé ensuite lève donc
  `LibsndfileError`. L'appli n'appelle `load_sounds` qu'en repli, quand le
  kit n'a pas pu être chargé : le cas ne se produit donc pas. Le test
  remet `media_lst` avant d'appeler `load_sounds`.
- **11f1** — conforme à D1, D4 et D5.
  - Dans `build_pattern_midi`, `kit_pad_notes` remplace `kit_note_base`.
    S'y ajoutent `kit_gm_map=None` et `unmapped=None`, et une fonction
    locale `kit_note` qui convertit les `GRID` des pistes kit et les `KIT`.
  - `mw_project` passe `snd.pad_notes` et `snd.gm_note_map`, puis ajoute
    au statut `— non converti en GM : <libellé> (<note>)`. Le libellé vient
    de `note_labels`, ou vaut `Note N` à défaut.
  - **`pytest` rouge à ce commit** : 34 tests passent encore
    `kit_note_base` (`test_midi_export*.py`, `test_gm_program.py`) ; ils
    sont réparés en 11g1.
  - **Écoute** (utilisateur, TiMidity et mpv) : la TR-707 exportée depuis
    l'appli est bien convertie.
    - Les 37 coups « crash » relevés en 10l1 n'étaient pas des cowbells,
      mais le pad 14, Tambourine. L'ancien export les écrivait
      `36 + 13 = 49` : c'était le bug D1. Ils sortent maintenant en 54.
    - Le sentiment que « tous les instruments sont des pianos » ne venait
      pas du fichier. `timidity -idvvv` confirme les Program Change 24
      (Nylon String Guitar) et 16 (DrawbarOrgan). L'écart venait des
      volumes relatifs et de la reverb et du chorus de TiMidity : un rendu
      sans effets (`-EFreverb=d -EFchorus=d`) a été jugé plus fidèle à
      l'appli.
  - **Pour un chantier séparé**, décidé avec l'utilisateur :
    - trouver une proportion acceptable entre les volumes de l'appli et
      ceux d'un lecteur GM, puisque l'équilibre entre instruments diffère
      nettement ;
    - jouer sec à l'export, par CC91 et CC93 à 0 au tick 0, ou par un
      réglage de TiMidity.
- **11g1** — `pytest` de nouveau vert, 2025 tests.
  - Adaptation : `kit_note_base=36` devient
    `kit_pad_notes=list(range(36, 52))`, de même sens, dans
    `test_midi_export.py`, `test_midi_export_mix.py` et
    `test_gm_program.py`. `_build` gagne `pad_notes`, `gm_map` et
    `unmapped`.
  - 10 nouveaux tests d'export :
    - le bug D1 : le pad 14 est écrit 48, et non plus 49 ;
    - GRID kit et KIT convertis, le KIT aussi sur une piste synthé ;
    - PATCH et GRID synthé intacts ;
    - `kit_gm_map=None` ;
    - `unmapped` rempli sans doublon, ou `None` ;
    - PATCH omis sur une piste kit, et non signalé ;
    - le chevauchement s'applique après la conversion ;
    - `export_pattern` transmet `unmapped`.
  - Interface : les paramètres `kit_pad_notes` et `kit_gm_map` sont des
    copies. La note du kit est convertie dans le fichier. Le statut liste
    les sons non convertis, y compris dans le statut de l'éditeur MIDI.
  - Constaté : un son sans libellé s'affiche `Note 90 (90)`, avec la note
    en double. Le test fige le comportement de 11f1. Un correctif pour
    afficher `Note 90` reste possible, avec l'accord de l'utilisateur.

### Clôture (11h1)

**11a1-11g1 FAITS** (commits `d3c8db5`..`8290b76`, 7 commits, plus ce
commit de clôture ; 2025 tests verts) : **chantier Phase 7 étape 11
complet**. À l'export MIDI, les notes d'un kit non GM sont écrites avec
leur équivalent GM.

**Ce que le chantier a livré** :
- **Correctif préalable** (D1, 11d1, 11f1) : la note GRID d'une piste kit
  est la note du son réellement joué par le pad (`SoundManager.pad_notes`),
  et non plus `kit_base + pad`. Sur la TR-707, tout était décalé d'une
  note : les 37 coups « crash » de 10l1 étaient des coups de Tambourine
  (pad 14).
- **Noms GM et devinette** (11b1, 11c1) : `GM_DRUM_NAMES` (35-81) et
  `guess_gm_drum_note` dans `midi_constants.py`. Les mots sont normalisés
  (hi-hat, synonymes), puis comparés par un score : mots communs, note
  actuelle, mots en trop. La TR-707 est convertie note pour note selon le
  tableau D3, et les 47 noms GM sont des points fixes.
- **Correspondance du kit** (11d1, 11e1) : `SoundManager.gm_note_map`.
  Ordre de priorité : `gm_note`, puis `"gm": true`, puis la devinette.
  `"gm": true` est ajouté à `data/kits/gm.json` et recopié dans
  `KITS/gm.json`, hors dépôt.
- **Export** (11f1, 11g1) : `kit_pad_notes`, `kit_gm_map` et `unmapped`
  dans `build_pattern_midi`. Les GRID kit et les KIT sont convertis, les
  PATCH et les GRID synthé ne le sont pas. Un son sans correspondance garde
  sa note et est listé au statut.

**Écarts au plan** :
- `"gm": true` est mis dans la copie versionnée `data/kits/gm.json`, à la
  demande de l'utilisateur, puis recopié dans `KITS/` ;
- les 34 tests de 11f1 ont été adaptés en 11g1, comme prévu par le plan.

**`docs/SPECS.md` mis à jour** : ligne Phase 7, clés `base_note`, `gm` et
`gm_note` du JSON de kit, sens de `note` (note du kit, pas forcément GM),
`pad_notes` et `gm_note_map` de `SoundManager`, section Export MIDI.

**Laissé hors périmètre, pour la suite** :
- **Volumes et effets à l'export** (écoute 11f1) : trouver un équilibre
  des volumes entre l'appli et un lecteur GM, et jouer sec (CC91 et CC93
  à 0, ou réglage de TiMidity). C'est un chantier séparé.
- Statut `Note 90 (90)` pour un son sans libellé, avec la note en double
  (11g1). Un affichage `Note 90` serait plus court pour Orca.
- Plusieurs kits dans un même export : un seul kit est chargé à la fois.
- La correspondance d'une note MIDI entrante vers un pad
  (`kit_base + kit_offset`), qui ignore elle aussi les entrées `"pad"`.
- `load_sounds` après `load_kit` plante si un pad n'a pas de fichier
  (11e1). Le cas ne se produit pas dans l'appli.
- Un dialogue d'édition de la correspondance GM (D6).
- La conversion pour un futur MIDI out.

---

## Phase 7 étape 12a1 — Courbe de volume GM dans l'appli, vélocité des cases de grille et effets à l'export

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 11 : `12a1`, `12b1`, `12c1`… ; un
commit imprévu inséré après `12b1` s'appelle `12b2`, `12b3`, etc.

### Origine du besoin

Relevé à l'écoute de la Phase 7 étape 11f1. L'utilisateur a exporté
`Pat_01` (guitare, TR-707, orgue, piano) et l'a écouté dans TiMidity
(banque FluidR3 GM) avec mpv :
- l'équilibre entre les instruments diffère nettement de celui de l'appli,
  l'orgue joué en live surtout ;
- un rendu sans reverb ni chorus est plus fidèle à l'appli, qui n'a pas
  d'effets.

Il a demandé un chantier séparé pour « trouver une proportion
acceptable ». Les décisions ci-dessous ont été validées le 2026-10-23.

### État des lieux constaté (2026-10-23, 2025 tests verts)

**Mesure de TiMidity** (rendu sec, note 60, RMS sur 0,4 s ; script jetable
du scratchpad, non versionné) :

| Valeur | 127 | 100 | 77 | 64 | 48 | 32 |
|---|---|---|---|---|---|---|
| Appli, linéaire : `20·log10(v/127)` | 0 dB | −2,1 | −4,3 | −6,0 | −8,5 | −12,0 |
| TiMidity, vélocité (orgue 16) | 0 dB | −4,1 | −8,4 | −11,4 | −15,5 | −21,4 |
| TiMidity, vélocité (piano 0, guitare 24) | 0 dB | −3,4 | −7,2 | −9,9 | −14,0 | −19,9 |
| TiMidity, CC7 (orgue) | 0 dB | −3,4 | — | −9,9 | — | −19,9 |

TiMidity suit la courbe GM habituelle, en carré, soit `40·log10(v/127)` :
deux fois plus de dB que l'appli, qui est linéaire. L'orgue de `Pat_01`,
joué en live avec des vélocités de 29 à 77, perd de 8 à 23 dB dans
TiMidity, contre 4 à 13 dB dans l'appli. C'est pourquoi l'utilisateur
voulait baisser tous les instruments sauf l'orgue.

**Calcul du gain dans l'appli** : un facteur linéaire dans [0, 1], produit
de facteurs bornés :
- **case de grille** (rejeu `dp_playback._dispatch_event`, jeu live
  `dp_live.play_sound`, pads MIDI `midi_handler_window.py:365` et `:403`) :
  `min(1, volume du pad/100 · vel/100)`, puis `× volume de piste/100`
  (`TrackRouter.on_play`).
  - L'échelle est **/100** : la vélocité 100 par défaut du Numpad et de la
    grille joue au maximum, et une vélocité au-delà de 100 est écrêtée.
- **KIT et PATCH** (`TrackRouter.on_kit_tape`, `on_patch_tape`) :
  `min(1, volume de piste/100 · vel/127)`.
- **jeu live d'un synthé** (`midi_handler_window.py:310`, `:335`) et
  pré-écoute de l'éditeur MIDI (`mew_playback.py:80`) : `vel/127`.
- **Note Repeat et Numpad en mode Keyboard** : volume du pad / 100.
- Ce facteur arrive au driver par trois points d'entrée seulement :
  `SoundManager.play_sound`, `SoundManager.play_note` et
  `SynthEngine.play`.
- Le métronome et la pré-écoute d'un son (`preview_sound`) appellent le
  driver sans facteur. Le volume général (`set_master_volume`) s'applique
  au mixage, à part.

**Ce qu'écrit l'export** :
- la vélocité du payload, pour tous les etypes ;
- CC7 = `volume de piste · 127/100` ;
- le volume des pads n'est pas exporté.

Une case de grille par défaut (vel 100, pad à 100) joue donc au maximum
dans l'appli, mais sort à −4 dB dans TiMidity.

**Effets dans TiMidity** (écart RMS avec le rendu sec de `Pat_01`) :
- rendu par défaut : −6,7 dB ;
- CC91 = 0 et CC93 = 0 écrits au tick 0 de chaque piste : −7,0 dB, donc
  **aucun effet**. La reverb et le chorus viennent des réglages
  d'instrument de la banque FluidR3 ;
- seules les options `-EFreverb=d -EFchorus=d` rendent sec, et un fichier
  `~/.timidity.cfg` contenant `opt EFreverb=d` et `opt EFchorus=d` donne
  le même résultat (écart nul), **sans sudo**.

### Décisions validées (utilisateur, 2026-10-23)

**D1 — l'appli passe à la courbe GM : gain = facteur².**
- Le facteur linéaire calculé partout aujourd'hui (vélocité × volume du
  pad × volume de piste, borné à [0, 1]) est élevé au carré en un seul
  endroit, juste avant le driver, aux trois points d'entrée :
  `SoundManager.play_sound`, `SoundManager.play_note` et
  `SynthEngine.play`.
- Comme `(a·b·c)² = a²·b²·c²`, c'est exactement la courbe GM appliquée à
  chaque facteur : la vélocité comme `40·log10(v/127)`, et le volume de
  piste comme un CC7.
- Une fonction `gm_gain(factor)` dans `midi_constants.py` borne le facteur
  à [0, 1] et le met au carré. On n'a pas à toucher la dizaine d'endroits
  qui calculent le facteur.
- Ne changent pas :
  - le métronome et `preview_sound`, qui n'ont pas de facteur ;
  - le volume général, qui reste linéaire : c'est un réglage d'écoute, non
    exporté ;
  - l'échelle /100 des cases de grille (vel 100 = maximum) ;
  - le pan.
- **Effet accepté** : les projets existants sonnent autrement. Une note
  douce ou une piste baissée l'est deux fois plus en dB qu'avant. Par
  exemple, vel 64 passe de −6 à −12 dB, et une piste à 45 de −7 à −14 dB.
  Les notes à 127 et les cases de grille par défaut ne bougent pas.

Alternatives écartées :
- **Compenser à l'export** (vélocité = 127·√gain) : l'appli resterait
  non standard, et l'import devrait appliquer l'inverse.
- **Ne rien changer.**

**D2 — la vélocité exportée d'une case de grille reflète le gain joué.**
- `vel_out = round(127 · min(1, vel/100 · volume du pad/100))`, borné à
  1..127.
  - C'est le facteur du rejeu (`dp_playback`), ramené à l'échelle MIDI.
  - Avec D1, un lecteur GM rend alors `(vel_out/127)²`, le gain de
    l'appli, au volume de piste près, déjà porté par CC7.
  - Une case par défaut (vel 100, pad à 100) sort à 127. Une case à vel
    100 sur un pad à 50 sort à 64.
- `build_pattern_midi` reçoit `pad_volumes`, les 16 volumes du
  `VoiceManager`. S'il vaut `None`, le volume du pad compte pour 100.
  `mw_project` le passe.
- KIT et PATCH : la vélocité du payload est inchangée. Elle est déjà sur
  l'échelle /127, et D1 rend le gain de l'appli identique à celui d'un
  lecteur GM.
- CC7 est inchangé : `volume · 127/100`, que D1 rend fidèle.

Alternatives écartées : prendre la vélocité seule sans le volume du pad,
ou garder la vélocité brute.

**D3 — les effets.**
- **À l'export** : CC91 (reverb) et CC93 (chorus) à 0 au tick 0 de chaque
  piste, après le volume et le pan. Ce sont les rangs négatifs du tick 0,
  comme CC7 et CC10 : un CC91 ou un CC93 capturé dans `_tape` au tick 0
  passe après et l'emporte.
  - Sans effet mesurable dans TiMidity, mais c'est la valeur juste pour
    un lecteur GM ou un DAW qui respecte ces CC (GM2 suppose 40 par
    défaut pour CC91).
- **Pour l'écoute dans TiMidity** : un fichier `/home/sam/.timidity.cfg`,
  hors dépôt, avec `opt EFreverb=d` et `opt EFchorus=d`.
  - Il remplace l'option `/etc/timidity/timidity.cfg` proposée lors des
    questions, qui demandait sudo.
  - Il est écrit avec l'accord de l'utilisateur, à l'étape de clôture.
  - Il agit sur toute écoute TiMidity de l'utilisateur, mpv compris s'il
    passe par TiMidity.

### Portée explicitement exclue de ce chantier

- **Écarts de niveau propres à chaque instrument**, entre un échantillon
  de l'appli et un preset FluidR3 : un réglage de gain GM par slot ne sera
  envisagé qu'après l'écoute de ce chantier, si l'équilibre reste
  insatisfaisant.
- Le volume général : il reste linéaire et n'est pas exporté.
- Le volume des pads pour les KIT et les PATCH : il ne s'applique pas au
  rejeu, donc rien à exporter.
- Le pan, ainsi que le volume (CC7) et le pan (CC10) capturés dans
  `_tape`, qui gardent leur conversion.
- Un réglage de la courbe (linéaire ou GM) dans l'interface.
- Le statut `Note 90 (90)` et les autres restes de la Phase 7 étape 11.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **12a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **12b1** | Implémentation — `gm_gain` ; courbe GM aux trois points d'entrée (D1). | `midi/midi_constants.py`, `sound_manager.py`, `synth_engine.py` |
| **12c1** | Tests — `gm_gain` (bornes, carré) ; `play_sound`, `play_note` et `SynthEngine.play` transmettent le facteur au carré au driver (driver factice) ; métronome et `preview_sound` inchangés. Mise à jour des tests qui vérifient le facteur transmis au driver, s'il y en a. | `tests/test_midi_constants.py`, `tests/test_sound_manager.py`, `tests/test_synth_engine*.py` |
| **12d1** | Implémentation — export : vélocité des cases de grille avec le volume du pad (D2, `pad_volumes`), CC91 et CC93 à 0 au tick 0 (D3) ; `mw_project` passe les volumes des pads. | `midi/midi_export.py`, `ui/mw_project.py` |
| **12e1** | Tests — vélocité de grille (défaut 127, pad à 50, écrêtage, `pad_volumes=None`, synthé et kit) ; KIT et PATCH inchangés ; CC91 et CC93 à 0 dans l'ordre du tick 0, battus par un CC capturé au tick 0 ; paramètres de l'interface. Mise à jour des tests qui figent les messages du tick 0 ou une vélocité de grille. | `tests/test_midi_export.py`, `tests/test_midi_export_mix.py`, `tests/test_midi_export_ui.py` |
| **12f1** | Doc — clôture (DESIGN.md ; `docs/SPECS.md` : courbe de volume, export), `~/.timidity.cfg` avec l'accord de l'utilisateur, `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- Avant de committer 12b1 : l'utilisateur écoute un projet dans l'appli.
  Les notes douces et les pistes baissées doivent sonner plus bas, et les
  notes fortes ne pas changer.
- Avant de committer 12d1 : on exporte `Pat_01`, et l'utilisateur compare
  l'appli et TiMidity sec. Si l'équilibre reste insatisfaisant, on
  mesurera les écarts propres à chaque instrument (portée exclue).
- 12d1 change les messages du tick 0 et les vélocités de grille : si
  `pytest` est rouge à ce commit, le titre le dira, et 12e1 réparera les
  tests.

### Avancement et écarts constatés

- **12b1** — conforme à D1. `gm_gain(factor)` (borné à [0, 1], au carré)
  dans `midi_constants.py`. Il est appliqué au facteur transmis au driver
  dans `SoundManager.play_sound`, `SoundManager.play_note` et
  `SynthEngine.play` ; `midi_constants` y est importé en tête.
  - 2025 tests verts : aucun test existant ne vérifiait le facteur transmis
    au driver.
  - Écoute validée par l'utilisateur dans l'appli.
- **12c1** — 22 tests, 2047 verts :
  - `gm_gain` (`test_midi_constants.py`) : carré, bornes, double des dB
    (vel 64 ≈ −12 dB), entier accepté ;
  - `SoundManager` (`test_sound_manager.py`, driver qui enregistre les
    appels) : `play_sound` et `play_note` transmettent le facteur au carré
    avec le pan inchangé ; 1.0 par défaut ; un facteur au-delà de 1 est
    borné ; le métronome est appelé sans facteur ;
  - `SynthEngine.play` (`test_synth_engine.py`, moteur factice) : facteur
    au carré, pan, `phase_incr` et `lfo_depth` inchangés ; défaut et borne ;
    pas d'appel au driver sans son.
  
  **Constaté en passant, déjà présent et hors périmètre** :
  `SoundManager.preview_sound` n'a aucun appelant dans `src/`, et il est
  cassé. Il indexe la liste `drum_sounds` par un objet son, un reste de
  l'époque où c'était un dict, et lève donc `TypeError`. Il n'est pas testé
  ici. C'est du code mort, à supprimer ou à réparer à part.
- **12d1** — conforme à D2 et D3.
  - `grid_velocity(vel, pad_volume)` dans `midi_export.py`, et paramètre
    `pad_volumes` (les volumes de `VoiceManager`, passés par
    `mw_project`).
  - CC91 et CC93 à 0 au tick 0, de rangs −2 et −1. Le volume et le pan
    passent aux rangs −4 et −3.
  - **`pytest` rouge à ce commit** : 6 tests figent les messages du tick 0
    (`test_midi_export.py`, `test_midi_export_mix.py`) ; ils sont adaptés
    en 12e1.
  - **Écoute** (utilisateur, 2026-10-23, `Pat_01`, volumes de toutes les
    pistes baissés sauf l'orgue) :
    - **l'orgue sonne une octave plus bas dans TiMidity.** Ce n'est pas
      l'export : le fichier porte les notes 67 à 81. C'est le preset
      FluidR3 « Drawbar Organ ». Spectre de la note 72, identique dans
      FluidSynth et dans TiMidity : 262 Hz à 0 dB, 130 Hz à −2 dB et
      524 Hz à −7 dB. L'échantillon de l'appli, lui, sonne à 524 Hz.
    - **Les échantillons de l'appli sont normalisés** : écart RMS (appli
      moins TiMidity, vélocité 127, sans effets) de +5,7 dB pour la
      guitare (programme 24), **+17,0 dB pour le piano** (programme 0) et
      +3,1 dB pour l'orgue (programme 16). Aucune courbe globale ne peut
      corriger un écart propre à chaque instrument : voir l'avenant 12a2.
    - **Bug trouvé, déjà présent et hors export** : les changements de
      volume et de pan faits par Alt+flèches, Alt+0, les CC7 et CC10 du
      contrôleur et les SpinCtrl des pads n'entrent pas dans l'Undo et ne
      marquent pas le projet modifié. À la fermeture, rien n'est proposé à
      la sauvegarde (`project_03.gvp` a encore tous ses volumes à 100).
      L'utilisateur a décidé d'en faire un chantier séparé, après
      celui-ci.

### Phase 7 étape 12a2 — Avenant : transposition et gain GM par slot

**Origine.** L'écoute de 12d1 a montré deux écarts propres à chaque
instrument, qu'aucune courbe globale ne corrige :
- le preset FluidR3 « Drawbar Organ » sonne une octave sous la note
  écrite (spectre en 12d1) ;
- les échantillons de l'appli sont normalisés, « fortement » pour l'orgue
  selon l'utilisateur. L'écart RMS entre l'appli et TiMidity va de
  +3,1 dB (orgue) à +17,0 dB (piano).

Le 2026-10-24, l'utilisateur a choisi des réglages GM par slot, qui ne
touchent que l'export, comme le programme GM (Phase 7 étape 10h3).

**D4 — transposition GM d'un slot synthé.**
- `slot.config["gm_transpose"]`, un entier de −24 à +24 demi-tons,
  0 par défaut. Accesseurs `Slot.gm_transpose()` et
  `set_gm_transpose(n)`, sur le modèle de `gm_program()` et
  `set_gm_program()`. `config` est remplacé, jamais modifié en place, à
  cause des instantanés d'Undo.
- Appliquée à l'export aux notes `PATCH` et aux `GRID` d'une piste dont le
  slot est un synthé, après le calcul de la note et avant la borne
  0..127.
- Sans effet sur un slot kit, dont les notes passent par la table GM de la
  Phase 7 étape 11, ni sur les `KIT`.
- Exemple : l'orgue à +12. Ses notes 67 à 81 sont écrites 79 à 93, et le
  preset sonne alors à la hauteur de l'appli.

**D5 — gain GM d'un slot, en dB, appliqué au CC7 du fichier.**
- `slot.config["gm_gain_db"]`, un entier de −40 à 0 dB, 0 par défaut.
  Accesseurs `Slot.gm_gain_db()` et `set_gm_gain_db(db)`.
- Il vaut pour tout slot non vide, kit compris.
- À l'export, tout CC7 de la piste est multiplié par `10^(dB/40)`, puis
  arrondi et borné à 0..127. Cela vaut pour le CC7 du tick 0 (volume de
  piste) comme pour un CC7 capturé dans `_tape`. Avec la courbe GM d'un
  lecteur (`40·log10`), c'est exactement le gain voulu en dB.
- Le gain est négatif ou nul, car CC7 plafonne à 127 : pour équilibrer, on
  baisse les instruments trop forts plutôt que de monter les autres.
- Ordre de grandeur, d'après les mesures de 12d1 : pour retrouver dans
  TiMidity l'équilibre de l'appli, il faudrait l'orgue vers −14 dB et la
  guitare vers −11 dB, le piano restant à 0. Ce n'est qu'un point de
  départ : l'utilisateur règle à l'oreille.

**D6 — réglage dans `TrackPropertiesDialog`.**
- Deux `SpinCtrl` après « Programme GM du slot » : « Transposition GM du
  slot (demi-tons) » et « Gain GM du slot (dB) ». Un `SpinCtrl` est
  annoncé en temps réel par Orca.
  - Ordre Tab : Mute → Solo → Slots → Canal → Programme → Transposition →
    Gain → Volume → Pan.
  - La transposition est grisée si le slot n'est pas un synthé, le gain si
    le slot est vide. Changer de slot dans le dialogue recharge les deux
    valeurs, comme le programme.
- Même aperçu, même Annuler et même Undo que le programme :
  `saved_configs` garde la `config` d'origine de chaque slot touché.
- Le réglage appartient au slot : toutes les pistes qui jouent ce slot le
  partagent, comme le programme GM.

**Paramètres d'export.** `build_pattern_midi` reçoit `track_transposes` et
`track_gain_db`, une valeur par piste, lue sur le slot de la piste.
`None` signifie 0. `mw_project._midi_export_params` les remplit depuis le
Rack.

**Exclu de l'avenant** :
- une mesure automatique des écarts : elle dépend de la banque du lecteur ;
- une transposition des kits ;
- un gain positif.

**Découpage révisé** (12a1 à 12d1 inchangés) :

| Étape | Contenu | Fichiers |
|---|---|---|
| **12a2** | Doc — cet avenant. | `docs/DESIGN.md` |
| **12e1** | Tests — comme prévu en 12a1 (vélocité de grille, CC91 et CC93, adaptation des 6 tests). | `tests/test_midi_export*.py` |
| **12f1** | Implémentation — `gm_transpose` et `gm_gain_db` du slot (D4, D5) ; export : `track_transposes`, `track_gain_db` ; `mw_project`. | `rack.py`, `midi/midi_export.py`, `ui/mw_project.py` |
| **12g1** | Tests — accesseurs, bornes, `config` remplacé ; transposition des PATCH et des GRID synthé, kit et KIT intacts, borne 0..127 ; gain sur le CC7 du tick 0 et sur un CC7 capturé, arrondi, borne, `None` ; paramètres de l'interface. | `tests/test_rack*.py`, `tests/test_midi_export_mix.py`, `tests/test_midi_export_ui.py` |
| **12h1** | Implémentation — deux `SpinCtrl` dans `TrackPropertiesDialog` (D6), aperçu, Annuler, Undo. | `ui/dialogs_properties.py`, `ui/mw_tracks.py` |
| **12i1** | Tests — valeurs initiales, grisage selon le slot, rechargement au changement de slot, aperçu, Annuler qui rend la `config`, Undo, ordre Tab. | `tests/test_track_properties_dialog.py` |
| **12j1** | Doc — clôture (ex-12f1) : DESIGN.md, `docs/SPECS.md`, `~/.timidity.cfg` avec l'accord de l'utilisateur, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- Avant de committer 12h1 : l'utilisateur règle l'orgue à +12 et les
  gains à l'oreille, exporte `Pat_01`, puis compare l'appli et TiMidity
  sec.
- **Chantier suivant**, décidé avec l'utilisateur : l'Undo et le marquage
  « projet modifié » des changements de volume et de pan (Alt+flèches,
  Alt+0, CC7 et CC10 du contrôleur, SpinCtrl des pads), vus en 12d1.
- **12e1** — `pytest` de nouveau vert, 2065 tests (3 passages de suite).
  - **Adaptation des 6 tests** : CC91 et CC93 attendus après CC7 et CC10
    dans les messages du tick 0. « `None` = rien d'écrit » ne vaut plus que
    pour CC7 et CC10. Le test CC/PGM/bend écarte les CC91 et CC93 du
    tick 0.
  - **Nouveaux tests** :
    - `grid_velocity` sur 9 cas, dont défaut 127, pad à 50 → 64, écrêtage
      au-delà de 100 et jamais 0 ;
    - cases de grille synthé et kit avec le volume du pad ;
    - `pad_volumes=None` ;
    - KIT et PATCH inchangés ;
    - CC91 et CC93 à 0 sur chaque piste et son canal, après le volume et
      le pan, seulement au tick 0 ;
    - un CC91 capturé au tick 0 passe après et l'emporte ;
    - les paramètres et le fichier de l'interface (pad à 50 → 64).
  - **Échec intermittent**, vu une seule fois sur 11 passages complets, et
    non reproduit : le test n'a pas pu être identifié (sortie non
    capturée). À surveiller ; voir la fragilité connue des tests
    `wx.CallAfter` sur la suite complète.
- **12f1** — conforme à D4 et D5, avec des bornes plus strictes que
  prévu.
  - `InstrumentSlot.gm_transpose()` et `set_gm_transpose()`,
    `gm_gain_db()` et `set_gm_gain_db()`, ainsi que les constantes
    `GM_TRANSPOSE_MIN/MAX` (±24) et `GM_GAIN_DB_MIN/MAX` (−40..0).
  - Un helper `_config_int` lit la valeur de `config`. Une valeur hors
    bornes y est **ramenée dans les bornes**, alors qu'une valeur non
    entière ou booléenne compte pour 0.
  - Les setters bornent la valeur et remplacent `config`.
  - Export :
    - `apply_gain_db(cc7, db)` vaut `CC7 · 10^(dB/40)`, borné ;
    - `track_transposes` s'ajoute à la note PATCH et à la note GRID d'une
      piste synthé ;
    - `track_gain_db` atténue le CC7 du tick 0 et tout CC7 de `_tape` ;
    - `mw_project` les remplit depuis le Rack.
  - 2065 tests verts : avec des réglages à 0, l'export est inchangé.
  - Essai : un orgue à +12 et −14 dB écrit la note 67 en 79 ; le CC7 passe
    de 127 à 57 au tick 0, et un CC7 capturé de 100 à 45.

### Phase 7 étape 12a3 — Avenant : l'export suit le mute et le solo du rejeu

**Origine.** Le 2026-10-24, l'utilisateur a exporté en ne gardant que la
TR-707 et l'orgue, les autres pistes étant mutées. Les pistes mutées ont
quand même été exportées. Le plan 10a1 les ignorait volontairement (§
Portée exclue : « Mute et solo sont ignorés »). L'utilisateur revient sur
ce choix : ce qui ne s'entend pas au rejeu ne doit pas être exporté.

Lors du même essai, l'orgue ne semblait pas transposé. C'est attendu : la
transposition GM n'a pas encore d'interface, qui arrive en 12h1. Aucun
projet ne porte `gm_transpose`, qui vaut donc 0.

**D7 — mêmes règles qu'au rejeu (validé par l'utilisateur).**
- **Pistes** : la règle est celle de `TrackRouter._track_is_audible`. Une
  piste mutée est omise. S'il y a au moins un solo, seules les pistes en
  solo sont gardées, et le mute l'emporte sur le solo.
  - Une piste omise n'a **aucune piste SMF**, comme une piste vide : ni
    notes, ni CC, ni Program Change. Au rejeu, `TrackRouter` coupe aussi
    ses CC et son bend.
- **Pads** : la règle est celle de `VoiceManager.is_audible`. Les cases de
  grille d'un pad muet, ou hors du solo des pads, sont omises sur toutes
  les pistes, comme dans `DrumPlayer._dispatch_event`.
  - Les `KIT` et les `PATCH` ne dépendent pas des pads, comme au rejeu.
  - Une piste dont il ne reste que des cases de pads muets garde sa piste
    SMF, sans note, comme une piste kit qui n'a que des `PATCH` (10h5).
- **Paramètres** : `build_pattern_midi` reçoit `track_audible` et
  `pad_audible`, des listes de booléens. `None` signifie que tout est
  audible. `mw_project` les remplit depuis le router et le
  `VoiceManager`.

**Découpage** : deux commits sont insérés après 12f1, et la suite (12g1 à
12j1) ne change pas.

| Étape | Contenu | Fichiers |
|---|---|---|
| **12a3** | Doc — cet avenant. | `docs/DESIGN.md` |
| **12f2** | Implémentation — `track_audible` et `pad_audible` (D7), paramètres de `mw_project`. | `midi/midi_export.py`, `ui/mw_project.py` |
| **12f3** | Tests — piste mutée omise, solo, mute qui l'emporte sur le solo ; pad muet ou hors solo omis sur une piste synthé et une piste kit ; KIT et PATCH intacts ; `None` ; paramètres de l'interface. | `tests/test_midi_export.py`, `tests/test_midi_export_ui.py` |
- **12f2** — conforme à D7.
  - `track_audible` saute la piste entière avant de construire sa piste
    SMF. `pad_audible` saute les cases de grille du pad.
  - `mw_project` passe `r._track_is_audible(t)` et `vm.is_audible(i)`.
  - 2065 tests verts : aucun test ne mutait de piste ou de pad à l'export.
  - Essai : une piste mutée disparaît ; un solo ne garde que sa piste ; un
    pad muet perd sa case de grille, mais la note KIT de même hauteur
    reste.

**Chantier 12 en pause après 12f2** (2026-10-24) : l'utilisateur fait
passer d'abord la Phase 7 étape 13, l'Undo des réglages de mixage. Le
chantier 12 reprendra à 12f3.

---

## Phase 7 étape 13a1 — Undo et projet modifié pour le mute, le solo et le volume des pistes et des pads

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 12 : `13a1`, `13b1`, `13c1`… ; un
commit imprévu inséré après `13b1` s'appelle `13b2`, `13b3`, etc.

### Origine du besoin

Relevé à l'écoute de la Phase 7 étape 12d1 : les volumes changés dans
l'appli n'entrent pas dans l'Undo et ne marquent pas le projet modifié.
À la fermeture, rien n'est donc proposé à la sauvegarde. Par exemple,
`project_03.gvp` avait encore tous ses volumes à 100 après une séance de
réglage.

Le 2026-10-24, l'utilisateur a demandé de le traiter avant les tests du
chantier 12, en se limitant pour l'instant au **mute, au solo et au volume
des pistes et des pads**. Le pan et le reste viendront dans un chantier
suivant.

### État des lieux constaté en code (2026-10-24, 2065 tests verts)

**L'instantané d'Undo contient déjà ces réglages.** `_capture_state`
range l'état du router dans le pattern courant (`_flush_pattern_to_store` :
`_track_volumes`, `_track_mutes`, `_track_solos`…) et les voix des pads
(`voice_manager.to_list()` : volume, pan, mute, solo, durée).
`_restore_state` les rétablit par `_apply_pattern_from_store`, puis
rafraîchit la grille, les pads et la liste des pistes. Il manque
seulement l'appel à `_add_undo`, qui marque aussi le projet modifié.

**Chemins sans Undo ni marquage**, dans le périmètre :

| Réglage | Chemin | Code |
|---|---|---|
| Mute / solo de piste | X, S, Shift+X, Shift+S sur la liste des pistes | `key_handler_chars.py:123-165` |
| Mute / solo de piste | X, S dans l'éditeur MIDI, sur les pistes sélectionnées | `mew_playback._toggle_track_mute/_solo` |
| Mute / solo de pad | X, S, Shift+X, Shift+S hors liste des pistes | `key_handler_chars.py` |
| Mute / solo de pad | Boutons Mute et Solo | `mw_pads._on_mute_btn`, `_on_solo_btn` |
| Volume de piste | Alt+↑/↓ sur la liste des pistes | `key_handler_alt.py:16-40` |
| Volume de piste | CC7 du contrôleur, liste des pistes focalisée | `midi_handler_window.on_cc` |
| Volume de pad | Alt+↑/↓ hors liste des pistes | `key_handler_alt.py` |
| Volume de pad | SpinCtrl Volume du pad | `mw_pads._on_vol_spin` |
| Volume de pad | CC7 du contrôleur, ailleurs que la liste des pistes | `midi_handler_window.on_cc` |
| Tout le pad | Dialogue de propriétés du pad : il a un Annuler, mais pas d'Undo | `mw_pads._pad_properties_dialog` |

Seul `TrackPropertiesDialog` fait déjà les choses correctement : un Undo
avant le dialogue, retiré si Annuler ou si rien n'a changé, et l'état
« modifié » rétabli (Phase 7 étape 10f1).

**Avec une prise ouverte** (`_take_begin`), `_take_end_if_idle` ne retire
l'Undo de la prise que s'il est toujours le dernier. Un réglage fait
pendant la prise, avec sa propre entrée, est donc conservé : il n'y a pas
de cas particulier à traiter.

### Décisions validées (utilisateur, 2026-10-24)

**D1 — un Undo avant chaque changement de mute, de solo ou de volume.**
- Il est pris **avant** le changement : l'instantané garde l'état
  d'avant, comme pour les autres actions.
- `_add_undo` marque le projet modifié : c'est ce qui fera proposer la
  sauvegarde à la fermeture.
- **Rien n'est fait si la valeur ne change pas**, par exemple Alt+↑ sur
  un volume à 100, ou Shift+X quand rien n'est muet. On ne crée alors
  aucune entrée vide, et le projet n'est pas marqué.
- Titres : `Mute piste 3`, `Solo pad 5`, `Démuter toutes les pistes`,
  `Désolo tous les pads`, `Volume piste 3`, `Volume pad 5`,
  `Mute pistes 2, 4` dans l'éditeur, `Propriétés pad 5`.

**D2 — regroupement des changements de volume successifs.**
- Une méthode `_add_mix_undo(title, key)` dans `mw_project.py` : `key`
  identifie le réglage, par exemple `("track_volume", 2)` ou
  `("pad_volume", 4)`.
- Un nouveau changement **n'ajoute pas d'entrée** si :
  - il porte la même `key` que le précédent ;
  - l'entrée créée par ce précédent est toujours la dernière de
    l'historique, donc sans autre action entre les deux ;
  - et il arrive **moins de 1 seconde** après le précédent. La fenêtre
    glisse : chaque changement la relance.

  Le projet est quand même marqué modifié.
- Un tour de bouton rotatif (des dizaines de CC7) ou une rafale d'Alt+↑
  ne donne ainsi qu'une entrée, et un seul Ctrl+Z revient au volume de
  départ.
- Les bascules (X, S, Shift+X, Shift+S, boutons Mute et Solo) passent
  `key=None` : **une entrée par bascule**. Une bascule de plusieurs
  pistes dans l'éditeur ne fait qu'une entrée.
- L'horloge est `time.monotonic()`, injectable pour les tests.

**D3 — dialogue de propriétés du pad** : on reprend le schéma de
`TrackPropertiesDialog`. Un Undo `Propriétés pad N` est pris avant le
dialogue. Il est retiré si on annule ou si rien n'a changé, et l'état
« modifié » d'avant est alors rétabli. Le pan et la durée y passent avec
le reste, puisque le dialogue les règle ensemble.

### Portée explicitement exclue de ce chantier

- **Le pan**, des pistes comme des pads : Alt+←/→, Alt+0, CC10 et
  SpinCtrl Pan. C'est le chantier suivant, à la demande de l'utilisateur,
  avec le reste des réglages sans Undo qu'on trouvera.
- Les CC7 et CC10 enregistrés dans `_tape` pendant une prise : ils sont
  déjà couverts par l'Undo de la prise.
- Le chargement des réglages d'un pattern lors de l'enchaînement du song
  (`mw_songs`) : ce n'est pas une action de l'utilisateur.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **13a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **13b1** | Implémentation — `_add_mix_undo` (D2) ; Undo avant chaque changement du tableau (D1) ; dialogue de propriétés du pad (D3). | `ui/mw_project.py`, `ui/key_handler_chars.py`, `ui/key_handler_alt.py`, `ui/midi_handler_window.py`, `ui/mw_pads.py`, `ui/mew_playback.py` |
| **13c1** | Tests — `_add_mix_undo` : regroupement par clé, fenêtre de 1 s glissante (horloge injectée), autre action entre deux, `key=None`. Chaque chemin du tableau : entrée créée, projet modifié, Ctrl+Z rend la valeur ; valeur inchangée sans entrée ni marquage ; dialogue du pad : Ok, Annuler, inchangé. | `tests/test_mix_undo.py` (nouveau) |
| **13d1** | Doc — clôture (DESIGN.md, `docs/SPECS.md` § Undo), `pytest` complet, mémoire ; reprise du chantier 12 à 12f3. | `docs/DESIGN.md`, `docs/SPECS.md` |

- Avant de committer 13b1 : l'utilisateur essaie dans l'appli. Muter une
  piste, tourner un bouton, puis Ctrl+Z, qui doit rétablir chaque
  réglage, le bouton d'un seul coup. Fermer l'appli doit proposer la
  sauvegarde.

**Reprise du chantier 12** (2026-10-24) : l'utilisateur revient sur la
pause. Le chantier 12 continue dès 12f3. Le chantier 13, dont le plan 13a1
est committé, viendra après la clôture du 12.

- **12f3** (chantier 12) — 9 tests, 2074 verts (deux passages) :
  - `test_midi_export.py` :
    - une piste inaudible n'a pas de piste SMF, ni aucun message sur son
      canal (notes, CC, PGM) ;
    - une seule piste audible, comme un solo ;
    - aucune piste audible : il ne reste que la conductor ;
    - `None` ;
    - un pad muet perd ses cases de grille, sur une piste synthé comme sur
      une piste kit ;
    - KIT et PATCH sont gardés ;
    - une piste aux seuls pads muets garde sa piste SMF, sans note.
  - `test_midi_export_ui.py` :
    - les paramètres suivent le router et le `VoiceManager`, le mute
      l'emportant sur le solo ;
    - la piste mutée est absente du fichier.
- **12g1** — 48 tests, 2122 verts (deux passages).
  - **Écart au plan** : les tests sont dans un nouveau fichier,
    `tests/test_gm_slot_export.py`, faute de fichier `test_rack*.py`. Le
    test des paramètres est dans `test_midi_export_ui.py`.
  - **Accesseurs** :
    - défauts à 0 ;
    - lecture dans `config` ;
    - bornes ±24 et −40..0 ;
    - une valeur non entière ou booléenne compte pour 0 ;
    - la transposition n'existe que pour un synthé ; le gain vaut pour
      tout slot non vide ;
    - les setters bornent et remplacent `config` ;
    - les réglages survivent à `to_dict` et `from_dict` du Rack.
  - **`apply_gain_db`** : 7 cas, et −N dB à ±0,3 près sur la courbe GM
    `40·log10`.
  - **Export** :
    - PATCH et GRID d'un synthé transposés, y compris négativement ;
    - piste kit et notes KIT jamais transposées ;
    - note bornée à 0..127 ;
    - réglage propre à chaque piste ;
    - gain sur le CC7 du tick 0 et sur un CC7 capturé, les autres CC
      intacts ;
    - `None` ou 0.
  - **Interface** : les réglages sont lus sur le slot, la transposition
    d'un kit est ignorée, et le fichier porte l'orgue en 79 avec un CC7 à
    57.
- **12h1** — conforme à D6.
  - `TrackPropertiesDialog` gagne `slot_gm_tuning(slot) -> (transposition,
    gain_db)`, où `None` grise le réglage, et deux `SpinCtrl` créés après
    la liste des programmes (ordre Tab). S'y ajoutent `_load_gm_tuning`,
    rappelée au changement de slot, ainsi que `get_transpose()` et
    `get_gain_db()`, qui renvoient `None` si le réglage est grisé.
  - `on_change` passe 9 valeurs au lieu de 7.
  - `mw_tracks` gagne `_slot_gm_tuning` : la transposition pour un synthé
    seulement, le gain pour tout slot non vide. `orig` compte 9 valeurs, et
    `apply` applique les deux réglages via `saved_configs`, comme le
    programme.
  - **`pytest` rouge à ce commit** : 12 tests figent l'ancien contrat
    (`test_gm_program.py`, `test_track_channels.py`,
    `test_track_properties_dialog.py`) ; ils sont adaptés en 12i1.
  - **Écoute validée** (utilisateur, 2026-10-24) : il faut transposer
    l'orgue de **+24**, et non de +12, et baisser les autres instruments.
    - +24 correspond à la mesure de 12d1. Le preset FluidR3 contient
      130 Hz à −2 dB sur la note 72, deux octaves sous la note écrite, et
      l'oreille suit cette composante grave. L'exemple « +12 » de D4
      sous-estimait l'écart, faute d'avoir tenu compte de la composante la
      plus grave.
    - Deux hypothèses de l'utilisateur ont été vérifiées et écartées. La
      racine `C5` de `DrawbarOrgan.json` vaut 72 (convention C4 = 60), et
      l'échantillon mesure 524 Hz, soit la note 72. Le mode Keyboard
      sauvegarde `kb_root_midi` dans le pattern, et une note PATCH garde
      la hauteur jouée. L'appli joue donc l'orgue à la hauteur écrite.
- **12i1** — `pytest` de nouveau vert, 2135 tests (deux passages).
  - **Adaptation des 12 tests** : les faux dialogues de
    `test_gm_program.py` et `test_track_channels.py` lisent
    `slot_gm_tuning` et rendent 9 valeurs, avec `get_transpose()` et
    `get_gain_db()`. Les appels scriptés transmettent les deux réglages.
    Le tuple initial d'`on_change` compte 9 valeurs. L'ordre Tab attendu
    est Canal → Programme → Transposition → Gain → Volume.
  - **7 tests du dialogue** (`test_track_properties_dialog.py`) :
    - synthé : actif, valeurs et bornes ;
    - kit : gain seul ;
    - slot vide, ou sans callback : tout grisé ;
    - un changement de slot recharge et transmet les réglages ;
    - `on_change` transmet les valeurs choisies ;
    - les vrais `EVT_SPINCTRL` donnent l'aperçu.
  - **6 tests de `mw_tracks`** (dans `test_gm_program.py` et non dans le
    fichier du dialogue, pour réutiliser le faux dialogue scripté) :
    - `_slot_gm_tuning` selon le genre du slot, et sa transmission ;
    - Ok enregistre `config` et garde l'Undo ;
    - Annuler rend la `config` d'origine de chaque slot touché ;
    - changé puis rétabli, l'action compte comme inchangée ;
    - un kit ne reçoit que le gain ;
    - le réglage est partagé par les pistes du même slot.

### Phase 7 étape 12a4 — Avenant : fin du fichier pile à la fin du pattern

**Origine.** Le 2026-10-24, l'utilisateur a remarqué que TiMidity reboucle
`Pat_01` environ une mesure et demie après sa fin. Diagnostic (4 mesures
à 100 BPM, soit 9,60 s) :
- le fichier dure 9,95 s. La règle D4 de 10a1 fait finir chaque piste au
  plus tard de deux instants, la fin du pattern ou le dernier note-off, et
  trois pistes ont une note qui déborde de 0,15 mesure ;
- TiMidity rend 12,45 s : il ajoute environ 2,5 s pour laisser s'éteindre
  le relâchement des instruments, puis du silence. Le son passe sous
  −60 dBFS à 10,55 s. Cette part ne dépend pas du fichier.

L'utilisateur a choisi de supprimer la part qui vient de l'export dès
maintenant, sans attendre l'export du song.

**D8 — chaque piste finit exactement à la fin du pattern**, soit
`num_bars · num_steps` pas. Cela remplace la règle « au plus tard des deux
instants » de 10a1 D4.
- Un note-off qui dépasse la fin est ramené à la fin du pattern : la note
  est coupée à la limite de la boucle. Au tick de fin, l'ordre de D7 met
  les note-off d'abord, puis `end_of_track`.
- Les autres messages ne peuvent pas dépasser la fin, puisque leur `time`
  est dans le pattern.
- **Perte acceptée** : la résonance des dernières notes, qui dans l'appli
  sonne par-dessus le retour de boucle, est coupée dans le fichier. On y
  reviendra avec l'export du song, où les patterns s'enchaînent.
- Le délai propre à TiMidity reste : un DAW, ou une boucle calée sur les
  mesures, n'en a pas.

| Étape | Contenu | Fichiers |
|---|---|---|
| **12a4** | Doc — cet avenant. | `docs/DESIGN.md` |
| **12i2** | Implémentation — `end_of_track` à la fin du pattern, note-off ramenés à la fin (D8). | `midi/midi_export.py` |
| **12i3** | Tests — note qui déborde coupée à la fin ; `end_of_track` de chaque piste à la fin du pattern ; durée `mido` égale à la durée des mesures ; note qui finit avant la fin intacte ; adaptation du test de 10i1 sur le dernier note-off. | `tests/test_midi_export.py` |
- **12i2** — conforme à D8, avec une règle élargie.
  - Le note-off d'une note qui déborde est ramené à `end_tick`.
    `end_of_track` tombe donc à la fin du pattern sur chaque piste.
  - **Écart à l'avenant** : D8 supposait que seuls les note-off pouvaient
    dépasser la fin. En fait, un événement de `_tape` peut se trouver
    au-delà de la longueur du pattern, par exemple dans une mesure 2 d'un
    pattern d'une seule mesure. Le rejeu (`_build_measure_events`) ne joue
    que les événements compris entre `lp_start` et `lp_end`.
  - L'export omet donc **tout événement**, quel que soit son etype, dont le
    tick tombe à la fin du pattern ou au-delà. Cela couvre aussi la note
    qui commencerait sur la fin par arrondi du tick : elle aurait une
    durée nulle et un note-on sans note-off.
  - **`pytest` rouge à ce commit** : 2 tests de `test_midi_export.py`.
    `test_track_end_at_pattern_end_or_last_note_off` suit l'ancienne règle
    du dernier note-off, et `test_time_conversion_16_and_32_steps` place
    une note en mesure 2 d'un pattern d'une mesure. Ils sont adaptés en
    12i3.
  - Essai : 4 mesures à 100 BPM donnent une durée `mido` de 9,600 s. Une
    note de 3 s au pas 62 est coupée au tick 7680.
- **12i3** — `pytest` de nouveau vert, 2147 tests (deux passages).
  - **Adaptation** :
    - `test_track_end_at_pattern_end_or_last_note_off` devient
      `test_track_end_at_pattern_end_even_if_note_overflows` : toutes les
      pistes finissent au tick de fin, et la note qui déborde y est
      coupée ;
    - le test de conversion des temps passe à 2 mesures, pour que sa note
      de la mesure 2 reste dans le pattern.
  - **12 nouveaux tests** :
    - durée `mido` égale à la durée des mesures, sur 3 cas (1 × 16 à
      120 BPM, 4 × 16 à 100, 2 × 32 à 90) ;
    - une note qui finit avant la fin reste intacte ;
    - une note coupée a son note-off au tick de fin, avant `end_of_track` ;
    - un événement pile à la fin ou au-delà est omis, pour les 6 etypes ;
    - une note arrondie sur le tick de fin est omise.
  - **Écoute** (utilisateur, 2026-10-24) : le rendu WAV de `Pat_01`,
    ramené à 9,600 s avec la résonance repliée sur le début, « boucle très
    précisément ».

### Clôture (12j1)

**12a1-12i3 FAITS** (commits `1625c17`..`bce9722`, 16 commits du chantier
12 et ce commit de clôture, 2147 tests verts) : **chantier Phase 7 étape 12
complet**. Un pattern exporté sonne dans un lecteur GM avec l'équilibre et
la hauteur de l'appli. Il suit le mute et le solo, et boucle pile sur ses
mesures.

**Ce que le chantier a livré** :
- **Courbe de volume GM dans l'appli** (12b1-12c1) : le gain d'une note
  est le carré de son facteur (`gm_gain`), comme dans un lecteur GM, où la
  vélocité et le CC7 suivent `40·log10`. Les projets existants sonnent
  plus bas sur les notes douces et les pistes baissées. L'utilisateur l'a
  validé à l'écoute.
- **Vélocité des cases de grille** (12d1, 12e1) : c'est le gain joué,
  volume du pad compris (`grid_velocity`). Une case par défaut sort à 127.
- **CC91 et CC93 à 0** au tick 0 de chaque piste (12d1). TiMidity les
  ignore, mais c'est la valeur juste pour un lecteur GM ou un DAW.
- **Réglages GM par slot** (12a2, 12f1, 12g1, 12h1, 12i1) :
  - transposition, de −24 à +24, pour un synthé ;
  - gain, de −40 à 0 dB, appliqué aux CC7 de la piste ;
  - deux SpinCtrl dans les propriétés de piste, avec aperçu, Annuler et
    Undo.

  L'orgue demande +24 avec FluidR3 : son preset a une composante deux
  octaves sous la note écrite.
- **Mute et solo à l'export** (12a3, 12f2, 12f3) : les pistes et les pads
  muets ou hors solo sont omis, comme au rejeu. C'est une demande de
  l'utilisateur, qui revient sur 10a1.
- **Fin du fichier pile à la fin du pattern** (12a4, 12i2, 12i3) : les
  notes qui débordent sont coupées, et les événements hors du pattern sont
  omis. Un rendu WAV de 9,600 s, résonance repliée sur le début,
  « boucle très précisément ».

**Écarts au plan** :
- trois avenants, 12a2 à 12a4, tous issus des écoutes ;
- la transposition de l'orgue est de +24, et non de +12 comme dans
  l'exemple de D4 ;
- les tests sont dans `test_gm_slot_export.py` (nouveau) et dans
  `test_gm_program.py`, faute de fichier `test_rack*.py` ;
- l'export omet tout événement hors du pattern, au-delà des seuls note-off
  prévus par D8 ;
- **pas de `~/.timidity.cfg`** : l'utilisateur le juge inutile maintenant
  que l'écart avec l'appli est expliqué, et préfère des options de
  lancement si besoin (`-EFreverb=d -EFchorus=d`).

**`docs/SPECS.md` mis à jour** :
- ligne Phase 7 ;
- slot : `gm_transpose` et `gm_gain_db` ;
- section « Courbe de volume » ;
- section Export MIDI : pistes audibles, CC91 et CC93, vélocité de grille,
  transposition, fin pile, éléments non exportés ;
- `TrackPropertiesDialog` ;
- Undo : le mute, le solo et le volume n'y passent pas encore. La liste
  annonçait le mute et le solo à tort, ce qui est corrigé.

**Laissé hors périmètre, pour la suite** :
- **Phase 7 étape 13**, l'Undo et le marquage modifié du mute, du solo et
  du volume des pistes et des pads : plan 13a1 committé (`22b3699`),
  prochain chantier. Le pan viendra ensuite.
- **Export audio en WAV**, chantier futur demandé par l'utilisateur. Il
  s'agit d'un rendu de la longueur exacte du pattern, avec la résonance
  repliée sur le début, comme la boucle validée en 12i3.
- La résonance des dernières notes, coupée à la fin du fichier, est à
  revoir avec l'export du song, où les patterns s'enchaînent.
- Le délai de bouclage propre à TiMidity (environ 2,5 s de relâchement
  et de silence).
- `SoundManager.preview_sound`, code mort et cassé (12c1).
- Un échec intermittent non identifié, vu une fois en 12e1.
- Les restes des Phase 7 étapes 10 et 11 listés dans leurs clôtures.

---

### Phase 7 étape 13 — Avancement et écarts constatés

- **13b1** (`f88f17b`) — conforme à D1, D2 et D3, avec ces précisions :
  - **Méthodes communes au volume** : `_set_track_volume_undo`
    (`mw_tracks.py`, absent de la liste de fichiers du plan) et
    `_set_pad_volume_undo` (`mw_pads.py`). Elles bornent la valeur, ne
    font rien si elle ne change pas, et servent à Alt+↑/↓, au CC7 et au
    SpinCtrl du pad.
  - **Shift+X, Shift+S** : l'Undo n'est pris que s'il y a quelque chose à
    rétablir (`any(_track_mutes)`, `voice_manager.any_mute()`, et de même
    pour le solo).
  - **Éditeur MIDI** : `_tracks_title` donne `Mute piste 3` ou
    `Mute pistes 2, 4`, une seule entrée pour toute la sélection.
  - **Avenant demandé par l'utilisateur à l'essai** (2026-10-25) : le
    titre d'un Undo de volume porte la **valeur atteinte**,
    `Volume piste 2: 80` ou `Volume pad 5: 80`. Dans un regroupement, le
    titre de l'entrée suit la dernière valeur (`UndoEntry.title` réécrit
    par `_add_mix_undo`). Cela remplace les titres `Volume piste 3` et
    `Volume pad 5` de D1.
  - **Essai dans l'appli** (utilisateur, 2026-10-25) : le mute et le
    volume de piste marchent. Le volume global, le champ « Vol: » après
    le BPM, n'a ni Undo ni marquage : il est hors périmètre, et surtout
    **il n'est pas sauvegardé** dans le `.gvp`, pas plus que le pan
    global (voir la clôture).
  - **`pytest` rouge à ce commit** : 13 échecs. 12 fausses fenêtres de
    `test_key_manager.py` et `test_midi_editor_window.py` n'ont pas les
    nouvelles méthodes ; `test_left_arrow_moves_grid` échoue en cascade
    et passe seul.
- **13c1** (`a2e7a58`) — 40 tests, 2187 verts (deux passages).
  - **Écart au plan** : pas de vraie `MainWindow`, qui chargerait le
    projet par défaut de l'utilisateur, ses sons et son cache. Les vraies
    méthodes (`ProjectMixin`, `TrackMixin`, `PadMixin`, `KeyManager`,
    `MidiHandler`, `PlaybackMixin`) tournent sur une fenêtre factice, avec
    un vrai `VoiceManager`, un `TrackRouter` sans son `__init__`, et un
    `_capture_state` réduit au mixage. Ctrl+Z passe par le vrai
    `_undo_action`.
  - **`_add_mix_undo`** :
    - même clé dans la fenêtre : une entrée, titre de la dernière valeur ;
    - la fenêtre glisse, et 1 s pile ouvre une nouvelle entrée ;
    - une autre clé, une autre action ou une bascule entre deux coupe le
      regroupement ;
    - après Ctrl+Z, un changement ne rejoint pas l'entrée annulée ;
    - un changement regroupé marque quand même le projet modifié.
  - **Chemins** : X, S, Shift+X, Shift+S (pistes et pads), Alt+↑/↓
    (rafale, bornes 0 et 100), CC7 (tour de bouton, pad avec son
    SpinCtrl, valeur inchangée), SpinCtrl et boutons M/S, éditeur MIDI
    sur plusieurs pistes. Chaque fois : entrée créée, projet modifié,
    Ctrl+Z rend la valeur ; une valeur inchangée ne crée rien.
  - **Dialogue du pad** : Ok avec changement (entrée gardée, Ctrl+Z
    restaure tout), Ok inchangé et Annuler (entrée retirée, état
    « modifié » d'avant rétabli, valeurs d'origine après un aperçu), et
    les entrées précédentes restent.
  - **Contrôle** : sur le code d'avant 13b1, 29 des 40 tests échouent ;
    les 11 autres sont les cas « rien ne change, aucune entrée ».
  - **Fakes adaptés** : `_add_mix_undo` enregistré, vraies
    `_set_*_volume_undo`, et les titres d'Undo vérifiés dans
    `test_key_manager.py` et `test_midi_editor_window.py`.

### Clôture (13d1)

**13a1-13c1 FAITS** (commits `22b3699`, `f88f17b`, `a2e7a58`, et ce
commit de clôture, 2187 tests verts) : **chantier Phase 7 étape 13
complet**. Le mute, le solo et le volume des pistes et des pads entrent
dans l'Undo et marquent le projet modifié : la fermeture propose la
sauvegarde après une séance de mixage.

**Ce que le chantier a livré** :
- **Un Undo avant chaque changement** de mute, de solo ou de volume, par
  tous les chemins : clavier (liste des pistes, pads, éditeur MIDI),
  boutons Mute et Solo, Alt+↑/↓, CC7, SpinCtrl Volume du pad. Rien n'est
  fait si la valeur ne change pas.
- **Regroupement des volumes** (`_add_mix_undo`) : un tour de bouton ou
  une rafale d'Alt+↑ ne donne qu'une entrée, `Volume piste 2: 80`, qu'un
  seul Ctrl+Z annule.
- **Dialogue de propriétés du pad** avec Undo, sur le schéma de celui
  des pistes.

**Écarts au plan** :
- le titre du volume porte la valeur atteinte (avenant de l'utilisateur) ;
- `mw_tracks.py` est touché en plus des fichiers prévus ;
- les tests n'utilisent pas de vraie `MainWindow`.

**`docs/SPECS.md` mis à jour** : ligne Phase 7, section Undo (chemins
couverts, `_add_mix_undo`, ce qui n'y passe pas encore), arborescence et
table des tests.

**Laissé hors périmètre, pour la suite** :
- **Le pan** des pistes et des pads (Alt+←/→, Alt+0, CC10, SpinCtrl Pan),
  chantier suivant voulu par l'utilisateur, avec les autres réglages sans
  Undo qu'on trouvera.
- **Le volume et le pan globaux** (`_player.volume`, 80 par défaut, et
  `_player.pan`) : **ni sauvegardés dans le `.gvp`, ni dans l'instantané
  d'Undo**. L'appli repart à 80 à chaque lancement. Il faut d'abord les
  ajouter au projet, avec une valeur par défaut pour les anciens
  fichiers, puis leur donner l'Undo et le marquage.
- **Export audio en WAV**, et les autres points listés à la clôture 12j1.

---

## Phase 7 étape 14a1 — Liste des tests de `docs/SPECS.md` à jour, et script de vérification

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 13 : `14a1`, `14b1`, `14c1`… ; un
commit imprévu inséré après `14b1` s'appelle `14b2`, `14b3`, etc.

### Origine du besoin

Relevé à la clôture 13d1 (2026-10-25) : `docs/SPECS.md` liste les fichiers
de tests deux fois, dans l'arborescence du projet et dans la table
« Tests unitaires ». **21 fichiers sur 60 n'y figurent pas.** Aucun
fichier listé n'a disparu.

Cause : rien ne demande de tenir ces listes à jour. Les clôtures de
chantier mettent à jour le fonctionnel (sections, raccourcis, dialogues),
pas la liste des tests. La table n'a été modifiée que 5 fois en 5 mois
(Phase 3, Phase 6 étapes 5b et 8a, Phase 7 étapes 4q et 13d1), à chaque
fois pour le seul fichier du chantier en cours. Les premiers fichiers
manquants datent du 2026-07-16 (Phase 6 étape 6b).

### Fichiers manquants (2026-10-25, 2187 tests verts)

`test_bend_log.py`, `test_gm_program.py`, `test_gm_slot_export.py`,
`test_kit_channel_migration.py`, `test_live_take.py`,
`test_load_project_cache.py`, `test_midi_constants.py`,
`test_midi_editor_window.py`, `test_midi_export.py`,
`test_midi_export_mix.py`, `test_midi_export_ui.py`,
`test_midi_handler_window.py`, `test_midi_parser.py`,
`test_midi_virtual_keyboard.py`, `test_pattern_grid_api.py`,
`test_pattern_properties_bug.py`, `test_playback_loop.py`,
`test_save_confirm_dialog.py`, `test_sixteen_tracks.py`,
`test_step_duration.py`, `test_track_channels.py`.

### Décisions (demande de l'utilisateur, 2026-10-25)

**D1 — rattraper les 21 fichiers** dans l'arborescence et dans la table,
à leur place alphabétique. La description de la table est tirée du
docstring d'en-tête de chaque fichier, résumée sur une ligne.

**D2 — un petit script de vérification**, `tools/check_specs_tests.py` :
- il compare les `tests/test_*.py` présents sur le disque avec les
  fichiers cités dans l'arborescence et dans la table de
  `docs/SPECS.md` ;
- il signale les fichiers absents de l'arborescence, ceux absents de la
  table, et ceux cités mais qui n'existent plus ;
- pour un fichier absent de la table, il propose une ligne prête à
  coller, avec la première phrase de son docstring ;
- code de sortie 0 si tout est à jour, 1 sinon ; `--root` pour viser un
  autre dossier (les tests du script s'en servent).
- Il est à lancer avant de committer un nouveau fichier de tests, et à
  chaque clôture de chantier.

### Portée explicitement exclue de ce chantier

- **Brancher le script dans `pytest`** (un test qui échoue si la doc
  décroche) ou dans `tests/test_all.sh` : proposé, mais l'utilisateur a
  demandé un script. On pourra le brancher plus tard.
- **Une seule liste** au lieu de deux, et **retrait des nombres de tests**
  (« (21 tests) ») qui vieillissent : proposé, non retenu pour l'instant.
- La mise à jour des descriptions des fichiers déjà listés.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **14a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **14b1** | Doc — les 21 fichiers dans l'arborescence et la table (D1). | `docs/SPECS.md` |
| **14c1** | Implémentation — le script (D2), décrit dans la section « Outils ». | `tools/check_specs_tests.py`, `docs/SPECS.md` |
| **14d1** | Tests — le script sur un faux dossier (`--root`) : tout à jour, absent de l'arborescence, absent de la table, cité mais disparu, ligne proposée, code de sortie ; et sur le vrai dépôt. Le nouveau fichier de tests est ajouté à `SPECS.md` dans ce commit. | `tests/test_check_specs_tests.py`, `docs/SPECS.md` |
| **14e1** | Doc — clôture, `pytest` complet, mémoire. | `docs/DESIGN.md` |

### Phase 7 étape 14 — Avancement et écarts constatés

- **14b1** (`a8332f5`) — les 21 fichiers dans les deux listes, à leur
  place alphabétique, avec une description tirée de leur docstring.
  - **Écart au plan** : 3 fichiers déjà dans la table manquaient à
    l'arborescence (`test_cc_event_edit_dialog.py`,
    `test_event_filter_dialog.py`, `test_midi_editor_filter.py`). Le
    relevé de 14a1 fusionnait les deux listes et ne les voyait pas ; ils
    sont ajoutés. C'est pourquoi le script vérifie chaque liste à part.
- **14c1** (`2fbf823`) — conforme à D2. Le script est décrit dans la
  section « Outils » et l'arborescence de `tools/`, et une consigne en
  tête de la table des tests rappelle de le lancer.
- **14c2** (`b1bff8c`), commit imprévu relevé en écrivant 14d1 : une ligne
  d'arborescence suivie d'un commentaire (`├── test_x.py   # …`) n'était
  pas reconnue, et le fichier aurait été signalé à tort comme absent.
- **14d1** (`ea365c6`) — 15 tests sur un faux dépôt (`--root`), 2202 verts
  (deux passages).
  - **Écart au plan** : pas de test sur le vrai dépôt. Il ferait échouer
    `pytest` dès qu'un fichier de tests manque à la doc, ce qui revient à
    brancher le script dans `pytest`, exclu par 14a1.
  - Le script a signalé `test_check_specs_tests.py` lui-même avant son
    ajout à `SPECS.md`, dans ce même commit.

### Clôture (14e1)

**14a1-14d1 FAITS** (commits `bb14990`, `a8332f5`, `2fbf823`, `b1bff8c`,
`ea365c6`, et ce commit de clôture, 2202 tests verts) : **chantier Phase 7
étape 14 complet**. `docs/SPECS.md` liste les 61 fichiers `tests/test_*.py`
dans l'arborescence et dans la table, et `python3 tools/check_specs_tests.py`
le vérifie.

**Usage retenu** : lancer le script avant de committer un nouveau fichier
de tests, et à chaque clôture de chantier.

**Laissé hors périmètre, pour la suite** :
- brancher le script dans `pytest` ou dans `tests/test_all.sh` ;
- une seule liste au lieu de deux, et le retrait des nombres de tests
  (« (21 tests) ») qui vieillissent ;
- la mise à jour des descriptions des fichiers déjà listés : celle de
  `test_midi_editor_window.py`, par exemple, ne dit pas que les bascules
  vérifient aussi l'Undo depuis 13c1 ;
- **Phase 7 étape 15**, le chantier suivant : le pan des pistes et des
  pads, puis le volume et le pan globaux, à sauvegarder d'abord dans le
  `.gvp`.

---

## Phase 7 étape 15a1 — Undo du pan, volume et pan globaux sauvegardés, points de boucle et boucle du song

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 14 : `15a1`, `15b1`, `15c1`… ; un
commit imprévu inséré après `15b1` s'appelle `15b2`, `15b3`, etc.

### Origine du besoin

- La clôture 13d1 a laissé pour la suite le **pan** des pistes et des pads,
  et les autres réglages sans Undo qu'on trouverait.
- En essayant 13b1 (2026-10-25), l'utilisateur a constaté que le **volume
  global** n'entrait pas dans l'Undo. En fait, ni le volume ni le pan
  globaux ne sont sauvegardés dans le projet.

### État des lieux constaté en code (2026-10-26, 2202 tests verts)

**Pan des pistes et des pads.** Il est sauvegardé dans le pattern
(`_track_pans`, `_voices`), et l'instantané d'Undo le contient déjà. Il
manque seulement l'appel, comme au chantier 13. Les dialogues de
propriétés de piste et de pad ont déjà l'Undo.

| Réglage | Chemin | Code |
|---|---|---|
| Pan de piste | Alt+←/→, Alt+0 sur la liste des pistes | `key_handler_alt.py` |
| Pan de piste | CC10, liste des pistes focalisée | `midi_handler_window.on_cc` |
| Pan de pad | Alt+←/→, Alt+0 hors liste des pistes | `key_handler_alt.py` |
| Pan de pad | CC10 ailleurs que la liste des pistes | `midi_handler_window.on_cc` |
| Pan de pad | SpinCtrl Pan du pad | `mw_pads._on_pan_spin` |

**Volume et pan globaux** (`DrumPlayer.volume`, 80 au lancement, et
`DrumPlayer.pan`, 0).
- Le volume global est le **volume maître** du pilote audio
  (`SoundDeviceDriver.set_master_volume`) : il s'applique à tout le
  mixage.
- Le pan global est un décalage ajouté au pan de chaque pad joué
  (`_mix_pan`).
- **Ni l'un ni l'autre n'est dans le `.gvp`, ni dans l'instantané d'Undo.**
  Nouveau projet et Ouvrir n'y touchent pas : la valeur de la séance
  continue d'un projet à l'autre, et l'appli repart à 80 et 0 à chaque
  lancement.
- L'export MIDI ne les utilise pas.

| Réglage | Chemin | Code |
|---|---|---|
| Volume global | Ctrl+↑/↓ | `key_handler_ctrl.py` |
| Volume global | `+`, `-` (et `6`) | `key_handler_chars.py` |
| Volume global | SpinCtrl « Vol: » (↑/↓ natifs) | `main_window._on_volume_spin` |
| Pan global | Ctrl+←/→, Ctrl+0 | `key_handler_ctrl.py` |
| Pan global | ←/→/↑/↓ dans le SpinCtrl « Pan: » | `key_handler_navigation.py` |
| Pan global | SpinCtrl « Pan: » | `main_window._on_pan_spin` |

**Points de boucle du pattern.** Ils sont sauvegardés dans le pattern
(`loop_start`, `loop_end`, `loop_count`, `looping`), et l'instantané les
contient et les rétablit. Aucun chemin n'a d'Undo :

| Réglage | Chemin | Code |
|---|---|---|
| Début de boucle | Ctrl+L | `key_handler_ctrl.py` |
| Fin de boucle | Shift+L | `key_handler_chars.py` |
| Réinitialisation | Alt+L | `key_handler_alt.py` |
| Tout | Dialogue Ctrl+Shift+L (`LoopSelectDialog`) | `mw_patterns._loop_select_dialog` |

**Case « Boucle » d'un song** (`song._looping`, sauvegardé avec le song).
Elle n'a pas d'Undo (`song_window._on_loop_toggle`), et elle est recopiée
dans `_player._song_looping` pendant la lecture.

### Décisions validées (utilisateur, 2026-10-26)

**D1 — pan des pistes et des pads : même schéma qu'au chantier 13.**
- `_add_mix_undo` avec les clés `("track_pan", t)` et `("pad_pan", p)`.
  Les changements successifs se regroupent s'ils arrivent à moins de 1 s
  d'écart.
- Le titre porte la valeur atteinte : `Pan piste 2: -20`, `Pan pad 5: 30`.
- Rien n'est fait si la valeur ne change pas (Alt+0 sur un pan centré,
  Alt+→ à +100).
- Deux méthodes communes, `_set_track_pan_undo` et `_set_pad_pan_undo`,
  sur le modèle de celles du volume.

**D2 — volume et pan globaux sauvegardés dans le projet** (option a) : une
seule valeur pour tout le fichier, comme un volume maître, et non une par
pattern.
- Le `.gvp` gagne une clé de premier niveau
  `"master": {"volume": 80, "pan": 0}`. `ProjectManager.VERSION` ne change
  pas : la clé est simplement absente des anciens fichiers.
- Ils entrent dans l'instantané d'Undo (`_capture_state`,
  `_restore_state`, qui remet aussi les deux SpinCtrl à jour).

**D3 — valeurs par défaut dans `data/config.json`** (lecture A) : deux clés,
`"master_volume"` et `"master_pan"`, lues par `AppConfig`. Si elles
manquent ou sont invalides, on prend 80 et 0, bornés à 0..100 et
−100..100.
- **Création** (Ctrl+N, ou lancement sans projet) : les valeurs de la
  config.
- **Ouverture d'un projet** sans clé `master` (ancien fichier) : les
  valeurs de la config. Avec la clé : celles du projet.
- **Sauvegarde** : le projet enregistre ses propres valeurs.
- **Fermeture** (Ctrl+N ou Ctrl+O vers un autre projet) : rien ne passe
  de l'ancien projet au suivant.
- L'appli **n'écrit jamais** `config.json` : l'utilisateur change les
  défauts à la main.

**D4 — Undo du volume et du pan globaux**, sur le schéma de D1 : clés
`("master_volume",)` et `("master_pan",)`, titres `Volume global: 75` et
`Pan global: -3`, rien si la valeur ne change pas. Deux méthodes communes,
`_set_master_volume_undo` et `_set_master_pan_undo`, servent à tous les
chemins du tableau.

**D5 — points de boucle et boucle du song.**
- Un Undo avant chaque changement, avec `key=None` : une entrée par action,
  sans regroupement. Titres : `Début de boucle`, `Fin de boucle`,
  `Réinitialiser la boucle`, `Boucle du pattern` (dialogue),
  `Song 03: boucle On`.
- Rien si la valeur ne change pas.
- Le dialogue Ctrl+Shift+L suit le schéma de `TrackPropertiesDialog` :
  Undo avant, retiré si Annuler ou inchangé, état « modifié » rétabli.
- Après un Ctrl+Z, `_player._song_looping` suit le song rétabli s'il est
  en lecture.

### Portée explicitement exclue de ce chantier

- **Un dialogue pour régler les paramètres de `config.json`** : demandé
  par l'utilisateur pour plus tard. Ici, la config se modifie à la main.
- L'export MIDI du volume et du pan globaux.
- Les autres réglages qui ne sont pas sauvegardés dans le projet (BPM du
  métronome, Note Repeat, mode et gamme du clavier en cours…).

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **15a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **15b1** | Implémentation — pan des pistes et des pads (D1). | `ui/mw_tracks.py`, `ui/mw_pads.py`, `ui/key_handler_alt.py`, `ui/midi_handler_window.py` |
| **15c1** | Tests — D1. | `tests/test_mix_undo.py`, fakes au besoin |
| **15d1** | Implémentation — volume et pan globaux : `config.json` (D3), `.gvp` (D2), Undo (D4). | `app_config.py`, `ui/main_window.py`, `ui/mw_project.py`, `ui/key_handler_ctrl.py`, `ui/key_handler_chars.py`, `ui/key_handler_navigation.py` |
| **15e1** | Tests — D2, D3, D4. | `tests/test_master_mix.py` (nouveau), fakes au besoin |
| **15f1** | Implémentation — points de boucle et boucle du song (D5). | `ui/key_handler_ctrl.py`, `ui/key_handler_chars.py`, `ui/key_handler_alt.py`, `ui/mw_patterns.py`, `ui/song_window.py`, `ui/mw_project.py` |
| **15g1** | Tests — D5. | `tests/test_loop_undo.py` (nouveau), fakes au besoin |
| **15h1** | Doc — clôture (DESIGN.md, `SPECS.md` § Undo, § Configuration, format `.gvp`), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- Avant de committer chaque implémentation, l'utilisateur l'essaie dans
  l'appli.

### Phase 7 étape 15a2 — Avenant : volume global par défaut à 100

Constaté en préparant 15d1 (2026-10-26) : le champ « Vol: » affiche 80
(`DrumPlayer.volume = 80`), mais **ce 80 n'est jamais transmis au pilote
audio**. `SoundDeviceDriver` démarre avec son volume maître à 1.0, soit
100 %. Le volume réel n'est appliqué qu'au premier réglage (Ctrl+↑/↓,
`+`/`-` ou le champ), et tout le mixage baisse alors d'environ 20 % d'un
coup.

Avec 15d1, la valeur du projet ou de la config est réellement appliquée à
l'ouverture. Avec un défaut à 80, tous les projets sonneraient environ
20 % plus bas qu'aujourd'hui.

**Décision (utilisateur, 2026-10-26)** : D3 est révisée. **Le volume global
par défaut est 100**, et non 80 : les projets sonnent comme aujourd'hui à
l'ouverture, et le champ affiche enfin la vraie valeur. On peut toujours
écrire `"master_volume": 80` dans `data/config.json`.
- `DrumPlayer.volume` démarre à 100.
- La valeur est appliquée au pilote dès le lancement.
- Avant de committer 15d1, l'utilisateur vérifie à l'écoute, en temps
  réel, qu'un projet sonne comme avant à l'ouverture.

### Phase 7 étape 15 — Avancement et écarts constatés

- **15b1** (`e7ebc12`) — conforme à D1 : `_set_track_pan_undo`
  (`mw_tracks.py`) et `_set_pad_pan_undo` (`mw_pads.py`), branchées sur
  Alt+←/→, Alt+0, le CC10 et le SpinCtrl Pan. Essayé par l'utilisateur.
  `pytest` rouge : 3 fausses fenêtres à adapter.
- **15c1** (`cd6a7db`) — 14 tests dans `test_mix_undo.py`, 2216 verts.
  L'instantané réduit de la fausse fenêtre ne gardait pas `_track_pans` :
  4 tests échouaient pour cette raison seule, corrigée.
- **15a2** (`d27849b`) — avenant : le volume global affiché (80) n'était
  jamais transmis au pilote, resté à 100 %. Défaut révisé à **100**.
- **15d1** (`1aabe35`) — conforme à D2, D3, D4 et à l'avenant 15a2.
  - `AppConfig.master_volume` et `master_pan` (repli 100 et 0, bornés,
    valeur invalide → défaut) ; les deux clés sont ajoutées à
    `data/config.json`, suivi par git.
  - `MainWindow._master_defaults`, appliqué au pilote dès le lancement ;
    `DrumPlayer.volume` démarre à 100.
  - `mw_project` : `_master_dict`, `_master_from_dict` (champ par champ),
    `_apply_master`, `_set_master_volume_undo`, `_set_master_pan_undo` ;
    clé `master` à la sauvegarde, à l'ouverture, dans l'instantané, et
    défauts de la config à Ctrl+N. Un instantané sans la clé laisse les
    valeurs en place.
  - **Écart au plan** : les méthodes communes sont dans `mw_project.py`
    et non dans `main_window.py`, puisque le réglage appartient au projet.
  - Essayé à l'écoute par l'utilisateur. `pytest` rouge : 6 fausses
    fenêtres à adapter.
- **15e1** (`2c84ed9`) — `tests/test_master_mix.py`, 43 tests, 2259 verts.
  Un vrai `DrumPlayer` avec un `SoundManager` simulé vérifie ce qui
  atteint le pilote. 42 des 43 tests échouent sur le code d'avant 15d1.
- **15f1** (`7e50310`) — D5.
  - **Écart au plan** : le dialogue Ctrl+Shift+L n'applique rien avant
    Ok. L'Undo est donc pris à l'Ok, seulement si une valeur change, et
    il n'y a rien à retirer si on annule.
  - `_restore_state` rétablit aussi le compteur de répétitions
    (`_loop_remaining`), synchronise `_song_looping` pendant la lecture
    d'un song, et réveille le thread de lecture.
  - Essayé par l'utilisateur ; `pytest` resté vert.
- **15f2** (`d1c930f`), commit imprévu relevé en écrivant 15g1 : le titre
  d'un point de boucle reprenait `position_str()` entier
  (`2:2:1 / 1:4:4`) ; il ne garde plus que la position.
- **15g1** (`1bec5e8`) — `tests/test_loop_undo.py`, 16 tests, 2275 verts.

### Clôture (15h1)

**15a1-15g1 FAITS** (commits `e1c4295`..`1bec5e8`, 10 commits du chantier
et ce commit de clôture, 2275 tests verts) : **chantier Phase 7 étape 15
complet**. Tous les réglages de mixage sauvegardés dans le projet, et les
boucles, entrent dans l'Undo et marquent le projet modifié.

**Ce que le chantier a livré** :
- **Undo du pan** des pistes et des pads, regroupé comme le volume
  (`Pan piste 2: -20`).
- **Volume et pan globaux** :
  - sauvegardés dans le projet (clé `master` du `.gvp`) ;
  - valeurs par défaut dans `data/config.json` (`master_volume`,
    `master_pan`), jamais écrit par l'appli ;
  - appliqués au pilote dès le lancement : le champ « Vol: » affiche
    enfin le volume réel ;
  - Undo regroupé (`Volume global: 75`).
- **Undo des points de boucle** (Ctrl+L, Shift+L, Alt+L, dialogue) et de
  la **case « Boucler » du song**.

**Écarts au plan** : l'avenant 15a2 (défaut 100), les méthodes du volume
global dans `mw_project.py`, l'Undo du dialogue de boucle pris à l'Ok, et
le correctif 15f2.

**`docs/SPECS.md` mis à jour** : ligne Phase 7, Configuration
(`master_volume`, `master_pan`), Volume et Pan global, format `.gvp`
(clé `master`, deux exemples), ProjectManager, Undo (tous les chemins
couverts).

**Laissé hors périmètre, pour la suite** :
- **Phase 7 étape 16** : le « point propre » de l'Undo. Revenir par
  Ctrl+Z à l'état sauvegardé doit effacer le marquage modifié, grâce à un
  numéro d'état et non à un booléen par entrée.
- **Un dialogue de réglage de `data/config.json`**, demandé par
  l'utilisateur.
- L'export MIDI du volume et du pan globaux.
- Les réglages qui ne sont pas sauvegardés dans le projet (métronome,
  Note Repeat, mode et gamme du clavier en cours…).

---

## Phase 7 étape 16a1 — « Point propre » de l'Undo : revenir à l'état sauvegardé efface le marquage modifié

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 15 : `16a1`, `16b1`, `16c1`… ; un
commit imprévu inséré après `16b1` s'appelle `16b2`, `16b3`, etc.

### Origine du besoin

Idée de l'utilisateur (2026-10-26, pendant le chantier 15) : on modifie un
projet, puis Ctrl+Z ramène exactement l'état du fichier sur disque. La
fermeture ne devrait alors pas proposer de sauvegarder, puisque le projet
n'a finalement pas changé. Aujourd'hui, `_project_modified` est un
booléen qui passe à vrai à la première modification et ne revient à faux
qu'à la sauvegarde, à l'ouverture ou à la création d'un projet.

### Pourquoi pas un booléen dans chaque entrée d'Undo

Mémoriser l'état « modifié » d'avant l'action dans l'entrée, puis le
rétablir par Ctrl+Z, se trompe après une sauvegarde : on ouvre, on change
un volume (l'entrée retient « non modifié »), on sauvegarde, puis Ctrl+Z.
L'entrée rétablit « non modifié » alors que l'appli a l'ancien volume et
le fichier le nouveau : la fermeture ne propose rien, et le retour arrière
est perdu.

### État des lieux constaté en code (2026-10-26, 2275 tests verts)

- `_mark_modified` (`mw_project.py`) passe le booléen à vrai. Il est
  appelé par `_add_undo`, par `_add_mix_undo` quand un réglage rejoint
  l'entrée précédente, et par `_restore_state` (donc par Ctrl+Z et
  Shift+Z).
- Le booléen passe à faux à la sauvegarde, à l'ouverture et à la création
  d'un projet.
- `UndoManager` (`undo_manager.py`) : `add`, `pop_last`, `undo`, `redo`,
  `push_future`, `push_history`. Shift+Z crée une **nouvelle**
  `UndoEntry` : l'identité d'une entrée ne suffit donc pas à repérer un
  état, d'où le numéro.
- **Annulations qui laissent le projet marqué** : une vingtaine de
  chemins prennent un Undo avant un dialogue ou une action, puis le
  retirent par `_pop_last_undo` si on annule ou si rien ne change. Ils ne
  rétablissent pas l'état « modifié » : F2 (piste, pattern, song),
  propriétés de pattern, éditeur MIDI (`mew_editing`, `mew_numpad`,
  `mew_delete_clipboard`), fenêtre Songs, `key_handler_ctrl`. Par
  exemple, F2 puis Annuler sur un projet intact affiche l'astérisque.
  Seuls `TrackPropertiesDialog`, le dialogue du pad (13b1) et la prise
  live (`_take_end_if_idle`) remettent l'état d'avant, à la main
  (`was_modified`).
- **L'historique passe d'un projet à l'autre** :
  - Ctrl+O ne vide pas l'historique. Après l'ouverture de B, Ctrl+Z
    rétablit des états de A (patterns, songs, rack) alors que le fichier
    courant reste B : un Ctrl+S écraserait B avec le contenu de A.
  - Ctrl+N ajoute une entrée « Nouveau projet ». Ctrl+Z ramène le contenu
    de l'ancien projet, mais le nom de fichier reste `noname_00x.gvp`.
- Ordre d'init de `MainWindow` : `_project_modified = False` est posé
  avant la création de `self._undo`.

### Décisions validées (utilisateur, 2026-10-26)

**D1 — un numéro d'état, tenu par `UndoManager`.**
- `UndoManager` garde `current_id` (l'état courant) et `saved_id` (l'état
  du fichier), et chaque `UndoEntry` gagne un champ `state_id` : le
  numéro de l'état qu'elle contient.
- `new_state()` : un nouveau numéro, à chaque modification (y compris un
  réglage regroupé par `_add_mix_undo`). `mark_saved()` :
  `saved_id = current_id`. `is_clean()` : `current_id == saved_id`.
- `add` range le numéro courant dans l'entrée. `undo` et `redo` rendent
  l'entrée ; `push_future` et `push_history` rangent le numéro courant
  avec l'état courant ; l'appelant rétablit `current_id` depuis l'entrée
  restaurée.
- `_project_modified` devient une **propriété** de `ProjectMixin` :
  `not self._undo.is_clean()`. Son setter garde les écritures
  existantes : `False` appelle `mark_saved()`, `True` appelle
  `new_state()`. `_mark_modified` appelle `new_state()`.
- `_restore_state` ne marque plus rien : `_undo_action` et `_redo_action`
  rétablissent le numéro de l'entrée et mettent le titre à jour.
- Revenir par Ctrl+Z à l'état sauvegardé retire l'astérisque, et la
  fermeture ne propose rien. Revenir par Ctrl+Z **avant** une sauvegarde
  laisse le projet modifié.

**D2 — correctif des annulations** : `pop_last()` rétablit le numéro de
l'entrée retirée, puisque l'état n'a pas changé. Les vingt chemins sont
corrigés d'un coup, et les rétablissements `was_modified` à la main
disparaissent (propriétés de piste et de pad, prise live).
- Cas d'une sauvegarde faite pendant une action encore ouverte (Ctrl+S
  pendant une prise live) : si `current_id == saved_id` au moment du
  retrait, `saved_id` suit aussi le numéro rétabli, car le contenu est
  le même.

**D3 — l'historique appartient à un projet** (option a) : Ctrl+O et
Ctrl+N vident l'historique (Undo et Redo). L'entrée « Nouveau projet »
disparaît. Si l'ancien projet est modifié, Ctrl+N et Ctrl+O proposent
déjà de le sauvegarder (`SaveConfirmDialog`).

### Portée explicitement exclue de ce chantier

- Comparer le contenu réel avec le fichier (un hash de l'état) : le
  numéro suffit pour tout ce qui passe par l'Undo.
- Les modifications qui ne passent ni par `_add_undo` ni par
  `_mark_modified` restent comme aujourd'hui.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **16a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **16b1** | Implémentation — numéros d'état dans `UndoManager` (D1, D2). | `undo_manager.py` |
| **16c1** | Tests — `UndoManager` : numéros, propre/sale, undo, redo, pop_last, sauvegarde pendant une action ouverte, limite d'historique. | `tests/test_undo_manager.py` |
| **16d1** | Implémentation — `ProjectMixin` (propriété, `_mark_modified`, Ctrl+Z/Shift+Z, sauvegarde, ouverture, création), retrait des `was_modified`, historique vidé à Ctrl+O et Ctrl+N (D3), ordre d'init. | `ui/mw_project.py`, `ui/main_window.py`, `ui/mw_tracks.py`, `ui/mw_pads.py` |
| **16e1** | Tests — Ctrl+Z jusqu'à l'état sauvegardé, avant et après une sauvegarde, réglage regroupé, F2 annulé, dialogues, prise live, Ctrl+O et Ctrl+N. | `tests/test_undo_clean_point.py` (nouveau), fakes au besoin |
| **16f1** | Doc — clôture, `SPECS.md` § Undo, `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- Avant de committer 16d1, l'utilisateur l'essaie dans l'appli.

### Phase 7 étape 16 — Avancement et écarts constatés

- **16b1** (`fbf0279`) — conforme à D1 et D2 : `UndoEntry.state_id`,
  `UndoManager.current_id` / `saved_id`, `new_state()`, `mark_saved()`,
  `is_clean()` ; `pop_last()` rétablit le numéro de l'entrée retirée.
  L'appli ne s'en sert pas encore ; `pytest` vert.
- **16c1** (`1e5a0bd`) — 16 tests dans `test_undo_manager.py`, qui
  échouent tous sans 16b1 ; 2291 verts.
- **16d1** (`a575fd6`) — conforme à D1, D2 et D3.
  - `_project_modified` est une propriété de `ProjectMixin`.
    `_undo_action` et `_redo_action` rétablissent le numéro de l'entrée
    et le titre ; `_restore_state` ne marque plus rien.
  - `_pop_last_undo` met aussi le titre à jour. Les `was_modified` des
    propriétés de piste et de pad et de la prise live sont supprimés ;
    `_take` ne garde plus que la signature et l'entrée.
  - `_load_project` et `_new_project` vident l'historique ; l'entrée
    « Nouveau projet » disparaît.
  - `MainWindow` crée `_undo` avant tout accès à `_project_modified`.
  - Essayé par l'utilisateur. `pytest` rouge : 13 échecs et 41 erreurs,
    tous des fausses fenêtres au contrat d'avant.
- **16e1** (`e51fce3`) — `tests/test_undo_clean_point.py`, 22 tests ;
  quatre fausses fenêtres adaptées ; 2313 verts.
  - **Contrôle non concluant** : sur le code d'avant 16d1, la fenêtre
    factice n'a pas de `_project_modified` et les 22 tests plantent à la
    préparation. Les tests de 16c1, eux, échouaient bien sans 16b1.

### Clôture (16f1)

**16a1-16e1 FAITS** (commits `4eb1bd3`, `fbf0279`, `1e5a0bd`, `a575fd6`,
`e51fce3`, et ce commit de clôture, 2313 tests verts) : **chantier Phase 7
étape 16 complet**. Revenir par Ctrl+Z à l'état du fichier efface le
marquage modifié, et la fermeture ne propose plus de sauvegarde inutile.

**Ce que le chantier a livré** :
- **Point propre** : un numéro par état, tenu par `UndoManager`, et
  « modifié » ⇔ l'état courant n'est pas celui du fichier. Ctrl+Z
  au-delà d'une sauvegarde reste correctement « modifié », ce qu'un
  booléen par entrée n'aurait pas permis.
- **Correctif des annulations** : une vingtaine de chemins (F2,
  dialogues, éditeur MIDI, fenêtre Songs…) laissaient l'astérisque après
  une annulation ; le retrait de l'entrée rétablit maintenant l'état
  d'avant.
- **Historique par projet** : Ctrl+O et Ctrl+N le vident. Avant, Ctrl+Z
  après Ctrl+O pouvait rétablir le projet précédent dans le fichier
  ouvert, et un Ctrl+S l'aurait écrasé.

**Écarts au plan** : aucun sur le fond ; le contrôle de 16e1 sur
l'ancien code n'est pas concluant (voir plus haut).

**`docs/SPECS.md` mis à jour** : ligne Phase 7, section Undo
(`pop_last_undo`, point propre, historique par projet), Ctrl+N et Ctrl+O.

**Laissé hors périmètre, pour la suite** :
- Comparer le contenu réel avec le fichier (hash de l'état) : le numéro
  suffit pour ce qui passe par l'Undo.
- Les modifications qui ne passent ni par `_add_undo` ni par
  `_mark_modified`.
- Rappel des chantiers en attente : dialogue de réglage de
  `data/config.json`, export audio WAV, 128 pads, mode Rack Synth/GM.

## Phase 7 étape 17a1 — Slot « Banque » : FluidSynth (SF2/SF3) dans le Rack, 4 emplacements de banque

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 16 : `17a1`, `17b1`, `17c1`… ; un
commit imprévu inséré après `17b1` s'appelle `17b2`, `17b3`, etc.

### Origine du besoin

- Le but suivant est l'**Import MIDI** (Phase 7 étape 18). Pour écouter un
  `.mid` importé tel qu'il a été écrit, l'utilisateur veut d'abord un vrai
  synthé General MIDI dans l'appli, et non nos seuls patches WAV.
- L'export MIDI (étapes 10 à 12) écrit déjà canal, programme, CC7, CC10 et
  vélocités GM. Un slot qui joue une soundfont doit sonner comme ce que
  l'export écrit.
- Contrainte transverse : le moteur audio Python est un **prototype**, la
  cible est C/C++. L'interface du moteur de banque doit rester étroite et
  portable, le rendu temps réel séparé de l'UI.

### Essais préalables (ctypes, 2026-10-26)

- FluidSynth 2.4.4 est installé (`libfluidsynth.so.3`), **sans** liaison
  Python (pas de pyfluidsynth) ni en-têtes de développement. libinstpatch
  est présent (le DLS est lu).
- Soundfonts dans `/usr/share/sounds/sf2/` : `FluidR3_GM.sf2` (148 Mo),
  `GeneralUser_GS.sf2`, `TimGM6mb.sf2` (6 Mo, pour les tests).
- **Plusieurs soundfonts dans une seule instance** : six chargées sans
  problème (`sfont_id` 1 à 6), puis
  `fluid_synth_program_select(synth, chan, sfont_id, bank, preset)`.
  `synth.midi-channels` vaut 16 par défaut (plage 16 à 256).
- `fluid_synth_write_float(synth, n, L, 0, 1, R, 0, 1)` rend du son, et
  peut écrire entrelacé (`lincr = rincr = 2`) directement dans un tampon
  `(frames, 2)`.
- **FluidSynth ne lit pas le SFZ** : un `.sfz` valide est refusé (essai
  SF2 puis DLS). Le SFZ viendra plus tard, par sfizz (lib C, non
  installée) ou par notre AudioSampler et un analyseur SFZ.

### État des lieux constaté en code (2026-10-26, 2313 tests verts)

**Rack** (`src/rack.py`). 16 `InstrumentSlot` (type, nom, `config`) ; types
`kit`, `synth`, `loop`, `audio`, `midi_file`, `midi_port`
(`InstrumentType`). Sauvegardé dans le `.gvp` sous `"rack"`
(`mw_project.py:192`, relu `:281`) et dans l'instantané d'Undo (`:369`,
`:513`). Programme GM, transposition et gain GM du slot servent à l'export
(`gm_program`, `gm_transpose`, `gm_gain_db`).

**Chargement des slots.** Pas de dialogue de slot : l'Explorateur (Alt+X,
`ExplorerDialog.ITEMS = ["Projects", "Preset", "Kit", "Patch", "Sound"]`,
`dialogs_simple.py:303`) charge un kit ou un patch dans `_cur_slot`
(`mw_pads._open_explorer`, `_explorer_kit`, `_explorer_patch`), **sans
Undo**.

**Routage** (`src/track_router.py`). `TrackRouter` répartit par type de
slot :

| Événement | Méthode | Aujourd'hui |
|---|---|---|
| Note de grille | `on_play` | SYNTH : note de la gamme du clavier (`_kb_notes_play[pad]`) ; sinon WAV du pad |
| Note KIT de `_tape` | `on_kit_tape` | `SoundManager.play_note` |
| Note PATCH de `_tape` | `on_patch_tape` | moteur du slot SYNTH |
| Pitch Bend, Mod Wheel | `on_bend_tape`, `on_mod_tape` | moteur du slot SYNTH |
| CC générique | `on_cc_tape` | 64/120/121/123 globaux ; 7 et 10 → volume et pan de la piste |
| Program Change | `on_program_change_tape` | **pont provisoire** `assign_slot(program % 16)` |

- Le jeu direct (pads, clavier, MIDI entrant) passe par `router.synth`, le
  moteur du slot courant chargé en aperçu (`load_slot_preview`).
- Les notes sont coupées par `threading.Timer`.
- Mute et solo : `_track_is_audible` en tête de chaque méthode.
- Canal de piste : `_track_channels` (sauvegardé dans le pattern,
  `pattern.py:160`, `:605`) ; `channel_after_slot` met une piste sur le
  canal 10 quand on lui assigne un kit, et la ramène à son canal par défaut
  quand elle quitte un kit (`track_router.py:298`).

**Pilote audio** (`src/sound_device_driver.py`). Un seul
`SoundDeviceDriver` (`main_window.py:190`). `_callback` (`:182`) mixe les
voix dans `mix`, puis `np.clip(mix * self._master_vol, …)` : le volume
global s'applique à tout ce qui passe par `mix`.

**Propriétés de piste** (`TrackPropertiesDialog`,
`dialogs_properties.py:6`). Mute, solo, slot, canal, liste de programmes
GM (`slot_program`, instruments GM ou kits GM2), transposition et gain GM
(`slot_gm_tuning`), volume, pan ; Undo avant ouverture, retiré si Annuler
ou inchangé.

**Export** (`src/midi/midi_export.py`). `build_pattern_midi` écrit au tick
0 le Program Change (`track_programs`), puis CC7, CC10, réverbération et
chorus à 0 ; les Program Change et CC de `_tape` suivent.

**Tests.** 51 tests utilisent `InstrumentType.SYNTH` ou `KIT`, dans 12
fichiers : le nouveau type ne doit pas changer le comportement des types
existants.

### Décisions validées (utilisateur, 2026-10-26)

**D1 — un moteur de banque commun FluidSynth / SFZ.** Une interface
« moteur de banque » : charger une banque, lister ses programmes, choisir
l'instrument d'un canal, note on/off, CC, Pitch Bend, Program Change,
rendu mixé dans notre callback. FluidSynth maintenant, le SFZ plus tard
derrière la même interface.

**D2 — liaison par ctypes**, pas pyfluidsynth (absent, et une dépendance
de moins). Les signatures des fonctions utilisées sont déclarées
(`argtypes`, `restype`) dans un seul module.

**D3 — un seul type de slot « Banque »** (`InstrumentType.BANK = "bank"`).
Le moteur est choisi par l'extension du fichier : `.sf2` et `.sf3`
maintenant, `.sfz` plus tard.

**D4 — 4 emplacements de banque fixes.** Un emplacement = un fichier
chargé une seule fois dans le moteur, que plusieurs slots du Rack peuvent
partager (FluidR3 n'est chargé qu'une fois, même pour huit slots). Pour le
SFZ, un emplacement sera un instrument.

**D5 — dialogue du slot Banque** : fichier de banque, numéro d'emplacement
(1 à 4), banque et programme. Il est ouvert par un nouvel élément
**« Banque »** de l'Explorateur (Alt+X), pour le slot courant.

**D6 — liste des programmes lue dans la soundfont** : les presets réels
(banque, numéro, nom), et non la liste GM fixe.

**D7 — FluidR3 par défaut.** Nouvelles clés de `data/config.json`, lues par
`AppConfig` : `"soundfonts_dir"` (défaut `/usr/share/sounds/sf2`) et
`"gm_soundfont"` (défaut `FluidR3_GM.sf2` dans ce dossier). C'est le
fichier proposé par le dialogue du slot Banque.

**D8 — le canal 10 est joué par FluidSynth** (batterie) quand la piste est
sur un slot Banque, pour regrouper le son au même endroit. Les KIT WAV
existants restent des KIT.

**D9 — pas de canal dans le slot.** Le canal reste celui de la **piste**
(étape 10f1). `channel_after_slot` est étendue : un slot Banque réglé sur
une batterie (banque 128) met la piste au canal 10 ; un slot Banque
mélodique la ramène à son canal par défaut si elle était au 10. Un
routage « canal MIDI entrant → slot » (clavier multi-timbral) sera une
table du Rack, en mode Rack 16 canaux : **hors périmètre**.

**D10 — deux pistes au même canal sur des slots Banque différents** :
avertissement dans la barre d'état ; le dernier programme envoyé
l'emporte, comme sur un vrai synthé.

**D11 — FluidSynth joue ce que l'export écrit** : volume de piste → CC7
(`volume_to_cc7`), pan → CC10 (`pan_to_cc10`), vélocité de l'export
(`grid_velocity`, étape 12e1) ; mute et solo suppriment les notes (comme
aujourd'hui, par `_track_is_audible`).

**D12 — notes de grille** : slot mélodique → gamme du clavier, comme un
slot SYNTH (`_kb_notes_play[pad]`) ; batterie (canal 10) → pad i = note GM
36 + i.

**D13 — pan global** ajouté au CC10 de chaque canal de banque (borné). Le
volume global, lui, s'applique déjà à tout `mix` dans le callback.

**D14 — code.** Nouveau paquet `src/engines/` : l'interface
(`bank_engine.py`) et `fluidsynth_engine.py`. Le pilote gagne une méthode
pour brancher une source de rendu dans son callback.

**D15 — propriétés de piste (Alt+Entrée) sur un slot Banque, en temps réel** :
changement de **canal** (dont le passage au 10 = batterie), de
**programme** (liste de la soundfont, D6), de **banque MSB (CC0) / LSB
(CC32)**, appliqués **aussitôt au moteur**. Annuler rétablit canal,
banque et programme dans le moteur ; l'Undo reste celui d'aujourd'hui.
Pour un SFZ, banque et programme seront grisés.

**D16 — note d'aperçu à chaque changement** de programme, de banque ou de
canal (do central ; grosse caisse, note 36, au canal 10), comme Alt+↑ sur
la liste des pads.

**D17 — Bank Select.** `synth.midi-bank-select` en **mode GS par défaut** :
seul le MSB choisit la banque (FluidR3 et GeneralUser numérotent leurs
banques comme le MSB : 0, 8, 16…, 128 pour la batterie). Clé
`"midi_bank_select"` de `config.json` (`"gs"` ou `"mma"`) pour passer en
**MMA** (banque = MSB × 128 + LSB). Le LSB est toujours enregistré et
exporté ; le dialogue indique qu'il est sans effet en mode GS.

**D18 — rejeu et export.** Les Program Change et CC0/CC32 de `_tape` sont
envoyés au moteur sur le canal de la piste : pour une piste sur slot
Banque, ils **remplacent le pont `program % 16`** (qui reste pour les
autres slots). L'export écrit CC0 et CC32 avant le Program Change, au
tick 0.

**D19 — découpage** : trois paires impl → tests, chacune **essayée à
l'écoute** par l'utilisateur avant le commit d'implémentation : (a)
moteur et branchement au pilote ; (b) type Banque, 4 emplacements,
`.gvp`, routage de tous les événements ; (c) dialogues (slot, propriétés
de piste) et Undo ; puis la clôture. Les tests du moteur utilisent
TimGM6mb et sont **sautés si libfluidsynth est absente**.

### Choix de conception proposés pour l'implémentation

Ces points découlent des décisions ; ils seront confirmés ou corrigés dans
« Avancement et écarts » au fil des commits.

**Interface `BankEngine`** (`src/engines/bank_engine.py`), volontairement
proche de l'API C, sans objet Python dans les appels temps réel :

| Méthode | Rôle |
|---|---|
| `load(slot, path)` → bool | charge le fichier dans l'emplacement 0..3 (remplace l'ancien) |
| `unload(slot)` | libère l'emplacement |
| `presets(slot)` → `[(bank, program, name)]` | liste lue dans la banque (D6) |
| `select(channel, slot, bank, program)` | instrument d'un canal |
| `note_on(ch, note, vel)`, `note_off(ch, note)` | notes |
| `cc(ch, num, value)`, `pitch_bend(ch, value)`, `program_change(ch, program)` | contrôles |
| `all_notes_off()`, `all_sounds_off()`, `reset_controllers()` | CC 123, 120, 121 |
| `render(out)` | ajoute `frames` échantillons stéréo float32 dans `out` `(frames, 2)` |

- `FluidSynthEngine` : une seule instance `fluid_synth`, 16 canaux, à la
  fréquence du pilote. Le `sfont_id` de chaque emplacement est gardé.
  L'API de FluidSynth est protégée par son propre verrou
  (`synth.threadsafe-api`, actif par défaut) : les appels de l'UI, des
  `threading.Timer` et du séquenceur ne demandent pas de verrou à nous.
- Le chargement d'un gros fichier (FluidR3, 148 Mo) se fait dans un fil,
  comme `_ensure_slot_synth` ; le slot reste muet jusqu'à la fin, message
  dans la barre d'état. Fichier introuvable ou refusé : message, slot muet.
- libfluidsynth absente : `FluidSynthEngine` n'est pas créé, le type
  Banque reste choisissable mais muet, avec un message.

**Pilote.** `SoundDeviceDriver.add_render_source(fn)` /
`remove_render_source(fn)` : `_callback` appelle `fn(mix)` après les voix
et avant `* self._master_vol`. Le volume global s'applique donc aussi à
FluidSynth (D13).

**Slot Banque dans le `.gvp`.**
- `config` du slot : `{"bank_slot": 0..3, "bank_msb": 0..127,
  "bank_lsb": 0..127, "program": 0..127}`. Le nom du slot est celui du
  preset (« Acoustic Grand Piano »).
- Les 4 emplacements sont sauvegardés avec le Rack :
  `"rack": {"slots": […], "bank_files": [chemin ou null] × 4}`. Ils
  entrent donc dans l'instantané d'Undo, et `_restore_state` recharge un
  emplacement seulement si son fichier a changé, puis resélectionne les
  instruments des canaux. `ProjectManager.VERSION` ne change pas : la clé
  est absente des anciens fichiers.
- Programme et banque appartiennent au **slot** (comme `gm_program`
  aujourd'hui) : deux pistes sur le même slot ont le même instrument, sur
  leurs canaux respectifs.

**Envoi aux canaux.** Le routeur tient l'état envoyé à chaque canal
(emplacement, banque, programme) et ne renvoie `select` que s'il change.
Au démarrage de la lecture, à l'ouverture d'un projet et après un Undo,
chaque piste sur slot Banque resélectionne son instrument et envoie CC7
et CC10 (D11, D13). Le jeu direct (pads, clavier, MIDI entrant) sur un
slot Banque va au canal de la piste courante.

**Export.** Une piste sur slot Banque exporte le programme et la banque du
slot (D18) ; ses notes de grille suivent D12 ; la transposition et le gain
GM (12h1) ne s'appliquent pas (SpinCtrl grisés), puisque le programme est
réel.

### Portée explicitement exclue de ce chantier

- Le **SFZ** (sfizz ou AudioSampler + analyseur) : l'interface est prévue
  pour lui, l'implémentation viendra plus tard.
- Le routage « canal MIDI entrant → slot » et le mode Rack 16 canaux
  (chantier futur « mode Rack Synth/GM »).
- Réglages de réverbération et chorus de FluidSynth (laissés à 0, comme
  l'export), polyphonie, interpolation.
- L'export audio WAV, le dialogue de réglage de `config.json`.
- L'Import MIDI lui-même (Phase 7 étape 18).

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **17a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **17b1** | Implémentation — (a) `BankEngine`, `FluidSynthEngine` par ctypes (D1, D2, D14, D17), `add_render_source` du pilote, clés `soundfonts_dir`, `gm_soundfont`, `midi_bank_select` (D7). | `src/engines/` (nouveau), `sound_device_driver.py`, `app_config.py`, `ui/main_window.py` |
| **17c1** | Tests — moteur sur TimGM6mb (chargement, presets, select, rendu non nul, note off, 4 emplacements, mode GS/MMA), source de rendu du pilote, config. Sautés sans libfluidsynth. | `tests/test_fluidsynth_engine.py` (nouveau), `tests/test_sound_device_driver.py` ou nouveau, `tests/test_app_config.py` |
| **17d1** | Implémentation — (b) `InstrumentType.BANK` (D3), 4 emplacements dans le Rack et le `.gvp` (D4), routage de tous les événements (D8, D11, D12, D13, D18), `channel_after_slot` (D9), avertissement de canal partagé (D10), export (D18). | `rack.py`, `track_router.py`, `ui/mw_project.py`, `midi/midi_export.py`, `ui/midi_handler_window.py` |
| **17e1** | Tests — Rack et `.gvp`, routage (moteur factice), canal 10, avertissement, export CC0/CC32. | `tests/test_bank_slot.py` (nouveau), tests d'export, fakes au besoin |
| **17f1** | Implémentation — (c) dialogue du slot Banque et élément « Banque » de l'Explorateur (D5, D6), propriétés de piste en temps réel (D15, D16), Undo. | `ui/dialogs_bank.py` (nouveau) ou `ui/dialogs_properties.py`, `ui/dialogs_simple.py`, `ui/mw_pads.py`, `ui/mw_tracks.py` |
| **17g1** | Tests — dialogues, application immédiate, Annuler, Undo, note d'aperçu. | `tests/test_bank_dialogs.py` (nouveau), fakes au besoin |
| **17h1** | Doc — clôture (DESIGN.md, `SPECS.md` : Rack, configuration, format `.gvp`, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

- Avant de committer 17b1, 17d1 et 17f1, l'utilisateur les essaie à
  l'écoute dans l'appli.

### Phase 7 étape 17 — Avancement et écarts constatés

- **17b1** — conforme à D1, D2, D7, D14 et D17 : `src/engines/`
  (`BankEngine`, `FluidSynthEngine` par ctypes, essai à l'écoute par
  `python3 -m engines.fluidsynth_engine` depuis `src/`),
  `SoundDeviceDriver.add_render_source` / `remove_render_source` et
  propriété `samplerate`, clés `soundfonts_dir`, `gm_soundfont`,
  `midi_bank_select` ; moteur créé par `MainWindow._init_bank_engine`
  (None sans libfluidsynth), fermé en quittant.
  - **Écart : gain.** À l'écoute, le gain par défaut de FluidSynth (0.2)
    était bien trop faible à côté de nos pads WAV normalisés (crête 1.0 ;
    FluidSynth montait à 0.05-0.09 à vélocité 100). Défaut porté à
    **1.0**, validé par l'utilisateur, et nouvelle clé
    **`"fluidsynth_gain"`** de `config.json` (0.0..10.0).
  - Essayé à l'écoute par l'utilisateur. `pytest` rouge : 1 échec, la
    fausse fenêtre de `test_live_take.py` n'a pas `_bank_engine`
    (adaptée en 17c1).
- **17c1** (`6c82f3a`) — `tests/test_fluidsynth_engine.py` (38 tests),
  sur **FluidR3_GM** à la demande de l'utilisateur (TimGM6mb en repli),
  sautés sans libfluidsynth ; seuil de son audible 1e-4, presets sans
  dépendre des noms ; source de rendu du pilote (6 tests), clés de
  config (29 tests) ; 2386 verts. FluidR3 se charge en 0,08 s.
- **17d1** (`1845318`) — conforme au plan d'origine (D3, D4, D8-D13,
  D18) : `InstrumentType.BANK`, instrument dans la config du slot, 4
  emplacements dans le Rack, le `.gvp` et l'Undo, routage de tous les
  événements, `BankPreview` pour le jeu direct, export CC0/CC32.
  - **Écart : chargement sans fil.** FluidSynth lit la soundfont à la
    demande (FluidR3 en 0,1 s) : pas de fil de chargement.
  - Essayé à l'écoute (lecture, volume, pan, pan global, mute, solo,
    export). `pytest` rouge : 27 faux objets.
- **17d2** (`4726b58`) — correctif trouvé par les tests de 17e1 :
  `assign_slot_by_user` synchronisait la banque **avant** de poser le
  canal ; une batterie était sélectionnée sur l'ancien canal de la piste.
- **17e1** (`6c0e5b3`) — `tests/test_bank_slot.py` (58 tests), 27 faux
  objets adaptés ; 2444 verts.
  - **Piège : crash de pytest à la sortie.** Un vrai `SynthEngine` sans
    pilote (créé par `assign_slot` sur un slot SYNTH) ouvre un
    `SoundDeviceDriver`, flux audio jamais fermé, qui faisait planter
    l'interpréteur après les tests (8 fois sur 10). Les tests remplacent
    désormais `track_router.SynthEngine`.
- **17e2** (`e8a2682`) puis **17e3** (`e04f96e`) — deux révisions du plan,
  ci-dessous : à l'essai de 17d1 puis de 17f1, l'utilisateur veut
  plusieurs instruments sur un même slot, puis le modèle « orchestre ».

## Phase 7 étape 17e2 — Révision du plan : programme et banque par piste

### Origine

- À l'ouverture de 17f1 (dialogues), l'utilisateur demande comment jouer
  plusieurs instruments, plus une batterie, à partir du même slot Banque.
- Dans le modèle de 17a1 à 17e1, **un slot du Rack = un instrument**
  (`config` : emplacement, MSB, LSB, programme, batterie). Plusieurs
  instruments demandent plusieurs slots qui désignent le même emplacement
  (fichier chargé une fois, D4). Chaque instrument consomme l'un des 16
  slots, partagés avec les kits et les synthés WAV : ce n'est pas un module
  GM « 16 canaux sur un slot ».
- L'Import MIDI (Phase 7 étape 18) va dans l'autre sens : un `.mid` de 16
  canaux doit devenir 16 pistes, chacune avec son canal, sa banque et son
  programme, sans consommer 16 slots.
- Décision de l'utilisateur (2026-10-27) : étudier le passage du programme
  à la **piste**, plan d'abord.

### État des lieux constaté en code (après 17e1, 2444 tests verts)

**Réglages par piste.** Ils appartiennent au **pattern** : `Pattern` porte
`_track_slots`, `_track_mutes`, `_track_solos`, `_track_volumes`,
`_track_pans`, `_track_channels` (`pattern.py:152-160`), sauvegardés par
`to_dict` (`:507-512`), relus par `from_dict` (`:598-606`), complétés par
`_extend_tracks` (`:646-652`). Ils sont copiés vers le routeur par
`_apply_pattern_from_store` (`mw_patterns.py:82-87`) et l'avance du song
(`mw_songs.py:143-148`), et retour par `_flush_pattern_to_store`
(`mw_patterns.py:67-72`). Ils entrent donc déjà dans l'Undo (dict du
pattern) et dans le `.gvp`.

**Instrument d'une banque (17d1).** Lu dans le slot : `InstrumentSlot`
`bank_msb`, `bank_lsb`, `bank_program`, `bank_drums` (`rack.py`) ;
`TrackRouter._bank_key(slot)` (`track_router.py:345`) ;
`channel_after_slot` met au canal 10 un slot dont `drums` est vrai
(`:534`) ; `gm_program` d'un slot Banque = son programme ; l'export lit
`track_banks` et `track_programs` sur le slot (`mw_project.py:112, :121`).

**Programme GM des synthés et kits** (`gm_program`, 10h3) : réglage du
**slot**, pour l'export seulement ; Alt+Entrée le modifie
(`mw_tracks.py:79-81`).

**Libellé de piste** (`mw_tracks.py:142`) : `Track_03 - Slot_06 - <nom du
slot>`.

### Décisions validées (utilisateur, 2026-10-27)

**R1 — le slot Banque ne désigne que l'emplacement.** `config =
{"bank_slot": 0..3}`. Son nom par défaut est celui du fichier
(« FluidR3_GM »). Les clés `bank_msb`, `bank_lsb`, `program`, `drums` du
slot disparaissent avec leurs accesseurs ; elles sont ignorées si un
`.gvp` les contient (seul le projet d'essai de 17d1 en a : pas de
migration).

**R2 — banque et programme appartiennent à la piste, donc au pattern**,
comme son slot et son canal. Trois nouvelles listes de `Pattern`,
sauvegardées, relues, complétées et copiées comme les autres :
`_track_programs` (0..127, défaut 0), `_track_bank_msb` et
`_track_bank_lsb` (0..127, défaut 0). Clés absentes des anciens fichiers :
valeurs par défaut. Elles ne servent qu'aux pistes sur slot Banque. Le
routeur les reçoit comme `_track_channels`.

**R3 — la batterie, c'est le canal 10.** Plus de drapeau : une piste sur
slot Banque au canal 10 joue la banque 128 de la soundfont (convention GM,
et ce que fait FluidSynth en mode GS), avec son programme (0 Standard,
8 Room, 16 Power…) ; MSB et LSB y sont sans effet. `channel_after_slot` :
un slot Banque **garde** le canal de la piste, 10 compris (seul un kit
force le 10 ; quitter un kit ramène au canal par défaut, comme
aujourd'hui).

**R4 — routeur.** `_bank_key(track)` = (emplacement du slot, 128 si canal
10 sinon `bank_number(MSB, LSB)` de la piste, programme de la piste). Le
cache par canal, l'avertissement de canal partagé (D10 : deux pistes au
même canal avec des instruments différents), le mixage CC7/CC10 et le
reste du routage de 17d1 ne changent pas. Nouveau
`set_track_program(track, program, msb, lsb)` : enregistre et resélectionne
aussitôt (Alt+Entrée temps réel, D15).

**R5 — Program Change et CC0/CC32 reçus ou rejoués** : comme en 17d1, au
moteur sur le canal de la piste, **sans** modifier les réglages
enregistrés de la piste. Un Program Change venu du contrôleur ne change
que le son ; si l'on relance la lecture, le début de lecture resélectionne
l'instrument enregistré de la piste (`on_play_start`), puis les Program
Change capturés dans `_tape` le changent en cours de route, comme sur un
vrai module (Q2).

**R6 — export.** `track_programs` et `track_banks` viennent de la piste
pour un slot Banque : CC0/CC32 (piste hors canal 10) puis Program Change au
tick 0. Le nom de la piste SMF est celui du **preset** (« Violin »), lu
dans la soundfont, à défaut celui du slot. Synthés et kits : inchangés
(`gm_program` du slot).

**R7 — libellé de piste** sur slot Banque : nom du preset de la piste
(`Track_03 - Slot_06 - Violin`, « Standard » au canal 10) ;
« (preset absent) » si la banque ne le contient pas ; nom du slot si
l'emplacement est vide.

**R8 — Alt+Entrée sur une piste Banque (D15, D16), en temps réel.**
- **Programme** : ListBox des 128 programmes de la banque de la piste,
  noms lus dans la soundfont (D6), « (vide) » pour un numéro absent ; au
  canal 10, les kits de la banque 128.
- **Banque MSB** et **LSB** : deux SpinCtrl 0..127 ; changer le MSB (ou le
  LSB en mode MMA) recharge la liste. Grisés au canal 10. Le libellé du
  LSB indique « sans effet en mode GS » en mode GS (D17).
- Chaque changement de canal, banque ou programme est appliqué aussitôt au
  moteur, avec une note d'aperçu (do central ; 36 au canal 10). Annuler
  rétablit le tout ; Undo inchangé (posé avant, retiré si Annuler ou rien
  changé).
- Transposition et gain GM grisés sur un slot Banque (programme réel).

**R9 — dialogue du slot Banque (D5 simplifié)** : élément « Banque »
ajouté en fin de liste de l'Explorateur (Alt+X) ; il règle le **slot
courant** : fichier (champ + « Parcourir… », défaut `gm_soundfont`) et
emplacement (ListBox « Emplacement 1 » à « Emplacement 4 », avec le
fichier qu'il contient déjà). Plus de liste d'instruments ici : on choisit
l'instrument par piste (R8). Appliqué à Ok ; Undo posé avant, retiré si
Annuler ou rien changé. Remplacer le fichier d'un emplacement change le son
de tous les slots qui le désignent : le dialogue l'annonce.

**R10 — synthés et kits inchangés.** Leur programme GM d'export reste un
réglage du slot. Le passer aussi à la piste serait cohérent, mais c'est un
autre chantier (non demandé).

### Questions tranchées (utilisateur, 2026-10-27)

- **Q1 — programme par pattern** (R2), comme le slot et le canal : changer
  de pattern peut changer d'instrument. Un fichier `.mid` est un pattern
  (Import MIDI, étape 18).
- **Q2 — un Program Change du contrôleur ne change que le son**, pas le
  programme enregistré de la piste (R5) : la piste se règle par Alt+Entrée,
  avec Undo, et la relance de la lecture rejoue le programme enregistré.

### Ce qui est repris de 17d1 et 17e1

- `rack.py` : accesseurs `bank_msb/lsb/program/drums` retirés ;
  `gm_program` d'un slot Banque → None ; `channel_after_slot` sans la
  clause batterie du slot.
- `track_router.py` : `_bank_key` par piste, listes de piste, R4.
- `pattern.py`, `mw_patterns.py`, `mw_songs.py` : trois listes (R2).
- `mw_project.py` : paramètres d'export (R6).
- `tests/test_bank_slot.py` : une vingtaine de tests à réécrire (config du
  slot, batterie, `channel_after_slot`, sélection, export) ; le reste
  (emplacements, rejeu, jeu direct, contrôles globaux) ne change pas.

### Portée exclue

Inchangée par rapport à 17a1 (SFZ, routage canal entrant → slot, mode Rack
16 canaux, réglages de réverbération et chorus, export WAV, Import MIDI).

### Découpage en commits révisé

| Étape | Contenu | Fichiers |
|---|---|---|
| **17e2** | Doc — cette révision. | `docs/DESIGN.md` |
| **17f1** | Implémentation — R1 à R7 : slot = emplacement, banque et programme par piste dans le pattern, batterie = canal 10, routeur, export, libellé de piste. Essayé à l'écoute. | `rack.py`, `pattern.py`, `track_router.py`, `ui/mw_patterns.py`, `ui/mw_songs.py`, `ui/mw_project.py`, `ui/mw_tracks.py` |
| **17g1** | Tests — R1 à R7, `tests/test_bank_slot.py` adapté. | `tests/test_bank_slot.py`, tests de Pattern au besoin |
| **17h1** | Implémentation — R8 et R9 : Alt+Entrée en temps réel sur une banque, dialogue du slot Banque dans l'Explorateur, Undo. Essayé à l'écoute. | `ui/dialogs_properties.py`, `ui/dialogs_bank.py` (nouveau), `ui/dialogs_simple.py`, `ui/mw_pads.py`, `ui/mw_tracks.py` |
| **17i1** | Tests — dialogues, temps réel, Annuler, Undo, note d'aperçu. | `tests/test_bank_dialogs.py` (nouveau), fakes au besoin |
| **17j1** | Doc — clôture (avancement 17c1 à 17i1, SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

## Phase 7 étape 17e3 — Révision du plan : le canal est l'instrument (modèle « orchestre »)

### Origine

- Essai à l'écoute de 17f1 (non committé), programme par piste (17e2) :
  quatre pistes sur un seul slot Banque s'entendent bien. Mais changer le
  canal d'une piste dans Alt+Entrée ne fait pas toujours entendre l'instrument
  du nouveau canal : quand deux pistes partagent un canal, la piste de plus
  grand numéro l'emporte (D10). La basse (piste 4) mise au canal 1 garde
  son son, et c'est le piano qui devient basse.
- L'utilisateur précise son modèle (2026-10-27) : **le canal est un
  instrument de l'orchestre, les pistes sont les musiciens.** Un musicien
  joue l'instrument qu'il veut, et peut en changer, donc changer de canal,
  en cours de morceau.
- Il demande que canal, programme et banque soient des **événements de la
  piste**, écrits à la validation de Alt+Entrée, visibles dans la liste des
  événements et modifiables à la main ou par automation.
- Pas de nouveau type d'événement « canal » : le Program Change porte déjà
  un numéro de canal. Pour changer de canal, on écrit un nouveau Program
  Change.

**Principe directeur** (utilisateur, 2026-10-27) : les normes MIDI et les
banques GM n'entrent dans l'appli que pour retrouver les habitudes des
séquenceurs comme **Sonar**, efficaces pour enregistrer et composer. En
cas de doute, on reproduit leur comportement.

### État des lieux constaté en code

- `TapeEvent.channel` existe pour tous les événements. À la capture, il
  reçoit le canal **du contrôleur** (`record_program_change(program,
  channel)`, `dp_recording.py:256`). À l'export, il est ignoré : tout
  s'écrit sur le canal de la piste
  (`test_every_event_on_track_channel_not_ev_channel`,
  `test_midi_export.py:152`).
- Rejeu : `PGM_TAPE_EVENT` transmet `(piste, programme)` sans le canal
  (`dp_playback.py:180-183`) ; `TrackRouter.program_change` l'envoie sur
  le canal de la piste.
- Aucune « poursuite » : démarrer au milieu du pattern ne renvoie pas les
  Program Change déjà passés.
- Export : à tick égal, le Program Change s'écrit **avant** les CC
  (`_ORDER_PGM = 1 < _ORDER_CC = 2`, `midi_export.py:34-35`). Des CC0 /
  CC32 de `_tape` au même tick qu'un Program Change arriveraient après lui
  et ne choisiraient pas la banque.

### Décisions validées (utilisateur, 2026-10-27)

Gardées de 17e2 : **R1** (slot Banque = emplacement seul), **R3** (canal
10 = batterie, banque 128 ; un slot Banque garde le canal de la piste),
**R7** (libellé de piste = nom du preset), **R9** (dialogue du slot Banque :
fichier et emplacement), **R10** (synthés et kits inchangés), **Q1**
(tout appartient au pattern ; un `.mid` est un pattern) et **Q2** (un
Program Change du contrôleur, hors enregistrement, ne change que le son).
**Abandonnée : R2** (listes `_track_programs`, `_track_bank_msb`,
`_track_bank_lsb` du pattern, écrites en 17f1 et non committées) : la
source devient les événements (O2).

**O1 — le canal est l'instrument.** Chacun des 16 canaux a un instrument
(programme, MSB, LSB), entendu par toutes les pistes de ce canal. Le
routeur tient l'instrument courant de chaque canal ; sans Program Change,
programme 0 banque 0 (au canal 10 : kit 0 de la banque 128).

**O2 — les événements de la piste sont la seule source.** Program Change
(`ETYPE_PGM`), CC0 et CC32 (`ETYPE_CC`) de `_tape`. L'**entête** d'une
piste = ses CC0, CC32 et Program Change à 1.1.1. Ils sont visibles dans la
liste des événements (Ctrl+2), modifiables, et l'Import MIDI les
produira directement.

**O3 — le Program Change porte le canal.** Le canal courant d'une piste,
à un instant, est celui de son **dernier Program Change** avant cet
instant ; avant le premier, le canal de la piste (`_track_channels`).
Changer de canal en cours de morceau = écrire un Program Change sur un
autre canal. Un Program Change change aussi l'instrument de son canal
(O1), comme sur un vrai module.
- Les notes, CC, Pitch Bend de la piste vont à son canal courant (leur
  propre champ `channel` reste ignoré, comme aujourd'hui).
- Modifier à la main le canal d'un Program Change à 1.1.1 change aussi le
  canal de la piste (`_track_channels`), pour que Alt+Entrée, le libellé et
  l'export restent d'accord.

**O4 — poursuite (chase).** Au début de la lecture, en partant de
n'importe quelle position, au chargement d'un pattern, à l'avance du song
et après un Undo : pour chaque canal, l'appli renvoie au moteur le dernier
CC0, CC32 et Program Change rencontrés avant la position (toutes pistes
confondues, à temps égal dans l'ordre des pistes), et chaque piste reprend
le canal de son dernier Program Change. Remplace la resélection de
`on_play_start` (17d1).

**O5 — Alt+Entrée sur une piste Banque, choix B : le canal impose son
instrument.**
- Programme, MSB et LSB affichés = l'instrument **du canal choisi**.
  Passer la piste sur un autre canal fait entendre et afficher
  l'instrument de ce canal.
- Changer le programme ou la banque change l'instrument du canal, en
  direct, pour toutes ses pistes, avec la note d'aperçu (D16).
- **Ok** écrit l'entête de la piste : CC0, CC32 et Program Change à 1.1.1,
  sur le canal de la piste, en remplaçant les précédents.
- **Les autres pistes du même canal** qui ont un entête le reçoivent mis à
  jour aussi (message dans la barre d'état) : le canal reste cohérent.
- **Annuler** rétablit canal et instrument dans le moteur ; Undo comme
  aujourd'hui (posé avant, retiré si Annuler ou rien changé).
- **Précision 17f2 (essai de 17f1, utilisateur, 2026-10-27) : piste
  temporaire pendant le dialogue.** Si la lecture tourne en boucle pendant
  Alt+Entrée, la poursuite et le rejeu de l'entête d'origine ramenaient la
  piste à son ancien canal et à son ancien son à chaque tour. Donc, dès
  l'ouverture, la piste (et les autres pistes du canal touchées) est
  copiée ; chaque changement de canal, de programme ou de banque réécrit
  aussitôt l'entête **dans la piste**, temporairement, si bien que le
  bouclage rejoue le nouveau réglage. **Ok** garde ces entêtes ;
  **Annuler** remet les pistes d'origine, puis la poursuite rétablit
  canaux et instruments.

**O6 — entête seulement pour les pistes sur slot Banque.** Sur un synthé
WAV ou un kit, un Program Change réassigne le slot (pont `program % 16`) :
Alt+Entrée n'y écrit pas d'entête.

**O7 — capture : le Program Change est remis au canal de la piste
(validé).** Un Program Change enregistré depuis le contrôleur
porte le canal du contrôleur. Avec O3, il ferait changer la piste de canal.
À la capture, Program Change, CC0 et CC32 reçoivent le **canal
courant de la piste** (comme le « rechannelize » d'un séquenceur). Changer
de canal reste un geste explicite : Alt+Entrée, ou édition de l'événement.

**O8 — export.**
- À tick égal, CC0 et CC32 s'écrivent avant le Program Change ; les
  autres CC restent après (ordre D7 sinon inchangé).
- Chaque événement s'écrit sur le canal courant de la piste à son instant
  (O3) : une piste peut changer de canal dans le fichier, ce que le SMF
  permet.
- Pistes Banque : plus de `track_programs` ni de CC0/CC32 de slot au tick
  0, l'entête de `_tape` suffit ; notes de grille au canal 10 = 36 + pad,
  selon le canal courant. Nom de la piste SMF = preset de l'entête.

### Ce qui change dans 17f1 (non committé)

- Retirés : les trois listes de `Pattern` et du routeur (R2),
  `set_track_program`, leur copie dans `mw_patterns.py` / `mw_songs.py`,
  les paramètres d'export qui en dépendent.
- Gardés : `rack.py` (slot = emplacement, `gm_program` None pour une
  banque), `channel_after_slot` (une banque garde le canal), libellé de
  piste et `bank_preset_name` (lu sur l'instrument du canal de la piste),
  cache des noms de presets.

### Découpage en commits révisé

| Étape | Contenu | Fichiers |
|---|---|---|
| **17e3** | Doc — cette révision. | `docs/DESIGN.md` |
| **17f1** | Implémentation — R1, R3, R7, O1 à O4, O7, O8 : slot = emplacement, instrument par canal tiré des événements, canal porté par le Program Change au rejeu, poursuite, capture au canal de la piste, export. Essayé à l'écoute. | `rack.py`, `track_router.py`, `player/dp_playback.py`, `player/dp_recording.py`, `midi/midi_export.py`, `ui/mw_project.py`, `ui/mw_patterns.py`, `ui/mw_songs.py`, `ui/mw_tracks.py` |
| **17g1** | Tests — 17f1 ; `tests/test_bank_slot.py` et tests d'export adaptés. | `tests/test_bank_slot.py`, `tests/test_midi_export.py`, tests du player au besoin |
| **17h1** | Implémentation — O5, O6, R9 : Alt+Entrée (canal impose l'instrument, écriture des entêtes), dialogue du slot Banque, édition du canal d'un Program Change à 1.1.1 (O3). Essayé à l'écoute. | `ui/dialogs_properties.py`, `ui/dialogs_bank.py` (nouveau), `ui/dialogs_simple.py`, `ui/mw_pads.py`, `ui/mw_tracks.py`, éditeur d'événements |
| **17i1** | Tests — dialogues, temps réel, entêtes, Annuler, Undo. | `tests/test_bank_dialogs.py` (nouveau), fakes au besoin |
| **17j1** | Doc — clôture (avancement 17c1 à 17i1, SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 7 étape 17 — Avancement après les révisions (17f1 à 17i1)

- **17f1** (`025e221`) — conforme à 17e3 (R1, R3, R7, O1-O4, O7, O8) :
  slot Banque = emplacement ; instrument des 16 canaux dans le routeur
  (`channel_instrument`) ; canal courant par piste (`track_channel_now`),
  celui de son dernier Program Change ; `program_change` /
  `bank_select` au canal de l'événement ; `chase(tape, pos)` au
  démarrage, à chaque saut, au changement de pattern, à l'avance du song
  et après Undo ; capture remise au canal de la piste ; export : Bank
  Select avant le Program Change à tick égal, canal qui suit la piste.
  - **Précision de O3** : CC0 et CC32 vont, comme le Program Change, à
    **leur propre canal** (et non au canal courant de la piste), pour
    qu'un entête qui change de canal choisisse la banque du bon canal.
  - Essayé à l'écoute : bon. `pytest` rouge : 28 tests.
- **17f2** (`aac5b79`) — précision de O5 trouvée à l'essai : pendant les
  propriétés de piste, la boucle rejouait l'entête d'origine ; la piste
  est donc copiée et son entête réécrit en direct.
- **17g1** (`a879d35`) — `tests/test_bank_slot.py` réécrit (77 tests) ;
  2467 verts.
- **17h1** (`c2f7df8`) — conforme à O5, O6, R8, R9 et 17f2 : propriétés de
  piste en direct sur une banque (liste du canal, MSB / LSB, entêtes,
  autres pistes du canal, note d'aperçu, Annuler) ; `BankSlotDialog`
  (élément « Banque » d'Alt+X) ; champ Canal des CC et Program Change
  dans l'éditeur MIDI (un Program Change à 1.1.1 donne son canal à la
  piste).
  - **Écart : raccourci.** Le plan disait « Ctrl+T » pour les propriétés
    de piste ; c'est **Alt+Entrée** (ou Ctrl+Maj+T). Ctrl+T assigne le
    slot à la piste. Corrigé dans le plan et dans `SPECS.md`.
  - **Correctif de l'essai : aller-retour de canal.** La basse, seule à
    définir le canal 4, le quittait ; la poursuite remettait ce canal à
    l'état GM (piano) et le retour de la basse imposait le piano. Le
    dialogue retient l'instrument des 16 canaux à son ouverture.
  - Essayé à l'écoute. `pytest` rouge : 28 tests.
- **17i1** (`77fc811`) — `tests/test_bank_dialogs.py` (32 tests), tests de
  l'édition du canal ; 28 tests adaptés ; 2506 verts.

### Clôture (17j1)

**17a1-17i1 FAITS** (commits `ee09786` à `77fc811`, et ce commit de
clôture, 2506 tests verts) : **chantier Phase 7 étape 17 complet**.
L'appli joue les soundfonts SF2 / SF3 par FluidSynth, comme un module GM
dont les pistes sont les musiciens.

**Ce que le chantier a livré** :
- **Moteur de banque** (`src/engines/`) : `BankEngine`, interface étroite
  et portable (cible C/C++), et `FluidSynthEngine` par ctypes, rendu
  dans le callback du pilote ; clés `soundfonts_dir`, `gm_soundfont`,
  `midi_bank_select`, `fluidsynth_gain`.
- **Slot Banque** : un emplacement parmi 4 (un fichier chargé une fois,
  partagé), sauvegardé dans le `.gvp` et l'Undo ; dialogue « Banque »
  de l'Explorateur.
- **Modèle « orchestre »** : le canal est l'instrument ; programme et
  banque sont des événements de la piste (entête à 1.1.1), visibles et
  modifiables ; le Program Change porte le canal de la piste ;
  poursuite à toute position ; canal 10 = batterie.
- **Propriétés de piste en direct** : le canal impose son instrument,
  programme et banque au son près, entêtes réécrits (boucle comprise),
  Annuler.
- **Export** fidèle : Bank Select avant le Program Change, canal qui
  suit la piste, nom du preset.

**Écarts au plan** : deux révisions de fond (17e2, puis 17e3, qui
remplace 17e2), une précision (17f2), le gain par défaut de FluidSynth
(1.0), le chargement sans fil, le raccourci (Alt+Entrée), deux
correctifs trouvés à l'essai ou par les tests (17d2, aller-retour de
canal) ; voir plus haut.

**`docs/SPECS.md` mis à jour** : ligne Phase 7, arborescence
(`src/engines/`, `dialogs_bank.py`), configuration, Rack (type BANK,
`bank_files`), section « Banques de sons », TrackRouter, Program Change,
export, format `.gvp`, boîtes de dialogue, Explorateur, tests ;
`docs/shortcuts.md` : Alt+X, propriétés de piste, édition d'un CC ou
d'un Program Change.

**Restent à essayer** (pas de matériel ou pas encore fait) :
- le jeu au contrôleur MIDI sur une banque (notes, Program Change, Bank
  Select en direct, enregistrement au canal de la piste) ;
- des pistes de deux banques différentes jouées ensemble.

**Laissé hors périmètre, pour la suite** :
- le **SFZ** (sfizz ou AudioSampler + analyseur), derrière la même
  interface ;
- le routage « canal MIDI entrant → slot » et le mode Rack 16 canaux ;
- la poursuite à la reprise d'une boucle qui ne commence pas à 1.1.1 ;
- les noms des cases d'une banque au canal 10 dans l'éditeur MIDI ;
- réverbération, chorus, polyphonie de FluidSynth ;
- **Phase 7 étape 18 : Import MIDI** (le but initial du chantier).

## Phase 7 étape 18a1 — Import MIDI : un fichier `.mid` devient un pattern

### Numérotation des commits de ce chantier

`18a1` = ce plan (doc seule). Le code commence à `18b1`. Une paire impl →
tests par sous-chantier ; `18a2`, `18b2`… pour un commit imprévu.

### Origine du besoin

- But initial du chantier 17 : l'utilisateur voulait d'abord un vrai
  synthé GM (slot Banque, FluidSynth) pour **écouter fidèlement les `.mid`
  importés**. Le chantier 17 est clos (17j1) ; l'import vient maintenant.
- Acquis à respecter :
  - **un `.mid` = un pattern** (Q1 de 17e2, gardée en 17e3) ;
  - **modèle « orchestre »** (17e3) : le canal est l'instrument ; les
    Program Change, CC0 et CC32 d'une piste sont ses événements, l'entête
    à 1.1.1 ; le Program Change porte le canal. O2 annonçait déjà que
    « l'Import MIDI les produira directement » ;
  - l'**export** existe (`src/midi/midi_export.py`, mido, SMF 1, PPQ 480) :
    l'import en est l'inverse, et un aller-retour export → import doit
    rendre le même pattern ;
  - comportement de référence : **Sonar**.

### État des lieux constaté en code (2026-10-29, 2506 tests verts)

- **mido 1.3.3** installé, déjà utilisé par l'export ; aucun code de
  lecture de `.mid` dans l'appli. `InstrumentType.MIDI_FILE` existe dans
  `rack.py` mais n'est utilisé nulle part : sans rapport avec ce chantier
  (slot de lecture de fichier, jamais commencé).
- **Positions** (`pattern.py`) : `TapeEvent.time` = pas cumulés
  (`mesure × _num_steps + pas`). Les notes (GRID, KIT, PATCH) sont posées
  sur un **pas entier** (`dp_recording.py:148`, `:223` ; commentaire de
  `_clipboard_to_dict`, `mw_project.py:404`) ; CC et Pitch Bend sont en
  **temps flottant** (`record_cc`, `record_bend`, Phase 7 étape 5b).
- **Résolution** : `_num_steps` ∈ `VALID_NUM_STEPS = (16, 32, 64, 128)` pas
  par mesure ; `_num_bars` 1..999.
- **Signature** : `_num_beats = 4` et `_denumerator = 4` existent, mais
  **ne sont ni sauvés ni relus** (`to_dict` / `from_dict`) et aucune UI ne
  les change : une mesure fait toujours 4 noires. L'export écrit
  `time_signature 4/4` et convertit `tick = steps × PPQ × 4 / num_steps`.
- **Tempo** : `_bpm` entier par pattern (SpinCtrl 1..600,
  `main_window.py:233`) ; un temps = 60 / BPM (Phase 7 étape 10b1).
- **Durée d'une note PATCH en millisecondes** (`ev.dur`, mesurée au
  note-off ; l'export la convertit au BPM : `ms_ticks`). Une note
  importée doit donc recevoir sa durée en ms au BPM du pattern.
- **16 pistes** par pattern ; `_track_channels` (canal 0..15 par piste),
  `_track_slots`, `_track_volumes` (0..100), `_track_pans` (-100..+100).
  Au rejeu, un CC7 / CC10 de `_tape` règle le volume / pan de la piste
  (`TrackRouter.on_cc_tape`, `track_router.py:835`) ; l'export écrit leur
  inverse exact (`volume_to_cc7`, `pan_to_cc10`).
- **Entête** : `bank_header` / `with_bank_header` (`pattern.py:66-89`) ;
  canal courant d'une piste = celui de son dernier Program Change
  (`TrackRouter.chase`, `track_router.py:505`).
- **Notes sur une banque** : un PATCH est joué tel quel au canal courant
  de la piste, canal 10 compris (`on_patch_tape`, `track_router.py:768`) ;
  l'export garde la note telle quelle. Une note de batterie importée en
  PATCH sonne donc juste au canal 10, avec sa durée.
- **Noms de pistes** : le nom d'une piste (F2, `_rename_track`,
  `mw_tracks.py:206`) est le nom du **pad** du même numéro
  (`voice_manager.get_name`, sauvé dans `Pattern._voices`). Le libellé
  d'une piste Banque affiche le preset de son canal (`bank_preset_name`).
- **Rack** : 16 slots, 4 emplacements de banque (`Rack.bank_files`,
  `set_bank_file`) ; `AppConfig.gm_soundfont` (FluidR3 par défaut).
- **Raccourcis** : Alt+Shift+E = export (fenêtre principale,
  `key_handler_alt.py:83`, et éditeur MIDI, `mew_keymap.py:333`).
  **Alt+Shift+I est libre** dans la fenêtre principale. Dans l'éditeur
  MIDI, le test de Shift+I (limiteur gauche, `mew_keymap.py:267`) ne
  regarde pas Alt : Alt+Shift+I doit être testé **avant** lui.

### Décisions validées (utilisateur, 2026-10-29)

**I1 — Commande.** **Alt+Shift+I** (fenêtre principale et éditeur MIDI,
comme l'export) ouvre un dialogue de fichier `*.mid` / `*.midi`, dans le
dossier EXPORTS (`exports_dir`) par défaut.

**I2 — Destination : le pattern courant** (choix a). S'il n'est pas vide,
une confirmation Oui / Non le dit avant de le remplacer. Un Undo
« Import MIDI : nom.mid » est posé avant ; Non ou une erreur de lecture
le retirent (`_pop_last_undo`). Le pattern est entièrement remplacé :
boucle, mute, solo, voix des pads remis aux valeurs d'un pattern neuf,
puis rempli par l'import. Son nom = nom de la piste conductor, sinon nom
du fichier sans extension.

**I3 — Slot : le premier slot Banque du Rack** (choix a). Toutes les
pistes importées y sont assignées. S'il n'y en a pas, l'import en crée un
dans le **premier slot vide**, avec la soundfont `gm_soundfont` : à
l'emplacement de banque qui la contient déjà, sinon au premier emplacement
libre, sinon à l'emplacement 1 tel qu'il est. Rack plein et sans slot
Banque : import refusé, message dans la barre d'état. Le Rack est dans
l'état de l'Undo : I2 le couvre.

**I4 — Notes arrondies au pas** (choix de l'utilisateur). L'import prend
le plus petit nombre de pas par mesure (16, 32, 64, 128) qui place
**toutes** les notes exactement ; sinon 128 (1/32 de noire), chaque note
arrondie au pas le plus proche, et le compte rendu dit combien de notes
ont bougé. CC, Pitch Bend et Program Change hors entête gardent leur
position exacte (temps flottant). **Chantier suivant prévu : les notes en
temps flottant**, pour une précision complète (voir « Portée exclue »).

**I5 — Noms des pistes : écrits comme noms de pistes F2** (choix b). Le
nom SMF (`track_name`) est nécessaire pour savoir quel instrument doit
jouer la piste. Il va dans le nom du pad du même numéro
(`Pattern._voices[t]["name"]`), avec le mélange pistes / pads connu
(séparation hors périmètre). Un nom vide laisse le nom vide.

**I6 — Pistes.** Une piste Groovebox par couple (piste SMF, canal) qui
porte au moins un événement de canal, dans l'ordre du fichier. Un SMF de
type 0 (une piste, plusieurs canaux) donne donc une piste par canal. Une
piste ne joue que sur un canal à la fois (O3) : c'est pourquoi une piste
SMF à plusieurs canaux est découpée. Plus de 16 pistes : les pistes d'un
même canal sont fusionnées (16 canaux au plus, donc 16 pistes au plus),
nom de la première ; le compte rendu le dit. SMF de type 2 : refusé.
`_track_channels[t]` = canal de la piste.

**I7 — Entête.** Les Program Change, CC0 et CC32 d'une piste **placés
avant sa première note** vont à 1.1.1 (beaucoup de fichiers les posent
quelques ticks après 0), dans l'ordre CC0, CC32, Program Change ; s'il y en
a plusieurs du même type, le dernier l'emporte (comme un module qui les
reçoit dans l'ordre). Chacun garde son propre canal (O3). Après la
première note, ils restent des événements à leur position. Sans Program
Change, pas d'entête : le canal garde l'instrument GM 0 (O1), kit 0 au
canal 10.

**I8 — Volume et pan.** Les CC7 et CC10 placés avant la première note
règlent `_track_volumes` / `_track_pans` (même conversion que
`on_cc_tape` : `round(v × 100 / 127)`, `round((v − 64) × 100 / 63)`), le
dernier l'emportant ; ils ne vont pas dans `_tape`. Ceux d'après restent
des événements CC. Un export suivi d'un import rend ainsi le même volume
et le même pan.

**I9 — Événements.**
- note on / note off (note on de vélocité 0 = note off) → **ETYPE_PATCH**
  (note, vélocité), position arrondie (I4), durée en ms au BPM du pattern
  (au moins 1 ms) ; appariement premier entré, premier sorti pour une même
  note ; note jamais fermée = fermée à la fin de sa piste ;
- control change → **ETYPE_CC**, CC91 / CC93 compris (tels quels) ;
- pitchwheel → **ETYPE_BEND** ;
- program change → **ETYPE_PGM** ;
- le champ `channel` de chaque événement = son canal MIDI ;
- ignorés et comptés dans le compte rendu : aftertouch de canal et
  polyphonique (pas d'etype), SysEx (dont les reset GM / GS), métas autres
  que nom de piste, tempo, signature et fin de piste.

**I10 — Tempo, signature, longueur.**
- BPM = premier `set_tempo` (arrondi, borné 1..600), 120 sans tempo (défaut
  MIDI). Les changements de tempo suivants sont ignorés et comptés : les
  positions en noires ne dépendent pas du tempo ; seul le rythme change.
- Signature : la mesure reste de 4 noires (`_num_beats` n'est pas
  sauvé) ; une autre signature est annoncée dans le compte rendu, les
  événements gardent leur position en noires.
- Conversion : `steps = tick × num_steps / (PPQ du fichier × 4)`.
- Longueur : `_num_bars` = fin la plus tardive (dernier note-off ou
  `end_of_track` de la piste la plus longue), arrondie à la mesure
  supérieure, bornée 1..999 ; au-delà de 999 mesures, les événements sont
  perdus, et comptés.

**I11 — Après l'import.** Pattern rechargé comme un changement de pattern
(poursuite O4 comprise), listes et grille rafraîchies, projet marqué
modifié (par l'Undo). Compte rendu dans la barre d'état, par exemple :
« Import MIDI : song.mid → Pattern 03, 8 pistes, 32 mesures, 96 BPM,
128 pas ; 12 notes déplacées ; ignorés : 40 aftertouch, 2 SysEx ».

**I12 — Code.** `src/midi/midi_import.py`, sans wx ni player (comme
l'export) : `build_pattern_from_midi(mid, *, name)` rend un `Pattern`
neuf (avec `_track_channels`, volumes, pans, noms dans `_voices`) et un
compte rendu ; le choix du slot (I3), le remplacement du pattern, l'Undo
et l'UI vont dans `ui/mw_project.py` (`_import_midi`, à côté de
`_export_midi`).

### Alternatives écartées

- Destination : premier pattern vide, ou dialogue de choix (I2) ;
- slot : slot courant seulement, ou dialogue de choix (I3) ;
- noms SMF ignorés, ou séparation préalable des noms pistes / pads (I5) ;
- notes en temps flottant dès ce chantier (I4) : chantier à part ;
- notes de batterie en ETYPE_KIT : one-shot d'un pas, la durée se
  perdrait ; ou en cases de grille (pads) : il faudrait un kit et une
  table note → pad. PATCH joue juste sur une banque, au canal 10 compris ;
- une piste Groovebox par piste SMF sans découpage par canal :
  incompatible avec O3 (une piste joue sur un canal à la fois).

### Portée explicitement exclue de ce chantier

- **Notes en temps flottant** (grille, piano roll, liste des événements,
  quantisation, presse-papier, enregistrement) : **chantier suivant**,
  demandé par l'utilisateur ;
- import d'un song ou de plusieurs patterns, carte de tempo, signatures
  autres que 4/4 (il faudrait d'abord sauver `_num_beats`) ;
- import sur un slot synthé WAV ou kit, conversion des notes de batterie
  en pads ;
- séparation des noms de pistes et des noms de pads ;
- aftertouch, SysEx, réverbération / chorus de FluidSynth ;
- routage « canal → slot », mode Rack 16 canaux.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **18a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **18b1** | Implémentation — `midi_import.py` : I4, I6 à I10 (lecture, pistes, entêtes, volume / pan, événements, tempo, longueur, compte rendu). | `src/midi/midi_import.py` (nouveau) |
| **18c1** | Tests — fichiers construits avec mido ; aller-retour export → import ; type 0 ; plus de 16 pistes ; arrondi ; entête décalé ; notes non fermées. | `tests/test_midi_import.py` (nouveau), `docs/SPECS.md` (liste des tests) |
| **18d1** | Implémentation — I1 à I3, I5, I11 : Alt+Shift+I (deux fenêtres), dialogue, confirmation, slot Banque, remplacement du pattern, Undo, compte rendu. Essayé à l'écoute sur de vrais `.mid`. | `ui/mw_project.py`, `ui/key_handler_alt.py`, `ui/mew_keymap.py` |
| **18e1** | Tests — commande, slot trouvé / créé / Rack plein, Undo, Non, erreur de lecture. | `tests/test_midi_import_ui.py` (nouveau), fakes au besoin |
| **18f1** | Doc — clôture (avancement, SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 7 étape 18 — Avancement et écarts constatés

- **18b1** — `src/midi/midi_import.py` : `build_pattern_from_midi(mid,
  *, name)` → `(Pattern, ImportReport)`, `import_pattern(path)` ;
  `ImportReport.details()` donne les remarques du compte rendu (I11).
  Conforme à I4, I6 à I10. Essayé sur un aller-retour export → import et
  sur dix vrais `.mid` (types 0 et 1, batterie seule, 3/4, fichier abîmé).
  Précisions trouvées à l'essai :
  - **SMF de type 0** : le nom de son unique piste est le nom du morceau ;
    il devient le nom du **pattern**, et les pistes (une par canal)
    restent sans nom (sinon elles porteraient toutes le même).
  - **Lecture tolérante** (`clip=True`) : un fichier abîmé (octet de
    données hors 0..127) que mido refusait se lit, l'octet ramené à 127.
  - **Noms** sans les espaces de début et de fin (`"Bass  "`).
  - L'export écrit CC91 et CC93 à 0 au tick 0 (12a1 D3) : réimportés, ils
    restent des événements CC (I9), sans effet sur le rendu ; un nouvel
    export les écrit deux fois au tick 0.
  - Le pan revient à ±1 près (`pan_to_cc10`, 127 valeurs pour 201
    positions) ; le volume revient exact.
- **18c1** — `tests/test_midi_import.py` (62 tests), fichiers construits
  avec mido ; `SPECS.md` (arborescence, liste des tests). 2568 verts.
- **18d1** — `_import_midi` et `_import_bank_slot` (`ui/mw_project.py`),
  Alt+Shift+I dans les deux fenêtres (dans l'éditeur MIDI, testé avant
  Shift+I). Conforme à I1-I3, I5, I11.
  - **Écart : le fichier est lu avant toute question.** Une erreur de
    lecture ne pose ni confirmation ni Undo (le plan disait : Undo posé,
    puis retiré). Même résultat, plus simple.
  - Lecture arrêtée avant le remplacement (`stop_all`), comme Ctrl+N.
  - Essayé à l'écoute (utilisateur, 2026-10-29) sur `bach_01.mid` et
    `recado.mid` : toutes les notes et tous les instruments y sont.
    **Problème de pédale trouvé**, qui ne vient pas de l'import mais du
    rejeu du CC64 sur une banque (chantier 17) : voir l'avenant 18d2.
  - Undo d'un import qui avait créé le slot Banque : FluidSynth écrit
    « No preset found » pour les 16 canaux dans le terminal
    (`fluid_synth_sfunload` avec remise des presets, dernière soundfont
    déchargée). Sans effet sur le son ; vrai de tout Undo qui retire la
    dernière banque.

## Phase 7 étape 18d2 — Avenant : pédale, Pitch Bend et modulation des banques, à l'arrêt et à la poursuite

### Origine

Essai à l'écoute de 18d1 (utilisateur, 2026-10-29) :
- `bach_01.mid` (une piste de piano, CC64 enfoncé puis relâché à chaque
  mesure) « saute » ou démarre mal sur la première mesure ;
- `recado.mid`, importé ensuite **sans relancer l'appli**, est joué
  avec un « gros problème de pédale sustain », alors qu'il n'enfonce
  jamais la pédale (trois CC64 à 0, à la toute fin).

L'utilisateur et Claude concluent au même diagnostic : une pédale de Bach
restée enfoncée, qui brouille le début de Bach à la relance et tout
Recado. Ce n'est pas l'import : c'est le rejeu du CC64 sur une banque
(chantier 17), que les vrais `.mid` révèlent.

### État des lieux constaté en code (après 18d1, 2568 tests verts)

- **CC64 rejoué = pédale globale.** `TrackRouter.on_cc_tape` traite le
  CC64 avant tout autre test (`track_router.py:853`) par
  `set_sustain(value >= 64)` (`:715`), qui l'envoie aux **16 canaux** de
  FluidSynth et à tous les synthés WAV. La pédale du piano tient aussi
  les autres instruments : contraire au modèle « orchestre » (17e3 O1),
  où chaque canal est un instrument.
- **Rien ne relâche la pédale à l'arrêt.** `stop_pattern`,
  `pause_pattern` et `stop_all` (`player/dp_transport.py`) n'appellent pas
  le routeur ; il n'existe pas de rappel « fin de lecture ». Les notes
  d'une banque s'arrêtent d'elles-mêmes (durée), et la pédale reste
  enfoncée dans FluidSynth.
- **La poursuite ignore la pédale.** `TrackRouter.chase`
  (`track_router.py:505`) rejoue PGM, CC0 et CC32 jusqu'à la position,
  rien d'autre. Une pédale enfoncée le reste d'une lecture à l'autre, et
  d'un pattern à l'autre.
- Pitch Bend et modulation d'une banque vont déjà au canal courant de la
  piste (`on_bend_tape`, `on_mod_tape`, `:800`, `:819`), mais ne sont, eux
  non plus, ni remis à zéro à l'arrêt ni poursuivis.
- Jeu en direct : `midi_handler_window.py:235` appelle aussi
  `set_sustain` (pédale du contrôleur sur tous les canaux).

### Comportement de Sonar (vérifié le 2026-10-29)

Vérifié sur les forums de Cakewalk (discuss.cakewalk.com : fils 38483,
38778, 90109, 44964, 9246) ; aucune page officielle à jour trouvée :
- **Zero Controllers When Play Stops** (Préférences > Projet > MIDI) : à
  l'arrêt, pitch wheel, pédale sustain et molette de modulation à zéro
  sur les 16 canaux. Sans cette option, arrêter avant le retour du CC64 à
  0 laisse des notes tenues (fil 38778) : notre cas.
- **MIDI Event Chase on Play** (même page ; « Patch/Controller
  Searchback » jusqu'à Sonar 4) : au démarrage, renvoie par canal les
  derniers programme, pitch wheel, pédale et contrôleurs avant la
  position.

### Décisions validées (utilisateur, 2026-10-29)

**P1 — Le CC64 d'une piste Banque va au canal courant de la piste
seulement**, comme les autres CC. Il est envoyé même si la piste est
muette ou hors solo, pour qu'un relâchement ne se perde jamais (comme
aujourd'hui, où le CC64 passe avant le test de mute). Les pistes sur
synthé WAV gardent la pédale globale (`set_sustain`).

**P2 — Arrêt = Zero Controllers.** À l'arrêt et à la pause de la
lecture (Espace, Pause, `stop_pattern`, `pause_pattern`, `stop_all`), le
routeur met à zéro, sur les 16 canaux du moteur de banque : pédale
(CC64 = 0), Pitch Bend (centre) et modulation (CC1 = 0). Le player
reçoit pour cela un rappel `_on_play_stop_cb`, symétrique de
`_on_play_start_cb` (17f1), appelé seulement si une lecture tournait.

**P3 — Poursuite étendue (Event Chase).** `chase(tape, pos)` reprend
aussi, pour chaque canal, la **dernière pédale (CC64), le dernier Pitch
Bend et la dernière modulation (CC1)** des pistes Banque avant la
position, sinon zéro. Le canal d'un tel événement est le canal courant
de sa piste à son instant (celui de son dernier Program Change, O3),
calculé dans la même passe. Comme la poursuite a lieu au démarrage, à
chaque saut, au changement de pattern, à l'avance du song et après
Undo, une pédale restée enfoncée ne survit plus à une relance.

### Portée exclue

- Pédale du **contrôleur en direct** (`midi_handler_window.py:235`) :
  reste globale ; à revoir avec le routage par canal du jeu en direct.
- Poursuite des autres contrôleurs (CC7 / CC10 sont déjà le mixage de la
  piste ; CC91, CC93 et autres) et des notes (« Include Note Events »).
- Synthés WAV : ni remise à zéro à l'arrêt ni poursuite nouvelles.

### Découpage en commits révisé

| Étape | Contenu | Fichiers |
|---|---|---|
| **18d2** | Doc — cet avenant. | `docs/DESIGN.md` |
| **18d3** | Implémentation — P1 à P3. Essayé à l'écoute : Bach arrêté pédale enfoncée, puis Recado, sans relancer l'appli. | `track_router.py`, `player/dp_transport.py`, `player/drum_player.py`, `ui/main_window.py` |
| **18e1** | Tests — interface de l'import (18d1) et P1 à P3. | `tests/test_midi_import_ui.py` (nouveau), `tests/test_bank_slot.py`, fakes au besoin |
| **18f1** | Doc — clôture. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 7 étape 18 — Avancement après l'avenant (18d3)

- **18d3** — P1 à P3 conformes à 18d2 : CC64 d'une piste Banque au canal
  courant de la piste (`on_cc_tape`) ; `TrackRouter.on_play_stop`, appelé
  par le nouveau rappel `_on_play_stop_cb` du player à l'arrêt, à la
  pause, et quand la lecture s'arrête d'elle-même (fin d'un pattern sans
  boucle, du song, des répétitions) ; `chase` étendu à la pédale, au Pitch
  Bend et à la modulation. Essayé à l'écoute (utilisateur, 2026-10-29) :
  Recado n'est plus noyé dans la pédale. Trois corrections de plus,
  trouvées à l'essai :
  - **Ordre des événements simultanés** (`dp_playback.py`, défaut du
    rejeu depuis le chantier 4) : `events.sort()` triait aussi sur les
    données, donc les CC d'un même instant par numéro. À 1.1.1 de
    `bach_01.mid`, les deux CC121 (Reset All Controllers) passaient après
    le CC64 = 127 et relâchaient la pédale : première mesure piquée, notes
    coupées. Tri stable sur (temps, marqueur) : l'ordre de `_tape` est
    gardé.
  - **Saut de lecture avec Haut / Bas sur la liste des pistes** :
    `Pattern.grid_row` cherchait chaque case en parcourant toute la piste
    (16 × 128 cases × 2715 notes sur la guitare de `survive1.mid`) :
    321 ms de thread UI par changement de piste, callback audio en retard,
    9 sous-alimentations en 3 s. Un seul passage par ligne : 2,8 ms,
    aucune sous-alimentation.
  - **Dossier de l'import retenu** pour la session (`_import_dir`), sinon
    EXPORTS ; pas d'une session à l'autre, `config.json` étant en lecture
    seule.

### Phase 7 étape 18d4 — Avenant : gain de FluidSynth, mesure vide initiale

Essai de `survive1.mid` (dix pistes, karaoké ; utilisateur, 2026-10-29) :

- **Saturation.** L'appli joue nettement plus fort que TiMidity et
  sature par moments. Rendu hors appli de deux minutes du morceau, avec
  les CC7 du fichier : au gain 1.0 (défaut de 17b1, validé sur quatre
  pistes à côté des pads WAV), crête 2,95 et 43,5 % des blocs écrêtés ;
  à 0.5, crête 1,47 (0,8 %) ; à 0.4, crête 1,18 (0,1 %). Le pilote
  écrête net (`np.clip`, `sound_device_driver.py:212`).
  **Décision (utilisateur) : défaut de `fluidsynth_gain` à 0.4** « pour
  l'instant ». Alternative écartée pour ce chantier : un limiteur doux
  sur la sortie générale (plus de code dans le pilote, à refaire dans le
  moteur natif) ; à reprendre s'il manque de niveau.
- **Mesure vide au début.** TiMidity commence tout de suite ; l'appli
  joue d'abord une mesure vide. Elle est dans le fichier (première note
  à la mesure 2, un seul tempo) ; TiMidity supprime le silence initial
  par défaut (son aide : « Default: drop initial silence »,
  `--preserve-silence`). **L'import reste fidèle**, comme Sonar, qui
  ouvre le fichier tel quel ; Ctrl+G permet de partir de la mesure 2.
- **Ralenti final de `bach_01.mid`** (60 changements de tempo) : carte de
  tempo, hors périmètre (18a1), chantier futur.
- **18d4** (`02ee85d`) — gain de FluidSynth par défaut à 0.4 ; `pytest`
  rouge : 6 tests de l'ancien défaut.
- **18e1** — `tests/test_midi_import_ui.py` (25 tests : slot Banque,
  dialogue et dossier retenu, annulation, erreur de lecture, Rack plein,
  confirmation, remplacement, noms, Undo, compte rendu, Alt+Shift+I dans
  les deux fenêtres) ; P1 à P3 et rappel de fin de lecture dans
  `tests/test_bank_slot.py` (17 tests) ; ordre de `_tape` à temps égal et
  rappel aux arrêts automatiques dans `tests/test_playback_loop.py` ;
  `grid_row` dans `tests/test_pattern_grid_api.py` ; 6 tests du gain
  adaptés. Chaque correction de 18d3 défaite à l'essai fait échouer au
  moins un test. 2620 verts.
- **18d5** — Ajout demandé avant la clôture (utilisateur, 2026-10-29) :
  **l'import place le lecteur au début** (`goto_start` après l'arrêt,
  avant le chargement du pattern, donc poursuite depuis 1.1.1). Arrêté,
  le player garde sa position (`_resume_offset`) : `bach_01.mid` importé
  après `survive1.mid` reprenait au milieu, à la position où ce dernier
  avait été arrêté.
- **18e2** — 2 tests de 18d5 dans `tests/test_midi_import_ui.py` (lecteur
  remis au début et poursuite depuis 1.1.1 ; position gardée si Non). 2622
  verts.

### Clôture (18f1)

**18a1-18e2 FAITS** (commits `f78408f` à `c8fbe05`, et ce commit de
clôture, 2622 tests verts) : **chantier Phase 7 étape 18 complet**. Un
fichier `.mid` s'ouvre dans le pattern courant et se joue par FluidSynth,
avec ses instruments, sa pédale et ses noms de pistes.

**Ce que le chantier a livré** :
- **`src/midi/midi_import.py`**, sans wx ni player, inverse de l'export :
  pistes par (piste SMF, canal), fusion au-delà de 16, entête à 1.1.1,
  volume et pan de piste, notes PATCH arrondies au pas, CC / Pitch Bend /
  Program Change en temps flottant, tempo, longueur, compte rendu ;
  lecture tolérante d'un fichier abîmé.
- **Alt+Shift+I** (fenêtre principale et éditeur MIDI) : dialogue
  (dernier dossier retenu), confirmation, slot Banque trouvé ou créé,
  pattern courant remplacé, noms de pistes, lecteur à 1.1.1, Undo,
  compte rendu au statut.
- **Rejeu des banques, comme Sonar** (avenant 18d2) : pédale au canal de
  la piste, Zero Controllers à l'arrêt, poursuite de la pédale, du Pitch
  Bend et de la modulation.
- **Trois défauts plus anciens, révélés par les vrais fichiers** :
  événements simultanés rejoués dans le désordre (chantier 4), grille
  recalculée case par case qui faisait sauter la lecture, gain de
  FluidSynth qui écrêtait un orchestre (1.0 → 0.4).

**Écarts au plan** : fichier lu avant toute question (18d1) ; nom d'un
SMF de type 0 donné au pattern, lecture tolérante, noms nettoyés (18b1) ;
l'avenant 18d2 et les corrections 18d3, le gain (18d4), le lecteur remis
au début (18d5) ; voir plus haut.

**Règle de travail confirmée** : pour reproduire Sonar, dire d'où vient
l'information (de mémoire ou vérifiée) et la vérifier avant d'en faire
une décision (§ 18d2, « Comportement de Sonar »).

**`docs/SPECS.md` mis à jour** : ligne Phase 7, outils, arborescence,
configuration (gain, dossier d'import), section « Banques de sons »
(pédale, arrêt, poursuite, ordre), nouvelle section « Import MIDI
(Alt+Shift+I) », tests ; `docs/shortcuts.md` : Alt+Shift+I dans les deux
fenêtres.

**Laissé hors périmètre, pour la suite** :
- **notes en temps flottant** (demandé par l'utilisateur, puis **reporté,
  non urgent** : l'import au pas marche bien ; corrigé en 19a1) : l'arrondi
  au pas déplace des milliers de notes jouées à la main ;
- **carte de tempo** : changements de tempo (ralenti final de
  `bach_01.mid`), signatures autres que 4/4 (`_num_beats` à sauver
  d'abord) ;
- limiteur doux sur la sortie générale, si le gain 0.4 manque de niveau ;
- dossier d'import gardé d'une session à l'autre (avec le dialogue de
  configuration, `config.json` étant en lecture seule) ;
- pédale du contrôleur en direct, qui reste globale ;
- réverbération et chorus de FluidSynth (CC91 / CC93 des fichiers) ;
- aftertouch, SysEx ; import d'un song ou de plusieurs patterns ;
  séparation des noms de pistes et des noms de pads ;
- message « No preset found » de FluidSynth quand un Undo retire la
  dernière banque (sans effet sur le son).

## Phase 7 étape 19a1 — Carte de tempo : plusieurs tempos par pattern

### Numérotation des commits de ce chantier

`19a1` = ce plan (doc seule). Le code commence à `19b1`. Une paire impl →
tests par sous-chantier ; `19a2`, `19b2`… pour un commit imprévu.

### Origine du besoin

- Essai de l'Import MIDI (Phase 7 étape 18) : TiMidity joue le ralenti
  final de `bach_01.mid` (60 changements de tempo, de 92 à 94 BPM puis
  plus lent), que l'appli ignore : un seul BPM par pattern, le premier.
- L'utilisateur demande la carte de tempo comme chantier suivant
  (2026-10-29) ; les notes en temps flottant sont reportées.

### Comportement de Sonar (vérifié le 2026-10-29)

Forums de Cakewalk (discuss.cakewalk.com, fils 19746, 38042, 89704,
29073, 2341) ; aucune page officielle à jour trouvée :
- **Insert Tempo** (menu Project) : un dialogue propose soit de
  **modifier le tempo en vigueur** à la position, soit d'**insérer un
  nouveau tempo** ; la position est celle du curseur, modifiable.
- Un changement de tempo en cours de morceau **décale toutes les barres de
  mesure qui suivent** (dans le temps réel).
- Un tempo égal au précédent est supprimé (redondant).
- Sonar connaît les **rampes** (le tempo glisse jusqu'au suivant).
- **Non trouvé** : ce que fait le champ de tempo de la barre de transport
  quand une carte existe ; aucune décision ne s'appuie dessus.

### État des lieux constaté en code (2026-10-29, 2622 tests verts)

- **Temps linéaire partout.** `DrumPlayer.step_duration = 60 ·
  _num_beats / (bpm · _num_steps)` (`player/drum_player.py:163`) ; toute
  conversion pas ↔ secondes est `pas × step_duration` ou `secondes /
  step_duration`, une soixantaine d'endroits :
  - lecture : `_run_thread`, `_build_measure_events` (`t_sec`), durée de
    la boucle, Note Repeat, décompte (`player/dp_playback.py`) ;
  - position : `_current_offset`, `position_str`, `navigate_bar`, saut en
    secondes (`player/dp_position.py`) ; pause (`dp_transport.py:93`) ;
  - enregistrement (`dp_recording.py:86`, `:111`), effacement
    (`dp_erase.py`) ;
  - métronome (`metronome.py:42`, reçoit `step_duration`) ;
  - dialogues : Aller à, sélection de boucle et de pistes, en secondes
    (`ui/dialogs_temporal.py`, `mw_patterns.py:231`, `song_window.py:252`,
    `mew_quantize.py:79`) ;
  - millisecondes par pas : quantisation des durées
    (`quantize_manager.py:138`), insertion au pavé numérique
    (`ui/mew_numpad.py:22`), dialogue d'insertion (`midi_editor_dialogs.py:131`).
- **Le BPM** : `Pattern._bpm` (entier), `DrumPlayer.bpm`, `set_bpm`
  (`dp_transport.py:144`, réveille le thread) ; champ BPM (SpinCtrl
  1..600, `main_window.py:234`, sans Undo), Tap Tempo (avec Undo) et ±5
  (`key_handler_chars.py:191`, `:351`) ; en mode song, le BPM du pattern
  suivant est repris à l'avance (`dp_playback.py:268`, `:282`).
- **Positions** : `TapeEvent.time` en pas cumulés ; toutes les mesures ont
  le même nombre de pas, la mesure fait 4 noires (`_num_beats` n'est ni
  sauvé ni modifiable).
- **Durées des notes en millisecondes** (PATCH, cases de grille sans durée
  propre : durée du pad) : indépendantes du tempo au rejeu.
- **Opérations qui déplacent le temps du pattern** : `resize` (change de
  `_num_steps`), `double_bars`, `halve_bars`, `copy_from` (ne copie pas
  le BPM : le player le reçoit à part), `to_dict` / `from_dict`.
- **Export** : un seul `set_tempo` au tick 0 ; durées ms → ticks au BPM
  unique (`ms_ticks`, `midi_export.py:138`).
- **Import** : premier tempo seul, changements suivants comptés et
  ignorés ; durées ticks → ms au BPM unique (`midi_import.py`).
- **Liste des événements** (Ctrl+2, `MidiEditor.get_all_events`,
  `midi/midi_editor.py:163`) : lignes (dictionnaires) tirées de `_tape`
  des pistes sélectionnées ; rien hors des pistes.
- **Alt+Shift+T** est libre dans la fenêtre principale et dans l'éditeur
  MIDI (Ctrl+Shift+T = propriétés de piste, Ctrl+T = assigner le slot).

### Décisions validées (utilisateur, 2026-10-29)

**T1 — Périmètre : le tempo seulement** (choix a). La mesure reste de 4
noires ; une signature par pattern, puis ses changements, feront un
autre chantier (ils touchent au codage des positions).

**T2 — Carte de tempo par pattern.** `Pattern._bpm` reste le **tempo de
départ** ; `Pattern._tempo_changes` = liste triée de `(position en pas,
BPM)`, position > 0, flottante (exacte depuis un import, comme un CC).
BPM **entier** 1..600, comme le champ BPM. Un changement égal au tempo
qui le précède est retiré (Sonar). Sauvé dans le `.gvp` (clé
`"tempo_changes"`, absente = aucun changement) et donc dans l'Undo ;
copié par `copy_from`, recalé par `resize`, `double_bars` et
`halve_bars`, comme les événements.

**T3 — Changements instantanés.** Comme dans un fichier MIDI ; un ralenti
est une suite de changements. Les rampes de Sonar sont exclues.

**T4 — `TempoMap`** (`src/tempo_map.py`, sans wx ni player, portable
C/C++) : construite depuis le tempo de départ, les changements et le
nombre de pas par noire ; `secs(pas)` (secondes depuis 0, linéaire par
morceaux), `steps(secs)` (inverse), `bpm_at(pas)`. Le player garde la
carte du pattern joué et l'utilise à la place de `step_duration` partout
(durée de la boucle = `secs(fin) − secs(début)`). **À tempo unique, mêmes
résultats qu'aujourd'hui** : les 2622 tests restent verts sans
adaptation de fond.

**T5 — Durées des notes : toujours en millisecondes.** L'import les
calcule au tempo en vigueur au début de chaque note, l'export les
reconvertit de même ; les millisecondes par pas (quantisation, pavé
numérique, dialogue d'insertion) prennent le tempo de la position.

**T6 — Import et export.** L'import garde tous les changements de tempo
(ils ne sont plus « ignorés » au compte rendu, qui dit combien il en a
lus) ; l'export écrit chaque changement dans la piste conductor. Un
aller-retour rend la même carte.

**T7 — Champ BPM, Tap Tempo, ±5 : le tempo en vigueur à la position
courante** (choix a ; le « modifier le tempo en vigueur » de Sonar).
Arrêté à 1.1.1, c'est le tempo de départ. Après un déplacement de la
position à l'arrêt (Aller à, mesure suivante ou précédente, début, fin),
le champ affiche le tempo de la position ; **pas pendant la lecture**
(pas de bavardage du lecteur d'écran). Tap Tempo garde son Undo ; le
champ et ±5 restent sans Undo, comme aujourd'hui.

**T8 — Dialogue « Tempo » (Alt+Shift+T, deux fenêtres)** (choix c, avec
T9). Liste des tempos du pattern : « 1.1.1 — 92 BPM » (départ), puis un
élément par changement, position en mesure.temps.pas. Boutons : **Insérer**
(à la position courante, position et BPM modifiables avant validation),
**Modifier** (BPM et position de l'élément ; le départ : BPM seul),
**Supprimer** (pas le départ), **Fermer**. Clavier : Entrée = Modifier,
Suppr = Supprimer, Échap = Fermer. Un Undo par changement (« Tempo :
insérer 80 BPM à 33.1.1 »). En lecture, un changement est entendu aussitôt
(réveil du thread, position gardée).

**T9 — Liste des événements (Ctrl+2).** Les tempos y apparaissent en tête
de chaque position, comme une piste « Tempo » (conductor), quelles que
soient les pistes sélectionnées : « Tempo 80 BPM ». Entrée les modifie (BPM,
position), Suppr les supprime (pas le départ), avec Undo ; le filtre
d'événements (Ctrl+Shift+F) gagne le type « Tempo ». Pas de copie /
duplication / insertion de tempo depuis la liste : le dialogue s'en charge.

**T10 — Mode song.** Chaque pattern joue avec sa propre carte ; à
l'avance du song, la carte du pattern suivant remplace la courante.

### Portée explicitement exclue de ce chantier

- **Signatures** (une par pattern, puis leurs changements) : chantier à
  part (T1) ;
- **rampes** de tempo (T3) ; BPM décimaux ;
- tempo dans le piano roll (Ctrl+1) ;
- Undo du champ BPM et de ±5 (inchangés) ;
- notes en temps flottant (reportées, non urgentes).

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **19a1** | Doc — ce plan ; correction de la clôture 18f1 (notes en temps flottant reportées). | `docs/DESIGN.md` |
| **19b1** | Implémentation — T2, T4, T6 : `TempoMap`, `_tempo_changes` (`.gvp`, `copy_from`, `resize`, doubler / diviser), import et export avec la carte, durées au tempo local (T5). | `src/tempo_map.py` (nouveau), `pattern.py`, `midi/midi_import.py`, `midi/midi_export.py` |
| **19c1** | Tests — 19b1 ; aller-retour export → import de la carte. | `tests/test_tempo_map.py` (nouveau), `tests/test_midi_import.py`, `tests/test_midi_export.py`, `docs/SPECS.md` |
| **19d1** | Implémentation — T4 dans le player (lecture, boucle, position, pause, enregistrement, effacement, métronome, décompte, Note Repeat), T5 (ms par pas), T7, T10, dialogues en secondes. Essayé à l'écoute (ralenti de Bach). | `player/*.py`, `metronome.py`, `quantize_manager.py`, `ui/main_window.py`, `ui/key_handler_chars.py`, `ui/dialogs_temporal.py`, `ui/mew_numpad.py`, `ui/midi_editor_dialogs.py`, `ui/mw_patterns.py`, `ui/mw_songs.py` |
| **19e1** | Tests — 19d1 (à tempo unique, rien ne change ; avec changements, positions, boucle, enregistrement, song). | `tests/test_tempo_playback.py` (nouveau), tests existants au besoin |
| **19f1** | Implémentation — T8, T9 : dialogue Tempo (Alt+Shift+T, deux fenêtres), tempos dans la liste des événements (affichage, Entrée, Suppr, filtre), Undo. Essayé au lecteur d'écran. | `ui/dialogs_tempo.py` (nouveau), `ui/key_handler_alt.py`, `ui/mew_keymap.py`, `midi/midi_editor.py`, `ui/mew_*.py`, `ui/midi_editor_dialogs.py` |
| **19g1** | Tests — 19f1. | `tests/test_tempo_dialog.py` (nouveau), `tests/test_midi_editor*.py` |
| **19h1** | Doc — clôture (avancement, SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 7 étape 19 — Avancement et écarts constatés

- **19b1** — `src/tempo_map.py` (`TempoMap`, `normalize_changes`,
  `clamp_bpm`) ; `Pattern._tempo_changes` (`.gvp` : `"tempo_changes"`),
  `tempo_map()`, `set_tempo_changes()`, `steps_per_beat()` ; recalés par
  `copy_from`, `resize`, `double_bars` (la seconde moitié repart du tempo
  de départ), `halve_bars` ; vidés par `new_pattern` (Nouveau pattern),
  **gardés par `reset_pattern`** (Shift+Suppr n'efface que les notes).
  Import : tempo de départ = dernier tempo au tick 0, sinon 120 jusqu'au
  premier ; chaque tempo suivant devient un changement ; durées au tempo
  local ; le compte rendu dit « N changements de tempo » (plus
  « ignorés »). Export : un `set_tempo` par changement dans la piste
  conductor, fin de note au tempo local (`end_tick`). À tempo unique,
  tous les tests de l'export passent sans changement.
  - Essai sur `bach_01.mid` : 60 changements, de 92 à 40 BPM ; durée
    jusqu'au dernier événement 98,30 s, comme mido ; notes identiques
    après export puis import.
  - **Limite de résolution** : un changement placé à une position que PPQ
    480 ne représente pas (fichier à PPQ 256, un tick avant la mesure)
    revient décalé de 1/600 de pas après export puis import, comme un CC.
  - `pytest` rouge : 2 tests de l'import attendaient « changements de
    tempo ignorés ».
- **19c1** — `tests/test_tempo_map.py` (42 tests : `clamp_bpm`,
  `normalize_changes`, `TempoMap` — à tempo unique, l'ancien calcul
  linéaire —, changements du pattern, import, export, aller-retour exact
  d'une carte faite dans l'appli) ; 2 tests de l'import adaptés (« N
  changements de tempo » ; un tempo pile à la fin du pattern est écarté).
  Quatre défauts de 19b1 réintroduits à l'essai : chacun fait échouer au
  moins un test. 2664 verts.
- **19d1** — le player suit la carte (T4) : `DrumPlayer.tempo_map()` (en
  cache), `_position_at` (position dans la fenêtre en cours, utilisée par
  la position, la pause, l'enregistrement et l'effacement),
  `_t_to_offset`, `_measure_clock` (durée de la fenêtre et minutage des
  événements, du métronome et du Note Repeat ; pendant le décompte, tempo
  de la position de reprise) ; dialogue Aller à en secondes par la carte ;
  ms par pas au tempo de la position (quantisation des durées, grille de
  l'éditeur MIDI, dialogue d'édition de note) ; mode song (carte du pattern
  suivant). T7 tel que planifié : champ BPM, Tap Tempo et ±5 modifient le
  tempo en vigueur (`set_tempo_at`), affiché après un déplacement à
  l'arrêt (`_on_stopped_move_cb`) et à l'arrêt de la lecture.
  - **Ajout : un changement de tempo en lecture garde la position
    musicale** (`_keep_position`, le thread se recale) ; avant, changer le
    BPM en lecture faisait sauter la position.
  - **Défauts plus anciens corrigés au passage** :
    - le pattern du player gardait `_bpm = 100` (jamais mis à jour) : le
      dialogue d'édition de note et la grille de l'éditeur MIDI
      convertissaient les durées à 100 BPM ; `set_bpm` et l'avance du song
      le tiennent maintenant à jour ;
    - avec une boucle qui ne commence pas à 1.1.1, l'enregistrement,
      l'effacement et le Note Repeat calculaient la position comme si la
      boucle commençait au début du pattern (d'après le code) ; ils
      passent par `_position_at` / `_t_to_offset` ;
    - une reprise à l'intérieur d'une telle boucle repartait décalée ;
      elle repart exactement à sa position.
  - Essai sans le son : de la mesure 34 à la fin de `bach_01.mid`, 15,31 s
    joués pour 15,30 s prévus (7,83 s à 92 BPM constant), notes à moins
    d'1 ms. **Essayé à l'écoute (utilisateur, 2026-10-29) : le ralenti de
    Bach s'entend bien.** Mais T7 ne permet pas de ralentir tout le
    morceau pour l'étudier : voir l'avenant 19d2.
  - `pytest` rouge : 1 test (`test_bpm_increase_via_key5`, fausse fenêtre
    sans `tempo_at` / `set_tempo_at`), plus un second qui n'échoue qu'à sa
    suite (application wx laissée ouverte).

## Phase 7 étape 19d2 — Avenant : ralentir tout le morceau, tempos décimaux

### Origine

Essai à l'écoute de 19d1 (utilisateur, 2026-10-29) : le ralenti de
`bach_01.mid` s'entend bien, mais avec T7 (le champ BPM ne change que le
tempo en vigueur à la position), un morceau à plusieurs tempos ne peut pas
être ralenti d'un seul geste. Or **ralentir un morceau pour l'étudier et
en relever les notes est l'intérêt premier de la carte de tempo**.

### Décisions validées (utilisateur, 2026-10-29)

**R1 — Tempos décimaux, à 0,01 près** (choix a). Tempo de départ et
changements gardent deux décimales : une mise à l'échelle est exacte et
un aller-retour (plus lent puis plus vite) revient au même point, sans
dérive d'arrondi. L'import garde les tempos exacts du fichier (93,75 au
lieu de 94), l'export les écrit tels quels. Le champ BPM reste un
SpinCtrl entier (seul widget annoncé en temps réel par le lecteur
d'écran) : il affiche le tempo arrondi à l'unité. Ailleurs (dialogue
Tempo, liste des événements, compte rendu de l'import), un tempo
s'affiche avec ses décimales seulement s'il en a, à la française :
« 46,5 BPM ». Remplace « BPM entier » de T2.

**R2 — Champ BPM, Tap Tempo, ±5 : tous les tempos changent dans la même
proportion** (remplace T7). Le champ **affiche le tempo en vigueur à la
position** (choix b, « pour pouvoir lire le changement de tempo en direct
avec un lecteur d'écran ») ; le modifier, taper un tempo (H) ou faire ±5
applique le rapport *nouveau / tempo affiché exact* au tempo de départ et
à tous les changements. Un tempo qui sortirait de 1..600 est borné.
- Affichage mis à jour après un déplacement à l'arrêt, à l'arrêt de la
  lecture, et **pendant la lecture, à chaque changement de tempo
  franchi** (le player signale le tempo atteint ; le champ suit, pour
  qu'un lecteur d'écran le lise). *Interprétation de « en direct », à
  confirmer à l'essai.*
- Undo inchangés : Tap Tempo en pose un ; le champ et ±5 non.

**R3 — Dialogue Tempo (T8), « Modifier » : deux choix.** « **Changer le
tempo récent** » (seul l'élément sélectionné, ou le tempo en vigueur à la
position, change ; le « modifier le tempo en vigueur » de Sonar) et
« **Tous les tempos** » (même proportion que R2). « Insérer » et
« Supprimer » inchangés.

### Ce qui reste de 19d1

Le player et la carte (T4), la position gardée quand le tempo change en
lecture, les ms par pas au tempo de la position, le mode song. `set_tempo_at`
(changer le tempo en vigueur) reste : il sert au choix « Changer le tempo
récent » du dialogue (19f1).

### Découpage en commits révisé

| Étape | Contenu | Fichiers |
|---|---|---|
| **19d2** | Doc — cet avenant. | `docs/DESIGN.md` |
| **19d3** | Implémentation — R1 (tempos à 0,01, import, export, affichage), R2 (mise à l'échelle de tous les tempos, champ qui suit le tempo en lecture). Essayé à l'écoute et au lecteur d'écran. | `tempo_map.py`, `pattern.py`, `player/*.py`, `midi/midi_import.py`, `ui/main_window.py`, `ui/key_handler_chars.py`, `ui/mw_project.py`, `ui/mw_patterns.py`, `ui/mw_songs.py` |
| **19e1** | Tests — 19d1 et 19d3. | `tests/test_tempo_playback.py` (nouveau), `tests/test_tempo_map.py`, fakes au besoin |
| **19f1** | Implémentation — T8 avec R3, T9. | inchangé |
| **19g1** | Tests — 19f1. | inchangé |
| **19h1** | Doc — clôture. | inchangé |

### Phase 7 étape 19 — Avancement après l'avenant (19d3)

- **19d3** — conforme à 19d2 :
  - R1 : `clamp_bpm` arrondit à 0,01 (entier s'il n'a pas de décimales),
    `format_bpm` (« 46,5 ») ; import exact à 0,01 (constantes `BPM_MIN` /
    `BPM_MAX` de l'import retirées) ; compte rendu de l'import formaté ;
    champ BPM arrondi à l'unité.
  - R2 : `DrumPlayer.scale_tempos(ratio)` et `set_tempo_scaled(bpm)`
    (rapport nouveau / tempo exact à la position, position musicale
    gardée) pour le champ BPM, Tap Tempo et ±5 (±5 depuis le tempo
    affiché, arrondi) ; marqueur `TEMPO_EVENT` dans la mesure (début de la
    fenêtre et chaque changement, seulement s'il y a des changements) →
    `_on_tempo_cb` → champ BPM mis à jour en lecture.
  - Essai sans le son : Bach à 46 → départ 46, fin 20, durée doublée
    (202,6 s) ; 46, +5 ×7, −5 ×7, puis 92 : carte identique ; en lecture
    depuis la mesure 34, tempos signalés 85, 83, 80, 77, 70, 60, 50, 40.
    **Essayé à l'écoute et au lecteur d'écran (utilisateur, 2026-10-29) :
    « ça marche bien »** ; affichage en direct confirmé.
  - `pytest` rouge : 6 tests (4 BPM entiers dans `test_tempo_map.py` et
    `test_midi_import.py`, la fausse fenêtre de `test_key_manager.py` et
    un échec qui n'en est que la suite).
