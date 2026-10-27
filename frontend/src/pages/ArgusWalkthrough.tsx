import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { StepTabs } from "../components/StepTabs";
import { correctionLine } from "../lib/corrections";
import { valueLabel } from "../lib/fieldValue";
import { listAllRuns } from "../lib/poll";
import { runTypeLabel } from "../lib/runs";
import { allCitations, fmt, markQuotes, notRecordedNote, passageFor, parseWalkthroughParams, pickRow, planBasis, steps, walkthroughHref, type Step } from "../lib/walkthrough";
import type { Correction, ExtractedField, RunManifest, Walkthrough, WalkthroughPassage } from "../types";

type Obj = Record<string, unknown>;
type Rec = { company_id: string; name?: string; schema_id?: string; needs_review?: boolean; fields?: ExtractedField[] };

const RUN_TYPES = new Set(["extraction", "financials", "tnfd"]);
const SECTIONS: Record<string, [string, string][]> = {
  financials: [["segments", "Segments"], ["capex", "CapEx"], ["rnd", "R&D"]],
  tnfd: [["disclosures", "Disclosures"], ["core_global_metrics", "Core global metrics"], ["sector_metrics", "Sector metrics"],
    ["general_requirements", "General requirements"], ["sector_leap_considerations", "Sector LEAP considerations"]],
};
// shortcut: the API does not serve retention_runs_days, so the note uses its default; serve it if it is ever changed.
const RETENTION_DAYS = 3650;
const PAGE = 500;

const obj = (v: unknown): Obj => (v && typeof v === "object" ? (v as Obj) : {});
const list = (v: unknown): Obj[] => (Array.isArray(v) ? v.map(obj) : []);
const conf = (v: unknown) => (typeof v === "number" ? v.toFixed(2) : "—");
const str = (v: unknown) => (v == null || v === "" ? "—" : typeof v === "object" ? JSON.stringify(v) : fmt(v));

async function loadRecords(run: RunManifest): Promise<Rec[]> {
  const page = (o: number) =>
    (run.run_type === "financials" ? api.getFinancialsResults(run.run_id, o, PAGE)
      : run.run_type === "tnfd" ? api.getTnfdResults(run.run_id, o, PAGE)
      : api.getExtractionResults(run.run_id, o, PAGE)) as Promise<{ total: number; results: Rec[] }>;
  const out: Rec[] = [];
  for (let o = 0; ; o += PAGE) {
    const r = await page(o);
    out.push(...r.results);
    if (out.length >= r.total || !r.results.length) return out;
  }
}

function fieldOptions(run: RunManifest, rec: Rec): { label: string; href: string }[] {
  const sections = SECTIONS[run.run_type];
  if (sections) return sections.map(([id, label]) => ({ label, href: walkthroughHref(run.run_id, rec.company_id, id) }));
  return (rec.fields ?? []).map((f) => {
    const basis = planBasis(rec.schema_id, f);
    return {
      label: [f.field_name, basis, f.period_end ? f.period_end.slice(0, 4) : "no period"].filter(Boolean).join(" · "),
      href: walkthroughHref(run.run_id, rec.company_id, f.field_id, f.period_end ?? null, basis),
    };
  });
}

const runLabel = (r: RunManifest) =>
  [runTypeLabel(r.run_type), typeof r.params?.schema_name === "string" ? r.params.schema_name : null, r.created_at.slice(0, 10), r.run_id]
    .filter(Boolean).join(" · ");

