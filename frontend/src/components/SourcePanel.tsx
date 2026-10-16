import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { highlightParts } from "../lib/sourceText";
import type { PageBox } from "../types";
import { FileFrame, FileImg, FileLink } from "./FileLink";

/** A page of a document's stored text, with the cited span when there is one. */
export interface SourceText {
  run_id: string;
  item_key: string;
  doc_id: string;
  doc_type: string;
  page: number | null;
  pages?: number;
  page_start: number;
  page_text: string;
  char_start?: number;
  char_end?: number;
}

export interface ActiveSource {
  title: string;
  src: string;
  quote?: string;
  /** Review workbench: show the stored text instead of the original file. */
  text?: SourceText;
  onSelectQuote?: (c: { doc_id: string; doc_type: string; quote: string }) => void;
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
        <h3 title={source.title}>{source.title}</h3>
        <button className="link-button" onClick={onClose}>
          Close
        </button>
      </div>
      {source.quote && <p className="source-panel-quote">"{source.quote}"</p>}
      {source.text ? (
        <TextView
          key={`${source.text.doc_id}:${source.text.page_start}:${source.text.char_start ?? ""}`}
          source={source}
          initial={source.text}
        />
      ) : (
        <FileFrame className="source-panel-iframe" url={source.src} title={source.title} />
      )}
    </div>
  );
}

/** The stored page text with the span marked inside its highlighted line; a selection becomes a quote. */
function TextView({ source, initial }: { source: ActiveSource; initial: SourceText }) {
  const [text, setText] = useState(initial);
  const [error, setError] = useState("");
  const isPdf = !!source.src && decodeURIComponent(source.src.split("#")[0]).toLowerCase().endsWith(".pdf/raw");
  const [view, setView] = useState<"page" | "text">(isPdf ? "page" : "text");
  const markRef = useRef<HTMLElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const parts =
    text.char_start != null && text.char_end != null
      ? highlightParts(text.page_text, text.char_start - text.page_start, text.char_end - text.page_start)
      : null;

  useEffect(() => markRef.current?.scrollIntoView({ block: "center" }), [text]);

  function goTo(page: number) {
    setError("");
    api
      .getItemSource(text.run_id, text.item_key, text.doc_id, page)
      .then((s) => setText((t) => ({ ...t, page: s.page, pages: s.pages, page_start: s.page_start, page_text: s.page_text })))
      .catch((err: Error) => setError(err.message));
  }

  function onSelect() {
    const sel = window.getSelection();
    if (!sel || !preRef.current?.contains(sel.anchorNode)) return;
    const quote = sel.toString().trim();
    if (quote && source.onSelectQuote) source.onSelectQuote({ doc_id: text.doc_id, doc_type: text.doc_type, quote });
  }

  return (
    <>
      <div className="toolbar">
        {text.page != null && (text.pages ?? 0) > 1 && (
          <>
            <button className="secondary" onClick={() => goTo(text.page! - 1)} disabled={text.page <= 1}>
              Previous page
            </button>
            <span className="muted">
              Page {text.page} of {text.pages}
            </span>
            <button className="secondary" onClick={() => goTo(text.page! + 1)} disabled={text.page >= text.pages!}>
              Next page
            </button>
          </>
        )}
        {isPdf && text.page != null && (
          <button className="secondary" onClick={() => setView(view === "page" ? "text" : "page")}>
            {view === "page" ? "Show text" : "Show page"}
          </button>
        )}
        {source.src && (
          <FileLink url={source.src} name={source.title} open className="link-button">
            Open original
          </FileLink>
        )}
      </div>
      {source.onSelectQuote && view === "text" && <p className="muted">Select text to use it as the correction's source.</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
      {view === "page" && text.page != null ? (
        <PageView rawUrl={source.src} page={text.page} mark={parts?.mark} />
      ) : (
        <pre
          ref={preRef}
          className="source-text"
          onMouseUp={onSelect}
          onKeyUp={onSelect}
          tabIndex={0}
          aria-label={source.onSelectQuote ? "Source text: select text to cite it as the correction's source" : "Source text"}
        >
          {parts ? (
            <>
              {parts.before}
              <span className="source-line-hit">
                {parts.lineBefore}
                <mark ref={markRef}>{parts.mark}</mark>
                {parts.lineAfter}
              </span>
              {parts.after}
            </>
          ) : (
            text.page_text
          )}
        </pre>
      )}
    </>
  );
}

/** The PDF page as an image, the cited span boxed on it where the PDF's own text layer has it. */
function PageView({ rawUrl, page, mark }: { rawUrl: string; page: number; mark?: string }) {
  const [boxes, setBoxes] = useState<PageBox[] | null>(null); // null until searched
  const [loaded, setLoaded] = useState(false);
  useEffect(() => setLoaded(false), [rawUrl, page]);
  useEffect(() => {
    setBoxes(null);
    if (!mark?.trim()) return;
    let live = true;
    api
      .documentPageBoxes(rawUrl, page, mark)
      .then((r) => live && setBoxes(r.boxes))
      .catch(() => live && setBoxes([])); // no boxes: the page still shows
    return () => {
      live = false;
    };
  }, [rawUrl, page, mark]);
  return (
    <div className="source-page">
      {boxes?.length === 0 && <p className="muted">The cited text could not be located on this page image; "Show text" has it marked.</p>}
      <div className="source-page-sheet">
        <FileImg url={api.documentPageUrl(rawUrl, page)} alt={`Page ${page} of the source document${boxes?.length ? ", the cited text boxed" : ""}`} className="source-page-img" onLoad={() => setLoaded(true)} />
        {loaded && boxes?.map((b, i) => (
          <div
            key={i}
            aria-hidden="true"
            ref={i === 0 ? (el) => el?.scrollIntoView({ block: "center" }) : undefined}
            className="source-page-box"
            style={{ left: `${b.l * 100}%`, top: `${b.t * 100}%`, width: `${(b.r - b.l) * 100}%`, height: `${(b.b - b.t) * 100}%` }}
          />
        ))}
      </div>
    </div>
  );
}
