=== Aide clavier — GroovyboxIt ===

--- Projet ---
Ctrl+N           Nouveau projet (noname_NNN.gvp, demande si modifié)
Ctrl+O           Ouvrir un projet (.gvp, .json ou tout fichier)
Ctrl+S           Enregistrer le projet
Ctrl+Shift+S     Enregistrer le projet sous...

--- Pattern ---
Ctrl+W           Enregistrer le pattern courant
Ctrl+Shift+W     Dupliquer le pattern courant vers un autre slot
Ctrl+P           Charger le pattern de démonstration
Shift+P          Générer un pattern aléatoire
Ctrl+F           Doubler le pattern (duplique les mesures existantes)
Shift+F          Diviser le pattern par deux (garde la première moitié)

--- Quantisation ---
Ctrl+E           Appliquer la quant à la ligne courante
Ctrl+Shift+E     Choisir la ligne + quant et générer le motif
Shift+E          Décocher toute la ligne courante
Shift+Q          Quantiser le pattern (valeur par défaut)
Ctrl+Shift+Q     Choisir la quant et appliquer au pattern

--- Lecture ---
Espace / P       Play / Pause pattern (reprend depuis la position pausée)
Ctrl+Space       Aller au début et lancer la lecture immédiatement (Goto Start + Play)
                 Fonctionne aussi depuis l'éditeur MIDI et la fenêtre Songs
