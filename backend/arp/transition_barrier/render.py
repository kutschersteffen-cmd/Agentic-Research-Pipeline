from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from arp.transition_barrier.rule_book import CriterionRules, ParamDef, RuleBook, SourceRef

OTHERWISE = "Otherwise (neither H nor M holds)"


def fmt_number(x: float) -> str:
    """At most two decimals, rounded half up on the decimal value, trailing zeros dropped."""
    text = format(Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _with_unit(value: float, unit: str | None) -> str:
    n = fmt_number(value)
    if not unit:
        return n
    return n + unit if unit == "%" else f"{n} {unit}"


def _param_text(param: ParamDef, region: str | None) -> str:
    if param.status == "open":
        return f"[open: {param.label}]"
    override = param.by_region.get(region) if region else None
    if override:
        return _with_unit(override.value, param.unit)
    text = _with_unit(param.value, param.unit)
    if region is None and param.by_region:
        extra = ", ".join(f"{r}: {_with_unit(o.value, param.unit)}" for r, o in param.by_region.items())
        text += f" ({extra})"
    return text


def _value_text(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def render_group(group: dict, rules: CriterionRules, region: str | None = None) -> str:
    """Render a condition or an all/any group. With `region`, its overrides replace the defaults."""
    facts = {f.id: f for f in rules.facts}
    params = {p.id: p for p in rules.params}

    def go(node: dict, nested: bool) -> str:
        for key, joiner in (("all", " and "), ("any", " or ")):
            if key in node:
                text = joiner.join(go(c, True) for c in node[key])
                return f"({text})" if nested else text
        label = facts[node["fact"]].label
        if "param" in node:
            return f"{label} {node['op']} {_param_text(params[node['param']], region)}"
        if "other_fact" in node:
            return f"{label} {node['op']} {facts[node['other_fact']].label}"
        value = node["value"]
        if isinstance(value, bool):
            return f"{label} is {'Yes' if value else 'No'}"
        return f"{label} {node['op']} {_value_text(value)}"

    return go(group, False)


def rubric(rules: CriterionRules) -> dict[str, str]:
    return {
        "H": render_group(rules.levels["H"], rules),
        "M": render_group(rules.levels["M"], rules),
        "L": OTHERWISE,
    }


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _source(src: SourceRef | None) -> str:
    if src is None:
        return ""
    parts = [src.title] + ([src.locator] if src.locator else [])
    text = ", ".join(parts)
    return f"{text} <{src.url}>" if src.url else text


def _param_row(p: ParamDef) -> str:
    if p.status == "open":
        cells = [f"`{p.id}` {p.label}", "open", p.unit or "", "", "", f"Open question: {p.question}"]
    else:
        overrides = "; ".join(
            f"{r}: {_with_unit(o.value, p.unit)} ({_source(o.source)})" if o.source else f"{r}: {_with_unit(o.value, p.unit)}"
            for r, o in p.by_region.items()
        )
        cells = [f"`{p.id}` {p.label}", fmt_number(p.value), p.unit or "", overrides, _source(p.source), p.rationale]
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def render_rule_book_md(rule_book: RuleBook, raw_schema: dict) -> str:
    labels = {a["id"]: a["label"] for acts in rule_book.actions.values() for a in acts}
    by_sector: dict[str, list[dict]] = {}
    for entry in raw_schema["criteria"]:
        by_sector.setdefault(entry["sector"], []).append(entry)

    out = ["# Transition barrier rule book", "", f"Rule book version {rule_book.version}.", ""]
    for sector, entries in by_sector.items():
        out += [f"# {sector}", ""]
        for entry in entries:
            rules = rule_book.criteria.get(entry["code"])
            if rules is None:
                continue
            out += [f"## {entry['code']} {entry['criterion']}", "", rules.rationale, ""]
            out += ["**Actions**", ""] + [f"- {labels.get(a, a)}" for a in rules.actions] + [""]
            out += ["**Facts**", ""]
            for f in rules.facts:
                out.append(f"- {f.label}: {f.definition}")
            out.append("")
            r = rubric(rules)
            out += ["**Rating**", ""] + [f"- {lvl}: {r[lvl]}." for lvl in ("H", "M", "L")] + [""]
            out += ["**Parameters**", "", "| Parameter | Value | Unit | Overrides | Source | Rationale |"]
            out += ["|---|---|---|---|---|---|"] + [_param_row(p) for p in rules.params] + [""]
    return "\n".join(out)
