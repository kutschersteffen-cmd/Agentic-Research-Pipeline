import { useEffect, useState } from "react";
import { api } from "../api/client";
import { AggregationResultTable } from "../components/AggregationResultTable";
import { PortfolioFilterPicker } from "../components/PortfolioFilterPicker";
import { GroundedBadge } from "../components/ConfidenceBadge";
import {
  AGGREGATION_DIMENSIONS,
  type AggregationResult,
  type CoverageBySource,
  type DataPointSchema,
  type FinancedEmissionsResult,
  type NewsItem,
  type NewsRiskFlag,
  type PortfolioSummary,
  type TrendPoint,
} from "../types";

const SUB_TABS = [
  { id: "waci", label: "WACI" },
  { id: "financed", label: "Financed Emissions" },
  { id: "coverage", label: "Coverage" },
  { id: "news", label: "News & Flags" },
] as const;

export function ClimateAnalytics() {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>("waci");
  const [portfolios, setPortfolios] = useState<PortfolioSummary[]>([]);
  const [schema, setSchema] = useState<DataPointSchema | null>(null);

  useEffect(() => {
    api.listPortfolios().then(setPortfolios).catch(() => setPortfolios([]));
    api.getClimateSchema().then(setSchema).catch(() => setSchema(null));
  }, []);

  return (
    <div className="page">
      <h2>Climate Analytics</h2>
      <p className="help-text">
        Weighted-average carbon intensity, PCAF-style financed emissions, and data coverage -- sourced from the
        internal ESG API and cross-validated against the Extraction Engine's independent read of company
        disclosures (see <code>climate/validation.py</code>). Seed the demo dataset on the Portfolio Risk tab first.
      </p>
      <nav className="sub-nav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {sub === "waci" && <WaciTab portfolios={portfolios} />}
      {sub === "financed" && <FinancedEmissionsTab portfolios={portfolios} />}
      {sub === "coverage" && <CoverageTab schema={schema} />}
      {sub === "news" && <NewsTab />}
    </div>
  );
}

