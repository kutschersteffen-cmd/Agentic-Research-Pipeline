import type { RefObject } from "react";

export type Phase = "title" | "play" | "over";

/** The shared cabinet frame: canvas, HUD line and the title / game-over card. Styles live in index.css (.cabinet). */
export function Cabinet({ canvasRef, w, h, scale, left, right, phase, headline, sub, cta, hint, flash, onStart }: {
  canvasRef: RefObject<HTMLCanvasElement | null>; w: number; h: number; scale: number;
  left: string; right: string; phase: Phase; headline: string; sub?: string; cta: string; hint?: string; flash?: boolean; onStart: () => void;
}) {
  return (
    <div className="cabinet" style={{ aspectRatio: `${w} / ${h}`, width: `min(100%, ${w * scale}px, calc((100dvh - var(--cab-chrome, 14.5rem)) * ${w / h}))` }}>
      <div className="cabinet-hud" aria-hidden="true">
        <span className={flash ? "cabinet-score cabinet-score-best" : "cabinet-score"}>{left}</span>
        <span>{right}</span>
      </div>
      <canvas ref={canvasRef} width={w} height={h} aria-label="Game area" />
      <div className="cabinet-vignette" aria-hidden="true" />
      {phase !== "play" && (
        <div className="cabinet-card" aria-live="polite">
          <strong>{headline}</strong>
          {sub && <span>{sub}</span>}
          <button type="button" className="cabinet-go" onClick={onStart}>{cta}</button>
          {hint && <span className="cabinet-hint">{hint}</span>}
        </div>
      )}
    </div>
  );
}
