import { useState } from "react";
import { api } from "../../api/client";
import { usePortfolioPane } from "../../context/usePortfolioPane";
import { AggregationView, TrendView } from "../../components/ResultView";
import { PivotTable } from "../../components/PivotTable";
import { AGGREGATION_DIMENSIONS, type AggregationMetric, type AggregationResult, type PivotResult, type TrendPoint } from "../../types";

const ASSET_CLASSES = ["", "equity", "corporate_bond", "government_bond", "fund", "etf", "derivative", "cash", "other"];

function DataPointFieldSelect({
  schema,
  value,
  onChange,
}: {
  schema: ReturnType<typeof usePortfolioPane>["climateSchema"];
  value: string;
  onChange: (v: string) => void;
}) {
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

/** The ad hoc cross-tab engine (spec §4 / §9 sub-tab 2): any metric by any
 * one dimension, or by two dimensions as a cross-tab, over the same data
 * "Standard Analytics" curates a fixed view of. Portfolio/date come from
 * the persistent pane; climate fields are just another data-point field,
 * so this single component subsumes what used to be three separate tabs
 * (Explore, Pivot, and the climate-only Pivot). */
export function PivotExplorer() {
  const [mode, setMode] = useState<"single" | "cross-tab">("single");
  return (
    <section className="card">
      <h3>Pivot Explorer</h3>
      <p className="help-text">
        e.g. "how many EUR million is the exposure to stocks from BMW": single dimension = portfolio_id, filter
        company_id = bmw, asset_class = equity, metric = market value sum. Or cross-tab sector x portfolio_id to see
        every sector broken out across every portfolio at once.
      </p>
      <div className="view-toggle">
        <button className={mode === "single" ? "active" : ""} onClick={() => setMode("single")}>
          Single dimension
        </button>
        <button className={mode === "cross-tab" ? "active" : ""} onClick={() => setMode("cross-tab")}>
          Cross-tab
        </button>
      </div>
      {mode === "single" ? <SingleDimension /> : <CrossTab />}
    </section>
  );
}

function SingleDimension() {
  const { selectedPortfolioIds, dateMode, effectiveAsOf, effectiveDateRange, climateSchema } = usePortfolioPane();
  const [groupBy, setGroupBy] = useState("portfolio_id");
  const [metric, setMetric] = useState<AggregationMetric>("market_value_sum");
  const [companyId, setCompanyId] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [fieldId, setFieldId] = useState("");
  const [result, setResult] = useState<AggregationResult | null>(null);
  const [trend, setTrend] = useState<TrendPoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function run() {
    setRunning(true);
    setError(null);
    setResult(null);
    setTrend(null);
    try {
      const securityFilter: Record<string, string> = {};
      if (companyId.trim()) securityFilter.company_id = companyId.trim();
      if (assetClass) securityFilter.asset_class = assetClass;
      const res = await api.runPortfolioAggregate({
        name: "Pivot Explorer query",
        portfolio_filter: selectedPortfolioIds,
        security_filter: securityFilter,
        group_by: groupBy,
        metric,
        data_point_field_id: metric === "weighted_avg_datapoint" ? fieldId || null : null,
        as_of: dateMode === "trend" ? null : effectiveAsOf ?? null,
        date_range: effectiveDateRange,
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
    <div>
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
    </div>
  );
}

function CrossTab() {
  const { selectedPortfolioIds, dateMode, effectiveAsOf, climateSchema } = usePortfolioPane();
  const [rowDim, setRowDim] = useState("sector");
  const [colDim, setColDim] = useState("portfolio_id");
  const [metric, setMetric] = useState<AggregationMetric>("market_value_sum");
  const [companyId, setCompanyId] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [fieldId, setFieldId] = useState("");
  const [result, setResult] = useState<PivotResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const trendModeActive = dateMode === "trend";

  async function run() {
    setRunning(true);
    setError(null);
    try {
      const securityFilter: Record<string, string> = {};
      if (companyId.trim()) securityFilter.company_id = companyId.trim();
      if (assetClass) securityFilter.asset_class = assetClass;
      const res = await api.runPortfolioPivot({
        name: "Pivot Explorer cross-tab",
        portfolio_filter: selectedPortfolioIds,
        security_filter: securityFilter,
        row_dim: rowDim,
        col_dim: colDim,
        metric,
        data_point_field_id: metric === "weighted_avg_datapoint" ? fieldId || null : null,
        as_of: effectiveAsOf ?? null,
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
    <div>
      {trendModeActive && (
        <p className="help-text">
          The pane is set to "Trend range," but cross-tabs are point-in-time only -- switch the pane to Latest or As
          of date to run one.
        </p>
      )}
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
      </div>

      <button onClick={run} disabled={running || trendModeActive}>
        {running ? "Running..." : "Run pivot"}
      </button>
      {error && <p className="error-text">{error}</p>}
      {result && (
        <div className="inline-block">
          <PivotTable result={result} />
        </div>
      )}
    </div>
  );
}
