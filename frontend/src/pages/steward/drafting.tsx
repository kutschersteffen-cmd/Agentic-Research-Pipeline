import { Fragment, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { BlocklistEntry, EngagementRecord, InteractionType, OutreachDecisionItem, OutreachDraft, StyleFlag } from "../../types";
import { ActorField, DataTable, Section, StudioHeader, VersionsPanel, useActor, usePolicy, words } from "./common";
import type { StudioProps } from "./studios";

const TAGS: InteractionType[] = ["informational", "advocacy_pressure", "other"];
const TYPES = ["letter", "email", "call", "meeting"];
const CATEGORIES = ["overclaiming", "unsupported_claim", "regulated_term", "legal_risk", "other"];

/** The text with every flagged phrase marked; the text itself is never changed. */
export function FlaggedText({ text, flags }: { text: string; flags: StyleFlag[] }) {
  const parts: React.ReactNode[] = [];
  let at = 0;
  flags.forEach((f, i) => {
    if (f.start < at) return; // overlapping match: the first one is already marked
    parts.push(<Fragment key={`t${i}`}>{text.slice(at, f.start)}</Fragment>);
    parts.push(
      <mark key={`m${i}`} className="style-flag" title={`${words(f.category)}: ${f.suggestion}`}>
        {text.slice(f.start, f.end)}
      </mark>,
    );
    at = f.end;
  });
  parts.push(<Fragment key="rest">{text.slice(at)}</Fragment>);
  return <p className="draft-text">{parts}</p>;
}

function FlagList({ flags }: { flags: StyleFlag[] }) {
  if (flags.length === 0) return <p className="muted">No style flags.</p>;
  return (
    <ul className="planned-list">
      {flags.map((f, i) => (
        <li key={i}>
          <strong>{f.match}</strong> (line {f.line}, {words(f.category)}): {f.suggestion}
        </li>
      ))}
    </ul>
  );
}

/** Stage 5: approve outreach before it is sent. A second person approves; open style flags need a note. */
export function OutreachDecisions({ items, actor, onDone }: { items: OutreachDecisionItem[]; actor: string; onDone: () => void }) {
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function run(id: string, fn: () => Promise<unknown>) {
    setBusy(id);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  return (
    <>
      {error && <p className="error-text">{error}</p>}
      {items.map((d) => {
        const author = d.authors.some((a) => a.trim().toLowerCase() === actor.trim().toLowerCase());
        return (
          <article key={d.draft_id} className="card position-card">
            <div className="section-heading">
              <h4>
                {d.company} · {words(d.theme)} · {d.type}
              </h4>
              <span className={`chip${d.interaction_type === "advocacy_pressure" ? " chip-warn" : ""}`}>{words(d.interaction_type)}</span>
            </div>
            <FlaggedText text={d.text} flags={d.style_flags} />
            <FlagList flags={d.style_flags} />
            <p className="muted">
              Proposed tag: {words(d.proposed_interaction_type)} ({d.proposed_because}). Written by {d.authors.join(", ")}.
            </p>
            <div className="inline-fields decision-controls">
              <label className="field-label">
                Interaction type
                <select
                  value={d.interaction_type}
                  disabled={!actor || busy !== null}
                  onChange={(e) =>
                    run(d.draft_id, () => api.updateDraft(d.draft_id, { updated_by: actor, interaction_type: e.target.value as InteractionType }))
                  }
                >
                  {TAGS.map((t) => (
                    <option key={t} value={t}>
                      {words(t)}
                    </option>
                  ))}
                </select>
              </label>
              <input
                aria-label="Approval note"
                placeholder={d.style_flags.length ? "Why the flagged phrases stay (required)" : "Note (optional)"}
                value={notes[d.draft_id] ?? ""}
                onChange={(e) => setNotes({ ...notes, [d.draft_id]: e.target.value })}
              />
              <button
                onClick={() => run(d.draft_id, () => api.approveDraft(d.draft_id, { approved_by: actor, note: notes[d.draft_id] ?? "" }))}
                disabled={!actor || author || busy !== null || (d.style_flags.length > 0 && !(notes[d.draft_id] ?? "").trim())}
                title={
                  !actor
                    ? "Enter your name above first"
                    : author
                      ? "Four-eyes: someone who did not write it approves"
                      : d.style_flags.length && !(notes[d.draft_id] ?? "").trim()
                        ? "Rewrite on the drafting tab, or give a note"
                        : undefined
                }
              >
                {busy === d.draft_id ? "Approving…" : "Approve for sending"}
              </button>
            </div>
          </article>
        );
      })}
    </>
  );
}

function Compose({ actor, onCreated }: { actor: string; onCreated: () => void }) {
  const [records, setRecords] = useState<EngagementRecord[]>([]);
  const [target, setTarget] = useState("");
  const [type, setType] = useState("letter");
  const [text, setText] = useState("");
  const [flags, setFlags] = useState<StyleFlag[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.listEngagementRecords().then(
      (r) => setRecords(r.records as EngagementRecord[]),
      (e) => setError((e as Error).message),
    );
  }, []);
  useEffect(() => {
    if (!text.trim()) {
      setFlags([]);
      return;
    }
    const timer = setTimeout(() => api.checkStyle(text).then((r) => setFlags(r.flags), () => undefined), 400);
    return () => clearTimeout(timer);
  }, [text]);
  const options = records.flatMap((r) =>
    r.issues.filter((i) => i.status === "open" || i.status === "stalled").map((i) => ({ value: `${r.company_id}|${i.issue_id}`, label: `${r.name} · ${words(i.theme)}` })),
  );
  async function create() {
    const [company_id, issue_id] = target.split("|");
    setBusy(true);
    setError(null);
    try {
      await api.createDraft({ company_id, issue_id, type, text, created_by: actor });
      setText("");
      onCreated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (options.length === 0) return <p className="muted">No open engagement yet: open one from a trigger (stage 1) or on the Engagement page.</p>;
  return (
    <>
      <div className="inline-fields">
        <label className="field-label">
          Engagement
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Choose…</option>
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field-label">
          Type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
      </div>
      <label className="field-label">
        Text (paste a draft from the Engagement page, or write it here)
        <textarea rows={7} value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      {text.trim() && (
        <>
          <p className="studio-step">Style check (E8), as you type</p>
          <FlagList flags={flags} />
        </>
      )}
      <div className="toolbar">
        <button onClick={create} disabled={!actor || !target || !text.trim() || busy} title={actor ? undefined : "Enter your name above first"}>
          {busy ? "Saving…" : "Save draft for approval"}
        </button>
        <span className="muted">The interaction type is proposed on save; the checkpoint can change it.</span>
      </div>
      {error && <p className="error-text">{error}</p>}
    </>
  );
}

function BlocklistEditor({ actor, onActivated }: { actor: string; onActivated: () => void }) {
  const { info, error, reload } = usePolicy("phrase_blocklist");
  const [list, setList] = useState<{ note?: string; phrases: BlocklistEntry[] } | null>(null);
  useEffect(() => {
    if (info && list === null) setList(info.active as { phrases: BlocklistEntry[] });
  }, [info, list]);
  if (!info || !list) return <p className="status-text">{error ?? "Loading…"}</p>;
  const dirty = JSON.stringify(list) !== JSON.stringify(info.active);
  const setEntry = (i: number, patch: Partial<BlocklistEntry>) =>
    setList({ ...list, phrases: list.phrases.map((p, j) => (j === i ? { ...p, ...patch } : p)) });
  return (
    <>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Phrase</th>
              <th>Category</th>
              <th>Suggestion</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.phrases.map((p, i) => (
              <tr key={i}>
                <td>
                  <input aria-label="Phrase" value={p.phrase} onChange={(e) => setEntry(i, { phrase: e.target.value })} />
                </td>
                <td>
                  <select aria-label="Category" value={p.category} onChange={(e) => setEntry(i, { category: e.target.value })}>
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {words(c)}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input aria-label="Suggestion" value={p.suggestion ?? ""} onChange={(e) => setEntry(i, { suggestion: e.target.value })} />
                </td>
                <td>
                  <button className="link-button" onClick={() => setList({ ...list, phrases: list.phrases.filter((_, j) => j !== i) })}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="toolbar">
        <button className="secondary" onClick={() => setList({ ...list, phrases: [...list.phrases, { phrase: "", category: "other", suggestion: "" }] })}>
          Add a phrase
        </button>
      </div>
      <VersionsPanel
        policyId="phrase_blocklist"
        info={info}
        workingCopy={list}
        dirty={dirty}
        actor={actor}
        onSaved={reload}
        onLoad={async (v) => setList((await api.getStewardPolicyVersion("phrase_blocklist", v)) as { phrases: BlocklistEntry[] })}
        onActivated={() => {
          reload();
          onActivated();
        }}
      />
    </>
  );
}

export function DraftingStudio({ stage, onChanged, onOpen }: StudioProps) {
  const [actor] = useActor();
  const [drafts, setDrafts] = useState<OutreachDraft[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => api.listDrafts().then((r) => setDrafts(r.drafts), (e) => setError((e as Error).message));
  useEffect(() => {
    load();
  }, [stage]);
  const refresh = () => {
    load();
    onChanged();
  };
  async function sent(d: OutreachDraft) {
    setError(null);
    try {
      await api.markDraftSent(d.draft_id, actor);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <>
      <StudioHeader
        stage={stage}
        capabilities={[
          { label: "Review", ready: true },
          { label: "Design", ready: true },
          { label: "Versions", ready: true },
        ]}
      >
        <p className="muted">
          Letters, talking points and meeting summaries are drafted with grounded citations on the <strong>Engagement</strong> page. Here
          each outreach gets its interaction type (E6) and the style check (E8), and waits for approval at stage 5 before it is sent.
        </p>
      </StudioHeader>
      <ActorField />
      <Section step="Construct" title="New outreach draft">
        <Compose actor={actor} onCreated={refresh} />
      </Section>
      <Section step="Review" title="Outreach drafts">
        {error && <p className="error-text">{error}</p>}
        {drafts === null ? (
          <p className="status-text">Loading…</p>
        ) : drafts.length === 0 ? (
          <p className="muted">No drafts yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Type</th>
                  <th>Interaction</th>
                  <th>Style flags</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {[...drafts].reverse().map((d) => (
                  <tr key={d.draft_id}>
                    <td>
                      {d.company} · {words(d.theme)}
                    </td>
                    <td>{d.type}</td>
                    <td>{words(d.interaction_type)}</td>
                    <td>{d.style_flags.length}</td>
                    <td>
                      {d.status === "draft" ? "waiting for approval" : d.status}
                      {d.approved_by ? <span className="muted"> · approved by {d.approved_by}</span> : null}
                    </td>
                    <td>
                      {d.status === "draft" && (
                        <button className="link-button" onClick={() => onOpen("checkpoint")}>
                          Approve at stage 5 →
                        </button>
                      )}
                      {d.status === "approved" && (
                        <button onClick={() => sent(d)} disabled={!actor} title={actor ? undefined : "Enter your name above first"}>
                          Mark as sent
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted">Marking a draft sent logs it on the engagement, with its interaction type.</p>
      </Section>
      <Section step="Design" title="Phrase blocklist (E8)">
        <p className="help-text">
          Phrases flagged in outreach and client-facing text: case-insensitive, whole words. The check flags, a person rewrites; nothing
          is removed automatically.
        </p>
        <BlocklistEditor actor={actor} onActivated={refresh} />
      </Section>
      <Section step="Review" title="Sent outreach by interaction type">
        <DataTable
          rows={TAGS.map((t) => ({ "interaction type": t, sent: (drafts ?? []).filter((d) => d.status === "sent" && d.interaction_type === t).length }))}
        />
      </Section>
    </>
  );
}
