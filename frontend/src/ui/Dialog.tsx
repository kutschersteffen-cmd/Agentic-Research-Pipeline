import { useEffect, useRef } from "react";
import type { MouseEvent, ReactNode } from "react";
import { Button } from "./Button";

interface DialogProps {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** Actions along the bottom of the panel. */
  footer?: ReactNode;
}

/** A modal built on the native <dialog>, which is what gives us the parts
 *  the hand-rolled overlay never had: focus trapped inside, Escape closing
 *  it, focus returned to whatever opened it, and the rest of the page inert
 *  to both pointer and screen reader. */
export function Dialog({ title, onClose, children, footer }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    // <dialog> restores focus itself on close(), but React unmounts this
    // element before the cleanup runs, so by then there is nothing to
    // restore from -- keep the reference and put focus back by hand.
    restoreTo.current = document.activeElement as HTMLElement | null;
    if (el && !el.open) el.showModal();
    // A modal owns the viewport; the page behind it should not scroll away.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
      if (el?.open) el.close();
      restoreTo.current?.focus();
    };
  }, []);

  // A click on the dialog element itself landed on the backdrop: the panel
  // inside it stops anything aimed at the content.
  function onBackdropClick(e: MouseEvent<HTMLDialogElement>) {
    if (e.target === ref.current) onClose();
  }

  return (
    <dialog
      ref={ref}
      className="dialog"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={onBackdropClick}
    >
      <div className="dialog-panel">
        <div className="dialog-header">
          <h3>{title}</h3>
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        </div>
        {children}
        {footer && <div className="dialog-footer">{footer}</div>}
      </div>
    </dialog>
  );
}
