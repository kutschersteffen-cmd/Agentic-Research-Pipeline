/** A lightweight modal for inspecting a source "in its original form" --
 * either a remote document (streamed through the backend's fetch/cache
 * endpoint and rendered in an iframe, so PDFs render natively) or raw
 * text already available client-side (e.g. an uploaded holdings CSV,
 * previewed without a round trip). */
interface Props {
  title: string;
  onClose: () => void;
  src?: string;
  text?: string;
}

export function InspectorModal({ title, onClose, src, text }: Props) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h4>{title}</h4>
          <button className="link-button" onClick={onClose}>
            Close
          </button>
        </div>
        {src && <iframe className="modal-iframe" src={src} title={title} />}
        {text !== undefined && <pre className="modal-text">{text}</pre>}
      </div>
    </div>
  );
}
