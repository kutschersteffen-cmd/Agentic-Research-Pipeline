import { Fragment } from "react";
import { api } from "../api/client";
import { ConfidenceBadge, GroundedBadge } from "./ConfidenceBadge";
import { ReviewControls } from "./ReviewControls";
import { CitationList } from "./CitationList";
import type { ActiveSource } from "./SourcePanel";
import type { BusinessSegment, CompanyFinancialsRecord, ExtractionRecord, ReviewDecision, SpendSummary } from "../types";

// Shared between Extraction.tsx (a run just started in this browser session)
// and DataLibrary.tsx (any past run, picked by run_id) -- both render the
// same result shapes, so the rendering lives here once.

export function fmtAmount(value?: number | null): string {
  return value == null ? "—" : value.toLocaleString();
}

export function SegmentDetail({ segment, onOpenSource }: { segment: BusinessSegment; onOpenSource: (s: ActiveSource) => void }) {
  return (
    <div className="field-detail">
      <strong>{segment.name}</strong> <GroundedBadge grounded={segment.grounded} /> <ConfidenceBadge value={segment.confidence} />
      {segment.description && <p>{segment.description}</p>}
      <CitationList citations={segment.description_citations} onOpenSource={onOpenSource} />
      <table className="data-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Value</th>
            <th>Grounded</th>
          </tr>
        </thead>
        <tbody>
          {(["revenue", "income", "assets"] as const).map((metric) => (
            <tr key={metric}>
              <td style={{ textTransform: "capitalize" }}>{metric}</td>
              <td>
                {fmtAmount(segment[metric].value)}
                {segment[metric].raw_value_text && <span className="muted"> ({segment[metric].raw_value_text})</span>}
              </td>
              <td><GroundedBadge grounded={segment[metric].grounded} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {(["revenue", "income", "assets"] as const).map((metric) =>
        segment[metric].citations.length > 0 ? (
          <div key={metric}>
            <span className="muted" style={{ textTransform: "capitalize" }}>{metric} citations:</span>
            <CitationList citations={segment[metric].citations} onOpenSource={onOpenSource} />
          </div>
        ) : null
      )}
      {segment.conflicting_sources && <p className="error-text">Conflicting figures across sources.</p>}
    </div>
  );
}

export function SpendDetail({ label, spend, onOpenSource }: { label: string; spend: SpendSummary; onOpenSource: (s: ActiveSource) => void }) {
  return (
    <div className="field-detail">
      <strong>{label} total:</strong> {fmtAmount(spend.total.value)}
      {spend.total.raw_value_text && <span className="muted"> ({spend.total.raw_value_text})</span>}{" "}
      <GroundedBadge grounded={spend.grounded} /> <ConfidenceBadge value={spend.confidence} />
      <CitationList citations={spend.total.citations} onOpenSource={onOpenSource} />
      {spend.description && (
        <>
          <p>{spend.description}</p>
          <CitationList citations={spend.description_citations} onOpenSource={onOpenSource} />
        </>
      )}
      {spend.categories.length > 0 && (
        <>
          <p className="muted">Category breakdown:</p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Description</th>
                <th>Amount</th>
                <th>Grounded</th>
              </tr>
            </thead>
            <tbody>
              {spend.categories.map((c, ci) => (
                <tr key={ci}>
                  <td>{c.name}</td>
                  <td>{c.description ?? "—"}</td>
                  <td>{fmtAmount(c.amount.value)}</td>
                  <td><GroundedBadge grounded={c.grounded} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {spend.verifier_notes && <p className="muted">{spend.verifier_notes}</p>}
      {spend.conflicting_sources && <p className="error-text">Conflicting figures across sources.</p>}
    </div>
  );
}

interface ExtractionResultsTableProps {
  results: ExtractionRecord[];
  runId: string;
  expanded: string | null;
  onToggleExpanded: (companyId: string) => void;
  reviewDecisions: Record<string, ReviewDecision>;
  reviewer: string;
  onReviewDone: () => void;
  onOpenSource: (s: ActiveSource) => void;
}

export function ExtractionResultsTable({
  results,
  runId,
  expanded,
  onToggleExpanded,
  reviewDecisions,
  reviewer,
  onReviewDone,
  onOpenSource,
}: ExtractionResultsTableProps) {
  if (results.length === 0) return null;
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Company</th>
          <th>Fields</th>
          <th>Overall confidence</th>
          <th>Needs review</th>
        </tr>
      </thead>
      <tbody>
        {results.map((r) => (
          <Fragment key={r.company_id}>
            <tr className="clickable-row" onClick={() => onToggleExpanded(r.company_id)}>
              <td>{r.name} {r.ticker && <span className="muted">({r.ticker})</span>}</td>
              <td>{r.fields.map((f) => `${f.field_name}=${f.value ?? "—"}`).join(", ")}</td>
              <td><ConfidenceBadge value={r.overall_confidence} /></td>
              <td>{r.needs_review ? "⚑" : ""}</td>
            </tr>
            {expanded === r.company_id && (
              <tr>
                <td colSpan={4} className="detail-cell">
                  {r.fields.map((f) => {
                    const itemKey = `${r.company_id}:${f.field_id}`;
                    return (
                      <div key={f.field_id} className="field-detail">
                        <strong>{f.field_name}:</strong> {String(f.value ?? "not disclosed")}{" "}
                        <ConfidenceBadge value={f.confidence} /> <GroundedBadge grounded={f.grounded} />
                        {f.verifier_notes && <p className="muted">{f.verifier_notes}</p>}
                        <CitationList citations={f.citations} onOpenSource={onOpenSource} />
                        <ReviewControls
                          runId={runId}
                          itemKey={itemKey}
                          current={reviewDecisions[itemKey]}
                          reviewer={reviewer}
                          onDone={onReviewDone}
                        />
                      </div>
                    );
                  })}
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

interface FinancialsResultsTableProps {
  results: CompanyFinancialsRecord[];
  runId: string;
  expanded: string | null;
  onToggleExpanded: (companyId: string) => void;
  reviewDecisions: Record<string, ReviewDecision>;
  reviewer: string;
  onReviewDone: () => void;
  onOpenSource: (s: ActiveSource) => void;
}

export function FinancialsResultsTable({
  results,
  runId,
  expanded,
  onToggleExpanded,
  reviewDecisions,
  reviewer,
  onReviewDone,
  onOpenSource,
}: FinancialsResultsTableProps) {
  if (results.length === 0) return null;
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Company</th>
          <th>Segments</th>
          <th>CapEx</th>
          <th>R&amp;D</th>
          <th>Confidence</th>
          <th>Needs review</th>
        </tr>
      </thead>
      <tbody>
        {results.map((r) => (
          <Fragment key={r.company_id}>
            <tr className="clickable-row" onClick={() => onToggleExpanded(r.company_id)}>
              <td>{r.name} {r.ticker && <span className="muted">({r.ticker})</span>}</td>
              <td>{r.segments.length === 0 ? "none found" : `${r.segments.length} segment(s)`}</td>
              <td>{fmtAmount(r.capex.total.value)} {r.currency ?? ""}</td>
              <td>{fmtAmount(r.rnd.total.value)} {r.currency ?? ""}</td>
              <td><ConfidenceBadge value={r.overall_confidence} /></td>
              <td>{r.needs_review ? "⚑" : ""}</td>
            </tr>
            {expanded === r.company_id && (
              <tr>
                <td colSpan={6} className="detail-cell">
                  <h4>Business Segments</h4>
                  {r.segments.length === 0 && <p className="muted">No segment reporting evidence found.</p>}
                  {r.segments.map((s, si) => (
                    <SegmentDetail key={si} segment={s} onOpenSource={onOpenSource} />
                  ))}
                  {r.segments_verifier_notes && <p className="muted">{r.segments_verifier_notes}</p>}

                  <h4>CapEx</h4>
                  <SpendDetail label="CapEx" spend={r.capex} onOpenSource={onOpenSource} />

                  <h4>R&amp;D</h4>
                  <SpendDetail label="R&D" spend={r.rnd} onOpenSource={onOpenSource} />

                  <ReviewControls
                    runId={runId}
                    itemKey={r.company_id}
                    current={reviewDecisions[r.company_id]}
                    reviewer={reviewer}
                    onDone={onReviewDone}
                    submitFn={api.submitFinancialsReview}
                    historyFn={api.getFinancialsReviewHistory}
                  />
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}
