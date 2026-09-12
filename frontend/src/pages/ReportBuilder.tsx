import { useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  AudienceLevel,
  ChartType,
  ContentItem,
  OutputFormat,
  QuantitativeDataset,
  ReportManifest,
  ReportPlan,
  ReportSection,
  SectionLayoutHint,
  TemplateStyleProfile,
  Tone,
} from "../types";
import { CHART_TYPES } from "../types";

const AUDIENCE_LEVELS: AudienceLevel[] = ["executive", "technical", "general"];
const TONES: Tone[] = ["formal", "conversational", "persuasive", "neutral_analytical"];
const OUTPUT_FORMATS: OutputFormat[] = ["pptx", "docx", "pdf"];
const LAYOUT_HINTS: SectionLayoutHint[] = ["standard", "chart_focus", "text_only", "section_header"];

function narrativeToText(narrative: ContentItem[]): string {
  return narrative.map((n) => n.text).join("\n");
}

function textToNarrative(text: string): ContentItem[] {
  return text.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => ({ text: line, bullet: true }));
}

export function ReportBuilder() {
  // Request inputs
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [datasets, setDatasets] = useState<QuantitativeDataset[]>([]);
  const [template, setTemplate] = useState<TemplateStyleProfile | null>(null);
  const [templates, setTemplates] = useState<TemplateStyleProfile[]>([]);
  const [audienceLevel, setAudienceLevel] = useState<AudienceLevel>("general");
  const [tone, setTone] = useState<Tone>("neutral_analytical");
  const [audienceDescription, setAudienceDescription] = useState("");
  const [focusAreas, setFocusAreas] = useState("");
  const [outputFormat, setOutputFormat] = useState<OutputFormat>("pptx");
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
  const [reports, setReports] = useState<ReportManifest[]>([]);

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
    try {
      const req = {
        title,
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
      const p = await api.getReportPlan(m.report_id);
      setPlan(p);
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
      const p = await api.getReportPlan(reportId).catch(() => null);
      setPlan(p);
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
    if (!plan) return;
    const target = index + delta;
    if (target < 0 || target >= plan.sections.length) return;
    const sections = [...plan.sections];
    [sections[index], sections[target]] = [sections[target], sections[index]];
    setPlan({ ...plan, sections });
  }

  function removeSection(index: number) {
    if (!plan) return;
    setPlan({ ...plan, sections: plan.sections.filter((_, i) => i !== index) });
  }

  return (
    <div className="page">
      <h2>Presentation &amp; Reporting Tool</h2>
      <p className="help-text">
        Drafts a structured content plan from your qualitative notes and quantitative data -- matched to the
        audience and layout instructions below, and to an ingested template's style if one is supplied -- then
        deterministically renders it to pptx/docx/pdf. Review and edit the plan (reorder sections, swap a chart
        type, tweak text) before rendering the final file.
      </p>

      <section className="card">
        <h3>1. Content</h3>
        <label className="field-label">Title</label>
        <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Electrification Thematic Review" />
        <label className="field-label">Qualitative notes / findings</label>
        <textarea rows={6} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Paste analysis, findings, talking points..." />

        <label className="field-label">Quantitative datasets (CSV/XLSX)</label>
        <input type="file" accept=".csv,.xlsx,.xlsm" onChange={(e) => e.target.files?.[0] && handleDatasetUpload(e.target.files[0])} />
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

        <label className="field-label">Template (optional -- ingest a .pptx to match its house style)</label>
        <input type="file" accept=".pptx" onChange={(e) => e.target.files?.[0] && handleTemplateUpload(e.target.files[0])} />
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
            Using "{template.source_filename}" -- {template.layouts.length} layout(s), fonts {template.major_font ?? "?"}/{template.minor_font ?? "?"}.
          </p>
        )}
      </section>

      <section className="card">
        <h3>2. Audience &amp; layout</h3>
        <div className="inline-fields">
          <div>
            <label className="field-label">Audience level</label>
            <select value={audienceLevel} onChange={(e) => setAudienceLevel(e.target.value as AudienceLevel)}>
              {AUDIENCE_LEVELS.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label">Tone</label>
            <select value={tone} onChange={(e) => setTone(e.target.value as Tone)}>
              {TONES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label">Output format</label>
            <select value={outputFormat} onChange={(e) => setOutputFormat(e.target.value as OutputFormat)}>
              {OUTPUT_FORMATS.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>
        </div>
        <label className="field-label">Audience description</label>
        <input type="text" value={audienceDescription} onChange={(e) => setAudienceDescription(e.target.value)} placeholder="Investment committee, 20 minutes, wants the recommendation up front" />
        <label className="field-label">Focus areas (comma-separated)</label>
        <input type="text" value={focusAreas} onChange={(e) => setFocusAreas(e.target.value)} placeholder="risk, valuation, ESG" />

        <div className="inline-fields">
          <div>
            <label className="field-label">Target length (slides/sections)</label>
            <input type="number" value={targetLength} onChange={(e) => setTargetLength(e.target.value)} placeholder="planner's choice" />
          </div>
          <div>
            <label className="field-label">Max bullets per slide</label>
            <input type="number" value={maxBullets} onChange={(e) => setMaxBullets(Number(e.target.value))} />
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
        <label className="field-label">Other layout/style instructions</label>
        <textarea rows={2} value={freeInstructions} onChange={(e) => setFreeInstructions(e.target.value)} placeholder="lead with the risk section, one chart per slide max..." />

        <button onClick={draftPlan} disabled={busy}>Draft content plan</button>
        {error && <p className="error-text">{error}</p>}
      </section>

      {manifest && plan && (
        <section className="card">
          <div className="section-heading">
            <h3>3. Review &amp; render</h3>
            <span className={`status-pill status-${manifest.status}`}>{manifest.status}</span>
          </div>

          <label className="field-label">Deck/report title</label>
          <input type="text" value={plan.title} onChange={(e) => setPlan({ ...plan, title: e.target.value })} />
          <label className="field-label">Subtitle</label>
          <input type="text" value={plan.subtitle} onChange={(e) => setPlan({ ...plan, subtitle: e.target.value })} />

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
                  <label className="field-label">Narrative (one point per line)</label>
                  <textarea
                    rows={3}
                    value={narrativeToText(section.narrative)}
                    onChange={(e) => updateSection(i, { narrative: textToNarrative(e.target.value) })}
                  />
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
              <a href={api.reportDownloadUrl(manifest.report_id)} target="_blank" rel="noreferrer">
                Download {manifest.output_format}
              </a>
            )}
          </div>
          {manifest.error && <p className="error-text">{manifest.error}</p>}
        </section>
      )}

      <section className="card">
        <h3>Previous reports</h3>
        {reports.length === 0 && <p className="muted">No reports generated yet.</p>}
        {reports.length > 0 && (
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
                <tr key={r.report_id} className="clickable-row" onClick={() => openReport(r.report_id)}>
                  <td>{r.title}</td>
                  <td>{r.output_format}</td>
                  <td><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td>
                    {r.status === "completed" && (
                      <a href={api.reportDownloadUrl(r.report_id)} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                        Download
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
