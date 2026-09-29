/** The engraved rosette security printers use as a seal: concentric rings
 * crossed by rotated ellipses. Decorative only. With `draw`, the strokes
 * engrave themselves once (the moment a person countersigns); reduced motion
 * shows it finished. */
export function Seal({ className, draw = false }: { className?: string; draw?: boolean }) {
  return (
    <svg className={`${className ?? ""}${draw ? " seal-draw" : ""}`} viewBox="0 0 200 200" aria-hidden>
      {[30, 45, 60, 75, 90].map((r) => (
        <circle key={r} cx="100" cy="100" r={r} pathLength={1} />
      ))}
      {[0, 30, 60, 90, 120, 150].map((a) => (
        <ellipse key={a} cx="100" cy="100" rx="90" ry="35" transform={`rotate(${a} 100 100)`} pathLength={1} />
      ))}
    </svg>
  );
}