/** Argus › Walkthrough: every step one stored value went through, from document to route. Reads only. */
export function ArgusWalkthrough({ params }: { params: string[] }) {
  const route = parseWalkthroughParams(params);
  const [runs, setRuns] = useState<RunManifest[] | null>(null);
  const [runId, setRunId] = useState(route.runId ?? "");
  const [records, setRecords] = useState<Rec[] | null>(null);
  const [companyId, setCompanyId] = useState(route.companyId ?? "");
  const [w, setW] = useState<Walkthrough | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    listAllRuns()
      .then((all) => setRuns(all.filter((r) => RUN_TYPES.has(r.run_type)).sort((a, b) => (a.created_at < b.created_at ? 1 : -1))))
      .catch((e) => setError((e as Error).message));
    if (route.runId && route.companyId && route.item) {
      api.getWalkthrough(route.runId, route.companyId, { item: route.item, period_end: route.periodEnd, basis: route.basis })
        .then(setW)
        .catch((e) => setError((e as Error).message));
    }
    // Mounted once per route: App keys this page by the route.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = runs?.find((r) => r.run_id === runId);
  useEffect(() => {
    if (!run) return;
    let live = true;
    setRecords(null);
    loadRecords(run).then((r) => live && setRecords(r)).catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
  }, [run]);

  const rec = records?.find((r) => r.company_id === companyId);
  const options = run && rec ? fieldOptions(run, rec) : [];
  const onRoute = runId === route.runId && companyId === route.companyId;
  const current = onRoute && route.item ? walkthroughHref(runId, companyId, route.item, route.periodEnd, route.basis) : "";

  return (
    <div className="page">
      <h1>Walkthrough</h1>
      <p className="help-text">
        How one stored value was found: each step from document to route, what each model answered and what the code
        checked. Review decisions are not shown here.
      </p>
      <section className="card wt-pickers" aria-label="Pick a value">
        <label className="field-label">
          Run
          <select value={runId} onChange={(e) => { setRunId(e.target.value); setCompanyId(""); }}>
            <option value="">{runs ? "Choose a run" : "Loading runs…"}</option>
            {runs?.map((r) => <option key={r.run_id} value={r.run_id}>{runLabel(r)}</option>)}
          </select>
        </label>
        <label className="field-label">
          Company
          <select value={companyId} disabled={!records} onChange={(e) => setCompanyId(e.target.value)}>
            <option value="">{runId && !records ? "Loading companies…" : "Choose a company"}</option>
            {records?.map((r) => <option key={r.company_id} value={r.company_id}>{r.name || r.company_id}</option>)}
          </select>
        </label>
        <label className="field-label">
          Field
          <select value={current} disabled={!rec} onChange={(e) => { if (e.target.value) window.location.hash = e.target.value; }}>
            <option value="">Choose a field</option>
            {options.map((o) => <option key={o.href} value={o.href}>{o.label}</option>)}
          </select>
        </label>
      </section>
      {error && <p className="error-text" role="alert">{error}</p>}
      {w && onRoute && <WalkthroughView w={w} periodEnd={route.periodEnd} basis={route.basis} needsReview={rec?.needs_review} />}
    </div>
  );
}

function WalkthroughView({ w, periodEnd, basis, needsReview }: { w: Walkthrough; periodEnd?: string; basis?: string; needsReview?: boolean }) {
  const note = w.recorded ? null : notRecordedNote(w.not_recorded_reason ?? "", RETENTION_DAYS);
  const isSection = w.run_type in SECTIONS;
  const row = isSection ? {} : pickRow(w, periodEnd);
  const quotes = (isSection ? allCitations(w.rows) : list(row.citations)).map((c) => String(c.quote ?? ""));
  return (
    <>
      {note && <p className="banner banner-warning">{note}</p>}
      <section className="card" aria-labelledby="wt-result">
        <h2 id="wt-result">{w.company_name ?? w.company_id} · {w.item_name}</h2>
        {isSection ? <SectionResult w={w} /> : <RowResult w={w} row={row} basis={basis} />}
      </section>
      {w.trace_run_id !== w.run_id && <p className="help-text">Reused from run {w.trace_run_id}; the steps show that run.</p>}
      <ol className="wt-steps" aria-label="Steps">
        {steps(w, { periodEnd, basis }).map((s) => (
          <li key={s.n} className="card">
            <div className="wt-step-head">
              <span className="mono wt-step-n">{s.n}</span>
              <h3>{s.name}</h3>
              <span className="mono wt-kind">{s.kind === "llm" ? (s.model ? `LLM · ${s.model}` : "LLM") : "code"}</span>
              <span className="wt-label">{s.label}</span>
            </div>
            {s.recorded ? <StepBody s={s} w={w} row={row} quotes={quotes} needsReview={needsReview} /> : <p className="wt-nr">not recorded</p>}
          </li>
        ))}
      </ol>
    </>
  );
}

