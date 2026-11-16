import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { Modal } from "../../components/Modal";
import {
  COLUMNS,
  COMPONENT_LABEL,
  DEFAULT_SORT,
  PAGE_SIZE,
  day,
  extraColumns,
  nextMeetingText,
  nextSort,
  programmeChip,
  programmeShort,
  selectionCounts,
  sortRows,
  tierText,
  totalText,
  weightsProblem,
  weightsTotal,
  withProgramme,
  withSelection,
  type Column,
  type SortKey,
} from "../../lib/workbench";
import { neighbour, type PanelTab } from "../../lib/workbenchPanel";
import type { PriorityPreview, SelectionList, WorkProgramme, Worklist, WorklistRow, WorklistScope } from "../../types";
import { DataTable, RuleEditor, Section, VersionsPanel, usePolicy, useActor } from "./common";
import { WorkbenchPanel } from "./WorkbenchPanel";

const Sim = () => <span className="sim-tag">Simulated</span>;
const shortLabel = (c: Column) => c.label.replace(/ (%|\(.*\))$/, "");
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const fixed = (v: number | null | undefined, d: number) => (v === null || v === undefined ? "—" : v.toFixed(d));

/** One cell of the table, as the spec's column table says it reads. */
function Cell({ col, row, asOf, onRemove }: { col: Column; row: WorklistRow; asOf: string; onRemove: (r: WorklistRow) => void }): ReactNode {
  const sim = col.simulated?.(row) ? <Sim /> : null;
  switch (col.id) {
    case "company":
      return row.company;
    case "sector":
      return row.sector === "unknown" ? "Unknown" : row.sector;
    case "identifier":
      return <span className="mono">{row.identifier}</span>;
    case "engaged":
      return row.engaged.yes ? `Yes · ${day(row.engaged.last)}` : "No";
    case "last_topics":
      return row.last_topics.length ? row.last_topics.join("; ") : "—";
    case "programmes":
      return row.programmes.length ? (
        <span className="wb-chips">
          {row.programmes.map((p) => (
            <span key={p.programme_id} className="chip" title={`${p.name}: ${p.status}`}>
              {programmeChip(p)}
            </span>
          ))}
        </span>
      ) : (
        "—"
      );
    case "norms_violation":
      return row.norms_violation === null ? "—" : <>{row.norms_violation.value ? "Yes" : "No"}{sim}</>;
    case "funds":
      return <span title={row.held_in.map((h) => h.name).join("\n") || undefined}>{row.held_in.length}</span>;
    case "holdings_weight":
      return fixed(row.holdings_weight_pct, 3);
    case "aum_held":
      return fixed(row.aum_held_eur_m, 1);
    case "coverage_tier":
      return tierText(row);
    case "triggers": {
      const t = row.triggers;
      return t.high + t.medium + t.low === 0 ? "—" : `H ${t.high} · M ${t.medium} · L ${t.low}`;
    }
    case "open_engagements":
      return row.open_engagements;
    case "escalated":
      return row.escalated;
    case "overdue_commitments":
      return row.overdue_commitments;
    case "next_meeting": {
      if (!row.next_meeting) return "—";
      const m = nextMeetingText(row.next_meeting, asOf);
      return <span title={m.title}>{m.text}</span>;
    }
    case "transition_grade":
      return row.transition_grade ? <>{`${row.transition_grade.value} ${row.transition_grade.label}`}{sim}</> : "—";
    case "esg_score":
      return row.esg_score ? <>{fixed(Number(row.esg_score.value), 1)}{sim}</> : "—";
    case "controversy":
      return row.controversy ? <>{fixed(Number(row.controversy.value), 0)}{sim}</> : "—";
    case "carbon_intensity":
      return row.carbon_intensity ? <>{fixed(Number(row.carbon_intensity.value), 0)}{sim}</> : "—";
    case "equity_held":
      return fixed(row.equity_held_eur_m, 1);
    case "ownership":
      return row.ownership_pct ? <>{fixed(Number(row.ownership_pct.value), 4)}{sim}</> : "—";
    case "selected_elsewhere":
      return row.selected_elsewhere.length ? (
        <span title={row.selected_elsewhere.map((s) => `${s.label}: ${s.status === "confirmed" ? "Confirmed" : "Proposed"}`).join("\n")}>
          {row.selected_elsewhere.length}
        </span>
      ) : (
        "—"
      );
    case "notes":
      return row.notes.count ? <span title={row.notes.latest?.text}>{`${row.notes.count} · ${day(row.notes.latest?.at)}`}</span> : "—";
    case "score":
      return <strong>{row.score.toFixed(1)}</strong>;
    case "selection":
      if (!row.selection) return null;
      if (row.selection.status === "confirmed") return <span title={`Confirmed by ${row.selection.confirmed_by}`}>Confirmed</span>;
      return (
        <span className="wb-proposed">
          <span className="proposed-tag">✎ Proposed</span>
          <button className="link-button" aria-label={`Remove ${row.company} from the selection`} title="Remove from the selection" onClick={() => onRemove(row)}>
            ✕
          </button>
        </span>
      );
    default: {
      const o = row.esg_extra[col.id.slice(4)];
      if (!o) return "—";
      const v = typeof o.value === "boolean" ? (o.value ? "Yes" : "No") : typeof o.value === "number" ? String(Math.round(o.value * 100) / 100) : o.value;
      return <>{v}{sim}</>;
    }
  }
}

