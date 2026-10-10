import { useEffect, useState } from "react";

/** SVG charts draw into a viewBox; at width 100% a fixed 760-unit box
 * shrinks its 13px labels to ~5px on a phone. This sizes the viewBox to the
 * container (capped at `max`) so one unit stays ~one CSS pixel when narrow.
 * Pass the returned ref callback to the chart's wrapper element. */
export function useChartWidth(max: number, min = 280) {
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [width, setWidth] = useState(max);
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      setWidth(Math.min(max, Math.max(min, Math.round(entry.contentRect.width))));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [el, max, min]);
  return [setEl, width] as const;
}
