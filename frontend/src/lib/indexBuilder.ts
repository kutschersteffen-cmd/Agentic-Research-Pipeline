// Index Construction wording (spec showcase-themes-fixes, section 10). Display only: the API's texts are unchanged.

export const DEMO_BANNER =
  "Demo data: reviews on this page run on a built-in synthetic universe of 60 companies. The results describe nothing real.";

export const SOLVER_MISSING =
  "The optimiser is not installed on this server. A calibration that asks for it falls back to step-by-step capping, and the review says so. Ask your administrator.";

type Labelled = { type: string; label: string };
type Method = { name: string; label: string };

/** A rule card's title: the catalogue's label for its type, else the type id. */
export const ruleTitle = (type: string, specs: Labelled[] | undefined): string =>
  specs?.find((s) => s.type === type)?.label ?? type;

/** A review exception as the Result tab shows it: the cvxpy fallback in plain words, anything else as it is. */
export function exceptionText(exception: string, methods: Method[] | undefined): string {
  if (!exception.includes("cvxpy is not installed")) return exception;
  const method = /solver\.method='([^']*)'/.exec(exception)?.[1] ?? "";
  const label = methods?.find((m) => m.name === method)?.label ?? method;
  return `The optimiser is not installed on this server, so this review used step-by-step capping instead of "${label}". Ask your administrator.`;
}

/** An error as this page shows it: no status prefix, and a rule's path named the way the page names the rule. */
export function indexErrorText(message: string, catalogue: { screens: Labelled[]; tilts: Labelled[] } | null): string {
  return message
    .replace(/^\d{3}: /, "")
    .replace(/spec › (screens|tilts) › (\d+) › ([a-z0-9_]+): (?:\3 )?/g, (_m, kind: string, n: string, type: string) => {
      const label = ruleTitle(type, kind === "screens" ? catalogue?.screens : catalogue?.tilts);
      return `${kind === "screens" ? "Screen" : "Tilt"} ${Number(n) + 1} (${label}): `;
    });
}
