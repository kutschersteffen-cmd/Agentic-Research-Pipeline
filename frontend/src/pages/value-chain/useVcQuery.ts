import { useEffect, useState, type DependencyList } from "react";
import { apiMessage } from "../../lib/projects";

export type VcQuery<T> = { data: T | null; error: string | null; loading: boolean };

/** Runs `fetch` whenever `deps` change, clearing the last error first; an older run's late answer is dropped.
 * `fetch` returning null skips the run. On failure `error` holds the API's `detail`. */
export function useVcQuery<T>(fetch: () => Promise<T> | null, deps: DependencyList): VcQuery<T> {
  const [state, setState] = useState<VcQuery<T>>({ data: null, error: null, loading: true });
  const key = JSON.stringify(deps); // deps are plain values (ids, numbers, flags)
  useEffect(() => {
    const pending = fetch();
    if (!pending) return;
    let live = true;
    setState((s) => ({ ...s, error: null, loading: true }));
    pending.then(
      (data) => live && setState({ data, error: null, loading: false }),
      (err) => live && setState({ data: null, error: apiMessage(err), loading: false }),
    );
    return () => {
      live = false;
    };
    // `deps` (as `key`) names everything `fetch` reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}
