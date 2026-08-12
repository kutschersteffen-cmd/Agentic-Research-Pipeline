import { useState } from "react";
import { api } from "../api/client";
import { InspectorModal } from "./InspectorModal";
import type { SourceCandidate } from "../types";

interface Props {
  candidates: SourceCandidate[];
  selected: Set<string>;
  onToggle: (candidateId: string) => void;
}

/** Ranked/explained source candidate cards with an in-app "Inspect" window
 * for viewing the original document (mostly PDF) before selecting it as a
 * reference -- used for both authority-source ranking and thematic-fund
 * discovery, since both return the same SourceCandidate shape. */
export function SourceDiscoveryPanel({ candidates, selected, onToggle }: Props) {
  const [inspecting, setInspecting] = useState<SourceCandidate | null>(null);

  if (candidates.length === 0) {
    return <p className="help-text">No candidates yet -- run a search above.</p>;
  }

  return (
    <div className="source-card-grid">
      {candidates.map((c) => (
        <div key={c.candidate_id} className={selected.has(c.candidate_id) ? "source-card selected" : "source-card"}>
          <label className="checkbox-label">
            <input type="checkbox" checked={selected.has(c.candidate_id)} onChange={() => onToggle(c.candidate_id)} />
            <strong>{c.name}</strong>
          </label>
          {c.authority_score != null && (
            <span className={c.authority_score >= 0.7 ? "badge badge-high" : c.authority_score >= 0.4 ? "badge badge-mid" : "badge badge-low"}>
              authority {Math.round(c.authority_score * 100)}%
            </span>
          )}
          <p className="muted">{c.url}</p>
          {c.authority_reasoning && <p className="help-text">{c.authority_reasoning}</p>}
          {!c.authority_reasoning && c.snippet && <p className="help-text">{c.snippet}</p>}
          <button className="link-button" onClick={() => setInspecting(c)}>
            Inspect source
          </button>
        </div>
      ))}
      {inspecting && (
        <InspectorModal title={inspecting.name} src={api.inspectSourceUrl(inspecting.url)} onClose={() => setInspecting(null)} />
      )}
    </div>
  );
}
