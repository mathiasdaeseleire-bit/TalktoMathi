# Fluister MVP — dicteren met Ctrl+Win

**Build-spec voor Claude Code** · Windows 10/11 · bouwtijd ± 1 dag

---

## Wat het is

Eén achtergrondprocesje in je systeemvak. Je tikt **Ctrl+Win**, je praat, je tikt
**Ctrl+Win** opnieuw, en er staat **geschreven** tekst op je cursor. Overal: WhatsApp,
Claude, Outlook, Slack, je terminal.

Het verschil met de dictatie die al in Windows zit:

| | Output |
|---|---|
| Windows Spraakherkenning | "hey eh kan je even eh laten weten of dat lukt vrijdag nee maandag" |
| Fluister | "Hey, kan je even laten weten of dat lukt maandag?" |

De euh's eruit, de zelfcorrectie toegepast, interpunctie erin, en de toon aangepast aan
de app waar je in staat. Dat is het hele product.

**Bewust niet in deze versie:** woordenboek, snippets, geschiedenis, statistieken,
tekstselectie transformeren, instellingen-venster, offline modus. Alles configureer je
in één YAML-bestand.

---

## 1. De trigger — Ctrl+Win als toggle

Ctrl+Win is een goede keuze: die combinatie doet op zichzelf niets in Windows, dus je
zit niemand in de weg. Er zijn drie dingen die je goed moet doen.

### Probleem 1: het Startmenu

Windows opent het Startmenu op de **keyup** van de Windows-toets, niet op de keydown.
Doe je niets, dan knalt bij elke dictatie het Startmenu open.

Oplossing: onderdruk in je hook de keyup van `VK_LWIN`/`VK_RWIN` **als die deel uitmaakte
van onze combinatie en er geen derde toets bij zat**. Microsoft beschrijft deze aanpak
zelf in hun documentatie over shortcut-onderdrukking in games. Dit werkt alleen met een
low-level hook — `RegisterHotKey` kan geen combinatie van alleen modifiers registreren,
en kan sowieso niets onderdrukken.

### Probleem 2: Ctrl+Win+D en vrienden mogen niet breken

Windows gebruikt Ctrl+Win+D (nieuw bureaublad), Ctrl+Win+←/→ (wisselen), Ctrl+Win+O
(schermtoetsenbord). Die moeten blijven werken.

Oplossing die beide problemen tegelijk oplost: **onderdruk de Win-keydown nooit.** Alleen
de keyup, en alleen als er tussen down en up geen enkele andere toets is aangeslagen.
Drukt iemand Ctrl+Win+D, dan is D al lang door Windows afgehandeld op de keydown, en
onderdrukken wij niets omdat er wél een derde toets was.

### Probleem 3: de hook zit in het pad van elke toetsaanslag

Duurt je callback te lang, dan gooit Windows je hook er stilletjes uit
(`LowLevelHooksTimeout`, standaard ~1 seconde) en werkt je trigger ineens niet meer.
Regel: in de callback gebeurt niets anders dan een vlag zetten en een event in een queue
duwen. Geen netwerk, geen disk, geen logging, geen `print`.

### De logica

```
Ctrl omlaag  → ctrl_down = True
Win  omlaag  → win_down = True; combo_clean = True
andere toets → combo_clean = False        (er zat een derde toets bij)
Win  omhoog  → als ctrl_down and combo_clean:
                   TOGGLE opname          (start als idle, stop als bezig)
                   return 1               ← keyup opslokken, geen Startmenu
               anders: doorlaten
ESC          → als opname bezig: annuleren, niets plakken
```

### De hook

