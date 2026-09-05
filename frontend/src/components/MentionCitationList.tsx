import { GroundedBadge } from "./ConfidenceBadge";
import type { MentionCitation } from "../types";

interface Props {
  citations: MentionCitation[];
}

/** Emerging Themes' evidence list -- deliberately not `CitationList`, which
 * hard-requires a `Citation`'s doc_type/source_filename/page to open the
 * cited document in the docked SourcePanel. A `MentionCitation` points at
 * an external news/filing URL, not a document stored in this system's
 * document store, so there's no internal doc to stream split-screen --
 * a plain new-tab link to the original source is the correct affordance
 * here, not an iframe. */
export function MentionCitationList({ citations }: Props) {
  if (citations.length === 0) return null;
  return (
    <ul className="citation-list">
      {citations.map((c, ci) => (
        <li key={ci}>
          <GroundedBadge grounded={c.grounded} /> [{c.source_type}] "{c.quote}"{" "}
          <a href={c.url} target="_blank" rel="noreferrer">
            source
          </a>
        </li>
      ))}
    </ul>
  );
}
