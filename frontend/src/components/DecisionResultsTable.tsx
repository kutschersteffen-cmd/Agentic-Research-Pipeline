import { Fragment, useState } from "react";
import type { DecisionResult, EntityDecision, MechanismConfig } from "../types";
import { Button } from "../ui";

function tierClass(tier?: number | null): string {
  if (tier === 1) return "badge badge-high";
  if (tier === 2) return "badge badge-mid";
  if (tier === 3) return "badge badge-neutral";
  return "badge badge-low";
}

function StatusCell({ entity }: { entity: EntityDecision }) {
  if (entity.status === "scored") {
    return <span className={tierClass(entity.tier)}>{entity.tier_name ?? `Tier ${entity.tier}`}</span>;
  }
  return <span className={entity.status === "excluded" ? "badge badge-low" : "badge badge-neutral"}>{entity.status}</span>;
}

export function DecisionResultsTable({
  result,
  config,
  orderBy,
  onOrderBy,
  onExplain,
}: {
  result: DecisionResult;
  config: MechanismConfig;
  orderBy: "score" | "leverage";
  onOrderBy: (value: "score" | "leverage") => void;
  onExplain: (entity: EntityDecision) => void;
}) {
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const dimensionNames = new Map(config.dimensions.map((d) => [d.id, d.name]));

  const rows = result.entities
    .filter((e) => e.name.toLowerCase().includes(filter.toLowerCase()))
    .sort((a, b) => {
      if (orderBy === "leverage") {
        if (a.leverage_rank == null) return b.leverage_rank == null ? 0 : 1;
        if (b.leverage_rank == null) return -1;
        return a.leverage_rank - b.leverage_rank;
      }
      if (a.rank == null) return b.rank == null ? a.name.localeCompare(b.name) : 1;
      if (b.rank == null) return -1;
      return a.rank - b.rank;
    });

  return (
    <div>
      <div className="toolbar">
        <input placeholder="Filter by name…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <select value={orderBy} onChange={(e) => onOrderBy(e.target.value as "score" | "leverage")}>
          <option value="score">Order by score</option>
          <option value="leverage">Order by leverage</option>
        </select>
        {orderBy === "leverage" && (
          <span className="help-text">
            Position size × the gap to a perfect score — where engagement moves the most, not who scores worst.
          </span>
        )}
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Name</th>
            <th>Score</th>
            <th>Rank band</th>
            <th>Outcome</th>
            <th>Coverage</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((entity) => (
            <Fragment key={entity.entity_key}>
              <tr
                className="clickable-row"
                onClick={() => setExpanded(expanded === entity.entity_key ? null : entity.entity_key)}
              >
                <td>{orderBy === "leverage" ? entity.leverage_rank ?? "—" : entity.rank ?? "—"}</td>
                <td>
                  <strong>{entity.name}</strong>
                  {entity.cohort && <div className="muted">{entity.cohort}</div>}
                </td>
                <td>{entity.score != null ? entity.score.toFixed(1) : "—"}</td>
                <td className="muted">
                  {entity.rank_min != null && entity.rank_max != null
                    ? entity.rank_min === entity.rank_max
                      ? `${entity.rank_min}`
                      : `${entity.rank_min}–${entity.rank_max}`
                    : "—"}
                </td>
                <td>
                  <StatusCell entity={entity} />
                </td>
                <td>
                  {Math.round(entity.coverage * 100)}%
                  {entity.grounded_coverage != null && (
                    <div className="muted">{Math.round(entity.grounded_coverage * 100)}% grounded</div>
                  )}
                </td>
                <td className="muted">{entity.notes.join("; ")}</td>
              </tr>
              {expanded === entity.entity_key && (
                <tr>
                  <td className="detail-cell" colSpan={7}>
                    <div className="toolbar">
                      <strong>What moved this score</strong>
                      <Button variant="ghost" onClick={() => onExplain(entity)}>
                        How much do the weights matter?
                      </Button>
                    </div>
                    <div className="decision-dims">
                      {Object.entries(entity.dimension_scores).map(([id, value]) => (
                        <span key={id} className="standards-chip">
                          <strong>{dimensionNames.get(id) ?? id}</strong>
                          {value != null ? value.toFixed(0) : "—"}
                        </span>
                      ))}
                    </div>
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Criterion</th>
                          <th>Normalised</th>
                          <th>Weight</th>
                          <th>Contribution</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...entity.contributions]
                          .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
                          .map((contribution) => (
                            <tr key={contribution.column}>
                              <td>
                                {contribution.column}
                                {contribution.imputed && <span className="muted"> (imputed)</span>}
                                {contribution.low_confidence && <span className="muted"> (unverified)</span>}
                              </td>
                              <td>{contribution.normalised != null ? contribution.normalised.toFixed(1) : "absent"}</td>
                              <td>{(contribution.weight * 100).toFixed(1)}%</td>
                              <td>{contribution.contribution >= 0 ? `+${contribution.contribution.toFixed(1)}` : contribution.contribution.toFixed(1)}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
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
