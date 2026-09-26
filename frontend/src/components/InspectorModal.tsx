import { Modal } from "./Modal";

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
    <Modal title={title} onClose={onClose}>
      {src && <iframe className="modal-iframe" src={src} title={title} />}
      {text !== undefined && <pre className="modal-text">{text}</pre>}
    </Modal>
  );
}
