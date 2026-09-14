import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { usePortfolioPane } from "../../context/usePortfolioPane";
import { AggregationView, TrendView } from "../../components/ResultView";
import { AGGREGATION_DIMENSIONS, type AggregationResult, type CoverageBySource, type FinancedEmissionsResult, type TrendPoint } from "../../types";

const CARBON_INTENSITY_UNIT = "tCO2e / EUR M revenue";
const SOURCE_LABELS: Record<string, string> = {
  internal_api: "Internal ESG API",
  extracted: "Extracted from disclosures",
  catalogue: "Catalogue",
  estimated_proxy: "Estimated (structural proxy)",
  missing: "Missing",
};

/** The default landing view: pre-built dashboards per risk category (spec
 * §9 sub-tab 1), driven entirely by the persistent pane -- only the climate
 * risk category exists today (see docs/SPEC_GAP_ANALYSIS.md §1), so that's
 * what this dashboard shows; factor/concentration/controversy/PAI
 * dashboards aren't available yet and are called out explicitly rather
 * than silently omitted. */
export function StandardAnalytics() {
  const { portfolios } = usePortfolioPane();
  return (
    <>
      <p className="help-text">
        Pre-built climate risk dashboards for the current selection. Factor, concentration, and PAI dashboards
        aren't built yet (see <code>docs/SPEC_GAP_ANALYSIS.md</code>) -- only climate risk is modeled today.
      </p>
      {portfolios.length === 0 ? (
        <p className="muted">Seed the demo dataset above to see dashboards.</p>
      ) : (
        <>
          <WaciCard />
          <FinancedEmissionsCard />
          <CoverageCard />
        </>
      )}
    </>
  );
}

function WaciCard() {
  const { selectedPortfolioIds, dateMode, effectiveAsOf, effectiveDateRange } = usePortfolioPane();
  const [groupBy, setGroupBy] = useState("portfolio_id");
  const [result, setResult] = useState<AggregationResult | null>(null);
  const [trend, setTrend] = useState<TrendPoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const portfolioFilter = selectedPortfolioIds.length ? selectedPortfolioIds : undefined;
    const load =
      dateMode === "trend" && effectiveDateRange
        ? api.getWaciTrend({ group_by: groupBy, portfolio_id: portfolioFilter }).then((t) => {
            if (!cancelled) {
              setTrend(t);
              setResult(null);
            }
          })
        : api.getWaci({ group_by: groupBy, as_of: effectiveAsOf, portfolio_id: portfolioFilter }).then((r) => {
            if (!cancelled) {
              setResult(r);
              setTrend(null);
            }
          });
    load
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [groupBy, selectedPortfolioIds, dateMode, effectiveAsOf, effectiveDateRange]);

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
      {loading && <p className="muted">Loading...</p>}
      {error && <p className="error-text">{error}</p>}
      {result && <AggregationView result={result} unit={CARBON_INTENSITY_UNIT} />}
      {trend && <TrendView trend={trend} unit={CARBON_INTENSITY_UNIT} />}
    </section>
  );
}

function FinancedEmissionsCard() {
  const { selectedPortfolioIds, effectiveAsOf } = usePortfolioPane();
  const [result, setResult] = useState<FinancedEmissionsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getFinancedEmissions({ as_of: effectiveAsOf, portfolio_id: selectedPortfolioIds.length ? selectedPortfolioIds : undefined })
      .then((r) => !cancelled && setResult(r))
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [selectedPortfolioIds, effectiveAsOf]);

  return (
    <section className="card">
      <h3>PCAF financed emissions</h3>
      <p className="help-text">
        <code>Σ (holding market value / issuer EVIC) × issuer Scope 1+2 emissions</code>. Holdings whose issuer lacks
        EVIC or Scope 1/2 data are excluded from the number, not treated as zero.
      </p>
      {loading && <p className="muted">Loading...</p>}
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

function CoverageCard() {
  const { climateSchema, effectiveAsOf } = usePortfolioPane();
  const [fieldId, setFieldId] = useState("");
  const [counts, setCounts] = useState<CoverageBySource | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!fieldId && climateSchema?.fields.length) setFieldId(climateSchema.fields[0].field_id);
  }, [climateSchema, fieldId]);

  useEffect(() => {
    if (!fieldId) return;
    let cancelled = false;
    setError(null);
    api
      .getClimateCoverage(fieldId, effectiveAsOf)
      .then((c) => !cancelled && setCounts(c))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [fieldId, effectiveAsOf]);

  const total = counts ? Object.values(counts).reduce((a, b) => a + b, 0) : 0;

  return (
    <section className="card">
      <h3>Data coverage</h3>
      <p className="help-text">Which source resolved each issuer's value for a field -- never mistake partial coverage for complete data.</p>
      <label className="field-label">Field</label>
      <select value={fieldId} onChange={(e) => setFieldId(e.target.value)}>
        {(climateSchema?.fields ?? []).map((f) => (
          <option key={f.field_id} value={f.field_id}>
            {f.name}
          </option>
        ))}
      </select>
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
