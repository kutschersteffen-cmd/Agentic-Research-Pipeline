import type { ReactNode } from "react";

interface FieldProps {
  label: ReactNode;
  /** Explanatory text under the control. */
  hint?: ReactNode;
  /** Validation message; announced when it appears. */
  error?: ReactNode;
  /** Set when the control cannot sit inside the label (it is nested in a
   *  wrapper, or several controls share one label). The caller then owns
   *  the matching id. Otherwise the control is wrapped by the label, which
   *  associates the two without an id. */
  htmlFor?: string;
  className?: string;
  children: ReactNode;
}

/** A labelled control. Every form control in the app goes through this, so
 *  that clicking a label focuses its control and a screen reader announces
 *  the two together -- previously 1 of 140 labels was associated at all. */
export function Field({ label, hint, error, htmlFor, className, children }: FieldProps) {
  const body = (
    <>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
      {error && (
        <span className="field-error" role="alert">
          {error}
        </span>
      )}
    </>
  );
  const classes = className ? `field ${className}` : "field";

  if (htmlFor) {
    return (
      <div className={classes}>
        <label className="field-label" htmlFor={htmlFor}>
          {label}
        </label>
        {body}
      </div>
    );
  }

  return (
    <label className={classes}>
      <span className="field-label">{label}</span>
      {body}
    </label>
  );
}
