=== Aide clavier — GroovyboxIt ===

--- Preset ---
Alt+W            Enregistrer le preset
Alt+Shift+W      Enregistrer le preset sous...

--- Pattern ---
Ctrl+W           Enregistrer le pattern courant
Ctrl+Shift+W     Enregistrer le pattern sous...
Ctrl+D           Réinitialiser le pattern (tout effacer)
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
V                Stop All (sons + pattern + Rec + Erase + réinitialise la position)
C                Toggle métronome (click)
Q                Activer / désactiver le mode Note Repeat
g                Transport : Aller au début du pattern (Goto Start)
Shift+G          Transport : Aller à la fin du pattern (Goto End)
l                Boucle On / Off (le pattern redémarre ou s'arrête en fin de cycle)
PageDown         Transport : +1 mesure
PageUp           Transport : −1 mesure
Ctrl+PageDown    Transport : +1 battement
Ctrl+PageUp      Transport : −1 battement
Shift+PageDown   Transport : +1 tick (pas)
Shift+PageUp     Transport : −1 tick (pas)
w                Transport : +1 seconde
b                Transport : −1 seconde
Ctrl+G           Afficher l'état du player et la position (Lecture|Pause|Arrêt, Pos: bar:beat:tick / total)
Ctrl+Shift+G     Transport : Aller à une position (boîte de dialogue Unité + Valeur + bar:beat:tick)
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
Alt+5            Ouvrir la fenêtre Songs (Mode Song)

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
Ctrl+T           Assigner le slot courant à la piste courante
Shift+D          Effacer la piste courante
Entrée           Ouvrir les propriétés de la piste sélectionnée
Alt+Entrée       Ouvrir les propriétés de la piste sélectionnée
Double-clic      Jouer le pad courant
Double-clic+Alt  Ouvrir les propriétés de la piste
X / Shift+X      Mute piste / Démuter toutes
S / Shift+S      Solo piste / Désolo toutes
Alt+↑ / Alt+↓   Volume piste ±5 (0..100)
Alt+← / Alt+→   Pan piste ±10 (-100..+100)
Alt+0            Recentrer le pan de la piste (Pan 0)

--- MIDI ---
Alt+M            Connecter / déconnecter le port MIDI sélectionné
Alt+Shift+M      Actualiser la liste des ports MIDI
Double-clic      Connecter le port MIDI sélectionné (liste des ports)

--- Aide ---
F1               Afficher cette aide
