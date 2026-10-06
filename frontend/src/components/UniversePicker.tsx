import { useState } from "react";
import { api } from "../api/client";
import { InputPicker } from "./InputPicker";

interface Props {
  onResolved: (universePath: string, companyCount: number) => void;
}

/** Uploads a company universe CSV/JSON (company_id, name, ticker, website,
 * cik, country, sector), or picks one saved earlier (by any screen that saves
 * universes), and hands the server-side path back to the caller, so
 * run-creation requests can reference up to thousands of companies by path
 * instead of inlining them. */
export function UniversePicker({ onResolved }: Props) {
  const [status, setStatus] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState("");

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setStatus("Uploading...");
    try {
      const result = (await api.uploadUniverse(file)) as { path: string; company_count: number };
      setStatus(`Loaded ${result.company_count} companies from ${file.name}`);
      onResolved(result.path, result.company_count);
    } catch (err) {
      setStatus(`Upload failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="universe-picker">
      <label className="field-label">
        Company universe (CSV or JSON)
        <input type="file" accept=".csv,.json" onChange={onFile} disabled={busy} />
      </label>
      <p className="help-text">
        Columns: company_id, name, ticker, website, cik, country, sector. Only company_id and name are required;
        adding website and CIK makes document discovery more precise.
      </p>
      <InputPicker
        kind="universe"
        label="Or pick a saved universe"
        value={saved}
        onChange={(o) => {
          setSaved(o?.id ?? "");
          if (!o) return;
          setStatus(`Using ${o.name}`);
          onResolved(o.id, o.count ?? 0);
        }}
      />
      {status && <p className="status-text">{status}</p>}
    </div>
  );
}
