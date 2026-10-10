import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { InspectorModal } from "../components/InspectorModal";
import type { CompanyFactRow, CompanySearchHit, CompanySummary, FactCitation, FactTrail } from "../types";
import { FactsTable } from "./company/FactsTable";
import { FactTrailPanel } from "./company/FactTrailPanel";
import { STATUS_TEXT, encodeRef, type FactFilters } from "./company/companyQuery";

// ponytail: one page of 500 facts (the API maximum); add paging when a company carries more.
const LIMIT = 500;

interface RegisteredDoc { doc_id: string; doc_type: string; local_path: string | null; source_url: string | null }

/** `#/companies/<ref>`: one company, its current (or as-of) facts and each fact's trail.
 * Without a ref it is a company search. */
export function Company({ companyRef }: { companyRef?: string }) {
  return companyRef ? <CompanyView key={companyRef} companyRef={companyRef} /> : <CompanySearch />;
}

function CompanySearch() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<CompanySearchHit[] | null>(null);
  const [error, setError] = useState("");
  return (
    <div className="page">
      <h1>Company</h1>
      <p className="muted">Find a company by name or identifier to see its facts and where each one came from.</p>
      <form
        className="inline-fields"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setError("");
          api.searchCompanies(q).then(setHits, (err: Error) => setError(err.message));
        }}
      >
        <label className="field-label inline-label">
          Name or identifier
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Siemens, LEI…" />
        </label>
        <button type="submit">Search</button>
      </form>
      {error && <p className="error-text" role="alert">{error}</p>}
      {hits && (hits.length === 0 ? <p className="muted" role="status">No company matches “{q}”.</p> : (
        <ul className="company-hits">
          {hits.map((h) => (
            <li key={h.id}>
              <a href={`#/companies/${encodeRef(h.id)}`}>{h.name}</a>
              <span className="muted mono"> {[h.country, h.sector].filter(Boolean).join(" · ")}</span>
            </li>
          ))}
        </ul>
      ))}
    </div>
  );
}

