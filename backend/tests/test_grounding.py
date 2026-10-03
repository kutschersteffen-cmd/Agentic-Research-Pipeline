from arp.grounding import ground_citations, is_grounded
from arp.schemas.common import Citation, DocType, SourceDocument


def test_exact_quote_is_grounded():
    source = "The company invested $500 million in green capex during fiscal 2025."
    assert is_grounded("invested $500 million in green capex", source)


def test_whitespace_variation_still_grounds():
    source = "Total  green   capex\nwas approximately $12 million."
    assert is_grounded("Total green capex was approximately $12 million.", source)


def test_hallucinated_quote_is_not_grounded():
    source = "The company discussed general R&D spending trends."
    assert not is_grounded("green capex reached $900 million", source)


def test_empty_quote_is_not_grounded():
    assert not is_grounded("", "some source text")


def test_ground_citations_marks_each_independently():
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t",
        full_text="Green capex totaled $50 million in FY2025.",
    )
    good = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Green capex totaled $50 million in FY2025.")
    bad = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Green capex totaled $9 billion.")
    missing_doc = Citation(doc_id="doc_missing", doc_type=doc.doc_type, quote="anything")

    result = ground_citations([good, bad, missing_doc], {doc.doc_id: doc})
    assert result[0].grounded is True
    assert result[1].grounded is False
    assert result[2].grounded is False


def test_ground_citations_resolves_page_from_verified_match_position():
    page1 = "Page one talks about general strategy and has nothing about capex."
    page2 = "Green capex totaled $50 million in FY2025, per the EU Taxonomy KPI table."
    page3 = "Page three covers governance topics unrelated to capex."
    full_text = "\n\n".join([page1, page2, page3])
    page_breaks = [0, len(page1) + 2, len(page1) + 2 + len(page2) + 2]

    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t",
        full_text=full_text, page_breaks=page_breaks, local_path="/data/documents/c1/sustainability_report/report.pdf",
    )
    citation = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Green capex totaled $50 million in FY2025")

    result = ground_citations([citation], {doc.doc_id: doc})[0]
    assert result.grounded is True
    assert result.page == 2
    assert result.company_id == "c1"
    assert result.source_filename == "report.pdf"


def test_ground_citations_resolves_sheet_from_verified_match_position():
    full_text = (
        "## Sheet: Overview\nCompany overview text goes here.\n\n"
        "## Sheet: EU Taxonomy\nCapex | 6912 | 92.6 | 1699 | 24.6\n\n"
        "## Sheet: Governance\nBoard composition details."
    )
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t", full_text=full_text,
    )
    citation = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Capex | 6912 | 92.6 | 1699 | 24.6")

    result = ground_citations([citation], {doc.doc_id: doc})[0]
    assert result.grounded is True
    assert result.sheet == "EU Taxonomy"
    assert result.page is None  # no page_breaks for an xlsx-derived document


def test_ungrounded_citation_gets_no_location_fields():
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t",
        full_text="Nothing about the hallucinated figure here.", page_breaks=[0],
        local_path="/data/documents/c1/sustainability_report/report.pdf",
    )
    citation = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Green capex reached $9 billion")

    result = ground_citations([citation], {doc.doc_id: doc})[0]
    assert result.grounded is False
    assert result.page is None
    assert result.sheet is None
    assert result.company_id is None
    assert result.source_filename is None


def test_ungrounded_citation_drops_llm_reported_location_fields():
    """Citation doubles as the LLM's draft schema, so the model can fill
    page/sheet/company_id/source_filename itself -- a citation that fails
    grounding must not keep those self-reported values."""
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t",
        full_text="Nothing about the hallucinated figure here.", page_breaks=[0],
    )
    citation = Citation(
        doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Green capex reached $9 billion",
        page=42, sheet="Capex", company_id="invented", source_filename="fake.pdf",
    )

    result = ground_citations([citation], {doc.doc_id: doc})[0]
    assert result.grounded is False
    assert result.page is None
    assert result.sheet is None
    assert result.company_id is None
    assert result.source_filename is None


def test_grounded_citation_from_non_local_document_has_no_filename():
    """EDGAR-sourced documents have no local_path -- page/company_id still
    resolve, but source_filename stays None (no regression, no broken
    'view source' link for a source with nothing to link to)."""
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="t",
        full_text="Green capex totaled $50 million in FY2025.", source_url="https://sec.gov/filing.htm",
    )
    citation = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Green capex totaled $50 million in FY2025.")

    result = ground_citations([citation], {doc.doc_id: doc})[0]
    assert result.grounded is True
    assert result.company_id == "c1"
    assert result.source_filename is None
    assert result.page is None


