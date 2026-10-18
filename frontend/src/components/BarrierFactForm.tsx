import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { announce } from "../lib/announce";
import { errorDetail } from "../lib/barrier";
import type { BarrierFact, BarrierPrimarySource } from "../types";

/** An analyst enters a fact for a source code cannot read: from a registered source, or with an uploaded PDF. */
export function BarrierFactForm({ code, region, facts, sources, onAdded }: {
  code: string;
  region: string;
  facts: BarrierFact[];
  sources: BarrierPrimarySource[];
  onAdded: () => void;
}) {
  const entered = facts.filter((f) => f.type);
  const [fact, setFact] = useState(entered[0]?.id ?? "");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  const [quote, setQuote] = useState("");
  const [page, setPage] = useState("");
  const [locator, setLocator] = useState("");
  const [sourceKey, setSourceKey] = useState(""); // "" is an uploaded document
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [publisher, setPublisher] = useState("");
  const [asOf, setAsOf] = useState("");
  const [tier, setTier] = useState("primary");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const def = entered.find((f) => f.id === fact);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const upload = sourceKey === "";
      const res = await api.addBarrierFact(code, region, {
        fact, value, unit: unit.trim(), quote, page, locator, source_key: sourceKey,
        ...(upload ? { file, title: title.trim(), publisher: publisher.trim(), as_of: asOf, tier } : {}),
      });
      const msg = `Fact saved${res.page ? `, quote found on page ${res.page}` : ""}. Derive the cell to use it.`;
      setNotice(msg);
      announce(msg);
      setValue("");
      setQuote("");
      setPage("");
      setLocator("");
      onAdded();
    } catch (err) {
      setError(errorDetail(err as Error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)}>
      <div className="inline-fields">
        <label className="field-label">
          Fact
          <select value={fact} onChange={(e) => { setFact(e.target.value); setValue(""); }}>
            {entered.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
        </label>
        <label className="field-label">
          Value
          {def?.type === "boolean" || def?.type === "enum" ? (
            <select value={value} onChange={(e) => setValue(e.target.value)} required>
              <option value="">Choose…</option>
              {(def.type === "boolean" ? ["Yes", "No"] : def.allowed_values ?? []).map((v) => <option key={v}>{v}</option>)}
            </select>
          ) : (
            <input type={def?.type === "date" ? "date" : "text"} value={value} onChange={(e) => setValue(e.target.value)} required />
          )}
        </label>
        {def?.type === "number" && (
          <label className="field-label">
            Unit{def.unit ? ` (blank is ${def.unit})` : ""}
            <input value={unit} onChange={(e) => setUnit(e.target.value)} />
          </label>
        )}
      </div>
      <label className="field-label">
        Quote, word for word
        <textarea value={quote} onChange={(e) => setQuote(e.target.value)} rows={2} required />
      </label>
      <div className="inline-fields">
        <label className="field-label">
          Page
          <input type="number" min={1} value={page} onChange={(e) => setPage(e.target.value)} />
        </label>
        <label className="field-label">
          Locator (optional)
          <input value={locator} onChange={(e) => setLocator(e.target.value)} />
        </label>
        <label className="field-label">
          Source
          <select value={sourceKey} onChange={(e) => setSourceKey(e.target.value)}>
            <option value="">Upload a document</option>
            {sources.filter((s) => s.key).map((s) => <option key={s.key} value={s.key!}>{s.source_name}</option>)}
          </select>
        </label>
      </div>
      {sourceKey === "" && (
        <div className="inline-fields">
          <label className="field-label">
            PDF
            <input type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
          </label>
          <label className="field-label">
            Title
            <input value={title} onChange={(e) => setTitle(e.target.value)} required />
          </label>
          <label className="field-label">
            Publisher
            <input value={publisher} onChange={(e) => setPublisher(e.target.value)} required />
          </label>
          <label className="field-label">
            As of
            <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} required />
          </label>
          <label className="field-label">
            Tier
            <select value={tier} onChange={(e) => setTier(e.target.value)}>
              <option value="primary">primary</option>
              <option value="secondary">secondary</option>
            </select>
          </label>
        </div>
      )}
      <div className="toolbar">
        <button type="submit" disabled={busy || !fact}>{busy ? "Saving…" : "Save fact"}</button>
      </div>
      {notice && <p role="status">{notice}</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
    </form>
  );
}
