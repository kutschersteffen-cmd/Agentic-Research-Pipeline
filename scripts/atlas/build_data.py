#!/usr/bin/env python3
"""Turn the Graphify graph, OpenWiki pages and notes into the Atlas page's data files.

Usage: build_data.py --graph graph.json --meta meta.json --report GRAPH_REPORT.md \
                     --wiki openwiki --notes notes --out DIR      (writes DIR/data/*)
       build_data.py --selftest
Exits 2 and writes nothing when an input file is missing.
"""
import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


def kind(n):
    if n.get("file_type") in ("document", "doc_ref", "rationale"):
        return "doc"
    src = n.get("source_file") or ""
    # Graphify gives each code file one node labelled with its basename; everything else in the file is an entity.
    return "file" if n.get("file_type") == "code" and src and n.get("label") == os.path.basename(src) else "entity"


def graph_data(raw):
    index = {n["id"]: i for i, n in enumerate(raw["nodes"])}
    links, inferred_deg = [], [0] * len(index)
    for l in raw.get("links", []):
        s, t = index.get(l["source"]), index.get(l["target"])
        if s is None or t is None:
            continue
        inf = l.get("confidence") == "INFERRED"
        links.append({"s": s, "t": t, "inferred": inf})
        if inf:
            inferred_deg[s] += 1
            inferred_deg[t] += 1
    nodes, communities = [], {}
    for i, n in enumerate(raw["nodes"]):
        c = n.get("community")
        nodes.append({"id": i, "label": n.get("label") or n["id"], "path": n.get("source_file") or None,
                      "community": c, "kind": kind(n), "inferredDeg": inferred_deg[i]})
        if c is not None:
            entry = communities.setdefault(c, {"id": c, "label": n.get("community_name") or f"Community {c}", "size": 0})
            entry["size"] += 1
    return {"nodes": nodes, "links": links, "communities": [communities[c] for c in sorted(communities)]}


def wiki_data(root):
    pages = []
    for f in sorted(Path(root).rglob("*.md")) if os.path.isdir(root) else []:
        rel = f.relative_to(root)
        if rel.as_posix() == "INSTRUCTIONS.md" or any(part.startswith(".") for part in rel.parts):
            continue
        md = f.read_text(encoding="utf-8")
        slug = rel.with_suffix("").as_posix()
        title = next((line[2:].strip() for line in md.splitlines() if line.startswith("# ")), slug)
        pages.append({"slug": slug, "title": title, "md": md})
    return {"pages": pages}


def notes_data(root):
    notes = []
    for f in sorted(Path(root).glob("*.md")) if os.path.isdir(root) else []:
        md = f.read_text(encoding="utf-8")
        targets = (m.split("|")[0].split("#")[0].strip() for m in WIKILINK.findall(md))
        notes.append({"name": f.stem, "md": md, "links": list(dict.fromkeys(t for t in targets if t))})
    return {"notes": notes}


def build(args):
    # Read everything before writing anything, so a bad input leaves --out as it was.
    files = {
        "graph.json": json.dumps(graph_data(json.loads(Path(args.graph).read_text(encoding="utf-8"))),
                                 separators=(",", ":"), ensure_ascii=False),
        "wiki.json": json.dumps(wiki_data(args.wiki), separators=(",", ":"), ensure_ascii=False),
        "notes.json": json.dumps(notes_data(args.notes), separators=(",", ":"), ensure_ascii=False),
        "report.md": Path(args.report).read_text(encoding="utf-8"),
        "meta.json": Path(args.meta).read_text(encoding="utf-8"),
    }
    out = Path(args.out) / "data"
    out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--graph")
    p.add_argument("--meta")
    p.add_argument("--report")
    p.add_argument("--wiki", default="openwiki")
    p.add_argument("--notes", default="notes")
    p.add_argument("--out")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return selftest()
    for name in ("graph", "meta", "report"):
        path = getattr(args, name)
        if not path or not os.path.isfile(path):
            print(f"build_data: --{name} missing: {path}", file=sys.stderr)
            return 2
    if not args.out:
        print("build_data: --out missing", file=sys.stderr)
        return 2
    build(args)
    return 0


