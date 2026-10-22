import { useEffect, useRef, useState } from "react";
import { api, downloadFile } from "../api/client";
import { announce } from "../lib/announce";
import { useMe } from "../lib/reviewer";
import type { RfpLibraryEntry, RfpProject, RfpProjectSummary, RfpQuestion } from "../types";

const STATUS_BADGE: Record<string, string> = {
  "no source": "badge badge-low",
  drafted: "badge badge-mid",
  edited: "badge badge-mid",
  approved: "badge badge-high",
  "left blank": "badge badge-neutral",
};
const RUNNING = new Set(["detecting", "drafting"]);
const rank = { viewer: 0, analyst: 1, approver: 2 } as const;

interface Props {
  projectId: number | null;
  onOpen: (id: number | null) => void;
}

/** RFP answers: the answer library, incoming RFPs, and each RFP's questions to draft, review and export. */
export function RfpAnswers({ projectId, onOpen }: Props) {
  return projectId === null ? <Overview onOpen={onOpen} /> : <ProjectView id={projectId} onBack={() => onOpen(null)} />;
}

function Overview({ onOpen }: { onOpen: (id: number) => void }) {
  const me = useMe();
  const [projects, setProjects] = useState<RfpProjectSummary[] | null>(null);
  const [library, setLibrary] = useState<RfpLibraryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => {
    api.listRfpProjects().then(setProjects, (e: Error) => setError(e.message));
    api.listRfpLibrary().then(setLibrary, (e: Error) => setError(e.message));
  };
  useEffect(load, []);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      load();
    }
  }

  function createProject(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const form = new FormData(ev.currentTarget);
    const file = form.get("file") as File;
    void act(async () => onOpen((await api.createRfpProject(file, String(form.get("investor")), String(form.get("due_date") ?? ""))).id));
  }

  function importFiles(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const files = (new FormData(ev.currentTarget).getAll("files") as File[]).filter((f) => f.size > 0);
    void act(async () => {
      const r = await api.importRfpLibrary(files);
      announce(`Imported ${r.imported} entries, dropped ${r.dropped.length}${r.dropped.length ? `: ${r.dropped.join("; ")}` : ""}`);
    });
  }

  const approver = me?.role === "approver";
  return (
    <div className="page">
      <h1>RFP Answers</h1>
      <p className="help-text">
        Upload an investor's RFP (Word or Excel). Its questions are found and drafted only from the answer library, each
        draft showing the entries it came from. A second person approves every answer; approved answers go back into the
        investor's own file and into the library.
      </p>
      {error && <p className="error-text" role="alert">{error}</p>}

      <section className="card">
        <h2>RFPs</h2>
        {me && rank[me.role] >= rank.analyst && (
          <form className="inline-fields" onSubmit={createProject}>
            <input id="rfp-file" name="file" type="file" accept=".docx,.xlsx" required aria-label="Investor's RFP file" />
            <input id="rfp-investor" name="investor" required placeholder="Investor" aria-label="Investor" />
            <input id="rfp-due" name="due_date" type="date" aria-label="Due date" />
            <button disabled={busy}>Upload RFP</button>
          </form>
        )}
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Investor</th><th>File</th><th>Due</th><th>Status</th><th>Approved</th></tr></thead>
            <tbody>
              {projects?.length === 0 && <tr><td colSpan={5} className="muted">No RFPs yet.</td></tr>}
              {projects?.map((p) => (
                <tr key={p.id}>
                  <td><a href={`#/rfp/${p.id}`}>{p.investor}</a></td>
                  <td>{p.filename}</td>
                  <td>{p.due_date ?? "—"}</td>
                  <td>{p.run_status}</td>
                  <td>{p.approved_count} of {p.question_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h2>Answer library</h2>
        {approver && (
          <form className="inline-fields" onSubmit={importFiles}>
            <input id="rfp-library-files" name="files" type="file" accept=".docx,.xlsx" multiple required aria-label="Past RFP responses" />
            <button disabled={busy}>Import past responses</button>
          </form>
        )}
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Question</th><th>Answer</th><th>Source</th><th>Review by</th><th>Status</th><th /></tr></thead>
            <tbody>
              {library?.length === 0 && <tr><td colSpan={6} className="muted">The library is empty: import past RFP responses.</td></tr>}
              {library?.map((e) => (
                <tr key={e.id}>
                  <td>{e.question}</td>
                  <td>{e.answer}</td>
                  <td>{e.source}</td>
                  <td>{e.review_by}</td>
                  <td>{e.status}</td>
                  <td>
                    {approver && e.status === "active" && (
                      <button className="secondary" disabled={busy} onClick={() => void act(() => api.retireRfpEntry(e.id))}>Retire</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function ProjectView({ id, onBack }: { id: number; onBack: () => void }) {
  const me = useMe();
  const [project, setProject] = useState<RfpProject | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mine, setMine] = useState(false);
  const [confirmExport, setConfirmExport] = useState(false);

  const running = project !== null && RUNNING.has(project.run_status);
  useEffect(() => {
    api.getRfpProject(id).then(setProject, (e: Error) => setError(e.message));
  }, [id]);
  // Bumped by every action, so a poll that started before it never overwrites its newer result.
  const actions = useRef(0);
  // Keyed on `running`, so a run started from this page ("Auto-fill again") is polled too.
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      const seen = actions.current;
      api.getRfpProject(id).then((p) => seen === actions.current && setProject(p), (e: Error) => setError(e.message));
    }, 3000);
    return () => clearInterval(timer);
  }, [id, running]);

  async function act(fn: () => Promise<RfpProject>) {
    setError(null);
    actions.current += 1;
    try {
      const result = await fn();
      actions.current += 1; // also drops a poll that started while this request was in flight
      setProject(result);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!project) return <div className="page">{error ? <p className="error-text" role="alert">{error}</p> : <p className="muted">Loading…</p>}</div>;
  const unapproved = project.question_count - project.approved_count;
  const shown = mine ? project.questions.filter((q) => q.assignee === me?.user_id) : project.questions;
  const download = () => {
    setConfirmExport(false);
    downloadFile(api.rfpExportUrl(id), project.filename).catch((e: Error) => setError(e.message));
  };

  return (
    <div className="page">
      <p><a href="#/rfp" onClick={onBack}>← All RFPs</a></p>
      <h1>{project.investor}</h1>
      <p className="help-text">
        {project.filename}{project.due_date ? ` · due ${project.due_date}` : ""} · {project.question_count} questions ·{" "}
        {project.approved_count} approved · {project.not_located} not located · {project.run_status}
      </p>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="toolbar">
        <label className="field-label checkbox-label">
          <input id="rfp-mine" type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Assigned to me
        </label>
        {me && rank[me.role] >= rank.analyst && (
          <button className="secondary" onClick={() => void act(() => api.autofillRfp(id))}>
            Auto-fill again
          </button>
        )}
        <button onClick={() => (unapproved > 0 ? setConfirmExport(true) : download())}>Download filled file</button>
      </div>
      {confirmExport && (
        <div className="card" role="alertdialog" aria-label="Unapproved questions">
          <p>
            {unapproved} {unapproved === 1 ? "question is" : "questions are"} not approved. Only approved answers are written into
            the file; the rest stay empty.
          </p>
          <div className="toolbar">
            <button onClick={download}>Download anyway</button>
            <button className="secondary" onClick={() => setConfirmExport(false)}>Cancel</button>
          </div>
        </div>
      )}
      {shown.length === 0 && <p className="muted">{mine ? "No questions are assigned to you." : "No questions found yet."}</p>}
      {shown.map((q) => (
        <QuestionCard key={q.id} q={q} projectId={id} act={act} />
      ))}
    </div>
  );
}

function QuestionCard({ q, projectId, act }: { q: RfpQuestion; projectId: number; act: (fn: () => Promise<RfpProject>) => Promise<void> }) {
  const me = useMe();
  const [answer, setAnswer] = useState(q.answer);
  const [confirmed, setConfirmed] = useState<string[]>([]);
  useEffect(() => setAnswer(q.answer), [q.answer]);
  const canEdit = !!me && rank[me.role] >= rank.analyst;
  const canApprove = me?.role === "approver" && q.status !== "approved" && q.last_editor !== me.user_id && q.answer.trim() !== "";

  return (
    <section className="card" aria-label={`Question ${q.location}`}>
      <p className="muted">{q.location} → answer at {q.answer_location}</p>
      <h2>{q.question}</h2>
      <div className="chip-row">
        <span className={STATUS_BADGE[q.status] ?? "badge"}>{q.status}</span>
        {q.flags.map((f) => <span key={f} className="chip chip-warn">{f}</span>)}
        <span className="chip">{q.assignee ? `assigned to ${q.assignee}` : "unassigned"}</span>
        {q.last_editor && <span className="chip">last edited by {q.last_editor}</span>}
      </div>
      <label className="field-label">
        Answer
        <textarea id={`rfp-answer-${q.id}`} rows={3} value={answer} readOnly={!canEdit} onChange={(e) => setAnswer(e.target.value)} />
      </label>
      {q.sources.length > 0 && (
        <ul>
          {q.sources.map((s, i) => (
            <li key={i}>
              <strong>{s.entry_question}</strong> “{s.quote}” <span className="muted">— {s.file ? `${s.file}, ${s.location}` : s.source}</span>
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <div className="toolbar">
          <button disabled={answer === q.answer} onClick={() => void act(() => api.editRfpAnswer(projectId, q.id, answer))}>Save answer</button>
          <button className="secondary" onClick={() => void act(() => api.assignRfp(projectId, q.id, q.assignee === me?.user_id ? null : me?.user_id ?? null))}>
            {q.assignee === me?.user_id ? "Unassign me" : "Assign to me"}
          </button>
          <button className="secondary" onClick={() => void act(() => api.leaveRfpBlank(projectId, q.id))}>Leave blank</button>
        </div>
      )}
      {canApprove && (
        <div className="inline-fields">
          {q.flags.map((f) => (
            <label key={f}>
              <input type="checkbox" checked={confirmed.includes(f)} onChange={(e) => setConfirmed(e.target.checked ? [...confirmed, f] : confirmed.filter((x) => x !== f))} />
              {f === "check figure" ? "Figures checked" : "Stale source checked"}
            </label>
          ))}
          <button disabled={q.flags.some((f) => !confirmed.includes(f))} onClick={() => void act(() => api.approveRfp(projectId, q.id, confirmed))}>
            Approve
          </button>
        </div>
      )}
    </section>
  );
}
