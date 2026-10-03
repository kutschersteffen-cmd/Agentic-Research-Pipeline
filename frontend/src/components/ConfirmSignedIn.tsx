import type { ReactNode } from "react";
import { Modal } from "./Modal";
import { SignedInAs } from "./SignedInAs";
import { useMe } from "../lib/reviewer";

/** The one confirmation for a decision that binds the firm (ratify, cast):
 * says what will happen, records it against the shared reviewer name, and
 * cannot be confirmed without one. */
export function ConfirmSignedIn({
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
  const name = useMe()?.name ?? "";
  return (
    <Modal title={title} compact noClose onClose={onCancel}>
      {children}
      {name ? <p className="muted">Recorded against {name}, the signed-in user</p> : <SignedInAs />}
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
