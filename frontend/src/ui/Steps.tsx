import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Button } from "./Button";

export interface Step {
  id: string;
  label: string;
  state: "done" | "current" | "todo";
}

interface StepsProps {
  steps: readonly Step[];
  /** What this sequence produces, for screen readers. */
  label: string;
}

/** The spine of a workflow page: which steps there are, which one you are
 *  on, and how many are left. A page that just stacks cards makes the
 *  analyst infer all three. */
export function Steps({ steps, label }: StepsProps) {
  const current = steps.findIndex((s) => s.state === "current");
  return (
    <ol className="steps" aria-label={label}>
      {steps.map((s, i) => (
        <li key={s.id} className="step" data-state={s.state} aria-current={s.state === "current" ? "step" : undefined}>
          <span className="step-marker" aria-hidden="true">
            {s.state === "done" ? "✓" : i + 1}
          </span>
          <span className="step-label">{s.label}</span>
          {s.state === "current" && <span className="sr-only">(current step, {i + 1} of {steps.length})</span>}
        </li>
      ))}
      {current === -1 && <li className="sr-only">All steps complete</li>}
    </ol>
  );
}

interface StepCardProps {
  step: number;
  title: ReactNode;
  /** Shown instead of the body once the step is behind you. */
  summary?: ReactNode;
  state?: "done" | "current";
  children: ReactNode;
}

/** A step behind you collapses to its one-line result, so the step you are
 *  actually on is the one filling the screen -- and re-opens on demand,
 *  because a decision made two steps ago is still worth changing. */
export function StepCard({ step, title, summary, state = "current", children }: StepCardProps) {
  const [open, setOpen] = useState(state !== "done");
  useEffect(() => setOpen(state !== "done"), [state]);
  const bodyId = `step-${step}-body`;

  return (
    <section className="card step-card" data-state={state} data-open={open}>
      <div className="step-card-head">
        <span className="step-marker" aria-hidden="true">
          {state === "done" ? "✓" : step}
        </span>
        <h3>{title}</h3>
        {summary && <span className="step-card-summary">{summary}</span>}
        {state === "done" && (
          <Button
            variant="ghost"
            size="sm"
            className={summary ? undefined : "push"}
            onClick={() => setOpen((was) => !was)}
            aria-expanded={open}
            aria-controls={bodyId}
          >
            {open ? "Hide" : "Edit"}
          </Button>
        )}
      </div>
      <div id={bodyId} hidden={!open}>
        {children}
      </div>
    </section>
  );
}