```python
import ctypes, ctypes.wintypes as w, time

VK_LCTRL, VK_RCTRL, VK_CTRL = 0xA2, 0xA3, 0x11
VK_LWIN,  VK_RWIN           = 0x5B, 0x5C
VK_ESCAPE                   = 0x1B
WM_KEYDOWN, WM_KEYUP        = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP  = 0x0104, 0x0105
LLKHF_INJECTED              = 0x10

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", w.DWORD), ("scanCode", w.DWORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ctypes.POINTER(w.ULONG))]

state = {"ctrl": False, "win": False, "clean": False}

def hook_proc(nCode, wParam, lParam):
    if nCode != 0:
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents

    # Negeer onze eigen gesimuleerde toetsen (Ctrl+V), anders krijg je een lus
    if kb.flags & LLKHF_INJECTED:
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    vk   = kb.vkCode
    down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)

    if vk in (VK_LCTRL, VK_RCTRL, VK_CTRL):
        state["ctrl"] = down
    elif vk in (VK_LWIN, VK_RWIN):
        if down:
            state["win"], state["clean"] = True, True
        else:
            fire = state["ctrl"] and state["clean"]
            state["win"] = False
            if fire:
                queue.put("TOGGLE")       # alleen dit; werk gebeurt elders
                return 1                  # keyup opslokken → geen Startmenu
    elif down:
        state["clean"] = False            # derde toets: dit is Ctrl+Win+X, niet van ons
        if vk == VK_ESCAPE and session.active:
            queue.put("CANCEL")
            return 1

    return user32.CallNextHookEx(None, nCode, wParam, lParam)
```

De hook draait in een eigen thread met een message loop (`GetMessageW`). De worker die de
queue leegtrekt is een **andere** thread — daar gebeurt het echte werk.

> **Test dit als eerste, vóór je iets anders bouwt.** Of het Startmenu opkomt bij een
> losse Ctrl+Win verschilt per Windows-build en per toetsenbord-layout. Zoals hierboven
> geschreven is het afgedekt, maar controleer het op jouw machine binnen tien minuten na
> de start — het is het enige dat de trigger onbruikbaar kan maken.

### Twee dingen om te weten

- **Verhoogde vensters.** Draait je app niet als administrator, dan ziet je hook geen
  toetsen terwijl een venster dat *wel* als administrator draait de focus heeft (UIPI).
  Dicteer je in zulke apps, laat Fluister dan ook verhoogd starten. Voor gewoon gebruik
  is dat onnodig en onwenselijk.
- **Antivirus.** Een low-level keyboard hook plus toetsaanslagen simuleren is precies wat
  keyloggers doen. Defender laat het meestal door, sommige scanners niet. Reken op een
  SmartScreen-waarschuwing bij je eerste `.exe` en documenteer de uitzondering.

### Als het je tegenvalt

In `config.yaml` staat `trigger: ctrl_win`. Zonder codewijziging kan je switchen naar
`ctrl_alt`, `right_ctrl` (dubbeltik) of `f13`. Zet de trigger achter één interface met
vier implementaties, dan is wisselen een regel config.

---

## 2. Wat er gebeurt tussen tik en tekst

```
Ctrl+Win
   ↓
[1] opname start (audio liep al — zie §4.1)
   ↓  je praat
Ctrl+Win
   ↓
[2] welke app heeft focus  → welke toon
[3] audio → Whisper        → ruwe tekst
[4] ruwe tekst → LLM       → geschreven tekst in de toon van die app
[5] clipboard + Ctrl+V     → staat op je cursor
```

Doel: **onder 1,2 seconde** van de tweede tik tot tekst, bij een dictatie van 10
seconden. Haal je dat niet, dan gebruik je het na twee weken niet meer.

| Stap | ms |
|---|---|
| Whisper (Groq, LPU) | 200–400 |
| Polish-LLM | 300–500 |
| Upload + plakken | 150–250 |

Twee trucs die je gratis krijgt:
- **Pre-warm.** Bij het starten één dummy-request naar beide endpoints, zodat TLS en DNS
  al gedaan zijn. Herhaal na 60 s inactiviteit.
- **Sla polish over onder 4 woorden.** "ja doe maar" hoeft niet door een LLM. Scheelt
  400 ms bij de helft van je dictaties.

