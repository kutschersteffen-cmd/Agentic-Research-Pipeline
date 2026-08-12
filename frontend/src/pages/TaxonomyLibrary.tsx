import { Fragment, useEffect, useState } from "react";
import { api } from "../api/client";
import { ActivityEditorTable } from "../components/ActivityEditorTable";
import { SourceDiscoveryPanel } from "../components/SourceDiscoveryPanel";
import { InspectorModal } from "../components/InspectorModal";
import { UniversePicker } from "../components/UniversePicker";
import type {
  ActivityDefinition,
  DerivationMethod,
  HoldingsOverlapResult,
  SourceCandidate,
  Taxonomy,
  TaxonomyComparison,
  TaxonomyRef,
  ThemeDefinition,
} from "../types";

const METHOD_LABELS: Record<DerivationMethod, string> = {
  llm_draft: "LLM draft (freeform)",
  industry_anchored: "Industry-anchored (ISIC / input-output)",
  authority_source: "Authority source (IEA, EU taxonomy, standards bodies, ...)",
  etf_index_holdings: "ETF / index holdings (bottom-up)",
  news_transcript_mining: "News & earnings-call transcript mining",
  empirical: "Empirical (Extraction Engine readings)",
  merged: "Merged from existing taxonomies",
  manual: "Manual / hand-authored",
};

const CREATABLE_METHODS: DerivationMethod[] = [
  "llm_draft",
  "industry_anchored",
  "authority_source",
  "etf_index_holdings",
  "news_transcript_mining",
  "empirical",
];

const SUB_TABS = [
  { id: "library", label: "Library" },
  { id: "new", label: "New taxonomy" },
  { id: "compare", label: "Compare & merge" },
  { id: "universe", label: "Universe builder" },
  { id: "overlap", label: "ETF holdings overlap" },
] as const;

export function TaxonomyLibrary() {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>("library");
  const [taxonomies, setTaxonomies] = useState<Taxonomy[]>([]);

  async function refreshLibrary() {
    const res = (await api.listTaxonomies()) as { taxonomies: Taxonomy[] };
    setTaxonomies(res.taxonomies);
  }

  useEffect(() => {
    refreshLibrary();
  }, []);

  return (
    <div className="page">
      <h2>Taxonomy Library</h2>
      <p className="help-text">
        Reusable, versioned thematic taxonomies with provenance -- draft one from an authoritative source, an
        existing ETF/index's holdings, news &amp; transcripts, or the Extraction Engine's own readings, then review,
        edit, ratify, compare and merge.
      </p>
      <nav className="sub-nav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      {sub === "library" && <LibraryView taxonomies={taxonomies} onChange={refreshLibrary} />}
      {sub === "new" && <NewTaxonomyWizard onCreated={refreshLibrary} />}
      {sub === "compare" && <CompareMergeView taxonomies={taxonomies} onSaved={refreshLibrary} />}
      {sub === "universe" && <UniverseBuilderView />}
      {sub === "overlap" && <OverlapView />}
    </div>
  );
}

// --- Library: list + detail edit/ratify -----------------------------------

