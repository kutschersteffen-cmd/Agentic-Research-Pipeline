// API contract: each line fails `tsc -b` when the backend's response schema (from the generated
// schema.gen.ts) no longer fits the type the frontend reads it into, e.g. a renamed or removed field.
// Add a line when you type a new request<...>() against an endpoint with a response model.
import type { components } from "./schema.gen";
import type { Me } from "../lib/reviewKeys";
import type { AlertRule, BIDesignResult, BIEmbedToken, BarrierStalenessReport, DataPointSchema, DatasetSummary, DecisionComparison, DecisionResult, EmergingThemesScheduleConfig, IndexCalibration, IndexReviewResult, MechanismEnvelope, PivotResult, PublishedDecision, QAAnswer, RuleGraph, RuleSuggestions, RunFailure, SearchResponse, SignalComparison, SignalExperimentDetail, SignalExperimentSummary, SignalMethod, SmartSearchAnswer } from "../types";

type S = components["schemas"];
// FastAPI marks fields with defaults optional in the schema, but responses always carry every
// declared field (no route uses response_model_exclude_*), so compare what is actually served.
type Served<T> = T extends (infer U)[] ? Served<U>[] : T extends object ? { [K in keyof T]-?: Served<Exclude<T[K], undefined>> } : T;
type Satisfies<Backend extends Frontend, Frontend> = [Backend, Frontend];
// The backend types these fields loosely (plain dicts, a list[str]); the frontend's narrower
// type is taken on trust until the backend models them.
type MechanismEnvelopeServed = Served<S["MechanismEnvelope"]> & { config: { rule_graph: RuleGraph | null; tier_graph: RuleGraph | null } };
type QAAnswerServed = Served<S["QAAnswer"]> & { spec: { date_range: [string, string] | null } | null };

export type ApiContract = [
  Satisfies<Served<S["AlertRule"]>, AlertRule>,
  Satisfies<Served<S["DataPointSchema"]>, DataPointSchema>,
  Satisfies<Served<S["DatasetSummary"]>, DatasetSummary>,
  Satisfies<Served<S["Comparison"]>, SignalComparison>,
  Satisfies<Served<S["DecisionComparison"]>, DecisionComparison>,
  Satisfies<Served<S["DecisionResult"]>, DecisionResult>,
  Satisfies<Served<S["DesignResult"]>, BIDesignResult>,
  Satisfies<Served<S["EmbedToken"]>, BIEmbedToken>,
  Satisfies<Served<S["EmergingThemesScheduleConfig"]>, EmergingThemesScheduleConfig>,
  Satisfies<Served<S["ExperimentDetail"]>, SignalExperimentDetail>,
  Satisfies<Served<S["ExperimentSummary"]>, SignalExperimentSummary>,
  Satisfies<Served<S["IndexCalibration"]>, IndexCalibration>,
  Satisfies<Served<S["MethodInfo"]>, SignalMethod>,
  Satisfies<MechanismEnvelopeServed, MechanismEnvelope>,
  Satisfies<Served<S["PivotResult"]>, PivotResult>,
  Satisfies<Served<S["Principal"]>, Me>,
  Satisfies<Served<S["PublishedDecision"]>, PublishedDecision>,
  Satisfies<QAAnswerServed, QAAnswer>,
  Satisfies<Served<S["ReviewResult"]>, IndexReviewResult>,
  Satisfies<Served<S["RuleSuggestions"]>, RuleSuggestions>,
  Satisfies<Served<S["RunFailure"]>, RunFailure>,
  Satisfies<Served<S["SearchAnswer"]>, SmartSearchAnswer>,
  Satisfies<Served<S["SearchResponse"]>, SearchResponse>,
  Satisfies<Served<S["StalenessReport"]>, BarrierStalenessReport>,
];
