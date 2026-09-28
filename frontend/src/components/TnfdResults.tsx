import { Fragment } from "react";
import { ConfidenceBadge, GroundedBadge } from "./ConfidenceBadge";
import { CitationList } from "./CitationList";
import type { ActiveSource } from "./SourcePanel";
import { ProposedTag } from "./ProposedTag";
import type { TnfdRecord } from "../types";
import { activatable } from "../lib/activatable";

const pretty = (id: string) => id.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

interface Props {
  results: TnfdRecord[];
  expanded: string | null;
  onToggleExpanded: (companyId: string) => void;
  onOpenSource: (s: ActiveSource) => void;
}

/** One row per company: how many of the 14 TNFD recommendations it discloses
 * and how many core global metrics are grounded; expanding shows each
 * recommendation with its summary and citations. */
export function TnfdResultsTable({ results, expanded, onToggleExpanded, onOpenSource }: Props) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Company</th>
            <th>Period</th>
            <th>Recommendations</th>
            <th>Grounded metrics</th>
            <th>Confidence</th>
            <th>Needs review</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => (
            <Fragment key={r.company_id}>
              <tr className="clickable-row" {...activatable(() => onToggleExpanded(r.company_id), expanded === r.company_id)}>
                <td>{r.name} {r.ticker && <span className="muted">({r.ticker})</span>}</td>
                <td>{r.as_of}</td>
                <td>{r.disclosures.filter((d) => d.disclosed).length}/14</td>
                <td>{r.core_global_metrics.filter((m) => m.grounded).length}</td>
                <td><ConfidenceBadge value={r.overall_confidence} /></td>
                <td>{r.needs_review ? <ProposedTag /> : ""}</td>
              </tr>
              {expanded === r.company_id && (
                <tr>
                  <td colSpan={6} className="detail-cell">
                    {r.missing_recommendations.length > 0 && (
                      <p className="muted">Not disclosed: {r.missing_recommendations.map(pretty).join(", ")}</p>
                    )}
                    {r.disclosures.filter((d) => d.disclosed).map((d) => (
                      <div key={d.recommendation_id} className="field-detail">
                        <h4>
                          {pretty(d.recommendation_id)} <GroundedBadge grounded={d.grounded} />
                        </h4>
                        {d.summary && <p>{d.summary}</p>}
                        {d.verifier_notes && <p className="muted">{d.verifier_notes}</p>}
                        <CitationList citations={d.summary_citations} onOpenSource={onOpenSource} />
                      </div>
                    ))}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
