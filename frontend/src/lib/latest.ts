/** Latest request wins: each `next()` hands out a check that is true until `next()` is called again on the same gate. */
export function latestGate(): { next(): () => boolean } {
  let n = 0;
  return {
    next() {
      const mine = ++n;
      return () => mine === n;
    },
  };
}

/** Calls `load` once and shares its promise, but forgets a rejected one so the next call tries again. */
export function memoUntilRejected<T>(load: () => Promise<T>): () => Promise<T> {
  let p: Promise<T> | null = null;
  return () => {
    if (!p) {
      const mine = load();
      p = mine;
      mine.catch(() => {
        if (p === mine) p = null;
      });
    }
    return p;
  };
}