Toggle-modus heeft één eigen risico: **je vergeet te stoppen.** Bouw daarom in:
- een zichtbare indicator in het systeemvak (rood terwijl hij luistert),
- automatisch afronden na `max_duration_s`,
- automatisch stoppen na 3 seconden stilte (`silence_stop_s`, standaard aan bij toggle).

---

## 3. Stack en config

| | |
|---|---|
| Taal | Python 3.12 |
| Deps | `pywin32`, `sounddevice`, `numpy`, `httpx`, `pyyaml`, `keyring`, `pystray`, `Pillow`, `winotify` |
| Hook | rechtstreeks via `ctypes` op `user32` — geef je meer controle dan `keyboard` of `pynput` |
| STT | Groq, Whisper-turbo (~$0,04 per uur audio) |
| Polish | Groq, snel tekstmodel |
| UI | Systeemvak-icoon dat van kleur verandert. Meer niet. |

Model-ID's veranderen elk kwartaal — laat de agent ze bij de start uit de provider-docs
halen in plaats van uit dit document.

### `%USERPROFILE%\.fluister\config.yaml`

```yaml
trigger: ctrl_win              # of: ctrl_alt | right_ctrl | f13
mode: toggle                   # toggle | hold
max_duration_s: 300
silence_stop_s: 3              # automatisch stoppen bij stilte; null = uit
language: auto                 # auto | nl | en — expliciet is accurater

polish:
  enabled: true
  skip_under_words: 4

# Toon per app. Exe-naam (kleine letters) → toon.
tones:
  whatsapp.exe:        chat
  slack.exe:           chat
  ms-teams.exe:        chat
  claude.exe:          prompt
  cursor.exe:          prompt
  code.exe:            prompt
  outlook.exe:         email
  olk.exe:             email        # nieuwe Outlook
  windowsterminal.exe: verbatim
  powershell.exe:      verbatim
  cmd.exe:             verbatim

# Browsers: de venstertitel bepaalt de toon (zie §4.3)
title_tones:
  "WhatsApp":  chat
  "Gmail":     email
  "Outlook":   email
  "Claude":    prompt
  "ChatGPT":   prompt
  "Slack":     chat

# Apps waar Ctrl+V niet werkt maar Ctrl+Shift+V wel
paste_keys:
  windowsterminal.exe: ctrl+shift+v

apps_disabled: []              # exe-namen waar de trigger uit moet
```

API-keys via `keyring` in de Windows Credential Manager. Nooit in dit bestand.

---

## 4. De vier stukken code die aandacht vragen

### 4.1 Audio met pre-roll

De klacht die iedereen heeft over dicteerapps: "hij mist mijn eerste woord." Oorzaak: de
microfoonstream wordt pas geopend bij de trigger, wat 100–300 ms kost — meer met een
Bluetooth-headset.

Oplossing: laat de stream **altijd** draaien in een ringbuffer van 800 ms. Bij de trigger
markeer je alleen het startpunt en pak je het verleden mee.

```python
class Recorder:
    def __init__(self, rate=16000, preroll_ms=800):
        self.ring = np.zeros(int(rate * preroll_ms / 1000), dtype=np.int16)
        self.stream = sd.InputStream(samplerate=rate, channels=1, dtype='int16',
                                     blocksize=512, callback=self._cb)
        self.stream.start()                  # draait vanaf app-start

    def _cb(self, indata, frames, t, status):
        self.ring_write(indata[:, 0])        # houd dit onder 1 ms
        if self.recording:
            self.chunks.append(indata[:, 0].copy())

    def start(self):
        self.chunks = [self.ring_read_all()] # pre-roll als eerste chunk
        self.recording = True
```

Windows-specifiek: als je een headset koppelt of loskoppelt sterft de stream. Vang
`PortAudioError` op, wacht 500 ms en open opnieuw met het huidige standaardapparaat. Doe
dat stil, zonder foutmelding — de gebruiker merkt het dan niet.

