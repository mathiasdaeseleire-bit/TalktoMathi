"""Version comparison for the GitHub updater.

Getting this wrong is quietly expensive: too eager and the app nags about
an update it already has, too lax and a real release never reaches anyone.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from talkwithme import updater


def test_tag_prefix_and_separators_are_ignored():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.2.3") == (1, 2, 3)
    assert updater.parse_version("V0.1.0") == (0, 1, 0)
    print("OK: v-prefix en scheidingstekens worden genormaliseerd")


def test_newer_only_when_actually_newer():
    assert updater.is_newer("v0.2.0", "0.1.0")
    assert updater.is_newer("v0.1.1", "0.1.0")
    assert updater.is_newer("v1.0.0", "0.9.9")
    assert not updater.is_newer("v0.1.0", "0.1.0"), "gelijke versie is geen update"
    assert not updater.is_newer("v0.0.9", "0.1.0"), "oudere versie is geen update"
    print("OK: alleen een hogere versie geldt als update")


def test_shorter_version_compares_sanely():
    assert updater.is_newer("v2", "1.9.9")
    assert not updater.is_newer("v1", "1.0.0"), "1 en 1.0.0 zijn dezelfde release"
    print("OK: korte en lange versienummers vergelijken correct")


def test_garbage_tag_never_triggers_an_update():
    """A stray tag like 'latest' must not read as a new version."""
    assert updater.parse_version("latest") == (0,)
    assert not updater.is_newer("latest", "0.1.0")
    assert not updater.is_newer("", "0.1.0")
    print("OK: onleesbare tags leiden nooit tot een update")


if __name__ == "__main__":
    test_tag_prefix_and_separators_are_ignored()
    test_newer_only_when_actually_newer()
    test_shorter_version_compares_sanely()
    test_garbage_tag_never_triggers_an_update()
    print("\nAlle updater-tests geslaagd.")
