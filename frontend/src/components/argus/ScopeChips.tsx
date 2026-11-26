import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { errorDetail } from "../../lib/barrier";
import type { DeskCompanies, DeskScopeItem } from "../../types";

/** `Asking about` and one chip per scope item, each with a remove ×, plus `+ Saved company` to search and add one. */
export function ScopeChips({ scope, onChange }: { scope: DeskScopeItem[]; onChange: (scope: DeskScopeItem[]) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<DeskCompanies["items"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0); // only the newest search's answer is shown

  useEffect(() => {
    if (!open) return;
    const n = ++latest.current;
    api.listDeskCompanies(q).then(
      (r) => { if (n === latest.current) { setHits(r.items); setError(null); } },
      (err) => { if (n === latest.current) setError(errorDetail(err as Error)); },
    );
  }, [open, q]);

  return (
    <div className="desk-scope">
      <span className="muted">Asking about</span>
      {scope.map((s) => (
        <span key={`${s.kind}:${s.ref}`} className="desk-chip">
          {s.label}
          <button type="button" className="desk-chip-x" aria-label={`Remove ${s.label}`} onClick={() => onChange(scope.filter((x) => x !== s))}>×</button>
        </span>
      ))}
      <button type="button" className="secondary desk-add" aria-expanded={open} onClick={() => setOpen(!open)}>+ Saved company</button>
      {open && (
        <div className="desk-search">
          <input type="search" aria-label="Find a saved company" placeholder="Find a saved company" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
          {error && <p className="error-text" role="alert">{error}</p>}
          {hits && hits.length === 0 && <p className="muted">No saved company matches.</p>}
          <ul>
            {hits?.filter((c) => !scope.some((s) => s.kind === "company" && s.ref === c.company_id)).map((c) => (
              <li key={c.company_id}>
                <button type="button" className="link-button" onClick={() => { onChange([...scope, { kind: "company", ref: c.company_id, label: c.name }]); setOpen(false); setQ(""); }}>
                  {c.name}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
