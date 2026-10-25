import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { dossierHref } from "../lib/dossiers";
import { CATEGORY_LABEL, NOTE_SECTIONS, canPropose, canUpload, canWriteNote, planOpen, unreadLines } from "../lib/research";
import type { ResearchNote, ResearchRound, ResearchSource, ResearchView, SourceCategory } from "../types";

const EMPTY_SOURCE = { title: "", publisher: "", url: "", category: "" as SourceCategory | "", why: "", how: "" };

/** #/themes/<id>/research: the latest round's source plan and note, earlier rounds collapsed below. */
export function ThemeResearch({ id }: { id: string }) {
  const [view, setView] = useState<ResearchView | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api.getResearch(id).then(setView, (err: Error) => setError(err.message)), [id]);
  useEffect(() => {
    load();
    api.getDossier(id).then((d) => setName(d.name), () => undefined);
  }, [id, load]);

  const latest = view?.rounds[view.rounds.length - 1];
  const running = latest?.plan_status === "proposing" || latest?.note?.status === "writing";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(load, 2000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  const act = useCallback(
    async (call: () => Promise<unknown>) => {
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

  if (error) return <div className="page"><p className="error-text" role="alert">The research could not be loaded: {error}.</p><a href={dossierHref(id)}>Back to the dossier</a></div>;
  if (!view) return <p className="muted" role="status">Loading…</p>;
  const earlier = view.rounds.slice(0, -1).reverse();
  return (
    <div className="page">
      <p><a href={dossierHref(id)}>Back to the dossier</a></p>
      <h1>Research{name && `: ${name}`}</h1>
      <p className="help-text">Sources come only from intergovernmental agencies, official statistics, central banks or regulators, and academic research. Every statement in the note quotes one of the approved sources.</p>
      {actionError && <p className="error-text" role="alert">{actionError}</p>}
      {canPropose(latest) && (
        <button type="button" disabled={busy} onClick={() => act(() => api.proposeSources(id))}>
          Propose sources
        </button>
      )}
      {latest && <LatestRound id={id} round={latest} busy={busy} act={act} />}
      {earlier.length > 0 && (
        <section aria-label="Earlier rounds">
          <h2>Earlier rounds</h2>
          {earlier.map((r) => (
            <details key={r.round} className="card">
              <summary>
                Round {r.round} · taxonomy v{r.taxonomy_version}
                {r.note?.status === "approved" && ` · note approved by ${r.note.approved_by}`}
              </summary>
              <SourceTable round={r} />
              {r.note && <Note round={r} note={r.note} />}
            </details>
          ))}
        </section>
      )}
    </div>
  );
}

type Act = (call: () => Promise<unknown>) => Promise<boolean>;

function LatestRound({ id, round, busy, act }: { id: string; round: ResearchRound; busy: boolean; act: Act }) {
  const [reason, setReason] = useState("");
  const open = planOpen(round);
  const note = round.note;
  return (
    <>
      <section className="card" aria-label="Sources">
        <h2>Sources · round {round.round}</h2>
        {round.plan_status === "proposing" && <p className="muted" role="status">Proposing sources…</p>}
        {round.plan_status === "proposal_failed" && <p className="error-text" role="alert">The source proposal failed. Propose again.</p>}
        {round.plan_status === "approved" && <p className="muted">Approved by {round.plan_approved_by} on {round.plan_approved_at?.slice(0, 10)}.</p>}
        {round.plan_status !== "proposing" && (
          <SourceTable
            round={round}
            onRemove={open ? (s) => act(() => api.removeResearchSource(id, s.source_id)) : undefined}
            onUpload={canUpload(round) ? (s, f) => act(() => api.uploadResearchFile(id, s.source_id, f)) : undefined}
          />
        )}
        {open && <AddSource busy={busy} onAdd={(body) => act(() => api.addResearchSource(id, body))} />}
        {open && (
          <button type="button" disabled={busy} onClick={() => act(() => api.approveSourcePlan(id))}>
            Approve sources
          </button>
        )}
      </section>
      {canWriteNote(round) && (
        <button type="button" disabled={busy} onClick={() => act(() => api.writeNote(id))}>
          Write note
        </button>
      )}
      {note?.status === "writing" && <p className="muted" role="status">Writing the note…</p>}
      {note?.status === "write_failed" && <p className="error-text" role="alert">The note could not be written: {note.error}.</p>}
      {note && note.status !== "writing" && note.status !== "write_failed" && (
        <section className="card" aria-label="Note">
          <Note round={round} note={note} />
          {note.status === "written" && (
            <div className="inline-fields">
              <button type="button" disabled={busy} onClick={() => act(() => api.approveNote(id))}>
                Approve note
              </button>
              <form
                className="inline-fields"
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (await act(() => api.rejectNote(id, reason))) setReason("");
                }}
              >
                <label htmlFor="note-reason">Reason</label>
                <input id="note-reason" value={reason} onChange={(e) => setReason(e.target.value)} required />
                <button type="submit" className="secondary" disabled={busy || !reason.trim()}>
                  Reject note
                </button>
              </form>
            </div>
          )}
        </section>
      )}
    </>
  );
}

