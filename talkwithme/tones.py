"""Per-app formatting: a WhatsApp message and a client email are not the
same text, even when the speaker said exactly the same words.

The rules below are derived from what the destination does with the text
rather than from taste. Chat clients send on Enter, so a chat message is
one line and carries no sign-off. Mail clients render blank lines as
paragraphs, so an email gets structure. A terminal executes what it gets,
so nothing may be rephrased. An AI prompt is read by a machine, so
identifiers must survive verbatim and multi-part requests need numbering.

This is an opt-in override of one line in the default cleanup
instructions ("do not change the speaker's tone, wording, or level of
formality"). With tone adaptation off, that instruction stands untouched.

Which tone applies is read from the foreground window: the executable
name normally, or the window title when that executable is a browser,
since a Gmail tab and a WhatsApp Web tab are the same .exe.
"""
from __future__ import annotations

BROWSER_EXES = {
    "chrome.exe", "msedge.exe", "firefox.exe",
    "brave.exe", "opera.exe", "vivaldi.exe", "arc.exe",
}

DEFAULT_EXE_TONES = {
    # chat — Enter sends
    "whatsapp.exe": "chat",
    "slack.exe": "chat",
    "ms-teams.exe": "chat",
    "teams.exe": "chat",
    "discord.exe": "chat",
    "telegram.exe": "chat",
    "signal.exe": "chat",
    # mail — blank lines are paragraphs
    "outlook.exe": "email",
    "olk.exe": "email",          # new Outlook
    "thunderbird.exe": "email",
    "hxoutlook.exe": "email",
    # documents — prose that will be read on a page
    "winword.exe": "document",
    "notion.exe": "document",
    "obsidian.exe": "document",
    "onenote.exe": "document",
    # AI assistants and editors — precision over politeness
    "claude.exe": "prompt",
    "cursor.exe": "prompt",
    "code.exe": "prompt",
    "devenv.exe": "prompt",
    # terminals — Enter executes
    "windowsterminal.exe": "verbatim",
    "powershell.exe": "verbatim",
    "cmd.exe": "verbatim",
    "wt.exe": "verbatim",
}

# Matched case-insensitively as a substring of the window title, first hit
# wins. Only consulted for browsers.
DEFAULT_TITLE_TONES = {
    "whatsapp": "chat",
    "slack": "chat",
    "discord": "chat",
    "teams": "chat",
    "messenger": "chat",
    "gmail": "email",
    "outlook": "email",
    "proton mail": "email",
    "superhuman": "email",
    "linkedin": "social",
    "x.com": "social",
    "twitter": "social",
    "bluesky": "social",
    "claude": "prompt",
    "chatgpt": "prompt",
    "gemini": "prompt",
    "perplexity": "prompt",
    "notion": "document",
    "google docs": "document",
    "docs.google": "document",
    "jira": "ticket",
    "linear": "ticket",
    "github": "ticket",
    "gitlab": "ticket",
}

TONE_LABELS = {
    "chat": "Chat  ·  WhatsApp, Slack, Teams",
    "email": "E-mail  ·  Outlook, Gmail",
    "document": "Document  ·  Word, Notion, Docs",
    "social": "Sociale post  ·  LinkedIn, X",
    "ticket": "Ticket  ·  Jira, Linear, GitHub",
    "prompt": "AI-assistent  ·  Claude, ChatGPT, editors",
    "verbatim": "Terminal  ·  letterlijk overnemen",
    "default": "Overige apps",
}

