import { useState } from "react";
import { BarChart } from "../../components/BarChart";
import type { CompanyFinancialsRecord } from "../../types";

/** Batch-level CapEx/R&D comparison across every company in the run --
 * companies with no disclosed value for the chosen metric are left out of
 * the chart (never charted as 0, which would misreport "no disclosure" as
 * "zero spend") and counted separately instead. Figures are charted exactly
 * as reported per company, in whatever currency each company discloses in
 * -- same as the table below -- rather than fabricating an FX conversion. */
export function BatchSpendChart({ results }: { results: CompanyFinancialsRecord[] }) {
  const [metric, setMetric] = useState<"capex" | "rnd">("capex");
  const withValue = results.filter((r) => r[metric].total.value != null);
  const currencies = new Set(withValue.map((r) => r.currency ?? "unknown"));
  const chartData = [...withValue]
    .sort((a, b) => (b[metric].total.value ?? 0) - (a[metric].total.value ?? 0))
    .map((r) => ({ label: r.name, value: r[metric].total.value ?? 0 }));

  return (
    <section className="card">
      <h2>Batch overview ({results.length} companies)</h2>
      <div className="view-toggle">
        <button className={metric === "capex" ? "active" : ""} onClick={() => setMetric("capex")}>
          CapEx
        </button>
        <button className={metric === "rnd" ? "active" : ""} onClick={() => setMetric("rnd")}>
          R&amp;D
        </button>
      </div>
      <p className="help-text">
        {withValue.length} of {results.length} companies disclosed a {metric === "capex" ? "CapEx" : "R&D"} total
        {results.length > withValue.length && ` (${results.length - withValue.length} not disclosed, excluded from the chart)`}.
        {currencies.size > 1 && " Figures are shown exactly as each company reports them — currencies are not converted; see the table below for each company's currency."}
      </p>
      <BarChart data={chartData} valueFormatter={(v) => v.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
    </section>
  );
}
