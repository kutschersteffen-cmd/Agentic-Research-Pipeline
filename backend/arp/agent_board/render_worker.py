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
MAX_SVG_BYTES = 2 * 2**20  # per SVG: a 5 000-point scatter fits; a board of 50 charts stays near 200 MB


def themed_svgs(source: dict) -> dict[str, str]:
    """The source with `config` replaced by the house theme for each colour scheme, as SVG. The chart's own top-level
    `title` is dropped: the Board shows the block's title above it."""
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
        config["axis"].update(domainColor=c["line"], tickColor=c["line"], gridColor=c["line"])
        config["title"] = {**config.get("title", {}), "color": c["ink"]}
        config["mark"] = {**config.get("mark", {}), "color": c["highlight"]}
        untitled = {k: v for k, v in source.items() if k != "title"}
        out[mode] = vega.to_svg({**untitled, "config": config}, tokens)
        if len(out[mode]) > MAX_SVG_BYTES:
            raise ValueError("the drawn chart exceeds 2 MB")
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
