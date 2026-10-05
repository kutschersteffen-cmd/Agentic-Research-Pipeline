import { useEffect, useRef, useState } from "react";
import "./ProvenanceLoupe.css";
import { FIGS, failed } from "./provenanceLoupeData";

function Fig({ i, sel, on }: { i: number; sel: number | null; on: (i: number | null, toggle: boolean) => void }) {
  const kind = useRef("mouse");
  return (
    <button
      type="button"
      className="n"
      aria-pressed={sel === i}
      onPointerDown={(e) => { kind.current = e.pointerType; }}
      onPointerEnter={(e) => { if (e.pointerType === "mouse") on(i, false); }}
      onClick={(e) => { on(i, e.detail === 0 || kind.current !== "mouse"); }}
    >
      {FIGS[i].model}
    </button>
  );
}

export function ProvenanceLoupe() {
  const [sel, setSel] = useState<number | null>(() =>
    typeof matchMedia === "function" && matchMedia("(min-width:1001px)").matches ? 5 : null);
  const on = (i: number | null, toggle: boolean) => setSel((s) => (toggle && s === i ? null : i));

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") setSel(null); };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, []);

  const d = sel === null ? null : FIGS[sel];
  const bad = d ? failed(d) : false;
  const rows: [string, boolean][] = d
    ? [["quote located", false], ["span offset match", false],
       [sel === 5 ? "digits 1,326 ≠ 1,362" : bad ? "digits equal" : "normalised equal", bad]]
    : [];
  const b = (i: number) => <Fig i={i} sel={sel} on={on} />;

  return (
    <div className="lab-loupe">
      <p className="muted lp-note">Sample data</p>
      <div className="lp-wrap">
        <main>
          <header>
            <div className="lp-m">NORTHWIND HEAVY INDUSTRIES · FY2025 ANNUAL REPORT · AGENT DRAFT 14</div>
            <p>Hover, focus or tap an underlined figure. The loupe opens the exact page span and diffs the model's quote against the verbatim text. Tap again or press Esc to close.</p>
          </header>
          <h2>Capital allocation</h2>
          <p>Northwind committed {b(0)} to green capex, up from {b(1)} a year earlier. R&amp;D spend reached {b(2)}, or {b(3)} of revenue.</p>
          <h2>Segments</h2>
          <table><tbody>
            <tr><td>Drive Systems</td><td>{b(4)}</td></tr>
            <tr><td>Grid &amp; Storage</td><td>{b(5)}</td></tr>
            <tr><td>Industrial Services</td><td>{b(6)}</td></tr>
          </tbody></table>
          <p>Group revenue was {b(7)}; adjusted EBIT margin {b(8)}.</p>
        </main>
        <aside aria-live="polite" aria-label="Loupe" data-open={d ? "1" : "0"}>
          {d ? (
            <>
              <div className="lp-bar lp-m">
                <span>LOUPE · {d.label.toUpperCase()}</span>
                <span>p.{d.page}</span>
                <button type="button" className="lp-x" onClick={() => setSel(null)} aria-label="Close loupe">esc ✕</button>
              </div>
              <div className="lp-pdf">
                <b>{d.section}</b>… {d.before}<mark>{d.quote}</mark>{d.after} …
                <span className="lp-pg">{d.page} / 96</span>
              </div>
              <div className="lp-sec"><h3>Grounding diff</h3>
                <dl className="lp-d">
                  <dt>model</dt><dd>{bad ? <del>{d.model}</del> : d.model}</dd>
                  <dt>source</dt><dd>{bad ? <ins>{d.source}</ins> : d.source}</dd>
                  <dt>hash</dt><dd><span className="lp-chip">sha256:{d.hash}…</span></dd>
                </dl>
              </div>
              <div className="lp-sec"><h3>Re-verify</h3>
                {rows.map(([t, f]) => (
                  <div key={t} className={"lp-v" + (f ? " f" : "")}><span>{t}</span><b>{f ? "FAILED" : "pass"}</b></div>
                ))}
              </div>
            </>
          ) : (
            <div className="lp-hint lp-m">Select a figure to open the loupe.</div>
          )}
          <div className="lp-hint lp-m">hover · focus · tap, tap again or esc closes</div>
        </aside>
      </div>
    </div>
  );
}
