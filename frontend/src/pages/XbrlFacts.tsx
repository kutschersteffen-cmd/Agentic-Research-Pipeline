import { useCallback, useState, type ReactNode } from "react";
import { XbrlFactsTable } from "../components/XbrlFactsTable";
import { XbrlFetchArea } from "../components/XbrlFetchArea";
import { XbrlFilesArea } from "../components/XbrlFilesArea";
import { XbrlRequiredArea } from "../components/XbrlRequiredArea";
import { XbrlVerifyArea } from "../components/XbrlVerifyArea";
import { XbrlTagsArea } from "../components/XbrlTagsArea";
import { keyLabel } from "../lib/xbrlTags";
import type { XbrlCompanyFiles } from "../types";

const factsCaption = (c: XbrlCompanyFiles, cik: ReactNode) => (
  <>
    {c.fact_count.toLocaleString()} {c.fact_count === 1 ? "fact" : "facts"} extracted from {keyLabel(c.market)} {cik},{" "}
    {c.tags
      ? `limited to a selection of ${c.tags.length} ${c.tags.length === 1 ? "tag" : "tags"} when it was fetched.`
      : "every tag the company reported."}
  </>
);

/** XBRL Facts: fetch companies' SEC or ESEF XBRL facts, see the stored files and facts, choose the tags that matter. Areas stack as sections. */
export function XbrlFacts({ selectedRunId, onSelectRun }: { selectedRunId: string | null; onSelectRun: (runId: string) => void }) {
  const [tags, setTags] = useState<string[]>([]);
  const [filesKey, setFilesKey] = useState(0);
  const [cik, setCik] = useState<string | null>(null);
  const [company, setCompany] = useState<XbrlCompanyFiles | null>(null); // the chosen CIK or LEI as the latest list has it
  const filesChanged = useCallback(() => setFilesKey((k) => k + 1), []);
  const choose = useCallback((next: string | null, show: boolean) => {
    setCik(next);
    if (show) {
      const h = document.getElementById("xbrl-facts-title");
      h?.scrollIntoView({ block: "start" });
      h?.focus({ preventScroll: true });
    }
  }, []);
  return (
    <div className="page">
      <h1>XBRL Facts</h1>
      <p className="help-text">
        Download each company’s XBRL facts and annual report from the SEC (US) or the ESEF filing index (EU), keep
        every fact traceable to its filing, and choose which tags you need.
      </p>
      <XbrlFetchArea tags={tags} onSettled={filesChanged} selectedRunId={selectedRunId} onSelectRun={onSelectRun} />
      <XbrlFilesArea refreshKey={filesKey} chosen={cik} onChoose={choose} onCompany={setCompany} />
      <section className="card" aria-labelledby="xbrl-facts-title">
        <h2 id="xbrl-facts-title" tabIndex={-1}>
          Facts{company && <>: {company.name || company.company_id}</>}
        </h2>
        {company && company.cik === cik ? (
          <>
            <p className="help-text">
              {factsCaption(company, <span className="mono">{company.cik}</span>)}
            </p>
            <XbrlFactsTable key={`${company.cik}|${company.fetched_at}`} cik={company.cik} />
          </>
        ) : (
          <p className="muted">Choose a company in Files to see its facts.</p>
        )}
      </section>
      <XbrlRequiredArea fetchRunId={selectedRunId} refreshKey={filesKey} />
      <XbrlVerifyArea />
      <XbrlTagsArea tags={tags} onChange={setTags} />
    </div>
  );
}