DEFAULT_TONE_INSTRUCTIONS = {
    "chat": (
        "## Tone: chat message (WhatsApp, Slack, Teams)\n"
        "Write it the way you would type it to a colleague: short, direct, informal. "
        "Contractions are natural. Light punctuation only.\n"
        "- Output a SINGLE line. Never use a line break: in these apps Enter sends the "
        "message, so a break would fire it off half-finished.\n"
        "- No greeting and no sign-off. The recipient already knows who is writing.\n"
        "- Do not end with a full stop. Keep '?' and '!' when the speaker meant them.\n"
        "- At most one emoji, and only when it genuinely fits. None at all in a serious, "
        "factual or bad-news message.\n"
        "- Keep it as short as it was said. Do not turn a two-word reply into a sentence."
    ),
    "email": (
        "## Tone: email (Outlook, Gmail)\n"
        "Complete sentences and correct punctuation: professional but warm, never stiff.\n"
        "- Start a new paragraph, separated by a blank line, whenever the subject changes. "
        "A wall of text is the most common thing wrong with a dictated email.\n"
        "- If a greeting or a sign-off was spoken, put each on its own line. If none was "
        "spoken, add none.\n"
        "- Turn a spoken enumeration into a bulleted list, one item per line.\n"
        "- Keep it the length it was spoken. An email is not an invitation to elaborate."
    ),
    "document": (
        "## Tone: document (Word, Notion, Docs)\n"
        "Written prose meant to be read on a page.\n"
        "- Paragraphs separated by a blank line, each holding one thought.\n"
        "- Spoken enumerations become a list, one item per line.\n"
        "- Full sentences and correct punctuation, but keep the speaker's register: do not "
        "make casual thinking-out-loud sound like a formal report."
    ),
    "social": (
        "## Tone: social post (LinkedIn, X)\n"
        "A short public post in the speaker's own voice.\n"
        "- Keep the opening line strong; it is what people see before 'more'.\n"
        "- Short paragraphs with a blank line between them. No wall of text.\n"
        "- No hashtags, no emoji and no call to action unless the speaker said them.\n"
        "- Never make it more promotional or more polished than it was spoken."
    ),
    "ticket": (
        "## Tone: issue or ticket (Jira, Linear, GitHub)\n"
        "Written for someone who has to act on it.\n"
        "- Lead with what is wrong or what is needed, in one sentence.\n"
        "- Steps, conditions or requirements become a numbered or bulleted list.\n"
        "- Keep every identifier, error message, file name and version exactly as spoken.\n"
        "- No pleasantries, no filler."
    ),
    "prompt": (
        "## Tone: AI assistant or code editor\n"
        "This is read by a machine, so precision beats politeness.\n"
        "- Keep every technical term, file name, path, identifier and error string exactly "
        "as spoken. Never 'correct' them into ordinary words.\n"
        "- Lay out a multi-part request as a numbered list, one instruction per item.\n"
        "- Keep the imperative. Never soften, shorten or hedge an instruction.\n"
        "- Drop politeness padding that carries no meaning, but keep every constraint."
    ),
    "verbatim": (
        "## Tone: terminal\n"
        "The result is executed, so nothing may be reworded.\n"
        "- Output a single line, with no trailing full stop.\n"
        "- Remove fillers only. Never restructure, rephrase or explain.\n"
        "- Convert spoken syntax: 'dash m' -> -m, 'dot py' -> .py, 'slash' -> /, "
        "'backslash' -> the backslash character, 'pipe' -> |, 'tilde' -> ~.\n"
        "- If it does not read like a command, output it unchanged rather than guessing."
    ),
    "default": (
        "## Tone: plain written text\n"
        "Clear, natural prose with correct punctuation and no filler. Keep the speaker's "
        "level of formality exactly as it was; this destination gives no reason to shift it."
    ),
}

# Placed before the tone block so the model knows the tone section is meant
# to win over the base instruction's "keep their formality" line.
_OVERRIDE_NOTE = (
    "The tone guidance below takes precedence over the general instruction to preserve the "
    "speaker's level of formality, and only that instruction. Everything else still holds: "
    "never add facts, never summarise, never answer the content, keep their language."
)


def resolve(exe: str, title: str,
            exe_tones: dict | None = None,
            title_tones: dict | None = None) -> str:
    exe_tones = exe_tones or DEFAULT_EXE_TONES
    title_tones = title_tones or DEFAULT_TITLE_TONES
    exe = (exe or "").lower()
    title = (title or "").lower()

    if exe in BROWSER_EXES:
        for needle, tone in title_tones.items():
            if needle.lower() in title:
                return tone
        return "default"
    return exe_tones.get(exe, "default")


def build_instructions(base: str, tone: str, tone_instructions: dict | None = None) -> str:
    """The full system instruction: user's base text, the always-rules, and
    the tone block for this app."""
    from . import prompts

    tone_instructions = tone_instructions or DEFAULT_TONE_INSTRUCTIONS
    block = tone_instructions.get(tone) or tone_instructions.get("default", "")
    if block:
        block = f"{_OVERRIDE_NOTE}\n\n{block}"
    return prompts.build_system_instruction(base, block)
