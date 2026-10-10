import { useEffect, useRef } from "react";
import { valueLabel } from "../../lib/fieldValue";
import type { ExtractedField, FactCitation, FactTrail } from "../../types";
import { FactStatus } from "./FactsTable";
import { sourceLabel } from "./companyQuery";

const day = (iso: string | null) => (iso ? iso.slice(0, 10) : "now");

/** Where one fact's value came from, newest version first: the observation,
 * its citations (each opens the document at its page), the provider load and
 * every review decision. Escape closes it. */
export function FactTrailPanel({ trail, error, onClose, onOpenCitation }: {
  trail: FactTrail | null;
  error: string;
  onClose: () => void;
  onOpenCitation: (c: FactCitation) => void;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
    headingRef.current?.scrollIntoView({ block: "nearest" });
  }, [trail?.fact_id]);
  useEffect(() => {
    // Not while the document viewer is open: its own Escape closes it first.
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !document.querySelector("dialog[open]") && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside className="source-panel trail-panel" aria-labelledby="trail-heading">
      <div className="source-panel-header">
        <h2 id="trail-heading" ref={headingRef} tabIndex={-1}>
          {trail ? <span className="mono">{trail.field_id}</span> : "Fact trail"}
          {trail?.period_end && <span className="muted"> · {trail.period_end}</span>}
          {trail?.basis && <span className="muted"> · {trail.basis}</span>}
        </h2>
        <button className="link-button" onClick={onClose}>Close</button>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {!trail && !error && <p className="muted" role="status">Loading…</p>}
      {trail && (
        <ol className="trail-versions">
          {[...trail.versions].reverse().map((v) => (
            <li key={v.fact_id} className={v.valid_to ? "trail-version superseded" : "trail-version"}>
              <div className="trail-version-head">
                <strong className="mono">{valueLabel({ ...v.observation, value: v.observation.value as ExtractedField["value"] })}</strong>
                <FactStatus status={v.status} />
              </div>
              <p className="muted mono">
                {v.valid_to ? `${day(v.valid_from)} → ${day(v.valid_to)}` : `current since ${day(v.valid_from)}`} · {sourceLabel(v)}
              </p>
              <dl className="trail-facts">
                <dt>Observed</dt>
                <dd className="mono">
                  {v.observation.source_kind}
                  {v.observation.run_id && ` · run ${v.observation.run_id}`}
                  {v.observation.confidence != null && ` · confidence ${v.observation.confidence.toFixed(2)}`}
                  {v.observation.route && ` · ${v.observation.route.replace("_", "-")}`}
                </dd>
                {v.load && (
                  <>
                    <dt>Load</dt>
                    <dd className="mono">{v.load.source_name} · loaded {v.load.fetched_at.slice(0, 16).replace("T", " ")}</dd>
                  </>
                )}
              </dl>
              {v.citations.length > 0 && (
                <ul className="trail-citations">
                  {v.citations.map((c, i) => (
                    <li key={i}>
                      <button type="button" className="link-button" onClick={() => onOpenCitation(c)}>
                        {c.title}{c.page != null ? `, p. ${c.page}` : ""}
                      </button>
                      <span className="muted"> {c.role}</span>
                      {!c.grounded && <span className="badge badge-low" title="The quote was not found in the source when re-checked">not verified</span>}
                      {c.quote && <q className="source-panel-quote">{c.quote}</q>}
                    </li>
                  ))}
                </ul>
              )}
              {v.decisions.length > 0 && (
                <ul className="trail-decisions">
                  {v.decisions.map((d, i) => (
                    <li key={i}>
                      <span className="mono">{day(d.decided_at)}</span> {d.decision ?? "comment"}
                      {d.reviewer && <> by {d.reviewer}</>}
                      {d.comment && <span className="muted"> — {d.comment}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}
