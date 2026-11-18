import { useEffect, useState } from "react";

/** Whole seconds since `active` last became true, counting up every second while it stays true. Used by
 * `ElapsedLine`, so only that line re-renders each second, not the page around it. */
export function useElapsed(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) return;
    const start = Date.now();
    const tick = () => setSeconds(Math.floor((Date.now() - start) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [active]);
  return seconds;
}
