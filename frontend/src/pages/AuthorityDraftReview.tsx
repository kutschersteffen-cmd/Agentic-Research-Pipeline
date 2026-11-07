import { useEffect, useState } from "react";
import { api } from "../api/client";
import { setLeaveGuard } from "../lib/leaveGuard";
import { CHECKLIST_KEYS, editText, saveThenAccept } from "../lib/authorityTaxonomy";
import type { AuthorityDraft, AuthorityRunState } from "../types";

type Cite = AuthorityDraft["technologies"][number]["citations"][number];
type Activity = AuthorityDraft["activities"][number];
type Role = Activity["value_chain_role"];

function Citations({ items }: { items: Cite[] }) {
  if (!items.length) return null;
  return (
    <ul className="plain-list" aria-label="Citations">
      {items.map((c, i) => (
        <li key={i}>
          <blockquote className="muted">“{c.quote}”</blockquote>
          <a href={c.source_url} target="_blank" rel="noreferrer">{c.source_url}</a>
          {c.location ? <span className="muted"> · {c.location}</span> : null}
        </li>
      ))}
    </ul>
  );
}

/** One editable, removable item with read-only citations. */
function Item({ children, citations, onRemove, label }: { children: React.ReactNode; citations: Cite[]; onRemove: () => void; label: string }) {
  return (
    <li className="card">
      {children}
      <Citations items={citations} />
      <button type="button" onClick={onRemove} aria-label={`Remove ${label}`}>Remove</button>
    </li>
  );
}

const replaceAt = <T,>(list: T[], i: number, next: T): T[] => list.map((x, j) => (j === i ? next : x));
const removeAt = <T,>(list: T[], i: number): T[] => list.filter((_, j) => j !== i);

