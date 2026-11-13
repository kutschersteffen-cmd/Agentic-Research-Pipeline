import { useState } from "react";
import { typedCompany } from "../lib/argusFlow";
import { InputPicker } from "./InputPicker";

export type OneCompany = { name: string; ticker?: string; isin?: string; lei?: string; cik?: string };

const EMPTY = { name: "", ticker: "", isin: "", lei: "", cik: "" };
export type CompanyForm = typeof EMPTY;

/** The five inputs of one company: Name (required), Ticker, ISIN, LEI, CIK. `idPrefix` gives each input an id. */
export function CompanyFields({ value, onChange, idPrefix }: { value: CompanyForm; onChange: (v: CompanyForm) => void; idPrefix?: string }) {
  return (
    <>
      {(["name", "ticker", "isin", "lei", "cik"] as const).map((k) => (
        <label key={k} className="field-label">
          {k === "name" ? "Name" : k.toUpperCase().replace("TICKER", "Ticker")}
          <input id={idPrefix && `${idPrefix}-${k}`} value={value[k]} required={k === "name"} onChange={(e) => onChange({ ...value, [k]: e.target.value })} />
        </label>
      ))}
    </>
  );
}

/** The one way to bring companies into Argus (step 1) and XBRL Facts: upload a list, pick a saved universe, or add one company.
 * The caller decides what each choice does. */
export function CompanyPicker({
  busy,
  onUpload,
  onUniverse,
  onAddOne,
}: {
  busy: boolean;
  onUpload: (file: File) => void;
  onUniverse: (path: string, count: number | null) => void;
  onAddOne: (company: OneCompany) => Promise<boolean>; // false: it failed, so keep what was typed
}) {
  const [one, setOne] = useState(EMPTY);
  const [saved, setSaved] = useState("");
  return (
    <section className="card argus-add" aria-label="Add companies">
      <label className="field-label">
        Upload a list
        <input
          type="file"
          accept=".csv,.json"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) onUpload(file);
          }}
        />
      </label>
      <p className="help-text">CSV or JSON with name and any of lei, isin, cik, ticker, sector, country, company_id.</p>
      <InputPicker
        kind="universe"
        label="Or pick a saved universe"
        value={saved}
        onChange={(o) => {
          setSaved(o?.id ?? "");
          if (o) onUniverse(o.id, o.count ?? null);
        }}
      />
      <form
        className="argus-one"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await onAddOne(typedCompany(one))) setOne(EMPTY);
        }}
      >
        <fieldset>
          <legend>Add one company</legend>
          <CompanyFields value={one} onChange={setOne} idPrefix="argus-one" />
          <button type="submit" disabled={busy}>Add</button>
        </fieldset>
      </form>
    </section>
  );
}
