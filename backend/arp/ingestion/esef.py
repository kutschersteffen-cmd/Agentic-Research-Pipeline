"""European ESEF filings (E16): an inline XBRL (iXBRL) annual report as visible text, plus the
`ix:nonFraction` facts it tags with the exact char span each one is printed at, so a tagged value
cites a real span of a stored original."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import io
import logging
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin

import httpx
from lxml import etree

from arp.ingestion.base import DocumentSource
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.xbrl import XbrlFact, _full_year
from arp.normalise.locale import context_decimal, decimal_for, detect_language
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.storage.document_blob_store import CaptureStoreError
from arp.storage.document_store import DocumentContentStore, derive_doc_id
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

logger = logging.getLogger(__name__)

ESEF_SUFFIXES = {".xhtml", ".zip"}
_IX = "http://www.xbrl.org/2013/inlineXBRL"
_XBRLI = "{http://www.xbrl.org/2003/instance}"
_XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
_SKIP = {"head", "script", "style"}
_BLOCK = {
    "p", "div", "br", "hr", "table", "tr", "thead", "tbody", "tfoot", "caption", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer", "blockquote", "pre",
}
_CELL = {"td", "th"}
_WS = re.compile(r"\s+")
# ixt formats, every registry version (v1 names, v2 names, v3+ hyphenated names with the hyphens dropped).
_DOT_DECIMAL = {"", "numdotdecimal", "numcommadot", "numspacedot"}
_COMMA_DECIMAL = {"numcommadecimal", "numdotcomma", "numspacecomma"}
_ZERO = {"fixedzero", "zerodash"}

# Bump whenever parse_ixbrl's text or fact logic changes.
_ESEF_PARSER_LOGIC_VERSION = 1


@functools.lru_cache(maxsize=1)
def esef_parser_version() -> str:
    try:
        lxml = _pkg_version("lxml")
    except PackageNotFoundError:
        lxml = "unknown"
    return f"esef={_ESEF_PARSER_LOGIC_VERSION}|lxml={lxml}"


@dataclass(frozen=True)
class EsefFact:
    concept: str
    value: float
    unit: str | None
    period_start: str | None
    period_end: str
    decimals: str | None
    char_start: int
    char_end: int
    printed: str
    scale: int = 0
    decimal: str | None = None  # "point" or "comma", from the ixt format


def _visible_text(root) -> tuple[str, dict]:
    """The page text (whitespace collapsed, blocks on their own lines, cells joined by " | ")
    and each ix:nonFraction element's (start, end) in it. ix:header -- with ix:hidden
    and the contexts -- is not page text, so hidden facts get no span."""
    out: list[str] = []
    n = 0
    spans: dict = {}

    def emit(s: str) -> None:
        nonlocal n
        s = _WS.sub(" ", s)
        if not out or out[-1].endswith("\n"):
            s = s.lstrip()
        if s:
            out.append(s)
            n += len(s)

    def brk() -> None:
        nonlocal n
        if out and not out[-1].endswith("\n"):
            out.append("\n")
            n += 1

    def walk(el) -> None:
        if not isinstance(el.tag, str):  # comment or processing instruction
            return
        q = etree.QName(el)
        if q.localname in _SKIP or (q.namespace == _IX and q.localname == "header"):
            return
        if q.localname in _BLOCK:
            brk()
        elif q.localname in _CELL and out and not out[-1].endswith("\n"):
            emit(" | ")
        start = n
        if el.text:
            emit(el.text)
        for child in el:
            walk(child)
            if child.tail:
                emit(child.tail)
        if q.namespace == _IX and q.localname == "nonFraction":
            spans[el] = (start, n)
        if q.localname in _BLOCK:
            brk()

    walk(root)
    return "".join(out), spans


def _format_name(fmt: str | None) -> str:
    return (fmt or "").rpartition(":")[2].replace("-", "").lower()


def _number(text: str, fmt: str | None) -> Decimal | None:
    """The printed number per its ixt format; None for a format this does not read."""
    name = _format_name(fmt)
    if name in _ZERO:
        return Decimal(0)
    if name in _DOT_DECIMAL:
        s = re.sub(r"[^\d.]", "", text)
    elif name in _COMMA_DECIMAL:
        s = re.sub(r"[^\d,]", "", text).replace(",", ".")
    else:
        return None
    return Decimal(s) if re.fullmatch(r"\d+(\.\d+)?", s) else None


def _date(el, tag: str) -> str | None:
    v = el.findtext(_XBRLI + tag)
    return v.strip()[:10] if v and v.strip() else None


def _contexts(root) -> dict[str, tuple[str | None, str]]:
    out = {}
    for ctx in root.iter(_XBRLI + "context"):
        # ponytail: dimensional (segment/scenario) facts are left out, not totals; carry dimensions if a field needs them
        if ctx.find(f".//{_XBRLI}segment") is not None or ctx.find(f".//{_XBRLI}scenario") is not None:
            continue
        period = ctx.find(_XBRLI + "period")
        if period is None:
            continue
        end = _date(period, "endDate") or _date(period, "instant")
        if end:
            out[ctx.get("id")] = (_date(period, "startDate"), end)
    return out


def _units(root) -> dict[str, str]:
    def measures(el) -> str:
        return "*".join(m.text.strip().rpartition(":")[2] for m in el.iter(_XBRLI + "measure") if m.text)

    out = {}
    for u in root.iter(_XBRLI + "unit"):
        num, den = u.find(f".//{_XBRLI}unitNumerator"), u.find(f".//{_XBRLI}unitDenominator")
        out[u.get("id")] = f"{measures(num)}/{measures(den)}" if num is not None and den is not None else measures(u)
    return out


def parse_ixbrl(xhtml: bytes) -> tuple[str, list[EsefFact]]:
    """Visible text and the printed, non-dimensional ix:nonFraction facts in it, in document
    order, with `scale`, `sign` and `format` applied. `text[f.char_start:f.char_end] == f.printed`."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(xhtml, parser=parser)
    text, spans = _visible_text(root)
    contexts, units = _contexts(root), _units(root)
    facts = []
    for el, (a, b) in sorted(spans.items(), key=lambda kv: kv[1]):
        printed = text[a:b]
        a += len(printed) - len(printed.lstrip())
        b -= len(printed) - len(printed.rstrip())
        period = contexts.get(el.get("contextRef"))
        num = _number("".join(el.itertext()), el.get("format"))
        if period is None or num is None or a >= b or el.get(_XSI_NIL) == "true":
            continue
        value = num.scaleb(int(el.get("scale") or 0))
        facts.append(EsefFact(
            concept=el.get("name"), value=float(-value if el.get("sign") == "-" else value), unit=units.get(el.get("unitRef")),
            period_start=period[0], period_end=period[1], decimals=el.get("decimals"), char_start=a, char_end=b,
            printed=text[a:b], scale=int(el.get("scale") or 0),
            decimal="comma" if _format_name(el.get("format")) in _COMMA_DECIMAL else "point",
        ))
    return text, facts