def test_one_document_is_normalized_once_however_many_citations_check_it():
    """The grounding hot path: `_normalize_with_offsets` walks the whole
    source text character by character, and `_find_match` calls it once per
    citation. Without the cache an extraction grounding twenty citations
    against one filing normalized that filing twenty times -- measured at
    531ms per pass on a 2.1MB 10-K, so ~10s of identical work per company.

    Asserted via cache_info rather than by timing, so it cannot flake on a
    slow or loaded machine."""
    from arp.grounding import _find_match, _normalize_with_offsets

    source = "The Company invested EUR 120 million in renewable capacity during fiscal 2024. " * 200
    quotes = [
        "INVESTED EUR 120 million in renewable capacity",  # not raw-exact: forces the normalised path
        "renewable CAPACITY during fiscal 2024",
        "the company invested EUR 120 MILLION",
    ]
    _normalize_with_offsets.cache_clear()

    verdicts = [_find_match(q, source, 0.92) is not None for q in quotes]

    assert all(verdicts), "these quotes differ from the source only in case"
    info = _normalize_with_offsets.cache_info()
    assert info.misses == 1, "the document should be normalized exactly once"
    assert info.hits == len(quotes) - 1


def test_the_cache_does_not_change_a_verdict_or_its_offset():
    """A cached normalization must be indistinguishable from a fresh one --
    same grounding verdict and the same resolved offset into the original
    text, since page/sheet resolution is derived from that offset."""
    from arp.grounding import _find_match, _normalize_with_offsets

    source = "Intro paragraph.\n\n  Green  capex  reached EUR 1.2bn  in 2024.\n\nOutro."
    quote = "Green capex reached EUR 1.2bn in 2024."

    _normalize_with_offsets.cache_clear()
    first = _find_match(quote, source, 0.92)
    second = _find_match(quote, source, 0.92)  # served from cache

    assert first == second
    assert first is not None
    assert source[first.char_start :].startswith("Green")


# --- E43: span evidence and passage binding ---------------------------------
from arp.extraction.extractor_agent import format_evidence  # noqa: E402
from arp.schemas.common import DocumentChunk  # noqa: E402

_A = "Alpha section: green capex totaled $50 million in FY2025."
_B = "Beta section: transition spend reached EUR 9 million in FY2024."
_C = "Gamma section: unrelated filler text about governance."


def _two_chunk_doc():
    text = f"{_A}\n\n{_B}\n\n{_C}"
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="t", full_text=text,
        content_key="ck1", parser_version="pv1",
    )

    def chunk(t):
        s = text.index(t)
        return DocumentChunk(doc_id=doc.doc_id, company_id="c1", doc_type=doc.doc_type, text=t, char_start=s, char_end=s + len(t))

    return doc, chunk(_A), chunk(_B), chunk(_C)


def test_grounded_citation_carries_span_and_offsets():
    doc, a, _b, _c = _two_chunk_doc()
    cit = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="green capex totaled $50 million")
    c = ground_citations([cit], {doc.doc_id: doc})[0]
    assert c.grounded
    assert doc.full_text[c.char_start : c.char_end] == c.span_text
    assert c.match_method == "exact" and c.match_score == 1.0
    assert c.content_key == doc.content_key and c.parser_version == doc.parser_version


def test_quote_from_unseen_passage_is_ungrounded():
    doc, a, _b, _c = _two_chunk_doc()
    cit = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="transition spend reached EUR 9 million")
    c = ground_citations([cit], {doc.doc_id: doc}, passages={a.chunk_id: a})[0]
    assert c.grounded is False
    assert c.char_start is None and c.span_text is None and c.content_key is None


def test_wrong_passage_id_corrected_to_shown_passage():
    doc, a, _b, c_ = _two_chunk_doc()
    cit = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="green capex totaled $50 million", passage_id=c_.chunk_id)
    c = ground_citations([cit], {doc.doc_id: doc}, passages={a.chunk_id: a, c_.chunk_id: c_})[0]
    assert c.grounded and c.passage_id == a.chunk_id


def test_ungrounded_keeps_reported_passage_id():
    doc, a, _b, _c = _two_chunk_doc()
    cit = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="nonexistent quote text here", passage_id="x")
    c = ground_citations([cit], {doc.doc_id: doc}, passages={a.chunk_id: a})[0]
    assert not c.grounded and c.passage_id == "x"


def test_without_passages_searches_whole_document():
    doc, _a, _b, _c = _two_chunk_doc()
    cit = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="transition spend reached EUR 9 million")
    assert ground_citations([cit], {doc.doc_id: doc})[0].grounded


def test_format_evidence_includes_passage_id():
    _doc, a, _b, _c = _two_chunk_doc()
    assert f"passage_id={a.chunk_id}" in format_evidence([a])


def test_old_citation_json_loads():
    c = Citation.model_validate({
        "doc_id": "d", "doc_type": "10-K", "quote": "q", "location": None, "grounded": True,
        "page": 1, "sheet": None, "company_id": "c", "source_filename": "f.pdf",
    })
    assert c.char_start is None and c.match_method is None and c.passage_id is None


# --- E44: robust matching -------------------------------------------------

from arp.grounding import _normalize_with_offsets  # noqa: E402


def _ground(quote, text):
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="t", full_text=text)
    cit = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)
    return doc, ground_citations([cit], {doc.doc_id: doc})[0]