Zet in je README dat de mic dus continu open staat maar dat er buiten een sessie niets
wordt weggeschreven of verstuurd, en bouw een echte "mic uit"-optie in het systeemvakmenu
die de stream sluit. Dat is niet cosmetisch, dat is eerlijk zijn.

### 4.2 Tekst op de cursor krijgen

Clipboard vullen en `Ctrl+V` simuleren via `SendInput`. Dat werkt overal, ook in
Electron-apps waar directe tekstinvoer faalt.

```python
import win32clipboard as cb, win32con, ctypes, time, threading

def insert_text(text: str, exe: str):
    saved = save_clipboard()                 # zie hieronder
    cb.OpenClipboard(); cb.EmptyClipboard()
    cb.SetClipboardData(win32con.CF_UNICODETEXT, text)
    cb.CloseClipboard()

    keys = PASTE_KEYS.get(exe, ("ctrl", "v"))
    send_key_combo(keys)                     # SendInput, KEYEVENTF_KEYUP netjes afsluiten

    def restore():
        time.sleep(0.15)                     # korter en trage apps plakken de oude inhoud
        restore_clipboard(saved)
    threading.Thread(target=restore, daemon=True).start()
```

Details die je anders een halve dag kosten:

- **Clipboard openen faalt regelmatig.** Een andere app kan hem vasthouden. Wikkel
  `OpenClipboard` in een retry: 5 pogingen met 20 ms ertussen, daarna opgeven en de tekst
  in een notificatie tonen.
- **Bewaar meer dan platte tekst.** Loop met `EnumClipboardFormats` over de aanwezige
  formats en bewaar minstens `CF_UNICODETEXT` en HTML. Afbeeldingen en bestandslijsten
  zijn handles die je niet triviaal terugzet — accepteer dat, maar meld het in de README
  zodat niemand denkt dat zijn screenshot spontaan verdween.
- **Ken de uitzonderingen op Ctrl+V.** Windows Terminal en veel SSH-clients gebruiken
  Ctrl+Shift+V. Vandaar `paste_keys` in de config.
- **Negeer je eigen toetsen.** Je hook ziet de `Ctrl+V` die je zelf stuurt. Zonder de
  `LLKHF_INJECTED`-check uit §1 krijg je een lus.
- **Vangnet als plakken geblokkeerd is** (wachtwoordvelden, RDP, sommige games): typ de
  tekst met `SendInput` en `KEYEVENTF_UNICODE`, in blokjes van ~20 tekens met 5 ms ertussen.
  Trager en zichtbaar, maar het werkt waar plakken faalt.
- **Venster gewisseld tijdens verwerking?** Onthoud bij de start de HWND. Klopt die bij
  het plakken niet meer: tekst in het clipboard laten plus notificatie, en niet plakken.
  Blind plakken in het verkeerde venster kost je in één keer al het vertrouwen.

### 4.3 Weten in welke app je zit

```python
import win32gui, win32process, psutil

hwnd  = win32gui.GetForegroundWindow()
title = win32gui.GetWindowText(hwnd)
_, pid = win32process.GetWindowThreadProcessId(hwnd)
exe   = psutil.Process(pid).name().lower()   # "whatsapp.exe"
```

Zit je in een browser (`chrome.exe`, `msedge.exe`, `firefox.exe`), dan bepaalt de
**venstertitel** de toon. Dat is de simpele route en hij werkt verrassend goed: een
Gmail-tab heet "Postvak IN – naam@… – Gmail", een WhatsApp-tab begint met "WhatsApp".
Match de sleutels uit `title_tones` als substring, hoofdletterongevoelig, eerste match
wint. Geen match → `default`.

Wil je later echt de URL: dat kan via UI Automation (`uiautomation`-package) door de
waarde van de adresbalk te lezen. Kost ~100 ms per call en is fragiel bij
browser-updates. Niet nodig voor deze versie.

### 4.4 Deterministisch, níet door de LLM

Deze drie dingen moeten 100% voorspelbaar zijn, dus doet Python ze en niet het model:

