#!/usr/bin/env python3
"""
investigate_structured_sources.py

Step 1 of the automation pipeline (see CLAUDE.md, build order item 1).

Purpose: for each of the 7 sources tagged `access_pattern:
structured_api_or_dashboard` in data/source_registry.json, determine what
"automated" actually means for that specific source -- a documented API, a
discoverable JSON/CSV endpoint behind a dashboard, a stable bulk-download
link, or (if none of those exist) a page that still needs an LLM-assisted
read.

This script does NOT extract any transition-feasibility figures. It only
answers one question per source: "how would a future Retriever actually
fetch data from this, without a human clicking around first?"

Run this before writing any Retriever/Extractor code for these sources --
per CLAUDE.md, do not assume `requests.get(url).json()` works for any of them
until this script (or equivalent manual checking) confirms it.

IMPORTANT -- network sandbox caveat:
This script was drafted and syntax-tested in an environment with NO real
outbound internet access (every request, including to example.com,
returned HTTP 403 from a local proxy, not from the target server). That
means the probe results in this environment are meaningless -- a 403 here
could mean "USGS blocks bots" or could mean "this sandbox blocks everything."
Before trusting any verdict from this script, run it once against a known-open
site (see `--selftest`) to confirm your environment actually reaches the
public internet. If Claude Code's own execution environment is similarly
sandboxed, run this script from a shell with real network access instead
(e.g. your local machine, not an agent sandbox), or route requests through
Claude's own web_fetch tool rather than raw urllib -- ask Claude Code to
do that rewrite if the selftest fails.

Usage:
    python3 scripts/investigate_structured_sources.py --selftest
    python3 scripts/investigate_structured_sources.py
    python3 scripts/investigate_structured_sources.py --source USGS_Mineral_Commodity_Summaries
"""
import json
import sys
import argparse
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REGISTRY_PATH = DATA_DIR / "source_registry.json"

SELFTEST_URL = "https://example.com"

USER_AGENT = (
    "Mozilla/5.0 (compatible; TransitionAssessmentBot/0.1; "
    "research tool, see CLAUDE.md for purpose)"
)

# ---------------------------------------------------------------------------
# Known / suspected endpoints found during manual verification (Aug 2026).
# These are HYPOTHESES to be checked live, not confirmed working APIs.
# Update this dict as investigation confirms or refutes each one.
# ---------------------------------------------------------------------------
CANDIDATE_ENDPOINTS = {
    "World_Bank_Carbon_Pricing_Dashboard": [
        # Cited by an external source (Tax Foundation, 2024) as their data
        # source for carbon price figures -- suggests a real backing endpoint.
        "https://carbonpricingdashboard.worldbank.org/map_data",
        "https://carbonpricingdashboard.worldbank.org/compliance/price",
        "https://carbonpricingdashboard.worldbank.org/compliance/coverage",
        "https://carbonpricingdashboard.worldbank.org/compliance/instrument-detail",
    ],
    "USGS_Mineral_Commodity_Summaries": [
        # Confirmed during manual verification: USGS publishes commodity-level
        # data releases with real DOIs via data.usgs.gov, separate from the
        # PDF report itself. This is the strongest lead of the 7.
        "https://www.usgs.gov/publications/mineral-commodity-summaries-2025",
        # data.usgs.gov entries are commodity-specific with unique DOIs, e.g.
        # https://doi.org/10.5066/P13XCP3R (potash, 2025) -- no single index
        # endpoint found yet; may need a data.usgs.gov catalogue search.
    ],
    "US_DOE_AFDC": [
        # AFDC has historically exposed a public API for station location
        # data (NREL Developer Network). Verify current key/registration
        # requirements -- may need a free API key, not fully anonymous.
        "https://developer.nrel.gov/docs/transportation/alt-fuel-stations-v1/",
        "https://afdc.energy.gov/stations",
    ],
    "NGFS_Scenario_Explorer": [
        # Confirmed downloadable during manual verification as CSV/XLSX.
        "https://data.ece.iiasa.ac.at/ngfs-phase-3/#/downloads",
    ],
    "China_National_ETS_Price": [
        # cneeex.com is Chinese-language; no API found during manual
        # verification. ICAP's tracker page is a more likely stable
        # secondary source for extracted price figures.
        "https://icapcarbonaction.com/en/ets/china-national-ets",
    ],
    "EU_ETS_Price": [
        # EEX has historical had paid API access; free spot price is
        # typically only on the dashboard page itself. CHECK: EU Commission
        # also republishes EUA auction results periodically.
        "https://www.eex.com/en/market-data/environmental-markets/spot-market",
    ],
    "LSE_Grantham_CCLW": [
        # climate-laws.org confirmed full-text searchable during manual
        # verification. Check whether Climate Policy Radar (the underlying
        # tech partner) exposes a documented public API separate from the
        # search UI.
        "https://climate-laws.org",
        "https://www.climatepolicyradar.org",
    ],
}

CONTENT_TYPE_VERDICT = {
    "application/json": "LIKELY MACHINE-READABLE (JSON)",
    "text/csv": "LIKELY MACHINE-READABLE (CSV)",
    "application/vnd.ms-excel": "LIKELY MACHINE-READABLE (Excel)",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "LIKELY MACHINE-READABLE (Excel)",
    "text/html": "HTML PAGE — needs further inspection (may embed JSON, may be pure UI)",
}


def load_registry():
    with open(REGISTRY_PATH) as f:
        return json.load(f)["sources"]


