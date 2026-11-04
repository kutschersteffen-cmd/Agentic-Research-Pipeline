import re

from arp.ingestion.html_text import extract_html_text

_NF = (
    '<ix:nonFraction name="us-gaap:ResearchAndDevelopmentExpense" contextRef="c-1"'
    ' unitRef="usd" decimals="-6" scale="6" sign="-">1,894</ix:nonFraction>'
)
_PARA = (
    "Research and development expense increased during the year because of higher"
    " headcount-related costs and infrastructure."
)
_HIDDEN = (
    '<div style="display:none"><ix:header><ix:hidden><ix:nonNumeric name="dei:AmendmentFlag" contextRef="c-1">'
    "HIDDENFLAG</ix:nonNumeric></ix:hidden></ix:header></div>"
)
_CONTEXT = (
    '<div style="display:none"><ix:header><ix:resources>'
    '<xbrli:context xmlns:xbrli="http://www.xbrl.org/2003/instance" id="c-1"><xbrli:entity>'
    '<xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>'
    "<xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate>"
    "</xbrli:period></xbrli:context></ix:resources></ix:header></div>"
)


def _doc(figure=_NF, first="", para=_PARA):
    return (
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>'
        f"{first}<p>{para}</p><p>(In millions)</p>"
        "<table><tr><td><span>Research and development</span></td><td><span>(</span></td>"
        f"<td><span>{figure}</span></td><td><span>)</span></td></tr></table></body></html>"
    )


def _lines(text):
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]


_ROW = "Research and development | ( | 1,894 | )"


def test_a_tagged_figure_in_a_table_cell_keeps_its_number():  # AC-1, AC-7
    lines = _lines(extract_html_text(_doc()))
    assert _ROW in lines
    assert "(In millions)" in lines


def test_a_non_numeric_tag_keeps_its_text():  # AC-2
    figure = '<ix:nonNumeric name="us-gaap:ResearchAndDevelopmentExpense" contextRef="c-1">1,894</ix:nonNumeric>'
    assert _ROW in _lines(extract_html_text(_doc(figure)))


def test_hidden_header_facts_stay_out_of_the_text():  # AC-3
    text = extract_html_text(_doc(first=_HIDDEN))
    assert "HIDDENFLAG" not in text
    assert _ROW in _lines(text)


def test_every_inline_content_tag_keeps_its_text():  # AC-8, AC-11, AC-12, AC-13
    for figure, tags in [
        ("<ix:fraction><ix:numerator>TAG1</ix:numerator><ix:denominator>TAG2</ix:denominator></ix:fraction>",
         ["TAG1", "TAG2"]),
        ('<ix:continuation id="k1">TAG3</ix:continuation>', ["TAG3"]),
        ("<ix:exclude>TAG4</ix:exclude>", ["TAG4"]),
        ('<ix:footnote id="fn1">TAG5</ix:footnote>', ["TAG5"]),
    ]:
        text = extract_html_text(_doc(figure))
        assert all(t in text for t in tags), figure


def test_an_xml_declaration_is_dropped_and_non_ascii_text_kept():  # AC-9, AC-15
    assert "1,894" in extract_html_text("<?xml version='1.0' encoding='ASCII'?>" + _doc())
    para = "Spending rose 5 € — mainly headcount."
    assert para in extract_html_text("<?xml version='1.0' encoding='ASCII'?>" + _doc(para=para))


def test_ixbrl_that_is_not_well_formed_xml_falls_back_to_the_html_path():  # AC-10
    raw = _doc().replace("<p>(In millions)", "<p>&nbsp;(In millions)")
    assert "(In millions)" in _lines(extract_html_text(raw))


def test_an_unreadable_fact_falls_back_to_the_html_path():  # AC-14
    raw = _doc(_NF.replace('scale="6"', 'scale="abc"'), first=_CONTEXT)
    assert "(In millions)" in _lines(extract_html_text(raw))