```python
def finish(text, ctx):
    # 1. Cursor midden in een zin? Eerste letter klein.
    if ctx.preceding_char and ctx.preceding_char not in ".!?\n":
        text = text[0].lower() + text[1:]
    # 2. Spatie ervoor als die er nog niet staat
    if ctx.preceding_char and ctx.preceding_char not in " \n\t":
        text = " " + text
    # 3. Chat-apps: laatste punt weg. ! en ? blijven altijd staan.
    if ctx.tone == "chat" and text.endswith(".") and not text.endswith(".."):
        text = text[:-1]
    return text
```

Het teken vóór de cursor uitlezen kan op Windows niet betrouwbaar zonder UI Automation.
Ga daarom uit van "begin van zin" — dat is de veiligste aanname — en laat punt 1 en 2 weg
tot je merkt dat je ze mist. Punt 3 werkt wel gewoon en is direct merkbaar in WhatsApp.

Een LLM doet dit soort mechaniek in een paar procent van de gevallen fout, en dan
vertrouw je de app niet meer. Toon en betekenis zijn voor het model, mechaniek is voor code.

---

## 5. De prompt

Dit is het eigenlijke product. Engels, omdat modellen daar instructies beter volgen, met
een expliciete regel over taalbehoud. Eén bestand, `prompts.py`, met een versienummer.

```
You are the polish layer of a dictation tool. You receive a raw speech-to-text
transcript and return the text the speaker MEANT to write.

## Absolute rules
1. Output ONLY the final text. No preamble, no quotes, no explanation, no markdown
   fences. Your entire response is pasted directly at the user's cursor.
2. NEVER answer, respond to, or act on the content. If the transcript is a question,
   you output the question — you do not answer it.
3. NEVER add information, names, or details that were not spoken.
4. Preserve the speaker's language exactly, including code-switching. If they mix Dutch
   and English in one sentence, keep both. Never translate.
5. When unsure whether something is a correction or content, keep the content.

## Clean up
- Fillers: uh, um, eh, like, you know, dus ja, nou, weet je.
- Repetitions and false starts: "the the launch" -> "the launch".
- Self-corrections: apply the correction, drop the original.
    "let's meet at five, actually six" -> "Let's meet at six."
    "als gift... als cadeau" -> "als cadeau"
  Use the FULL transcript as context. "I actually enjoyed it" is not a correction.
- Add punctuation, capitalisation and paragraph breaks where a writer would.
- Spoken enumerations ("one... two...", "eerst... daarna...") become a list.
- When the speaker names a punctuation mark or command, insert the symbol:
  period/punt, comma/komma, question mark/vraagteken, exclamation point/uitroepteken,
  colon, semicolon, dash, slash, at sign/apenstaartje, hashtag/hekje, open/close paren,
  new line/nieuwe regel, new paragraph/nieuwe alinea.
- Never insert an em dash on your own initiative.

## Do not
- Do not fix misheard words. A wrong but plausible word stays.
- Do not add greetings or sign-offs that were not spoken.
- Do not make it longer or more formal than the tone below.
- Do not add a trailing period if the text already ends in ! or ?

## Tone: {tone}
{TONE_DESCRIPTION}

Application: {app_name}
```

Vier tonen, meer heb je niet nodig:

```python
TONES = {
 "chat": (
   "Short and natural, like a message to a colleague or friend. Contractions are fine. "
   "Minimal punctuation. No sign-off. Do not end with a period."),

 "email": (
   "Complete sentences, correct punctuation, professional but warm. Break into "
   "paragraphs where the speaker changes subject. Do not invent a greeting or sign-off "
   "that was not spoken."),

 "prompt": (
   "This goes into an AI assistant. Prioritise clarity and precision over politeness. "
   "Keep every technical term, file name, and identifier exactly as spoken. Structure "
   "multi-part requests as a list. Never soften or shorten an instruction."),

 "verbatim": (
   "A terminal or code editor. Transcribe faithfully. Remove fillers and fix obvious "
   "punctuation, nothing else. Never restructure or rephrase. Convert spoken syntax: "
   "'dash m' -> -m, 'dot py' -> .py, 'slash' -> /, 'backslash' -> \\."),

 "default": (
   "Clear written prose. Natural and direct, correct punctuation, no filler."),
}
```

