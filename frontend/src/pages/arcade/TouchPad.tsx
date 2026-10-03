export type Pad = { label: string; aria: string; hold: (down: boolean) => void };

/** On-screen hold buttons for phones, shown below the cabinet (hidden on mouse-and-keyboard devices; see .touchpad in index.css). */
export function TouchPad({ pads, maxWidth }: { pads: Pad[]; maxWidth: number }) {
  return (
    <div className="touchpad" style={{ maxWidth, gridTemplateColumns: `repeat(${pads.length}, minmax(0, 1fr))` }}>
      {pads.map((p) => (
        <button key={p.aria} type="button" aria-label={p.aria}
          onPointerDown={(e) => { e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); p.hold(true); }}
          onPointerUp={() => p.hold(false)} onPointerCancel={() => p.hold(false)} onContextMenu={(e) => e.preventDefault()}>
          {p.label}
        </button>
      ))}
    </div>
  );
}