def probe_url(url: str, timeout: int = 15) -> dict:
    """
    Lightweight HEAD-like probe: fetch headers and a small content sample.
    Does not attempt to parse the response -- that's the Extractor's job,
    once this script has confirmed *whether* parsing is worthwhile.
    """
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "unknown").split(";")[0].strip()
            status = resp.status
            sample = resp.read(500)
            return {
                "url": url,
                "reachable": True,
                "status": status,
                "content_type": content_type,
                "verdict": CONTENT_TYPE_VERDICT.get(content_type, f"UNKNOWN CONTENT TYPE: {content_type}"),
                "sample_bytes": len(sample),
            }
    except HTTPError as e:
        return {"url": url, "reachable": False, "status": e.code, "error": str(e)}
    except URLError as e:
        return {"url": url, "reachable": False, "status": None, "error": str(e.reason)}
    except Exception as e:  # noqa: BLE001 - this is a diagnostic tool, log and continue
        return {"url": url, "reachable": False, "status": None, "error": f"{type(e).__name__}: {e}"}


def investigate_source(name: str, source_info: dict) -> dict:
    result = {
        "source_name": name,
        "publisher": source_info.get("publisher", "unknown"),
        "registered_url": source_info.get("url", "none"),
        "probes": [],
    }
    candidates = CANDIDATE_ENDPOINTS.get(name, [])
    if not candidates and source_info.get("url"):
        candidates = [source_info["url"]]

    for url in candidates:
        print(f"  probing {url} ...", file=sys.stderr)
        result["probes"].append(probe_url(url))

    return result


def selftest() -> bool:
    """
    Confirm this environment actually has outbound internet access before
    trusting any probe result. Returns True if the environment appears to
    have real network access, False otherwise.
    """
    print(f"Self-test: fetching {SELFTEST_URL} ...", file=sys.stderr)
    result = probe_url(SELFTEST_URL)
    if result.get("reachable"):
        print(f"  OK -- environment has real outbound network access "
              f"(HTTP {result['status']}).\n", file=sys.stderr)
        return True
    print(f"  FAILED -- {result.get('error', 'unknown error')}", file=sys.stderr)
    print("  This environment does NOT appear to have real outbound internet\n"
          "  access (even example.com was unreachable). Every probe result\n"
          "  below is meaningless -- do not conclude anything about the\n"
          "  actual sources from this run. See the module docstring for\n"
          "  what to do instead.\n", file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        help="Investigate a single source by its registry key (e.g. USGS_Mineral_Commodity_Summaries). "
             "Default: investigate all 7 structured_api_or_dashboard sources.",
    )
    parser.add_argument(
        "--out",
        default=str(DATA_DIR / "source_investigation_results.json"),
        help="Where to write the JSON results (default: data/source_investigation_results.json)",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Only run the network self-test (fetch example.com) and exit. "
             "Run this first in any new environment before trusting other output.",
    )
    parser.add_argument(
        "--skip-selftest",
        action="store_true",
        help="Skip the automatic self-test before probing sources. Not recommended.",
    )
    args = parser.parse_args()

    if args.selftest:
        ok = selftest()
        sys.exit(0 if ok else 1)

    if not args.skip_selftest:
        network_ok = selftest()
        if not network_ok:
            print("Aborting -- rerun with --skip-selftest to proceed anyway "
                  "(results will not be trustworthy), or fix network access first.",
                  file=sys.stderr)
            sys.exit(1)

    sources = load_registry()
    structured = {
        k: v for k, v in sources.items()
        if v.get("access_pattern") == "structured_api_or_dashboard"
    }

    if args.source:
        if args.source not in structured:
            print(f"'{args.source}' is not a structured_api_or_dashboard source. "
                  f"Available: {list(structured.keys())}", file=sys.stderr)
            sys.exit(1)
        structured = {args.source: structured[args.source]}

    print(f"Investigating {len(structured)} structured_api_or_dashboard source(s)...\n", file=sys.stderr)

    results = []
    for name, info in structured.items():
        print(f"[{name}]", file=sys.stderr)
        results.append(investigate_source(name, info))
        print(file=sys.stderr)

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to {args.out}\n", file=sys.stderr)

    # Human-readable summary to stdout
    print("=" * 78)
    print("SUMMARY — what each source actually offers for automated retrieval")
    print("=" * 78)
    for r in results:
        print(f"\n{r['source_name']} ({r['publisher']})")
        if not r["probes"]:
            print("  No candidate endpoints probed -- registry has no url and "
                  "no CANDIDATE_ENDPOINTS entry. Needs manual investigation.")
            continue
        for p in r["probes"]:
            if p.get("reachable"):
                print(f"  {p['url']}")
                print(f"    -> {p['verdict']} (HTTP {p['status']}, {p['content_type']})")
            else:
                print(f"  {p['url']}")
                print(f"    -> UNREACHABLE: {p.get('error', 'unknown error')}")

    print("\n" + "=" * 78)
    print("NEXT STEP: for any source marked LIKELY MACHINE-READABLE, write a")
    print("small dedicated parser and confirm it extracts a real, current")
    print("value before wiring it into the Retriever. For anything marked")
    print("HTML PAGE or UNREACHABLE, that source needs an LLM-assisted read")
    print("(see docs/Automation_Pipeline_Design.docx Section 5.1) or a")
    print("different access_pattern classification entirely -- update")
    print("data/source_registry.json accordingly rather than forcing it.")
    print("=" * 78)


if __name__ == "__main__":
    main()
