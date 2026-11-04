# Keep iXBRL-tagged numbers in converted filing text

## Problem

`arp/ingestion/html_text.py::extract_html_text` drops every number that a filer tagged with inline
XBRL. In recent 10-Ks the financial statements and notes are tagged; MD&A tables mostly are not. So the
statements come out with labels and empty cells while MD&A keeps its figures.

Reproduced on 2026-11-04 with two of the six reported filings:

| Filing | HTML | Text today |
|--------|------|------------|
| Apple 0000320193-26-000026, income statement | `<td><span><ix:nonFraction name="us-gaap:ResearchAndDevelopmentExpense" scale="6" …>45,765</ix:nonFraction>&#160;</span></td>` | `\| Research and development \|  \|  \|  \| …` (all cells empty) |
| Apple, same filing, MD&A (untagged) | `<td><span>45,765&#160;</span></td>` | `\| Research and development \|  \|  \| $ \| 45,765 \| …` |
| 3M 0000066740-26-000014, segment note | `ix:nonFraction` cells | `\| Research, development and related expenses \|  \|  \| …` (empty) |

Apple loses 999 of 2,783 numeric tokens (36%), 3M 2,278 of 6,184 (37%).

## Root cause

trafilatura (2.3.1) builds table cells in `main_extractor._fill_cell`. Each descendant of a `<td>` goes
through `handle_textelem`, which returns `None` for a tag it does not know. `ix:nonfraction` is unknown,
so its text is discarded. Parentheses and `$` sit outside the tag and survive, the figure does not. The
BeautifulSoup text in `extract_html_text` keeps the figures, but it is used only when trafilatura
returns nothing, or returns under 20% of the words of a document of 10,000+ words. Every other document,
small or large, gets trafilatura's output, so a one-paragraph test document shows the bug too (checked:
the AC-1 document on `main` has no `1,894` in its output).

The `XMLParsedAsHTMLWarning` comes from that BeautifulSoup fallback reading XHTML with the HTML parser.
It is noise, the text it returns is complete; out of scope.

## Impact

Every caller of `extract_html_text` gets the gaps: EDGAR 10-K / DEF 14A ingestion (`edgar.py`),
local HTML disclosure files (`local_files.py`), and fetched pages that happen to be iXBRL. Text-based
extraction (`arp/extraction`, financials pipeline, grounding of quoted figures) cannot read statement or
note numbers from these filings. The XBRL companyfacts path (`xbrl.py`, tagged-first fields) covers only
consolidated annual totals for its tag lists (CapEx, R&D, revenue and the field-graph tags). Segment rows,
note tables and anything else the LLM reads from text are not covered.

## Change

Reuse the repo's own inline-XBRL parser, `arp/ingestion/esef.py::parse_ixbrl` (built for ESEF, E16), for
every inline-XBRL document. The owner asked whether a dedicated SEC/ESEF tool exists; this is it. No
external library (Arelle, edgartools) is installed or needed. `parse_ixbrl` walks the XHTML itself,
keeps the text of every element, skips `ix:header` (hidden facts, contexts), and joins table cells with
` | `. On all six reported filings it parses in about 0.2 s and keeps the statement figures
(Apple: 3,320 numeric tokens, against 1,784 today).

In `extract_html_text`: when the document contains the inline-XBRL namespace
`http://www.xbrl.org/2013/inlineXBRL`, drop a leading `<?xml …?>` declaration, encode as UTF-8, and
return `parse_ixbrl(...)[0]`. If it raises `lxml.etree.XMLSyntaxError` or `ValueError` (for example a
non-numeric `scale`), carry on with today's trafilatura/BeautifulSoup path. About 6 lines; the import stays inside
the function (esef → xbrl → edgar → html_text would otherwise be circular).

Bump `edgar._EDGAR_PARSER_LOGIC_VERSION` to 3, as the docstring requires, so cached EDGAR text is
re-parsed. iXBRL filings' text changes format: table lines lose the leading and trailing `|` that
trafilatura adds. Nothing downstream parses that format (checked: no code matches on it), but chunk
boundaries and citation offsets of re-ingested filings move, which the version bump covers.

Not done: the BeautifulSoup `XMLParsedAsHTMLWarning` (gone for iXBRL documents anyway, since they no
longer reach BeautifulSoup); facts from `parse_ixbrl` are not wired into EDGAR ingestion; an iXBRL
document that is not well-formed XML keeps today's output, numbers missing (EDGAR validates iXBRL as
XHTML, and all six reported filings parse).

## Acceptance

