import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { OutputItem, OutputKind } from "../types";

const KINDS: { id: OutputKind | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "universe", label: "Universes" },
  { id: "run", label: "Runs" },
  { id: "publication", label: "Published scores" },
  { id: "taxonomy", label: "Taxonomies" },
  { id: "calibration", label: "Index calibrations" },
];
const KIND_LABEL: Record<OutputKind, string> = {
  universe: "Universe", run: "Run", publication: "Published scores", taxonomy: "Taxonomy", calibration: "Index calibration",
};
const DRAFTY = new Set(["draft", "failed", "cancelled", "pending", "running"]);
const SHOWN = 200;

/** Where an output (or a consumer of it) is opened. */
function href(kind: string, id: string, runType?: string): string | null {
  if (kind === "run") return runType === "proxy_voting" ? `#/voting/${encodeURIComponent(id)}` : "#/history";
  if (kind === "publication" || kind === "dataset") return "#/decision";
  if (kind === "taxonomy") return "#/taxonomy";
  if (kind === "calibration" || kind === "index_review") return "#/index";
  if (kind === "report") return "#/reporting";
  return null;
}

/** Data Hub · Outputs: everything one step produced that another can use, with who made it, its status and what
 * already uses it. Read from the stores; nothing here is copied or kept separately. */
export function Outputs() {
  const [items, setItems] = useState<OutputItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<(typeof KINDS)[number]["id"]>("all");

  useEffect(() => {
    api.listOutputs().then((r) => setItems(r.outputs), (e: Error) => setError(e.message));
  }, []);

  const shown = (items ?? []).filter((o) => kind === "all" || o.kind === kind);
  const count = (id: (typeof KINDS)[number]["id"]) => (items ?? []).filter((o) => id === "all" || o.kind === id).length;

  return (
    <div className="page">
      <h1>Outputs</h1>
      <p className="help-text">
        Every stored result one step produces and another can use: saved universes, runs, published scores, taxonomies
        and index calibrations, newest first. &ldquo;Used by&rdquo; lists what has already read each one, so you can see
        what a change would affect. Drafts and unfinished runs are marked.
      </p>
      {error && <p className="error-text" role="alert">Outputs could not be loaded: {error}</p>}

      <div className="sub-nav workflow-tabs" role="tablist" aria-label="Output kind">
        {KINDS.map((k) => (
          <button key={k.id} className={k.id === kind ? "nav-tab active" : "nav-tab"} role="tab" aria-selected={k.id === kind} onClick={() => setKind(k.id)}>
            {k.label} {items && `(${count(k.id)})`}
          </button>
        ))}
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>Output</th><th>Kind</th><th>Date</th><th>Status</th><th>By</th><th>Used by</th></tr>
          </thead>
          <tbody>
            {!items && !error && <tr><td colSpan={6} className="muted">Loading…</td></tr>}
            {items && shown.length === 0 && <tr><td colSpan={6} className="muted">Nothing stored here yet.</td></tr>}
            {shown.slice(0, SHOWN).map((o) => {
              const link = href(o.kind, o.id, o.run_type);
              return (
                <tr key={`${o.kind}/${o.id}`}>
                  <td>{link ? <a href={link}>{o.name}</a> : o.name}{o.version != null && <span className="muted"> v{o.version}</span>}</td>
                  <td>{KIND_LABEL[o.kind]}</td>
                  <td>{o.as_of ? o.as_of.slice(0, 10) : "—"}</td>
                  <td><span className={DRAFTY.has(o.status) ? "badge badge-mid" : "badge badge-neutral"}>{o.status.replace(/_/g, " ")}</span></td>
                  <td>{o.by ?? "—"}</td>
                  <td>
                    {o.used_by.length === 0 ? (
                      <span className="muted">Nothing yet</span>
                    ) : (
                      <details>
                        <summary>{o.used_by.length} {o.used_by.length === 1 ? "use" : "uses"}</summary>
                        <ul>
                          {o.used_by.map((c) => {
                            const to = href(c.kind, c.id);
                            return <li key={`${c.kind}/${c.id}`}>{to ? <a href={to}>{c.label}</a> : c.label}{c.version != null && ` (v${c.version})`}</li>;
                          })}
                        </ul>
                      </details>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {shown.length > SHOWN && <p className="muted">Showing the newest {SHOWN} of {shown.length}.</p>}
    </div>
  );
}
