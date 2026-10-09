import { useCallback, useState, type ReactNode } from "react";
import { XbrlFactsTable } from "../components/XbrlFactsTable";
import { XbrlFetchArea } from "../components/XbrlFetchArea";
import { XbrlFilesArea } from "../components/XbrlFilesArea";
import { XbrlTagsArea } from "../components/XbrlTagsArea";
import type { XbrlCompanyFiles } from "../types";

const factsCaption = (c: XbrlCompanyFiles, cik: ReactNode) => (
  <>
    {c.fact_count.toLocaleString()} {c.fact_count === 1 ? "fact" : "facts"} extracted from CIK {cik},{" "}
    {c.tags
      ? `limited to a selection of ${c.tags.length} ${c.tags.length === 1 ? "tag" : "tags"} when it was fetched.`
      : "every tag the company reported."}
  </>
);

/** XBRL Facts: fetch companies' SEC XBRL facts, see the stored files and facts, choose the tags that matter. Areas stack as sections. */
export function XbrlFacts() {
  const [tags, setTags] = useState<string[]>([]);
  const [filesKey, setFilesKey] = useState(0);
  const [company, setCompany] = useState<XbrlCompanyFiles | null>(null);
  const filesChanged = useCallback(() => setFilesKey((k) => k + 1), []);
  const choose = useCallback((c: XbrlCompanyFiles, show: boolean) => {
    setCompany(c);
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
        Download each company’s XBRL facts and annual report from the SEC, keep every fact traceable to its filing, and
        choose which tags you need.
      </p>
      <XbrlFetchArea tags={tags} onSettled={filesChanged} />
      <XbrlFilesArea refreshKey={filesKey} chosen={company?.cik ?? null} onChoose={choose} />
      <section className="card" aria-labelledby="xbrl-facts-title">
        <h2 id="xbrl-facts-title" tabIndex={-1}>
          Facts{company && <>: {company.name || company.company_id}</>}
        </h2>
        {company ? (
          <>
            <p className="help-text">
              {factsCaption(company, <span className="mono">{company.cik}</span>)}
            </p>
            <XbrlFactsTable key={company.cik} cik={company.cik} />
          </>
        ) : (
          <p className="muted">Choose a company in Files to see its facts.</p>
        )}
      </section>
      <XbrlTagsArea tags={tags} onChange={setTags} />
    </div>
  );
}
