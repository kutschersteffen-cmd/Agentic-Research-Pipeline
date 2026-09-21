import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { RunProgress } from "../components/RunProgress";
import { UniversePicker } from "../components/UniversePicker";
import { ConfidenceBadge, VerdictBadge } from "../components/ConfidenceBadge";
import { CitationList } from "../components/CitationList";
import { SourcePanel, type ActiveSource } from "../components/SourcePanel";
import type { ActivityCatalogueMapping, ActivityDefinition, CompanyMatch, Taxonomy, ThemeDefinition } from "../types";
import { Button, Field, PageHeader, StateBlock } from "../ui";

const EXPOSURE_RANK: Record<string, number> = { pure_play: 3, significant: 2, minor: 1, none: 0 };

interface Props {
  onSendToExtraction?: (path: string, count: number) => void;
  pendingTaxonomyId?: string | null;
}

export function ThemeBuilder({ onSendToExtraction, pendingTaxonomyId }: Props = {}) {
  const [name, setName] = useState("Electrification");
  const [description, setDescription] = useState(
    "The shift of energy generation, transport, industry, and buildings from fossil fuels to electricity."
  );
  const [theme, setTheme] = useState<ThemeDefinition | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [universePath, setUniversePath] = useState<string | null>(null);
  const [companyCount, setCompanyCount] = useState(0);
  const [runId, setRunId] = useState<string | null>(null);
  const [results, setResults] = useState<CompanyMatch[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [useSampleIcio, setUseSampleIcio] = useState(false);
  const [taxonomies, setTaxonomies] = useState<Taxonomy[]>([]);
  const [selectedTaxonomyId, setSelectedTaxonomyId] = useState("");
  const [loadedTaxonomy, setLoadedTaxonomy] = useState<Taxonomy | null>(null);
  const [cataloguePath, setCataloguePath] = useState<string | null>(null);
  const [catalogueStatus, setCatalogueStatus] = useState("");
  const [catalogueMappings, setCatalogueMappings] = useState<ActivityCatalogueMapping[]>([]);
  const [mappingBusy, setMappingBusy] = useState(false);
  const [verdictFilter, setVerdictFilter] = useState("all");
  const [activityFilter, setActivityFilter] = useState("all");
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [sortBy, setSortBy] = useState<"confidence_desc" | "confidence_asc" | "exposure_desc" | "name_asc">("confidence_desc");
  const [sendBusy, setSendBusy] = useState(false);
  const [sendStatus, setSendStatus] = useState("");
  const [sentUniverse, setSentUniverse] = useState<{ path: string; count: number } | null>(null);
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);

  useEffect(() => {
    api
      .listTaxonomies()
      .then((res) => setTaxonomies((res as { taxonomies: Taxonomy[] }).taxonomies))
      .catch((err: Error) => setError(err.message));
  }, []);

  // A taxonomy sent over from the Taxonomy Library's "Use in Thematic
  // Universe" button arrives here as an id -- load it as soon as the
  // taxonomy list itself has loaded, same as picking it from the dropdown
  // by hand.
  useEffect(() => {
    if (!pendingTaxonomyId || taxonomies.length === 0) return;
    loadTaxonomyById(pendingTaxonomyId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingTaxonomyId, taxonomies]);

  async function decompose() {
    setBusy(true);
    setError(null);
    try {
      const drafted = (await api.decomposeTheme(name, description)) as ThemeDefinition;
      setTheme(drafted);
      setLoadedTaxonomy(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function loadTaxonomyById(taxonomyId: string) {
    const t = taxonomies.find((tax) => tax.taxonomy_id === taxonomyId);
    if (!t) return;
    setSelectedTaxonomyId(taxonomyId);
    setName(t.theme.name);
    setDescription(t.theme.description);
    setTheme(t.theme);
    setLoadedTaxonomy(t);
  }

  function loadFromTaxonomy() {
    loadTaxonomyById(selectedTaxonomyId);
  }

  function updateActivity(idx: number, patch: Partial<ActivityDefinition>) {
    if (!theme) return;
    const activities = theme.activities.map((a, i) => (i === idx ? { ...a, ...patch } : a));
    setTheme({ ...theme, activities });
  }

  function removeActivity(idx: number) {
    if (!theme) return;
    setTheme({ ...theme, activities: theme.activities.filter((_, i) => i !== idx) });
  }

  async function startRun() {
    if (!theme || !universePath) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.startThemeRun({
        theme,
        universe_path: universePath,
        use_sample_icio: useSampleIcio,
        ...(cataloguePath && catalogueMappings.length > 0
          ? { revenue_catalogue_path: cataloguePath, catalogue_mapping: catalogueMappings }
          : {}),
      });
      setRunId(res.run_id);
      setResults([]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function uploadCatalogue(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setCatalogueStatus("Uploading...");
    try {
      const res = await api.rawUpload(file);
      setCataloguePath(res.path);
      setCatalogueStatus(`Ready: ${file.name}`);
      setCatalogueMappings([]);
    } catch (err) {
      setCatalogueStatus(`Upload failed: ${(err as Error).message}`);
    }
  }

  async function suggestMapping() {
    if (!cataloguePath || !loadedTaxonomy) return;
    setMappingBusy(true);
    setError(null);
    try {
      const res = (await api.suggestCatalogueMapping({
        taxonomy_id: loadedTaxonomy.taxonomy_id,
        taxonomy_version: loadedTaxonomy.version,
        catalogue_path: cataloguePath,
      })) as { mappings: ActivityCatalogueMapping[] };
      setCatalogueMappings(res.mappings);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setMappingBusy(false);
    }
  }

  function updateMappingLabels(idx: number, labelsText: string) {
    setCatalogueMappings((prev) =>
      prev.map((m, i) => (i === idx ? { ...m, matched_labels: labelsText.split(",").map((s) => s.trim()).filter(Boolean) } : m))
    );
  }

  function activityName(activityId: string): string {
    return theme?.activities.find((a) => a.activity_id === activityId)?.name ?? activityId;
  }

  async function refreshResults() {
    try {
      if (!runId) return;
      const res = (await api.getThemeResults(runId)) as { results: CompanyMatch[] };
      setResults(res.results);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const filteredResults = useMemo(() => {
    let rows = results;
    if (verdictFilter !== "all") rows = rows.filter((m) => m.verdict === verdictFilter);
    if (activityFilter !== "all") rows = rows.filter((m) => m.activity_id === activityFilter);
    if (flaggedOnly) rows = rows.filter((m) => m.flagged_for_review);
    const sorted = [...rows];
    switch (sortBy) {
      case "confidence_desc":
        sorted.sort((a, b) => b.confidence - a.confidence);
        break;
      case "confidence_asc":
        sorted.sort((a, b) => a.confidence - b.confidence);
        break;
      case "exposure_desc":
        sorted.sort((a, b) => (EXPOSURE_RANK[b.exposure_estimate] ?? 0) - (EXPOSURE_RANK[a.exposure_estimate] ?? 0));
        break;
      case "name_asc":
        sorted.sort((a, b) => a.name.localeCompare(b.name));
        break;
    }
    return sorted;
  }, [results, verdictFilter, activityFilter, flaggedOnly, sortBy]);

  async function sendToExtraction() {
    setSendBusy(true);
    setSendStatus("");
    setSentUniverse(null);
    try {
      const seen = new Set<string>();
      const companies = filteredResults
        .filter((m) => (seen.has(m.company_id) ? false : (seen.add(m.company_id), true)))
        .map((m) => ({ company_id: m.company_id, name: m.name, ticker: m.ticker }));
      if (companies.length === 0) {
        setSendStatus("No companies match the current filters.");
        return;
      }
      const res = await api.universeFromCompanies(companies, `${theme?.name ?? "theme"}_screen`);
      setSendStatus(`Saved ${res.company_count} companies as a universe.`);
      setSentUniverse({ path: res.path, count: res.company_count });
    } catch (err) {
      setSendStatus(`Failed: ${(err as Error).message}`);
    } finally {
      setSendBusy(false);
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="Thematic Investment Universe Builder"
        description={
          <>
            Decompose a macro theme into checkable activities, then screen a company universe against each one using an
            Advocate / Opposing / Adjudicator agent pipeline with programmatically grounded citations.
          </>
        }
      />

      <section className="card">
        <h2>1. Define the theme</h2>
        <Field label="Macro theme name">
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Description">
          <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <Button onClick={decompose} disabled={busy}>
          Decompose into activities
        </Button>

        <p className="help-text mt-4">
          Or load an existing, versioned taxonomy from the Taxonomy Library instead of drafting a new one:
        </p>
        <div className="inline-fields">
          <Field label="Saved taxonomy">
            <select value={selectedTaxonomyId} onChange={(e) => setSelectedTaxonomyId(e.target.value)}>
              <option value="">Select a saved taxonomy...</option>
              {taxonomies.map((t) => (
                <option key={t.taxonomy_id} value={t.taxonomy_id}>
                  {t.name} (v{t.version}, {t.status})
                </option>
              ))}
            </select>
          </Field>
          <Button onClick={loadFromTaxonomy} disabled={!selectedTaxonomyId}>
            Load
          </Button>
        </div>
        {loadedTaxonomy && (
          <p className="status-text">
            Loaded {loadedTaxonomy.name} v{loadedTaxonomy.version} ({loadedTaxonomy.derivation_method},{" "}
            {loadedTaxonomy.status}) -- {loadedTaxonomy.theme.activities.length} activities. Edits below are local to
            this run and aren't saved back to the taxonomy; use the Taxonomy Library to save changes permanently.
          </p>
        )}
      </section>

      {theme && (
        <section className="card">
          <h2>2. Review &amp; edit activities</h2>
          {theme.activities.map((a, idx) => (
            <div className="activity-editor" key={a.activity_id}>
              <input value={a.name} onChange={(e) => updateActivity(idx, { name: e.target.value })} />
              <Field label="In scope">
                <textarea
                  rows={2}
                  value={a.in_scope_description}
                  onChange={(e) => updateActivity(idx, { in_scope_description: e.target.value })}
                />
              </Field>
              <Field label="Out of scope">
                <textarea
                  rows={2}
                  value={a.out_of_scope_description}
                  onChange={(e) => updateActivity(idx, { out_of_scope_description: e.target.value })}
                />
              </Field>
              <Field label="Seed keywords (comma-separated)">
                <input
                  value={a.seed_keywords.join(", ")}
                  onChange={(e) => updateActivity(idx, { seed_keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                />
              </Field>
              <Button variant="ghost" onClick={() => removeActivity(idx)}>
                Remove activity
              </Button>
            </div>
          ))}
        </section>
      )}

      {theme && (
        <section className="card">
          <h2>3. Choose the company universe</h2>
          <UniversePicker
            onResolved={(path, count) => {
              setUniversePath(path);
              setCompanyCount(count);
            }}
          />
          <label className="checkbox-label">
            <input type="checkbox" checked={useSampleIcio} onChange={(e) => setUseSampleIcio(e.target.checked)} />
            Enable indirect (input-output) exposure tier using the bundled sample dataset
          </label>
          <p className="help-text">
            Structural supply-chain exposure via OECD ICIO input-output propagation -- catches companies with no
            direct textual evidence but real economic linkage to the theme's core sectors. The sample dataset is
            illustrative only; for a real run, configure ARP_ICIO_MATRIX_PATH/ARP_ICIO_INDUSTRIES_PATH on the
            backend instead and leave this off.
          </p>

          <p className="help-text mt-4">
            Optional: a structured revenue/CapEx catalogue -- resolves exposure from hard disclosed numbers
            (catalogue match, then extraction from disclosures) before falling back to the qualitative debate above.
          </p>
          <input type="file" accept=".csv" onChange={uploadCatalogue} />
          {catalogueStatus && <p className="status-text">{catalogueStatus}</p>}
          {cataloguePath && !loadedTaxonomy && (
            <p className="help-text">Load a saved taxonomy above first -- mapping suggestion needs a taxonomy_id to reference.</p>
          )}
          {cataloguePath && loadedTaxonomy && (
            <Button onClick={suggestMapping} disabled={mappingBusy}>
              Suggest activity -&gt; catalogue-label mapping
            </Button>
          )}
          {catalogueMappings.length > 0 && (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Activity</th>
                    <th>Metric</th>
                    <th>Matched labels</th>
                    <th>Rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {catalogueMappings.map((m, idx) => (
                    <tr key={`${m.activity_id}-${m.metric}`}>
                      <td>{activityName(m.activity_id)}</td>
                      <td>{m.metric}</td>
                      <td>
                        <input value={m.matched_labels.join(", ")} onChange={(e) => updateMappingLabels(idx, e.target.value)} />
                      </td>
                      <td className="muted">{m.rationale}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <Button onClick={startRun} disabled={busy || !universePath}>
            Run screen against {companyCount || "..."} companies
          </Button>
        </section>
      )}

      {error && <StateBlock kind="error" message={error} />}

      {runId && (
        <section className="card">
          <h2>4. Run progress</h2>
          <RunProgress runId={runId} />
          <div className="toolbar">
            <Button onClick={refreshResults}>Refresh results</Button>
            <a href={api.exportRunCsvUrl(runId)} target="_blank" rel="noreferrer">
              Export CSV
            </a>
          </div>
          {results.length > 0 && (
            <>
              <div className="inline-fields">
                <select value={verdictFilter} onChange={(e) => setVerdictFilter(e.target.value)}>
                  <option value="all">All verdicts</option>
                  <option value="include">Include</option>
                  <option value="exclude">Exclude</option>
                  <option value="uncertain">Uncertain</option>
                </select>
                <select value={activityFilter} onChange={(e) => setActivityFilter(e.target.value)}>
                  <option value="all">All activities</option>
                  {theme?.activities.map((a) => (
                    <option key={a.activity_id} value={a.activity_id}>
                      {a.name}
                    </option>
                  ))}
                </select>
                <label className="checkbox-label">
                  <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
                  Flagged for review only
                </label>
                <select value={sortBy} onChange={(e) => setSortBy(e.target.value as typeof sortBy)}>
                  <option value="confidence_desc">Sort: confidence (high to low)</option>
                  <option value="confidence_asc">Sort: confidence (low to high)</option>
                  <option value="exposure_desc">Sort: exposure (strongest first)</option>
                  <option value="name_asc">Sort: company name (A-Z)</option>
                </select>
              </div>
              <p className="muted">
                Showing {filteredResults.length} of {results.length} results.
              </p>
              <div className="toolbar">
                <Button onClick={sendToExtraction} disabled={sendBusy || filteredResults.length === 0}>
                  Save {new Set(filteredResults.map((m) => m.company_id)).size} companies as a universe
                </Button>
                {sentUniverse && (
                  <Button onClick={() => onSendToExtraction?.(sentUniverse.path, sentUniverse.count)}>
                    Go to Extraction Engine &rarr;
                  </Button>
                )}
              </div>
              {sendStatus && <p className="status-text">{sendStatus}</p>}
            </>
          )}
          {filteredResults.length > 0 && (
            <div className="split-review">
              <div className="split-review-main">
                <div className="table-wrap">
                    <table className="data-table">
                    <thead>
                      <tr>
                        <th>Company</th>
                        <th>Activity</th>
                        <th>Verdict</th>
                        <th>Exposure</th>
                        <th>Confidence</th>
                        <th>Source</th>
                        <th>Structural</th>
                        <th>Review</th>
                      </tr>
                    </thead>
                    <tbody>
                    {filteredResults.map((m) => {
                      const key = `${m.company_id}:${m.activity_id}`;
                      const io = m.indirect_exposure;
                      const revenue = m.revenue_exposure?.revenue;
                      return (
                        <Fragment key={key}>
                          <tr onClick={() => setExpanded(expanded === key ? null : key)} className="clickable-row">
                            <td>{m.name} {m.ticker && <span className="muted">({m.ticker})</span>}</td>
                            <td>{m.activity_name}</td>
                            <td><VerdictBadge verdict={m.verdict} /></td>
                            <td>{m.exposure_estimate}</td>
                            <td><ConfidenceBadge value={m.confidence} /></td>
                            <td>
                              {revenue && revenue.value_pct != null ? (
                                <span className={revenue.source === "catalogue" ? "badge badge-high" : "badge badge-mid"}>
                                  {revenue.source} ({(revenue.value_pct * 100).toFixed(1)}%)
                                </span>
                              ) : (
                                <span className="muted">qualitative</span>
                              )}
                            </td>
                            <td>
                              {io ? (
                                <span className="muted">
                                  &uarr;{Math.round(io.upstream_exposure * 100)}% &darr;{Math.round(io.downstream_exposure * 100)}%
                                </span>
                              ) : (
                                ""
                              )}
                            </td>
                            <td>{m.flagged_for_review ? "⚑" : ""}</td>
                          </tr>
                          {expanded === key && (
                            <tr>
                              <td colSpan={8} className="detail-cell">
                                <p><strong>Rationale:</strong> {m.adjudicator_rationale}</p>
                                <p><strong>Citations:</strong></p>
                                <CitationList citations={m.citations} onOpenSource={setActiveSource} />
                                {m.revenue_exposure && (
                                  <>
                                    <p><strong>Revenue/CapEx exposure:</strong></p>
                                    <ul>
                                      <li>
                                        Revenue: {m.revenue_exposure.revenue.value_pct != null ? `${(m.revenue_exposure.revenue.value_pct * 100).toFixed(1)}%` : "unresolved"}
                                        {" "}({m.revenue_exposure.revenue.source})
                                        {m.revenue_exposure.revenue.matched_catalogue_labels.length > 0 &&
                                          ` -- ${m.revenue_exposure.revenue.matched_catalogue_labels.join(", ")}`}
                                      </li>
                                      <li>
                                        CapEx: {m.revenue_exposure.capex.value_pct != null ? `${(m.revenue_exposure.capex.value_pct * 100).toFixed(1)}%` : "unresolved"}
                                        {" "}({m.revenue_exposure.capex.source})
                                        {m.revenue_exposure.capex.matched_catalogue_labels.length > 0 &&
                                          ` -- ${m.revenue_exposure.capex.matched_catalogue_labels.join(", ")}`}
                                      </li>
                                      <li className="muted">Sector-relevant to this company: {m.revenue_exposure.sector_relevant ? "yes" : "no"}</li>
                                    </ul>
                                  </>
                                )}
                                {io && (
                                  <>
                                    <p>
                                      <strong>Indirect (structural) exposure:</strong> {io.isic_label ?? io.isic_code}{" "}
                                      {io.core_sector && <span className="badge badge-high">core sector</span>}
                                    </p>
                                    <ul>
                                      <li>Upstream exposure: {(io.upstream_exposure * 100).toFixed(1)}% -- share of this industry's total input requirement traceable to the activity's core sectors</li>
                                      <li>Downstream exposure: {(io.downstream_exposure * 100).toFixed(1)}% -- share of this industry's output propagation landing in the activity's core sectors</li>
                                      <li className="muted">Computed from {io.icio_edition}</li>
                                    </ul>
                                  </>
                                )}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                    </tbody>
                  </table>
                </div>
              </div>
              <SourcePanel source={activeSource} onClose={() => setActiveSource(null)} />
            </div>
          )}
        </section>
      )}
    </div>
  );
}
