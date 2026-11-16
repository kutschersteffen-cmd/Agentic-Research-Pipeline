import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { StepTabs } from "../../components/StepTabs";
import { isDemo } from "../../lib/engagement";
import { day, programmeShort } from "../../lib/workbench";
import { LAST_LINE, PANEL_TABS, why, type PanelTab, type WhyLine } from "../../lib/workbenchPanel";
import type { CompanyFactRow, CompanySummary, EngagementRecord, SimulatedObservation, StewardNote, UnifiedTrigger, VoteList, Worklist, WorklistRow } from "../../types";
import { companyHref, universeRef } from "../company/companyQuery";
import { useActor, words } from "./common";

const Sim = () => <span className="sim-tag">Simulated</span>;
const Demo = () => <span className="chip">Demo data</span>;
const Empty = ({ children }: { children: ReactNode }) => <p className="muted">{children}</p>;
const notFound = (e: unknown) => /^404:/.test((e as Error).message);

/** One request per (company, tab); a response for a company the user has already stepped away from is dropped. */
function useLoaded<T>(key: string, load: () => Promise<T>): { data?: T; error?: string } {
  const [state, setState] = useState<{ key: string; data?: T; error?: string }>({ key: "" });
  useEffect(() => {
    let live = true;
    load().then(
      (data) => live && setState({ key, data }),
      (e: Error) => live && setState({ key, error: e.message }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` names everything `load` reads
  }, [key]);
  return state.key === key ? state : {};
}

function Loading({ error }: { error?: string }) {
  return error ? <p className="error-text" role="alert">{error}</p> : <p className="status-text">Loading…</p>;
}

/** The Workbench row's side panel: seven tabs on one company, ↑/↓ to the next row, Esc to close. Non-modal: the
 * table stays usable beside it. Reads only per-company routes; the worklist itself is never re-requested. */
export function WorkbenchPanel({
  row, rows, data, scope, tab, onTab, onStep, canStep, onClose, onNoteAdded,
}: {
  row: WorklistRow;
  rows: WorklistRow[];
  data: Worklist;
  scope: string;
  tab: PanelTab;
  onTab: (t: PanelTab) => void;
  onStep: (step: 1 | -1) => void;
  /** Whether a row exists above and below this one in the table's order. */
  canStep: { up: boolean; down: boolean };
  onClose: () => void;
  onNoteAdded: (n: StewardNote) => void;
}) {
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => title.current?.focus(), []); // focus moves into the panel once, when it opens
  // A step to the first or last row disables the button just pressed; focus goes to the other one, not to the page.
  const up = useRef<HTMLButtonElement>(null);
  const down = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const at = document.activeElement; // still the button just disabled; a sort or filter elsewhere moves nothing
    if (at !== up.current && at !== down.current) return;
    const other = at === up.current ? down.current : up.current;
    if ((at === up.current && !canStep.up) || (at === down.current && !canStep.down)) (other?.disabled ? title.current : other)?.focus();
  }, [canStep.up, canStep.down]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || document.querySelector("dialog[open]")) return;
      const t = e.target as HTMLElement;
      const field = t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName);
      const typing = t.tagName === "TEXTAREA" || (t.tagName === "INPUT" && ["text", "search"].includes((t as HTMLInputElement).type));
      if (e.key === "Escape") {
        if (document.querySelector("details[open]")) return; // the open menu takes this Escape (seen first: capture phase)
        if (typing && (t as HTMLInputElement).value) return; // a half-typed note is not thrown away
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
      // ↑/↓ step rows from the panel's head and tabs, the table's rows, or nowhere in particular; elsewhere they scroll.
      const stepsHere = t === document.body || !!t.closest(".wb-panel-head, .wb-panel [role=tablist], .wb-table tbody");
      if (field || !stepsHere) return;
      e.preventDefault();
      onStep(e.key === "ArrowDown" ? 1 : -1);
    }
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [onClose, onStep]);

  // The trigger route lists every company's triggers: read once per panel, not once per company step.
  const triggers = useRef<Promise<UnifiedTrigger[]> | null>(null);
  const loadTriggers = () => (triggers.current ??= api.listTriggers().then((r) => r.triggers, (e) => { triggers.current = null; throw e; }));

  const id = row.issuer_id;
  return (
    <aside className="wb-panel" aria-labelledby="wb-panel-title">
      <header className="wb-panel-head">
        <div>
          <h2 id="wb-panel-title" ref={title} tabIndex={-1}>
            {row.company}
          </h2>
          <p className="muted mono">
            {row.identifier} · {row.sector === "unknown" ? "Unknown" : row.sector}
          </p>
        </div>
        <div className="wb-panel-nav">
          <button ref={up} className="secondary" aria-label="Previous company" title="Previous company (↑)" disabled={!canStep.up} onClick={() => onStep(-1)}>
            ↑
          </button>
          <button ref={down} className="secondary" aria-label="Next company" title="Next company (↓)" disabled={!canStep.down} onClick={() => onStep(1)}>
            ↓
          </button>
          <button className="secondary" aria-label="Close the panel" title="Close (Esc)" onClick={onClose}>
            ✕
          </button>
        </div>
      </header>
      <StepTabs label="Company details" tabs={PANEL_TABS.map((t) => ({ id: t, label: t }))} active={tab} onSelect={(t) => onTab(t as PanelTab)} />
      <div className="wb-panel-body" role="tabpanel" aria-label={tab} tabIndex={0 /* Tab reaches it and ↑/↓ scroll it, also when a tab has nothing focusable (WCAG 2.1.1) */}>
        {tab === "Why" && <WhyTab row={row} rows={rows} data={data} />}
        {tab === "Company" && <CompanyTab key={id} row={row} />}
        {tab === "Engagements" && <EngagementsTab key={id} id={id} />}
        {tab === "Votes" && <VotesTab key={id} id={id} />}
        {tab === "Triggers" && <TriggersTab key={id} id={id} load={loadTriggers} />}
        {tab === "Holdings" && <HoldingsTab row={row} cycle={data.cycle} />}
        {tab === "Notes" && <NotesTab key={id} id={id} scope={scope} onAdded={onNoteAdded} />}
      </div>
    </aside>
  );
}

const valueCell = (l: WhyLine) => (
  <>
    {l.value.text}
    {l.value.simulated && <> <Sim /></>}
    {l.messages.map((m, i) => (
      <span key={i} className="wb-flag-msg">
        {m}
      </span>
    ))}
  </>
);
const inline = (lines: WhyLine[], withValue = true) =>
  lines.length
    ? lines.map((l, i) => (
        <span key={l.id}>
          {i > 0 && ", "}
          {l.label}
          {withValue && <> {valueCell(l)}</>}
        </span>
      ))
    : "—";

function WhyTab({ row, rows, data }: { row: WorklistRow; rows: WorklistRow[]; data: Worklist }) {
  const w = why(row, rows, data);
  return (
    <>
      <div className="wb-chips wb-panel-programmes" aria-label="Programmes">
        {row.programmes.length ? (
          row.programmes.map((p) => (
            <span key={p.programme_id} className="chip" title={p.name}>
              {`${programmeShort(p.name)} · ${p.status === "confirmed" ? "Confirmed" : "Proposed"}`}
            </span>
          ))
        ) : (
          <span className="muted">In no programme.</span>
        )}
      </div>
      <h3>Why is this here</h3>
      <p>{w.first}</p>
      <p className="muted">{w.second}</p>
      <div className="table-wrap">
        <table className="data-table wb-why">
          <thead>
            <tr>
              <th>Indicator</th>
              <th>Value</th>
              <th className="num">Counts as</th>
              <th className="num">Weight</th>
              <th className="num">Points</th>
            </tr>
          </thead>
          <tbody>
            {w.weighted.map((l) => (
              <tr key={l.id}>
                <td>{l.label}</td>
                <td>{valueCell(l)}</td>
                <td className="num">{l.normalised.toFixed(2)}</td>
                <td className="num">{l.weight}</td>
                <td className="num">{l.points.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={4} className="num">
                Total
              </td>
              <td className="num">
                <strong>{w.total}</strong>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p>Not weighted (weight 0): {inline(w.notWeighted)}</p>
      <p>No data, 0 points: {inline(w.noData, false)}</p>
      <p>{LAST_LINE}</p>
    </>
  );
}

type Fact = { key: string; field: string; value: string; period: string; source: string; simulated: boolean };
const NUMBER = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });
const withUnit = (v: unknown, unit: string | null | undefined) =>
  `${typeof v === "number" ? NUMBER.format(v) : v !== null && typeof v === "object" ? JSON.stringify(v) : String(v ?? "—")}${unit ? ` ${unit}` : ""}`;
const factValue = (f: CompanyFactRow) => (f.canonical_value !== null ? withUnit(f.canonical_value, f.canonical_unit) : withUnit(f.value, null));

function CompanyTab({ row }: { row: WorklistRow }) {
  const ref = universeRef(row.issuer_id);
  // The row's name, ISIN and sector show whatever the reads return; a 404 (not in the central registry) is no error.
  const soft = <T,>(p: Promise<T>, empty: T) => p.catch((e) => (notFound(e) ? empty : Promise.reject(e)));
  const { data, error } = useLoaded(ref, () =>
    Promise.all([soft<CompanySummary | null>(api.getCompany(ref), null), soft<CompanyFactRow[]>(api.getCompanyFacts(ref, { limit: 100 }), []), soft<SimulatedObservation[]>(api.getSimulatedEsg(ref), [])]),
  );
  const [summary, facts, simulated] = data ?? [null, [], []];
  const rowsShown: Fact[] = [
    ...facts.map((f) => ({ key: `f${f.fact_id}`, field: words(f.field_id), value: factValue(f), period: f.period_end ?? "—", source: f.source_label, simulated: false })),
    ...simulated.map((o) => ({
      key: `s${o.field_id}`,
      field: o.field_name,
      value: withUnit(o.value, o.unit),
      period: o.period || "—",
      source: "Simulated dataset",
      simulated: true,
    })),
  ];
  return (
    <>
      <dl className="wb-facts">
        <dt>Name</dt>
        <dd>{summary?.name ?? row.company}</dd>
        <dt>ISIN</dt>
        <dd className="mono">{row.identifier}</dd>
        <dt>Sector</dt>
        <dd>{row.sector === "unknown" ? (summary?.sector ?? "Unknown") : row.sector}</dd>
        <dt>Country</dt>
        <dd>{summary?.country ?? "—"}</dd>
      </dl>
      {summary && (
        <p>
          <a href={companyHref(row.issuer_id, summary.id)}>Open the company page</a>
        </p>
      )}
      <h3>Facts</h3>
      {!data ? (
        <Loading error={error} />
      ) : rowsShown.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Field</th>
                <th>Value</th>
                <th>Period</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {rowsShown.map((f) => (
                <tr key={f.key}>
                  <td>{f.field}</td>
                  <td>
                    {f.value}
                    {f.simulated && <> <Sim /></>}
                  </td>
                  <td className="wb-nowrap">{f.period}</td>
                  <td>{f.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>No facts stored for this company.</Empty>
      )}
    </>
  );
}

function EngagementsTab({ id }: { id: string }) {
  const { data, error } = useLoaded(`e${id}`, () =>
    (api.getEngagementRecord(id) as Promise<EngagementRecord>).catch((e) => (notFound(e) ? null : Promise.reject(e))),
  );
  if (data === undefined) return <Loading error={error} />;
  if (!data?.issues.length) return <Empty>No engagements recorded for this company.</Empty>;
  return (
    <>
      {data.issues.map((issue) => (
        <section key={issue.issue_id} className="wb-issue">
          <h3>{words(issue.theme)}</h3>
          <p className="muted">
            Status {words(issue.status)} · Escalation {words(issue.escalation_stage)}
            {isDemo(issue, {}) && <> · <Demo /></>}
          </p>
          <h4>Objectives</h4>
          {issue.objectives.length ? (
            <ul className="wb-list">
              {issue.objectives.map((o) => (
                <li key={o.objective_id ?? o.description}>
                  {o.description}
                  <span className="muted">{` · ${words(o.objective_type)} · ${words(o.status)} · result: ${o.result ? words(o.result) : "—"}`}</span>
                  {isDemo(issue, o) && <Demo />}
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No objectives.</Empty>
          )}
          <h4>Commitments</h4>
          {issue.commitments.length ? (
            <ul className="wb-list">
              {issue.commitments.map((c) => (
                <li key={c.commitment_id}>
                  {c.text}
                  <span className="muted">{` · ${words(c.status)}${c.target_date ? ` · due ${day(c.target_date)}` : ""}`}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No commitments.</Empty>
          )}
          <h4>Last activities</h4>
          {issue.correspondence.length ? (
            <ul className="wb-list">
              {[...issue.correspondence]
                .sort((a, b) => b.date.localeCompare(a.date))
                .slice(0, 10)
                .map((a) => (
                  <li key={a.entry_id}>
                    <span className="mono">{day(a.date)}</span> {words(a.activity_type ?? a.type)}: {a.summary}
                  </li>
                ))}
            </ul>
          ) : (
            <Empty>No activities.</Empty>
          )}
        </section>
      ))}
    </>
  );
}

function VotesTab({ id }: { id: string }) {
  const { data, error } = useLoaded<VoteList>(`v${id}`, () => api.getVotes(id));
  if (!data) return <Loading error={error} />;
  if (!data.votes.length) return <Empty>No votes in the ledger for this company.</Empty>;
  return (
    <>
      {data.total > data.votes.length && <p className="muted">{`Showing ${data.votes.length} of ${data.total}`}</p>}
      <div className="table-wrap">
        <table className="data-table wb-stack">
          <thead>
            <tr>
              <th>Date</th>
              <th>Item</th>
              <th>Management recommendation</th>
              <th>Vote</th>
              <th>Against management</th>
              <th>
                <span className="visually-hidden">Data</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {data.votes.map((v, i) => (
              <tr key={`${v.meeting_date}-${v.item_number}-${i}`}>
                <td className="mono" data-label="Date">{day(v.meeting_date) || "—"}</td>
                <td className="wb-wrap" data-label="Item">{[v.item_number, v.description].filter(Boolean).join(" ") || "—"}</td>
                <td data-label="Management recommendation">{v.management_recommendation ? words(v.management_recommendation).toUpperCase() : "—"}</td>
                <td data-label="Vote">{v.vote_label ?? words(v.vote)}</td>
                <td data-label="Against management">{v.against_management === null ? "—" : v.against_management ? "Yes" : "No"}</td>
                <td data-label="">{v.demo && <Demo />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function TriggersTab({ id, load }: { id: string; load: () => Promise<UnifiedTrigger[]> }) {
  const { data, error } = useLoaded(`t${id}`, () => load().then((all) => all.filter((t) => t.issuer_id === id)));
  if (!data) return <Loading error={error} />;
  if (!data.length) return <Empty>No triggers stored for this company.</Empty>;
  const order = { high: 0, medium: 1, low: 2 };
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Severity</th>
            <th>Rule</th>
            <th>Reason</th>
            <th>Status</th>
            <th>First seen</th>
          </tr>
        </thead>
        <tbody>
          {[...data]
            .sort((a: UnifiedTrigger, b: UnifiedTrigger) => order[a.severity] - order[b.severity])
            .map((t) => (
              <tr key={t.trigger_id}>
                <td>{t.severity}</td>
                <td className="mono">{t.rule}</td>
                <td className="wb-wrap">{t.reason}</td>
                <td>{t.status}</td>
                <td className="mono">{t.first_seen_month}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

function HoldingsTab({ row, cycle }: { row: WorklistRow; cycle: string }) {
  if (!row.held_in.length) return <Empty>No house fund holds this company.</Empty>;
  return (
    <div className="table-wrap">
      <table className="data-table wb-stack">
        <thead>
          <tr>
            <th>Fund</th>
            <th className="num">Weight in fund %</th>
            <th className="num">Market value (EUR m)</th>
            <th>{`Selection ${cycle}`}</th>
          </tr>
        </thead>
        <tbody>
          {row.held_in.map((h) => (
            <tr key={h.portfolio_id}>
              <td className="wb-wrap" data-label="Fund">{h.name}</td>
              <td className="num" data-label="Weight in fund %">{h.weight_pct === null ? "—" : h.weight_pct.toFixed(3)}</td>
              <td className="num" data-label="Market value (EUR m)">{h.market_value_eur_m.toFixed(1)}</td>
              <td data-label={`Selection ${cycle}`}>{h.selection_status === "confirmed" ? "Confirmed" : h.selection_status === "proposed" ? "Proposed" : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NotesTab({ id, scope, onAdded }: { id: string; scope: string; onAdded: (n: StewardNote) => void }) {
  const actor = useActor();
  const loaded = useLoaded(`n${id}`, () => api.getNotes(id).then((r) => r.notes));
  const [added, setAdded] = useState<StewardNote[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function add() {
    setBusy(true);
    setError(null);
    try {
      const n = await api.addNote({ company_id: id, text: text.trim(), scope });
      setAdded((a) => [n, ...a]);
      setText("");
      onAdded(n);
    } catch (e) {
      setError(`The note was not saved (${(e as Error).message}). Your text is kept; try again.`);
    } finally {
      setBusy(false);
    }
  }
  const mine = new Set(added.map((n) => n.note_id)); // a note added before the list arrived is in both
  const notes = [...added, ...(loaded.data ?? []).filter((n) => !mine.has(n.note_id))];
  return (
    <>
      <form
        className="wb-note-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) add();
        }}
      >
        <label className="field-label">
          Add note
          <textarea rows={3} maxLength={2000} value={text} readOnly={busy} onChange={(e) => setText(e.target.value)} placeholder="A comment or remark on this company" />
        </label>
        <div className="toolbar">
          <button type="submit" disabled={!actor || !text.trim() || busy} title={actor ? undefined : "Sign in first"}>
            {busy ? "Adding…" : "Add note"}
          </button>
          <span className="muted">Notes are kept across quarters and never change the score.</span>
        </div>
        {error && <p className="error-text" role="alert">{error}</p>}
      </form>
      {!loaded.data && <Loading error={loaded.error} />}
      {loaded.data && !notes.length && <Empty>No notes on this company yet.</Empty>}
      {notes.length > 0 && (
        <ol className="wb-notes" aria-label="Notes, newest first">
          {notes.map((n) => (
            <li key={n.note_id}>
              <p className="wb-note-meta">
                <strong>{n.by}</strong> <span className="mono muted">{`${day(n.at)} ${n.at.slice(11, 16)} UTC`}</span>
              </p>
              <p className="wb-note-text">{n.text}</p>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
