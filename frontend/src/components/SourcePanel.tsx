export interface ActiveSource {
  title: string;
  src: string;
  quote?: string;
}

interface Props {
  source: ActiveSource | null;
  onClose: () => void;
}

/** The right-hand pane of the review split-screen: the original source
 * document (PDF/xlsx/HTML, streamed through the same backend endpoint
 * InspectorModal uses), scrolled to the citation's page via the URL's
 * #page= fragment where one is known. Docked and persistent -- unlike
 * InspectorModal's floating overlay -- specifically so a reviewer moving
 * down a results table doesn't lose their place or re-open a modal for
 * every single citation; clicking a different "view source" link just
 * swaps this pane's contents in place. */
export function SourcePanel({ source, onClose }: Props) {
  if (!source) {
    return (
      <div className="source-panel source-panel-empty">
        <p className="muted">Click "view source" on any citation to see the original document here, side by side with the extracted value.</p>
      </div>
    );
  }
  return (
    <div className="source-panel">
      <div className="source-panel-header">
        <h4 title={source.title}>{source.title}</h4>
        <button className="link-button" onClick={onClose}>
          Close
        </button>
      </div>
      {source.quote && <p className="source-panel-quote">"{source.quote}"</p>}
      <iframe className="source-panel-iframe" src={source.src} title={source.title} />
    </div>
  );
}