Stuur vier few-shot voorbeelden mee, niet meer — elk voorbeeld kost latency:

```
Input:  eh dus ik denk dat we eh de deadline moeten verschuiven naar niet vrijdag maar maandag
Output: Ik denk dat we de deadline moeten verschuiven naar maandag.

Input:  hey kan je even kijken of dat lukt vanmiddag          [tone: chat]
Output: Hey, kan je even kijken of dat lukt vanmiddag?

Input:  so I told the team dat de deadline verschuift naar maandag
Output: So I told the team dat de deadline verschuift naar maandag.

Input:  git commit dash m fix de null pointer in het auth veld  [tone: verbatim]
Output: git commit -m "fix de null pointer in het auth veld"
```

Praktisch:
- `temperature: 0.2`. Hoger en dezelfde dictatie geeft elke keer iets anders, wat
  onbetrouwbaar voelt.
- Houd de system prompt kort. Elke 500 tokens kost je ~30 ms.
- Versienummer bij elke prompt (`PROMPT_VERSION = "1.0"`). Zakt de kwaliteit ineens, dan
  weet je waarom.

---

## 6. Bouwvolgorde

Drie stappen. Commit na elke stap.

### Stap 1 — de lus (halve dag)

Hook met toggle-logica, audio met pre-roll, Whisper-call, plakken. Nog geen polish, nog
geen tonen.

**Klaar als:**
- Ctrl+Win in Kladblok, praten, Ctrl+Win → ruwe tekst staat er binnen 1,5 s
- **het Startmenu komt niet op** — test dit als allereerste
- Ctrl+Win+D maakt nog steeds een nieuw bureaublad, Ctrl+Win+←/→ wisselt nog
- normaal typen voelt onveranderd
- ESC tijdens opname plakt niets
- stilte opnemen plakt niets
- je clipboard is achteraf zoals het was (tekst in elk geval)
- de hook overleeft 30 minuten normaal typen zonder eruit te vallen

### Stap 2 — de polish (halve dag)

App-detectie, tonen, prompt, en de afwerking uit §4.4.

**Klaar als** deze zes goed gaan:

| Gesproken | Verwacht |
|---|---|
| "eh dus ja ik denk dat we maandag moeten starten" | "Ik denk dat we maandag moeten starten." |
| "laten we om vijf uur afspreken eigenlijk om zes uur" | "Laten we om zes uur afspreken." |
| in WhatsApp: "prima doe ik" | "prima doe ik" — geen punt |
| in Outlook: "hoi tom bedankt voor je bericht ik kijk er maandag naar" | Nette zinnen met interpunctie |
| in Claude: "kan je die functie herschrijven zodat hij async is" | Instructie intact, niks weggepoetst |
| in Windows Terminal: "git status" | "git status" — niet "Git status." |

Log bij elk transcript de tijden (`stt_ms`, `polish_ms`, `total_ms`) naar een logbestand.
Is p95 boven de 2 s, ga dan niet verder maar optimaliseer eerst.

### Stap 3 — leefbaar maken (halve dag)

- Systeemvak-icoon: grijs = klaar, rood = luistert, geel = verwerkt. Bij toggle-modus is
  dit geen luxe maar noodzaak — het is je enige signaal dat hij nog opneemt.
- Automatisch stoppen bij stilte en bij `max_duration_s`
- Pre-warm bij start en na 60 s idle
- Fallbacks: polish faalt → ruwe tekst plakken · plakken faalt → clipboard + notificatie ·
  netwerk weg → notificatie vóór de opname begint
