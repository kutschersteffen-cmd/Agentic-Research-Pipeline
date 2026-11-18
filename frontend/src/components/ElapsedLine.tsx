import { elapsedLabel } from "../lib/progress";
import { useElapsed } from "../lib/useElapsed";

/** The status line of a slow action, counting up while it is mounted. `text` builds the whole sentence for a
 * number of seconds. The counter is hidden from screen readers: a live region re-reads its whole text on every
 * change, so a visible counter inside it would be read out once a second. */
export function ElapsedLine({ text }: { text: (seconds: number) => string }) {
  const seconds = useElapsed(true);
  const counter = `${elapsedLabel(seconds)} elapsed. `;
  const [before, after] = text(seconds).split(counter);
  return (
    <p className="muted" role="status">
      {before}
      <span aria-hidden="true">{counter}</span>
      {after}
    </p>
  );
}
