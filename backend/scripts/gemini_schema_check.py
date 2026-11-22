"""Send every structured-output schema in arp/ to the live Gemini API once and list the ones it rejects.

Opt-in and paid (a few cents per run): needs ARP_GEMINI_API_KEY, or ARP_GEMINI_USE_VERTEX with gcloud credentials.
It finds the schemas the way a reader would, from `output_model=<Name>` at the `complete_structured` call sites,
so a call site that picks its model at runtime is not covered.

    cd backend && python scripts/gemini_schema_check.py [--model gemini-4-argon] [--only SlideContent,PlanDraft]

A schema Gemini finds too complex still passes when the client's fallback (relaxed schema, or schema in the
prompt) gets a valid answer; the line says which fallback it needed. Exit code 1 when any schema is rejected (a 400 from the API) or no answer validates against it; exit code 2 when
the check could not run (no key, or the API refused the key or its billing: 401, 402, 403).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import re
import sys
from pathlib import Path

from google.genai import errors
from pydantic import BaseModel, ValidationError

from arp.config import Settings
from arp.llm.factory import build_llm_client

ARP = Path(__file__).resolve().parents[1] / "arp"
CALL = re.compile(r"output_model=([A-Z_][A-Za-z0-9_]*)")


def find_output_models() -> dict[str, type[BaseModel]]:
    found: dict[str, type[BaseModel]] = {}
    for path in sorted(ARP.rglob("*.py")):
        if path.parts[-2] == "llm":
            continue
        names = CALL.findall(path.read_text())
        if not names:
            continue
        module = importlib.import_module(".".join(path.relative_to(ARP.parent).with_suffix("").parts))
        for name in names:
            model = getattr(module, name, None)
            if isinstance(model, type) and issubclass(model, BaseModel):
                found.setdefault(name, model)
    return found


async def check(client, name: str, model: type[BaseModel], gate: asyncio.Semaphore) -> tuple[str, str, str]:
    async with gate:
        try:
            await client.complete_structured(
                system="Fill the schema with a short, plausible example.", prompt=f"Give one example {name}.",
                output_model=model, max_validation_retries=0, max_tokens=8192,
            )
            level = getattr(client, "_schema_level", {}).get(name, 0)
            return name, "ok", ("", "schema too complex: sent relaxed", "schema too complex: sent in the prompt")[level]
        except errors.ClientError as exc:
            return name, "REJECTED", str(exc)[:300]
        except ValidationError as exc:
            return name, "INVALID", " ".join(str(exc).split())[:300]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="gemini-3.8-flash")
    ap.add_argument("--only", default="", help="comma-separated model names")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    settings = Settings(llm_cache_enabled=False)
    if not settings.gemini_available:
        print("Set ARP_GEMINI_API_KEY (or ARP_GEMINI_USE_VERTEX) to run this check.", file=sys.stderr)
        return 2
    models = find_output_models()
    if args.only:
        models = {k: v for k, v in models.items() if k in set(args.only.split(","))}
    client = build_llm_client(settings, model=args.model)
    gate = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*(check(client, n, m, gate) for n, m in models.items()))
    unusable = [d for _, status, d in results if status == "REJECTED" and d[:3] in ("401", "402", "403")]
    if unusable:
        print(f"Gemini refused the key on {args.model}, so no schema was checked: {unusable[0]}", file=sys.stderr)
        return 2
    for name, status, detail in sorted(results, key=lambda r: (r[1] == "ok", r[0])):
        print(f"{status:9} {name}  {detail}")
    bad = sum(status != "ok" for _, status, _ in results)
    print(f"\n{len(results) - bad}/{len(results)} schemas ok on {args.model}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