In this table `\|` is a plain `|`: expected strings contain no backslashes. "Contains the line X": some
line of the output, with leading and trailing whitespace stripped and inner runs of whitespace collapsed
to one space, equals X exactly.

The **AC-1 document**, exactly (one line in the test; wrapped here):

```
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>
<p>Research and development expense increased during the year because of higher headcount-related costs and infrastructure.</p>
<p>(In millions)</p>
<table><tr><td><span>Research and development</span></td><td><span>(</span></td>
<td><span>FIGURE</span></td><td><span>)</span></td></tr></table></body></html>
```

with `FIGURE` = `<ix:nonFraction name="us-gaap:ResearchAndDevelopmentExpense" contextRef="c-1"
unitRef="usd" decimals="-6" scale="6" sign="-">1,894</ix:nonFraction>`. Other rows swap `FIGURE` for
the markup they name. On `main` this document's output has no `1,894`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | The AC-1 document | `extract_html_text` runs | The output contains the line `Research and development \| ( \| 1,894 \| )` | holdout |
| AC-2 | `FIGURE` = `<ix:nonNumeric name="us-gaap:ResearchAndDevelopmentExpense" contextRef="c-1">1,894</ix:nonNumeric>` | `extract_html_text` runs | The output contains the line `Research and development \| ( \| 1,894 \| )` | unit |
| AC-3 | The AC-1 document with `<div style="display:none"><ix:header><ix:hidden><ix:nonNumeric name="dei:AmendmentFlag" contextRef="c-1">HIDDENFLAG</ix:nonNumeric></ix:hidden></ix:header></div>` as the first child of `<body>` | `extract_html_text` runs | The output does not contain `HIDDENFLAG` | holdout |
| AC-4 | Apple 10-K `aapl-20260926.htm`, accession 0000320193-26-000026, downloaded from EDGAR (not committed: 1.6 MB) | `extract_html_text` runs | The output contains the line `Research and development \| 45,765 \| \| \| 34,550 \| \| \| 31,370 \|` | owner-accepted exception: manual run, output line quoted in the PR |
| AC-5 | The fixture documents of `tests/test_html_text.py` (none contain the inline-XBRL namespace) | that file runs | It passes with no edits to it | unit |
| AC-6 | The content store holds the text `STALE` for an EDGAR filing under a parser version containing `logic=2`; the HTTP stub serves the AC-1 document as that filing's primary `.htm` | `EdgarDocumentSource` fetches the filing | The returned text contains `1,894` and does not contain `STALE` | unit |
| AC-7 | The AC-1 document | `extract_html_text` runs | The output contains the line `(In millions)` | unit |
| AC-8 | `FIGURE` = `<ix:fraction><ix:numerator>TAG1</ix:numerator><ix:denominator>TAG2</ix:denominator></ix:fraction>` | `extract_html_text` runs | The output contains `TAG1` and `TAG2` | unit |
| AC-9 | The AC-1 document preceded by `<?xml version='1.0' encoding='ASCII'?>` | `extract_html_text` runs | The output contains `1,894` | unit |
| AC-10 | The AC-1 document with `&nbsp;` inserted before `(In millions)` (not well-formed XML) | `extract_html_text` runs | It returns without raising, and the output contains the line `(In millions)` | unit |
| AC-11 | `FIGURE` = `<ix:continuation id="k1">TAG3</ix:continuation>` | `extract_html_text` runs | The output contains `TAG3` | unit |
| AC-12 | `FIGURE` = `<ix:exclude>TAG4</ix:exclude>` | `extract_html_text` runs | The output contains `TAG4` | unit |
| AC-13 | `FIGURE` = `<ix:footnote id="fn1">TAG5</ix:footnote>` | `extract_html_text` runs | The output contains `TAG5` | unit |
| AC-14 | The AC-1 document with `scale="abc"` in `FIGURE`, and as first child of `<body>`: `<div style="display:none"><ix:header><ix:resources><xbrli:context xmlns:xbrli="http://www.xbrl.org/2003/instance" id="c-1"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context></ix:resources></ix:header></div>` (so `parse_ixbrl` reads the scale and raises `ValueError`) | `extract_html_text` runs | It returns without raising, and the output contains the line `(In millions)` | unit |
| AC-15 | The AC-9 document with the paragraph text replaced by `Spending rose 5 € — mainly headcount.` | `extract_html_text` runs | The output contains `Spending rose 5 € — mainly headcount.` | unit |

Must not change: documents without the inline-XBRL namespace (AC-5), hidden `ix:header` facts stay out
of the text (AC-3), malformed iXBRL still returns text (AC-10, AC-14).
