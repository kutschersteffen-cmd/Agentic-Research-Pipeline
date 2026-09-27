import type { ReactNode } from "react";

/** The one set of decision controls on every review surface: Approve is the
 * primary action, Override is secondary (and opens its own input), Reject is
 * an outlined danger action rather than a second solid button of equal
 * weight. Same order, same look, everywhere a person decides. */
export function DecisionBar({
  onApprove,
  onOverride,
  onReject,
  overrideOpen,
  disabled,
  approveLabel = "Approve",
  rejectLabel = "Reject",
  children,
}: {
  onApprove: () => void;
  onOverride?: () => void;
  onReject: () => void;
  overrideOpen?: boolean;
  disabled?: boolean;
  approveLabel?: string;
  rejectLabel?: string;
  /** Extra, quieter actions after the decision (e.g. History). */
  children?: ReactNode;
}) {
  return (
    <div className="toolbar decision-bar">
      <button onClick={onApprove} disabled={disabled}>
        {approveLabel}
      </button>
      {onOverride && (
        <button className="secondary" onClick={onOverride} disabled={disabled} aria-expanded={overrideOpen}>
          Override…
        </button>
      )}
      <button className="danger-outline" onClick={onReject} disabled={disabled}>
        {rejectLabel}
      </button>
      {children}
    </div>
  );
}
