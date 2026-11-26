import type { DeskStage } from "../../types";

export const STAGE_LABEL: Record<string, string> = {
  pick_sources: "Picked the sources",
  split: "Split the question",
  search: "Searched the reports",
  rank: "Picked the best passages",
  write: "Wrote the answer",
  check: "Checked every figure",
};

export const seconds = (ms: number) => `${(ms / 1000).toFixed(1)} s`;

/** `Working on it · step k of n` and one row per stage that is not skipped. */
export function StageList({ stages }: { stages: DeskStage[] }) {
  const shown = stages.filter((s) => s.status !== "skipped");
  const k = shown.findIndex((s) => s.status === "running") + 1 || shown.filter((s) => s.status === "done").length;
  return (
    <div className="desk-stages">
      <p className="desk-stages-head" role="status">Working on it · step {k} of {shown.length}</p>
      <ol>
        {shown.map((s) => (
          <li key={s.name} data-status={s.status}>
            <span className="desk-stage-mark" aria-hidden="true">{s.status === "done" ? "✓" : s.status === "failed" ? "✕" : s.status === "running" ? "●" : "○"}</span>
            <span>{STAGE_LABEL[s.name] ?? s.name}</span>
            {s.status === "done" && s.ms !== null && <span className="desk-stage-ms">{seconds(s.ms)}</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}