def parse_package(data: bytes) -> tuple[str, list[EsefFact]]:
    """An ESEF report package (zip): parse_ixbrl of its largest reports/*.xhtml."""
    from arp.holdings.file_source import _check_zip

    _check_zip(data)  # the holdings intake's decompressed-size cap: a zip bomb raises ValueError
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        reports = [i for i in z.infolist()
                   if PurePosixPath(i.filename).parent.name == "reports" and i.filename.lower().endswith((".xhtml", ".html"))]
        if not reports:
            raise ValueError("not an ESEF report package: no reports/*.xhtml")
        return parse_ixbrl(z.read(max(reports, key=lambda i: i.file_size)))


def parse_file(path: Path) -> tuple[str, list[EsefFact]]:
    data = path.read_bytes()
    return parse_package(data) if path.suffix.lower() == ".zip" else parse_ixbrl(data)


def _precision(f: EsefFact) -> float:
    d = (f.decimals or "").strip()
    if d == "INF":
        return float("inf")
    try:
        return int(d)
    except ValueError:
        return float("-inf")


_SCALE_WORDS = {0: "", 3: "thousand", 6: "million", 9: "billion"}


class EsefXbrlFact(XbrlFact):
    """An ESEF fact: it cites the span it is printed at in the stored filing."""

    citation: Citation
    scale: int = 0
    decimal: str | None = None

    def reported(self) -> tuple[float, str, str, str]:
        """The number as printed ("1,234.5" EUR million), so the layer-2 checks read the
        printed span and its caption scale; a scale with no word falls back to the tagged value."""
        word = _SCALE_WORDS.get(self.scale)
        if word is None or self.decimal is None:
            return super().reported()
        value = float(Decimal(repr(self.value)).scaleb(-self.scale))
        return value, self.citation.quote, f"{self.unit} {word}".strip(), self.decimal

    def as_citation(self, cik: str | None = None) -> Citation:
        return self.citation


