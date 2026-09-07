import { useState } from "react";
import { RunHistory } from "./RunHistory";
import { ReviewQueue } from "./ReviewQueue";
import type { ReviewableRunKind } from "../types";

const SUB_TABS = [
  { id: "history", label: "Run History" },
  { id: "review", label: "Review Queue" },
] as const;

/** Everything about past and pending runs: the full history/cost log, and
 * the low-confidence-item review queue those runs feed. */
export function Runs() {
  const [sub, setSub] = useState<(typeof SUB_TABS)[number]["id"]>("history");
  const [pendingReview, setPendingReview] = useState<{ kind: ReviewableRunKind; runId: string } | null>(null);

  function openReview(kind: ReviewableRunKind, runId: string) {
    setPendingReview({ kind, runId });
    setSub("review");
  }

  return (
    <div>
      <nav className="sub-nav app-nav">
        {SUB_TABS.map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      {sub === "history" && <RunHistory onOpenReview={openReview} />}
      {sub === "review" && <ReviewQueue pendingReview={pendingReview} />}
    </div>
  );
}
