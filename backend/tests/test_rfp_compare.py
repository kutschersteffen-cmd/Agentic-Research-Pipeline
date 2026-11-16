"""rfp-approved-answers-first-design §4: the word comparison of an answer with its base entry's answer."""

import subprocess
import sys
from pathlib import Path

from arp.rfp.compare import compare

BASE = "Example AM is an independent manager founded in 2004."


def seg(*pairs):
    return [{"text": t, "change": c} for t, c in pairs]


def test_unchanged_is_one_kept_run():
    assert compare(BASE, BASE) == (seg((BASE, "kept")), 100)


def test_added_word():  # AC-5, AC-6
    assert compare(BASE, "Example AM is an independent asset manager founded in 2004.") == (
        seg(("Example AM is an independent", "kept"), ("asset", "added"), ("manager founded in 2004.", "kept")), 90)


def test_removed_word():  # AC-45
    assert compare(BASE, "Example AM is an manager founded in 2004.") == (
        seg(("Example AM is an", "kept"), ("independent", "removed"), ("manager founded in 2004.", "kept")), 89)


def test_replace_is_removed_then_added_and_rounds_half_up():  # AC-58: 2 kept, 7 added, 7 removed = 12.5
    segments, share = compare(BASE, "Example AM has been managing money for pension funds.")
    assert [s["change"] for s in segments] == ["kept", "removed", "added"]
    assert share == 13


def test_appended_sentence():  # AC-32
    assert compare(BASE, BASE + " We engage on climate, governance and human rights.")[1] == 53


def test_empty_answer_is_all_removed():
    assert compare("a b", "") == (seg(("a b", "removed")), 0)


def test_compare_two_thousand_words_under_half_a_second():
    # timed in a fresh interpreter: coverage tracing in the test process slows pure-Python difflib 3-4x
    code = (
        "import time; from arp.rfp.compare import compare\n"
        "a, b = ' '.join(f'w{i}' for i in range(2000)), ' '.join(f'w{i}' for i in range(0, 2000, 2))\n"
        "start = time.perf_counter(); compare(a, b); print(time.perf_counter() - start)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=Path(__file__).parents[1])
    assert float(out.stdout) < 0.5
