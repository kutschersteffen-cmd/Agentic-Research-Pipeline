"""Fund overlap (spec `stewardship-workbench-overlap`): how much the house funds hold the same companies, and which
companies are picked in more than one scope. Computed on every read from `fund_holdings()` and the selection log;
nothing is stored and nothing is cached.

A company's weight in a fund is its market value / the fund's company market value x 100 (the worklist's
`held_in[].weight_pct`, unrounded here). The shared weight of two funds is the sum, over the companies both hold, of
the lower of the two weights: the formula of `compute_holdings_overlap`, per company id instead of ticker.
"""

from __future__ import annotations

from itertools import combinations

from arp.stewardship.worklist import HOUSE


def fund_weights(funds: dict[str, dict]) -> dict[str, dict[str, float]]:
    """portfolio_id -> company_id -> weight in that fund, % (unrounded), from `fund_holdings()`."""
    out = {}
    for pid, fund in funds.items():
        total = sum(v[0] for v in fund["companies"].values())
        out[pid] = {cid: v[0] / total * 100 for cid, v in fund["companies"].items()} if total else {}
    return out


def fund_list(funds: dict[str, dict]) -> list[dict]:
    """The funds by name (case-insensitive), then portfolio_id."""
    rows = [{"portfolio_id": pid, "name": f["name"], "companies": len(f["companies"])} for pid, f in funds.items()]
    return sorted(rows, key=lambda f: (f["name"].casefold(), f["portfolio_id"]))


def pairs(order: list[str], weights: dict[str, dict[str, float]]) -> list[dict]:
    out = []
    for a, b in combinations(order, 2):
        shared = weights[a].keys() & weights[b].keys()
        pct = sum(min(weights[a][c], weights[b][c]) for c in shared)
        out.append({"a": a, "b": b, "shared_companies": len(shared), "shared_weight_pct": round(pct, 2)})
    return out


def house_weights(funds: dict[str, dict]) -> dict[str, float]:
    """company_id -> its market value across all funds / all funds' company market value x 100 (unrounded)."""
    held: dict[str, float] = {}
    for fund in funds.values():
        for cid, (mv, _) in fund["companies"].items():
            held[cid] = held.get(cid, 0.0) + mv
    total = sum(held.values())
    return {cid: mv / total * 100 for cid, mv in held.items()} if total else {}


def held_in(cid: str, fund_rows: list[dict], weights: dict[str, dict[str, float]]) -> list[dict]:
    return [
        {"portfolio_id": f["portfolio_id"], "name": f["name"], "weight_pct": round(weights[f["portfolio_id"]][cid], 3)}
        for f in fund_rows
        if cid in weights[f["portfolio_id"]]
    ]


def shared_selections(
    selections: dict[str, dict[str, dict]], labels: dict[str, str], fund_rows: list[dict], weights: dict[str, dict[str, float]]
) -> list[dict]:
    """The companies picked in two or more scopes. `selections`: `SelectionLog.all_rows(cycle)`; `labels`: scope key
    -> label (a key without one shows the key itself)."""
    labels = {"house": HOUSE, **labels}
    picked: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for key, rows in selections.items():
        for iid, row in rows.items():
            picked.setdefault(iid, []).append({"scope": key, "label": labels.get(key, key), "status": row["status"]})
            names.setdefault(iid, row.get("company") or iid)
    out = []
    for iid, scopes in picked.items():
        if len(scopes) < 2:
            continue
        scopes.sort(key=lambda s: (s["scope"] != "house", s["label"].casefold(), s["scope"]))
        out.append({"issuer_id": iid, "company": names[iid], "scopes": scopes, "held_in": held_in(iid, fund_rows, weights)})
    return sorted(out, key=lambda e: (-len(e["scopes"]), e["company"].casefold(), e["issuer_id"]))


def overview(funds: dict[str, dict], selections: dict[str, dict[str, dict]], labels: dict[str, str]) -> dict:
    """`funds`, `pairs`, `shared_selections` and the number of companies any fund holds."""
    fund_rows, weights = fund_list(funds), fund_weights(funds)
    return {
        "companies": len(set().union(*(w.keys() for w in weights.values()))),
        "funds": fund_rows,
        "pairs": pairs([f["portfolio_id"] for f in fund_rows], weights),
        "shared_selections": shared_selections(selections, labels, fund_rows, weights),
    }


def matrix(funds: dict[str, dict], names: dict[str, str], n: int | None = None, picked: dict[str, str] | None = None) -> dict:
    """The fund x company grid: the `n` companies with the largest house weight, or (`picked`: company_id -> name from
    the selection log) every picked company, a company no fund holds last. `names`: company_id -> name."""
    fund_rows, weights, house = fund_list(funds), fund_weights(funds), house_weights(funds)
    ids = list(house) if picked is None else list(picked)
    picked = picked or {}

    def name(cid: str) -> str:
        return names.get(cid) or picked.get(cid) or cid

    ids.sort(key=lambda c: (c not in house, -house.get(c, 0.0), name(c).casefold(), c))
    companies = []
    for cid in ids if n is None else ids[:n]:
        w = {
            f["portfolio_id"]: round(weights[f["portfolio_id"]][cid], 3) if cid in weights[f["portfolio_id"]] else None
            for f in fund_rows
        }
        companies.append({
            "issuer_id": cid, "company": name(cid), "house_weight_pct": round(house[cid], 3) if cid in house else None,
            "funds": sum(v is not None for v in w.values()), "weights": w,
        })  # fmt: skip
    return {"funds": fund_rows, "companies": companies}
