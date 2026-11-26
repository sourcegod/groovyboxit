=== Aide clavier — GroovyboxIt ===

--- Projet ---
Ctrl+N           Nouveau projet (noname_NNN.gvp, demande si modifié)
Ctrl+O           Ouvrir un projet (.gvp, .json ou tout fichier)
Ctrl+S           Enregistrer le projet
Ctrl+Shift+S     Enregistrer le projet sous... ; case « Créer un nouveau dossier pour
                 ce projet » (cochée par défaut : MonProjet/MonProjet.gvp) ; champ
                 « Chemin des fichiers audios » (défaut : Audios dans le dossier du
                 projet) et « Parcourir… » ; les prises audio y suivent, au nom du projet
Ctrl+Z           Annuler (une prise d'enregistrement s'annule d'un bloc) ; bip s'il
                 n'y a rien à annuler
Shift+Z          Refaire ; bip s'il n'y a rien à refaire
Ctrl+Shift+Z     Afficher l'historique des annulations (bip s'il est vide)
Alt+F4           Quitter (demande d'enregistrer si le projet est modifié) ; dans
                 l'éditeur MIDI et Songs, Alt+F4 ferme cette fenêtre seulement
                 (menu Fichier → Quitter : toute l'appli)
Note: Ctrl+N, Ctrl+O, Ctrl+S, Ctrl+Shift+S et le menu Fichier marchent aussi
      depuis l'éditeur MIDI et Songs ; la fenêtre d'origine reprend le focus
Alt+Shift+P      Préférences (depuis toutes les fenêtres) : onglets Général, Matériel
                 (pilote audio ; entrées et sorties audio et MIDI à cocher, Espace ;
                 sortie principale ; Tester : La 440 Hz / A4 d'une seconde, niveau
                 d'une entrée audio, prochaine note d'une entrée MIDI ; Détecter ;
                 Résultat du test), Audio, Midi, Projet, Raccourcis, Divers ; focus sur l'onglet :
                 Gauche / Droite = onglet voisin ; Ctrl+Tab / Ctrl+Shift+Tab =
                 onglet suivant / précédent depuis n'importe quel champ ; Ok,
                 Annuler, Appliquer (réglages écrits dans
                 ~/.config/groovyboxit/preferences.json)

--- Pattern ---
Ctrl+W           Enregistrer le pattern courant
Ctrl+Shift+W     Dupliquer le pattern courant vers un autre slot
Alt+Shift+E      Exporter en fichier MIDI (.mid), dossier EXPORTS : choix d'abord,
                 « Pattern courant » ou « Song courant » (dernier choix gardé)
Alt+Shift+W      Exporter en audio (.wav) : un dialogue, puis le nom du fichier.
                 Dialogue : Source (Pattern courant, Song courant, Sélection,
                 Presse-papier ; ouvert sur la dernière utilisée) ;
                 « Exporter les pistes sélectionnées » (sinon toutes les pistes ;
                 pistes sélectionnées ou piste courante, appliquées à chaque pattern
                 d'un song ; grisée pour le presse-papier) ; « Tenir compte des
                 Mutes », « Tenir compte des Solos » (cochées : on exporte ce qu'on
                 entend ; décochées : pistes muettes ou hors solo exportées quand
                 même) ; Début et Fin de la sélection (mesure:temps:pas,
                 préremplis par les limiteurs, source Sélection seulement) ; fin
                 (boucle exacte ou + résonance) ; format 16, 24 ou 32 bits
                 flottant ; sortie : mix, pistes séparées ou mix + pistes, les
                 pistes dans un sous-dossier du nom du fichier ; Normaliser :
                 mesure Crête, RMS ou LUFS-I, niveau visé de -24 à 0 dB ; limiteur
                 à -0,3 dBFS toujours actif. Choix gardés pour la session.
                 Presse-papier = celui des pistes (éditeur MIDI : celui des notes)
Alt+Shift+I      Importer un fichier MIDI (.mid) dans le pattern courant (le remplace) ;
                 après le fichier, choix « Banque GM » ou « Rack 16 canaux » (dernier
                 choix gardé)
Alt+Shift+T      Tempos du pattern : insérer, modifier, supprimer, Tap Tempo, Click
                 (dialogue Tempo ; Entrée ou Espace sur « Tap Tempo » = une frappe)
< / >            Pattern précédent / suivant, quel que soit le focus (> = Shift+<) ;
                 bip si l'on est déjà au premier / au dernier
Ctrl+< / Ctrl+>  Premier pattern / dernier pattern utilisé (non vide) ; bip si l'on
                 y est déjà (aussi Pattern > Changer de pattern)
Ctrl+F           Doubler le pattern (duplique les mesures existantes)
Shift+F          Diviser le pattern par deux (garde la première moitié)

--- Quantisation ---
Ctrl+E           Appliquer la quant à la ligne courante
Ctrl+Shift+E     Choisir la ligne + quant et générer le motif
Shift+E          Décocher toute la ligne courante
Ctrl+Q           Quantiser le pattern depuis la grille courante (résolution déduite de la grille)
Shift+Q          Quantiser le pattern avec les derniers paramètres mémorisés (sans dialog)
Ctrl+Shift+Q     Choisir la quant et appliquer au pattern
                 Toutes les notes (grille, kit, synthé) sont quantisées de la même
                 façon, avec leur vélocité. « Enlever les doublons » (cochée par
                 défaut) : parmi les notes de même hauteur au même temps, la dernière
                 jouée reste. « Quantiser la vélocité » : toutes les notes prennent la
                 vélocité choisie dans la liste (100 par défaut)
Alt+Shift+Q      Quantisation à l'enregistrement (fenêtre principale, éditeur MIDI) :
                 case « Quantiser à l'enregistrement » (cochée par défaut), résolution
                 (Quant courante, Grille courante ou une valeur), force, swing,
                 fenêtre, direction, « Enlever les doublons » (cochée par défaut : la
                 nouvelle frappe remplace la note de même hauteur au même temps),
                 « Quantiser la vélocité » ; Ok mémorise, sans toucher aux notes
Overdub (R)      Sans « Enlever les doublons » à l'enregistrement (Alt+Shift+Q),
                 toutes les frappes sont gardées, même au même temps ; la
                 quantisation (Ctrl+Shift+Q) les enlève ensuite

--- Lecture ---
Espace / P       Play / Pause pattern (reprend depuis la position pausée)
Ctrl+Space       Aller au début et lancer la lecture immédiatement (Goto Start + Play)
                 Fonctionne aussi depuis l'éditeur MIDI et la fenêtre Songs
V                Stop All (sons + pattern + Rec + Erase + réinitialise la position)
C                Toggle métronome (click) ; voir aussi les clics des Options de
                 l'enregistrement (Ctrl+Shift+R)
Q                Activer / désactiver le mode Note Repeat
g                Transport : Aller au début du pattern (Goto Start)
Shift+G          Transport : Aller à la fin du pattern (Goto End)
l                Boucle On / Off (le pattern redémarre ou s'arrête en fin de cycle)
Ctrl+L           Poser le point de début de boucle à la position courante du playhead
Shift+L          Poser le point de fin de boucle à la position courante du playhead ;
                 la fin est EXCLUE, comme dans Sonar : quatre mesures vont de 1:1:1
                 à 5:1:1 (refusée au début de boucle ou avant)
Ctrl+Shift+L     Ouvrir le dialog de points de boucle (début, fin exclue — « Fin du
                 pattern » = la mesure suivante —, répétitions)
Alt+L            Réinitialiser les points de boucle (début et fin) à la longueur du pattern
Ctrl+Shift+F     Ouvrir l'éditeur MIDI (si besoin) puis le dialog de filtre d'événements
PageDown         Transport : +1 mesure
PageUp           Transport : −1 mesure
Ctrl+PageDown    Transport : +1 battement
Ctrl+PageUp      Transport : −1 battement
Shift+PageDown   Transport : +1 tick (pas)
Shift+PageUp     Transport : −1 tick (pas)
w                Transport : +1 seconde
b                Transport : −1 seconde
U                Afficher l'état du player et la position (Lecture|Pause|Arrêt, Pos: bar:beat:tick / total)
Ctrl+G           Aller à une position (boîte de dialogue Unité + Valeur + bar:beat:tick)
Ctrl+Shift+G     Ouvrir la boîte de grille (résolution de navigation et quantisation)
Ctrl+F12         Panic : arrêt immédiat de tous les sons + Reset All Controllers
                 (Shift+F12, Ctrl+Shift+F12 : périphériques MIDI, voir --- MIDI ---)
                 (rarement utile : les Mute / Solo et les changements de son
                 coupent déjà les notes, et une note tenue au contrôleur
                 s'arrête toujours au relâchement)

--- Mute / Solo (Pads — focus grille) ---
X                Bascule le Mute du Pad courant
Shift+X          Démuter tous les Pads
S                Bascule le Solo du Pad courant
Shift+S          Désolo tous les Pads

--- Mute / Solo (Pistes — focus liste des pistes) ---
X                Bascule le Mute de la Piste sélectionnée
Shift+X          Démuter toutes les Pistes
S                Bascule le Solo de la Piste sélectionnée
Shift+S          Désolo toutes les Pistes
                 (menu Piste : les mêmes, sur la piste courante, quel que soit le focus)
F3               Mute exclusif On / Off (fenêtre principale, quel que soit le focus)
F4               Solo exclusif On / Off (fenêtre principale, quel que soit le focus)
F5               Réinitialiser tous les Mute et Solo de piste
F8               Monitoring de l'entrée audio On / Off (voir « Enregistrement »)
                 Chaque Mute / Solo de piste coupe d'abord toutes les notes en cours
                 (pédale relâchée ; Pitch Bend et modulation gardés) ; détails des
                 modes exclusifs dans « Pistes »

--- Volume / Pan par Pad ---
Alt+↑            Volume du Pad courant +5
Alt+↓            Volume du Pad courant -5
Alt+←            Pan du Pad courant -10 (vers la gauche)
Alt+→            Pan du Pad courant +10 (vers la droite)
Shift+Retour arrière  Volume du Pad courant à 100 et Pan à 0 (hors de la liste
                      des pistes)

--- Enregistrement (mode R) ---
Ctrl+Shift+R     Options de l'enregistrement (aussi depuis l'éditeur MIDI et la
                 fenêtre Songs) : Mode (Overdub, Remplacer, Remplacer puis Overdub
                 (MPC)), Clic pendant la lecture, Décompte pendant la lecture
                 (Espace, Ctrl+Espace), Clic pendant l'enregistrement, Décompte
                 pendant l'enregistrement (Ctrl+R) ; décomptes : aucun, 1, 2, 4
                 ou 8 mesures ; Monitoring de l'entrée (F8). Gardées dans le
                 projet ; Ctrl+Z annule un changement. Espace pendant un
                 décompte l'annule.
F8               Monitoring de l'entrée audio On / Off (fenêtre principale) :
                 l'entrée de la piste audio courante s'entend à l'arrêt, en
                 lecture et pendant une prise, au volume et au pan de la piste ;
                 avec un micro et des haut-parleurs, attention au Larsen : F8
                 le coupe tout de suite
                 Mode MPC « Remplacer puis Overdub » : en boucle, le premier
                 passage remplace (la piste se tait), les suivants s'ajoutent
                 (annoncé « Rec (MPC) : Overdub ») ; MIDI et audio ; sans
                 boucle, comme Remplacer
R                Démarrer l'enregistrement dans le mode des Options (Overdub par
                 défaut ; démarre aussi la lecture)
R (2e appui)     Arrêter l'enregistrement (lecture continue)
Shift+R          Enregistrement en Remplacement : les notes existantes de la piste
                 sont effacées au fil du playback, sans être jouées (la piste se
                 tait), remplacées par les nouvelles frappes
Shift+R (2e)     Arrêter le mode Remplacement
Ctrl+R           Count-In : le décompte des Options (1 mesure par défaut), puis
                 Rec+Play démarre dans le mode des Options
NumPad 1-8       Jouer + enregistrer le pad dans le pattern
NumPad 9         Rejouer + enregistrer le dernier pad
Note: en mode Note Repeat actif, les répétitions sont aussi enregistrées
Note: R, Shift+R, Ctrl+R et E ouvrent une prise : Ctrl+Z l'annule d'un bloc ;
      une prise où rien n'a changé ne laisse pas d'annulation. Effacer sans
      rien jouer (Remplacement, Erase) compte comme une modification.
Note: sur une piste audio (Type de piste « Audio »), R, Shift+R et Ctrl+R
      enregistrent une prise audio sur l'entrée de la piste (vide : première
      entrée cochée dans l'onglet Matériel des Préférences, sinon l'entrée par
      défaut). Projet encore sans nom : son nom est demandé d'abord. La prise
      est un fichier WAV 24 bits dans le dossier des prises, posée à la
      position entendue (latence de sortie + « Compensation de latence en ms »
      de l'onglet Audio). Sans boucle, le pattern gagne une mesure à chaque fin
      atteinte. Ctrl+Z retire la prise (le fichier reste sur le disque).
      En boucle : R (Overdub) pose chaque passage comme un clip, joué dès le
      passage suivant et superposé aux précédents ; Shift+R (Remplacer) fait
      taire la piste dans la plage enregistrée et ne garde que le dernier
      passage (au Stop, la fin non enregistrée revient).
Note: une prise qui n'enregistre que du bruit (par exemple avec un casque
      branché sur une prise jack combinée) : cocher l'entrée « pipewire » ou
      « default » dans l'onglet Matériel des Préférences (Alt+Shift+P) ; ces
      entrées suivent l'entrée choisie par le système, une entrée matérielle
      ALSA (hw:) ne la suit pas.

--- Effacement en temps réel (mode E) ---
E                Activer / désactiver le mode Erase (désactive Rec si actif)
NumPad 1-8       Effacer l'événement le plus proche du temps d'appui
NumPad 9         Effacer l'événement le plus proche sur le dernier pad
V / NumPad 0     Sortir du mode Erase

--- Note Repeat (mode Q actif) ---
NumPad 1-8       Jouer le pad + lancer le repeat (re-presser pour stopper)
1-8 (clavier)   Choisir le taux binaire : 1/1, 1/2, 1/4, 1/8, 1/16, 1/32, 1/64, 1/128
9 (clavier)      Basculer binaire ↔ ternaire
1-6 (ternaire)   Choisir le taux ternaire : 1/3, 1/6, 1/12, 1/24, 1/48, 1/96
Note: les taux sont des fractions de mesure (1/16 = double croche, quel que
      soit le nombre de pas). Les touches 1 à 9 sont sans effet sur le taux
      quand le focus est sur la liste des patterns ou de quantisation.

--- BPM / Volume Global / Pan Global ---
H                Tap Tempo : frapper au rythme pour définir le BPM (aussi Transport >
                 Métronome, avec Click, BPM +5 et BPM −5)
                 (4 frappes minimum = 1 mesure ; pause > 2 s repart de zéro)
( ou 5           BPM +5
)                BPM -5
                 Champ BPM, ( et ) : annulables (Ctrl+Z ; des pas rapprochés
                 de moins d'une seconde ne font qu'une entrée)
                 Champ BPM, H, ( et ) : tous les tempos du pattern changent
                 dans la même proportion ; le champ affiche le tempo en
                 vigueur à la position (et le suit pendant la lecture)
+                Volume +1
- ou 6           Volume -1
Ctrl+↑           Volume Global +1 (0..200)
Ctrl+↓           Volume Global -1 (0..200)
                 100 = volume normal ; au-dessus, le mix est amplifié
                 (200 = +6 dB) et le limiteur d'écoute empêche la saturation ;
                 l'annonce donne le gain : « Volume Global: 150 (+3,5 dB) »
Ctrl+→           Pan Global +1 (-100..+100)
Ctrl+←           Pan Global -1 (-100..+100)
Ctrl+Retour arrière   Volume et Pan Global aux valeurs des Préférences
                 (Retour arrière garde son rôle dans les champs BPM, Vol:, Pan:
                 et ceux des pads)

--- Grille (navigation) ---
Flèches          Déplacer le curseur
Entrée           Cocher / décocher la cellule + jouer la ligne courante
Shift+Entrée     Décocher la cellule + jouer la ligne courante
Tab / Shift+Tab  Passer au widget suivant / précédent

--- NumPad ---
NumPad 1-8       Jouer pad 1-8 (ou 9-16 selon ShiftPad)
NumPad 9         Rejouer le dernier pad
NumPad Entrée    Jouer le pad courant (depuis n'importe quel widget)
NumPad 0         Stop All
NumPad +         ShiftPad vers pads 9-16
NumPad -         ShiftPad vers pads 1-8

--- Mode Keyboard (Ctrl+2 pour activer, Ctrl+1 pour revenir en Pad) ---
Ctrl+1           Passer en mode Pad
Ctrl+2           Passer en mode Keyboard
                 Mode choisi d'office en arrivant sur un slot : Clavier sur
                 une banque ou un Synth SFZ, Pad sur un kit (annonce
                 « — Mode Clavier » / « — Mode Pad ») ; Ctrl+1 / Ctrl+2 est
                 gardé tant qu'on reste sur le même slot
Alt+X            Ouvrir l'explorateur (Projects, Preset, Kit, Patch, Sound, Banque :
                 fichier SF2/SF3 et emplacement 1 à 4 du slot courant ; SFZ :
                 slot Synth SFZ, voir ci-dessous)

  -- Slot Synth SFZ (Alt+X, élément SFZ) --
  Liste          Sources du dossier des instruments SFZ (clé sfz_dir de
                 config.json, par défaut /home/com/groovybox/media/sfz) :
                 banque Sforzando (.bank.xml), banque SFZ, dossier de
                 programmes (« 001-Piano » = programme 1), fichier .sfz seul ;
                 chaque ligne commence par son chemin (taper les premières
                 lettres pour y aller) ; Entrée ou double-clic = Ok
  Gain du slot   −24 à +12 dB : baisser une source trop forte (saturation)
  Fichier…       Choisir une source ailleurs (.sfz, .bank.xml, .sfzbank.json)
  Dossier…       Choisir un dossier de programmes ailleurs
  Nouvelle banque SFZ…   Composer sa propre banque (fichier .sfzbank.json),
                 par exemple des pianos de plusieurs bibliothèques
  Modifier la banque…    Modifier la banque SFZ sélectionnée dans la liste

  -- Composer une banque SFZ --
  Nom            Nom de la banque
  Programmes     Liste « numéro - nom — fichier » :
                 Suppr      retirer le programme
                 F2         renommer le programme
                 Alt+Haut / Alt+Bas   monter / descendre (échange le numéro
                            avec le programme voisin)
  Numéro         Numéro du programme sélectionné (1 à 128) ; un numéro déjà
                 pris est échangé avec l'autre programme
  Disponibles    Fichiers SFZ du dossier des instruments : Entrée ou
                 double-clic (ou Ajouter) ajoute au numéro libre suivant
  Parcourir…     Ajouter un fichier SFZ d'ailleurs
  Enregistrer    Choisir le fichier (proposé dans le dossier des instruments)
                 la première fois ; la banque est ensuite sélectionnée
                 Ok : le slot devient un Synth SFZ (Undo « SFZ slot NN ») ;
                 Ctrl+T pour l'assigner à la piste ; le Program Change de la
                 piste choisit le programme (comme une banque)

  -- Slot SYNTH (instrument mélodique) --
  NumPad 1-8     Jouer les 8 premières notes de la gamme courante ; au
                 départ NumPad 1 = do 2 (note 36), comme la touche la plus
                 grave du contrôleur MIDI
  NumPad 9       Rejouer la dernière note MIDI jouée
  NumPad +       Octave suivante (bloquant à C7) : le contrôleur MIDI suit
  NumPad -       Octave précédente (bloquant à C0) : le contrôleur MIDI suit
  NumPad /       Gamme précédente (bloquant en début de liste)
  NumPad *       Gamme suivante (bloquant en fin de liste)

  -- Slot KIT (batterie pitchée, style Maschine+) --
  NumPad 1-8     Pitcher le dernier pad joué (ou pad courant) sur les 8 notes
                 de la gamme ; root C4 = pitch original du son
  NumPad 9       Rejouer la dernière note MIDI pitchée
  NumPad +/-     Décaler l'octave (et donc la plage de pitch)
  NumPad / *     Changer de gamme

--- Patterns (focus liste des patterns) ---
Alt+Entrée       Ouvrir les propriétés du pattern sélectionné : nom, début, longueur,
                 tempo (tous les tempos en proportion), signature (temps par mesure,
                 valeur du temps), résolution, boucle, mode Rack 16 canaux (le canal
                 N d'une piste joue le slot N), action ; tempo et signature
                 s'entendent en direct, Annuler les rétablit
Double-clic      Ouvrir les propriétés du pattern (liste des patterns)
Ctrl+P           Lecture / Pause (depuis la boite de dialogue des propriétés)

--- Slots (liste des slots) ---
Haut / Bas       Parcourir les slots : nom annoncé, rien n'est chargé (la batterie
                 et le son du clavier restent ceux de la piste courante)
Entrée           Assigner le slot sélectionné à la piste courante et le charger
Double-clic      Assigner le slot sélectionné à la piste courante (≡ Ctrl+T)
Alt+X            Explorateur : charger un kit, un patch ou une banque dans le slot
                 sélectionné (sons chargés si c'est le slot de la piste courante)

--- Pistes (focus liste des pistes) ---
Ctrl+T / Entrée  Assigner le slot sélectionné dans la liste des slots à la piste
                 courante (un kit met la piste sur le canal MIDI 10 ; un autre slot
                 la ramène à son canal par défaut), avec Undo « Piste N → Slot_NN » ;
                 en mode Rack 16 canaux : passer la piste au canal du slot
                 (Undo « Piste N → canal M ») ; les notes de la piste sont
                 coupées avant
Ctrl+Entrée      Ouvrir la boîte de sélection de pistes + plage temporelle (bar:beat:tick)
Ctrl+Shift+T     Propriétés de la piste courante, quel que soit le focus (≡ Alt+Entrée)
Alt+Entrée       Ouvrir les propriétés de la piste sélectionnée :
                 Type de piste (MIDI ou Audio ; une piste audio enregistre une entrée
                 audio, ses réglages MIDI sont grisés), Entrée audio (entrées cochées
                 dans les Préférences), Mute, Solo, Slot, Entrée MIDI (« Toutes les entrées » ou une entrée
                 cochée dans les Préférences : la piste ne reçoit que ce port),
                 Sortie MIDI (« Interne (son du slot) » ou une sortie externe cochée :
                 la piste y envoie ses notes, son son interne se tait ; port absent :
                 son interne, avec avertissement), Canal MIDI (1 à 16), Programme GM
                 du slot (instruments pour un synthé, kits GM2 pour un kit), Volume, Pan
                 Sur un slot Banque, en direct : Programme du canal (liste de la
                 soundfont), Banque MSB et LSB ; changer de canal fait entendre
                 l'instrument de ce canal ; note d'aperçu ; Ok écrit l'entête
                 de la piste (CC0, CC32, Program Change à 1.1.1)
                 Sur un slot Synth SFZ : de même, Programme du canal = liste
                 des programmes de sa source ; Banque MSB et LSB grisées
                 En mode Rack 16 canaux : le slot est le canal (choisir l'un
                 choisit l'autre) ; chaque canal dit le slot qu'il joue
                 Changer le slot, le canal, le programme ou la banque coupe d'abord
                 les notes de la piste ; changer Mute ou Solo coupe toutes les notes
Double-clic      Jouer le pad courant
Double-clic+Alt  Ouvrir les propriétés de la piste
X / Shift+X      Mute piste / Démuter toutes (toutes les notes coupées avant ;
                 X quitte le mode exclusif, Shift+X quitte le Mute exclusif)
S / Shift+S      Solo piste / Désolo toutes (toutes les notes coupées avant ;
                 S quitte le mode exclusif, Shift+S quitte le Solo exclusif)
F3               Mute exclusif On / Off : seule la piste courante est muette ;
                 Haut / Bas dans la liste des pistes y met la nouvelle piste
F4               Solo exclusif On / Off : seule la piste courante est en solo ;
                 Haut / Bas dans la liste des pistes y met la nouvelle piste
                 (F4 en Mute exclusif passe en Solo exclusif, et inversement ;
                 un second F3 / F4 quitte le mode et rétablit les Mute et Solo
                 d'avant son activation)
F5               Réinitialiser tous les Mute et Solo de piste et quitter le mode
                 exclusif (Shift+X et Shift+S à la fois)
Alt+↑ / Alt+↓   Volume piste ±5 (0..100)
Alt+← / Alt+→   Pan piste ±10 (-100..+100)
Shift+Retour arrière  Volume de la piste à 100 et Pan à 0 (depuis la liste des
                      pistes)
                 Volume et pan de piste, et pan global, s'entendent tout de
                 suite sur ce qui sonne déjà (clips, notes Wave et Kit), Ctrl+Z
                 compris

  -- Sélection multi-pistes --
  Ctrl+A           Sélectionner toutes les pistes + limiteurs sur plage complète
  Ctrl+Shift+A     Désélectionner tout + réinitialiser les limiteurs
  Shift+Espace     Ajouter / retirer la piste courante de la sélection (bip à l'ajout)
                   Permet la sélection non-adjacente (ex. pistes 1, 3, 7)
  Shift+↑          Étendre la sélection vers la piste du dessus (pistes adjacentes)
  Shift+↓          Étendre la sélection vers la piste du dessous (pistes adjacentes)
  ↑ / ↓           Naviguer entre les pistes (la sélection multi-pistes est préservée)

  -- Limiteurs temporels (in/out points) --
  i                Poser le limiteur gauche (In)  à la position courante du playhead
  o                Poser le limiteur droit  (Out) à la position courante du playhead ;
                   il est EXCLU, comme la fin de boucle : quatre mesures vont de 1:1:1
                   à 5:1:1 (refusé au limiteur gauche ou avant)
  Shift+I          Poser le limiteur gauche (In)  au début du pattern (step 0)
  Shift+O          Poser le limiteur droit  (Out) à la fin du pattern (9:1:1 pour 8 mesures)
                   Affichés dans la barre de statut en BBT + step
                   Ctrl+Entrée pré-remplit le dialog avec les limiteurs courants
                   Ctrl+A / Ctrl+Shift+A gèrent aussi les limiteurs
  Ctrl+Shift+I     Sélection des limiteurs (dialogue : sources Position courante,
                   début / fin du pattern, début / fin de boucle, Personnalisé ;
                   refus si le gauche est après le droit) ; aussi dans l'éditeur
                   Les limiteurs sont enregistrés dans le projet, et chaque
                   commande qui les change est annulable (Ctrl+Z)

  -- Navigation par les limiteurs --
  Début (Home)     Aller au limiteur gauche (ou début du pattern si non défini)
  Fin   (End)      Aller au limiteur droit, exclu (dernier step sans limiteur ou s'il
                   est à la fin du pattern)
  Shift+Début      Aller au début de la boucle (ou step 0 si non défini)
  Shift+Fin        Aller à la fin de la boucle, exclue (5:1:1 pour quatre mesures ;
                   dernier step si non définie)
  Alt+Début        Assigner la boucle aux limiteurs (annulable ; sans boucle : tout
                   le pattern)
  Alt+Fin          Assigner les limiteurs à la boucle (annulable ; limiteur absent :
                   début / fin du pattern) ; aussi Transport > Limiteurs
  Ctrl+Début       Aller au début absolu du pattern (step 0)
  Ctrl+Fin         Aller à la fin absolue du pattern (dernier step)

  -- Édition des pistes sélectionnées --
  Ctrl+C           Copier les pistes sélectionnées → presse-papier
  Ctrl+X           Erase : copie → presse-papier + efface grille (+ tape si limiteurs)
  Ctrl+D           Delete : copie → presse-papier + efface grille et tape
  Ctrl+V           Coller le presse-papier sur la piste courante
  Shift+V          Coller par fusion (les événements existants sont conservés)
  Ctrl+Suppr       Effacer grille et tape sans presse-papier
  Shift+Suppr      Réinitialiser (vider) le pattern entier (annulable)
  Suppr            Effacer piste(s) sélectionnée(s) sans presse-papier (annulable)

--- MIDI ---
Shift+F12        Connecter / déconnecter les entrées MIDI cochées dans les Préférences
                 (Alt+Shift+P, onglet Matériel) ; toutes les fenêtres
Ctrl+Shift+F12   Réinitialiser les périphériques MIDI : relire les ports et rouvrir
                 les entrées et sorties cochées (après un débranchement) ; toutes
                 les fenêtres
Contrôleur       Une note tenue s'arrête au relâchement là où elle a été jouée, même
                 après un changement de piste, de slot, de canal ou de programme :
                 on peut tenir une note, changer de piste et en jouer une autre
                 (accord sur plusieurs canaux) ; un Program Change reçu coupe d'abord
                 les notes de la piste courante

--- Éditeur MIDI (Alt+4) ---
Alt+4            Ouvrir l'éditeur MIDI (rouvre dans le dernier mode utilisé)
Échap            Fermer la fenêtre
Alt+Shift+E      Exporter en MIDI (.mid) le pattern ou le song courant, comme la fenêtre principale
Alt+Shift+W      Exporter en audio (.wav), même dialogue que la fenêtre principale
                 (source Presse-papier = celui des notes de l'éditeur)
Alt+Shift+I      Importer un fichier MIDI (.mid) dans le pattern courant, comme la fenêtre principale
Alt+Shift+T      Dialogue Tempo, comme la fenêtre principale

  -- Modes d'affichage --
  Ctrl+1         Afficher les notes de la piste courante seulement (mode sauvegardé)
  Ctrl+2         Afficher tous les événements MIDI du pattern (mode sauvegardé)

  -- Navigation dans la liste --
  ←/→            Aller et jouer la note ou groupe temporel précédent / suivant
  ↑/↓            Naviguer entre les notes d'un accord (groupe simultané)
  Début (Home)   Aller au premier événement de la liste filtrée
  Fin   (End)    Aller au dernier événement de la liste filtrée
  Ctrl+Début     Réinitialiser les limiteurs et aller au premier événement
  Ctrl+Fin       Réinitialiser les limiteurs et aller au dernier événement

  -- Sélection --
  Ctrl+A         Sélectionner tous les événements affichés
  Ctrl+Shift+A   Désélectionner tout
  Shift+←        Sélectionner/désélectionner le groupe et aller au précédent (joue le groupe)
  Shift+→        Sélectionner/désélectionner le groupe et aller au suivant (joue le groupe)
  Shift+↑/↓      Sélectionner / désélectionner la note individuelle dans l'accord
  Ctrl+Shift+F   Ouvrir le dialog de filtre d'événements (type, note, vélocité, pitch
                 bend, position ; Ok/Appliquer/Ajouter/Supprimer/Réinitialiser la
                 sélection/Effacer le filtre — le dernier état est mémorisé en session)

  -- Édition --
  Ctrl+Q         Quantiser le pattern depuis la grille courante (sans dialog)
  Shift+Q        Quantiser le pattern avec les derniers paramètres mémorisés (sans dialog)
  Ctrl+Shift+Q   Ouvrir le dialog de quantisation (résolution, force, swing, fenêtre)
  Entrée         Éditer la note sélectionnée (dialog : pitch, position, longueur, velocity ;
                 note de grille d'une piste à notes : 128 notes, convertie en note
                 enregistrée si la hauteur sort des notes de la grille) ;
                 un CC ou un Program Change : valeur, position, canal (1 à 16) — un
                 Program Change à 1.1.1 d'une piste Banque lui donne son canal ;
                 une ligne Tempo : position, BPM et portée (le plus récent, tous à
                 cette valeur, tous proportionnellement)
  Suppr / Ret.   Supprimer l'événement sélectionné (une ligne Tempo : ce changement ;
                 le tempo de départ ne se supprime pas)
  Ctrl+C         Copier les événements sélectionnés
  Ctrl+X         Couper les événements sélectionnés
  Ctrl+V         Coller le presse-papier
  Ctrl+Z         Annuler (Undo)
  Shift+Z        Refaire (Redo)
  Ctrl+Shift+Z   Afficher l'historique des annulations
  D              Dupliquer l'événement/accord courant (empilé à la même position ;
                 pad adjacent pour GRID) + avancer le playhead d'une valeur de grille
  Shift+D        Dupliquer sans avancer le playhead
  Ctrl+I         Insérer une note (instrument de la piste courante) à la position du
                 playhead + avancer le playhead d'une valeur de grille
  Alt+I          Insérer une note sans avancer le playhead
  Ctrl+Shift+N   Ouvrir le dialog d'insertion (note, durée, vélocité)
  A              Insérer une note entre l'événement courant et le suivant (au pas
                 médian entre les deux), curseur sur la nouvelle note
  R              Rafraîchir la liste des événements (utile si le pattern a été modifié
                 depuis la fenêtre principale pendant que l'éditeur est ouvert)
  S / Shift+S    Solo piste(s) sélectionnée(s) / Désolo toutes
  X / Shift+X    Mute piste(s) sélectionnée(s) / Démuter toutes
                 (toutes les notes coupées avant ; S et X quittent le Mute / Solo
                 exclusif de la fenêtre principale)

  -- Limiteurs temporels --
  i              Poser le limiteur gauche (In) à la position courante du playhead
  o              Poser le limiteur droit (Out, exclu) à la position courante du playhead
  Shift+I        Poser le limiteur gauche au début du pattern (step 0)
  Shift+O        Poser le limiteur droit à la fin du pattern
  Ctrl+Shift+I   Sélection des limiteurs (même dialogue que la fenêtre principale)

  -- Édition numpad (événement ou accord sélectionné ; aussi Traitement >
     Midi > Note) --
  Num 1 / Num 3  Raccourcir / rallonger la durée (KIT/PATCH uniquement, pas GRID)
  Num 4 / Num 6  Reculer / avancer la position d'une valeur de grille
                 (étend le pattern si on dépasse la fin)
  Num 7 / Num 9  Vélocité -1 / +1 (bornée 1..127)
  Num 2 / Num 8  Pitch ±1 demi-ton (0..127 ; note de grille d'une piste à notes :
                 sur sa hauteur réelle, convertie en note enregistrée hors des notes
                 de la grille ; piste de kit : 0..num_pads-1)
  Ctrl+Num 2 / Ctrl+Num 8  Pitch ±1 octave (mêmes bornes)
  NumPad 5       Afficher la position courante
  Ctrl+NumPad 5  Afficher la valeur de grille courante
  NumPad - / +   Diminuer / augmenter la valeur de grille courante

  -- Clavier virtuel (liste des 128 notes C0..G10) --
  ↑ / ↓          (focus sur le clavier virtuel) Note précédente/suivante, jouée et annoncée
  Alt+NumPad 2/8 Note du clavier virtuel ±1 demi-ton (raccourci global, quel
                 que soit le focus) ; sert de source par défaut pour Ctrl+I/Alt+I

  -- Transport (partagé avec la fenêtre principale) --
  Espace / P       Play / Pause pattern
  Ctrl+Space       Aller au début et lancer la lecture immédiatement (Goto Start + Play)
  V                Stop All
  g                Aller au début du pattern (Goto Start)
  Shift+G          Aller à la fin du pattern (Goto End)
  w                Avancer de 1 seconde
  b                Reculer de 1 seconde
  PageDown         +1 mesure
  PageUp           -1 mesure
  Ctrl+PageDown    +1 battement
  Ctrl+PageUp      -1 battement
  Shift+PageDown   +1 tick (pas)
  Shift+PageUp     -1 tick (pas)
  l                Boucle On / Off
  Shift+L          Poser le point de fin de boucle (exclue) à la position courante
  U                Afficher l'état du player et la position courante
  Ctrl+G           Aller à une position (dialog bar:beat:tick)
  Ctrl+Shift+G     Ouvrir la boîte de grille
  Ctrl+F12         Panic : arrêt immédiat de tous les sons + Reset All Controllers

--- Fenêtre Songs (Alt+5) ---
Alt+5            Ouvrir la fenêtre Songs
Espace / P       Play / Pause du song courant
g                Aller au début du song (Goto Start)
Shift+G          Aller à la fin du song (Goto End)
Ctrl+W           Enregistrer le projet (avec le song courant)
Ctrl+Shift+W     Enregistrer le projet sous... (avec le song courant)
Alt+Shift+E      Exporter le song courant en fichier MIDI (.mid), dossier EXPORTS (sans choix)
Alt+Shift+W      Exporter en audio (.wav) : le dialogue de la fenêtre principale,
                 ouvert sur la source Song courant, puis le nom du fichier (fin
                 proposée : boucle exacte si le song boucle, sinon song + résonance)
Échap            Fermer la fenêtre Songs
Note: les raccourcis de transport (PageUp/Down, w, b, Ctrl+G, Ctrl+Shift+G…)
      fonctionnent aussi depuis la fenêtre Songs

  -- Liste Patterns disponibles (focus) --
  Entrée / Double-clic             Ajouter le pattern à la séquence du song
  Ctrl+Entrée / Ctrl+Double-clic   Insérer le pattern avant la position courante dans la séquence

  -- Séquence (focus) --
  Ctrl+Entrée           Insérer le pattern (Patterns disponibles) avant la position courante
  Suppr / Retour arr.   Supprimer l'entrée sélectionnée
  Alt+↑                 Monter l'entrée sélectionnée
  Alt+↓                 Descendre l'entrée sélectionnée

--- Aide ---
F1               Afficher cette aide
F10 / Alt seul   Ouvrir la barre de menus (menu Fichier) ; Alt seul (appuyé puis
                 relâché sans autre touche, pas AltGr) la referme aussi ; Gauche / Droite : menu
                 voisin, Haut / Bas : élément, Échap : remonter d'un sous-menu ou
                 fermer la barre ; les raccourcis sont affichés dans les éléments
Alt+lettre       Ouvrir un menu : F Fichier / Effets, E Edition, T Transport /
                 Piste, G Aller à, I Insertion, P Pattern, A Affichage / Aide,
                 R Traitement, M Mixer, O Outils, N Options, W Fenêtres ; une
                 lettre partagée alterne, même menu ouvert ; les commandes
                 Alt+lettre (Alt+X, Alt+L…) gardent la priorité
                 Les éléments des menus Edition (Supprimer, Sélection), Piste
                 (précédente / suivante), Pattern et Mixer agissent sur la piste
                 ou le pattern courant quel que soit le focus
                 Dialogues sans raccourci : Mixer > Régler… (volume, pan),
                 Pattern > Choisir un pattern…, Redimensionner le pattern…,
                 Transport > Métronome > Régler le tempo… (( et ) : ±5, H :
                 Tap Tempo, case Click ; entendu en direct, tous les tempos
                 changent en proportion ; Annuler rétablit)
F3 / F4          Mute exclusif / Solo exclusif (voir « Pistes »)
F5               Réinitialiser tous les Mute et Solo de piste
F8               Monitoring de l'entrée audio On / Off
F2               Renommer l'élément courant :
                   focus liste des pistes  → renommer la piste
                   focus ailleurs          → renommer le pattern courant
                   fenêtre Songs           → renommer le song courant
