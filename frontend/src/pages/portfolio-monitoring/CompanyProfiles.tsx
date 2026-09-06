import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { usePortfolioPane } from "../../context/usePortfolioPane";
import { GroundedBadge } from "../../components/ConfidenceBadge";
import type { CompanyRef, NewsItem, NewsRiskFlag } from "../../types";

const SEVERITY_CLASS: Record<string, string> = { high: "badge badge-low", medium: "badge badge-mid", low: "badge badge-neutral" };

/** The drill-down endpoint every pivot eventually terminates at (spec §6):
 * one assembled view per issuer. This repo has no engagement/voting store
 * to combine in (see docs/SPEC_GAP_ANALYSIS.md §6) -- what's here is the
 * part that's genuinely available: identity, climate data points as
 * recorded against this issuer's holdings, news, and risk flags, all via
 * endpoints that already existed but were never called this way. */
export function CompanyProfiles() {
  const { climateSchema, selectedPortfolioIds, effectiveAsOf } = usePortfolioPane();
  const [companies, setCompanies] = useState<CompanyRef[]>([]);
  const [filter, setFilter] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [values, setValues] = useState<Record<string, number | string | boolean | null>>({});
  const [news, setNews] = useState<NewsItem[]>([]);
  const [flags, setFlags] = useState<NewsRiskFlag[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.listPortfolioCompanies().then(setCompanies).catch(() => setCompanies([]));
  }, []);

  useEffect(() => {
    if (!companyId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setValues({});

    async function loadClimateValues() {
      const fields = climateSchema?.fields ?? [];
      const entries = await Promise.all(
        fields.map(async (f) => {
          try {
            const result = await api.runPortfolioAggregate({
              name: `profile:${companyId}:${f.field_id}`,
              portfolio_filter: selectedPortfolioIds,
              security_filter: { company_id: companyId },
              group_by: "company_id",
              metric: "weighted_avg_datapoint",
              data_point_field_id: f.field_id,
              as_of: effectiveAsOf ?? null,
            });
            const result_ = Array.isArray(result) ? null : result;
            return [f.field_id, result_?.rows[0]?.weighted_avg_value ?? null] as const;
          } catch {
            return [f.field_id, null] as const;
          }
        })
      );
      if (!cancelled) setValues(Object.fromEntries(entries));
    }

    Promise.all([
      loadClimateValues(),
      api.listPortfolioNews(companyId).then((n) => !cancelled && setNews(n)),
      api.listNewsFlags(companyId).then((f) => !cancelled && setFlags(f)),
    ])
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));

    return () => {
      cancelled = true;
    };
  }, [companyId, climateSchema, selectedPortfolioIds, effectiveAsOf]);

  const filteredCompanies = companies.filter(
    (c) => !filter.trim() || c.name.toLowerCase().includes(filter.toLowerCase()) || c.company_id.toLowerCase().includes(filter.toLowerCase())
  );
  const selected = companies.find((c) => c.company_id === companyId) ?? null;

  return (
    <section className="card">
      <h3>Company Profiles</h3>
      <p className="help-text">
        Reached by picking an issuer directly, or by filtering to one <code>company_id</code> in Pivot Explorer. No
        engagement/voting history is shown -- this repo has no Engagement Record Store to draw from (see{" "}
        <code>docs/SPEC_GAP_ANALYSIS.md</code>). Climate figures reflect what's recorded against holdings in this
        issuer within the current pane selection; an issuer not currently held may show no data for that reason.
      </p>
      <label className="field-label">Filter issuers</label>
      <input type="text" placeholder="Search by name or ID..." value={filter} onChange={(e) => setFilter(e.target.value)} />
      <label className="field-label">Issuer</label>
      <select value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
        <option value="">-- select an issuer --</option>
        {filteredCompanies.map((c) => (
          <option key={c.company_id} value={c.company_id}>
            {c.name} ({c.company_id})
          </option>
        ))}
      </select>

      {loading && <p className="muted">Loading profile...</p>}
      {error && <p className="error-text">{error}</p>}

      {selected && !loading && (
        <>
          <div className="card" style={{ marginTop: 16 }}>
            <h4>{selected.name}</h4>
            <p className="muted">
              {selected.company_id}
              {selected.sector ? ` -- ${selected.sector}` : ""}
              {selected.country ? ` -- ${selected.country}` : ""}
            </p>
            <div className="stat-tile-grid">
              {(climateSchema?.fields ?? []).map((f) => {
                const v = values[f.field_id];
                return (
                  <div className="stat-tile" key={f.field_id}>
                    <div className="stat-value">{v != null ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 }) : "no data"}</div>
                    <div className="stat-label">
                      {f.name} {f.unit ? `(${f.unit})` : ""}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="card">
            <h4>News ({news.length})</h4>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Headline</th>
                  <th>Published</th>
                </tr>
              </thead>
              <tbody>
                {news.map((n) => (
                  <tr key={n.news_id}>
                    <td>{n.source_url ? <a href={n.source_url} target="_blank" rel="noreferrer">{n.headline}</a> : n.headline}</td>
                    <td>{n.published_at}</td>
                  </tr>
                ))}
                {news.length === 0 && (
                  <tr>
                    <td colSpan={2} className="muted">
                      No news for this issuer.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="card">
            <h4>Risk flags ({flags.length})</h4>
            {flags.map((f) => (
              <div key={f.flag_id} className="review-item">
                <div className="run-progress-header">
                  <span className="badge badge-neutral">{f.category}</span>{" "}
                  <span className={SEVERITY_CLASS[f.severity] ?? "badge badge-neutral"}>{f.severity}</span> <GroundedBadge grounded={f.grounded} />
                </div>
                <p>{f.rationale}</p>
                <p className="muted">"{f.quote}"</p>
              </div>
            ))}
            {flags.length === 0 && <p className="muted">No risk flags for this issuer.</p>}
          </div>
        </>
      )}
    </section>
  );
}
