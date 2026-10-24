import { useEffect, useState, type DependencyList } from "react";
import { apiMessage } from "../../lib/projects";

export type VcQuery<T> = { data: T | null; error: string | null; loading: boolean };

/** Runs `load` whenever `deps` change, clearing the last error first; an older run's late answer is dropped.
 * `load` returning null skips the run and clears data and error. On failure `error` holds the API's `detail`. */
export function useVcQuery<T>(load: () => Promise<T> | null, deps: DependencyList): VcQuery<T> {
  const [state, setState] = useState<VcQuery<T>>({ data: null, error: null, loading: true });
  const key = JSON.stringify(deps); // deps are plain values (ids, numbers, flags)
  useEffect(() => {
    const pending = load();
    if (!pending) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    let live = true;
    setState((s) => ({ ...s, error: null, loading: true }));
    pending.then(
      (data) => live && setState({ data, error: null, loading: false }),
      (err) => live && setState({ data: null, error: apiMessage(err), loading: false }),
    );
    return () => {
      live = false;
    };
    // `deps` (as `key`) names everything `load` reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}
