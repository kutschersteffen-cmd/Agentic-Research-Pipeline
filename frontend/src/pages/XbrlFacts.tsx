import { useState } from "react";
import { XbrlFetchArea } from "../components/XbrlFetchArea";
import { XbrlTagsArea } from "../components/XbrlTagsArea";

/** XBRL Facts: fetch companies' SEC XBRL facts, choose the tags that matter. Areas stack as sections. */
export function XbrlFacts() {
  const [tags, setTags] = useState<string[]>([]);
  return (
    <div className="page">
      <h1>XBRL Facts</h1>
      <p className="help-text">
        Download each company’s XBRL facts and annual report from the SEC, keep every fact traceable to its filing, and
        choose which tags you need.
      </p>
      <XbrlFetchArea tags={tags} />
      <XbrlTagsArea tags={tags} onChange={setTags} />
    </div>
  );
}
