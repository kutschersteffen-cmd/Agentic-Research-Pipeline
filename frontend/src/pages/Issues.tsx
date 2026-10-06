import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { DataIssue } from "../types";

const SOURCES: { id: DataIssue["source"] | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "feed", label: "Feeds" },
  { id: "security_master", label: "Security master" },
  { id: "check", label: "Data checks" },
];
const SEVERITY: Record<DataIssue["severity"], [string, string]> = {
  block: ["Blocking", "badge badge-low"],
  warn: ["Warning", "badge badge-mid"],
  info: ["Info", "badge badge-neutral"],
};
const SHOWN = 200;

/** Where an issue is fixed. */
export function fixHref(i: DataIssue): string {
  if (i.source === "feed") return "#/feeds";
  if (i.source === "security_master") return "#/securityMaster";
  return `#/review/extraction/${encodeURIComponent(i.run_id ?? "")}`;
}

/** Data Hub · Issues: every open data problem the tool already knows about. Nothing here is re-run or guessed: feeds
 * behind or failed, held securities the master doesn't map, and failing checks on extracted values not yet decided. */
export function Issues() {
  const [issues, setIssues] = useState<DataIssue[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<(typeof SOURCES)[number]["id"]>("all");

  useEffect(() => {
    api.listIssues().then((r) => setIssues(r.issues), (e: Error) => setError(e.message));
  }, []);

  const count = (id: (typeof SOURCES)[number]["id"]) => (issues ?? []).filter((i) => id === "all" || i.source === id).length;
  const shown = (issues ?? []).filter((i) => source === "all" || i.source === source);

  return (
    <div className="page">
      <h1>Issues</h1>
      <p className="help-text">
        Every open data problem in one list, most serious first: feeds behind or whose last load failed, held securities the
        security master doesn&apos;t map, and failing checks on extracted values no reviewer has decided yet. An issue
        disappears once it is fixed where it lives.
      </p>
      {error && <p className="error-text" role="alert">Issues could not be loaded: {error}</p>}
      {issues && (
        <p role="status">
          {issues.length === 0 ? "No open issues." : `${issues.length} open issues, ${issues.filter((i) => i.severity === "block").length} blocking.`}
        </p>
      )}

      <div className="sub-nav workflow-tabs" role="tablist" aria-label="Issue source">
        {SOURCES.map((s) => (
          <button key={s.id} className={s.id === source ? "nav-tab active" : "nav-tab"} role="tab" aria-selected={s.id === source} onClick={() => setSource(s.id)}>
            {s.label} {issues && `(${count(s.id)})`}
          </button>
        ))}
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>Severity</th><th>Issue</th><th>Detail</th><th /></tr>
          </thead>
          <tbody>
            {!issues && !error && <tr><td colSpan={4} className="muted">Loading…</td></tr>}
            {issues && shown.length === 0 && <tr><td colSpan={4} className="muted">Nothing open here.</td></tr>}
            {shown.slice(0, SHOWN).map((i) => (
              <tr key={i.ref}>
                <td><span className={SEVERITY[i.severity][1]}>{SEVERITY[i.severity][0]}</span></td>
                <td>{i.title}</td>
                <td className="muted">{i.detail}</td>
                <td><a href={fixHref(i)}>{i.source === "check" ? "Review →" : "Fix →"}</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length > SHOWN && <p className="muted">Showing the first {SHOWN} of {shown.length}, most serious first.</p>}
    </div>
  );
}
