import { ProposedTag } from "../../components/ProposedTag";
import type { CompanyFactRow } from "../../types";
import { STATUS_TEXT } from "./companyQuery";

/** Status cell: only what waits on a person takes the signal. */
export function FactStatus({ status, conflicting }: { status: CompanyFactRow["status"]; conflicting?: boolean }) {
  return (
    <span className="company-status">
      {status === "pending_review" ? <ProposedTag>Awaiting review</ProposedTag> : <span className="status-pill">{STATUS_TEXT[status]}</span>}
      {conflicting && <ProposedTag>Sources conflict</ProposedTag>}
    </span>
  );
}

/** The company's facts, one row per field / period / basis; a field opens its trail. */
export function FactsTable({ rows, selected, onSelect }: { rows: CompanyFactRow[]; selected: number | null; onSelect: (factId: number, opener: HTMLElement) => void }) {
  return (
    <div className="table-wrap">
      <table className="data-table stack-on-phone company-facts">
        <caption className="visually-hidden">Facts; choose a field to see where its value came from</caption>
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">Period</th>
            <th scope="col">Value</th>
            <th scope="col">Status</th>
            <th scope="col">Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.fact_id} className={r.fact_id === selected ? "selected-row" : undefined}>
              <td data-label="Field">
                <span>
                  <button type="button" className="link-button mono" aria-pressed={r.fact_id === selected} onClick={(e) => onSelect(r.fact_id, e.currentTarget)}>
                    {r.field_id}
                  </button>
                  {r.basis && <span className="muted"> {r.basis}</span>}
                </span>
              </td>
              <td data-label="Period" className="mono">{r.period_end ?? "—"}</td>
              <td data-label="Value" className="mono company-value">
                <span>
                  {r.value == null ? "—" : String(r.value)}
                  {r.canonical_value != null && (
                    <span className="muted">
                      {r.canonical_value === Number(r.value) ? ` ${r.canonical_unit ?? ""}` : ` = ${r.canonical_value.toLocaleString()} ${r.canonical_unit ?? ""}`}
                    </span>
                  )}
                </span>
              </td>
              <td data-label="Status"><FactStatus status={r.status} conflicting={r.conflicting_sources} /></td>
              <td data-label="Source">
                <span>
                  {r.source_label}
                  {r.licence === "internal_only" && <span className="muted"> · internal only</span>}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
