import { useEffect, useState } from "react";
import { api, downloadFile } from "../api/client";
import { keyLabel, safeHref, rangeLabel, reportText, secFilingUrl } from "../lib/xbrlTags";
import type { XbrlCompanyFiles } from "../types";
import { Pager } from "./XbrlFactsTable";

const PAGE = 25;
const msg = (err: unknown) => (err as Error).message;
const tagLimit = (tags: string[] | null) =>
  tags ? `Limited to ${tags.length} selected ${tags.length === 1 ? "tag" : "tags"}` : "All tags";

/** One stored file: downloaded with the bearer token, disabled with its reason when the file does not exist. */
function DownloadButton(p: { url: string; name: string; label: string; what: string; missing?: string }) {
  const [state, setState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  async function go() {
    setState({ busy: true, error: null });
    try {
      await downloadFile(p.url, p.name);
      setState({ busy: false, error: null });
    } catch (err) {
      setState({ busy: false, error: msg(err) });
    }
  }
  return (
    <>
      <button type="button" className="link-button" onClick={go} disabled={!!p.missing || state.busy} aria-label={`Download ${p.what}`}>
        {p.label}
      </button>
      {p.missing && <span className="xbrl-download-note muted">{p.missing}</span>}
      {state.error && (
        <span className="xbrl-download-note error-text" role="alert">
          {p.label} download failed ({state.error}).
        </span>
      )}
    </>
  );
}

/** XBRL Facts, Files area: every fetched company with its stored files; choosing a row shows its facts. */
export function XbrlFilesArea(p: {
  refreshKey: number;
  chosen: string | null;
  onChoose: (cik: string | null, show: boolean) => void;
  /** The chosen company as the latest list has it, so captions follow a re-fetch. */
  onCompany: (c: XbrlCompanyFiles | null) => void;
}) {
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: XbrlCompanyFiles[]; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { chosen, onChoose, onCompany } = p;
  const [seenKey, setSeenKey] = useState(p.refreshKey);
  if (seenKey !== p.refreshKey) {
    // A fetch just finished: the newest fetch is listed first, so start there, where a re-fetched company now is.
    setSeenKey(p.refreshKey);
    setOffset(0);
  }

  useEffect(() => {
    let live = true;
    api
      .listXbrlCompanies(offset, PAGE)
      .then((res) => {
        if (!live) return;
        setData(res);
        setError(null);
      })
      .catch((err) => live && setError(msg(err)));
    return () => {
      live = false;
    };
  }, [offset, p.refreshKey]);

  // The most recently fetched company is shown in Facts until the user picks another. The chosen company is looked
  // up in every reloaded list, so a re-fetch updates its caption; one that vanished from a fully visible list
  // clears the choice. (ponytail: a company chosen on another page keeps its last known data until that page loads.)
  useEffect(() => {
    if (!data) return;
    if (!chosen) {
      if (data.items.length) onChoose(data.items[0].cik, false);
      return;
    }
    const found = data.items.find((c) => c.cik === chosen);
    if (found) onCompany(found);
    else if (data.total <= PAGE) {
      onCompany(null);
      onChoose(null, false);
    }
  }, [chosen, data, onChoose, onCompany]);

  return (
    <section className="card" aria-labelledby="xbrl-files-title">
      <h2 id="xbrl-files-title">Files</h2>
      <p className="help-text" id="xbrl-files-hint">
        What is stored for each fetched company. Choose a company’s name to see its facts below. The annual report is
        third-party HTML: it is only downloaded, never opened in this app.
      </p>
      {error && <p className="error-text">Fetched companies could not be loaded ({error}).</p>}
      {!data && !error && <p className="muted">Loading fetched companies…</p>}
      {data && data.total === 0 && <p className="muted">No company has been fetched yet. Start a fetch above.</p>}
      {data && data.total > 0 && (
        <>
          <div className="table-wrap">
            <table className="data-table stack-on-phone xbrl-files">
              <caption className="visually-hidden">
                Fetched companies, {rangeLabel(offset, data.items.length, data.total)}, most recent fetch first
              </caption>
              <thead>
                <tr>
                  <th scope="col">Company</th>
                  <th scope="col">Market</th>
                  <th scope="col">Key</th>
                  <th scope="col">Fetched</th>
                  <th scope="col" className="num">Facts</th>
                  <th scope="col">Annual report</th>
                  <th scope="col">Download</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((c) => {
                  const r = c.report;
                  const who = c.name || c.company_id;
                  const url = (kind: string) => api.xbrlDownloadUrl(c.cik, kind);
                  const href = c.market === "esef" ? safeHref(r?.source_url) : r ? secFilingUrl(c.cik, r.accession) : null;
                  const linkText = c.market === "esef" ? "Open package" : "Open filing on SEC.gov";
                  return (
                    <tr
                      key={c.cik}
                      className="clickable-row"
                      aria-current={c.cik === chosen ? "true" : undefined}
                      onClick={() => onChoose(c.cik, false)}
                    >
                      <th scope="row" data-label="Company">
                        <span>
                          <button
                            type="button"
                            className="link-button xbrl-name"
                            aria-pressed={c.cik === chosen}
                            aria-describedby="xbrl-files-hint"
                            onClick={(e) => {
                              e.stopPropagation();
                              onChoose(c.cik, true);
                            }}
                          >
                            {who}
                          </button>
                          {c.name && <span className="xbrl-sub mono">{c.company_id}</span>}
                        </span>
                      </th>
                      <td data-label="Market">{c.market === "esef" ? "EU (ESEF)" : "US (SEC)"}</td>
                      <td data-label="Key" className="mono">
                        <span>
                          {c.cik}
                          <span className="xbrl-sub">{keyLabel(c.market)}</span>
                        </span>
                      </td>
                      <td data-label="Fetched" className="mono">
                        <span>
                          {c.fetched_at.slice(0, 10)}
                          <span className="xbrl-sub">{c.fetched_at.slice(11, 16)} UTC</span>
                        </span>
                      </td>
                      <td data-label="Facts" className="num">
                        <span>
                          <span className="xbrl-name mono">{c.fact_count.toLocaleString()}</span>
                          <span className="xbrl-sub">{tagLimit(c.tags)}</span>
                        </span>
                      </td>
                      <td data-label="Annual report">
                        {r ? (
                          <span className="xbrl-report">
                            <span>
                              <span className="mono">{r.form}</span>
                              {r.filing_date && <span className="muted"> filed <span className="mono">{r.filing_date}</span></span>}
                            </span>
                            <span className="xbrl-sub">{r.inline_xbrl ? "Inline XBRL" : "Not inline XBRL"}</span>
                            {href ? (
                              <a href={href} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
                                {linkText}<span className="visually-hidden"> (opens in a new tab)</span>
                              </a>
                            ) : (
                              <span className="muted">No package link</span>
                            )}
                          </span>
                        ) : (
                          <span className="muted">{reportText("none")}</span>
                        )}
                      </td>
                      <td data-label="Download">
                        <span className="xbrl-downloads" onClick={(e) => e.stopPropagation()}>
                          <DownloadButton
                            url={url("original")}
                            name={`companyfacts-${c.cik}.json`}
                            label="Original"
                            what={`the companyfacts original for ${who}`}
                            missing={c.original_size ? undefined : "Original not stored"}
                          />
                          <DownloadButton
                            url={url("report")}
                            name={r?.filename ?? `annual-${c.cik}.htm`}
                            label={r?.form ?? "10-K"}
                            what={`the ${r?.form ?? "10-K"} annual report for ${who}`}
                            missing={r ? undefined : "No report stored"}
                          />
                          <DownloadButton url={url("facts")} name={`facts-${c.cik}.jsonl`} label="Facts" what={`the facts file for ${who}`} />
                          <DownloadButton url={url("required")} name={`required-${c.cik}.jsonl`} label="Required" what={`the required revenue and capex file for ${who}`} />
                          <DownloadButton url={url("catalog")} name={`catalog-${c.cik}.jsonl`} label="Catalogue" what={`the tag catalogue for ${who}`} />
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} count={data.items.length} total={data.total} limit={PAGE} noun="companies" onPage={setOffset} />
        </>
      )}
    </section>
  );
}