def selftest():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        graph = {"nodes": [
            {"id": "a", "label": "grounding.py", "file_type": "code", "source_file": "backend/arp/grounding.py",
             "community": 0, "community_name": "Grounding"},
            {"id": "b", "label": "ground()", "file_type": "code", "source_file": "backend/arp/grounding.py",
             "community": 0, "community_name": "Grounding"},
            {"id": "c", "label": "anthropic", "file_type": "concept", "source_file": "",
             "community": 1, "community_name": "Community 1"},
            {"id": "d", "label": "Design notes", "file_type": "document", "source_file": "docs/x.md",
             "community": 1, "community_name": "Community 1"},
        ], "links": [
            {"source": "a", "target": "b", "relation": "contains", "confidence": "EXTRACTED"},
            {"source": "b", "target": "c", "relation": "calls", "confidence": "INFERRED"},
            {"source": "b", "target": "gone", "relation": "calls", "confidence": "EXTRACTED"},
        ]}
        (t / "graph.json").write_text(json.dumps(graph))
        (t / "meta.json").write_text('{"commit": "abc1234def", "built_at": "2026-10-18T03:00Z"}')
        (t / "report.md").write_text("# Graph Report\n")
        wiki = t / "openwiki"
        (wiki / ".claims").mkdir(parents=True)
        (wiki / "INSTRUCTIONS.md").write_text("# Instructions\n")
        (wiki / ".claims" / "c.md").write_text("# Claim\n")
        (wiki / "grounding.md").write_text("Intro\n\n# Grounding\n\nSee [other](other.md).\n")
        (wiki / "other.md").write_text("no heading\n")
        (t / "notes").mkdir()
        (t / "notes" / "ctx-probe.md").write_text(
            "Tolerance [[backend/arp/grounding.py|grounding]] and [[grounding#Tolerance]], again "
            "[[backend/arp/grounding.py]].\n")
        base = ["--graph", str(t / "graph.json"), "--meta", str(t / "meta.json"), "--report", str(t / "report.md"),
                "--wiki", str(wiki), "--notes", str(t / "notes")]

        out = t / "out"
        assert main(base + ["--out", str(out)]) == 0
        d = out / "data"
        g = json.loads((d / "graph.json").read_text())
        assert [n["kind"] for n in g["nodes"]] == ["file", "entity", "entity", "doc"], g["nodes"]
        assert g["nodes"][1] == {"id": 1, "label": "ground()", "path": "backend/arp/grounding.py",
                                 "community": 0, "kind": "entity", "inferredDeg": 1}, g["nodes"][1]
        assert g["nodes"][2]["path"] is None
        assert g["links"] == [{"s": 0, "t": 1, "inferred": False}, {"s": 1, "t": 2, "inferred": True}], g["links"]
        assert g["communities"] == [{"id": 0, "label": "Grounding", "size": 2},
                                    {"id": 1, "label": "Community 1", "size": 2}], g["communities"]
        w = json.loads((d / "wiki.json").read_text())
        assert [(p["slug"], p["title"]) for p in w["pages"]] == [("grounding", "Grounding"), ("other", "other")], w
        assert "[other](other.md)" in w["pages"][0]["md"]
        n = json.loads((d / "notes.json").read_text())
        assert n == {"notes": [{"name": "ctx-probe", "md": (t / "notes" / "ctx-probe.md").read_text(),
                                "links": ["backend/arp/grounding.py", "grounding"]}]}, n
        assert (d / "report.md").read_text() == "# Graph Report\n"
        assert json.loads((d / "meta.json").read_text())["commit"] == "abc1234def"

        # Missing --graph (absent flag or absent file): exit 2, --out untouched.
        out2 = t / "out2"
        out2.mkdir()
        (out2 / "keep").write_text("x")
        no_graph = base[2:] + ["--out", str(out2)]
        with contextlib.redirect_stderr(io.StringIO()) as err:
            assert main(no_graph) == 2
            assert main(["--graph", str(t / "nope.json")] + no_graph) == 2
            assert main(["--graph", str(t / "nope.json")] + base[2:] + ["--out", str(t / "out3")]) == 2
        assert err.getvalue().count("--graph missing") == 3, err.getvalue()
        assert sorted(p.name for p in out2.iterdir()) == ["keep"]
        assert not (t / "out3").exists()

        # Missing wiki/notes dirs are fine (first run).
        assert main(base[:6] + ["--wiki", str(t / "nw"), "--notes", str(t / "nn"), "--out", str(t / "out4")]) == 0
        assert json.loads((t / "out4" / "data" / "wiki.json").read_text()) == {"pages": []}
    print("build_data selftest: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
