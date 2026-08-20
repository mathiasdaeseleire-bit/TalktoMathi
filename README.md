# TalkWithMe

Dicteren op Windows. Houd **Ctrl + Windows** ingedrukt, praat, laat los — de
uitgeschreven tekst verschijnt op je cursor. In WhatsApp, in Outlook, in je
terminal, overal.

| | |
|---|---|
| Wat je zegt | `eh dus ik denk dat we de deadline moeten verschuiven naar vrijdag nee maandag` |
| Wat er verschijnt | `Ik denk dat we de deadline moeten verschuiven naar maandag.` |

De vullers eruit, de zelfcorrectie toegepast, interpunctie erin — en de opmaak
afgestemd op de app waarin je typt.

---

## Hoe het werkt

1. Een low-level keyboard hook vangt Ctrl+Win als *hold-to-talk*.
2. De opname start bij indrukken en stopt bij loslaten.
3. De audio gaat naar **ElevenLabs Scribe v2** voor de transcriptie.
4. Het ruwe transcript gaat naar **Gemini Flash** om vullers, valse starts en
   zelfcorrecties te verwijderen.
5. De tekst wordt op je cursor geplakt.

## Opmaak per app

Dezelfde woorden horen er anders uit te zien afhankelijk van waar ze terechtkomen.
De regels volgen uit wat de doel-app met de tekst *doet*, niet uit smaak:

| App | Wat er gebeurt | Gevolg voor de opmaak |
|---|---|---|
| WhatsApp, Slack, Teams | Enter verstuurt | Altijd één regel, geen afsluitende punt, geen aanhef |
| Outlook, Gmail | Lege regels zijn alinea's | Alinea's bij onderwerpwissel, gesproken aanhef op eigen regel |
| Word, Notion, Docs | Wordt op een pagina gelezen | Lopende alinea's, opsommingen als lijst |
| Jira, Linear, GitHub | Iemand moet ermee aan de slag | Kern eerst, stappen als lijst, identifiers letterlijk |
| Claude, ChatGPT, editors | Wordt door een machine gelezen | Bestandsnamen en termen letterlijk, instructies genummerd |
| Terminal | Enter voert uit | Één regel, geen punt, nooit herformuleren |

Uitschakelbaar via het systeemvakmenu; de instructies per toon zijn aanpasbaar
in Instellingen.

---

## Installeren

Je hebt Windows 10 of 11 nodig, Python 3.12 of nieuwer, en twee API-keys.

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\pyinstaller talkwithme.spec
dist\TalkWithMe.exe --install
```

`--install` zet de app in `%LOCALAPPDATA%\Programs\TalkWithMe`, maakt een
Start-menu-snelkoppeling en zet automatisch starten bij inloggen aan.

Vastmaken aan de taakbalk gaat handmatig: Start openen, *TalkWithMe* typen,
rechtsklikken, **Aan taakbalk vastmaken**. Windows staat programma's niet toe
zichzelf vast te maken.

### API-keys

Open **Instellingen** vanuit het systeemvakmenu en plak ze daar. Ze worden
opgeslagen in de Windows Credential Manager, nooit in een bestand.

- ElevenLabs, voor spraak naar tekst: <https://elevenlabs.io/app/settings/api-keys>
- Google Gemini, voor het opschonen: <https://aistudio.google.com/apikey>

Zonder Gemini-key werkt de app gewoon door en plakt hij de ruwe transcriptie.

---

## Gebruik

| Actie | Wat er gebeurt |
|---|---|
| Ctrl+Win ingedrukt houden | Opname loopt, indicator rechtsonder toont je stem |
| Loslaten | Verwerken en plakken |
| Escape tijdens opname | Annuleren, er wordt niets geplakt |
| Klik op het systeemvakicoon | Het venster opent |

Het venster heeft drie tabbladen: **Geschiedenis** (elk dictaat, met een
schakelaar tussen opgeschoonde en ruwe tekst), **Weekrapport** (hoeveel tijd
dicteren bespaarde tegenover typen) en **Instellingen**.

---

## Bekende beperkingen

**Microsoft Store-apps weigeren gesimuleerde toetsaanslagen.** In onder meer de
nieuwe Kladblok komt je tekst op het klembord terecht in plaats van op je cursor,
met een melding erbij. Dat is een beveiligingsgrens van Windows, geen bug die
hier op te lossen valt.

**Je virusscanner kan aanslaan.** Een low-level keyboard hook die ook
toetsaanslagen simuleert is technisch niet te onderscheiden van een keylogger.
Reken op een SmartScreen-waarschuwing bij een zelfgebouwde `.exe`.

**Kosten.** ElevenLabs rekent per minuut audio. De gratis tier van Gemini Flash
volstaat ruim voor persoonlijk gebruik.

**Privacy.** De microfoon gaat alleen open zolang je de toetsen ingedrukt houdt.
Audio gaat naar ElevenLabs, de transcriptie naar Google. De geschiedenis blijft
lokaal in `%USERPROFILE%\.talkwithme\history.jsonl`.

---

## Ontwikkelen

```bash
venv\Scripts\python -m talkwithme --debug     # draaien met logging op de console
for %f in (scripts\test_*.py) do venv\Scripts\python %f
```

Zie [ARCHITECTUUR.md](ARCHITECTUUR.md) voor hoe het in elkaar zit en welke
valkuilen er in de Windows-API's zitten, [DELEN.md](DELEN.md) voor de bouwprompt
waarmee je de app zelf opnieuw kunt laten bouwen, en [CHANGELOG.md](CHANGELOG.md)
voor wat er per versie veranderde.

## Licentie

MIT — zie [LICENSE](LICENSE).
