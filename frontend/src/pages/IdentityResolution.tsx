import { useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import type { IdentityResolutionResult } from "../types";

interface Props {
  onSendToDiscovery?: (path: string, count: number) => void;
}

export function IdentityResolution({ onSendToDiscovery }: Props = {}) {
  const [universePath, setUniversePath] = useState<string | null>(null);
  const [companyCount, setCompanyCount] = useState(0);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<IdentityResolutionResult[]>([]);
  const [sendBusy, setSendBusy] = useState(false);
  const [sendStatus, setSendStatus] = useState("");
  const [sentUniverse, setSentUniverse] = useState<{ path: string; count: number } | null>(null);

  async function refreshResults() {
    if (!runId) return;
    const res = (await api.getIdentityResults(runId)) as { results: IdentityResolutionResult[] };
    setResults(res.results);
  }

  async function runNow() {
    if (!universePath) return;
    setBusy(true);
    setError(null);
    setResults([]);
    setSentUniverse(null);
    try {
      const res = await api.startIdentityRun({ universe_path: universePath });
      setRunId(res.run_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function sendToDiscovery() {
    if (!runId) return;
    setSendBusy(true);
    setSendStatus("");
    setSentUniverse(null);
    try {
      const enriched = await api.getEnrichedUniverse(runId);
      if (enriched.companies.length === 0) {
        setSendStatus("No resolved (or approved) companies yet -- nothing to send.");
        return;
      }
      const res = await api.universeFromCompanies(enriched.companies, "identity_resolved");
      setSendStatus(`Saved ${res.company_count} companies as a universe.`);
      setSentUniverse({ path: res.path, count: res.company_count });
    } catch (err) {
      setSendStatus(`Failed: ${(err as Error).message}`);
    } finally {
      setSendBusy(false);
    }
  }

  return (
    <div className="page">
      <h2>Company Identity Resolution</h2>
      <p className="help-text">
        Resolves a list of bare company names to a real, verified website/CIK before any document discovery runs --
        a deterministic EDGAR lookup resolves the clean case for free, and only genuine ambiguity escalates to a
        single adjudicating LLM call. Nothing ambiguous is ever guessed: it's queued in the Review Queue tab for a
        human to approve, edit, or reject. This is a one-time cost per company -- run it once, then reuse the
        resulting universe for every future Document Discovery run.
      </p>

      <section className="card">
        <h3>Resolve identity</h3>
        <UniversePicker
          onResolved={(path, count) => {
            setUniversePath(path);
            setCompanyCount(count);
          }}
        />
        <button onClick={runNow} disabled={busy || !universePath}>
          Resolve identity for {companyCount || "..."} companies
        </button>
        {error && <p className="error-text">{error}</p>}
        {runId && <RunProgress runId={runId} runType="identity" />}
        {runId && (
          <>
            <button onClick={refreshResults}>Refresh results</button>
            {results.length > 0 && (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Company</th>
                    <th>Verdict</th>
                    <th>Confidence</th>
                    <th>Resolved website</th>
                    <th>Resolved CIK</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <tr key={r.company_id}>
                      <td>{r.input_name}</td>
                      <td>{r.verdict}</td>
                      <td>{r.confidence.toFixed(2)}</td>
                      <td>{r.resolved_website ?? "-"}</td>
                      <td>{r.resolved_cik ?? "-"}</td>
                      <td>
                        {r.flagged_for_review ? (
                          <span className="error-text" title={r.rationale}>
                            ⚠️ needs review
                          </span>
                        ) : (
                          "ok"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="toolbar">
              <button onClick={sendToDiscovery} disabled={sendBusy}>
                Send resolved companies to Document Discovery
              </button>
              {sentUniverse && (
                <button onClick={() => onSendToDiscovery?.(sentUniverse.path, sentUniverse.count)}>
                  Go to Document Discovery &rarr;
                </button>
              )}
            </div>
            {sendStatus && <p className="status-text">{sendStatus}</p>}
            <p className="muted">
              Anything flagged for review must be approved (or edited with a corrected website/CIK) via the Review
              Queue tab before it's included in the sent universe.
            </p>
          </>
        )}
      </section>
    </div>
  );
}
