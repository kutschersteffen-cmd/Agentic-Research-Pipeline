import { useEffect, useRef, type ReactNode } from "react";

/** A native modal <dialog>: showModal() supplies the focus trap, inert
 * background, Escape-to-close and focus return. Clicking the backdrop also
 * closes it -- the dialog itself has no padding, so a click whose target is
 * the dialog element can only have landed on the backdrop. */
/** `noClose`: the dialog has its own cancel button, so the header link would be a second way out saying the same thing. Esc still closes. */
export function Modal({ title, onClose, children, compact = false, noClose = false }: { title: string; onClose: () => void; children: ReactNode; compact?: boolean; noClose?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  // Every close goes through dialog.close() so the browser returns focus to
  // the opener; the resulting close event is what calls onClose.
  const close = () => ref.current?.close();

  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);

  return (
    <dialog ref={ref} className={compact ? "modal-panel modal-compact" : "modal-panel"} aria-label={title} onClose={onClose} onClick={(e) => e.target === e.currentTarget && close()}>
      <div className="modal-body">
        <div className="modal-header">
          <h3>{title}</h3>
          {!noClose && (
            <button className="link-button" onClick={close}>
              Close
            </button>
          )}
        </div>
        {children}
      </div>
    </dialog>
  );
}
