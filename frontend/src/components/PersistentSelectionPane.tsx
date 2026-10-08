import { useState } from "react";
import { api } from "../api/client";
import { usePortfolioPane } from "../context/usePortfolioPane";
import { PortfolioFilterPicker } from "./PortfolioFilterPicker";
import { DateSelector } from "./DateSelector";
import type { DemoSeedSummary } from "../types";

/** The persistent portfolio/group + as-of-date selector (spec §9): not a
 * sub-tab itself, rendered once above the sub-nav, and read by every
 * sub-tab via `usePortfolioPane()` -- switching sub-tabs never resets it. */
type Destination = "transitionPlan" | "extraction" | "discovery";
const DESTINATIONS: { id: Destination; label: string }[] = [
  { id: "transitionPlan", label: "Transition Plan" },
  { id: "extraction", label: "Extraction" },
  { id: "discovery", label: "Document Discovery" },
];

export function PersistentSelectionPane({ onSendUniverse }: { onSendUniverse?: (to: Destination, path: string, count: number) => void }) {
  const {
    portfolios, refreshPortfolios, portfoliosError, selectedPortfolioIds, setSelectedPortfolioIds, groups, saveCurrentAsGroup, loadGroup, deleteGroup,
    effectiveAsOf, selectionLabel,
  } = usePortfolioPane();
  const [sendError, setSendError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  // The held companies, saved as a universe and handed to the chosen screen.
  async function sendHoldings(to: Destination) {
    setSending(true);
    setSendError(null);
    try {
      const u = await api.holdingsUniverse({ portfolio_ids: selectedPortfolioIds, as_of: effectiveAsOf });
      onSendUniverse?.(to, u.path, u.company_count);
    } catch (e) {
      setSendError((e as Error).message);
      setSending(false);
    }
  }
  const [groupName, setGroupName] = useState("");
  const [seeding, setSeeding] = useState(false);
  const [seedSummary, setSeedSummary] = useState<DemoSeedSummary | null>(null);
  const [seedError, setSeedError] = useState<string | null>(null);

  async function seedDemo() {
    setSeeding(true);
    setSeedError(null);
    try {
      setSeedSummary(await api.seedPortfolioDemo());
      await refreshPortfolios();
    } catch (e) {
      setSeedError(String(e));
    } finally {
      setSeeding(false);
    }
  }

  return (
    <section className="card selection-pane">
      {portfoliosError && portfolios.length === 0 ? (
        <div role="alert">
          <p className="error-text" role="alert">Portfolios could not be loaded ({portfoliosError}). The backend may be unreachable.</p>
          <button onClick={refreshPortfolios}>Retry</button>
        </div>
      ) : portfolios.length === 0 ? (
        <>
          <p className="help-text">No portfolios yet. Seed the built-in illustrative demo dataset to get started.</p>
          <button onClick={seedDemo} disabled={seeding}>
            {seeding ? "Seeding..." : "Seed demo dataset"}
          </button>
          {seedError && <p className="error-text" role="alert">{seedError}</p>}
          {seedSummary && (
            <p className="status-text">
              Seeded {seedSummary.company_count} companies, {seedSummary.portfolio_count} portfolios,{" "}
              {seedSummary.holding_rows} holding rows.
            </p>
          )}
        </>
      ) : (
        <div className="pane-grid">
          <div>
            <PortfolioFilterPicker portfolios={portfolios} selected={selectedPortfolioIds} onChange={setSelectedPortfolioIds} />
            <div className="toolbar">
              <select
                value=""
                onChange={(e) => {
                  if (e.target.value) loadGroup(e.target.value);
                }}
              >
                <option value="">Load a saved group...</option>
                {groups.map((g) => (
                  <option key={g.name} value={g.name}>
                    {g.name} ({g.portfolioIds.length || "all"})
                  </option>
                ))}
              </select>
              <input type="text" aria-label="Group name" placeholder="Group name" value={groupName} onChange={(e) => setGroupName(e.target.value)} />
              <button
                onClick={() => {
                  saveCurrentAsGroup(groupName);
                  setGroupName("");
                }}
                disabled={!groupName.trim()}
              >
                Save selection as group
              </button>
            </div>
            {groups.length > 0 && (
              <p className="muted">
                Saved groups:{" "}
                {groups.map((g) => (
                  <span key={g.name}>
                    {g.name}{" "}
                    <button className="link-button" onClick={() => deleteGroup(g.name)}>
                      remove
                    </button>{" "}
                  </span>
                ))}
              </p>
            )}
          </div>
          <DateSelector />
          {onSendUniverse && (
            <div className="toolbar" style={{ gridColumn: "1 / -1" }}>
              <span className="muted">Use the companies held in {selectionLabel || "this selection"} in:</span>
              {DESTINATIONS.map((d) => (
                <button key={d.id} className="secondary" disabled={sending} onClick={() => sendHoldings(d.id)}>
                  {d.label} &rarr;
                </button>
              ))}
              {sendError && <span className="error-text" role="alert">{sendError}</span>}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
