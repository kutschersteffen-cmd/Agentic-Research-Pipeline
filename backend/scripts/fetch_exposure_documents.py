"""Download each exposure golden case's first document into the layout the funnel and LocalFileDocumentSource read:
<out>/<case_id>/<doc_type>/<file>. Existing files are skipped; failures are printed and the rest continue.

    python3 backend/scripts/fetch_exposure_documents.py --cases backend/tests/golden/exposure/<set>/cases.json --out <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

_DOC_TYPE = {"annual_report": "10-K", "sustainability_report": "sustainability_report"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    cases = json.loads(args.cases.read_text())["cases"]
    failed = 0
    with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": "arp-golden-fetch"}) as client:
        for case in cases:
            doc = case["documents"][0]
            if not doc.get("url"):
                continue
            name = Path(urlparse(doc["url"]).path).name or "document.pdf"
            dest = args.out / case["case_id"] / _DOC_TYPE.get(doc.get("kind", ""), "other") / name
            if dest.exists() or any(dest.parent.glob(f"{dest.name}.*")):
                continue
            try:
                r = client.get(doc["url"])
                r.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"{case['case_id']}: {exc}", file=sys.stderr)
                failed += 1
                continue
            if not dest.suffix:  # URL without an extension: take it from the response type, or the parser rejects it
                kind = r.headers.get("content-type", "").split(";")[0].strip()
                dest = dest.with_suffix({"application/pdf": ".pdf", "text/html": ".html"}.get(kind, ".html"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
            print(f"{case['case_id']}: {dest}")
    print(f"{failed} of {len(cases)} cases have no document.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