def test_hyphen_split_number_grounds():
    text = "Scope 1 emissions of 12,3-\n45 tCO2e in 2023"
    doc, c = _ground("emissions of 12,345 tCO2e", text)
    assert c.grounded and c.match_method == "normalised"
    assert c.span_text.startswith("emissions of 12,3-")
    assert c.span_text == text[c.char_start : c.char_end]


def test_word_hyphenation_grounds():
    text = "Total emis-\nsions fell sharply in 2023 versus prior year."
    doc, c = _ground("total emissions fell sharply in 2023", text)
    assert c.grounded and c.match_method == "normalised"
    assert c.span_text == text[c.char_start : c.char_end]


def test_repeated_quote_picks_cited_passage():
    q = "Scope 1 emissions: 4,210 tCO2e"
    a, b = f"Section A. {q} in 2023.", f"Section B. {q} again."
    text = f"{a}\n\n{b}"
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="t", full_text=text)

    def chunk(t):
        s = text.index(t)
        return DocumentChunk(doc_id=doc.doc_id, company_id="c1", doc_type=doc.doc_type, text=t, char_start=s, char_end=s + len(t))

    ca, cb = chunk(a), chunk(b)
    cit = Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=q, passage_id=cb.chunk_id)
    c = ground_citations([cit], {doc.doc_id: doc}, passages={ca.chunk_id: ca, cb.chunk_id: cb})[0]
    assert c.grounded and c.passage_id == cb.chunk_id
    assert cb.char_start <= c.char_start < cb.char_end


def test_typographic_variants_normalise():
    text = "the e\ufb03cient – “net zero” 2030 tar­get"
    doc, c = _ground('the efficient - "net zero" 2030 target', text)
    assert c.grounded and c.match_method == "normalised"
    assert c.span_text == text[c.char_start : c.char_end] == text
    # and the reverse: variants in the quote, plain source
    doc, c = _ground(text, 'the efficient - "net zero" 2030 target')
    assert c.grounded and c.match_method == "normalised"


def test_minus_and_other_dashes_curly_apostrophe():
    text = "Net change − 5.2 million—the firm’s result ‒ final"
    doc, c = _ground("net change - 5.2 million-the firm's result - final", text)
    assert c.grounded and c.match_method == "normalised"
    assert c.span_text == text[c.char_start : c.char_end]


def test_normalised_offsets_with_extra_whitespace_and_zero_width():
    pre = "Intro.   "
    body = "Green​  capex\n\ttotalled   $50 million"
    text = pre + body + " trailing"
    doc, c = _ground("green capex totalled $50 million", text)
    assert c.match_method == "normalised"
    assert (c.char_start, c.char_end) == (len(pre), len(pre) + len(body))
    assert c.span_text == body


def test_fuzzy_match_span_is_original_slice():
    text = "Intro ﬁrst   line.\n" + "The company reported green capex of $500 million during the year" + " tail"
    doc, c = _ground("the company reported green capex of $500 million during the yeer", text)
    assert c.grounded and c.match_method == "fuzzy"
    assert c.span_text == text[c.char_start : c.char_end]
    assert c.span_text.startswith("The company")


def test_multichar_lowercase_keeps_offsets_aligned():
    text = "İstanbul office emitted 1,200 tCO2e in 2023"
    norm, offs = _normalize_with_offsets(text)
    assert len(norm) == len(offs)
    assert offs[0] == offs[1] == 0 and offs[2] == 1  # both chars of lower(U+0130) map to the İ
    i = norm.index("office")
    assert text[offs[i]] == "o"
    _, c = _ground("office emitted 1,200 tCO2e", text)
    assert c.grounded and c.span_text == "office emitted 1,200 tCO2e"
    assert text[c.char_start : c.char_end] == c.span_text


def test_ligature_expansion_maps_to_ligature_offset():
    text = "x ﬃ y"
    norm, offs = _normalize_with_offsets(text)
    assert norm == "x ffi y" and offs[2:5] == [2, 2, 2]


def test_short_bare_number_rejected():
    assert not is_grounded("42", "Total was 42 units across sites.")


def test_short_number_with_label_grounds():
    assert is_grounded("42 MWh", "Consumption was 42 MWh across sites.")


def test_short_non_numeric_quote_grounds_exactly():
    assert is_grounded("Yes", "Board oversight of climate: Yes. Next row.")
    assert is_grounded("Not applicable", "Scope 3 reporting:  not\napplicable for this entity.")


def test_short_non_numeric_quote_never_fuzzy():
    assert not is_grounded("Yes", "Board oversight of climate: Yse.")
    assert not is_grounded("Yes", "Board oversight of climate: No.")


def test_short_numeric_with_unit_grounds():
    assert is_grounded("42 tCO2e", "Total was 42 tCO2e this year.")


def test_short_quote_never_fuzzy():
    assert not is_grounded("43 MWx", "Consumption was 43 MWh across sites.")
