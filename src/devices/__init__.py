#python3
"""
    Paquet devices — détection et essai des périphériques audio et MIDI
    (Phase 8 étape 11, docs/DESIGN.md § Phase 8 étape 11a).

    Paquet AUTONOME : il n'importe rien de GroovyboxIt et peut être copié
    tel quel dans une autre application audio / MIDI. Dépendances :
    sounddevice et numpy (devices.audio_device) ; python-rtmidi (devices.midi_device).

    - devices.audio_device : pilotes (host API) et périphériques de PortAudio par
      nom, relecture, La 440 Hz de test, crête d'une entrée ;
    - devices.midi_device : ports MIDI par nom, plusieurs entrées ouvertes
      ensemble, sorties, A4 de test, écoute de la prochaine note ;
    - python3 -m devices : liste des pilotes et des périphériques (essai
      d'une carte son).

    Date: Wed, 11/11/2026
    Author: Coolbrother
"""
