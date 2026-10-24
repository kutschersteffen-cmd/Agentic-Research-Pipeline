import { flowHref } from "../lib/argusFlow";
import { STEPS } from "../lib/argusStart";

// shortcut: steps 3 to 5 are not built yet (slices 4 and 5), so they are never links.
const BUILT = 2;

/** The one step bar of an Argus flow: finished steps show ✓ and go back with their data unchanged. */
export function StepBar({ flowId, current, reached }: { flowId: string; current: number; reached: number }) {
  return (
    <nav className="argus-steps" aria-label="Steps">
      <ol>
        {STEPS.map((name, i) => {
          const n = i + 1;
          const text = `${n} ${name}`;
          const done = n < reached;
          return (
            <li key={n} aria-current={n === current ? "step" : undefined} className={done ? "argus-step-done" : undefined}>
              {n <= BUILT && n !== current ? <a href={flowHref(flowId, n)}>{text}</a> : text}
              {done && <span aria-label="finished"> ✓</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
