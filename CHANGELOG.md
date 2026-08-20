# Changelog

Versienummers volgen de tag van de GitHub-release. De app vergelijkt de
nieuwste tag met `__version__` in `talkwithme/__init__.py`.

## 0.4.0

**Streaming transcriptie.** De audio wordt nu verstuurd terwijl je praat in
plaats van erna. Bij het loslaten rest alleen nog de staart: gemeten ging
de transcriptie van ongeveer 2,7 seconden naar 0,8. Valt de verbinding weg,
dan gebruikt de app gewoon de oude route met de bewaarde opname, dus een
haperend netwerk kost je nooit een dictaat.

- Bij een vergadering loopt het transcript live mee in het tabblad, en zijn
  de notities meteen klaar in plaats van na het uploaden van een uur audio.
- Uit te zetten met `realtime_enabled` in de config.

**Een dode microfoon wordt herkend.** Komt een opname helemaal stil terug,
dan zegt de app dat, met de meest waarschijnlijke oorzaak eerst: de
mute-toets op je toetsenbord. Twee stille dictaten op rij geven een venster
met het volledige stappenplan. Voorheen meldde de app "geen spraak herkend"
en wees daarmee naar de spreker terwijl de microfoon uitstond.

**Opgelost: blanco pictogram op de taakbalk.** Werd de app geïnstalleerd
vanuit een verpakte (MSIX) omgeving, dan legde Windows de bestanden in een
container en verwees de snelkoppeling naar een pad dat daarbuiten niet
bestaat. Het installatiepad wordt nu uit het gebruikersprofiel opgebouwd in
plaats van uit de omgevingsvariabele.

## 0.3.0

**Vergadernotities.** Ctrl+Win+M, of de knop in het nieuwe tabblad
Vergaderingen, neemt een heel gesprek op en werkt het daarna uit tot
notities met besluiten, actiepunten en aandachtspunten.

- Neemt zowel je microfoon als het geluid van je computer op, zodat de
  andere deelnemers in een online gesprek ook in het transcript staan.
  Zonder die tweede bron blijft de opname eenzijdig, en dat wordt gemeld
  in plaats van stil weggelaten.
- Sprekerherkenning: het transcript staat per spreker.
- Typ tijdens de vergadering korte notities; die worden achteraf
  aangevuld met de details uit het transcript in plaats van vervangen
  door een samenvatting. Wat jij niet noteerde maar wel een besluit of
  actie was, komt erbij met een "+" ervoor.
- Notities exporteren als Markdown, tekst, HTML, Word of PDF.
- Het transcript blijft naast de notities bewaard: een samenvatting is
  een interpretatie, en die moet je kunnen nakijken.

**Dashboard.** Zes kerncijfers, en per kanaal uitgesplitst.

- Bespaarde tijd, dictaten, woorden, spreektempo, wachttijd en hoe vaak
  de tekst zonder omweg op de cursor belandde.
- Waar de wachttijd heen gaat: transcriptie, opschonen, de rest.
  Medianen en een 95e percentiel, geen gemiddelden.
- Per app of per toon: aantal, gemiddelde lengte, bespaarde tijd,
  wachttijd. Met een concrete observatie eronder, afgeleid uit je eigen
  cijfers.

**Opgelost.** Weigerde de microfoon kortstondig te openen, dan viel de app
terug op het standaardapparaat, dat op sommige machines alleen stilte
opneemt. De opname leek te lukken maar bevatte niets. De echte microfoon
krijgt nu meerdere pogingen, en een stille opname wordt herkend en gemeld
in plaats van als "geen spraak herkend" afgedaan.

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