function WaciTab({ portfolios }: { portfolios: PortfolioSummary[] }) {
  const [groupBy, setGroupBy] = useState("portfolio_id");
  const [selectedPortfolios, setSelectedPortfolios] = useState<string[]>([]);
  const [asOf, setAsOf] = useState("");
  const [result, setResult] = useState<AggregationResult | null>(null);
  const [trend, setTrend] = useState<TrendPoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    setLoading(true);
    setError(null);
    setTrend(null);
    try {
      setResult(await api.getWaci({ group_by: groupBy, as_of: asOf || undefined, portfolio_id: selectedPortfolios.length ? selectedPortfolios : undefined }));
    } catch (e) {
      setError(String(e));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  async function runTrend() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setTrend(await api.getWaciTrend({ group_by: groupBy, portfolio_id: selectedPortfolios.length ? selectedPortfolios : undefined }));
    } catch (e) {
      setError(String(e));
      setTrend(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card">
      <h3>Weighted-average carbon intensity</h3>
      <label className="field-label">Group by</label>
      <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
        {AGGREGATION_DIMENSIONS.map((d) => (
          <option key={d} value={d}>
            {d}
          </option>
        ))}
      </select>
      <div className="inline-block">
        <PortfolioFilterPicker portfolios={portfolios} selected={selectedPortfolios} onChange={setSelectedPortfolios} />
      </div>
      <label className="field-label">As of (blank = latest)</label>
      <input type="text" placeholder="YYYY-MM-DD" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
      <div className="toolbar">
        <button onClick={run} disabled={loading}>
          {loading ? "Running..." : "Run"}
        </button>
        <button onClick={runTrend} disabled={loading}>
          Show trend across all snapshots
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {result && <AggregationResultTable result={result} />}
      {trend && <WaciTrendTable trend={trend} />}
    </section>
  );
}

function WaciTrendTable({ trend }: { trend: TrendPoint[] }) {
  const dates = trend.map((t) => t.as_of);
  const groupValues = Array.from(new Set(trend.flatMap((t) => t.result.rows.map((r) => r.group_value)))).sort();
  const valueAt = (groupValue: string, date: string) => {
    const point = trend.find((t) => t.as_of === date);
    const row = point?.result.rows.find((r) => r.group_value === groupValue);
    return row?.weighted_avg_value ?? null;
  };

  return (
    <div className="inline-block">
      <p className="muted">Weighted-average carbon intensity by snapshot date:</p>
      <table className="data-table">
        <thead>
          <tr>
            <th>Group</th>
            {dates.map((d) => (
              <th key={d}>{d}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groupValues.map((gv) => (
            <tr key={gv}>
              <td>{gv}</td>
              {dates.map((d) => {
                const v = valueAt(gv, d);
                return <td key={d}>{v != null ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "--"}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FinancedEmissionsTab({ portfolios }: { portfolios: PortfolioSummary[] }) {
  const [selectedPortfolios, setSelectedPortfolios] = useState<string[]>([]);
  const [asOf, setAsOf] = useState("");
  const [result, setResult] = useState<FinancedEmissionsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      setResult(await api.getFinancedEmissions({ as_of: asOf || undefined, portfolio_id: selectedPortfolios.length ? selectedPortfolios : undefined }));
    } catch (e) {
      setError(String(e));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card">
      <h3>PCAF financed emissions</h3>
      <p className="help-text">
        <code>Σ (holding market value / issuer EVIC) × issuer Scope 1+2 emissions</code>. Holdings whose issuer lacks
        EVIC or Scope 1/2 data are excluded from the number, not treated as zero -- see the uncovered figures below.
      </p>
      <div className="inline-block">
        <PortfolioFilterPicker portfolios={portfolios} selected={selectedPortfolios} onChange={setSelectedPortfolios} />
      </div>
      <label className="field-label">As of (blank = latest)</label>
      <input type="text" placeholder="YYYY-MM-DD" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
      <button onClick={run} disabled={loading}>
        {loading ? "Running..." : "Run"}
      </button>
      {error && <p className="error-text">{error}</p>}
      {result && (
        <div className="stat-tile-grid">
          <div className="stat-tile">
            <div className="stat-value">{result.financed_emissions_tco2e.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
            <div className="stat-label">Financed emissions (tCO2e)</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value">{(result.coverage_pct * 100).toFixed(1)}%</div>
            <div className="stat-label">Coverage</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value">{result.covered_market_value_eur.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
            <div className="stat-label">Covered market value (EUR)</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value">{result.uncovered_market_value_eur.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
            <div className="stat-label">Uncovered market value (EUR)</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value">{result.uncovered_holding_count}</div>
            <div className="stat-label">Uncovered holdings</div>
          </div>
        </div>
      )}
    </section>
  );
}

const SOURCE_LABELS: Record<string, string> = {
  internal_api: "Internal ESG API",
  extracted: "Extracted from disclosures",
  catalogue: "Catalogue",
  estimated_proxy: "Estimated (structural proxy)",
  missing: "Missing",
};

function CoverageTab({ schema }: { schema: DataPointSchema | null }) {
  const [fieldId, setFieldId] = useState("");
  const [asOf, setAsOf] = useState("");
  const [counts, setCounts] = useState<CoverageBySource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!fieldId && schema?.fields.length) setFieldId(schema.fields[0].field_id);
  }, [schema, fieldId]);

  async function run() {
    if (!fieldId) return;
    setLoading(true);
    setError(null);
    try {
      setCounts(await api.getClimateCoverage(fieldId, asOf || undefined));
    } catch (e) {
      setError(String(e));
      setCounts(null);
    } finally {
      setLoading(false);
    }
  }

  const total = counts ? Object.values(counts).reduce((a, b) => a + b, 0) : 0;

  return (
    <section className="card">
      <h3>Data coverage</h3>
      <p className="help-text">Which source resolved each issuer's value for a field -- never mistake partial coverage for complete data.</p>
      <label className="field-label">Field</label>
      <select value={fieldId} onChange={(e) => setFieldId(e.target.value)}>
        {(schema?.fields ?? []).map((f) => (
          <option key={f.field_id} value={f.field_id}>
            {f.name}
          </option>
        ))}
      </select>
      <label className="field-label">As of (blank = latest)</label>
      <input type="text" placeholder="YYYY-MM-DD" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
      <button onClick={run} disabled={loading || !fieldId}>
        {loading ? "Running..." : "Run"}
      </button>
      {error && <p className="error-text">{error}</p>}
      {counts && (
        <div className="inline-block">
          {Object.entries(counts).map(([source, count]) => (
            <div key={source} className="coverage-bar-row">
              <span className="coverage-bar-label">{SOURCE_LABELS[source] ?? source}</span>
              <span className="coverage-bar-track">
                <span className="coverage-bar-fill" style={{ width: total ? `${(count / total) * 100}%` : "0%" }} />
              </span>
              <span className="coverage-bar-count">{count}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

const SEVERITY_CLASS: Record<string, string> = { high: "badge badge-low", medium: "badge badge-mid", low: "badge badge-neutral" };

function NewsTab() {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [flags, setFlags] = useState<NewsRiskFlag[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [classifying, setClassifying] = useState(false);
  const [classifyStatus, setClassifyStatus] = useState<string | null>(null);

  async function refresh() {
    try {
      const [n, f] = await Promise.all([api.listPortfolioNews(), api.listNewsFlags()]);
      setNews(n);
      setFlags(f);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function classify() {
    setClassifying(true);
    setError(null);
    setClassifyStatus(null);
    try {
      const res = await api.classifyPortfolioNews();
      setClassifyStatus(`Classified ${res.classified} article(s), created ${res.flags_created} risk flag(s).`);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setClassifying(false);
    }
  }

  return (
    <>
      <section className="card">
        <h3>Ingested news ({news.length})</h3>
        <p className="help-text">
          From the news feed connector (mocked -- see <code>news/mock_source.py</code>). Not classified until you run
          the classifier below, which requires <code>ARP_ANTHROPIC_API_KEY</code>.
        </p>
        <button onClick={classify} disabled={classifying}>
          {classifying ? "Classifying..." : "Classify news"}
        </button>
        {classifyStatus && <p className="status-text">{classifyStatus}</p>}
        {error && <p className="error-text">{error}</p>}
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Headline</th>
              <th>Published</th>
            </tr>
          </thead>
          <tbody>
            {news.map((n) => (
              <tr key={n.news_id}>
                <td>{n.company_id}</td>
                <td>{n.source_url ? <a href={n.source_url} target="_blank" rel="noreferrer">{n.headline}</a> : n.headline}</td>
                <td>{n.published_at}</td>
              </tr>
            ))}
            {news.length === 0 && (
              <tr>
                <td colSpan={3} className="muted">
                  No news ingested yet -- seed the demo dataset on the Portfolio Risk tab.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h3>Risk flags ({flags.length})</h3>
        <p className="help-text">
          Every flag's quote is checked against the source article's own text by the same grounding checker used for
          citations elsewhere -- an ungrounded quote is dropped, never just marked unverified.
        </p>
        {flags.map((f) => (
          <div key={f.flag_id} className="review-item">
            <div className="run-progress-header">
              <strong>{f.company_id}</strong>
              <span>
                <span className="badge badge-neutral">{f.category}</span>{" "}
                <span className={SEVERITY_CLASS[f.severity] ?? "badge badge-neutral"}>{f.severity}</span> <GroundedBadge grounded={f.grounded} />
              </span>
            </div>
            <p>{f.rationale}</p>
            <p className="muted">"{f.quote}"</p>
          </div>
        ))}
        {flags.length === 0 && <p className="muted">No risk flags yet -- classify the news above.</p>}
      </section>
    </>
  );
}
