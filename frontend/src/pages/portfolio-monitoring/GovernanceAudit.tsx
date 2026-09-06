import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { ConfidenceBadge } from "../../components/ConfidenceBadge";
import type { DataPointObservation, SecurityResolution } from "../../types";

/** Ownership, methodology, and audit trail (spec §5 / §9 sub-tab 7). This
 * is the one sub-tab where the pane's selection is informational context
 * rather than a hard filter -- both lists below are issuer/security-level
 * facts, not portfolio-scoped queries. What's built is flagging, not a
 * full decision/approval workflow: see docs/SPEC_GAP_ANALYSIS.md §5 for
 * what a real accept/reject/ownership record would still need. */
export function GovernanceAudit() {
  const [reviewQueue, setReviewQueue] = useState<SecurityResolution[]>([]);
  const [conflicts, setConflicts] = useState<DataPointObservation[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listSecuritiesNeedingReview(), api.listConflictingObservations()])
      .then(([r, c]) => {
        setReviewQueue(r);
        setConflicts(c);
      })
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <>
      <section className="card">
        <h3>Methodology</h3>
        <p className="help-text">
          Entity-resolution confidence and climate-validation tolerance are configured, versionless settings today
          (<code>ARP_PORTFOLIO_CONFIDENCE_REVIEW_THRESHOLD</code>, <code>ARP_CLIMATE_VALIDATION_TOLERANCE_PCT</code>
          in <code>backend/arp/config.py</code>) -- there is no logged history yet of when either changed, or by
          whom (see <code>docs/SPEC_GAP_ANALYSIS.md</code> §5).
        </p>
      </section>

      {error && <p className="error-text">{error}</p>}

      <section className="card">
        <h3>Entity-resolution review queue ({reviewQueue.length})</h3>
        <p className="help-text">
          Securities whose issuer match fell below the confidence threshold -- never auto-matched, always surfaced
          here instead (see <code>entity_resolution.py</code>).
        </p>
        <table className="data-table">
          <thead>
            <tr>
              <th>Security</th>
              <th>Best-guess issuer</th>
              <th>Confidence</th>
              <th>Method</th>
            </tr>
          </thead>
          <tbody>
            {reviewQueue.map((r) => (
              <tr key={r.security_id}>
                <td>{r.security_id}</td>
                <td>{r.company_id ?? "(none)"}</td>
                <td>
                  <ConfidenceBadge value={r.confidence} />
                </td>
                <td>{r.method}</td>
              </tr>
            ))}
            {reviewQueue.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  Nothing pending review.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h3>Climate data conflicts ({conflicts.length})</h3>
        <p className="help-text">
          Values where the internal ESG API disagreed with an independent extraction from company disclosures beyond
          tolerance. The internal-API value is still the one used for computation, but it's flagged rather than
          silently reconciled (see <code>climate/validation.py</code>).
        </p>
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Field</th>
              <th>Value used</th>
              <th>Conflicting value</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {conflicts.map((c) => (
              <tr key={`${c.company_id}:${c.field_id}`}>
                <td>{c.company_id}</td>
                <td>{c.field_name}</td>
                <td>{String(c.value)}</td>
                <td>{String(c.conflicting_value)}</td>
                <td>{c.conflicting_source_label}</td>
              </tr>
            ))}
            {conflicts.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No conflicts flagged.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}