function RowResult({ w, row, basis }: { w: Walkthrough; row: Obj; basis?: string }) {
  const f = row as unknown as ExtractedField;
  return (
    <>
      <p className="wt-value">{valueLabel(f)}</p>
      <dl className="wt-facts">
        <div><dt>Period</dt><dd>{f.period_end ?? "unspecified"}</dd></div>
        {basis && <div><dt>Basis</dt><dd>{basis}</dd></div>}
        <div><dt>Confidence</dt><dd>{conf(f.confidence)}</dd></div>
        <div><dt>Alternatives</dt><dd>{f.alternatives?.length ?? 0}</dd></div>
        <div><dt>Route</dt><dd>{f.route ?? "none"}{f.route_reasons?.length ? ` · ${f.route_reasons.join(", ")}` : ""}</dd></div>
      </dl>
      {f.route === "review" && <a href={`#/review/${w.run_type}/${w.run_id}`}>Open in review queue</a>}
    </>
  );
}

function SectionResult({ w }: { w: Walkthrough }) {
  return (
    <dl className="wt-facts">
      <div><dt>Entries</dt><dd>{w.rows.length}</dd></div>
      {w.rows.length === 1 && <div><dt>Confidence</dt><dd>{conf(w.rows[0].confidence)}</dd></div>}
    </dl>
  );
}

function StepBody({ s, w, row, quotes, needsReview }: { s: Step; w: Walkthrough; row: Obj; quotes: string[]; needsReview?: boolean }) {
  switch (s.name) {
    case "Find evidence":
      return w.passages.length ? <Passages passages={w.passages} quotes={quotes} /> : null;
    case "Extract":
    case "Extract plan":
    case "Adjudicate":
      return s.answer == null ? null : <ModelTabs step={s.name} answer={s.answer} summary={summary(s.name, s.answer)} full={<FullAnswer answer={s.answer} w={w} row={row} />} />;
    case "Verify":
    case "Verify, blind": {
      if (s.answer != null) return <VerifyTabs s={s} w={w} row={row} />;
      if (w.recorded) return null;
      // Not recorded: what the stored row holds.
      const notes = w.run_type in SECTIONS ? w.rows.map((r) => r.verifier_notes).filter(Boolean).join(" ") : `Verifier confidence ${conf(row.verifier_confidence)}. ${row.verifier_notes ?? ""}`;
      return <p className="wt-line">{notes || "No verifier notes stored."}</p>;
    }
    case "Ground every quote": {
      const cites = w.run_type in SECTIONS ? allCitations(w.rows) : list(row.citations);
      return (
        <>
          {cites.length > 0 && (
            <ul className="wt-lines">
              {cites.map((c, i) => <li key={i}>“{String(c.quote ?? "")}” · {c.grounded ? "grounded" : "not grounded"}</li>)}
            </ul>
          )}
          {w.vision && (
            <div className="wt-sub">
              <p className="wt-line mono">Vision check · {w.vision.model}</p>
              <ModelTabs step="Vision check" answer={w.vision.answer} summary={lines(w.vision.answer).map(([k, v]) => `${k}: ${v}`).join("; ")} full={<Lines answer={w.vision.answer} />} />
            </div>
          )}
        </>
      );
    }
    case "Combine":
      return needsReview === undefined ? null : <p className="wt-line">Needs review: {needsReview ? "yes" : "no"}</p>;
    case "Combine into one record": {
      const alts = list(row.alternatives);
      return alts.length ? <ul className="wt-lines">{alts.map((a, i) => <li key={i}>Alternative: {fmt(a.value)} ({String(a.source ?? "")})</li>)}</ul> : null;
    }
    case "Auto-corrections": {
      const name = (id: string) => String(w.rows.find((r) => r.field_id === id)?.field_name ?? id);
      const cs = list(row.corrections) as unknown as Correction[];
      return cs.length ? <ul className="wt-lines">{cs.map((c, i) => <li key={i}>{correctionLine(c, name)}</li>)}</ul> : null;
    }
    case "Checks": {
      const bad = list(row.checks).filter((c) => c.outcome === "fail");
      return bad.length ? <ul className="wt-lines">{bad.map((c, i) => <li key={i}>{String(c.check_id)}: {String(c.detail ?? "")}</li>)}</ul> : null;
    }
    case "Route": {
      const reasons = Array.isArray(row.route_reasons) ? row.route_reasons : [];
      return reasons.length ? <p className="wt-line">{reasons.join(", ")}</p> : null;
    }
    default:
      return null;
  }
}

