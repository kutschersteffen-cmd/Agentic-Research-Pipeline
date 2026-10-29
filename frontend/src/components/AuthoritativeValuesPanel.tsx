import { useEffect, useState } from "react";
import { api } from "../api/client";
import { derivationLines } from "../lib/derivation";
import type { AuthoritativeValue } from "../types";

type Derived = Parameters<typeof derivationLines>[0];

// The published authoritative values of one calculate-only framework; a cell opens how its value was derived.
export function AuthoritativeValuesPanel({ frameworkId, names }: { frameworkId: string; names: Record<string, string> }) {
  const [values, setValues] = useState<AuthoritativeValue[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<AuthoritativeValue | null>(null);

  useEffect(() => {
    setValues(null);
    setOpen(null);
    api.listAuthoritativeValues(frameworkId).then(setValues, (e: Error) => setError(e.message));
  }, [frameworkId]);

  if (error) return <p className="decision-check-banner" role="alert">{error}</p>;
  if (values === null) return <p className="status-text">Loading authoritative values…</p>;
  if (values.length === 0) return <p className="muted">Nothing published yet. An approver publishes a ratified version.</p>;

  const outputs = [...new Set(values.map((v) => v.output))].sort();
  const companies = [...new Set(values.map((v) => v.company_id))];
  const cell = (company: string, output: string) => values.find((v) => v.company_id === company && v.output === output);
  const lines = open ? derivationLines(open as unknown as Derived) : null;

  return (
    <div className="card">
      <h2>Authoritative values</h2>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              {outputs.map((o) => <th key={o}>{o}</th>)}
            </tr>
          </thead>
          <tbody>
            {companies.map((company) => (
              <tr key={company}>
                <td>{names[company] ?? company}</td>
                {outputs.map((output) => {
                  const v = cell(company, output);
                  return (
                    <td key={output}>
                      {v ? (
                        <button
                          className="link-button authoritative-cell"
                          aria-label={`How ${output} for ${names[company] ?? company} was derived`}
                          onClick={async () => setOpen(await api.getAuthoritativeValue(v.id))}
                        >
                          {v.status === "value" ? String(v.value) : "No value"}
                        </button>
                      ) : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && lines && (
        <section aria-label="Derivation" className="detail-cell derivation-panel">
          <div className="toolbar">
            <h3>{names[open.company_id] ?? open.company_id} · {open.output}: {lines.value}</h3>
            <button className="link-button" onClick={() => setOpen(null)}>Close</button>
          </div>
          <p className="muted">Framework {open.framework_id} v{open.framework_version} · dataset as of {open.dataset_as_of ?? "—"}</p>
          <h4>Inputs</h4>
          {lines.inputs.length ? <ul>{lines.inputs.map((l) => <li key={l}>{l}</li>)}</ul> : <p className="muted">None</p>}
          <h4>Rule</h4>
          {lines.expressions.length ? lines.expressions.map((e) => <pre key={e}>{e}</pre>) : <p className="muted">No rule ran</p>}
        </section>
      )}
    </div>
  );
}
