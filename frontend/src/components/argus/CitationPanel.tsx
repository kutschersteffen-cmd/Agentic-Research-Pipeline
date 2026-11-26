import { useEffect, useRef } from "react";
import type { DeskCitation, DeskSource } from "../../types";

/** One cited source beside the answer: where it is, the quote, whether the check found it, arrows to the other
 * citations. `×` or Esc closes it. */
export function CitationPanel({ citations, at, sources, onMove, onClose }: {
  citations: DeskCitation[]; at: number; sources: DeskSource[]; onMove: (at: number) => void; onClose: () => void;
}) {
  const close = useRef<HTMLButtonElement>(null);
  const c = citations[at];
  const source = sources.find((s) => s.n === c.source);
  useEffect(() => close.current?.focus(), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <aside className="desk-citation" role="dialog" aria-label={`Source ${c.source}`}>
      <div className="desk-citation-head">
        <span className="desk-cite" aria-hidden="true">{c.source}</span>
        <div>
          <strong>{source?.company_name ?? "Unknown source"}</strong>
          <div className="muted">{source?.filename}{c.page !== null && <> · Page {c.page}</>}</div>
        </div>
        <button type="button" className="secondary" ref={close} aria-label="Close" onClick={onClose}>×</button>
      </div>
      <blockquote>{c.quote}</blockquote>
      <p className="desk-grounded" data-grounded={c.grounded}>{c.grounded ? "found word for word" : "not found in the source"}</p>
      <div className="desk-citation-nav">
        {at > 0 && <button type="button" className="link-button" onClick={() => onMove(at - 1)}>← Source {citations[at - 1].source}</button>}
        {at < citations.length - 1 && <button type="button" className="link-button" onClick={() => onMove(at + 1)}>Source {citations[at + 1].source} →</button>}
      </div>
    </aside>
  );
}
