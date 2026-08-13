import { useEffect, useState } from "react";
import { api } from "../api/client";
import { AggregationView, TrendView } from "../components/ResultView";
import { PivotTable } from "../components/PivotTable";
import { PortfolioFilterPicker } from "../components/PortfolioFilterPicker";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import {
  AGGREGATION_DIMENSIONS,
  type AggregationMetric,
  type AggregationResult,
  type DataPointSchema,
  type DemoSeedSummary,
  type PivotResult,
  type PortfolioSummary,
  type QAAnswer,
  type SecurityResolution,
  type TrendPoint,
} from "../types";

const SUB_TABS = [
  { id: "overview", label: "Overview" },
  { id: "explore", label: "Explore" },
  { id: "pivot", label: "Pivot" },
  { id: "ask", label: "Ask" },
] as const;

const ASSET_CLASSES = ["", "equity", "corporate_bond", "government_bond", "fund", "etf", "derivative", "cash", "other"];

export function PortfolioRisk() {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>("overview");
  const [portfolios, setPortfolios] = useState<PortfolioSummary[]>([]);
  const [climateSchema, setClimateSchema] = useState<DataPointSchema | null>(null);

  async function refreshPortfolios() {
    try {
      setPortfolios(await api.listPortfolios());
    } catch {
      setPortfolios([]);
    }
  }

  useEffect(() => {
    refreshPortfolios();
    api.getClimateSchema().then(setClimateSchema).catch(() => setClimateSchema(null));
  }, []);

  return (
    <div className="page">
      <h2>Portfolio Risk &amp; Exposure</h2>
      <p className="help-text">
        Aggregate holdings across every portfolio, build analytics on the fly, or ask a plain-language question --
        the LLM only drafts the query, a deterministic engine computes the real number. See{" "}
        <code>docs/PORTFOLIO_RISK_EXPOSURE_PLAN.md</code> for the design.
      </p>
      <nav className="sub-nav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {sub === "overview" && <OverviewTab portfolios={portfolios} onSeeded={refreshPortfolios} />}
      {sub === "explore" && <ExploreTab portfolios={portfolios} climateSchema={climateSchema} />}
      {sub === "pivot" && <PivotTab portfolios={portfolios} climateSchema={climateSchema} />}
      {sub === "ask" && <AskTab />}
    </div>
  );
}

