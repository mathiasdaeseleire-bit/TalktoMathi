"""Deterministic formatting rules.

Each of these protects against something the user would notice: a chat
message sent half-finished, a broken shell command, a wall-of-text email,
or the model's own chatter ending up in the paste.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from talkwithme import postprocess as pp


def test_chat_is_always_one_line():
    """Enter sends in WhatsApp and Slack, so a newline would fire the
    message off half-written."""
    out = pp.finish("Eerste stuk.\n\nTweede stuk", "chat")
    assert "\n" not in out, out
    assert out == "Eerste stuk. Tweede stuk", out
    print("OK: chat wordt altijd één regel")


def test_chat_drops_the_trailing_period_but_keeps_intent():
    assert pp.finish("prima doe ik.", "chat") == "prima doe ik"
    assert pp.finish("lukt dat?", "chat") == "lukt dat?"
    assert pp.finish("top!", "chat") == "top!"
    assert pp.finish("wacht even...", "chat") == "wacht even..."
    print("OK: chat laat de punt vallen, maar niet ? ! of ...")


def test_terminal_stays_executable():
    assert pp.finish("git status.", "verbatim") == "git status"
    assert pp.finish("cd map\nls", "verbatim") == "cd map ls"
    print("OK: terminalcommando blijft uitvoerbaar")


def test_email_puts_a_spoken_greeting_on_its_own_line():
    out = pp.finish("Hoi Tom, bedankt voor je bericht. Ik kijk er maandag naar.", "email")
    assert out.startswith("Hoi Tom,\n\n"), out
    assert "bedankt voor je bericht" in out
    print("OK: gesproken aanhef krijgt een eigen regel")


def test_email_never_invents_a_greeting():
    out = pp.finish("Ik kijk er maandag naar.", "email")
    assert out == "Ik kijk er maandag naar.", out
    print("OK: zonder gesproken aanhef wordt er niets verzonnen")


def test_email_keeps_paragraphs():
    out = pp.finish("Eerste alinea.\n\nTweede alinea.", "email")
    assert out == "Eerste alinea.\n\nTweede alinea.", out
    print("OK: e-mail behoudt alinea-indeling")


def test_model_chatter_is_stripped():
    assert pp.finish("```\nhallo daar\n```", "default") == "hallo daar"
    assert pp.finish('"hallo daar"', "default") == "hallo daar"
    assert pp.finish("Here is the cleaned text:\nhallo daar", "default") == "hallo daar"
    print("OK: fences, aanhalingstekens en preambules verdwijnen")


def test_inner_quotation_survives():
    """Only a fully wrapped text is unwrapped; a real quote stays."""
    text = 'Hij zei "morgen" tegen mij'
    assert pp.finish(text, "default") == text
    print("OK: aanhalingstekens binnen de zin blijven staan")


def test_whitespace_is_normalised():
    assert pp.finish("te   veel    spaties", "default") == "te veel spaties"
    assert pp.finish("een\n\n\n\ntwee", "default") == "een\n\ntwee"
    print("OK: overtollige witruimte wordt opgeruimd")


def test_empty_input_stays_empty():
    assert pp.finish("", "chat") == ""
    assert pp.finish("   \n  ", "email") == ""
    print("OK: lege invoer blijft leeg")


if __name__ == "__main__":
    test_chat_is_always_one_line()
    test_chat_drops_the_trailing_period_but_keeps_intent()
    test_terminal_stays_executable()
    test_email_puts_a_spoken_greeting_on_its_own_line()
    test_email_never_invents_a_greeting()
    test_email_keeps_paragraphs()
    test_model_chatter_is_stripped()
    test_inner_quotation_survives()
    test_whitespace_is_normalised()
    test_empty_input_stays_empty()
    print("\nAlle formatteringstests geslaagd.")
