from __future__ import annotations

from arp.ingestion.esef import parse_ixbrl, parse_ixbrl_dimensional
from tests.segment_fixture import AXIS, FY25, NOTE, REV, fixture_s, ixbrl, seg


def test_explicit_member_parsed():
    facts, dims, _ = parse_ixbrl_dimensional(ixbrl(fixture_s()))
    alpha = dims[0]
    assert alpha.dims == {AXIS: "x:AlphaSegmentMember"} and alpha.value == 300 and alpha.unit == "USD"
    assert (alpha.period_start, alpha.period_end) == FY25
    assert len(dims) == 3 and [f.value for f in facts] == [1000]


def test_ac_17_member_without_dimension_never_matches_an_axis():
    _, dims, _ = parse_ixbrl_dimensional(ixbrl(fixture_s(extra=[(REV, {None: "x:DeltaMember"}, 5, FY25)])))
    assert len(dims) == 4 and AXIS not in dims[3].dims


def test_typed_member_counts_as_extra_dim():
    doc = ixbrl(fixture_s()).replace(
        b'<xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">x:BetaMember</xbrldi:explicitMember>',
        b'<xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">x:BetaMember</xbrldi:explicitMember>'
        b'<xbrldi:typedMember dimension="x:T"><x:v xmlns:x="x">1</x:v></xbrldi:typedMember>')
    _, dims, _ = parse_ixbrl_dimensional(doc)
    assert len(dims[1].dims) == 2


def test_scale_applied():
    _, dims, _ = parse_ixbrl_dimensional(ixbrl([seg("x:AlphaSegmentMember", 300_000_000)], scale=6))
    assert dims[0].value == 300_000_000


def test_text_block():
    _, _, texts = parse_ixbrl_dimensional(ixbrl(fixture_s(note=NOTE)))
    assert texts["us-gaap:SegmentReportingDisclosureTextBlock"] == NOTE


def test_text_block_follows_continuation_chain():
    doc = ixbrl(fixture_s(note="Part one.")).replace(
        b'name="us-gaap:SegmentReportingDisclosureTextBlock"',
        b'name="us-gaap:SegmentReportingDisclosureTextBlock" continuedAt="k1"').replace(
        b"</body>", b'<div><ix:continuation id="k1"><p>Part two.</p></ix:continuation></div></body>')
    _, _, texts = parse_ixbrl_dimensional(doc)
    assert texts["us-gaap:SegmentReportingDisclosureTextBlock"] == "Part one.\nPart two."


def test_ac_21_parse_ixbrl_unchanged_with_dimensional_contexts():
    doc = ixbrl(fixture_s())
    text, facts = parse_ixbrl(doc)
    assert [(f.concept, f.value) for f in facts] == [(REV, 1000)]
    assert parse_ixbrl_dimensional(doc)[0] == facts
