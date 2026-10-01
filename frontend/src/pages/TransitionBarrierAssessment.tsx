import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import type {
  BarrierCriterionDetail,
  BarrierMatrix,
  BarrierMatrixCell,
  BarrierPillar,
  BarrierRating,
  BarrierRefreshCoverage,
  BarrierStalenessReport,
} from "../types";

const PILLARS: BarrierPillar[] = ["Technology", "Regulation", "Demand & Economics"];

// H means transition is MORE feasible (fewer barriers), so H maps to the
// positive colour. Reuses the app's existing badge vocabulary rather than
// introducing a second colour scale.
const RATING_CLASS: Record<BarrierRating, string> = {
  H: "badge badge-high",
  M: "badge badge-mid",
  L: "badge badge-low",
};

const RATING_LABEL: Record<BarrierRating, string> = {
  H: "High feasibility",
  M: "Moderate",
  L: "Low feasibility",
};

function RatingCell({ cell, onClick }: { cell: BarrierMatrixCell | undefined; onClick: () => void }) {
  if (!cell) return <td className="muted">--</td>;
  return (
    <td>
      <button
        type="button"
        className="link-button"
        onClick={onClick}
        title={`${RATING_LABEL[cell.rating]} — confidence ${cell.confidence}${cell.stale ? " — STALE" : ""}`}
      >
        <span className={RATING_CLASS[cell.rating]}>{cell.rating}</span>
        {cell.stale && <span className="badge badge-neutral" title={`Last verified ${cell.last_verified}`}>stale</span>}
      </button>
    </td>
  );
}