- Automatisch starten bij inloggen: snelkoppeling in `shell:startup`, of een waarde onder
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- `PyInstaller --noconsole --onefile`. Reken op een SmartScreen-waarschuwing bij de eerste
  start en op mogelijke antivirus-meldingen vanwege de keyboard hook.

---

## 7. Foutafhandeling

Eén regel: **verlies nooit de woorden van de gebruiker.** Elk faalpad eindigt met de
tekst op de cursor of op het clipboard met een notificatie.

| Situatie | Gedrag |
|---|---|
| Polish faalt of timeout (6 s) | Ruwe transcriptie plakken |
| STT faalt | Notificatie, audio 60 s bewaren zodat je kan retryen |
| Clipboard niet te openen | 5× retry, daarna tekst in een notificatie |
| Plakken faalt | Clipboard + notificatie "staat op je klembord" |
| Venster gewisseld | Clipboard + notificatie, niet plakken |
| Geen spraak | Stil niets doen, geen foutmelding |
| Langer dan `max_duration_s` | Automatisch afronden en verwerken |
| Audioapparaat verdwenen | Stream stil opnieuw openen |
| Hook eruit gegooid door Windows | Detecteren en opnieuw installeren, notificatie |

---

## 8. `CLAUDE.md`

```markdown
# Fluister — werkinstructies

Dicteerapp voor Windows. Ctrl+Win → praten → Ctrl+Win → gepolijste tekst op de cursor.
Volledige spec in FLUISTER_MVP.md. Lees die eerst.

## Werkwijze
Werk per stap uit §6. Bouw niets uit een latere stap. Stop bij de acceptatiecriteria en
rapporteer wat je getest hebt. Vraag niets wat in de spec staat.

## Harde regels
- De hook-callback zit in het pad van elke toetsaanslag. Geen netwerk, geen disk, geen
  logging, geen sleep, geen print. Te traag = Windows gooit je hook eruit.
- In de callback alleen een vlag zetten en iets in de queue duwen. Werk gebeurt in een
  andere thread.
- Altijd LLKHF_INJECTED checken, anders zie je je eigen Ctrl+V en krijg je een lus.
- Onderdruk de Win-KEYDOWN nooit, alleen de KEYUP, en alleen zonder derde toets.
- Geen faalpad mag tekst verliezen: cursor of clipboard, altijd.
- Capitalisatie, spaties en de trailing punt horen in Python, niet in de prompt.
- Prompts alleen in prompts.py, met PROMPT_VERSION.
- API-keys via keyring, nooit in config of code.

## Valkuilen (uitgebreid in de spec)
- Het Startmenu opent op de keyup van de Win-toets. §1 lost dit op. Test het eerst.
- Ctrl+Win+D en Ctrl+Win+pijltjes moeten blijven werken.
- OpenClipboard faalt regelmatig omdat een andere app hem vasthoudt: retryen.
- Windows Terminal plakt met Ctrl+Shift+V, niet Ctrl+V.
- Zonder verhoogde rechten ziet de hook niets in vensters die als admin draaien.

## Commando's
Draaien: `python -m fluister --debug`
Logs:    `type %USERPROFILE%\.fluister\fluister.log`
Bouwen:  `pyinstaller fluister.spec`
```

---

## 9. Als je later meer wil

Deze versie is expres klein. De dingen die je waarschijnlijk als eerste gaat missen, in
de volgorde waarin mensen ze missen:

1. **Een klein zwevend venstertje** dat laat zien dat hij luistert en meebeweegt met je
   stem. Bij toggle-modus dubbel nuttig, want je hebt geen toets die je vasthoudt als
   herinnering.
2. **Een woordenlijst** met je eigen namen en jargon, meegestuurd als Whisper-prompt.
   Een uurtje werk, direct merkbaar.
3. **Tekst selecteren en met je stem laten herschrijven** — Wispr's Command Mode.

Alle drie staan uitgewerkt in de uitgebreide spec. Bouw ze pas als je deze versie een
week echt gebruikt hebt — dan weet je welke je écht mist in plaats van welke leuk klinkt.