function CompanyView({ companyRef }: { companyRef: string }) {
  const [company, setCompany] = useState<CompanySummary | null>(null);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState<FactFilters>({});
  const [rows, setRows] = useState<CompanyFactRow[] | null>(null);
  const [rowsError, setRowsError] = useState("");
  const [fieldIds, setFieldIds] = useState<string[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [trail, setTrail] = useState<FactTrail | null>(null);
  const [trailError, setTrailError] = useState("");
  const [viewer, setViewer] = useState<{ title: string; src: string } | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const docs = useRef<Promise<RegisteredDoc[]> | null>(null);

  useEffect(() => {
    api.getCompany(companyRef).then(
      (c) => {
        setCompany(c);
        document.title = `${c.name} · ARP`;
      },
      (err: Error) => setError(err.message.startsWith("404") ? "notfound" : err.message),
    );
  }, [companyRef]);

  useEffect(() => {
    let live = true;
    setRowsError("");
    api.getCompanyFacts(companyRef, { ...filters, limit: LIMIT }).then(
      (r) => {
        if (!live) return;
        setRows(r);
        // Fields seen so far stay pickable after narrowing to one.
        setFieldIds((known) => [...new Set([...known, ...r.map((x) => x.field_id)])].sort());
      },
      (err: Error) => live && setRowsError(err.message),
    );
    return () => {
      live = false;
    };
  }, [companyRef, filters]);

  useEffect(() => {
    if (selected == null) return;
    let live = true;
    setTrail(null);
    setTrailError("");
    api.getFactTrail(selected).then(
      (t) => live && setTrail(t),
      (err: Error) => live && setTrailError(err.message),
    );
    return () => {
      live = false;
    };
  }, [selected]);

  const closeTrail = useCallback(() => {
    setSelected(null);
    opener.current?.focus();
  }, []);

  const universeId = company?.identifiers.find((i) => i.scheme === "UNIVERSE" && !i.valid_to)?.value;

  /** A citation opens the stored document at its page, through the same raw-file route review uses. */
  async function openCitation(c: FactCitation) {
    setTrailError("");
    try {
      if (!universeId) throw new Error("This company has no universe id, so its documents cannot be listed.");
      docs.current ??= api.listDocuments(universeId).then((r) => (r as { registered: RegisteredDoc[] }).registered);
      const doc = (await docs.current).find((d) => d.doc_id === c.doc_id);
      const filename = doc?.local_path?.split(/[\\/]/).pop();
      if (doc && filename) {
        setViewer({ title: `${c.title}${c.page != null ? ` — p. ${c.page}` : ""}`, src: `${api.documentRawUrl(universeId, doc.doc_type, filename)}${c.page != null ? `#page=${c.page}` : ""}` });
      } else if (doc?.source_url && /^https?:\/\//i.test(doc.source_url)) {
        window.open(doc.source_url, "_blank", "noopener");
      } else {
        throw new Error(`“${c.title}” has no stored file to open.`);
      }
    } catch (err) {
      docs.current = null;
      setTrailError((err as Error).message);
    }
  }

  const set = (patch: FactFilters) => setFilters((f) => ({ ...f, ...patch }));

  if (error === "notfound") {
    return (
      <div className="page">
        <h1>Company not found</h1>
        <p className="muted">
          No company matches <span className="mono">{companyRef}</span>. <a href="#/companies">Search for a company</a>
        </p>
      </div>
    );
  }

  const counts = company ? Object.entries(company.fact_counts).filter(([, n]) => n) : [];

  return (
    <div className="page company-page">
      <h1>{company?.name ?? companyRef}</h1>
      {error && <p className="error-text" role="alert">{error}</p>}
      {company && (
        <>
          <p className="muted company-meta">
            {[company.country, company.sector, company.isic_code && `ISIC ${company.isic_code}`, company.fiscal_year_end && `FY ends ${company.fiscal_year_end}`, ...company.regimes]
              .filter(Boolean)
              .join(" · ") || "No country or sector recorded"}
          </p>
          <dl className="company-ids">
            {company.identifiers.filter((i) => !i.valid_to).map((i) => (
              <div key={`${i.scheme}:${i.value}`}>
                <dt>{i.scheme}</dt>
                <dd className="mono">{i.value}</dd>
              </div>
            ))}
          </dl>
          <dl className="company-counts">
            {counts.map(([status, n]) => (
              <div key={status} className={status === "pending_review" ? "awaiting" : undefined}>
                <dt>{STATUS_TEXT[status as CompanyFactRow["status"]]}</dt>
                <dd>{n}</dd>
              </div>
            ))}
            <div className={company.open_review_items ? "awaiting" : undefined}>
              <dt>{company.open_review_items ? <a href="#/review">open review items</a> : "open review items"}</dt>
              <dd>{company.open_review_items}</dd>
            </div>
            <div><dt>documents</dt><dd>{company.documents}</dd></div>
            <div><dt>runs</dt><dd>{company.runs}</dd></div>
          </dl>
          {company.holders_available && company.holders.length > 0 && (
            <p className="muted">
              Held in{" "}
              {company.holders.map((h, i) => (
                <span key={`${h.kind}:${h.holder_id}`} className="mono">
                  {i > 0 && ", "}
                  {h.holder_id}{h.weight_pct != null && ` ${h.weight_pct.toFixed(2)}%`}
                </span>
              ))}{" "}
              <span>(as of {company.holders[0].as_of_date})</span>
            </p>
          )}
        </>
      )}

      <div className={selected != null ? "split-review" : undefined}>
        <section className="split-review-main" aria-labelledby="facts-heading">
          <h2 id="facts-heading">Facts</h2>
          <form className="inline-fields company-filters" onSubmit={(e) => e.preventDefault()}>
            <label className="field-label inline-label">
              Kind
              <select value={filters.kind ?? ""} onChange={(e) => set({ kind: e.target.value })}>
                <option value="">All</option>
                <option value="extracted">Extracted</option>
                <option value="provider">Provider</option>
              </select>
            </label>
            <label className="field-label inline-label">
              Field
              <select value={filters.fieldId ?? ""} onChange={(e) => set({ fieldId: e.target.value })}>
                <option value="">All</option>
                {fieldIds.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
            </label>
            <label className="field-label inline-label">
              Period end
              <input type="date" value={filters.periodEnd ?? ""} onChange={(e) => set({ periodEnd: e.target.value })} />
            </label>
            <label className="field-label inline-label">
              As of
              <input type="date" value={filters.asOf ?? ""} onChange={(e) => set({ asOf: e.target.value })} />
            </label>
            {Object.values(filters).some(Boolean) && (
              <button type="button" className="link-button" onClick={() => setFilters({})}>Clear filters</button>
            )}
          </form>
          <p className="muted" role="status">
            {rowsError ? "" : rows == null ? "Loading…" : `${rows.length}${rows.length === LIMIT ? "+" : ""} ${rows.length === 1 ? "fact" : "facts"}${filters.asOf ? ` as they stood on ${filters.asOf}` : ", current values"}`}
          </p>
          {rowsError && <p className="error-text" role="alert">{rowsError}</p>}
          {rows && rows.length > 0 && (
            <FactsTable
              rows={rows}
              selected={selected}
              onSelect={(id, el) => {
                opener.current = el;
                setSelected(id === selected ? null : id);
              }}
            />
          )}
        </section>
        {selected != null && <FactTrailPanel trail={trail} error={trailError} onClose={closeTrail} onOpenCitation={openCitation} />}
      </div>
      {viewer && <InspectorModal title={viewer.title} src={viewer.src} onClose={() => setViewer(null)} />}
    </div>
  );
}