function CriterionDetail({ detail, onClose }: { detail: BarrierCriterionDetail; onClose: () => void }) {
  const { criterion, scores, sources } = detail;
  return (
    <div className="card">
      <div className="section-heading">
        <h2>
          {criterion.code} — {criterion.criterion}
        </h2>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
      <p className="muted">
        {criterion.sector} / {criterion.category}
      </p>

      <h3>What is measured</h3>
      <p>{criterion.metric}</p>
      <p className="muted">Unit: {criterion.unit}</p>

      <h3>Rating rubric</h3>
      <div className="table-wrap">
        <table className="data-table">
          <tbody>
            {(["H", "M", "L"] as BarrierRating[]).map((r) => (
              <tr key={r}>
                <td>
                  <span className={RATING_CLASS[r]}>{r}</span>
                </td>
                <td>{criterion.rating_rubric[r]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Ratings by region</h3>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Region</th>
              <th>Rating</th>
              <th>Confidence</th>
              <th>Evidence</th>
              <th>Last verified</th>
            </tr>
          </thead>
          <tbody>
            {scores.map((s) => (
              <tr key={s.region}>
                <td>{s.region}</td>
                <td>
                  <span className={RATING_CLASS[s.rating]}>{s.rating}</span>
                </td>
                <td>{s.confidence}</td>
                <td>{s.evidence}</td>
                <td>{s.last_verified}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Sources ({sources.length})</h3>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Publisher</th>
              <th>Access pattern</th>
              <th>Refresh cadence</th>
              <th>Where to look</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.key}>
                <td>
                  {s.url ? (
                    <a href={s.url} target="_blank" rel="noreferrer">
                      {s.source_name}
                    </a>
                  ) : (
                    s.source_name
                  )}
                </td>
                <td>{s.publisher}</td>
                <td>{s.access_pattern}</td>
                <td>{s.refresh_cadence}</td>
                <td>{s.locator}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function TransitionBarrierAssessment() {
  const [matrix, setMatrix] = useState<BarrierMatrix | null>(null);
  const [staleness, setStaleness] = useState<BarrierStalenessReport | null>(null);
  const [coverage, setCoverage] = useState<BarrierRefreshCoverage | null>(null);
  const [pillar, setPillar] = useState<BarrierPillar | "all">("all");
  const [detail, setDetail] = useState<BarrierCriterionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshRunId, setRefreshRunId] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.getBarrierMatrix(), api.getBarrierStaleness(), api.getBarrierRefreshCoverage()])
      .then(([m, s, c]) => {
        setMatrix(m);
        setStaleness(s);
        setCoverage(c);
      })
      .catch((e) => setError(String(e)));
  }, []);

  const visibleCriteria = useMemo(() => {
    if (!matrix) return [];
    return pillar === "all" ? matrix.criteria : matrix.criteria.filter((c) => c.category === pillar);
  }, [matrix, pillar]);

  async function openCriterion(code: string) {
    try {
      setDetail(await api.getBarrierCriterionDetail(code));
    } catch (e) {
      setError(String(e));
    }
  }

  async function startRefresh() {
    setRefreshError(null);
    try {
      const { run_id } = await api.startBarrierRefreshRun();
      setRefreshRunId(run_id);
    } catch (e) {
      // 409 when ARP_TRANSITION_BARRIER_REFRESH_ENABLED is off -- the common case.
      setRefreshError(String(e));
    }
  }

  if (error) return <p className="error-text" role="alert">{error}</p>;
  if (!matrix) return <p className="muted">Loading the transition barrier matrix...</p>;

  const dist = matrix.distribution.overall;

  return (
    <div className="page">
      <h1>Transition Barriers</h1>
      <p className="muted">
        How feasible decarbonisation is for {matrix.sectors.length} hard-to-abate sectors across{" "}
        {matrix.regions.length} regions — {matrix.criteria.length} criteria x {matrix.regions.length} regions ={" "}
        {matrix.criteria.length * matrix.regions.length} rated cells. <strong>H means transition is more feasible</strong>{" "}
        (fewer barriers), not that the barrier is high.
      </p>

      <div className="stat-tile-grid">
        <div className="stat-tile">
          <span className="stat-value">{dist.H}</span>
          <span className="stat-label">High feasibility</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{dist.M}</span>
          <span className="stat-label">Moderate</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{dist.L}</span>
          <span className="stat-label">Low feasibility</span>
        </div>
        {staleness && (
          <div className="stat-tile">
            <span className="stat-value">{staleness.stale}</span>
            <span className="stat-label">Stale (over {staleness.threshold_days} days)</span>
          </div>
        )}
      </div>

      <div className="card">
        <h2>Ratings by region</h2>
        {/* One H/M/L bar per region in the matrix's own traffic-light colours,
            drawn in HTML so labels stay body-sized at any width. */}
        <ul className="tb-dist">
          {matrix.regions.map((region) => {
            const d = matrix.distribution[region] ?? {};
            const parts = (["H", "M", "L"] as BarrierRating[]).map((r) => ({ r, n: d[r] ?? 0 }));
            return (
              <li key={region}>
                <span className="tb-dist-region">{region}</span>
                <span className="tb-dist-bar" aria-label={`${region}: ${parts.map((p) => `${p.n} ${p.r}`).join(", ")}`}>
                  {parts
                    .filter((p) => p.n > 0)
                    .map((p) => (
                      <span key={p.r} className={`tb-dist-seg ${RATING_CLASS[p.r].split(" ")[1]}`} style={{ flexGrow: p.n }} aria-hidden>
                        {p.r} {p.n}
                      </span>
                    ))}
                </span>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="section-heading">
        <h2>The matrix</h2>
        <div>
          <label htmlFor="pillar-filter">Pillar: </label>
          <select
            id="pillar-filter"
            value={pillar}
            onChange={(e) => setPillar(e.target.value as BarrierPillar | "all")}
          >
            <option value="all">All pillars</option>
            {PILLARS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="table-wrap">
        <table className="data-table tb-matrix">
          <thead>
            <tr>
              <th>Code</th>
              {matrix.regions.map((r) => (
                <th key={r}>{r}</th>
              ))}
              <th>Criterion</th>
              <th>Sector</th>
              <th>Pillar</th>
            </tr>
          </thead>
          <tbody>
            {visibleCriteria.map((c) => (
              <tr key={c.code}>
                <td>
                  <button type="button" className="link-button" onClick={() => openCriterion(c.code)}>
                    {c.code}
                  </button>
                </td>
                {matrix.regions.map((r) => (
                  <RatingCell key={r} cell={matrix.cells[c.code]?.[r]} onClick={() => openCriterion(c.code)} />
                ))}
                <td>{c.criterion}</td>
                <td>{c.sector}</td>
                <td>{c.category}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail && <CriterionDetail detail={detail} onClose={() => setDetail(null)} />}

      <div className="card">
        <div className="section-heading">
          <h2>Source refresh</h2>
          <button type="button" onClick={startRefresh}>
            Re-check legal sources
          </button>
        </div>
        {coverage && (
          <p className="muted">
            {coverage.automatable} of {coverage.total_sources} sources can be re-checked automatically (
            {coverage.enabled_patterns.join(", ")}). The remaining {coverage.manual} still require manual verification.
          </p>
        )}
        <p className="muted">
          A refresh never rewrites a rating. Anything that looks like a rating change is queued for human review; only
          evidence text and the last-verified date may ever be refreshed automatically.
        </p>
        {refreshError && <p className="error-text" role="alert">{refreshError}</p>}
        {refreshRunId && <RunProgress runId={refreshRunId} runType="transition_barrier_refresh" />}
      </div>
    </div>
  );
}
