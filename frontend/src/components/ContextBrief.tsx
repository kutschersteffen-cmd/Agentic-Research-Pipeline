import { useRef, useState } from "react";
import { NO_BRIEF, actionsLine, companyNames, evidenceNumber, factsLine, financialsLine } from "../lib/contextBrief";
import type { ContextBrief } from "../types";

/** Step 1's context brief: why now, early evidence, affected sectors. Shared by the candidate card and the dossier. */
export function ContextBriefBody({ brief }: { brief: ContextBrief | null }) {
  const items = useRef(new Map<string, HTMLLIElement>());
  const [current, setCurrent] = useState<string | null>(null);
  if (!brief) return <p className="muted">{NO_BRIEF}</p>;

  const failed = brief.status === "failed";
  const markers = (ids: string[]) =>
    ids.map((id) => (
      <span key={id}>
        {" "}
        <button
          type="button"
          className="link-button"
          title={`Show evidence ${evidenceNumber(id)}`}
          onClick={() => {
            items.current.get(id)?.scrollIntoView({ block: "nearest" });
            setCurrent(id);
          }}
        >
          [{evidenceNumber(id)}]
        </button>
      </span>
    ));
  const sentences = (list: ContextBrief["why_now"]) =>
    list.map((s, i) => (
      <p key={i}>
        {s.text}
        {markers(s.evidence_ids)}
      </p>
    ));
  const unclassified = brief.companies.filter((c) => c.isic_division == null);
  const { by_company, groups, unclassified_company_ids } = brief.activities;

  return (
    <div className="context-brief">
      {failed && <p className="muted">The brief's wording failed; facts, evidence and sectors are shown.</p>}
      <h3>Why now</h3>
      <p>{factsLine(brief)}</p>
      <p>{actionsLine(brief)}</p>
      {sentences(brief.why_now)}

      <h3>Early evidence</h3>
      {sentences(brief.early_evidence)}
      <ol>
        {brief.evidence.map((e) => (
          <li
            key={e.evidence_id}
            ref={(el) => {
              if (el) items.current.set(e.evidence_id, el);
            }}
            aria-current={current === e.evidence_id ? "true" : undefined}
          >
            {e.kind === "financials" ? (
              financialsLine(e, companyNames(brief, [e.company_id]))
            ) : (
              <>
                {e.kind === "counter" && "Counter-evidence: "}"{e.quote}" —{" "}
                <a href={e.url} target="_blank" rel="noreferrer">{e.title}</a>
                {e.published_at && <span className="muted">, {e.published_at.slice(0, 10)}</span>}
              </>
            )}
          </li>
        ))}
      </ol>

      <h3>Affected sectors</h3>
      {brief.sectors.map((s) => (
        <p key={s.isic_division}>
          {s.label} (ISIC {s.isic_division}): {companyNames(brief, s.company_ids)}
        </p>
      ))}
      {unclassified.length > 0 && (
        <>
          <h4>Activities (no ISIC code)</h4>
          {groups.map((g, i) => (
            <p key={i}>
              {g.activity}: {companyNames(brief, g.company_ids)}
            </p>
          ))}
          {by_company.map((line) => (
            <p key={line.company_id}>
              {companyNames(brief, [line.company_id])}: {line.activity}
              {markers(line.evidence_ids)}
            </p>
          ))}
          {unclassified_company_ids.length > 0 && <p>Not classified: {companyNames(brief, unclassified_company_ids)}</p>}
        </>
      )}
      {brief.dropped_statements > 0 && <p className="muted">Dropped for lack of a cited source: {brief.dropped_statements}</p>}
    </div>
  );
}