function ActivityBlock({ a, onChange, onRemove }: { a: Activity; onChange: (a: Activity) => void; onRemove: () => void }) {
  const [kw, setKw] = useState("");
  const keywords = a.seed_keywords ?? [];
  return (
    <li className="card" aria-label={`Activity ${a.name}`}>
      <label>Name<input value={a.name} onChange={(e) => onChange(editText(a, { name: e.target.value }))} /></label>
      <label>In scope<textarea value={a.in_scope_description} onChange={(e) => onChange(editText(a, { in_scope_description: e.target.value }))} /></label>
      <label>Out of scope<textarea value={a.out_of_scope_description} onChange={(e) => onChange(editText(a, { out_of_scope_description: e.target.value }))} /></label>
      <label>
        Value-chain role
        <select value={a.value_chain_role} onChange={(e) => onChange(editText(a, { value_chain_role: e.target.value as Role }))}>
          {["core", "upstream", "enabling"].map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </label>
      <h4>Criteria</h4>
      <ul className="plain-list">
        {(a.criteria ?? []).map((c, i) => (
          <Item key={i} label={`criterion ${i + 1}`} citations={c.citations ?? []} onRemove={() => onChange({ ...a, criteria: removeAt(a.criteria ?? [], i) })}>
            <textarea aria-label={`Criterion ${i + 1}`} value={c.text}
              onChange={(e) => onChange({ ...a, criteria: replaceAt(a.criteria ?? [], i, editText({ ...c, citations: c.citations ?? [] }, { text: e.target.value })) })} />
          </Item>
        ))}
      </ul>
      <h4>Seed keywords</h4>
      <div>
        {keywords.map((k, i) => (
          <span key={`${k}-${i}`} className="chip">
            {k} <button type="button" aria-label={`Remove keyword ${k}`} onClick={() => onChange({ ...a, seed_keywords: removeAt(keywords, i) })}>×</button>
          </span>
        ))}
        <input aria-label="New keyword" value={kw} onChange={(e) => setKw(e.target.value)} />
        <button type="button" disabled={!kw.trim()} onClick={() => { onChange({ ...a, seed_keywords: [...keywords, kw.trim()] }); setKw(""); }}>Add keyword</button>
      </div>
      <h4>Sector codes</h4>
      <ul className="plain-list">
        {(a.sector_codes ?? []).map((s, i) => (
          <li key={i}>
            {s.system} {s.code} <span className="badge">{s.origin}</span>{" "}
            <button type="button" aria-label={`Remove ${s.system} ${s.code}`} onClick={() => onChange({ ...a, sector_codes: removeAt(a.sector_codes ?? [], i) })}>Remove</button>
          </li>
        ))}
      </ul>
      <h4>Citations</h4>
      <Citations items={a.citations ?? []} />
      {(a.out_of_scope_citations ?? []).length > 0 && <><h4>Out-of-scope citations</h4><Citations items={a.out_of_scope_citations ?? []} /></>}
      <button type="button" onClick={onRemove}>Remove activity</button>
    </li>
  );
}

const FOUND = (v: string | undefined) => (v === "found" ? "found" : "not in source");

export function AuthorityDraftReview({ run, onRun }: { run: AuthorityRunState; onRun: (r: AuthorityRunState) => void }) {
  const [draft, setDraft] = useState<AuthorityDraft>(run.draft as AuthorityDraft);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const id = run.run_id;

  const edit = (next: AuthorityDraft) => { setDraft(next); setDirty(true); };

  useEffect(() => {
    if (!dirty) return;
    setLeaveGuard(() => window.confirm("Discard your unsaved edits?"));
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => { setLeaveGuard(null); window.removeEventListener("beforeunload", warn); };
  }, [dirty]);

  // A 409 means the run moved on: show whatever stage it is at now.
  async function guarded(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      const msg = (e as Error).message;
      if (msg.startsWith("409")) { setDirty(false); onRun(await api.getAuthorityRun(id)); }
      else setError(msg.replace(/^\d+: /, ""));
    } finally {
      setBusy(false);
    }
  }
  const save = async () => { await api.putAuthorityDraft(id, draft); setDirty(false); };

  const sources = Object.keys(draft.checklist_report ?? {});
  return (
    <div>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="inline-block">
        <button disabled={busy || !dirty} onClick={() => guarded(save)}>Save</button>
        <button disabled={busy} onClick={() => guarded(async () => {
          await saveThenAccept(dirty, save, () => api.acceptAuthorityRun(id));
          setDirty(false);
          onRun(await api.getAuthorityRun(id));
        })}>Accept</button>
        <button disabled={busy} onClick={() => { if (window.confirm("Cancel this run? The draft is discarded.")) guarded(async () => { await api.cancelAuthorityRun(id); setDirty(false); onRun(await api.getAuthorityRun(id)); }); }}>Cancel</button>
      </div>

      <section><h3>Theme description</h3>
        <p className="muted">Scope: {draft.scope || "none"}</p>
        <textarea aria-label="Theme description" value={draft.description} onChange={(e) => edit({ ...draft, description: e.target.value })} />
      </section>

      <section><h3>Technologies</h3>
        <ul className="plain-list">{(draft.technologies ?? []).map((t, i) => (
          <Item key={i} label={`technology ${t.name}`} citations={t.citations ?? []} onRemove={() => edit({ ...draft, technologies: removeAt(draft.technologies ?? [], i) })}>
            <input aria-label={`Technology ${i + 1}`} value={t.name} onChange={(e) => edit({ ...draft, technologies: replaceAt(draft.technologies ?? [], i, editText({ ...t, citations: t.citations ?? [] }, { name: e.target.value })) })} />
          </Item>))}</ul>
      </section>

      <section><h3>Definitions</h3>
        <ul className="plain-list">{(draft.definitions ?? []).map((d, i) => (
          <Item key={i} label={`definition ${d.term}`} citations={d.citations ?? []} onRemove={() => edit({ ...draft, definitions: removeAt(draft.definitions ?? [], i) })}>
            <input aria-label={`Term ${i + 1}`} value={d.term} onChange={(e) => edit({ ...draft, definitions: replaceAt(draft.definitions ?? [], i, editText({ ...d, citations: d.citations ?? [] }, { term: e.target.value })) })} />
            <textarea aria-label={`Definition ${i + 1}`} value={d.text} onChange={(e) => edit({ ...draft, definitions: replaceAt(draft.definitions ?? [], i, editText({ ...d, citations: d.citations ?? [] }, { text: e.target.value })) })} />
          </Item>))}</ul>
      </section>

      <section><h3>Activities</h3>
        <ul className="plain-list">{draft.activities.map((a, i) => (
          <ActivityBlock key={a.activity_id ?? i} a={a} onChange={(n) => edit({ ...draft, activities: replaceAt(draft.activities, i, n) })} onRemove={() => edit({ ...draft, activities: removeAt(draft.activities, i) })} />))}</ul>
      </section>

      <section><h3>Thresholds</h3>
        <p className="muted">Not used for activity matching.</p>
        <ul className="plain-list">{(draft.thresholds ?? []).map((t, i) => (
          <Item key={i} label={`threshold ${i + 1}`} citations={t.citations ?? []} onRemove={() => edit({ ...draft, thresholds: removeAt(draft.thresholds ?? [], i) })}>
            <textarea aria-label={`Threshold ${i + 1}`} value={t.text} onChange={(e) => edit({ ...draft, thresholds: replaceAt(draft.thresholds ?? [], i, editText({ ...t, citations: t.citations ?? [] }, { text: e.target.value })) })} />
          </Item>))}</ul>
      </section>

      <section><h3>Checklist report</h3>
        <div style={{ overflowX: "auto" }}><table>
          <thead><tr><th>Source</th>{CHECKLIST_KEYS.map((k) => <th key={k}>{k}</th>)}</tr></thead>
          <tbody>{sources.map((s) => (
            <tr key={s}><td>{s}</td>{CHECKLIST_KEYS.map((k) => <td key={k}>{FOUND(draft.checklist_report?.[s]?.[k])}</td>)}</tr>))}</tbody>
        </table></div>
      </section>

      <section><h3>Notes</h3><p className="muted">{run.notes || "None"}</p></section>
    </div>
  );
}
