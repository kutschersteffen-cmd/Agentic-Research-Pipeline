// What the monitoring tables show instead of stored ids, comparators and fractions. Stored values are not changed.

export interface RuleLike {
  rule_id: string;
  name: string;
  rule_type: string;
  field_id?: string | null;
  comparator: string;
  threshold_value: number;
  company_ids: string[];
  portfolio_ids: string[];
}

export interface AlertLike {
  rule_id?: string | null;
  category: string;
  scope_id: string;
  company_id?: string | null;
  breach_type: string;
}

interface FieldLike { field_id: string; name: string; unit?: string | null }
interface PortfolioLike { portfolio_id: string; name: string }

export const RULE_TYPES = [
  { id: "field_threshold", label: "Company field threshold" },
  { id: "concentration_threshold", label: "Single-name concentration" },
  { id: "portfolio_aggregate_threshold", label: "Portfolio aggregate (WACI-style)" },
] as const;

export const ruleTypeLabel = (type: string): string => RULE_TYPES.find((t) => t.id === type)?.label ?? type;

const COMPARATOR_SYMBOLS: Record<string, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤" };
export const comparatorSymbol = (comparator: string): string => COMPARATOR_SYMBOLS[comparator] ?? comparator;

/** A stored fraction as a percent: at most 2 decimals, trailing zeros dropped (0.05 -> "5%", 0.0712 -> "7.12%"). */
export const percentText = (fraction: number): string => `${Number((fraction * 100).toFixed(2))}%`;

// The rule form shows a concentration threshold in percent and stores a fraction; toPrecision drops float noise (0.07 * 100).
export const fractionToPercent = (fraction: number): number => Number((fraction * 100).toPrecision(12));
export const percentToFraction = (percent: number): number => Number((percent / 100).toPrecision(12));

const portfolioNames = (ids: string[], portfolios: PortfolioLike[]): string =>
  ids.map((id) => portfolios.find((p) => p.portfolio_id === id)?.name ?? id).join(", ");

export function ruleCondition(rule: RuleLike, fields: FieldLike[]): string {
  const comparator = comparatorSymbol(rule.comparator);
  if (rule.rule_type === "concentration_threshold") return `Weight of one company ${comparator} ${percentText(rule.threshold_value)}`;
  const field = fields.find((f) => f.field_id === rule.field_id);
  return [field?.name ?? rule.field_id ?? "", comparator, rule.threshold_value, field?.unit ?? ""].filter((part) => part !== "").join(" ");
}

export function ruleScope(rule: RuleLike, portfolios: PortfolioLike[]): string {
  if (rule.portfolio_ids.length) return portfolioNames(rule.portfolio_ids, portfolios);
  return rule.company_ids.length ? rule.company_ids.join(", ") : "All portfolios";
}

/** A concentration alert: company-scoped and holdings-caused (by construction, see BreachType in the backend). */
export const isConcentrationAlert = (alert: AlertLike): boolean => !!alert.company_id && alert.breach_type === "holdings_caused";

export function alertRuleName(alert: AlertLike, rules: RuleLike[]): string {
  if (!alert.rule_id) return "—";
  return rules.find((r) => r.rule_id === alert.rule_id)?.name ?? "Deleted rule";
}

export function alertScope(alert: AlertLike, rules: RuleLike[], portfolios: PortfolioLike[]): string {
  if (alert.scope_id.startsWith("portfolio__")) return portfolioNames([alert.scope_id.slice("portfolio__".length)], portfolios);
  if (!isConcentrationAlert(alert)) return alert.scope_id;
  const rule = rules.find((r) => r.rule_id === alert.rule_id);
  if (!rule) return alert.company_id!;
  return `${alert.company_id} · across ${rule.portfolio_ids.length ? portfolioNames(rule.portfolio_ids, portfolios) : "all portfolios"}`;
}

/** Observed and Threshold: percent on a concentration alert, the stored number otherwise. */
export function alertNumber(alert: AlertLike, value: number | null | undefined): string {
  if (value == null) return "--";
  return isConcentrationAlert(alert) ? percentText(value) : String(value);
}

export function breachTypeLabel(type: string, category: string): string {
  if (type === "unknown") return category === "news_controversy" ? "—" : "No earlier breach to compare";
  return { holdings_caused: "Holdings-caused", data_caused: "Data-caused", mixed: "Mixed" }[type] ?? type;
}
