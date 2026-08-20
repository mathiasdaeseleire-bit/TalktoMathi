# TalkWithMe — werkinstructies

Dicteerapp voor Windows. Ctrl+Win vasthouden, praten, loslaten, tekst op de
cursor. Lees `ARCHITECTUUR.md` voor de opbouw en de valkuilen; die staan er
uitgewerkt met de reden erbij.

`FLUISTER_MVP_WINDOWS.md` en `FLUISTER_SPEC.md` zijn de oorspronkelijke spec
waar dit uit voortkomt. Ze beschrijven een oudere opzet (toggle in plaats van
hold-to-talk, Groq in plaats van ElevenLabs) en zijn achtergrond, geen
waarheid over de huidige code.

## Providers
- **STT:** ElevenLabs Scribe v2 (`model_id=scribe_v2`, header `xi-api-key`).
- **Opschonen:** Gemini Flash via `gemini-flash-lite-latest`.

Gebruik de `-latest`-alias, geen vast versienummer: modellen worden sneller
uitgefaseerd dan dit bestand wordt bijgehouden. Vermijd `gemini-flash-latest`
zonder `-lite` — dat is een thinking-model dat te traag is voor dictatie.
Controleer bij twijfel live bij de provider in plaats van in documentatie.

## Harde regels

- **De hook blokkeert nooit een toets.** `hook.py` geeft altijd
  `CallNextHookEx` terug. Er mag geen codepad ontstaan dat `1` teruggeeft.
  Onderdruk nooit de keyup van Win of Alt: dat laat Windows denken dat de
  modifier nog ingedrukt is en maakt typen onmogelijk.
- **In de callback alleen vlaggen zetten en iets in de queue duwen.** Geen
  netwerk, geen disk, geen logging, geen sleep, geen print. Te traag betekent
  dat Windows de hook eruit gooit.
- **Altijd `LLKHF_INJECTED` checken**, anders ziet de hook zijn eigen Ctrl+V.
- **Toetsstatus komt uit `GetAsyncKeyState`**, niet uit eigen vlaggen alleen.
- **De indicator mag geen focus krijgen** (`WS_EX_NOACTIVATE`).
- **Verse microfoonstream per opname.** Een continu open stream viel stil.
- **Geen faalpad mag tekst verliezen:** cursor of klembord, altijd.
- **Opmaak die altijd moet gelden hoort in `postprocess.py`**, niet in de
  prompt. Een model doet dat een paar procent van de tijd fout, en dat is
  precies genoeg om de app niet meer te vertrouwen.
- **`ALWAYS_RULES` in `prompts.py` is niet optioneel.** Zonder die regels
  beantwoordt het model de gedicteerde tekst of vertaalt het hem.
- **API-keys via keyring**, nooit in config of code.

## Tests

```
for %f in (scripts\test_*.py) do venv\Scripts\python %f
```

Schrijf bij elke wijziging aan de hook een test die bewijst dat er geen toets
geblokkeerd wordt.

## Commando's

| | |
|---|---|
| Draaien met logging | `venv\Scripts\python -m talkwithme --debug` |
| Keys instellen | via Instellingen in de app, of `--set-elevenlabs-key` / `--set-gemini-key` |
| Key-status | `venv\Scripts\python -m talkwithme --show-key-status` |
| Bouwen | `venv\Scripts\pyinstaller talkwithme.spec` |
| Installeren | `dist\TalkWithMe.exe --install` |
| Logs | `type %USERPROFILE%\.talkwithme\talkwithme.log` |

## Release

1. Verhoog `__version__` in `talkwithme/__init__.py`.
2. Werk `CHANGELOG.md` bij.
3. Bouw, en publiceer een GitHub-release met tag `vX.Y.Z` en `TalkWithMe.exe`
   als asset. De asset moet exact zo heten, anders vindt de updater hem niet.
