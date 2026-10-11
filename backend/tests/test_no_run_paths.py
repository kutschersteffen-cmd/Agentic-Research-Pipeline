import re
from pathlib import Path

ARP = Path(__file__).resolve().parents[1] / "arp"
ALLOWED_FILES = {ARP / "storage" / "run_store.py", ARP / "db" / "runs.py"}
# Path helpers on other stores, not run files.
OTHER_STORES = ("overrides_path", "output_path", "file_path", "template_source_path")
PATTERN = re.compile(r"\b\w*store\.\w+_path\(")


def test_no_path_access_outside_run_store():
    offenders = []
    for py in sorted(ARP.rglob("*.py")):
        if py in ALLOWED_FILES:
            continue
        for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if PATTERN.search(line) and not any(o in line for o in OTHER_STORES):
                offenders.append(f"{py.relative_to(ARP.parent)}:{n}: {line.strip()}")
    assert not offenders, "run files must go through RunStore methods:\n" + "\n".join(offenders)