function Passages({ passages, quotes }: { passages: WalkthroughPassage[]; quotes: string[] }) {
  const [all, setAll] = useState(false);
  return (
    <>
      <ol className="wt-passages">
        {(all ? passages : passages.slice(0, 2)).map((p) => (
          <li key={p.rank}>
            <p className="wt-line mono">
              {p.rank} · {p.doc_title ?? p.doc_id} · {p.section ?? "no section"} · characters {p.char_start.toLocaleString("en-US")}–{p.char_end.toLocaleString("en-US")}
            </p>
            {p.text == null ? (
              <p className="wt-line muted">Text not available</p>
            ) : (
              <blockquote className="wt-passage">
                {markQuotes(p.text, quotes).map((x, i) => (x.mark ? <mark key={i}>{x.text}</mark> : <span key={i}>{x.text}</span>))}
              </blockquote>
            )}
          </li>
        ))}
      </ol>
      {!all && passages.length > 2 && (
        <button type="button" className="link-button" onClick={() => setAll(true)}>Show the other {passages.length - 2} passages</button>
      )}
    </>
  );
}

const TABS = [{ id: "summary", label: "Summary" }, { id: "full", label: "Full answer" }, { id: "json", label: "JSON" }];

function ModelTabs({ step, answer, summary, full }: { step: string; answer: unknown; summary: string; full: ReactNode }) {
  const [tab, setTab] = useState("summary");
  const [copied, setCopied] = useState("");
  const pre = useRef<HTMLPreElement>(null);
  const json = JSON.stringify(answer, null, 2);
  async function copy() {
    try {
      await navigator.clipboard.writeText(json);
      setCopied("Copied");
    } catch {
      const sel = window.getSelection();
      if (pre.current && sel) sel.selectAllChildren(pre.current);
      setCopied("Copy is blocked here: the JSON is selected, press Ctrl+C");
    }
  }
  return (
    <div className="wt-tabs">
      <StepTabs label="Answer view" tabs={TABS} active={tab} onSelect={setTab} />
      <div role="tabpanel" aria-label={`${step}: ${TABS.find((t) => t.id === tab)?.label}`}>
        {tab === "summary" && <p className="wt-line">{summary}</p>}
        {tab === "full" && full}
        {tab === "json" && (
          <>
            <pre ref={pre} className="wt-json">{json}</pre>
            <div className="wt-copy">
              <button type="button" className="secondary" onClick={copy}>Copy</button>
              <span className="muted" role="status">{copied}</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function VerifyTabs({ s, w, row }: { s: Step; w: Walkthrough; row: Obj }) {
  const v = w.verifier!;
  const a = obj(v.answer);
  if (w.run_type in SECTIONS) {
    const agrees = a[`${w.item}_agree`];
    const text = `${agrees === undefined ? "Answered" : agrees ? "Agrees" : "Disagrees"} · confidence ${conf(a.confidence)}. ${String(a[`${w.item}_notes`] ?? "")}`;
    return <ModelTabs step={s.name} answer={v.answer} summary={text} full={<Lines answer={v.answer} />} />;
  }
  if (!v.blind) {
    const text = `${a.agrees ? "Agrees" : `Disagrees (${String(a.disagreement_type ?? "value")})`} · confidence ${conf(a.confidence)}. ${String(a.notes ?? "")}`;
    return <ModelTabs step={s.name} answer={v.answer} summary={text} full={<Lines answer={v.answer} />} />;
  }
  const d = obj(v.verdict);
  const verdict = `${d.agrees ? "agrees" : `disagrees (${String(d.disagreement_type ?? "value")})`}. ${String(d.notes ?? "")}`;
  return (
    <ModelTabs
      step={s.name}
      answer={s.answer}
      summary={`Re-extracted ${readValues(v.answer)} without seeing the draft. Code compared the two: ${verdict}`}
      full={<><FullAnswer answer={v.answer} w={w} row={row} /><h4>Code’s verdict</h4><Lines answer={v.verdict} /></>}
    />
  );
}

function readValues(answer: unknown): string {
  const vs = list(obj(answer).values);
  return vs.length ? vs.map((x) => [fmt(x.value), x.unit_text, x.period_text && `(${x.period_text})`].filter(Boolean).join(" ")).join(", ") : "nothing (not disclosed)";
}

function summary(name: string, answer: unknown): string {
  const a = obj(answer);
  if (name === "Adjudicate") {
    return `${a.settled ? `Settled on ${[fmt(a.value), a.unit_text].filter(Boolean).join(" ")}` : "Unresolved"}. ${String(a.notes ?? "")}`;
  }
  if ("values" in a) return `Read ${readValues(answer)} · confidence ${conf(a.confidence)}.`;
  const counts = Object.entries(a).filter(([, x]) => Array.isArray(x)).map(([k, x]) => `${(x as unknown[]).length} ${k.replaceAll("_", " ")}`);
  return [...counts, `confidence ${conf(a.confidence)}`].join(" · ");
}

const lines = (answer: unknown): [string, string][] =>
  Object.entries(obj(answer)).map(([k, v]) => [k.replaceAll("_", " "), str(v)]);

function Lines({ answer }: { answer: unknown }) {
  return <dl className="wt-kv">{lines(answer).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}

/** Extract (and a blind verifier's draft): one row per period, then each quote with its passage and grounding. */
function FullAnswer({ answer, w, row }: { answer: unknown; w: Walkthrough; row: Obj }) {
  const a = obj(answer);
  if (!Array.isArray(a.values)) return <Lines answer={answer} />;
  const values = list(a.values);
  const cites = values.flatMap((v) => list(v.citations));
  const rowCites = w.run_type in SECTIONS ? allCitations(w.rows) : list(row.citations);
  return (
    <>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th scope="col">Period</th><th scope="col">Value</th><th scope="col">Printed as</th><th scope="col">Unit</th><th scope="col">State</th></tr></thead>
          <tbody>
            {values.map((v, i) => (
              <tr key={i}>
                <td>{str(v.period_text ?? v.planned_period_end)}</td><td>{fmt(v.value)}</td><td>{str(v.raw_value_text)}</td><td>{str(v.unit_text)}</td><td>{str(v.state)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {cites.length > 0 && (
        <ul className="wt-lines">
          {cites.map((c, i) => {
            const q = String(c.quote ?? "");
            const p = passageFor(w.passages, q);
            const g = rowCites.find((x) => x.quote === q);
            return <li key={i}>“{q}” · {p ? `passage ${p.rank}` : "passage not found"} · {g ? (g.grounded ? "grounded" : "not grounded") : "not in the stored row"}</li>;
          })}
        </ul>
      )}
    </>
  );
}