function LibraryView({ taxonomies, onChange }: { taxonomies: Taxonomy[]; onChange: () => void }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [activities, setActivities] = useState<ActivityDefinition[]>([]);
  const [notes, setNotes] = useState("Manual edit.");
  const [ratifiedBy, setRatifiedBy] = useState("");
  const [useSampleIcio, setUseSampleIcio] = useState(false);
  const [useSampleStandards, setUseSampleStandards] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function open(t: Taxonomy) {
    setOpenId(openId === t.taxonomy_id ? null : t.taxonomy_id);
    setActivities(t.theme.activities);
    setError(null);
  }

  async function saveVersion(t: Taxonomy) {
    setBusy(true);
    setError(null);
    try {
      await api.newTaxonomyVersion(t.taxonomy_id, { theme: { ...t.theme, activities }, source_notes: notes });
      onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function ratify(t: Taxonomy) {
    if (!ratifiedBy) return;
    setBusy(true);
    setError(null);
    try {
      await api.ratifyTaxonomy(t.taxonomy_id, { version: t.version, ratified_by: ratifiedBy });
      onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function mapStandards(t: Taxonomy) {
    setBusy(true);
    setError(null);
    try {
      await api.mapStandards(t.taxonomy_id, {
        version: t.version,
        use_sample_icio: useSampleIcio,
        use_sample_standards: useSampleStandards,
      });
      onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (taxonomies.length === 0) {
    return <p className="help-text">No taxonomies yet -- draft one under "New taxonomy".</p>;
  }

  return (
    <section className="card">
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Method</th>
            <th>Version</th>
            <th>Status</th>
            <th>Activities</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {taxonomies.map((t) => (
            <Fragment key={t.taxonomy_id}>
              <tr className="clickable-row" onClick={() => open(t)}>
                <td>{t.name}</td>
                <td>{METHOD_LABELS[t.derivation_method]}</td>
                <td>v{t.version}</td>
                <td>
                  <span className={t.status === "ratified" ? "badge badge-high" : "badge badge-neutral"}>{t.status}</span>
                </td>
                <td>{t.theme.activities.length}</td>
                <td>{openId === t.taxonomy_id ? "▲" : "▼"}</td>
              </tr>
              {openId === t.taxonomy_id && (
                <tr>
                  <td colSpan={6} className="detail-cell">
                    <p className="muted">{t.source_notes}</p>
                    <ActivityEditorTable activities={activities} onChange={setActivities} />
                    <label className="field-label">Version notes</label>
                    <input value={notes} onChange={(e) => setNotes(e.target.value)} />
                    <div className="toolbar">
                      <button onClick={() => saveVersion(t)} disabled={busy}>
                        Save as new version
                      </button>
                    </div>
                    {t.status === "draft" && (
                      <div className="toolbar">
                        <input
                          placeholder="Ratified by (name)"
                          value={ratifiedBy}
                          onChange={(e) => setRatifiedBy(e.target.value)}
                        />
                        <button onClick={() => ratify(t)} disabled={busy || !ratifiedBy}>
                          Ratify v{t.version}
                        </button>
                      </div>
                    )}
                    <div className="toolbar">
                      <label className="checkbox-label">
                        <input type="checkbox" checked={useSampleIcio} onChange={(e) => setUseSampleIcio(e.target.checked)} />
                        sample ICIO (for ISIC classification)
                      </label>
                      <label className="checkbox-label">
                        <input type="checkbox" checked={useSampleStandards} onChange={(e) => setUseSampleStandards(e.target.checked)} />
                        sample NACE/NAICS/SIC/GICS reference data
                      </label>
                      <button onClick={() => mapStandards(t)} disabled={busy}>
                        Map to NACE / NAICS / SIC / GICS
                      </button>
                      <a href={api.standardsCsvUrl(t.taxonomy_id)} target="_blank" rel="noreferrer">
                        Export standards CSV
                      </a>
                    </div>
                    <p className="help-text">
                      Uses configured ARP_NACE_CROSSWALK_PATH / ARP_NAICS_CROSSWALK_PATH / ARP_SIC_CROSSWALK_PATH /
                      ARP_GICS_REFERENCE_PATH by default; check the sample boxes to use the bundled illustrative data
                      instead. Saves a new taxonomy version. <strong>The bundled GICS data below sector level is an
                      unverified, LLM-reconstructed approximation of the licensed MSCI/S&amp;P structure</strong> --
                      fine for testing this pipeline, not for citing. Supply a verified ARP_GICS_REFERENCE_PATH
                      before relying on sub-industry-level GICS output.
                    </p>
                    {error && <p className="error-text">{error}</p>}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// --- New taxonomy wizard ----------------------------------------------------

function NewTaxonomyWizard({ onCreated }: { onCreated: () => void }) {
  const [method, setMethod] = useState<DerivationMethod>("llm_draft");
  const [name, setName] = useState("Electrification");
  const [description, setDescription] = useState("");
  const [useSampleIcio, setUseSampleIcio] = useState(false);
  const [mineNews, setMineNews] = useState(true);
  const [sampleSize, setSampleSize] = useState(25);
  const [universePath, setUniversePath] = useState<string | null>(null);
  const [holdingsPath, setHoldingsPath] = useState<string | null>(null);
  const [holdingsStatus, setHoldingsStatus] = useState("");

  const [authorityCandidates, setAuthorityCandidates] = useState<SourceCandidate[]>([]);
  const [selectedAuthority, setSelectedAuthority] = useState<Set<string>>(new Set());

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Taxonomy | null>(null);
  const [draftActivities, setDraftActivities] = useState<ActivityDefinition[]>([]);

  async function discoverAuthoritySources() {
    setBusy(true);
    setError(null);
    try {
      const res = (await api.discoverTaxonomySources(name)) as { authority_sources: SourceCandidate[] };
      setAuthorityCandidates(res.authority_sources);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onHoldingsFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setHoldingsStatus("Uploading...");
    try {
      const res = await api.rawUpload(file);
      setHoldingsPath(res.path);
      setHoldingsStatus(`Ready: ${file.name}`);
    } catch (err) {
      setHoldingsStatus(`Upload failed: ${(err as Error).message}`);
    }
  }

  function toggleAuthority(candidateId: string) {
    setSelectedAuthority((prev) => {
      const next = new Set(prev);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });
  }

  async function draftTaxonomy() {
    setBusy(true);
    setError(null);
    try {
      const authorityUrls = authorityCandidates.filter((c) => selectedAuthority.has(c.candidate_id)).map((c) => c.url);
      const payload = {
        name,
        description,
        derivation_method: method,
        use_sample_icio: useSampleIcio,
        authority_urls: authorityUrls,
        universe_path: universePath,
        sample_size: sampleSize,
        mine_news: mineNews,
        holdings_path: holdingsPath,
      };
      const created = (await api.createTaxonomy(payload)) as Taxonomy;
      setDraft(created);
      setDraftActivities(created.theme.activities);
      onCreated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveDraftEdits() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      const updated = (await api.newTaxonomyVersion(draft.taxonomy_id, {
        theme: { ...draft.theme, activities: draftActivities },
        source_notes: "Manual edit after review.",
      })) as Taxonomy;
      setDraft(updated);
      setDraftActivities(updated.theme.activities);
      onCreated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="card">
        <h3>1. Method &amp; theme</h3>
        <label className="field-label">Derivation method</label>
        <select value={method} onChange={(e) => setMethod(e.target.value as DerivationMethod)}>
          {CREATABLE_METHODS.map((m) => (
            <option key={m} value={m}>
              {METHOD_LABELS[m]}
            </option>
          ))}
        </select>
        <label className="field-label">Theme name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} />
        <label className="field-label">Description</label>
        <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />

        {method === "industry_anchored" && (
          <label className="checkbox-label">
            <input type="checkbox" checked={useSampleIcio} onChange={(e) => setUseSampleIcio(e.target.checked)} />
            Anchor against the bundled sample ISIC/OECD-ICIO reference list
          </label>
        )}

        {method === "authority_source" && (
          <div className="inline-block">
            <button onClick={discoverAuthoritySources} disabled={busy || !name}>
              Discover authority sources
            </button>
            <SourceDiscoveryPanel candidates={authorityCandidates} selected={selectedAuthority} onToggle={toggleAuthority} />
          </div>
        )}

        {method === "etf_index_holdings" && (
          <>
            <label className="field-label">Fund/index holdings export (CSV)</label>
            <input type="file" accept=".csv" onChange={onHoldingsFile} />
            {holdingsStatus && <p className="status-text">{holdingsStatus}</p>}
          </>
        )}

        {(method === "empirical" || method === "news_transcript_mining") && (
          <>
            <UniversePicker onResolved={(path) => setUniversePath(path)} />
            {method === "empirical" && (
              <>
                <label className="field-label">Sample size</label>
                <input type="number" value={sampleSize} onChange={(e) => setSampleSize(Number(e.target.value))} />
              </>
            )}
            {method === "news_transcript_mining" && (
              <label className="checkbox-label">
                <input type="checkbox" checked={mineNews} onChange={(e) => setMineNews(e.target.checked)} />
                Also search news for activity mentions (in addition to any selected company universe)
              </label>
            )}
          </>
        )}

        <button onClick={draftTaxonomy} disabled={busy || !name}>
          Draft &amp; save taxonomy
        </button>
        {error && <p className="error-text">{error}</p>}
      </section>

      {draft && (
        <section className="card">
          <h3>2. Review &amp; adjust the drafted taxonomy</h3>
          <p className="muted">
            {draft.name} v{draft.version} -- {draft.source_notes}
          </p>
          <ActivityEditorTable activities={draftActivities} onChange={setDraftActivities} />
          <button onClick={saveDraftEdits} disabled={busy}>
            Save adjustments as new version
          </button>
        </section>
      )}
    </>
  );
}

// --- Compare & merge ---------------------------------------------------------

function CompareMergeView({ taxonomies, onSaved }: { taxonomies: Taxonomy[]; onSaved: () => void }) {
  const [idA, setIdA] = useState("");
  const [idB, setIdB] = useState("");
  const [comparison, setComparison] = useState<TaxonomyComparison | null>(null);
  const [mergeName, setMergeName] = useState("");
  const [mergeDescription, setMergeDescription] = useState("");
  const [mergeDraft, setMergeDraft] = useState<{ theme: ThemeDefinition; source_notes: string } | null>(null);
  const [mergeActivities, setMergeActivities] = useState<ActivityDefinition[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const taxA = taxonomies.find((t) => t.taxonomy_id === idA);
  const taxB = taxonomies.find((t) => t.taxonomy_id === idB);

  function activityName(id: string): string {
    const fromA = taxA?.theme.activities.find((a) => a.activity_id === id);
    const fromB = taxB?.theme.activities.find((a) => a.activity_id === id);
    return fromA?.name ?? fromB?.name ?? id;
  }

  function refFor(id: string): TaxonomyRef {
    return { taxonomy_id: id, version: null };
  }

  async function compare() {
    if (!idA || !idB) return;
    setBusy(true);
    setError(null);
    setComparison(null);
    try {
      const result = (await api.compareTaxonomies({ a: refFor(idA), b: refFor(idB) })) as TaxonomyComparison;
      setComparison(result);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function merge() {
    if (!idA || !idB || !mergeName) return;
    setBusy(true);
    setError(null);
    setMergeDraft(null);
    try {
      const result = (await api.mergeTaxonomies({
        refs: [refFor(idA), refFor(idB)],
        name: mergeName,
        description: mergeDescription,
      })) as { theme: ThemeDefinition; source_notes: string };
      setMergeDraft(result);
      setMergeActivities(result.theme.activities);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveMerge() {
    if (!mergeDraft) return;
    setBusy(true);
    setError(null);
    try {
      await api.createTaxonomy({
        name: mergeName,
        description: mergeDescription,
        derivation_method: "merged",
        theme: { ...mergeDraft.theme, activities: mergeActivities },
        source_notes: mergeDraft.source_notes,
      });
      setMergeDraft(null);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h3>Compare two taxonomies</h3>
      <div className="inline-fields">
        <select value={idA} onChange={(e) => setIdA(e.target.value)}>
          <option value="">Taxonomy A</option>
          {taxonomies.map((t) => (
            <option key={t.taxonomy_id} value={t.taxonomy_id}>
              {t.name} (v{t.version})
            </option>
          ))}
        </select>
        <select value={idB} onChange={(e) => setIdB(e.target.value)}>
          <option value="">Taxonomy B</option>
          {taxonomies.map((t) => (
            <option key={t.taxonomy_id} value={t.taxonomy_id}>
              {t.name} (v{t.version})
            </option>
          ))}
        </select>
      </div>
      <button onClick={compare} disabled={busy || !idA || !idB || idA === idB}>
        Compare
      </button>

      {comparison && (
        <div className="detail-cell">
          <p>
            <strong>Unique to A:</strong> {comparison.unique_to_a.map(activityName).join(", ") || "none"}
          </p>
          <p>
            <strong>Unique to B:</strong> {comparison.unique_to_b.map(activityName).join(", ") || "none"}
          </p>
          <p>
            <strong>Likely duplicates:</strong>
          </p>
          <ul>
            {comparison.likely_duplicates.map((d, i) => (
              <li key={i}>
                {activityName(d.activity_a_id)} &harr; {activityName(d.activity_b_id)} -- {d.similarity_note}
              </li>
            ))}
            {comparison.likely_duplicates.length === 0 && <li className="muted">none found</li>}
          </ul>
        </div>
      )}

      <h3>Merge into a new taxonomy</h3>
      <label className="field-label">Merged taxonomy name</label>
      <input value={mergeName} onChange={(e) => setMergeName(e.target.value)} />
      <label className="field-label">Description</label>
      <input value={mergeDescription} onChange={(e) => setMergeDescription(e.target.value)} />
      <button onClick={merge} disabled={busy || !idA || !idB || idA === idB || !mergeName}>
        Draft merge
      </button>
      {error && <p className="error-text">{error}</p>}

      {mergeDraft && (
        <div className="detail-cell">
          <p className="muted">{mergeDraft.source_notes}</p>
          <ActivityEditorTable activities={mergeActivities} onChange={setMergeActivities} />
          <button onClick={saveMerge} disabled={busy}>
            Save merged taxonomy
          </button>
        </div>
      )}
    </section>
  );
}

// --- Universe builder ---------------------------------------------------------

function UniverseBuilderView() {
  const [query, setQuery] = useState("S&P 500");
  const [funds, setFunds] = useState<SourceCandidate[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ path: string; company_count: number; sample: unknown[] } | null>(null);

  async function search() {
    setBusy(true);
    setError(null);
    try {
      const res = (await api.discoverTaxonomySources(query)) as { thematic_funds: SourceCandidate[] };
      setFunds(res.thematic_funds);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function onHoldingsFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.universeFromHoldings(file);
      setResult(res);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="card">
        <h3>1. Find sector/index funds (tool-assisted)</h3>
        <label className="field-label">Sector or index name</label>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. S&amp;P 500, US technology sector" />
        <button onClick={search} disabled={busy || !query}>
          Search
        </button>
        <SourceDiscoveryPanel candidates={funds} selected={selected} onToggle={toggle} />
        <p className="help-text">
          Fund-provider export formats aren't standardized and several finance domains are unreachable for automated
          fetching, so download the constituents CSV from the fund's site, then upload it below to build the
          company universe.
        </p>
      </section>

      <section className="card">
        <h3>2. Build a company universe from a holdings export</h3>
        <input type="file" accept=".csv" onChange={onHoldingsFile} disabled={busy} />
        {error && <p className="error-text">{error}</p>}
        {result && (
          <>
            <p className="status-text">
              Built {result.company_count} companies -- saved at <code>{result.path}</code>. Use this path as the
              universe for the empirical/news-mining derivation methods or the Thematic Universe Builder.
            </p>
            <table className="data-table">
              <thead>
                <tr>
                  <th>company_id</th>
                  <th>name</th>
                  <th>ticker</th>
                  <th>sector</th>
                </tr>
              </thead>
              <tbody>
                {(result.sample as Record<string, unknown>[]).map((c, i) => (
                  <tr key={i}>
                    <td>{String(c.company_id ?? "")}</td>
                    <td>{String(c.name ?? "")}</td>
                    <td>{String(c.ticker ?? "")}</td>
                    <td>{String(c.sector ?? "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    </>
  );
}

// --- ETF holdings overlap ------------------------------------------------------

interface FundEntry {
  name: string;
  path: string;
  file: File;
}

function OverlapView() {
  const [funds, setFunds] = useState<FundEntry[]>([]);
  const [fundName, setFundName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<HoldingsOverlapResult | null>(null);
  const [inspecting, setInspecting] = useState<{ name: string; text: string } | null>(null);

  async function addFund(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !fundName) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.rawUpload(file);
      setFunds((prev) => [...prev, { name: fundName, path: res.path, file }]);
      setFundName("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  function removeFund(idx: number) {
    setFunds((prev) => prev.filter((_, i) => i !== idx));
  }

  async function inspect(entry: FundEntry) {
    const text = await entry.file.text();
    setInspecting({ name: entry.name, text });
  }

  async function compute() {
    if (funds.length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const fundMap = Object.fromEntries(funds.map((f) => [f.name, f.path]));
      const res = (await api.computeOverlap(fundMap)) as HoldingsOverlapResult;
      setResult(res);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="card">
        <h3>1. Select ETFs/indices to compare</h3>
        <div className="inline-fields">
          <input placeholder="Fund display name" value={fundName} onChange={(e) => setFundName(e.target.value)} />
          <input type="file" accept=".csv" onChange={addFund} disabled={busy || !fundName} />
        </div>
        {funds.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Fund</th>
                <th>File</th>
                <th></th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {funds.map((f, idx) => (
                <tr key={idx}>
                  <td>{f.name}</td>
                  <td>{f.file.name}</td>
                  <td>
                    <button className="link-button" onClick={() => inspect(f)}>
                      Inspect holdings
                    </button>
                  </td>
                  <td>
                    <button className="link-button" onClick={() => removeFund(idx)}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button onClick={compute} disabled={busy || funds.length < 2}>
          Compute holdings overlap
        </button>
        {error && <p className="error-text">{error}</p>}
        {inspecting && (
          <InspectorModal title={`${inspecting.name} holdings (raw)`} text={inspecting.text} onClose={() => setInspecting(null)} />
        )}
      </section>

      {result && (
        <section className="card">
          <h3>2. Overlap</h3>
          <p>
            <strong>Core holdings (in every fund):</strong> {result.core_tickers.join(", ") || "none"}
          </p>
          <p>
            <strong>Union of holdings:</strong> {result.union_tickers.length} tickers
          </p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Fund pair</th>
                <th>Weight-adjusted overlap</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(result.pairwise_overlap_pct).map(([pair, pct]) => (
                <tr key={pair}>
                  <td>{pair.replace("|", " vs ")}</td>
                  <td>{pct.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h4>Holdings inspection</h4>
          <table className="data-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Held by</th>
              </tr>
            </thead>
            <tbody>
              {result.union_tickers.map((ticker) => (
                <tr key={ticker}>
                  <td>{ticker}</td>
                  <td>{(result.ticker_presence[ticker] ?? []).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