function OverviewTab({ portfolios, onSeeded }: { portfolios: PortfolioSummary[]; onSeeded: () => void }) {
  const [seeding, setSeeding] = useState(false);
  const [summary, setSummary] = useState<DemoSeedSummary | null>(null);
  const [reviewQueue, setReviewQueue] = useState<SecurityResolution[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function refreshReviewQueue() {
    try {
      setReviewQueue(await api.listSecuritiesNeedingReview());
    } catch {
      setReviewQueue([]);
    }
  }

  useEffect(() => {
    refreshReviewQueue();
  }, [portfolios]);

  async function seedDemo() {
    setSeeding(true);
    setError(null);
    try {
      const result = await api.seedPortfolioDemo();
      setSummary(result);
      onSeeded();
    } catch (e) {
      setError(String(e));
    } finally {
      setSeeding(false);
    }
  }

  return (
    <>
      <section className="card">
        <h3>Demo dataset</h3>
        <p className="help-text">
          Seeds a deterministic, illustrative dataset: 15 companies, 4 portfolios, 4 quarterly holdings snapshots,
          validated climate data points, and ingested news -- see <code>arp/portfolio/mock_data.py</code>. Safe to
          re-run.
        </p>
        <button onClick={seedDemo} disabled={seeding}>
          {seeding ? "Seeding..." : "Seed demo dataset"}
        </button>
        {error && <p className="error-text">{error}</p>}
        {summary && (
          <p className="status-text">
            Seeded {summary.company_count} companies, {summary.security_count} securities, {summary.holding_rows} holding
            rows across {summary.portfolio_count} portfolios ({summary.snapshot_dates.join(", ")}); {summary.climate_observations}{" "}
            climate observations ({summary.climate_mismatch_companies.join(", ") || "none"} flagged for internal-API/extraction
            mismatch); {summary.news_items} news items ingested.
          </p>
        )}
      </section>

      <section className="card">
        <h3>Portfolios ({portfolios.length})</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Name</th>
              <th>Tags</th>
            </tr>
          </thead>
          <tbody>
            {portfolios.map((p) => (
              <tr key={p.portfolio_id}>
                <td>{p.portfolio_id}</td>
                <td>{p.name}</td>
                <td>{p.tags.join(", ")}</td>
              </tr>
            ))}
            {portfolios.length === 0 && (
              <tr>
                <td colSpan={3} className="muted">
                  No portfolios yet -- seed the demo dataset above.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

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
    </>
  );
}

function DataPointFieldSelect({ schema, value, onChange }: { schema: DataPointSchema | null; value: string; onChange: (v: string) => void }) {
  return (
    <>
      <label className="field-label">Data point field</label>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">-- select a field --</option>
        {(schema?.fields ?? []).map((f) => (
          <option key={f.field_id} value={f.field_id}>
            {f.name} ({f.unit ?? f.data_type})
          </option>
        ))}
      </select>
    </>
  );
}

function ExploreTab({ portfolios, climateSchema }: { portfolios: PortfolioSummary[]; climateSchema: DataPointSchema | null }) {
  const [groupBy, setGroupBy] = useState<string>("portfolio_id");
  const [metric, setMetric] = useState<AggregationMetric>("market_value_sum");
  const [companyId, setCompanyId] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [fieldId, setFieldId] = useState("");
  const [selectedPortfolios, setSelectedPortfolios] = useState<string[]>([]);
  const [asOf, setAsOf] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [result, setResult] = useState<AggregationResult | null>(null);
  const [trend, setTrend] = useState<TrendPoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function run() {
    setRunning(true);
    setError(null);
    setTrend(null);
    setResult(null);
    try {
      const securityFilter: Record<string, string> = {};
      if (companyId.trim()) securityFilter.company_id = companyId.trim();
      if (assetClass) securityFilter.asset_class = assetClass;
      const wantsTrend = Boolean(dateFrom.trim() && dateTo.trim());
      const res = await api.runPortfolioAggregate({
        name: "Explore query",
        portfolio_filter: selectedPortfolios,
        security_filter: securityFilter,
        group_by: groupBy,
        metric,
        data_point_field_id: metric === "weighted_avg_datapoint" ? fieldId || null : null,
        as_of: wantsTrend ? null : asOf || null,
        date_range: wantsTrend ? [dateFrom.trim(), dateTo.trim()] : null,
      });
      if (Array.isArray(res)) setTrend(res);
      else setResult(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="card">
      <h3>Build a query</h3>
      <p className="help-text">
        e.g. "how many EUR million is the exposure to stocks from BMW": group by portfolio_id, filter company_id =
        bmw, asset_class = equity, metric = market_value_sum. Fill in a date range to see the same query as a trend
        instead of a single point in time.
      </p>

      <label className="field-label">Group by</label>
      <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
        {AGGREGATION_DIMENSIONS.map((d) => (
          <option key={d} value={d}>
            {d}
          </option>
        ))}
      </select>

      <label className="field-label">Metric</label>
      <select value={metric} onChange={(e) => setMetric(e.target.value as AggregationMetric)}>
        <option value="market_value_sum">Market value sum (EUR)</option>
        <option value="weighted_avg_datapoint">Weighted-average data point</option>
        <option value="count">Holding count</option>
      </select>

      {metric === "weighted_avg_datapoint" && <DataPointFieldSelect schema={climateSchema} value={fieldId} onChange={setFieldId} />}

      <div className="inline-fields">
        <div>
          <label className="field-label">Issuer (company_id)</label>
          <input type="text" placeholder="e.g. bmw" value={companyId} onChange={(e) => setCompanyId(e.target.value)} />
        </div>
        <div>
          <label className="field-label">Asset class</label>
          <select value={assetClass} onChange={(e) => setAssetClass(e.target.value)}>
            {ASSET_CLASSES.map((a) => (
              <option key={a} value={a}>
                {a || "(any)"}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="field-label">As of (blank = latest)</label>
          <input type="text" placeholder="YYYY-MM-DD" value={asOf} onChange={(e) => setAsOf(e.target.value)} disabled={Boolean(dateFrom || dateTo)} />
        </div>
      </div>

      <div className="inline-fields">
        <div>
          <label className="field-label">Trend from (optional)</label>
          <input type="text" placeholder="YYYY-MM-DD" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div>
          <label className="field-label">Trend to (optional)</label>
          <input type="text" placeholder="YYYY-MM-DD" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
      </div>

      <div className="inline-block">
        <PortfolioFilterPicker portfolios={portfolios} selected={selectedPortfolios} onChange={setSelectedPortfolios} />
      </div>

      <button onClick={run} disabled={running}>
        {running ? "Running..." : "Run query"}
      </button>
      {error && <p className="error-text">{error}</p>}
      {result && (
        <div className="inline-block">
          <AggregationView result={result} />
        </div>
      )}
      {trend && (
        <div className="inline-block">
          <TrendView trend={trend} />
        </div>
      )}
    </section>
  );
}

function PivotTab({ portfolios, climateSchema }: { portfolios: PortfolioSummary[]; climateSchema: DataPointSchema | null }) {
  const [rowDim, setRowDim] = useState("sector");
  const [colDim, setColDim] = useState("portfolio_id");
  const [metric, setMetric] = useState<AggregationMetric>("market_value_sum");
  const [companyId, setCompanyId] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [fieldId, setFieldId] = useState("");
  const [selectedPortfolios, setSelectedPortfolios] = useState<string[]>([]);
  const [asOf, setAsOf] = useState("");
  const [result, setResult] = useState<PivotResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      const securityFilter: Record<string, string> = {};
      if (companyId.trim()) securityFilter.company_id = companyId.trim();
      if (assetClass) securityFilter.asset_class = assetClass;
      const res = await api.runPortfolioPivot({
        name: "Explore pivot",
        portfolio_filter: selectedPortfolios,
        security_filter: securityFilter,
        row_dim: rowDim,
        col_dim: colDim,
        metric,
        data_point_field_id: metric === "weighted_avg_datapoint" ? fieldId || null : null,
        as_of: asOf || null,
      });
      setResult(res);
    } catch (e) {
      setError(String(e));
      setResult(null);
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="card">
      <h3>Cross-tab two dimensions</h3>
      <p className="help-text">
        e.g. row = sector, column = portfolio_id, metric = market value sum: every sector's exposure broken out
        across every portfolio in one grid, instead of filtering one dimension at a time.
      </p>

      <div className="inline-fields">
        <div>
          <label className="field-label">Rows</label>
          <select value={rowDim} onChange={(e) => setRowDim(e.target.value)}>
            {AGGREGATION_DIMENSIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="field-label">Columns</label>
          <select value={colDim} onChange={(e) => setColDim(e.target.value)}>
            {AGGREGATION_DIMENSIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="field-label">Metric</label>
          <select value={metric} onChange={(e) => setMetric(e.target.value as AggregationMetric)}>
            <option value="market_value_sum">Market value sum (EUR)</option>
            <option value="weighted_avg_datapoint">Weighted-average data point</option>
            <option value="count">Holding count</option>
          </select>
        </div>
      </div>

      {metric === "weighted_avg_datapoint" && <DataPointFieldSelect schema={climateSchema} value={fieldId} onChange={setFieldId} />}

      <div className="inline-fields">
        <div>
          <label className="field-label">Issuer (company_id)</label>
          <input type="text" placeholder="e.g. bmw" value={companyId} onChange={(e) => setCompanyId(e.target.value)} />
        </div>
        <div>
          <label className="field-label">Asset class</label>
          <select value={assetClass} onChange={(e) => setAssetClass(e.target.value)}>
            {ASSET_CLASSES.map((a) => (
              <option key={a} value={a}>
                {a || "(any)"}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="field-label">As of (blank = latest)</label>
          <input type="text" placeholder="YYYY-MM-DD" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </div>
      </div>

      <div className="inline-block">
        <PortfolioFilterPicker portfolios={portfolios} selected={selectedPortfolios} onChange={setSelectedPortfolios} />
      </div>

      <button onClick={run} disabled={running}>
        {running ? "Running..." : "Run pivot"}
      </button>
      {error && <p className="error-text">{error}</p>}
      {result && (
        <div className="inline-block">
          <PivotTable result={result} />
        </div>
      )}
    </section>
  );
}

const EXAMPLE_QUESTIONS = [
  "How many EUR million is our exposure to BMW?",
  "What's our total equity exposure by sector?",
  "How much do we hold in TotalEnergies across all portfolios?",
];

function AskTab() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<QAAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  async function ask(q: string) {
    setAsking(true);
    setError(null);
    setAnswer(null);
    try {
      setAnswer(await api.askPortfolio(q));
    } catch (e) {
      setError(String(e));
    } finally {
      setAsking(false);
    }
  }

  return (
    <section className="card">
      <h3>Ask a question</h3>
      <p className="help-text">
        The LLM only drafts the underlying query (portfolios, filters, grouping, metric) -- the deterministic
        aggregation engine computes the real number. Requires <code>ARP_ANTHROPIC_API_KEY</code> to be configured on
        the server.
      </p>
      <textarea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about portfolio exposure..." />
      <div className="toolbar">
        <button onClick={() => ask(question)} disabled={asking || !question.trim()}>
          {asking ? "Asking..." : "Ask"}
        </button>
        {EXAMPLE_QUESTIONS.map((q) => (
          <button key={q} className="link-button" onClick={() => { setQuestion(q); ask(q); }} disabled={asking}>
            {q}
          </button>
        ))}
      </div>
      {error && <p className="error-text">{error}</p>}
      {answer && !answer.resolvable && <p className="help-text">Could not resolve the question: {answer.clarification_needed}</p>}
      {answer && answer.resolvable && (
        <>
          <p className="answer-text">{answer.answer_text}</p>
          {answer.result && <AggregationView result={answer.result} />}
          {answer.spec && (
            <p className="muted">
              Query: group_by={answer.spec.group_by}, metric={answer.spec.metric}, filter=
              {JSON.stringify(answer.spec.security_filter)}, portfolios={answer.spec.portfolio_filter?.join(", ") || "all"}
            </p>
          )}
        </>
      )}
    </section>
  );
}
