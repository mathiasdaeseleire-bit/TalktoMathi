# Changelog

Versienummers volgen de tag van de GitHub-release. De app vergelijkt de
nieuwste tag met `__version__` in `talkwithme/__init__.py`.

## 0.5.1

**Opgelost: verkeerde taal in de transcriptie.** Sinds de overstap naar
streaming stond de taal op automatisch, en die keuze wordt per kort
fragment gemaakt in plaats van over de hele opname. Een korte Nederlandse
zin kwam daardoor terug in het Bulgaars. De taal staat nu standaard op
Nederlands en is instelbaar; Engelse woorden in een Nederlandse zin
blijven gewoon staan.

**Resterend tegoed na het spreken.** Beweeg over het systeemvakicoon en je
ziet hoeveel minuten je nog kunt spreken. Dat cijfer wordt na elk dictaat
ververst. Een melding komt er alleen wanneer het tegoed echt bijna op is,
en dan eenmalig.

## 0.5.0

**Resterend tegoed zichtbaar.** Het weekrapport toont hoeveel credits er nog
bij ElevenLabs staan, met een schatting in minuten transcriptie en wanneer
het tegoed vernieuwt. Start je een vergadering terwijl er minder dan 15%
over is, dan waarschuwt de app eerst — een uur opnemen kan een gratis
tegoed in één keer opsouperen, en dat merk je liever vooraf dan achteraf.

De minuten zijn nadrukkelijk een schatting: ElevenLabs publiceert geen
vaste verhouding tussen credits en seconden audio, dus die wordt afgeleid
en ook zo benoemd.

Kan de key het verbruik niet lezen, dan blijft het blok gewoon weg. Een
API-key die alleen spraak-naar-tekst mag, werkt prima om te dicteren maar
krijgt hier een 401; dat is geen fout om over te klagen.

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

**Opgelost: blanco pictogram in Start en op de taakbalk.** Werd de app
geïnstalleerd vanuit een verpakte (MSIX) omgeving, dan leidde Windows het
schrijven naar `AppData\Local` om naar een containermap. Het installeren
leek te lukken — de installer las zijn eigen bestand gewoon terug — maar
Explorer zag daar niets, dus verwees de snelkoppeling naar een doel dat
voor Windows niet bestond. De installer detecteert die omleiding nu met een
testbestand en wijkt uit naar een map die wel doorgelaten wordt. De
snelkoppeling verwijst bovendien naar een apart `.ico`-bestand in plaats
van naar een pictogramindex in een `.exe` van 50 MB.

Ook de indicator werd verborgen opgebouwd: hij zette zijn vensterstijl pas
na het aanmaken, waardoor Windows hem heel even als taakbalkknop
registreerde en er bij elke opname een leeg pictogram opflitste.

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
