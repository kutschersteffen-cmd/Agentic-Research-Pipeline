import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { RATING_CLASS, RATING_LABEL, cellHash, errorDetail } from "../lib/barrier";
import { BarrierCellDetail } from "./BarrierCellDetail";
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
  const [derived, setDerived] = useState<{ runId: string } | { error: string } | null>(null);
  async function deriveAll() {
    setDerived(null);
    try {
      setDerived({ runId: (await api.deriveBarrierCells(scores.map((s) => ({ code: s.code, region: s.region })))).run_id });
    } catch (e) {
      setDerived({ error: errorDetail(e as Error) });
    }
  }
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
        {criterion.rule_book_version != null && <> · <span className="mono">rule book v{criterion.rule_book_version}</span></>}
      </p>

      <h3>Why it matters</h3>
      <p>{criterion.rationale}</p>

      <h3>Actions it limits</h3>
      <ul>
        {criterion.actions.map((a) => (
          <li key={a} className="mono">
            {a}
          </li>
        ))}
      </ul>

      <h3>What is measured</h3>
      <p>{criterion.metric}</p>
      <p className="muted">Unit: {criterion.unit}</p>

      <h3>Facts</h3>
      <div className="table-wrap">
        <table className="data-table">
          <tbody>
            {criterion.facts.map((f) => (
              <tr key={f.id}>
                <td>
                  {f.label} <span className="mono muted">{f.id}</span>
                </td>
                <td>{f.definition}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

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

      <h3>Thresholds</h3>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Threshold</th>
              <th>Value</th>
              <th>Source</th>
              <th>Rationale</th>
            </tr>
          </thead>
          <tbody>
            {criterion.params.map((p) => (
              <tr key={p.id}>
                <td>
                  {p.label} <span className="mono muted">{p.id}</span>
                </td>
                <td className="mono">{p.status === "open" ? "open" : `${p.value}${p.unit ? ` ${p.unit}` : ""}`}</td>
                <td>
                  {p.source ? (
                    <>
                      {p.source.url ? (
                        <a href={p.source.url} target="_blank" rel="noreferrer">
                          {p.source.title}
                        </a>
                      ) : (
                        p.source.title
                      )}
                      {p.source.locator && <span className="muted"> · {p.source.locator}</span>}
                    </>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  {p.status === "open" ? <>Open question: {p.question}</> : p.rationale}
                  {Object.entries(p.by_region).map(([region, o]) => (
                    <div key={region} className="muted">
                      {region}: <span className="mono">{o.value}</span>
                      {o.source && <> · {o.source.title}</>}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="section-heading">
        <h3>Ratings by region</h3>
        <button type="button" className="secondary" onClick={() => void deriveAll()}>
          Derive all regions
        </button>
      </div>
      {derived && "runId" in derived && (
        <p role="status">
          Derivation <span className="mono">{derived.runId}</span> finished. <a href={`#/review/transition_barrier_derivation/${encodeURIComponent(derived.runId)}`}>Review the results</a>
        </p>
      )}
      {derived && "error" in derived && <p className="error-text" role="alert">{derived.error}</p>}
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
                <td>
                  <a href={cellHash(s.code, s.region)}>{s.region}</a>
                </td>
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

function BarrierMatrixPage() {
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
                  <RatingCell key={r} cell={matrix.cells[c.code]?.[r]} onClick={() => (window.location.hash = cellHash(c.code, r).slice(1))} />
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

/** `#/transitionBarrier` is the matrix; `#/transitionBarrier/cell/<code>/<region>` is one cell. */
export function TransitionBarrierAssessment({ params = [] }: { params?: string[] }) {
  return params[0] === "cell" && params[1] && params[2] ? <BarrierCellDetail code={params[1]} region={params[2]} /> : <BarrierMatrixPage />;
}
