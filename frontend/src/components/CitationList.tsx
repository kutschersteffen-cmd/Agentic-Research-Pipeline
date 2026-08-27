import { api } from "../api/client";
import type { Citation } from "../types";
import type { ActiveSource } from "./SourcePanel";

interface Props {
  citations: Citation[];
  onOpenSource: (source: ActiveSource) => void;
}

/** Shared citation list used by every review page (extraction, financials,
 * transition-plan). "view source" opens the document in the page's docked
 * SourcePanel (see SourcePanel.tsx) instead of a new browser tab -- so
 * checking a citation never navigates the reviewer away from the value
 * they're reviewing. */
export function CitationList({ citations, onOpenSource }: Props) {
  if (citations.length === 0) return null;
  return (
    <ul className="citation-list">
      {citations.map((c, ci) => (
        <li key={ci}>
          [{c.doc_type}] "{c.quote}"
          {c.grounded && c.company_id && c.source_filename && (
            <>
              {" "}
              <button
                type="button"
                className="link-button"
                onClick={() =>
                  onOpenSource({
                    title: `${c.source_filename}${c.page ? ` — p. ${c.page}` : c.sheet ? ` — ${c.sheet}` : ""}`,
                    src: `${api.documentRawUrl(c.company_id!, c.doc_type, c.source_filename!)}${c.page ? `#page=${c.page}` : ""}`,
                    quote: c.quote,
                  })
                }
              >
                view source{c.page ? ` (p. ${c.page})` : c.sheet ? ` (${c.sheet})` : ""}
              </button>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}
