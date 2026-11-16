"""The word comparison of an answer with its base entry's answer (rfp-approved-answers-first-design §4). Worked out by
the code, never by a model."""

from __future__ import annotations

from difflib import SequenceMatcher


def compare(base: str, answer: str) -> tuple[list[dict[str, str]], int]:
    """(runs of words in order, each {text, change} with change kept|added|removed; kept words as a whole percentage
    of kept, added and removed words, rounded half up)."""
    a, b = base.split(), answer.split()
    runs: list[dict[str, str]] = []
    counts = {"kept": 0, "added": 0, "removed": 0}

    def run(words: list[str], change: str) -> None:
        runs.append({"text": " ".join(words), "change": change})
        counts[change] += len(words)

    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            run(a[i1:i2], "kept")
            continue
        if op in ("delete", "replace"):
            run(a[i1:i2], "removed")
        if op in ("insert", "replace"):
            run(b[j1:j2], "added")
    total = sum(counts.values())
    return runs, (200 * counts["kept"] + total) // (2 * total) if total else 100
