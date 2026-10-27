import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { dossierHref } from "../lib/dossiers";
import { DATA_LABEL, checkGrid, criterion, editorDraft, latestStandards, positionState, releasedFieldIds } from "../lib/position";
import { NOTE_SECTIONS } from "../lib/research";
import { useMe } from "../lib/reviewer";
import type { PositionVersion, PositionView, ResearchView, StandardsDraft, StandardsVersion, StandardsView } from "../types";

type Act = (call: () => Promise<unknown>) => Promise<boolean>;

/** #/themes/<id>/position: the latest position version, then the latest standards version and the company check. */
export function ThemePosition({ id }: { id: string }) {
  const [position, setPosition] = useState<PositionView | null>(null);
  const [standards, setStandards] = useState<StandardsView | null>(null);
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const approver = useMe()?.role === "approver";

  const load = useCallback(
    () => Promise.all([api.getPosition(id), api.getStandards(id)]).then(([p, s]) => { setPosition(p); setStandards(s); }),
    [id],
  );
  useEffect(() => {
    load().catch((err: Error) => setError(err.message));
    api.getDossier(id).then((d) => setName(d.name), () => undefined);
    api.getResearch(id).then((r) => setTitles(itemTitles(r)), () => undefined);
  }, [id, load]);

  const act: Act = useCallback(
    async (call) => {
      setBusy(true);
      setActionError(null);
      try {
        await call();
        await load();
        return true;
      } catch (err) {
        setActionError((err as Error).message);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  if (error) return <div className="page"><p className="error-text" role="alert">The position could not be loaded: {error}.</p><a href={dossierHref(id)}>Back to the dossier</a></div>;
  if (!position || !standards) return <p className="muted" role="status">Loading…</p>;
  return (
    <div className="page">
      <p><a href={dossierHref(id)}>Back to the dossier</a></p>
      <h1>Position and standards{name && `: ${name}`}</h1>
      {actionError && <p className="error-text" role="alert">{actionError}</p>}
      <Position id={id} view={position} titles={titles} approver={approver} busy={busy} act={act} />
      {position.approved_version !== null && <Standards id={id} view={standards} approver={approver} busy={busy} act={act} />}
    </div>
  );
}

function itemTitles(r: ResearchView): Record<string, string> {
  const note = r.rounds.find((x) => x.round === r.approved_round)?.note;
  const items = note ? NOTE_SECTIONS.flatMap(([key]) => note.sections[key]) : [];
  return Object.fromEntries(items.map((i) => [i.item_id, i.title]));
}

function Redraft({ label, busy, onRedraft }: { label: string; busy: boolean; onRedraft: (instructions: string | null) => Promise<boolean> }) {
  const [instructions, setInstructions] = useState("");
  const fieldId = `instructions-${label}`;
  return (
    <form
      className="inline-fields"
      onSubmit={async (e) => {
        e.preventDefault();
        if (await onRedraft(instructions.trim() || null)) setInstructions("");
      }}
    >
      <label htmlFor={fieldId}>Instructions</label>
      <textarea id={fieldId} rows={2} value={instructions} onChange={(e) => setInstructions(e.target.value)} />
      <button type="submit" className="secondary" disabled={busy}>Redraft</button>
    </form>
  );
}

function Position({ id, view, titles, approver, busy, act }: { id: string; view: PositionView; titles: Record<string, string>; approver: boolean; busy: boolean; act: Act }) {
  const [editing, setEditing] = useState(false);
  const latest = view.versions.at(-1);
  return (
    <section className="card" aria-label="Position">
      <h2>Position{latest && ` · v${latest.version} · ${positionState(view, latest)}`}</h2>
      {!latest && (
        <button type="button" disabled={busy} onClick={() => act(() => api.draftPosition(id, null))}>
          Draft position
        </button>
      )}
      {latest && !editing && (
        <>
          <p>{latest.summary}</p>
          {latest.paragraphs.map((p, i) => (
            <article key={i}>
              <p>{p.text}</p>
              <p className="muted">{p.cites.map((c) => `${c} · ${titles[c] ?? c}`).join("; ")}</p>
            </article>
          ))}
          {latest.instructions && <p className="muted">Redrafted with: {latest.instructions}</p>}
          <Redraft label="position" busy={busy} onRedraft={(text) => act(() => api.draftPosition(id, text))} />
          {approver && (
            <div className="toolbar">
              <button type="button" className="secondary" disabled={busy} onClick={() => setEditing(true)}>Edit</button>
              {view.approved_version !== latest.version && (
                <button type="button" disabled={busy} onClick={() => act(() => api.approvePosition(id, latest.version))}>
                  Approve
                </button>
              )}
            </div>
          )}
        </>
      )}
      {latest && editing && (
        <PositionEditor version={latest} busy={busy} onCancel={() => setEditing(false)}
          onSave={async (body) => {
            if (await act(() => api.savePosition(id, body))) setEditing(false);
          }} />
      )}
    </section>
  );
}

function PositionEditor({ version, busy, onSave, onCancel }: { version: PositionVersion; busy: boolean; onSave: (body: { summary: string; paragraphs: { text: string; cites: string[] }[] }) => void; onCancel: () => void }) {
  const [summary, setSummary] = useState(version.summary);
  const [paragraphs, setParagraphs] = useState(version.paragraphs.map((p) => ({ text: p.text, cites: p.cites.join(", ") })));
  const set = (i: number, key: "text" | "cites", value: string) =>
    setParagraphs(paragraphs.map((p, j) => (j === i ? { ...p, [key]: value } : p)));
  return (
    <form
      aria-label="Edit position"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({ summary, paragraphs: paragraphs.map((p) => ({ text: p.text, cites: p.cites.split(",").map((c) => c.trim()).filter(Boolean) })) });
      }}
    >
      <label htmlFor="position-summary">Summary</label>
      <textarea id="position-summary" rows={2} value={summary} onChange={(e) => setSummary(e.target.value)} />
      {paragraphs.map((p, i) => (
        <div key={i}>
          <label htmlFor={`paragraph-${i}`}>Paragraph {i + 1}</label>
          <textarea id={`paragraph-${i}`} rows={4} value={p.text} onChange={(e) => set(i, "text", e.target.value)} />
          <label htmlFor={`cites-${i}`}>Cites (item ids)</label>{" "}
          <input id={`cites-${i}`} value={p.cites} onChange={(e) => set(i, "cites", e.target.value)} />
        </div>
      ))}
      <div className="toolbar">
        <button type="submit" disabled={busy}>Save as new version</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function Standards({ id, view, approver, busy, act }: { id: string; view: StandardsView; approver: boolean; busy: boolean; act: Act }) {
  const [editing, setEditing] = useState(false);
  const latest = latestStandards(view.versions);
  const lastActivation = view.activations.at(-1);
  const state = !latest ? "" : latest.version === view.active_version
    ? `Approved by ${lastActivation?.approved_by}` : `Draft by ${latest.created_by}`;
  return (
    <section className="card" aria-label="Standards">
      <h2>Standards{latest && ` · v${latest.version} · ${state}`}</h2>
      {!latest && (
        <button type="button" disabled={busy} onClick={() => act(() => api.draftStandards(id, null))}>
          Draft standards
        </button>
      )}
      {latest && !editing && (
        <>
          <StandardsTable version={latest} names={view.field_names} />
          <Redraft label="standards" busy={busy} onRedraft={(text) => act(() => api.draftStandards(id, text))} />
          {approver && (
            <div className="toolbar">
              <button type="button" className="secondary" disabled={busy} onClick={() => setEditing(true)}>Edit</button>
              {latest.version !== view.active_version && (
                <button type="button" disabled={busy} onClick={() => act(() => api.activateStandards(id, latest.version))}>
                  Approve
                </button>
              )}
            </div>
          )}
        </>
      )}
      {latest && editing && (
        <StandardsEditor version={latest} released={releasedFieldIds(view)} busy={busy} onCancel={() => setEditing(false)}
          onSave={async (body) => {
            if (await act(() => api.saveStandards(id, body))) setEditing(false);
          }} />
      )}
      {view.active_version > 0 && (
        <section aria-label="Company check">
          <h3>Company check</h3>
          <button type="button" disabled={busy} onClick={() => act(() => api.checkStandards(id))}>Check companies</button>
          {view.latest_check && <CheckGrid check={view.latest_check} />}
        </section>
      )}
    </section>
  );
}

function StandardsTable({ version, names }: { version: StandardsVersion; names: Record<string, string> }) {
  return (
    <div className="table-wrap">
      <table className="data-table stack-on-phone" aria-label={`Standards, version ${version.version}`}>
        <thead>
          <tr>
            <th>Standard</th>
            <th>Definition</th>
            <th>Where reported</th>
            <th>Criterion</th>
            <th>Data</th>
            <th>Severity</th>
            <th>Rests on</th>
          </tr>
        </thead>
        <tbody>
          {version.standards.map((s) => (
            <tr key={s.standard_id}>
              <td><span><strong>{s.standard_id}</strong> {s.title}<br /><span className="muted">{s.expectation}</span></span></td>
              <td data-label="Definition">{s.definition}</td>
              <td data-label="Where reported">{s.where_reported}</td>
              <td data-label="Criterion"><span className="mono">{criterion(s, names)}</span></td>
              <td data-label="Data">{DATA_LABEL[s.data]}</td>
              <td data-label="Severity">{s.severity}</td>
              <td data-label="Rests on">{s.rests_on.map((n) => `¶${n}`).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StandardsEditor({ version, released, busy, onSave, onCancel }: { version: StandardsVersion; released: Set<string>; busy: boolean; onSave: (body: StandardsDraft) => void; onCancel: () => void }) {
  // Released theme fields are carried by the server; only the fields this version adds are edited here.
  const [text, setText] = useState(() => JSON.stringify(editorDraft(version, released), null, 2));
  const [parseError, setParseError] = useState<string | null>(null);
  return (
    <form
      aria-label="Edit standards"
      onSubmit={(e) => {
        e.preventDefault();
        try {
          onSave(JSON.parse(text) as StandardsDraft);
          setParseError(null);
        } catch (err) {
          setParseError((err as Error).message);
        }
      }}
    >
      <label htmlFor="standards-json">Standards and new fields (JSON)</label>
      <textarea id="standards-json" className="mono" rows={18} value={text} onChange={(e) => setText(e.target.value)} />
      {parseError && <p className="error-text" role="alert">{parseError}</p>}
      <div className="toolbar">
        <button type="submit" disabled={busy}>Save as new version</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function CheckGrid({ check }: { check: NonNullable<StandardsView["latest_check"]> }) {
  const grid = checkGrid(check);
  return (
    <div className="table-wrap">
      <p className="muted">Checked {check.checked_at.slice(0, 16).replace("T", " ")} · {check.flagged} flagged</p>
      <table className="data-table" aria-label="Company check">
        <thead>
          <tr>
            <th>Company</th>
            {grid.standards.map((s) => <th key={s}>{s}</th>)}
          </tr>
        </thead>
        <tbody>
          {grid.rows.map((r) => (
            <tr key={r.name}>
              <td>{r.name}</td>
              {r.cells.map((c, i) => <td key={grid.standards[i]} className={c === "Unmet" ? "error-text" : undefined}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