class EsefFactSource:
    """FactSource over one ESEF filing's facts. Tags are the concept names as the filing writes
    them ("ifrs-full:Revenue")."""

    def __init__(self, facts: list[EsefFact], doc: SourceDocument) -> None:
        # A fact whose span the document's text does not print (text from another parse) is not citable.
        self.facts = [f for f in facts if doc.full_text[f.char_start:f.char_end] == f.printed]
        self.doc = doc

    def fact_for_tags(self, tags: list[str], *, fiscal_year: int) -> XbrlFact | None:
        """Like XbrlFactSource.fact_for_tags: a full-year duration (or an instant) ending in
        `fiscal_year`, for the first tag that has one; of duplicates the most precise."""
        for tag in tags:
            hits = [f for f in self.facts if f.concept == tag and f.period_end[:4] == str(fiscal_year)
                    and _full_year({"start": f.period_start, "end": f.period_end})]
            if hits:
                return self._fact(max(hits, key=_precision), fiscal_year)
        return None

    def _fact(self, f: EsefFact, fiscal_year: int) -> EsefXbrlFact:
        doc = self.doc
        citation = Citation(
            doc_id=doc.doc_id, doc_type=doc.doc_type, quote=f.printed, location=f"ESEF iXBRL {f.concept}", grounded=True,
            company_id=doc.company_id, source_filename=Path(doc.local_path).name if doc.local_path else None,
            content_key=doc.content_key, parser_version=doc.parser_version, span_text=f.printed,
            char_start=f.char_start, char_end=f.char_end, match_method="exact",
        )
        return EsefXbrlFact(
            tag=f.concept, value=f.value, unit=f.unit or "", fiscal_year=fiscal_year, fiscal_period="FY", form="ESEF",
            period_start=f.period_start, period_end=f.period_end, citation=citation, scale=f.scale, decimal=f.decimal,
        )


def esef_fact_sources(docs: list[SourceDocument]) -> list[EsefFactSource]:
    """A fact source per ESEF filing (.xhtml or .zip on disk) among `docs`. Blocking."""
    out = []
    for d in docs:
        if not d.local_path or Path(d.local_path).suffix.lower() not in ESEF_SUFFIXES:
            continue
        try:
            _, facts = parse_file(Path(d.local_path))
        except Exception as exc:  # noqa: BLE001 - an unreadable filing has no facts; its fields are extracted
            logger.warning("ESEF facts unavailable from %s: %s", d.local_path, exc)
            continue
        if facts:
            out.append(EsefFactSource(facts, d))
    return out