function SourceTable({ round, onRemove, onUpload }: { round: ResearchRound; onRemove?: (s: ResearchSource) => void; onUpload?: (s: ResearchSource, f: File) => void }) {
  if (!round.sources.length) return <p className="muted">No sources. Add one below.</p>;
  return (
    <div className="table-wrap">
      <table className="data-table stack-on-phone" aria-label={`Sources, round ${round.round}`}>
        <thead>
          <tr>
            <th>Title</th>
            <th>Publisher</th>
            <th>Category</th>
            <th>Why</th>
            <th>How</th>
            <th>File</th>
            {onRemove && <th><span className="visually-hidden">Remove</span></th>}
          </tr>
        </thead>
        <tbody>
          {round.sources.map((s) => (
            <tr key={s.source_id}>
              <td><a href={s.url} target="_blank" rel="noreferrer">{s.title}</a></td>
              <td>{s.publisher}</td>
              <td>{CATEGORY_LABEL[s.category]}</td>
              <td>{s.why}</td>
              <td>{s.how}</td>
              <td>
                {s.file && <span className="mono">{s.file.filename}</span>}
                {onUpload && (
                  <label className="secondary">
                    {s.file ? " Replace" : "Upload"}
                    <input
                      type="file"
                      accept=".pdf,.html,.htm,.txt"
                      className="visually-hidden"
                      aria-label={`Upload a file for ${s.title}`}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) onUpload(s, f);
                        e.target.value = "";
                      }}
                    />
                  </label>
                )}
              </td>
              {onRemove && (
                <td>
                  <button type="button" className="secondary" onClick={() => onRemove(s)} aria-label={`Remove ${s.title}`}>
                    Remove
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AddSource({ busy, onAdd }: { busy: boolean; onAdd: (body: Omit<typeof EMPTY_SOURCE, "category"> & { category: SourceCategory }) => Promise<boolean> }) {
  const [form, setForm] = useState(EMPTY_SOURCE);
  const field = (key: Exclude<keyof typeof EMPTY_SOURCE, "category">, label: string) => (
    <div>
      <label htmlFor={`source-${key}`}>{label}</label>{" "}
      <input id={`source-${key}`} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} required />
    </div>
  );
  const complete = Object.values(form).every((v) => v.trim());
  return (
    <form
      aria-label="Add source"
      onSubmit={async (e) => {
        e.preventDefault();
        if (form.category && (await onAdd({ ...form, category: form.category }))) setForm(EMPTY_SOURCE);
      }}
    >
      <h3>Add source</h3>
      <div className="inline-fields">
      {field("title", "Title")}
      {field("publisher", "Publisher")}
      {field("url", "URL")}
      <div>
      <label htmlFor="source-category">Category</label>{" "}
      <select id="source-category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as SourceCategory })} required>
        <option value="">Pick a category</option>
        {Object.entries(CATEGORY_LABEL).map(([value, label]) => (
          <option key={value} value={value}>{label}</option>
        ))}
      </select>
      </div>
      {field("why", "Why")}
      {field("how", "How")}
      <button type="submit" disabled={busy || !complete}>
        Add source
      </button>
      </div>
    </form>
  );
}

function Note({ round, note }: { round: ResearchRound; note: ResearchNote }) {
  const [opened, setOpened] = useState<string | null>(null);
  const source = (sid: string) => round.sources.find((s) => s.source_id === sid);
  return (
    <div>
      <h2>Note · {note.status === "rejected" ? `rejected: ${note.reject_reason}` : note.status === "approved" ? `approved by ${note.approved_by}` : "awaiting approval"}</h2>
      {NOTE_SECTIONS.map(([key, heading]) => (
        <section key={key} aria-label={heading}>
          <h3>{heading}</h3>
          {note.sections[key].length === 0 && <p className="muted">Nothing the sources support.</p>}
          {note.sections[key].map((item) => (
            <article key={item.item_id}>
              <h4>
                {item.title}
                {item.channel && <span className="status-pill status-pending"> {item.channel === "economic" ? "Economic" : "Financial"}</span>}
              </h4>
              <p>
                {item.text}
                {item.citations.map((_c, i) => {
                  const key = `${item.item_id}:${i}`;
                  return (
                    <button key={key} type="button" className="citation-marker" aria-expanded={opened === key}
                      aria-label={`Citation ${i + 1}`} onClick={() => setOpened(opened === key ? null : key)}>
                      [{i + 1}]
                    </button>
                  );
                })}
              </p>
              {item.citations.map((c, i) => {
                if (opened !== `${item.item_id}:${i}`) return null;
                const s = source(c.source_id);
                return (
                  <blockquote key={i} className="card">
                    <p>“{c.quote}”</p>
                    <p className="muted">
                      {s?.title ?? c.source_id}
                      {c.page != null && `, page ${c.page}`}
                      {s && <> · <a href={s.url} target="_blank" rel="noreferrer">{s.url}</a></>}
                    </p>
                  </blockquote>
                );
              })}
            </article>
          ))}
        </section>
      ))}
      {unreadLines(round).map((line) => (
        <p key={line} className="muted">{line}</p>
      ))}
      {note.dropped_items > 0 && <p className="muted">Dropped for lack of a checked quote: {note.dropped_items}</p>}
    </div>
  );
}
