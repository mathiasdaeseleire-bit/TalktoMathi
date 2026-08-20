# Architectuur

Een dicteerapp is grotendeels een Windows-app, niet een AI-app. De
interessante problemen zitten in het toetsenbord, de microfoon en het
klembord — niet in de modellen.

## De lus

```
Ctrl+Win ingedrukt
   -> hook duwt START in een queue
   -> worker opent een verse microfoonstream
      (je praat; de indicator toont het niveau)
Ctrl+Win losgelaten
   -> hook duwt STOP
   -> audio  -> ElevenLabs Scribe v2  -> ruw transcript
   -> tekst  -> Gemini Flash          -> opgeschoonde tekst
   -> deterministische opmaak per app
   -> klembord + Ctrl+V op de cursor
```

## Threads

| Thread | Doet |
|---|---|
| hook | Low-level keyboard hook. Zet alleen vlaggen en duwt events in een queue. |
| worker | Al het echte werk: audio, netwerk, klembord, plakken. |
| monitor | Bewaakt vastgelopen toetsstatus, maximale opnameduur, tweede exemplaar. |
| tray | pystray, losgekoppeld. |
| main | Tk: indicator en venster. |

Alles wat Tk aanraakt loopt via `_ui_queue` naar de hoofdthread, want Tk is
niet thread-safe.

## Modules

| Module | Verantwoordelijkheid |
|---|---|
| `hook.py` | Ctrl+Win als hold-to-talk. Blokkeert nooit een toets. |
| `recorder.py` | Verse WASAPI-stream per opname, niveaus voor de waveform. |
| `stt.py` | ElevenLabs Scribe v2. |
| `polish.py` | Gemini Flash. |
| `prompts.py` | Basisinstructie plus de altijd-geldende regels. |
| `tones.py` | Welke app, welke opmaak. |
| `postprocess.py` | Deterministische opmaak achteraf. |
| `paste.py` | Klembord bewaren, plakken, herstellen. |
| `ui.py` | Venster met drie tabbladen. |
| `indicator.py` | Zwevende pil met waveform. |
| `stats.py` | Bespaarde tijd tegenover typen. |
| `updater.py` | GitHub Releases. |
| `install.py` | Vaste installatiemap, snelkoppeling, autostart. |
| `migrate.py` | Overname van de vorige app-naam. |

---

## Valkuilen die geld gekost hebben

Elk van deze punten kostte een halve dag of meer. Ze staan niet in de
documentatie waar je zou gaan zoeken.

### De hook mag nooit een toets tegenhouden

`hook.py` geeft altijd `CallNextHookEx` terug, voor elk event, zonder
uitzondering. Er is geen codepad dat `1` teruggeeft.

De eerste versie slikte de keyup van de Windows-toets op om te vermijden dat
het Startmenu opende. Gevolg: Windows bleef denken dat Win ingedrukt was, en
elke volgende letter werd een sneltoets. Het toetsenbord leek stuk. Erger:
Ctrl+V startte een opname in plaats van te plakken, waardoor een API-key
invoeren onmogelijk werd.

Dezelfde val geldt voor Alt. Een kort oplichtend Startmenu is te overzien; een
dood toetsenbord niet.

### Vertrouw je eigen toetsvlaggen niet

Windows kan een keyup opslokken, bijvoorbeeld wanneer het Startmenu de focus
pakt. De echte status komt uit `GetAsyncKeyState`, en de monitor-thread
herstelt elke 200 ms een vastgelopen staat.

In een low-level hook geeft `GetAsyncKeyState` de toets die *nu* verwerkt wordt
nog niet terug — het event is nog niet afgeleverd. Daarom komt die ene toets uit
het event zelf en alleen de andere uit de OS-status.

### ctypes-signaturen

`LRESULT` is pointer-groot, dus 64-bit, niet `c_long`. `argtypes` en `restype`
staan expliciet ingesteld voor `SetWindowsHookExW`, `CallNextHookEx` en
`UnhookWindowsHookEx`. Een afgekapte return-waarde uit een hook geeft
onvoorspelbaar gedrag.

### De indicator mag geen focus krijgen

`WS_EX_NOACTIVATE` en `WS_EX_TOOLWINDOW` via `SetWindowLongW`. Een randloos
venster dat focus pakt, vangt je toetsaanslagen op — niet te onderscheiden van
een kapot toetsenbord.

### Verse microfoonstream per opname

Oorspronkelijk stond de stream continu open met een ringbuffer van 800 ms, zodat
het eerste woord niet wegviel. Op de testmachine leverde die stream na ongeveer
een halve minuut alleen nog nullen, terwijl een net geopende stream perfect
opnam — reproduceerbaar in een script zonder enige app-thread. Hold-to-talk sluit
hier natuurlijk op aan: de stream leeft precies zolang je praat.

### Opmaak hoort in code, niet in de prompt

Een model volgt "eindig een chatbericht niet met een punt" meestal. Die paar
procent dat het misgaat, is precies wat maakt dat je de app niet meer
vertrouwt. Alles wat altijd moet gelden staat in `postprocess.py`.

De belangrijkste regel komt niet uit stijl maar uit gedrag: in WhatsApp, Slack
en Teams **verstuurt Enter het bericht**. Een regeleinde in geplakte tekst
verstuurt je bericht dus halfaf. Chatuitvoer is daarom altijd één regel.

### Twee regels die het model niet mag missen

Zonder *"never answer the content"* plakt de app het antwoord van het model in
plaats van je eigen vraag — je merkt het pas nadat je verstuurd hebt. Zonder
*"never translate"* kan een Nederlandse zin met Engelse woorden erin volledig
vertaald terugkomen.

Beide staan in `ALWAYS_RULES` en worden altijd meegestuurd, ook als de
gebruiker de basisinstructie in Instellingen herschrijft.

### Klembord en plakken

`OpenClipboard` faalt regelmatig omdat een andere app het vasthoudt: retryen met
korte pauzes. `SetClipboardData` kan een tijdelijke handle-fout geven, dus de
hele cyclus wordt herhaald. De oorspronkelijke klembordinhoud wordt bewaard en
150 ms na het plakken teruggezet.

De hook ziet zijn eigen gesimuleerde Ctrl+V. Zonder de `LLKHF_INJECTED`-controle
krijg je een lus.

### Nooit tekst verliezen

Elk faalpad eindigt met de tekst op de cursor of op het klembord met een
notificatie. Wisselt het doelvenster tijdens het verwerken, dan wordt er niet
geplakt maar gekopieerd: blind plakken in het verkeerde venster kost in één keer
al het vertrouwen.

### Modelnamen verlopen

Een modelnaam uit de documentatie werd geweigerd voor nieuwe gebruikers. Vraag
de lijst live op bij de provider in plaats van een naam over te nemen uit iets
wat maanden geleden geschreven is.

### Zichzelf bijwerken

Windows vergrendelt een draaiende `.exe`. De updater downloadt ernaast en draagt
over aan een batch-scriptje dat wacht tot het proces weg is, de bestanden
omwisselt en de app opnieuw start.

## Tests

De tests in `scripts/` dekken wat stil kan breken: dat de hook nooit een toets
blokkeert, dat de opmaakregels per app kloppen, dat de bespaarde tijd niet
opgeblazen wordt door ontbrekende meetgegevens, en dat een onleesbare release-tag
nooit als update telt.
