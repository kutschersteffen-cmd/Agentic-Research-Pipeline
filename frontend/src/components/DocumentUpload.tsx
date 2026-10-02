import { useState } from "react";
import { api } from "../api/client";
import type { DocType } from "../types";

const TYPES: [DocType, string][] = [
  ["10-K", "Annual report"],
  ["sustainability_report", "Sustainability report"],
  ["DEF-14A", "Proxy statement"],
  ["earnings_transcript", "Earnings transcript"],
  ["investor_presentation", "Investor presentation"],
  ["other", "Other"],
];

interface FileResult { key: string; text: string; ok: boolean }

export function DocumentUpload({
  companies,
  onUploaded,
}: {
  companies: { company_id: string; name: string }[];
  onUploaded: (companyId: string) => void;
}) {
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<FileResult[]>([]);
  const companyId = companies.some((c) => c.company_id === picked) ? picked : companies[0]?.company_id;

  async function upload(docType: DocType, label: string, files: File[]) {
    if (!companyId || files.length === 0) return;
    setBusy(true);
    for (const f of files) {
      const key = `${companyId}/${docType}/${f.name}/${Date.now()}`;
      try {
        await api.uploadDocument(companyId, docType, f);
        setDone((d) => [...d, { key, ok: true, text: `${f.name} (${label}): uploaded` }]);
        onUploaded(companyId);
      } catch (err) {
        setDone((d) => [...d, { key, ok: false, text: `${f.name} (${label}): ${(err as Error).message}` }]);
      }
    }
    setBusy(false);
  }

  return (
    <div>
      <h3>Add your own documents</h3>
      <label className="field-label">
        Company
        <select value={companyId ?? ""} onChange={(e) => setPicked(e.target.value)} disabled={busy}>
          {companies.map((c) => (
            <option key={c.company_id} value={c.company_id}>{c.name}</option>
          ))}
        </select>
      </label>
      {TYPES.map(([t, label]) => (
        <label key={t} className="field-label">
          {label}
          <input
            type="file"
            multiple
            disabled={busy}
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              upload(t, label, files);
            }}
          />
        </label>
      ))}
      {done.length > 0 && (
        <ul aria-live="polite">
          {done.map((r) => (
            <li key={r.key} className={r.ok ? "status-text" : "error-text"}>{r.text}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