V                Stop All (sons + pattern + Rec + Erase + réinitialise la position)
C                Toggle métronome (click)
Q                Activer / désactiver le mode Note Repeat
g                Transport : Aller au début du pattern (Goto Start)
Shift+G          Transport : Aller à la fin du pattern (Goto End)
l                Boucle On / Off (le pattern redémarre ou s'arrête en fin de cycle)
Ctrl+L           Poser le point de début de boucle à la position courante du playhead
Shift+L          Poser le point de fin de boucle à la position courante du playhead
Ctrl+Shift+L     Ouvrir le dialog de points de boucle (début, fin, répétitions)
Alt+L            Réinitialiser les points de boucle (début et fin) à la longueur du pattern
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

--- Volume / Pan par Pad ---
Alt+↑            Volume du Pad courant +5
Alt+↓            Volume du Pad courant -5
Alt+←            Pan du Pad courant -10 (vers la gauche)
Alt+→            Pan du Pad courant +10 (vers la droite)
Alt+0            Recentrer le Pan du Pad courant (→ 0)

--- Enregistrement (mode R) ---
R                Démarrer l'enregistrement en Overdub (démarre aussi la lecture)
R (2e appui)     Arrêter l'enregistrement (lecture continue)
Shift+R          Enregistrement en Remplacement : les notes existantes sont effacées
                 au fil du playback, remplacées par les nouvelles frappes
Shift+R (2e)     Arrêter le mode Remplacement
Ctrl+R           Count-In : 1 mesure de métronome, puis Rec+Play démarre
NumPad 1-8       Jouer + enregistrer le pad dans le pattern
NumPad 9         Rejouer + enregistrer le dernier pad
Note: en mode Note Repeat actif, les répétitions sont aussi enregistrées

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

--- BPM / Volume Global / Pan Global ---
H                Tap Tempo : frapper au rythme pour définir le BPM
                 (4 frappes minimum = 1 mesure ; pause > 2 s repart de zéro)
( ou 5           BPM +5
)                BPM -5
+                Volume +1
- ou 6           Volume -1
Ctrl+↑           Volume Global +1 (0..100)
Ctrl+↓           Volume Global -1 (0..100)
Ctrl+→           Pan Global +1 (-100..+100)
Ctrl+←           Pan Global -1 (-100..+100)
Ctrl+0           Centrer le Pan Global (→ 0)

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
Alt+X            Ouvrir l'explorateur de patch (charger un instrument)

  -- Slot SYNTH (instrument mélodique) --
  NumPad 1-8     Jouer les 8 premières notes de la gamme courante
  NumPad 9       Rejouer la dernière note MIDI jouée
  NumPad +       Octave suivante (bloquant à C7)
  NumPad -       Octave précédente (bloquant à C0)
  NumPad /       Gamme précédente (bloquant en début de liste)
  NumPad *       Gamme suivante (bloquant en fin de liste)

  -- Slot KIT (batterie pitchée, style Maschine+) --
  NumPad 1-8     Pitcher le dernier pad joué (ou pad courant) sur les 8 notes
                 de la gamme ; root C4 = pitch original du son
  NumPad 9       Rejouer la dernière note MIDI pitchée
  NumPad +/-     Décaler l'octave (et donc la plage de pitch)
  NumPad / *     Changer de gamme

--- Patterns (focus liste des patterns) ---
Alt+Entrée       Ouvrir les propriétés du pattern sélectionné
Double-clic      Ouvrir les propriétés du pattern (liste des patterns)
Ctrl+P           Lecture / Pause (depuis la boite de dialogue des propriétés)

--- Slots (liste des slots) ---
Double-clic      Assigner le slot sélectionné à la piste courante (≡ Ctrl+T)

--- Pistes (focus liste des pistes) ---
Ctrl+T / Entrée  Assigner le slot courant à la piste courante
Ctrl+Entrée      Ouvrir la boîte de sélection de pistes + plage temporelle (bar:beat:tick)
Alt+Entrée       Ouvrir les propriétés de la piste sélectionnée
Double-clic      Jouer le pad courant
Double-clic+Alt  Ouvrir les propriétés de la piste
X / Shift+X      Mute piste / Démuter toutes
S / Shift+S      Solo piste / Désolo toutes
Alt+↑ / Alt+↓   Volume piste ±5 (0..100)
Alt+← / Alt+→   Pan piste ±10 (-100..+100)
Alt+0            Recentrer le pan de la piste (Pan 0)

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
  o                Poser le limiteur droit  (Out) à la position courante du playhead
  Shift+I          Poser le limiteur gauche (In)  au début du pattern (step 0)
  Shift+O          Poser le limiteur droit  (Out) à la fin du pattern (dernier step)
                   Affichés dans la barre de statut en BBT + step
                   Ctrl+Entrée pré-remplit le dialog avec les limiteurs courants
                   Ctrl+A / Ctrl+Shift+A gèrent aussi les limiteurs

  -- Navigation par les limiteurs --
  Début (Home)     Aller au limiteur gauche (ou début du pattern si non défini)
  Fin   (End)      Aller au limiteur droit  (ou fin du pattern si non défini)
  Shift+Début      Aller au début de la boucle (ou step 0 si non défini)
  Shift+Fin        Aller à la fin de la boucle  (ou dernier step si non défini)
  Ctrl+Début       Aller au début absolu du pattern (step 0)
  Ctrl+Fin         Aller à la fin absolue du pattern (dernier step)

  -- Édition des pistes sélectionnées --
  Ctrl+C           Copier les pistes sélectionnées → presse-papier
  Ctrl+X           Erase : copie → presse-papier + efface grille (+ tape si limiteurs)
  Ctrl+D           Delete : copie → presse-papier + efface grille et tape
  Ctrl+V           Coller le presse-papier sur la piste courante
  Shift+V          Coller par fusion (les événements existants sont conservés)
  Ctrl+Suppr       Effacer grille et tape sans presse-papier
  Shift+Suppr      Réinitialiser le pattern entier
  Suppr            Effacer piste(s) sélectionnée(s) sans presse-papier

--- MIDI ---
Alt+M            Connecter / déconnecter le port MIDI sélectionné
Alt+Shift+M      Actualiser la liste des ports MIDI
Double-clic      Connecter le port MIDI sélectionné (liste des ports)

--- Éditeur MIDI (Alt+4) ---
Alt+4            Ouvrir l'éditeur MIDI (rouvre dans le dernier mode utilisé)
Échap            Fermer la fenêtre

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

  -- Édition --
  Ctrl+Shift+Q   Ouvrir le dialog de quantisation (résolution, force, swing, fenêtre)
  Entrée         Éditer la note sélectionnée (dialog : pitch, position, longueur, velocity)
  Suppr / Ret.   Supprimer l'événement sélectionné
  Ctrl+C         Copier les événements sélectionnés
  Ctrl+X         Couper les événements sélectionnés
  Ctrl+V         Coller le presse-papier
  Ctrl+Z         Annuler (Undo)
  Shift+Z        Refaire (Redo)
  Ctrl+Shift+Z   Afficher l'historique des annulations

  -- Limiteurs temporels --
  i              Poser le limiteur gauche (In) à la position courante du playhead
  o              Poser le limiteur droit (Out) à la position courante du playhead
  Shift+I        Poser le limiteur gauche au début du pattern (step 0)
  Shift+O        Poser le limiteur droit à la fin du pattern (dernier step)

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
  Shift+L          Poser le point de fin de boucle à la position courante du playhead
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
F2               Renommer l'élément courant :
                   focus liste des pistes  → renommer la piste
                   focus ailleurs          → renommer le pattern courant
                   fenêtre Songs           → renommer le song courant
