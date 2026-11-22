"""One chart render in a child process (spec agent-board, D1): `python -m arp.agent_board.render_worker`.

Reads the Vega-Lite source as JSON on stdin and writes `{"light": svg, "dark": svg}` on stdout. Its data segment is
capped before vl-convert loads, so a chart that grows without bound kills this process, never the API. On a chart error
it writes the error's first line on stderr and exits 1.
"""

from __future__ import annotations

import json
import resource
import sys

MEMORY_BYTES = 1024 * 2**20  # RLIMIT_DATA: V8 reserves far more address space than it uses, so RLIMIT_AS cannot work
MAX_SVG_BYTES = 2**20  # per SVG, so a board of 50 charts stays near 100 MB


def themed_svgs(source: dict) -> dict[str, str]:
    """The source with `config` replaced by the house theme for each colour scheme, as SVG."""
    from arp.reporting import vega
    from arp.reporting.house_style import load_tokens
    from arp.reporting.render_model import palette

    tokens, out = load_tokens(), {}
    for mode in ("light", "dark"):
        c = palette(tokens, mode)
        config = vega.theme_config(tokens, mode)
        config["background"] = c["panel"]
        for part in ("axis", "legend"):
            config[part] = {**config.get(part, {}), "labelColor": c["ink"], "titleColor": c["ink"]}
        config["axis"].update(domainColor=c["line"], tickColor=c["line"])
        config["title"] = {**config.get("title", {}), "color": c["ink"]}
        config["mark"] = {**config.get("mark", {}), "color": c["highlight"]}
        out[mode] = vega.to_svg({**source, "config": config}, tokens)
        if len(out[mode]) > MAX_SVG_BYTES:
            raise ValueError("the drawn chart exceeds 1 MB")
    return out


def main() -> int:
    resource.setrlimit(resource.RLIMIT_DATA, (MEMORY_BYTES, MEMORY_BYTES))
    try:
        out = themed_svgs(json.load(sys.stdin))
    except Exception as exc:  # noqa: BLE001 - any failure is the chart's; the parent reports its first line
        sys.stderr.write((str(exc).strip().splitlines() or [type(exc).__name__])[0])
        return 1
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