type Dialog = null | "confirm" | "bilateral" | "programme" | "subgroup" | "funds";

/** Steward Workflow → Workbench: every company of a scope in one table, the score one column among many. */
export function WorkbenchStudio({ onRowsShown }: { onRowsShown?: () => void }) {
  const actor = useActor();
  const [scopes, setScopes] = useState<WorklistScope[]>([]);
  const [scope, setScope] = useState("house");
  const [data, setData] = useState<Worklist | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSortKeys] = useState<SortKey[]>(DEFAULT_SORT);
  const [page, setPage] = useState(0);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [visible, setVisible] = useState<Set<string>>(() => new Set(COLUMNS.filter((c) => !c.hidden).map((c) => c.id)));
  const [programmes, setProgrammes] = useState<WorkProgramme[]>([]);
  const [fieldLabels, setFieldLabels] = useState<Record<string, string>>({});
  const [selection, setSelection] = useState<SelectionList | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [panel, setPanel] = useState<{ id: string; tab: PanelTab } | null>(null);
  const selectStep = useRef<HTMLDivElement>(null);
  const columnsMenu = useRef<HTMLDetailsElement>(null);
  useDismiss(columnsMenu);

  // A response for a scope the user has already left is dropped.
  const wanted = useRef(scope);
  wanted.current = scope;
  const load = useCallback(async (key: string) => {
    setLoading(true);
    setError(null);
    try {
      const w = await api.getWorklist(key);
      if (wanted.current !== key) return;
      setData(w);
      api.getSelection(key, w.cycle).then((s) => wanted.current === key && setSelection(s), () => undefined);
    } catch (e) {
      if (wanted.current === key) setError((e as Error).message);
    } finally {
      if (wanted.current === key) setLoading(false);
      onRowsShown?.();
    }
  }, [onRowsShown]);
  const loadScopes = useCallback(() => api.getWorklistScopes().then((r) => setScopes(r.scopes), (e: Error) => setActionError(e.message)), []);
  useEffect(() => {
    load(scope);
  }, [load, scope]);
  // The rows come first: the rest is read once they are on screen.
  const loaded = data !== null;
  useEffect(() => {
    if (!loaded) return;
    loadScopes();
    api.listProgrammes().then((r) => setProgrammes(r.programmes), () => undefined);
    api.getSimulatedSchema().then((s) => setFieldLabels(Object.fromEntries(s.fields.map((f) => [f.field_id, f.name]))), () => undefined);
  }, [loaded, loadScopes]);

  const rows = useMemo(() => data?.rows ?? [], [data]);
  const columns = useMemo(() => [...COLUMNS, ...extraColumns(rows, fieldLabels)], [rows, fieldLabels]);
  const shown = columns.filter((c) => c.pinned || visible.has(c.id));
  const simulatedCols = useMemo(() => new Set(columns.filter((c) => c.simulated && rows.some(c.simulated)).map((c) => c.id)), [columns, rows]);
  const sorted = useMemo(() => sortRows(rows, sort, columns), [rows, sort, columns]);
  const pages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const pageRows = sorted.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);
  const counts = selectionCounts(rows);
  const scopeLabel = data?.scope.label ?? scopes.find((s) => s.key === scope)?.label ?? "";
  const tickedRows = rows.filter((r) => ticked.has(r.issuer_id));
  const needName = actor ? undefined : "Sign in first";
  const gone = selection?.rows.filter((r) => !r.in_scope) ?? [];
  // The server's universe note describes the house; a fund or subgroup gets its own count of simulated values.
  const simulatedRows = useMemo(() => rows.filter((r) => columns.some((c) => c.simulated?.(r))).length, [rows, columns]);
  const scopeNote =
    data?.scope.kind === "house"
      ? data.universe_note
      : simulatedRows
        ? `Simulated: ${simulatedRows} of these ${rows.length} companies carry simulated ESG values, not real data.`
        : null;

  function setSort(keys: SortKey[]) {
    setSortKeys(keys);
    setPage(0);
  }
  function chooseScope(key: string) {
    setScope(key);
    setData(null); // the old scope's rows must not be acted on under the new scope
    setSelection(null);
    setTicked(new Set());
    setPage(0);
    setMessage(null);
    setPanel(null);
  }
  function tick(id: string, on: boolean) {
    setTicked((t) => {
      const next = new Set(t);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }
  async function act(run: () => Promise<string | null>) {
    setBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      setMessage(await run());
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const patch = (f: (rows: WorklistRow[]) => WorklistRow[]) => setData((d) => (d ? { ...d, rows: f(d.rows) } : d));

  // The side panel: a row click opens it (Score ⓘ on Why), ↑/↓ step through the table's order across pages.
  const openRow = panel ? rows.find((r) => r.issuer_id === panel.id) : undefined;
  const open = (id: string, tab?: PanelTab) => setPanel((p) => ({ id, tab: tab ?? p?.tab ?? "Why" }));
  const step = useCallback(
    (by: 1 | -1) => {
      const id = panel && neighbour(sorted, panel.id, by);
      if (!panel || !id) return;
      setPage(Math.floor(sorted.findIndex((r) => r.issuer_id === id) / PAGE_SIZE));
      setPanel({ ...panel, id });
    },
    [panel, sorted],
  );
  const closePanel = useCallback(() => {
    // Focus goes back to the row, so its page must be the one on screen.
    const at = panel ? sorted.findIndex((r) => r.issuer_id === panel.id) : -1;
    if (at >= 0) setPage(Math.floor(at / PAGE_SIZE));
    if (panel) requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-open-row="${CSS.escape(panel.id)}"]`)?.focus());
    setPanel(null);
  }, [panel, sorted]);
  const openId = panel?.id;
  useEffect(() => {
    if (openId) document.querySelector(`[data-open-row="${CSS.escape(openId)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [openId]);

  const addSelected = () =>
    act(async () => {
      const list = await api.changeSelection({ cycle: data!.cycle, scope, add: [...ticked] });
      patch((r) => withSelection(r, list));
      setSelection(list);
      setTicked(new Set());
      return `Added ${plural(ticked.size, "company", "companies")} to the ${scopeLabel} selection ${data!.cycle}.`;
    });
  const removeSelected = (row: WorklistRow) =>
    act(async () => {
      const list = await api.changeSelection({ cycle: data!.cycle, scope, remove: [row.issuer_id] });
      patch((r) => withSelection(r, list));
      setSelection(list);
      return `${row.company} is no longer proposed.`;
    });
  const confirmSelection = () =>
    act(async () => {
      const res = await api.confirmSelection({ cycle: data!.cycle, scope });
      const list = await api.getSelection(scope, data!.cycle);
      patch((r) => withSelection(r, list));
      setSelection(list);
      setDialog(null);
      return `Confirmed ${plural(res.confirmed, "company", "companies")} for the ${data!.cycle} engagement selection.`;
    });

  return (
    <>
      <section className="card">
        <h2>Workbench</h2>
        <ol className="wb-steps" aria-label="Steps">
          <li>① Holdings in scope</li>
          <li>② Narrow down</li>
          <li>③ Select</li>
        </ol>
        <p className="help-text">
          Every company in the scope in one table. The priority score is one column. It does not hide, order or select anything unless
          you sort or filter by it.
        </p>

        <div className="wb-step">
          <h3>① Holdings in scope</h3>
          <div className="inline-fields">
            <select aria-label="Scope" value={scope} onChange={(e) => chooseScope(e.target.value)}>
              {scopes.length === 0 && <option value={scope}>{scopeLabel || "All house holdings"}</option>}
              {scopes.filter((s) => s.kind === "house").map((s) => (
                <option key={s.key} value={s.key}>{`${s.label} (${s.companies})`}</option>
              ))}
              {(["portfolio", "group"] as const).map((kind) => {
                const list = scopes.filter((s) => s.kind === kind);
                return list.length > 0 ? (
                  <optgroup key={kind} label={kind === "portfolio" ? "Funds" : "Subgroups"}>
                    {list.map((s) => (
                      <option key={s.key} value={s.key}>{`${s.label} (${s.companies})`}</option>
                    ))}
                  </optgroup>
                ) : null;
              })}
            </select>
            {scopes.some((s) => s.kind === "portfolio") && (
              <button className="secondary" disabled={!actor} title={needName} onClick={() => setDialog("funds")}>
                + New fund subgroup
              </button>
            )}
          </div>
          {data && (
            <p className="wb-scope-line">
              <strong>{data.scope.label}</strong>: {plural(data.scope.companies, "company", "companies")} in scope · Cycle {data.cycle} · Weights v
              {data.weights.version}
              {data.weights.version === 0
                ? " (bundled default)"
                : ` (activated ${day(data.weights.activated_at)}${data.weights.activated_by ? ` by ${data.weights.activated_by}` : ""})`}
            </p>
          )}
          {data && scopeNote && <p className="help-text">{scopeNote}</p>}
        </div>

        <div className="wb-step">
          <h3>② Narrow down</h3>
          <p className="muted">No filter set.</p>
        </div>

        {error && <p className="error-text" role="alert">{error}</p>}
        {!data && loading && <p className="status-text">Loading the companies in scope…</p>}
        {data && (
          <>
            <div className="toolbar wb-sortbar">
              <span className="muted">Sorted by:</span>
              {sort.map((k, i) => {
                const col = columns.find((c) => c.id === k.id);
                return (
                  <span key={k.id} className="chip wb-sort-chip">
                    {`${i + 1} ${col ? shortLabel(col) : k.id} ${k.desc ? "↓" : "↑"}`}
                    <button className="link-button" aria-label={`Stop sorting by ${col ? shortLabel(col) : k.id}`} onClick={() => setSort(sort.filter((s) => s.id !== k.id))}>
                      ✕
                    </button>
                  </span>
                );
              })}
              {sort.length === 0 && <span className="muted">nothing</span>}
              <MenuButton
                label="Add as next sort ▾"
                items={shown.filter((c) => !sort.some((k) => k.id === c.id)).map((c) => ({ key: c.id, label: c.label, run: () => setSort(nextSort(sort, c, true)) }))}
              />
              <details className="wb-menu" ref={columnsMenu}>
                <summary>Columns ▾</summary>
                <div className="wb-menu-panel" role="group" aria-label="Columns">
                  {columns.filter((c) => !c.pinned).map((c) => (
                    <label key={c.id} className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={visible.has(c.id)}
                        onChange={(e) =>
                          setVisible((v) => {
                            const next = new Set(v);
                            if (e.target.checked) next.add(c.id);
                            else next.delete(c.id);
                            return next;
                          })
                        }
                      />
                      {c.label}
                      {c.id.startsWith("esg:") && <Sim />}
                    </label>
                  ))}
                </div>
              </details>
              <span className="wb-counts">
                Showing {sorted.length} of {rows.length} · Selected {counts.selected} ({counts.confirmed} confirmed)
                {loading && <span className="muted"> · Refreshing…</span>}
              </span>
            </div>

            {/* Always there, so ticking a row never moves the table under the pointer. */}
            <div className="toolbar wb-ticked">
              <strong role="status">{ticked.size ? `${plural(ticked.size, "company", "companies")} ticked` : "Nothing ticked"}</strong>
              <button disabled={!actor || !ticked.size || busy} title={needName} onClick={addSelected}>
                Add {ticked.size} to {scopeLabel} selection {data.cycle}
              </button>
              <button className="link-button" onClick={() => selectStep.current?.scrollIntoView({ block: "start" })}>
                More in ③ Select ↓
              </button>
            </div>
            <div className="table-wrap wb-table-wrap">
              <table className="data-table wb-table">
                <thead>
                  <tr>
                    <th className="wb-tick">
                      <span className="visually-hidden">Tick</span>
                    </th>
                    {shown.map((c) => {
                      const at = sort.findIndex((k) => k.id === c.id);
                      return (
                        <th
                          key={c.id}
                          className={c.id === "company" ? "wb-name" : undefined}
                          aria-sort={at === 0 ? (sort[0].desc ? "descending" : "ascending") : undefined}
                          title={c.title}
                        >
                          <button className="wb-sort" onClick={(e) => setSort(nextSort(sort, c, e.shiftKey))} title={`${c.title ? `${c.title}. ` : ""}Click to sort, shift-click to add as the next sort`}>
                            {c.label}
                            {simulatedCols.has(c.id) && " · Simulated"}
                            {at >= 0 && <span className="wb-sort-mark">{` ${at + 1}${sort[at].desc ? "↓" : "↑"}`}</span>}
                          </button>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((r) => (
                    <tr
                      key={r.issuer_id}
                      className={[ticked.has(r.issuer_id) && "selected-row", panel?.id === r.issuer_id && "wb-open-row"].filter(Boolean).join(" ") || undefined}
                      onClick={(e) => !(e.target as HTMLElement).closest("button, input, a, label, .wb-tick") && !window.getSelection()?.toString() && open(r.issuer_id)}
                    >
                      <td className="wb-tick">
                        <input type="checkbox" aria-label={`Tick ${r.company}`} checked={ticked.has(r.issuer_id)} onChange={(e) => tick(r.issuer_id, e.target.checked)} />
                      </td>
                      {shown.map((c) => (
                        <td key={c.id} className={c.id === "company" ? "wb-name" : c.id === "last_topics" ? "wb-topics" : c.numeric && !c.pinned ? "num" : undefined} title={c.id === "company" ? r.company : c.id === "last_topics" ? r.last_topics.join("; ") || undefined : undefined}>
                          {c.id === "company" ? (
                            <button className="link-button wb-open" data-open-row={r.issuer_id} aria-expanded={panel?.id === r.issuer_id} onClick={() => open(r.issuer_id)}>
                              {r.company}
                            </button>
                          ) : (
                            <Cell col={c} row={r} asOf={data.as_of} onRemove={removeSelected} />
                          )}
                          {c.id === "score" && (
                            <button className="link-button wb-why-button" aria-label={`Why is ${r.company} here`} title="Why is this here" onClick={() => open(r.issuer_id, "Why")}>
                              ⓘ
                            </button>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <nav className="toolbar wb-pager" aria-label="Pages">
              <button className="secondary" disabled={current === 0} onClick={() => setPage(current - 1)}>
                ‹ Previous
              </button>
              <span>
                Page {current + 1} of {pages} · rows {sorted.length ? current * PAGE_SIZE + 1 : 0}–{Math.min(sorted.length, (current + 1) * PAGE_SIZE)}
              </span>
              <button className="secondary" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
                Next ›
              </button>
            </nav>

            <div className="wb-step" ref={selectStep}>
              <h3>③ Select</h3>
              <p className="muted">
                {ticked.size ? `${plural(ticked.size, "company", "companies")} ticked.` : "Tick rows by hand on any page; nothing is ticked for you."}
              </p>
              <div className="toolbar wb-actions">
                <button disabled={!actor || !ticked.size || busy} title={needName} onClick={addSelected}>
                  Add {ticked.size} to {scopeLabel} selection {data.cycle}
                </button>
                <button className="secondary" disabled={!actor || !counts.proposed || busy} title={needName} onClick={() => setDialog("confirm")}>
                  Confirm {data.cycle} selection ({counts.proposed} proposed)
                </button>
                <button className="secondary" disabled={!actor || !ticked.size || busy} title={needName} onClick={() => setDialog("bilateral")}>
                  Pick for bilateral
                </button>
                <MenuButton
                  label="Add to programme ▾"
                  disabled={!actor || !ticked.size || busy}
                  items={[
                    ...programmes.map((p) => ({
                      key: p.programme_id,
                      label: programmeShort(p.name),
                      run: () =>
                        act(async () => {
                          const detail = await api.addProgrammeMembers(p.programme_id, [...ticked]);
                          patch((r) => withProgramme(r, detail));
                          return `Proposed ${plural(ticked.size, "company", "companies")} for the ${detail.name}.`;
                        }),
                    })),
                    { key: "__new", label: "New programme…", run: () => setDialog("programme") },
                  ]}
                />
                <button className="secondary" disabled={!actor || !ticked.size || busy} title={needName} onClick={() => setDialog("subgroup")}>
                  Save ticked as subgroup
                </button>
              </div>
              {message && <p className="status-text">{message}</p>}
              {actionError && <p className="error-text" role="alert">{actionError}</p>}
              {gone.length > 0 && (
                <>
                  <h4>Selected but no longer in this scope</h4>
                  <DataTable rows={gone.map((g) => ({ company: g.company, status: g.status, proposed_by: g.proposed_by }))} />
                </>
              )}
            </div>
          </>
        )}
      </section>

      <WeightsSection onActivated={() => load(scope)} />

      {openRow && data && (
        <WorkbenchPanel
          row={openRow}
          rows={rows}
          data={data}
          scope={scope}
          tab={panel!.tab}
          onTab={(tab) => setPanel((p) => p && { ...p, tab })}
          onStep={step}
          onClose={closePanel}
          onNoteAdded={(n) => patch((rs) => rs.map((r) => (r.issuer_id === n.company_id ? { ...r, notes: { count: r.notes.count + 1, latest: { text: n.text.slice(0, 120), by: n.by, at: n.at } } } : r)))}
        />
      )}

      {dialog === "confirm" && data && (
        <Modal title="Confirm the selection" compact noClose onClose={() => setDialog(null)}>
          <p>
            Confirm {plural(counts.proposed, "company", "companies")} for the {data.cycle} engagement selection? Confirmed rows cannot be removed.
            Recorded as {actor}.
          </p>
          <div className="toolbar">
            <button disabled={busy} onClick={confirmSelection}>
              Confirm
            </button>
            <button className="secondary" onClick={() => setDialog(null)}>
              Cancel
            </button>
          </div>
          {actionError && <p className="error-text" role="alert">{actionError}</p>}
        </Modal>
      )}
      {dialog === "bilateral" && (
        <NameDialog
          title={`Pick ${plural(tickedRows.length, "company", "companies")} for bilateral`}
          label="Reason"
          help="The pick becomes each company's tier proposal until it is withdrawn; it counts once a person confirms it at Checkpoint."
          maxLength={500}
          action="Pick for bilateral"
          onCancel={() => setDialog(null)}
          onSubmit={(reason) =>
            act(async () => {
              const picked: string[] = [], already: string[] = [], failed: string[] = [];
              const ids = new Set<string>();
              // One at a time: each pick makes the server build the house universe, so a burst would stall it for everyone.
              for (const r of tickedRows) {
                try {
                  await api.pickBilateral({ issuer_id: r.issuer_id, reason });
                  picked.push(r.company);
                  ids.add(r.issuer_id);
                } catch (e) {
                  const msg = (e as Error).message;
                  if (/already picked/.test(msg)) already.push(r.company);
                  else failed.push(`${r.company} (${msg})`);
                }
              }
              // A standing pick is the proposal of a row with no confirmed tier (the refetch below confirms it).
              patch((rs) => rs.map((r) => (ids.has(r.issuer_id) && !r.coverage_tier_confirmed ? { ...r, coverage_tier: "bilateral" } : r)));
              setDialog(null);
              setTicked(new Set());
              load(scope);
              return [
                picked.length && `Picked for bilateral: ${picked.join(", ")}.`,
                already.length && `Already picked, left as they are: ${already.join(", ")}.`,
                failed.length && `Not picked: ${failed.join(", ")}.`,
              ]
                .filter(Boolean)
                .join(" ");
            })
          }
        />
      )}
      {dialog === "programme" && (
        <NameDialog
          title="New programme"
          label="Programme name"
          help={`The ${plural(ticked.size, "ticked company", "ticked companies")} are proposed as its first members.`}
          maxLength={80}
          action="Create and add"
          onCancel={() => setDialog(null)}
          onSubmit={(name) =>
            act(async () => {
              const p = await api.createProgramme(name);
              setProgrammes((ps) => [...ps, p]); // listed even if adding the members below fails
              const detail = await api.addProgrammeMembers(p.programme_id, [...ticked]);
              patch((r) => withProgramme(r, detail));
              setDialog(null);
              return `Created ${p.name} and proposed ${plural(ticked.size, "company", "companies")}.`;
            })
          }
        />
      )}
      {dialog === "subgroup" && (
        <NameDialog
          title="Save ticked as subgroup"
          label="Subgroup name"
          help={`A subgroup of ${plural(ticked.size, "company", "companies")}; pick it in step ① to work on it.`}
          maxLength={120}
          action="Save subgroup"
          onCancel={() => setDialog(null)}
          onSubmit={(name) =>
            act(async () => {
              await api.createPortfolioGroup({ name, kind: "companies", members: [...ticked] });
              await loadScopes();
              setDialog(null);
              return `Saved the subgroup ${name}. Pick it in step ①.`;
            })
          }
        />
      )}
      {dialog === "funds" && (
        <FundSubgroupDialog
          funds={scopes.filter((s) => s.kind === "portfolio")}
          onCancel={() => setDialog(null)}
          onSubmit={(name, members) =>
            act(async () => {
              await api.createPortfolioGroup({ name, kind: "portfolios", members });
              await loadScopes();
              setDialog(null);
              return `Saved the fund subgroup ${name}. Pick it in step ①.`;
            })
          }
        />
      )}
    </>
  );
}

/** Closes an open `<details>` menu on Escape (focus back on its summary) or on a click outside it. */
function useDismiss(ref: React.RefObject<HTMLDetailsElement | null>) {
  useEffect(() => {
    const close = (e: Event) => {
      const menu = ref.current;
      if (!menu?.open) return;
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !menu.contains(e.target as Node)) {
        menu.open = false;
        if (e instanceof KeyboardEvent) menu.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("keydown", close);
    document.addEventListener("pointerdown", close);
    return () => {
      document.removeEventListener("keydown", close);
      document.removeEventListener("pointerdown", close);
    };
  }, [ref]);
}

/** A button that opens a menu of actions: nothing happens until an item is clicked (a select's onChange fires on
 * an arrow key, WCAG 3.2.2). */
function MenuButton({ label, disabled, items }: { label: string; disabled?: boolean; items: { key: string; label: string; run: () => void }[] }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useDismiss(ref);
  if (disabled)
    return (
      <button className="secondary" disabled>
        {label}
      </button>
    );
  return (
    <details ref={ref} className="wb-menu wb-menu-button">
      <summary>{label}</summary>
      <div className="wb-menu-panel" role="group" aria-label={label.replace(/[ ▾…]+$/, "")}>
        {items.map((it) => (
          <button
            key={it.key}
            className="link-button wb-menu-item"
            onClick={() => {
              if (ref.current) ref.current.open = false;
              it.run();
            }}
          >
            {it.label}
          </button>
        ))}
      </div>
    </details>
  );
}

function NameDialog({
  title, label, help, maxLength, action, onCancel, onSubmit,
}: { title: string; label: string; help: string; maxLength: number; action: string; onCancel: () => void; onSubmit: (text: string) => void }) {
  const [text, setText] = useState("");
  return (
    <Modal title={title} compact noClose onClose={onCancel}>
      <p className="help-text">{help}</p>
      <form
        className="inline-fields"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) onSubmit(text.trim());
        }}
      >
        <input aria-label={label} placeholder={label} value={text} maxLength={maxLength} autoFocus onChange={(e) => setText(e.target.value)} />
        <button type="submit" disabled={!text.trim()}>
          {action}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </form>
    </Modal>
  );
}

function FundSubgroupDialog({ funds, onCancel, onSubmit }: { funds: WorklistScope[]; onCancel: () => void; onSubmit: (name: string, members: string[]) => void }) {
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  return (
    <Modal title="New fund subgroup" compact noClose onClose={onCancel}>
      <p className="help-text">Its companies are every company held in any of the ticked funds.</p>
      <input aria-label="Subgroup name" placeholder="Subgroup name" value={name} maxLength={120} autoFocus onChange={(e) => setName(e.target.value)} />
      <div className="wb-fund-list" role="group" aria-label="Funds">
        {funds.map((f) => (
          <label key={f.key} className="checkbox-label">
            <input
              type="checkbox"
              checked={picked.has(f.key)}
              onChange={(e) =>
                setPicked((p) => {
                  const next = new Set(p);
                  if (e.target.checked) next.add(f.key);
                  else next.delete(f.key);
                  return next;
                })
              }
            />
            {f.label} <span className="muted">({f.companies})</span>
          </label>
        ))}
      </div>
      <div className="toolbar">
        <button disabled={!name.trim() || picked.size === 0} onClick={() => onSubmit(name.trim(), [...picked].map((k) => k.slice("portfolio:".length)))}>
          Save subgroup
        </button>
        <button className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </Modal>
  );
}

type Weights = { components: { id: string; weight: number }[] } & Record<string, unknown>;

/** The `priority_weights` policy: edit, preview against the active version, save, activate (four-eyes). */
function WeightsSection({ onActivated }: { onActivated: () => void }) {
  const { info, error, reload } = usePolicy("priority_weights");
  const actor = useActor();
  const [draft, setDraft] = useState<Weights | null>(null);
  const [base, setBase] = useState<number | null>(null);
  const [preview, setPreview] = useState<PriorityPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  useEffect(() => {
    if (info && draft === null) {
      setDraft(info.active as Weights);
      setBase(info.active_version);
    }
  }, [info, draft]);
  const total = draft ? weightsTotal(draft.components) : 0;
  const problem = draft ? weightsProblem(draft.components) : undefined;
  const dirty = !!info && !!draft && JSON.stringify(draft) !== JSON.stringify(info.active);
  const setWeight = (id: string, weight: number) => {
    setDraft((d) => (d ? { ...d, components: d.components.map((c) => (c.id === id ? { ...c, weight } : c)) } : d));
    setPreview(null);
  };
  async function runPreview() {
    setPreviewing(true);
    setPreviewError(null);
    try {
      setPreview(await api.previewPriority(draft));
    } catch (e) {
      setPreviewError((e as Error).message);
    } finally {
      setPreviewing(false);
    }
  }
  const moves = (list: PriorityPreview["entering_top"]) =>
    list.length ? (
      <ul className="decision-changes">
        {list.map((m) => (
          <li key={m.issuer_id}>{`${m.company}: rank ${m.rank_active} → ${m.rank_candidate}`}</li>
        ))}
      </ul>
    ) : (
      <p className="muted">None.</p>
    );

  return (
    <>
      {error && <p className="error-text" role="alert">{error}</p>}
      <RuleEditor label="weights">
        <Section step="Design" title="Weights">
          <p className="help-text">
            The priority score is the weighted sum of these indicators, each scaled to 0..1. Weights are whole numbers that add up to 100. One
            set of weights applies to every scope.
          </p>
          <p className="muted">{`Editing ${base === null ? "…" : `a copy of v${base}`}${dirty ? " · unsaved changes" : ""}`}</p>
          {draft && (
            <div className="table-wrap">
              <table className="data-table wb-weights">
                <thead>
                  <tr>
                    <th>Indicator</th>
                    <th>Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {draft.components.map((c) => (
                    <tr key={c.id}>
                      <td>{COMPONENT_LABEL[c.id] ?? c.id}</td>
                      <td>
                        <input
                          type="number"
                          min={0}
                          max={100}
                          step={1}
                          aria-label={`Weight of ${COMPONENT_LABEL[c.id] ?? c.id}`}
                          value={c.weight}
                          onChange={(e) => setWeight(c.id, e.target.value === "" ? 0 : Number(e.target.value))}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={2}>
                      <strong className={total === 100 ? undefined : "error-text"} role="status">
                        {totalText(total)}
                      </strong>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </Section>
        <Section step="Calibrate" title="What these weights would change">
          <div className="toolbar">
            <button onClick={runPreview} disabled={!draft || !!problem || previewing} title={problem}>
              {previewing ? "Running…" : "Preview against the active weights"}
            </button>
          </div>
          {previewError && <p className="error-text" role="alert">{previewError}</p>}
          {preview && (
            <>
              <p className="muted">{preview.companies} companies in the house scope.</p>
              <div className="studio-columns">
                <div>
                  <h3>Entering top 25</h3>
                  {moves(preview.entering_top)}
                </div>
                <div>
                  <h3>Leaving top 25</h3>
                  {moves(preview.leaving_top)}
                </div>
              </div>
              <h3>Largest score changes</h3>
              <DataTable
                rows={preview.score_change.slice(0, 25).map((s) => ({ company: s.company, active: s.active, "these weights": s.candidate, change: s.change }))}
                empty="No company's score would change."
              />
              {preview.score_change.length > 25 && <p className="muted">The 25 largest of {preview.score_change.length} changes.</p>}
            </>
          )}
        </Section>
        <Section step="Versions" title="Save and activate">
          {info && draft && (
            <VersionsPanel
              policyId="priority_weights"
              info={info}
              workingCopy={draft}
              dirty={dirty}
              invalid={problem}
              actor={actor}
              onSaved={reload}
              onLoad={async (v) => {
                setDraft((await api.getStewardPolicyVersion("priority_weights", v)) as Weights);
                setBase(v);
                setPreview(null);
              }}
              onActivated={() => {
                reload();
                onActivated();
              }}
            />
          )}
        </Section>
      </RuleEditor>
    </>
  );
}
