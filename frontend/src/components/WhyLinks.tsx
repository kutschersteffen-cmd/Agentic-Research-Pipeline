import { useState } from "react";
import { api } from "../api/client";
import type { RowLineage } from "../lib/lineage";
import { whyLinks } from "../lib/whyLinks";
import type { PublishedDecision } from "../types";
import { LineagePanel } from "./LineagePanel";

/** "Why: <framework> <tier>" for each published framework with a row for this company; opens its score lineage. */
export function WhyLinks({ issuerId, published }: { issuerId: string; published: PublishedDecision[] }) {
  const [open, setOpen] = useState<RowLineage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const links = whyLinks(issuerId, published);
  if (!links.length) return null;
  return (
    <div>
      {links.map((l) => (
        <button
          key={l.snapshotId}
          className="link-button"
          onClick={() => {
            setError(null);
            api.getRowLineage(l.snapshotId, l.entityId).then(setOpen, (e: Error) => setError(e.message));
          }}
        >
          {l.label}
        </button>
      ))}
      {error && <p className="decision-check-banner" role="alert">{error}</p>}
      {open && <LineagePanel lineage={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
