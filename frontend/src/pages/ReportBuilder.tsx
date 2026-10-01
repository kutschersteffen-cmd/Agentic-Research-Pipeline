import { when } from "../lib/runs";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Modal } from "../components/Modal";
import type {
  AudienceLevel,
  ChartType,
  ContentItem,
  Finding,
  OutputFormat,
  QuantitativeDataset,
  ReportManifest,
  ReportPlan,
  ReportSection,
  SectionLayoutHint,
  Storyline,
  StorylineSlide,
  TemplateStyleProfile,
  Tone,
} from "../types";
import { CHART_TYPES } from "../types";
import { activatable } from "../lib/activatable";

const AUDIENCE_LEVELS: AudienceLevel[] = ["executive", "technical", "general"];
const TONES: Tone[] = ["formal", "conversational", "persuasive", "neutral_analytical"];
const OUTPUT_FORMATS: OutputFormat[] = ["pptx", "docx", "pdf", "house_deck"];
const FORMAT_LABELS: Partial<Record<OutputFormat, string>> = { house_deck: "House deck (PDF + PPTX)" };
const LAYOUT_HINTS: SectionLayoutHint[] = ["standard", "chart_focus", "text_only", "section_header"];

function narrativeToText(narrative: ContentItem[]): string {
  return narrative.map((n) => n.text).join("\n");
}

function textToNarrative(text: string): ContentItem[] {
  return text.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => ({ text: line, bullet: true }));
}

