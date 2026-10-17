#!/usr/bin/env python3
"""Write the API's OpenAPI schema to frontend/src/api/openapi.json (the API contract snapshot).

The frontend generates src/api/schema.gen.ts from that file (`npm run gen:api`), so a backend
change to a request or response shape shows up in the PR diff and, where the frontend uses the
generated types, as a type error.

Usage (from backend/):  python scripts/export_openapi.py           write the snapshot
                        python scripts/export_openapi.py --check   fail if it is out of date
"""

import json
import sys
from pathlib import Path

from arp.api.main import app

OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    text = render()
    if sys.argv[1:] == ["--check"]:
        if OUT.exists() and OUT.read_text() == text:
            print("API contract snapshot is up to date.")
            return 0
        print(
            "The API changed but frontend/src/api/openapi.json was not regenerated.\n"
            "Run: cd backend && python scripts/export_openapi.py && cd ../frontend && npm run gen:api\n"
            "then fix any frontend type errors and commit both files."
        )
        return 1
    OUT.write_text(text)
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
