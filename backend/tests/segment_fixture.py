"""Fixture S for the segment tests: an iXBRL 10-K (FY2025, USD) built from (concept, dims, value) facts."""

from __future__ import annotations

REV = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
AXIS = "us-gaap:StatementBusinessSegmentsAxis"
FY25, FY24, Q4 = ("2024-09-29", "2025-09-27"), ("2023-10-01", "2024-09-28"), ("2025-06-29", "2025-09-27")
NOTE = "Alpha sells widgets. Beta sells gadgets."


def seg(member: str, value, concept: str = REV, period=FY25, extra: dict | None = None):
    return (concept, {AXIS: member, **(extra or {})}, value, period)


def fixture_s(gamma=295, total=1000, extra: list | None = None, note: str | None = None) -> list:
    facts = [seg("x:AlphaSegmentMember", 300), seg("x:BetaMember", 400), seg("x:GammaSegmentMember", gamma)]
    if total is not None:
        facts.append((REV, {}, total, FY25))
    return [*facts, *(extra or [])] + ([("note", note)] if note else [])


def ixbrl(facts: list, scale: int = 0) -> bytes:
    ctxs, body = [], []
    for i, f in enumerate(facts):
        if f[0] == "note":
            body.append(f'<ix:nonNumeric name="us-gaap:SegmentReportingDisclosureTextBlock" contextRef="c0">'
                        f'<p>{f[1]}</p></ix:nonNumeric>')
            continue
        concept, dims, value, (start, end) = f
        members = "".join(
            f'<xbrldi:explicitMember dimension="{a}">{m}</xbrldi:explicitMember>' if a else
            f'<xbrldi:explicitMember>{m}</xbrldi:explicitMember>' for a, m in dims.items())
        seg_xml = f"<xbrli:segment>{members}</xbrli:segment>" if dims else ""
        ctxs.append(f'<xbrli:context id="c{i}"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1'
                    f'</xbrli:identifier>{seg_xml}</xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate>'
                    f'<xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>')
        shown = value / 10**scale
        body.append(f'<p><ix:nonFraction name="{concept}" contextRef="c{i}" unitRef="usd" decimals="0" scale="{scale}"'
                    f' format="ixt:num-dot-decimal">{shown:g}</ix:nonFraction></p>')
    if not ctxs:
        ctxs.append('<xbrli:context id="c0"><xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>'
                    '</xbrli:entity><xbrli:period><xbrli:instant>2025-09-27</xbrli:instant></xbrli:period></xbrli:context>')
    return (
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"'
        ' xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"'
        ' xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"><body>'
        f'<div style="display:none"><ix:header><ix:resources>{"".join(ctxs)}'
        '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></ix:resources></ix:header></div>'
        f'{"".join(body)}</body></html>'
    ).encode()