/** `items` with entry `index` swapped one step by `delta`, or null when that would leave the list. */
function moved<T>(items: T[], index: number, delta: number): T[] | null {
  const target = index + delta;
  if (target < 0 || target >= items.length) return null;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

function groupBySlide(findings: Finding[]): [number, Finding[]][] {
  const groups = new Map<number, Finding[]>();
  for (const f of findings) groups.set(f.slide, [...(groups.get(f.slide) ?? []), f]);
  return [...groups.entries()].sort((a, b) => a[0] - b[0]);
}

export function ReportBuilder() {
  // Request inputs
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [notes, setNotes] = useState("");
  const [datasets, setDatasets] = useState<QuantitativeDataset[]>([]);
  const [template, setTemplate] = useState<TemplateStyleProfile | null>(null);
  const [templates, setTemplates] = useState<TemplateStyleProfile[]>([]);
  const [audienceLevel, setAudienceLevel] = useState<AudienceLevel>("general");
  const [tone, setTone] = useState<Tone>("neutral_analytical");
  const [audienceDescription, setAudienceDescription] = useState("");
  const [focusAreas, setFocusAreas] = useState("");
  const [outputFormat, setOutputFormat] = useState<OutputFormat>("pptx");
  const [deckTheme, setDeckTheme] = useState<"light" | "dark">("light");
  const [deckDensity, setDeckDensity] = useState<"committee" | "present">("committee");
  const [targetLength, setTargetLength] = useState<string>("");
  const [maxBullets, setMaxBullets] = useState(6);
  const [includeTitleSlide, setIncludeTitleSlide] = useState(true);
  const [includeAgendaSlide, setIncludeAgendaSlide] = useState(true);
  const [includeAppendix, setIncludeAppendix] = useState(false);
  const [freeInstructions, setFreeInstructions] = useState("");

  // Generation state
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manifest, setManifest] = useState<ReportManifest | null>(null);
  const [plan, setPlan] = useState<ReportPlan | null>(null);
  const [storyline, setStoryline] = useState<Storyline | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [reports, setReports] = useState<ReportManifest[]>([]);

  // Preview state -- a docked thumbnail strip + click-to-enlarge modal for
  // whichever completed report was last opened for preview.
  const [previewReportId, setPreviewReportId] = useState<string | null>(null);
  const [previewTitle, setPreviewTitle] = useState<string>("");
  const [previewPageCount, setPreviewPageCount] = useState(0);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [enlargedPage, setEnlargedPage] = useState<number | null>(null);

  useEffect(() => {
    refreshReports();
    api.listReportTemplates().then((r) => setTemplates(r.templates)).catch(() => undefined);
  }, []);

  async function refreshReports() {
    try {
      const res = await api.listReports();
      setReports(res.reports);
    } catch {
      /* best-effort */
    }
  }

  async function handleDatasetUpload(file: File) {
    setError(null);
    try {
      const ds = await api.uploadReportDataset(file);
      setDatasets((prev) => [...prev, ds]);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function handleTemplateUpload(file: File) {
    setError(null);
    try {
      const style = await api.uploadReportTemplate(file);
      setTemplate(style);
      setTemplates((prev) => [style, ...prev]);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function draftPlan() {
    if (!title.trim() || !notes.trim()) {
      setError("Title and qualitative notes are required.");
      return;
    }
    setBusy(true);
    setError(null);
    setPlan(null);
    setStoryline(null);
    setFindings([]);
    try {
      const req = {
        title,
        goal,
        qualitative_notes: notes,
        datasets,
        audience: {
          level: audienceLevel,
          tone,
          description: audienceDescription,
          focus_areas: focusAreas.split(",").map((s) => s.trim()).filter(Boolean),
        },
        layout: {
          output_format: outputFormat,
          theme: deckTheme,
          density: deckDensity,
          target_length: targetLength ? Number(targetLength) : null,
          max_bullets_per_slide: maxBullets,
          include_title_slide: includeTitleSlide,
          include_agenda_slide: includeAgendaSlide,
          include_appendix: includeAppendix,
          section_order_hint: [],
          free_instructions: freeInstructions,
        },
        template_id: template?.template_id ?? null,
      };
      const m = await api.createReport(req, false);
      setManifest(m);
      if (m.output_format === "house_deck") setStoryline(await api.getStoryline(m.report_id));
      else setPlan(await api.getReportPlan(m.report_id));
      refreshReports();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function openReport(reportId: string) {
    setError(null);
    try {
      const m = await api.getReport(reportId);
      setManifest(m);
      const house = m.output_format === "house_deck";
      setPlan(house ? null : await api.getReportPlan(reportId).catch(() => null));
      setStoryline(house ? await api.getStoryline(reportId).catch(() => null) : null);
      setFindings(house ? (await api.getReportFindings(reportId)).findings : []);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function savePlan() {
    if (!manifest || !plan) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api.updateReportPlan(manifest.report_id, plan);
      setPlan(saved);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function render() {
    if (!manifest) return;
    setBusy(true);
    setError(null);
    try {
      const m = await api.renderReport(manifest.report_id);
      setManifest(m);
      refreshReports();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function updateSection(index: number, patch: Partial<ReportSection>) {
    if (!plan) return;
    const sections = plan.sections.map((s, i) => (i === index ? { ...s, ...patch } : s));
    setPlan({ ...plan, sections });
  }

  function moveSection(index: number, delta: number) {
    const sections = plan && moved(plan.sections, index, delta);
    if (plan && sections) setPlan({ ...plan, sections });
  }

  function removeSection(index: number) {
    if (!plan) return;
    setPlan({ ...plan, sections: plan.sections.filter((_, i) => i !== index) });
  }

  async function saveStoryline() {
    if (!manifest || !storyline) return;
    setBusy(true);
    setError(null);
    try {
      setStoryline(await api.updateStoryline(manifest.report_id, storyline));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function approveAndBuild() {
    if (!manifest || !storyline) return;
    setBusy(true);
    setError(null);
    try {
      if (!storyline.approved) await api.updateStoryline(manifest.report_id, storyline); // build exactly what is on screen
      const m = await api.approveStoryline(manifest.report_id);
      setManifest(m);
      setStoryline({ ...storyline, approved: true });
      setFindings((await api.getReportFindings(m.report_id)).findings);
      refreshReports();
    } catch (err) {
      setError((err as Error).message);
      api.getReport(manifest.report_id).then(setManifest).catch(() => undefined);
      api.getStoryline(manifest.report_id).then(setStoryline).catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  function updateSlide(index: number, patch: Partial<StorylineSlide>) {
    if (!storyline) return;
    setStoryline({ ...storyline, slides: storyline.slides.map((s, i) => (i === index ? { ...s, ...patch } : s)) });
  }

  function moveSlide(index: number, delta: number) {
    const slides = storyline && moved(storyline.slides, index, delta);
    if (storyline && slides) setStoryline({ ...storyline, slides });
  }

  async function openPreview(reportId: string, title: string) {
    setPreviewReportId(reportId);
    setPreviewTitle(title);
    setEnlargedPage(null);
    setPreviewError(null);
    setPreviewLoading(true);
    setPreviewPageCount(0);
    try {
      const res = await api.getReportPreview(reportId);
      setPreviewPageCount(res.page_count);
    } catch (err) {
      setPreviewError((err as Error).message);
    } finally {
      setPreviewLoading(false);
    }
  }

  function closePreview() {
    setPreviewReportId(null);
    setPreviewPageCount(0);
    setEnlargedPage(null);
  }

  return (
    <div className={previewReportId ? "page split-review" : "page"} style={previewReportId ? { maxWidth: 1560 } : undefined}>
    <div className={previewReportId ? "split-review-main page-body" : "page-body"}>
      <h1>Presentations &amp; Reports</h1>
      <p className="help-text">Draft a report plan from your notes and data, edit it, then render it to PowerPoint, Word or PDF.</p>

      <section className="card">
        <h2>1. Content</h2>
        <label className="field-label">
          Title
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Electrification Thematic Review" />
        </label>
        <label className="field-label">
          Qualitative notes / findings
          <textarea rows={6} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Paste analysis, findings, talking points..." />
        </label>

        <label className="field-label">
          Quantitative datasets (CSV/XLSX)
          <input type="file" accept=".csv,.xlsx,.xlsm" onChange={(e) => e.target.files?.[0] && handleDatasetUpload(e.target.files[0])} />
        </label>
        {datasets.length > 0 && (
          <div className="chip-row">
            {datasets.map((ds, i) => (
              <span className="chip" key={ds.dataset_id}>
                {ds.name} ({ds.rows.length} rows)
                <button className="link-button" style={{ marginLeft: 6 }} onClick={() => setDatasets(datasets.filter((_, j) => j !== i))}>
                  &times;
                </button>
              </span>
            ))}
          </div>
        )}

        <label className="field-label">
          Template (optional — ingest a .pptx to match its house style)
          <input type="file" accept=".pptx" onChange={(e) => e.target.files?.[0] && handleTemplateUpload(e.target.files[0])} />
        </label>
        {templates.length > 0 && (
          <select value={template?.template_id ?? ""} onChange={(e) => setTemplate(templates.find((t) => t.template_id === e.target.value) ?? null)}>
            <option value="">(no template)</option>
            {templates.map((t) => (
              <option key={t.template_id} value={t.template_id}>
                {t.source_filename} ({t.layouts.length} layouts)
              </option>
            ))}
          </select>
        )}
        {template && (
          <p className="muted">
            Using "{template.source_filename}" — {template.layouts.length} layout(s), fonts {template.major_font ?? "?"}/{template.minor_font ?? "?"}.
          </p>
        )}
      </section>

      <section className="card">
        <h2>2. Audience &amp; layout</h2>
        <div className="inline-fields">
          <div>
            <label className="field-label">
              Audience level
              <select value={audienceLevel} onChange={(e) => setAudienceLevel(e.target.value as AudienceLevel)}>
                {AUDIENCE_LEVELS.map((l) => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </select>
            </label>
          </div>
          <div>
            <label className="field-label">
              Tone
              <select value={tone} onChange={(e) => setTone(e.target.value as Tone)}>
                {TONES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
          </div>
          <div>
            <label className="field-label">
              Output format
              <select value={outputFormat} onChange={(e) => setOutputFormat(e.target.value as OutputFormat)}>
                {OUTPUT_FORMATS.map((f) => (
                  <option key={f} value={f}>{FORMAT_LABELS[f] ?? f}</option>
                ))}
              </select>
            </label>
          </div>
          {outputFormat === "house_deck" && (
            <div>
              <span className="field-label">Deck colours</span>
              <div className="theme-switch" role="group" aria-label="Deck colour theme" style={{ margin: 0, width: 160 }}>
                {(["light", "dark"] as const).map((m) => (
                  <button key={m} type="button" className={deckTheme === m ? "on" : undefined} aria-pressed={deckTheme === m} onClick={() => setDeckTheme(m)}>
                    {m === "light" ? "Light" : "Dark"}
                  </button>
                ))}
              </div>
            </div>
          )}
          {outputFormat === "house_deck" && (
            <div>
              <span className="field-label">Deck density</span>
              <div className="theme-switch" role="group" aria-label="Deck density" style={{ margin: 0, width: 260 }}>
                {(["committee", "present"] as const).map((d) => (
                  <button key={d} type="button" className={deckDensity === d ? "on" : undefined} aria-pressed={deckDensity === d} onClick={() => setDeckDensity(d)}>
                    {d === "committee" ? "Committee" : "Presentation"}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
        {outputFormat === "house_deck" && (
          <label className="field-label">
            Goal — what should the audience decide or believe?
            <input type="text" value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Approve the utilities underweight" />
          </label>
        )}
        <label className="field-label">
          Audience description
          <input type="text" value={audienceDescription} onChange={(e) => setAudienceDescription(e.target.value)} placeholder="Investment committee, 20 minutes, wants the recommendation up front" />
        </label>
        <label className="field-label">
          Focus areas (comma-separated)
          <input type="text" value={focusAreas} onChange={(e) => setFocusAreas(e.target.value)} placeholder="risk, valuation, ESG" />
        </label>

        <div className="inline-fields">
          <div>
            <label className="field-label">
              Target length (slides/sections)
              <input type="number" value={targetLength} onChange={(e) => setTargetLength(e.target.value)} placeholder="planner's choice" />
            </label>
          </div>
          <div>
            <label className="field-label">
              Max bullets per slide
              <input type="number" value={maxBullets} onChange={(e) => setMaxBullets(Number(e.target.value))} />
            </label>
          </div>
        </div>
        <label className="checkbox-label">
          <input type="checkbox" checked={includeTitleSlide} onChange={(e) => setIncludeTitleSlide(e.target.checked)} /> Include title slide
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={includeAgendaSlide} onChange={(e) => setIncludeAgendaSlide(e.target.checked)} /> Include agenda slide (pptx)
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={includeAppendix} onChange={(e) => setIncludeAppendix(e.target.checked)} /> Route detailed material to an appendix
        </label>
        <label className="field-label">
          Other layout/style instructions
          <textarea rows={2} value={freeInstructions} onChange={(e) => setFreeInstructions(e.target.value)} placeholder="lead with the risk section, one chart per slide max..." />
        </label>

        <button onClick={draftPlan} disabled={busy}>{outputFormat === "house_deck" ? "Draft storyline" : "Draft content plan"}</button>
        {error && <p className="error-text" role="alert">{error}</p>}
      </section>

      {manifest && plan && (
        <section className="card">
          <div className="section-heading">
            <h2>3. Review &amp; render</h2>
            <span className={`status-pill status-${manifest.status}`}>{manifest.status}</span>
          </div>

          <label className="field-label">
            Deck/report title
            <input type="text" value={plan.title} onChange={(e) => setPlan({ ...plan, title: e.target.value })} />
          </label>
          <label className="field-label">
            Subtitle
            <input type="text" value={plan.subtitle} onChange={(e) => setPlan({ ...plan, subtitle: e.target.value })} />
          </label>

          {plan.sections.map((section, i) => (
            <div className="review-item" key={i}>
              <div className="inline-fields">
                <input type="text" value={section.heading} onChange={(e) => updateSection(i, { heading: e.target.value })} placeholder="Section heading" />
                <select value={section.layout_hint} onChange={(e) => updateSection(i, { layout_hint: e.target.value as SectionLayoutHint })}>
                  {LAYOUT_HINTS.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </div>
              {section.layout_hint !== "section_header" && (
                <>
                  <label className="field-label">
                    Narrative (one point per line)
                    <textarea
                      rows={3}
                      value={narrativeToText(section.narrative)}
                      onChange={(e) => updateSection(i, { narrative: textToNarrative(e.target.value) })}
                    />
                  </label>
                  {section.chart && (
                    <div className="inline-fields">
                      <span className="chip">Chart on dataset {section.chart.dataset_id}</span>
                      <select
                        value={section.chart.chart_type}
                        onChange={(e) => updateSection(i, { chart: { ...section.chart!, chart_type: e.target.value as ChartType } })}
                      >
                        {CHART_TYPES.filter((c) => c !== "table").map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                    </div>
                  )}
                  {section.table && <span className="chip">Table on dataset {section.table.dataset_id}</span>}
                </>
              )}
              <div className="toolbar">
                <label className="checkbox-label">
                  <input type="checkbox" checked={section.appendix} onChange={(e) => updateSection(i, { appendix: e.target.checked })} /> Appendix
                </label>
                <button className="link-button" onClick={() => moveSection(i, -1)} disabled={i === 0}>&uarr; up</button>
                <button className="link-button" onClick={() => moveSection(i, 1)} disabled={i === plan.sections.length - 1}>&darr; down</button>
                <button className="danger" onClick={() => removeSection(i)}>Remove</button>
              </div>
            </div>
          ))}

          <div className="toolbar">
            <button onClick={savePlan} disabled={busy}>Save plan changes</button>
            <button onClick={render} disabled={busy}>Render {manifest.output_format}</button>
            {manifest.status === "completed" && (
              <>
                <button className="link-button" onClick={() => openPreview(manifest.report_id, plan.title || manifest.title)}>
                  Preview
                </button>
                <a href={api.reportDownloadUrl(manifest.report_id)} target="_blank" rel="noreferrer">
                  Download {manifest.output_format}
                </a>
              </>
            )}
          </div>
          {manifest.error && <p className="error-text" role="alert">{manifest.error}</p>}
        </section>
      )}

      {manifest && storyline && (
        <section className="card">
          <div className="section-heading">
            <h2>3. Storyline</h2>
            <span className={`status-pill status-${manifest.status}`}>{manifest.status}</span>
          </div>
          <p className="help-text">One takeaway headline per slide. Read top to bottom, they should tell the whole argument.</p>

          <label className="field-label">
            Deck title
            <input type="text" value={storyline.title} disabled={storyline.approved} onChange={(e) => setStoryline({ ...storyline, title: e.target.value })} />
          </label>
          <label className="field-label">
            Subtitle
            <input type="text" value={storyline.subtitle} disabled={storyline.approved} onChange={(e) => setStoryline({ ...storyline, subtitle: e.target.value })} />
          </label>

          {storyline.slides.map((slide, i) => (
            <div className="review-item" key={i}>
              <input type="text" value={slide.headline} disabled={storyline.approved} onChange={(e) => updateSlide(i, { headline: e.target.value })} placeholder={`Slide ${i + 1} headline`} />
              <input type="text" value={slide.purpose} disabled={storyline.approved} onChange={(e) => updateSlide(i, { purpose: e.target.value })} placeholder="Purpose (what this slide shows)" />
              {!storyline.approved && (
                <div className="toolbar">
                  <button className="link-button" onClick={() => moveSlide(i, -1)} disabled={i === 0}>&uarr; up</button>
                  <button className="link-button" onClick={() => moveSlide(i, 1)} disabled={i === storyline.slides.length - 1}>&darr; down</button>
                  <button className="danger" onClick={() => setStoryline({ ...storyline, slides: storyline.slides.filter((_, j) => j !== i) })}>Remove</button>
                </div>
              )}
            </div>
          ))}

          <div className="toolbar">
            {!storyline.approved && (
              <>
                <button className="link-button" onClick={() => setStoryline({ ...storyline, slides: [...storyline.slides, { headline: "", purpose: "", source_refs: [] }] })}>
                  + Add headline
                </button>
                <button onClick={saveStoryline} disabled={busy}>Save</button>
                <button
                  onClick={approveAndBuild}
                  disabled={busy || storyline.slides.length === 0 || storyline.slides.some((s) => !s.headline.trim())}
                  title={storyline.slides.some((s) => !s.headline.trim()) ? "Every slide needs a headline" : undefined}
                >
                  {busy ? "Building..." : "Approve & build"}
                </button>
              </>
            )}
            {storyline.approved && manifest.status === "failed" && (
              <button onClick={approveAndBuild} disabled={busy}>{busy ? "Building..." : "Retry build"}</button>
            )}
            {manifest.status === "completed" && (
              <>
                <button className="link-button" onClick={() => openPreview(manifest.report_id, storyline.title || manifest.title)}>
                  Preview
                </button>
                {manifest.output_files.map((f) => (
                  <a key={f} className="button-link" href={api.reportDownloadUrl(manifest.report_id, f)} target="_blank" rel="noreferrer">
                    Download {f.split(".").pop()?.toUpperCase()}
                  </a>
                ))}
              </>
            )}
          </div>
          {manifest.error && <p className="error-text" role="alert">{manifest.error}</p>}

          {findings.length > 0 && (
            <>
              <h3>Findings</h3>
              {groupBySlide(findings).map(([slide, items]) => (
                <div className="review-item" key={slide}>
                  <strong>{slide === 0 ? "Title slide" : `Slide ${slide}`}</strong>
                  {[false, true].map((info) => {
                    const shown = items.filter((f) => (f.severity === "info") === info);
                    return shown.length > 0 && (
                      <div key={String(info)} className={info ? "muted" : undefined}>
                        {info && <span className="mono">Layout changes</span>}
                        <ul>
                          {shown.map((f, j) => (
                            <li key={j}>
                              <span className="mono">{f.stage}/{f.rule}</span>
                              {f.slot && <span className="muted"> [{f.slot}]</span>} — {f.message}
                            </li>
                          ))}
                        </ul>
                      </div>
                    );
                  })}
                </div>
              ))}
            </>
          )}
        </section>
      )}

      <section className="card">
        <h2>Previous reports</h2>
        {reports.length === 0 && <p className="muted">No reports generated yet.</p>}
        {reports.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Format</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {reports.map((r) => (
                  <tr key={r.report_id} className="clickable-row" {...activatable(() => openReport(r.report_id))}>
                    <td>{r.title}</td>
                    <td>{r.output_format}</td>
                    <td><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                    <td className="mono">{when(r.created_at)}</td>
                    <td>
                      {r.status === "completed" && (
                        <>
                          <button
                            className="link-button"
                            style={{ marginRight: 10 }}
                            onClick={(e) => {
                              e.stopPropagation();
                              openPreview(r.report_id, r.title);
                            }}
                          >
                            Preview
                          </button>
                          <a href={api.reportDownloadUrl(r.report_id)} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                            Download
                          </a>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>

    {previewReportId && (
      <aside className="source-panel">
        <div className="source-panel-header">
          <h3>Preview — {previewTitle}</h3>
          <button className="link-button" onClick={closePreview}>Close</button>
        </div>
        {previewLoading && <p className="muted">Rendering preview...</p>}
        {previewError && <p className="error-text" role="alert">{previewError}</p>}
        {!previewLoading && !previewError && previewPageCount === 0 && <p className="muted">No pages to show.</p>}
        {!previewLoading && !previewError && previewPageCount > 0 && (
          <div className="preview-thumb-grid">
            {Array.from({ length: previewPageCount }, (_, i) => i + 1).map((p) => (
              <button key={p} className="preview-thumb" onClick={() => setEnlargedPage(p)}>
                <img src={api.reportPreviewPageUrl(previewReportId, p)} alt={`Page ${p}`} loading="lazy" />
                <span>{p}</span>
              </button>
            ))}
          </div>
        )}
      </aside>
    )}

    {enlargedPage && previewReportId && (
      <Modal title={`${previewTitle} — page ${enlargedPage} / ${previewPageCount}`} onClose={() => setEnlargedPage(null)}>
        <img className="modal-image" src={api.reportPreviewPageUrl(previewReportId, enlargedPage)} alt={`Page ${enlargedPage}`} />
        <div className="toolbar">
          <button onClick={() => setEnlargedPage((p) => Math.max(1, (p ?? 1) - 1))} disabled={enlargedPage <= 1}>
            &larr; Prev
          </button>
          <button onClick={() => setEnlargedPage((p) => Math.min(previewPageCount, (p ?? 1) + 1))} disabled={enlargedPage >= previewPageCount}>
            Next &rarr;
          </button>
        </div>
      </Modal>
    )}
    </div>
  );
}
