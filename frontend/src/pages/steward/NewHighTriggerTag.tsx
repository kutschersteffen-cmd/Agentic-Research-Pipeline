import type { WorklistRow } from "../../types";

/** Before a row's trigger counts (they stay right-aligned): the company has a stored high trigger first raised in the latest monitoring run. */
export function NewHighTriggerTag({ row }: { row: Pick<WorklistRow, "new_high_trigger"> }) {
  if (!row.new_high_trigger) return null;
  return (
    <span className="proposed-tag wb-new-trigger" title="A high trigger first raised in the latest monitoring run">
      New high trigger
    </span>
  );
}
