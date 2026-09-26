import { useEffect, useRef, type ReactNode } from "react";

/** A native modal <dialog>: showModal() supplies the focus trap, inert
 * background, Escape-to-close and focus return. Clicking the backdrop also
 * closes it -- the dialog itself has no padding, so a click whose target is
 * the dialog element can only have landed on the backdrop. */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  // Every close goes through dialog.close() so the browser returns focus to
  // the opener; the resulting close event is what calls onClose.
  const close = () => ref.current?.close();

  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);

  return (
    <dialog ref={ref} className="modal-panel" aria-label={title} onClose={onClose} onClick={(e) => e.target === e.currentTarget && close()}>
      <div className="modal-body">
        <div className="modal-header">
          <h4>{title}</h4>
          <button className="link-button" onClick={close}>
            Close
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}
