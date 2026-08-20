# Changelog

Versienummers volgen de tag van de GitHub-release. De app vergelijkt de
nieuwste tag met `__version__` in `talkwithme/__init__.py`.

## 0.2.0

- Opmaak per app afgeleid uit wat de doel-app met de tekst doet. Chat en
  terminal worden altijd één regel, omdat Enter daar verstuurt of uitvoert;
  e-mail krijgt alinea's en een gesproken aanhef op een eigen regel.
- Nieuwe tonen: document, sociale post en ticket.
- Deterministische opmaak in code in plaats van in de prompt, zodat regels
  die altijd moeten gelden ook altijd gelden.
- Twee regels die nooit ontbreken mogen: het model beantwoordt de tekst niet
  en vertaalt hem niet. Ook niet als de basisinstructie is aangepast.
- Gesproken interpunctie ("nieuwe alinea", "vraagteken") wordt herkend.
- Eén exemplaar tegelijk: de app opnieuw starten opent het venster van het
  exemplaar dat al draait.
- Hernoemd van TalktoMathi naar TalkWithMe. Bestaande keys, geschiedenis en
  instellingen worden automatisch overgenomen.

## 0.1.0

Eerste release.

- Hold-to-talk op Ctrl+Win: indrukken, praten, loslaten.
- Spraak naar tekst via ElevenLabs Scribe v2.
- Opschonen via Gemini Flash: vullers, valse starts en zelfcorrecties eruit,
  interpunctie erin, betekenis en woordkeuze ongemoeid.
- Toon per app: chat kort en informeel, e-mail verzorgd, terminal letterlijk.
- Zwevende indicator met live waveform, systeemvakicoon per status.
- Geschiedenis met schakelaar tussen opgeschoonde en ruwe tekst.
- Weekrapport met bespaarde tijd tegenover typen.
- Installatie met Start-menu-snelkoppeling en autostart.
- Automatische updates via GitHub Releases.
