import { useState } from "react";
import { api } from "../api/client";
import { usePortfolioPane } from "../context/usePortfolioPane";
import { PortfolioFilterPicker } from "./PortfolioFilterPicker";
import { DateSelector } from "./DateSelector";
import type { DemoSeedSummary } from "../types";
import { Button, StateBlock } from "../ui";

/** The persistent portfolio/group + as-of-date selector (spec §9): not a
 * sub-tab itself, rendered once above the sub-nav, and read by every
 * sub-tab via `usePortfolioPane()` -- switching sub-tabs never resets it. */
export function PersistentSelectionPane() {
  const { portfolios, refreshPortfolios, loadError, selectedPortfolioIds, setSelectedPortfolioIds, groups, saveCurrentAsGroup, loadGroup, deleteGroup } =
    usePortfolioPane();
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
      {/* The pane loads what every sub-tab reads, so its failure belongs
          here rather than repeated on each of them. */}
      {loadError && <StateBlock kind="error" message={loadError} onRetry={refreshPortfolios} />}
      {portfolios.length === 0 ? (
        <>
          <p className="help-text">No portfolios yet. Seed the built-in illustrative demo dataset to get started.</p>
          <Button onClick={seedDemo} disabled={seeding}>
            {seeding ? "Seeding..." : "Seed demo dataset"}
          </Button>
          {seedError && <StateBlock kind="error" message={seedError} />}
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
              <input type="text" placeholder="Group name" value={groupName} onChange={(e) => setGroupName(e.target.value)} />
              <Button
                onClick={() => {
                  saveCurrentAsGroup(groupName);
                  setGroupName("");
                }}
                disabled={!groupName.trim()}
              >
                Save selection as group
              </Button>
            </div>
            {groups.length > 0 && (
              <p className="muted">
                Saved groups:{" "}
                {groups.map((g) => (
                  <span key={g.name}>
                    {g.name}{" "}
                    <Button variant="ghost" onClick={() => deleteGroup(g.name)}>
                      remove
                    </Button>{" "}
                  </span>
                ))}
              </p>
            )}
          </div>
          <DateSelector />
        </div>
      )}
    </section>
  );
}
