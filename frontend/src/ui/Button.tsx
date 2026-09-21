import type { ComponentPropsWithoutRef, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

interface BaseProps extends Omit<ComponentPropsWithoutRef<"button">, "children"> {
  /** primary: the one committing action on a view. secondary: supporting
   *  actions. ghost: inline text actions (the old .link-button). danger:
   *  destructive, and never the default. */
  variant?: Variant;
  size?: "sm" | "md";
  /** Shows a spinner and disables the control -- a pending button must not
   *  stay clickable while its request is in flight. */
  loading?: boolean;
  children?: ReactNode;
}

/** An icon-only button has no text, so it has to carry its own label. */
type ButtonProps = BaseProps & ({ iconOnly: true; "aria-label": string } | { iconOnly?: false });

export function Button(props: ButtonProps) {
  const {
    variant = "primary",
    size = "md",
    loading = false,
    iconOnly = false,
    className,
    disabled,
    type = "button",
    children,
    ...rest
  } = props as BaseProps & { iconOnly?: boolean };

  return (
    <button
      {...rest}
      type={type}
      className={className ? `btn ${className}` : "btn"}
      data-variant={variant}
      data-size={size}
      data-icon-only={iconOnly || undefined}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {loading && <span className="btn-spinner" aria-hidden="true" />}
      {children}
    </button>
  );
}
