// Index Construction wording (spec showcase-themes-fixes, section 10). Display only: the API's texts are unchanged.
import type { IndexFieldInventory, IndexStartingUniverse, IndexStartingUniverseDetail } from "../types";

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

// Starting universe (spec index-starting-universe, PR 2).

type Universe = IndexStartingUniverse;
type UniverseDetail = IndexStartingUniverseDetail;

export const DEMO_UNIVERSE = "demo";

/** The select's entry when the universe list cannot be read: the demo universe always works. */
export const DEMO_UNIVERSE_ENTRY: Universe = {
  universe_id: DEMO_UNIVERSE,
  label: "Built-in demo universe (60 synthetic companies)",
  kind: "demo",
  as_of_date: null,
};

/** A starting universe as the select lists it. */
export function universeOption(u: Universe): string {
  if (u.kind === "demo") return u.label;
  return `${u.label} (${u.kind === "file" ? "holdings file" : "portfolio"}, ${u.as_of_date ?? "no date"})`;
}

/** The index id the page proposes: `demo_index`, the file stem lower-cased, or the portfolio id, plus `_index`. */
export function autoIndexId(universeId: string): string {
  if (universeId === DEMO_UNIVERSE) return "demo_index";
  const [kind, ...rest] = universeId.split(":");
  const slug = rest.join(":");
  return `${kind === "file" ? slug.toLowerCase() : slug}_index`;
}

/** The index id after a switch: an id the page proposed follows the universe, one the user typed stays. */
export const nextIndexId = (current: string, from: string, to: string): string =>
  current === autoIndexId(from) ? autoIndexId(to) : current;

/** The banner on every tab: the demo warning, or what the loaded universe is. */
export function universeBanner(u: UniverseDetail | null): string {
  if (!u) return DEMO_BANNER;
  return `Starting universe: ${u.label} (holdings as of ${u.as_of_date}, ${u.company_count} companies). Sizes are a weight proxy and ESG values, where present, are simulated. The results describe no real index.`;
}

/** The loaded universe (null = demo) and the last load error. */
export type UniverseChoice = { detail: UniverseDetail | null; error: string | null };

/** Choose a universe: the demo needs no request; a failed load keeps the previous universe and says why. */
export async function chooseUniverse(
  current: UniverseChoice,
  universeId: string,
  load: (id: string) => Promise<UniverseDetail>,
): Promise<UniverseChoice> {
  if (universeId === DEMO_UNIVERSE) return { detail: null, error: null };
  try {
    return { detail: await load(universeId), error: null };
  } catch (e) {
    return { detail: current.detail, error: e instanceof Error ? e.message : String(e) };
  }
}

/** The fields the rule pickers offer before Decision Studio fields are added. */
export const pickerFields = (choice: UniverseChoice, catalogueFields: IndexFieldInventory): IndexFieldInventory =>
  choice.detail?.fields ?? catalogueFields;

/** A run request on the chosen universe: `universe` only for a loaded one, never `candidates`. */
export const withUniverse = <T extends object>(body: T, choice: UniverseChoice): T & { universe?: string } =>
  choice.detail ? { ...body, universe: choice.detail.universe_id } : body;
