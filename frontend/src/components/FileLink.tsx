import { useEffect, useState, type ReactNode } from "react";
import { downloadFile, fetchFile, openFile } from "../api/client";
import { inlineSafe } from "../lib/files";

/** A link to an authenticated file: fetched with the bearer token on click,
 * then saved (default) or opened in a new tab (`open`). */
export function FileLink({ url, name, open = false, className, children }: {
  url: string;
  name: string;
  open?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const [error, setError] = useState("");
  return (
    <>
      <a
        href={url}
        className={className}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setError("");
          (open ? openFile(url, name) : downloadFile(url, name)).catch((err: Error) => setError(err.message));
        }}
      >
        {children}
      </a>
      {error && (
        <span className="error-text" role="alert">
          {" "}
          {error}
        </span>
      )}
    </>
  );
}

/** An object URL for an authenticated file (for <img>/<iframe>), revoked when
 * the url changes or the component unmounts. `safe` is false for types that
 * must only be shown sandboxed (HTML, SVG). */
function useFileUrl(url: string | null): { src: string | null; safe: boolean; error: string } {
  const [state, setState] = useState<{ src: string | null; safe: boolean; error: string }>({ src: null, safe: false, error: "" });
  useEffect(() => {
    setState({ src: null, safe: false, error: "" });
    if (!url) return;
    let href: string | null = null;
    let live = true;
    const hash = url.includes("#") ? url.slice(url.indexOf("#")) : "";
    fetchFile(url)
      .then(({ blob }) => {
        if (!live) return;
        href = URL.createObjectURL(blob);
        setState({ src: href + hash, safe: inlineSafe(blob.type), error: "" });
      })
      .catch((err: Error) => live && setState({ src: null, safe: false, error: err.message }));
    return () => {
      live = false;
      if (href) URL.revokeObjectURL(href);
    };
  }, [url]);
  return state;
}

/** An <iframe> for an authenticated file. Anything that is not safe to show
 * from this origin (HTML from the source inspector, say) is fully sandboxed. */
export function FileFrame({ url, title, className }: { url: string; title: string; className: string }) {
  const { src, safe, error } = useFileUrl(url);
  if (error) return <p className="error-text">{error}</p>;
  if (!src) return <p className="muted">Loading…</p>;
  return <iframe className={className} src={src} title={title} sandbox={safe ? undefined : ""} />;
}

export function FileImg({ url, alt, className }: { url: string; alt: string; className?: string }) {
  const { src, safe } = useFileUrl(url);
  return src && safe ? <img className={className} src={src} alt={alt} /> : <span className="muted">{alt}</span>;
}
