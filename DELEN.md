# TalkWithMe — bouwprompt om te delen

Deze prompt bouwt de app opnieuw op, inclusief de dingen die pas na een dag
debuggen bleken te kloppen. Plak hem in Claude Code (of een vergelijkbare
agent met terminaltoegang) in een lege map.

---

## Vooraf nodig

- Windows 10 of 11
- Python 3.12 of nieuwer
- Een ElevenLabs API-key (spraak → tekst)
- Een Google Gemini API-key (opschonen, gratis tier volstaat)

---

## De prompt

Bouw een Windows-dicteerapp in Python. Ik houd Ctrl+Windows ingedrukt, ik praat,
ik laat los, en de uitgeschreven tekst verschijnt op mijn cursor — in elke app.

**Werking**

1. Low-level keyboard hook (ctypes op user32) vangt Ctrl+Win als hold-to-talk.
2. Opname start bij indrukken, stopt bij loslaten.
3. Audio gaat naar ElevenLabs Scribe v2 (`POST https://api.elevenlabs.io/v1/speech-to-text`,
   header `xi-api-key`, multipart met `model_id=scribe_v2`; transcript staat in `text`).
4. Het ruwe transcript gaat naar Gemini Flash om vullers, valse starts en
   zelfcorrecties te verwijderen en interpunctie te herstellen — zonder de
   betekenis of woordkeuze te veranderen.
5. Tekst gaat naar het klembord en wordt met Ctrl+V geplakt.

**Interface**

- Systeemvakicoon dat van kleur verandert: klaar, luistert, verwerkt.
- Zwevende indicator rechtsonder met een live waveform tijdens het spreken.
- Eén venster met drie tabbladen: Geschiedenis, Weekrapport, Instellingen.
- Geschiedenis toont elk dictaat, met een schakelaar tussen de opgeschoonde en
  de ruwe versie.
- Weekrapport toont hoeveel tijd dicteren bespaarde tegenover typen. Reken in
  woorden per minuut: typen op 40 wpm als aanname, spreektijd gemeten. Zet de
  aanname zichtbaar op het scherm.
- Instellingen: beide API-keys, een schakelaar "spraak opschonen", en de
  opschoon-instructies in een bewerkbaar tekstvak.

**Toon per app (optioneel maar leuk)**

Bepaal de toon uit het voorgrondvenster: chat-apps kort en informeel, e-mail
verzorgd, terminal letterlijk. Voor browsers bepaalt de venstertitel de toon,
want een Gmail-tab en een WhatsApp-tab zijn dezelfde .exe.

---

## Harde regels — hier ging het bij mij mis

Deze punten kostten me een dag. Neem ze letterlijk over.

**De hook mag nooit een toets tegenhouden.** Geef altijd `CallNextHookEx` terug,
voor elk event. Onderdruk in het bijzonder nooit de keyup van Win of Alt om het
Startmenu te vermijden: Windows denkt dan dat de modifier nog ingedrukt is, en
elke volgende toetsaanslag wordt een sneltoets in plaats van tekst. Je toetsenbord
lijkt kapot. Een flitsend Startmenu is minder erg.

**Vertrouw je eigen vlaggen niet.** Windows kan een keyup opslokken (bijvoorbeeld
wanneer het Startmenu de focus pakt). Controleer de echte toetsstatus met
`GetAsyncKeyState` en laat een watchdog elke 200 ms de staat herstellen. Zonder
dit start elke Ctrl-druk een opname en werkt Ctrl+V niet meer.

**Zet de ctypes-signaturen goed.** `LRESULT` is pointer-groot (64-bit), niet
`c_long`. Zet `argtypes` en `restype` expliciet voor `SetWindowsHookExW`,
`CallNextHookEx` en `UnhookWindowsHookEx`.

**De zwevende indicator mag nooit focus krijgen.** Zet `WS_EX_NOACTIVATE` en
`WS_EX_TOOLWINDOW` via `SetWindowLongW`. Anders verdwijnen je toetsaanslagen in
een onzichtbaar venstertje — niet te onderscheiden van een kapot toetsenbord.

**Open de microfoonstream vers bij elke opname.** Een stream die continu
openstaat leverde op mijn machine na een halve minuut alleen nog stilte, terwijl
een net geopende stream perfect opnam. Hold-to-talk past hier natuurlijk bij.

**Verlies nooit tekst.** Elk faalpad eindigt met de tekst op de cursor óf op het
klembord met een notificatie. Klembord openen faalt regelmatig omdat een andere
app hem vasthoudt: probeer het een paar keer opnieuw.

**Negeer je eigen toetsaanslagen.** Controleer `LLKHF_INJECTED`, anders ziet de
hook zijn eigen Ctrl+V en krijg je een lus.

**Controleer modelnamen live.** Modelnamen verlopen sneller dan documentatie
wordt bijgewerkt. Vraag de lijst op bij de provider in plaats van een naam uit
een blogpost over te nemen.

**API-keys in de Windows Credential Manager** (via `keyring`), nooit in code of
een configbestand.

---

## Kanttekeningen om te vermelden

- **Microsoft Store-apps** (de nieuwe Kladblok, sommige desktop-apps) weigeren
  gesimuleerde toetsaanslagen. Daar komt de tekst op het klembord terecht in
  plaats van op de cursor. Dat is een Windows-beperking, geen bug.
- **SmartScreen en antivirus** zullen waarschuwen bij een zelfgebouwde .exe. Een
  low-level keyboard hook plus toetsaanslagen simuleren is letterlijk wat een
  keylogger doet — dat je app het om goede redenen doet, ziet een scanner niet.
- **Kosten**: ElevenLabs rekent per minuut audio; Gemini Flash heeft een gratis
  tier die ruim volstaat voor persoonlijk gebruik.
- **De microfoon** wordt alleen geopend terwijl je de toetsen ingedrukt houdt.
