import type { ReactNode } from "react";
import { Modal } from "./Modal";
import { ReviewerField } from "./ReviewerField";
import { useReviewer } from "../lib/reviewer";

/** The one confirmation for a decision that binds the firm (ratify, cast):
 * says what will happen, records it against the shared reviewer name, and
 * cannot be confirmed without one. */
export function ConfirmDecision({
  title,
  confirmLabel,
  onConfirm,
  onCancel,
  children,
}: {
  title: string;
  confirmLabel: string;
  onConfirm: (reviewer: string) => void;
  onCancel: () => void;
  children: ReactNode;
}) {
  const [reviewer] = useReviewer();
  const name = reviewer.trim();
  return (
    <Modal title={title} compact onClose={onCancel}>
      {children}
      {name ? <p className="muted">Recorded against the name you entered: {name} (not verified by a login)</p> : <ReviewerField />}
      <div className="toolbar">
        <button onClick={() => onConfirm(name)} disabled={!name}>
          {confirmLabel}
        </button>
        <button className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </Modal>
  );
}
