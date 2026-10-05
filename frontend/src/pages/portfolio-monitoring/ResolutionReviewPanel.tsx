import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { ConfidenceBadge } from "../../components/ConfidenceBadge";
import { DecisionBar } from "../../components/DecisionBar";
import { SIGN_IN_REQUIRED, useMe } from "../../lib/reviewer";
import type { ResolutionReviewItem } from "../../types";

/** Securities whose issuer match was flagged for review. Accept/reject only log the decision;
 * override also repoints the security to the corrected company_id. Decided items drop off the list. */
export function ResolutionReviewPanel() {
  const [items, setItems] = useState<ResolutionReviewItem[]>([]);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const signedIn = (useMe()?.name ?? "").trim() !== "";

  const load = () => api.listResolutionReview().then(setItems, (e: Error) => setError(e.message));
  useEffect(() => {
    void load();
  }, []);

  async function decide(itemKey: string, decision: "accept" | "override" | "reject") {
    if (!signedIn) return setError(SIGN_IN_REQUIRED);
    const override_value = overrides[itemKey]?.trim();
    if (decision === "override" && !override_value) return setError("Enter the corrected company_id before overriding.");
    setError(null);
    try {
      await api.recordResolutionDecision({ item_key: itemKey, decision, override_value: decision === "override" ? override_value : undefined });
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section>
      <h3>Entity-resolution review ({items.length})</h3>
      {error && <p className="error-text" role="alert">{error}</p>}
      <table className="data-table">
        <thead>
          <tr><th>Security</th><th>Matched company</th><th>Confidence</th><th>Method</th><th>Decision</th></tr>
        </thead>
        <tbody>
          {items.length === 0 && <tr><td colSpan={5} className="muted">Nothing pending review.</td></tr>}
          {items.map((r) => (
            <tr key={r.security_id}>
              <td>{r.security_id}</td>
              <td>{r.company_id ?? "(none)"}</td>
              <td><ConfidenceBadge value={r.confidence} /></td>
              <td>{r.method}</td>
              <td>
                <input
                  aria-label="Corrected company_id, for Override"
                  placeholder="correct company_id"
                  value={overrides[r.security_id] ?? ""}
                  onChange={(e) => setOverrides((prev) => ({ ...prev, [r.security_id]: e.target.value }))}
                />
                <DecisionBar
                  approveLabel="Accept"
                  onApprove={() => void decide(r.security_id, "accept")}
                  onOverride={() => void decide(r.security_id, "override")}
                  onReject={() => void decide(r.security_id, "reject")}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