class EsefDocumentSource(DocumentSource):
    """The latest ESEF annual report of a company with an LEI, from a filings.xbrl.org-style
    index (`GET {index_url}/api/entities/{lei}/filings`, JSON:API with `package_url`)."""

    name = "esef"

    def __init__(
        self,
        index_url: str,
        cache_dir: Path,
        *,
        client: httpx.AsyncClient | None = None,
        content_store: DocumentContentStore | None = None,
        indexing_config: IndexingConfig | None = None,
    ) -> None:
        self._index_url = index_url.rstrip("/")
        self._dir = cache_dir / "esef"
        self._client = client
        self._content_store = content_store
        self._indexing_config = indexing_config

    async def fetch(self, company: CompanyRef, doc_types: list[DocType] | None = None) -> list[SourceDocument]:
        if not company.lei or (doc_types and DocType.ANNUAL_REPORT_10K not in doc_types):
            return []
        try:
            safe_id(company.company_id, label="company_id")
        except UnsafeIdentifierError:
            logger.warning("Rejected unsafe company_id in ESEF fetch: %r", company.company_id)
            return []
        if self._client is not None:
            return await self._fetch(self._client, company)
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            return await self._fetch(client, company)

    async def _fetch(self, client: httpx.AsyncClient, company: CompanyRef) -> list[SourceDocument]:
        resp = await client.get(f"{self._index_url}/api/entities/{company.lei}/filings")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        filings = [d.get("attributes") or {} for d in resp.json().get("data") or []]
        filings = [f for f in filings if f.get("package_url")]
        if not filings:
            return []
        latest = max(filings, key=lambda f: f.get("period_end") or "")
        url = urljoin(self._index_url + "/", latest["package_url"])
        pkg = await client.get(url)
        pkg.raise_for_status()
        raw = pkg.content
        text, facts = await asyncio.to_thread(parse_package, raw)
        if not text.strip():
            return []
        content_key = hashlib.sha256(raw).hexdigest()
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{content_key}.zip"  # the local copy esef_fact_sources reads the facts from
        if not path.exists():
            path.write_bytes(raw)
        language = detect_language(text)
        doc_type = DocType.ANNUAL_REPORT_10K
        title = f"{company.name} ESEF annual report ({latest.get('period_end')})"
        kwargs: dict = dict(
            company_id=company.company_id, doc_type=doc_type, title=title, source_url=url, local_path=str(path),
            fiscal_period=latest.get("period_end"), full_text=text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            language=language,
            # The printed numbers prove the mark (European filings often print a decimal comma); else the language's.
            decimal=context_decimal([f.printed for f in facts]) or decimal_for(language),
        )
        if self._content_store is not None:
            store = self._content_store
            kwargs["content_key"] = content_key
            kwargs["parser_version"] = esef_parser_version()
            kwargs["doc_id"] = store.register_document(
                doc_id=derive_doc_id(company.company_id, doc_type.value, content_key), company_id=company.company_id,
                doc_type=doc_type.value, content_key=content_key, title=title, local_path=str(path), source_url=url,
            )
            if store.lookup(content_key, esef_parser_version()) is None:  # the text the publish gate re-grounds against
                store.store(content_key, key_kind="esef_package", parser_version=esef_parser_version(), source_suffix=".zip",
                            byte_size=len(text.encode("utf-8")), text=text, page_breaks=[])
            if self._indexing_config is not None:
                try:
                    self._index_and_archive(kwargs["doc_id"], company.company_id, title, content_key, text, raw, url, path)
                except CaptureStoreError as exc:  # not collected: no verified copy of the original bytes
                    logger.warning("ESEF filing %s not collected: %s", url, exc)
                    return []
        return [SourceDocument(**kwargs)]

    def _index_and_archive(
        self, doc_id: str, company_id: str, title: str, content_key: str, text: str, raw: bytes, url: str, path: Path
    ) -> None:
        """Mirrors EdgarDocumentSource._index_and_archive; the blob key is the content_key (sha256 of the bytes)."""
        from arp.retrieval.search_indexer import index_document_if_enabled
        from arp.storage.document_blob_store import blob_store_for, upload_or_fail
        from arp.storage.document_registry import StoredDocumentRef
        from arp.storage.postgres_document_projection import sync_document_if_enabled

        cfg = self._indexing_config
        doc_type = DocType.ANNUAL_REPORT_10K
        index_document_if_enabled(cfg, doc_id=doc_id, company_id=company_id, doc_type=doc_type, title=title, full_text=text)
        storage_uri = upload_or_fail(blob_store_for(cfg), content_key, raw)
        self._content_store.set_storage_uri(doc_id, storage_uri)
        sync_document_if_enabled(cfg, StoredDocumentRef(
            doc_id=doc_id, company_id=company_id, doc_type=doc_type.value, content_key=content_key,
            title=title, local_path=str(path), source_url=url, storage_uri=storage_uri,
        ))
