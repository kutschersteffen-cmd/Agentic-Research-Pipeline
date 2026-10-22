import type { components } from "./api/schema.gen";

export type S = components["schemas"];
// FastAPI marks fields with defaults optional in the schema, but responses always carry every
// declared field (no route uses response_model_exclude_*), so this is what is actually served.
export type Served<T> = T extends (infer U)[] ? Served<U>[] : T extends object ? { [K in keyof T]-?: Served<Exclude<T[K], undefined>> } : T;

export type DocType =
  | "10-K"
  | "DEF-14A"
  | "sustainability_report"
  | "earnings_transcript"
  | "investor_presentation"
  | "product_page"
  | "research_paper"
  | "transition_plan"
  | "other";

export type JobStatus = "pending" | "running" | "completed" | "partially_completed" | "failed" | "cancelled";

export type RunFailure = Served<S["RunFailure"]>;

export type RfpLibraryEntry = Served<S["RfpLibraryEntryOut"]>;
export type RfpProjectSummary = Served<S["RfpProjectSummary"]>;
export type RfpProject = Served<S["RfpProjectOut"]>;
export type RfpQuestion = Served<S["RfpQuestionOut"]>;

// The run types the Review Queue endpoints exist for -- a subset of every
// run_type, since discovery has no review queue of its own.
export type ReviewableRunKind = "theme" | "extraction" | "financials" | "identity" | "transition_plan" | "tnfd" | "transition_barrier_derivation";

export interface CompanyRef {
  company_id: string;
  name: string;
  ticker?: string | null;
  website?: string | null;
  cik?: string | null;
  lei?: string | null;
  isin?: string | null;
  country?: string | null;
  sector?: string | null;
}

export interface Readiness {
  on_disk: number;
  registered: number;
  parsed: number;
  doc_types: string[];
  last_seen_at: string | null;
  ready: boolean;
}

/** A saved company universe handed from one screen to the next; `from` names the sender. */
export interface UniverseHandoff {
  path: string;
  count: number;
  from: string;
}

export interface RunManifest {
  run_id: string;
  run_type: string;
  created_at: string;
  updated_at: string;
  status: JobStatus;
  params: Record<string, unknown>;
  company_count: number;
  completed_count: number;
  failed_count: number;
  review_count: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens?: number;
  cache_creation_tokens?: number;
  estimated_cost_usd: number;
  batch_saved_usd?: number;
  batch_wait?: { batch_id: string; request_count: number; submitted_at: string; status: string } | null;
  cancel_requested?: boolean;
  model?: string | null;
  error?: string | null;
}

// --- Thematic universe ---

export interface ActivityDefinition {
  activity_id: string;
  name: string;
  in_scope_description: string;
  out_of_scope_description: string;
  seed_keywords: string[];
  core_isic_codes?: string[];
  source_citation?: Citation | null;
  standards_mapping?: ActivityStandardsMapping | null;
}

export type StandardCodeMatch = Served<S["StandardCodeMatch"]>;

export type GicsMatch = Served<S["GicsMatch"]>;

export type ActivityStandardsMapping = Served<S["ActivityStandardsMapping"]>;

export interface ThemeDefinition {
  theme_id: string;
  name: string;
  description: string;
  activities: ActivityDefinition[];
  created_at: string;
}

export interface Citation {
  doc_id: string;
  doc_type: DocType;
  quote: string;
  location?: string | null;
  grounded: boolean;
  page?: number | null;
  sheet?: string | null;
  company_id?: string | null;
  source_filename?: string | null;
  span_text?: string | null;
  char_start?: number | null;
  char_end?: number | null;
  match_method?: "exact" | "normalised" | "fuzzy" | null;
  match_score?: number | null;
  passage_id?: string | null;
  parser_version?: string | null;
}

export interface AgentOpinion {
  stance: string;
  rationale: string;
  citations: Citation[];
  exposure_estimate: "pure_play" | "significant" | "minor" | "none";
}

export interface IndirectExposureResult {
  company_id: string;
  isic_code: string;
  isic_label?: string | null;
  upstream_exposure: number;
  downstream_exposure: number;
  core_sector: boolean;
  icio_edition: string;
  generated_at: string;
}

export interface CompanyMatch {
  company_id: string;
  ticker?: string | null;
  name: string;
  activity_id: string;
  activity_name: string;
  verdict: "include" | "exclude" | "uncertain";
  exposure_estimate: "pure_play" | "significant" | "minor" | "none";
  confidence: number;
  advocate?: AgentOpinion | null;
  opposing?: AgentOpinion | null;
  adjudicator_rationale: string;
  citations: Citation[];
  indirect_exposure?: IndirectExposureResult | null;
  revenue_exposure?: RevenueExposureResult | null;
  flagged_for_review: boolean;
  generated_at: string;
}

// --- Revenue/CapEx exposure resolution ---

export type RevenueCapexMetric = "revenue" | "capex";
export type ExposureDataSource = "catalogue" | "extracted" | "qualitative" | "unresolved";

export type ActivityCatalogueMapping = Served<S["ActivityCatalogueMapping"]>;

export interface MetricExposure {
  value_pct?: number | null;
  source: ExposureDataSource;
  confidence: number;
  matched_catalogue_labels: string[];
  citation?: Citation | null;
  notes: string;
}

export interface RevenueExposureResult {
  activity_id: string;
  revenue: MetricExposure;
  capex: MetricExposure;
  sector_relevant: boolean;
}

// --- Data-point extraction ---

export type FieldDataType = "number" | "currency_amount" | "percentage" | "string" | "boolean" | "enum" | "date";

export type RuleScalar = boolean | string | number;
interface FieldRuleBase { rule_id: string; when?: RuleScalar | null }
export type FieldRule =
  | (FieldRuleBase & { kind: "requires"; field: string; equals: RuleScalar })
  | (FieldRuleBase & { kind: "threshold"; conditions: { field: string; op: ">=" | "<=" | ">" | "<" | "="; value: number }[] })
  | (FieldRuleBase & { kind: "series"; field: string; years: number; trend?: "none" | "down" | "up" })
  | (FieldRuleBase & { kind: "label"; field: string; not_in: string[] })
  | (FieldRuleBase & { kind: "computed"; formula: "ratio_pct" | "sum"; inputs: string[]; tolerance?: number });

export type RuleSuggestions = Served<S["RuleSuggestions"]>;

/** One suggested rule on the Schema screen, with the helper fields it would add (UI only, not served). */
export interface RuleSuggestion { field_id: string; rule: FieldRule; helper_fields: FieldDefinition[] }

export interface FieldDefinition {
  field_id: string;
  name: string;
  description: string;
  data_type: FieldDataType;
  unit?: string | null;
  extraction_instructions: string;
  allowed_values?: string[] | null;
  required: boolean;
  source_doc_types: DocType[];
  seed_keywords: string[];
  status?: "draft" | "released" | "retired";
  rules?: FieldRule[];
}

export interface DataPointSchema {
  schema_id: string;
  name: string;
  description: string;
  fields: FieldDefinition[];
  created_at: string;
  release_flag?: boolean;
}

export interface ExtractedField {
  field_id: string;
  field_name: string;
  value: string | number | boolean | null;
  raw_value_text?: string | null;
  citations: Citation[];
  confidence: number;
  grounded: boolean;
  verifier_notes?: string | null;
  extractor_confidence?: number | null;
  verifier_confidence?: number | null;
  alternatives?: { value: unknown; raw_value_text: string | null; source: string; citations: Citation[] }[];
  conflicting_sources: boolean;
  value_state?: "found" | "not_found" | "not_applicable" | "zero";
  unit?: string | null;
  canonical_value?: string | number | null;
  canonical_unit?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  basis?: string | null;
  qualifiers?: string[] | null;
  scale_applied?: number | null;
  fx_rate?: number | null;
  fx_rate_ref?: string | null;
  review_reasons?: string[] | null;
  checks?: CheckResult[] | null;
  /** Absent on legacy rows. */
  route?: "auto_accept" | "review" | "hold" | null;
  route_reasons?: string[] | null;
}

export interface CheckResult {
  check_id: string;
  layer: number;
  outcome: "pass" | "fail" | "not_applicable";
  severity: "info" | "warn" | "block";
  detail: string;
  threshold_ref?: string | null;
}

export interface HeldDocument {
  doc_id: string;
  title: string;
  covered_entity: string;
  match_status: "confirmed" | "ambiguous" | "mismatch";
}

export interface ExtractionRecord {
  company_id: string;
  /** Absent on runs from before per-field keys. */
  issuer_key?: string | null;
  ticker?: string | null;
  name: string;
  schema_id: string;
  run_id: string;
  fields: ExtractedField[];
  overall_confidence: number;
  needs_review: boolean;
  generated_at: string;
  held_documents?: HeldDocument[] | null;
}

// --- Company Financials: business segments + CapEx + R&D, extracted
// together in a single combined pass per company (they're almost always
// wanted together, so this avoids re-fetching/re-extracting per topic) ---

export interface SegmentMetric {
  value?: number | null;
  raw_value_text?: string | null;
  citations: Citation[];
  grounded: boolean;
}

export interface BusinessSegment {
  name: string;
  description?: string | null;
  description_citations: Citation[];
  revenue: SegmentMetric;
  income: SegmentMetric;
  assets: SegmentMetric;
  currency?: string | null;
  fiscal_period?: string | null;
  confidence: number;
  grounded: boolean;
  verifier_notes?: string | null;
  conflicting_sources: boolean;
}

export interface AmountMetric {
  value?: number | null;
  raw_value_text?: string | null;
  citations: Citation[];
  grounded: boolean;
}

export interface SpendCategory {
  name: string;
  description?: string | null;
  description_citations: Citation[];
  amount: AmountMetric;
  confidence: number;
  grounded: boolean;
  conflicting_sources: boolean;
}

export interface SpendSummary {
  total: AmountMetric;
  description?: string | null;
  description_citations: Citation[];
  categories: SpendCategory[];
  confidence: number;
  grounded: boolean;
  verifier_notes?: string | null;
  conflicting_sources: boolean;
}

export interface CompanyFinancialsRecord {
  company_id: string;
  ticker?: string | null;
  name: string;
  run_id: string;
  currency?: string | null;
  fiscal_period?: string | null;
  segments: BusinessSegment[];
  segments_verifier_notes?: string | null;
  capex: SpendSummary;
  rnd: SpendSummary;
  overall_confidence: number;
  needs_review: boolean;
  generated_at: string;
}

// --- Transition Plan Assessment (Colesanti Senni et al. 2024: "Using AI to
// assess corporate climate transition disclosures") ---

export type IndicatorCategory = "target" | "governance" | "strategy" | "tracking";
export type WalkOrTalk = "walk" | "talk";
export type Verdict = "YES" | "NO" | "NA";

export type TransitionPlanIndicatorDef = Served<S["TransitionPlanIndicator"]>;

export interface IndicatorAssessment {
  number: number;
  identifier: string;
  category: IndicatorCategory;
  walk_or_talk: WalkOrTalk;
  question: string;
  verdict: Verdict;
  answer: string;
  citations: Citation[];
  grounded: boolean;
  confidence: number;
  needs_review: boolean;
  verifier_notes?: string | null;
  assessment_error: boolean;
}

export interface CategoryBreakdown {
  category: IndicatorCategory;
  disclosed_count: number;
  total_count: number;
}

export interface TransitionPlanAssessmentRecord {
  company_id: string;
  ticker?: string | null;
  name: string;
  run_id: string;
  company_sector?: string | null;
  company_location?: string | null;
  report_year?: string | null;
  indicators: IndicatorAssessment[];
  disclosed_count: number;
  walk_disclosed_count: number;
  walk_total_count: number;
  talk_disclosed_count: number;
  talk_total_count: number;
  by_category: CategoryBreakdown[];
  overall_confidence: number;
  needs_review: boolean;
  generated_at: string;
}

// --- Review decisions (per-item audit trail; item_key granularity is
// caller-defined, e.g. "{company_id}:{activity_id}" or "{company_id}:{field_id}") ---

export interface ReviewDecision {
  item_key: string;
  decision: "approve" | "edit" | "correct" | "reject" | "escalate";
  reviewer?: string | null;
  role?: string | null;
  reason_code?: string | null;
  corrected_value?: { value?: unknown } | null;
  correction_citation?: Citation | null;
  snapshot_id?: string | null;
  step?: string | null;
  /** Set by the server on the review workbench: this decision is the signed-in person's. */
  mine?: boolean;
  edited_value?: { value?: unknown } | null;
  comment?: string | null;
  decided_at: string;
}

export type ReviewItemKind = "value" | "sector_code" | "identity" | "quarantined_document" | "restatement_candidate" | "security" | "barrier_cell" | "other";
export type ItemState = "pending" | "first_done" | "second_done" | "disagreed" | "final";

export interface ReviewItem {
  item_key: string;
  kind: ReviewItemKind;
  run_id: string;
  run_type: ReviewableRunKind;
  payload: Record<string, unknown>;
  state: ItemState;
  escalated: boolean;
  high_risk: boolean;
  decision: ReviewDecision | null;
}

/** Extraction `review-decisions`: every decided key's review state. */
export type ReviewStates = Record<string, { state: ItemState; escalated: boolean }>;

export interface EvidenceSpan {
  doc_id: string;
  doc_type: string;
  title: string | null;
  company_id: string | null;
  source_filename: string | null;
  page: number | null;
  quote: string;
  char_start: number;
  char_end: number;
  page_start: number | null;
  page_text: string | null;
}

/** Where a span sits on a PDF page, as fractions of the page size (top-left origin). */
export interface PageBox {
  l: number;
  t: number;
  r: number;
  b: number;
}

export interface ItemSource {
  doc_id: string;
  doc_type: string;
  title: string | null;
  company_id: string | null;
  source_filename: string | null;
  page: number;
  pages: number;
  page_start: number;
  page_text: string;
}

export interface ItemContext {
  item: ReviewItem;
  field_definition: Record<string, unknown> | null;
  value: ExtractedField | null;
  evidence: EvidenceSpan[];
  documents: { doc_id: string; doc_type: string; title: string; pages?: number }[];
  failed_checks: { check_id: string; severity: string; plain: string; detail: string }[];
  route_reasons: string[];
  conflict: { conflicting_sources: boolean; alternatives: { value: unknown; raw_value_text: string | null; source: string; citations: Citation[] }[] } | null;
  /** The verifier's or adjudicator's value, pre-filled when the reviewer opens Correct (E57). */
  suggested_correction?: { value: unknown; citations: Citation[] } | null;
  prior_period: { value: unknown; period_end: string } | null;
  published: { value: unknown; run_id: string; decided_by: string } | null;
  confidence: { final: number; extractor: number | null; verifier: number | null; grounded: boolean; match_methods: string[]; auto_accept_min: number | null } | null;
  state: ItemState;
  escalated: boolean;
  decisions: ReviewDecision[];
  blind: boolean;
  etag: string;
}

/** A final decision on the same field and issuer, from the same kind of document, in an earlier run. */
export interface SimilarDecision {
  run_id: string;
  item_key: string;
  period: string;
  value: unknown;
  decision: ReviewDecision;
}

export interface ItemDecisionBody {
  decision: "approve" | "correct" | "reject" | "escalate";
  reason_code: string;
  corrected_value: Record<string, unknown> | null;
  correction_citation: { doc_id: string; doc_type: string; quote: string } | null;
  comment: string | null;
  context_etag: string;
}

// --- Discovery ---

export interface DiscoveredDocument {
  company_id: string;
  doc_type: DocType;
  url: string;
  local_path?: string | null;
  sha256?: string | null;
  discovered_at: string;
}

export interface DiscoveryCompanyResult {
  company_id: string;
  name: string;
  homepage_used?: string | null;
  homepage_unreachable: boolean;
  crawl_error?: string | null;
  documents_found: DiscoveredDocument[];
  new_events: DocumentEvent[];
  generated_at: string;
}

export interface DocumentEvent {
  event_id: string;
  event_type: "new_document" | "updated_document";
  company_id: string;
  company_name?: string | null;
  document: DiscoveredDocument;
  created_at: string;
}

// --- Identity resolution ---

export type IdentityVerdict = "resolved" | "uncertain" | "unresolved";

export interface EdgarNameMatch {
  ticker: string;
  cik: string;
  title: string;
}

export interface WebSearchHit {
  title: string;
  url: string;
  snippet: string;
}

export interface IdentitySignals {
  edgar_matches: EdgarNameMatch[];
  search_results: WebSearchHit[];
}

export interface IdentityResolutionResult {
  company_id: string;
  input_name: string;
  verdict: IdentityVerdict;
  confidence: number;
  resolved_website?: string | null;
  resolved_cik?: string | null;
  signals: IdentitySignals;
  rationale: string;
  flagged_for_review: boolean;
  generated_at: string;
}

export type DiscoveryScheduleConfig = Served<S["DiscoveryScheduleConfig"]>;

export type TaxonomyResearcherScheduleConfig = Served<S["TaxonomyResearcherScheduleConfig"]>;

export type CalibrationScheduleConfig = Served<S["CalibrationScheduleConfig"]>;

export interface TaxonomyResearchFinding {
  taxonomy_id: string;
  taxonomy_name: string;
  proposed: boolean;
  new_version?: number | null;
  added_activity_names: string[];
  reason: string;
}

export interface DriftFlag {
  source_run_id: string;
  company_id: string;
  activity_id: string;
  old_verdict: string;
  old_confidence: number;
  old_generated_at: string;
  newest_document_at: string;
  reason: string;
}

// --- Taxonomy library ---

export type DerivationMethod =
  | "llm_draft"
  | "industry_anchored"
  | "authority_source"
  | "etf_index_holdings"
  | "news_transcript_mining"
  | "empirical"
  | "emerging_signal_discovery"
  | "merged"
  | "manual";

export type TaxonomyStatus = "draft" | "ratified";

export type Taxonomy = Served<S["Taxonomy"]>;

export type TaxonomyRef = Served<S["TaxonomyRef"]>;

export type ActivityDuplicateCandidate = Served<S["ActivityDuplicateCandidate"]>;

export type TaxonomyComparison = Served<S["TaxonomyComparison"]>;

export type SourceCandidateType = "authority" | "thematic_fund";

export type SourceCandidate = Served<S["SourceCandidate"]>;

export type HoldingsOverlapResult = Served<S["HoldingsOverlapResult"]>;

// --- Emerging Themes Scanner ("Tool 0") ---

export type MentionSourceType = "edgar_fts" | "gdelt" | "regulatory_rss";

export interface MentionCitation {
  mention_id: string;
  source_type: MentionSourceType;
  url: string;
  quote: string;
  grounded: boolean;
}

export type CandidateStatus = "candidate" | "under_review" | "promoted" | "rejected" | "disconfirmed";

export interface CompanyActionEvidence {
  company_id: string;
  cik: string;
  capex_pct_change?: number | null;
  rnd_pct_change?: number | null;
  as_of: string;
}

export type CompanyRole =
  | "beneficiary"
  | "enabler"
  | "adopter"
  | "transition_candidate"
  | "bottleneck_owner"
  | "negatively_exposed"
  | "ambiguous";

export interface CompanyExposure {
  company_id: string;
  role: CompanyRole;
  role_rationale: string;
  risk: number;
  momentum: number;
  evidence_quality: number;
  as_of: string;
}

export interface EmergingThemeCandidate {
  theme_id: string;
  theme_name: string;
  description: string;
  first_detected_date: string;
  signal_velocity: number;
  breadth: number;
  persistence: number;
  novelty: number;
  corroborating_sources: MentionCitation[];
  candidate_sectors_companies: string[];
  rationale: string;
  economic_rationale: string;
  confidence_score: number;
  action_score: number;
  xbrl_corroboration: CompanyActionEvidence[];
  materiality: number;
  contradiction: number;
  contradiction_evidence: MentionCitation[];
  company_exposure: CompanyExposure[];
  status: CandidateStatus;
  promoted_to_taxonomy_id?: string | null;
  promoted_to_taxonomy_version?: number | null;
  decision_reason?: string | null;
  cluster_id: string;
  run_id: string;
  created_at: string;
}

export interface EmergingThemesScheduleConfig {
  enabled: boolean;
  interval_hours: number;
  universe_path?: string | null;
  last_run_id?: string | null;
  next_run_at?: string | null;
}

// --- Engagement (stewardship) ---

export type MilestoneStage =
  | "identified"
  | "contacted"
  | "dialogue_opened"
  | "response_received"
  | "commitment_made"
  | "commitment_verified";

export type EscalationStage =
  | "private_engagement"
  | "joint_engagement"
  | "written_escalation_to_board"
  | "escalation_to_chair"
  | "vote_against_management"
  | "file_or_cofile_resolution"
  | "public_statement";

export type IssueStatus = "open" | "stalled" | "resolved" | "closed";
export type IssueSeverity = "low" | "medium" | "high";
export type TriggerSource = "controversy_screen" | "analyst_raised" | "sla_stall" | "monitoring_rule" | "manual";
export type CorrespondenceType = "letter" | "call" | "meeting" | "email" | "other";
export type CommitmentStatus = "open" | "verified" | "missed";

export type Contact = Served<S["Contact"]>;

export interface CorrespondenceEntry {
  entry_id: string;
  date: string;
  type: CorrespondenceType;
  summary: string;
  doc_ref?: string | null;
  logged_by?: string | null;
}

export interface Commitment {
  commitment_id: string;
  text: string;
  made_at: string;
  target_date?: string | null;
  status: CommitmentStatus;
  validated_by?: string | null;
  validated_at?: string | null;
}

export interface MilestoneTransition {
  stage: MilestoneStage;
  changed_at: string;
  reason: string;
}

export interface EscalationTransition {
  stage: EscalationStage;
  changed_at: string;
  decided_by: string;
  reason: string;
}

export interface EngagementIssue {
  issue_id: string;
  theme: string;
  opened_at: string;
  status: IssueStatus;
  severity: IssueSeverity;
  source: TriggerSource;
  source_detail: string;
  milestone_stage: MilestoneStage;
  milestone_history: MilestoneTransition[];
  escalation_stage: EscalationStage;
  escalation_history: EscalationTransition[];
  correspondence: CorrespondenceEntry[];
  commitments: Commitment[];
  tags: string[];
}

export interface EngagementRecord {
  company_id: string;
  name: string;
  sector?: string | null;
  contacts: Contact[];
  issues: EngagementIssue[];
  created_at: string;
  updated_at: string;
}

export interface TriggerEvent {
  trigger_id: string;
  company_id: string;
  theme: string;
  source: TriggerSource;
  severity: IssueSeverity;
  detail: string;
  detected_at: string;
  raised_issue_id?: string | null;
}

export type OrchestratorAction =
  | "dispatch_research"
  | "await_response"
  | "dispatch_drafting_summary"
  | "await_commitment_target_date"
  | "flag_for_escalation_decision"
  | "no_action";

export interface OrchestratorDecision {
  action: OrchestratorAction;
  reason: string;
}

export interface ResearchDossier {
  dossier_id: string;
  company_id: string;
  issue_id: string;
  generated_at: string;
  summary: string;
  controversy_context: string;
  peer_benchmark_notes: string;
  engagement_history_summary: string;
  recommended_contacts: string[];
  citations: Citation[];
  confidence: number;
  needs_review: boolean;
}

export interface OutreachLetterDraft {
  subject: string;
  body: string;
  recommended_recipient: string;
  citations: Citation[];
}

export interface MeetingTalkingPoints {
  objectives: string[];
  points: string[];
}

export interface MeetingSummaryDraft {
  summary: string;
  commitments_identified: string[];
  follow_up_actions: string[];
}

// --- Voting (proxy) ---

export type ProposalType =
  | "director_election"
  | "say_on_pay"
  | "auditor_ratification"
  | "shareholder_resolution"
  | "merger_acquisition"
  | "capital_action"
  | "other";

export type VotePosition = "for" | "against" | "abstain" | "withhold";
export type CastStatus = "confirmed" | "failed";

export interface Proposal {
  proposal_id: string;
  company_id: string;
  meeting_id: string;
  meeting_date?: string | null;
  proposal_number: string;
  type: ProposalType;
  sponsor: string;
  resolution_text: string;
  management_recommendation?: VotePosition | null;
  supporting_data: Record<string, string>;
  citations: Citation[];
  confidence: number;
  source_doc_id?: string | null;
}

export interface PolicyRecommendation {
  vote: VotePosition;
  rationale: string;
  policy_rule_id?: string | null;
  confidence: number;
  engagement_alignment_flag: boolean;
  engagement_alignment_note?: string | null;
}

export interface HumanVoteDecision {
  vote: VotePosition;
  decided_by: string;
  decided_at: string;
  override_note?: string | null;
  co_signed_by?: string | null;
}

export interface CastConfirmation {
  platform: string;
  cast_at: string;
  confirmation_id: string;
  status: CastStatus;
  detail?: string | null;
}

export interface VoteRecord {
  vote_record_id: string;
  run_id: string;
  proposal: Proposal;
  policy_recommendation?: PolicyRecommendation | null;
  human_decision?: HumanVoteDecision | null;
  cast_confirmation?: CastConfirmation | null;
}

export interface CompanyBallot {
  company_id: string;
  name: string;
  meeting_id: string;
  meeting_date?: string | null;
  votes: VoteRecord[];
  generated_at: string;
}

export interface VoteReviewDecision {
  item_key: string;
  decision: "approve" | "edit" | "reject";
  reviewer?: string | null;
  edited_value?: { vote?: string | null; co_signed_by?: string | null } | null;
  comment?: string | null;
  decided_at: string;
}

// --- Portfolio risk & exposure monitoring ---

export type AggregationMetric = "market_value_sum" | "weighted_avg_datapoint" | "count";

export type PortfolioSummary = Served<S["Portfolio"]>;

export type AggregationRow = Served<S["AggregationRow"]>;

export type AggregationResult = Served<S["AggregationResult"]>;

export interface AnalyticRequest {
  name?: string;
  portfolio_filter?: string[];
  security_filter?: Record<string, string>;
  group_by: string;
  metric: AggregationMetric;
  data_point_field_id?: string | null;
  as_of?: string | null;
  date_range?: [string, string] | null;
  save?: boolean;
}

export interface QAAnswer {
  question: string;
  resolvable: boolean;
  clarification_needed: string;
  spec?: (AnalyticRequest & { analytic_id: string; created_at: string }) | null;
  result?: AggregationResult | null;
  answer_text: string;
}

export type AlertRuleType = "field_threshold" | "concentration_threshold" | "portfolio_aggregate_threshold";
export type AlertComparator = "gt" | "gte" | "lt" | "lte";
export type AlertStatus = "open" | "acknowledged" | "escalated" | "resolved" | "false_positive";
export type BreachType = "holdings_caused" | "data_caused" | "mixed" | "unknown";

export type AlertRule = Served<S["AlertRule"]>;

export type Alert = Served<S["Alert"]>;

export interface SecurityMasterStatus {
  issuers: number;
  identifiers: Record<"ISIN" | "CUSIP" | "SEDOL" | "FIGI" | "LEI" | "CIK" | "PERMID", number>;
  last_load: { status: "ok" | "failed"; detail: string; at: string; content_hash: string } | null;
}
export type OutputKind = "universe" | "run" | "publication" | "taxonomy" | "calibration";
export interface OutputItem {
  kind: OutputKind;
  id: string;
  name: string;
  version: number | null;
  as_of: string | null;
  /** saved · completed/failed/… (runs) · published · draft/ratified (taxonomies) · draft/approved (calibrations) */
  status: string;
  by: string | null;
  run_type?: string;
  count?: number;
  used_by: { kind: string; id: string; label: string; version?: number | null }[];
}
export type SmartSearchAnswer = Served<S["SearchAnswer"]>;
export interface FeedRow {
  feed: "security_master" | "holdings" | "index" | "esg" | "news";
  source_id: string;
  channel: "api" | "file" | null;
  as_of: string | null;
  last_load: { status: "ok" | "failed"; detail: string; at: string; month: string } | null;
  stale: boolean;
  detail: string;
}
export interface DataIssue {
  source: "feed" | "security_master" | "check";
  severity: "block" | "warn" | "info";
  title: string;
  detail: string;
  subject: string;
  ref: string;
  run_id?: string;
}
export interface UnmatchedSecurity {
  holder_id: string;
  kind: "index" | "portfolio";
  as_of: string;
  isin: string | null;
  security_id: string;
  reason: "not in security master" | "ambiguous";
  issuer_key: string;
  candidates: string[];
}

export interface DemoSeedSummary {
  company_count: number;
  security_count: number;
  portfolio_count: number;
  snapshot_dates: string[];
  holding_rows: number;
  climate_observations: number;
  climate_mismatch_companies: string[];
  news_items: number;
  unresolved_security_ids: string[];
}

// --- Data library ---

// From /api/runs/known-companies -- every company_id seen across a run
// type's history, with its most recently seen name/ticker. Not a full
// CompanyRef: only what the result rows themselves carried.
export interface CompanyDirectoryEntry {
  company_id: string;
  name?: string | null;
  ticker?: string | null;
}

export interface CompanyDocumentRow {
  doc_type: string;
  filename: string;
  size_bytes: number;
}

// Browsing cached parsed document text across all runs ---

export interface CachedDocumentRow {
  id: number;
  content_key: string;
  key_kind: string;
  parser_version: string;
  source_suffix: string;
  char_len: number;
  byte_size: number;
  text_sha256: string;
  created_at: string;
  company_id?: string | null;
  doc_type?: string | null;
  title?: string | null;
  filename?: string | null;
}

// Deliberately not `extends CachedDocumentRow` -- the detail endpoint
// doesn't re-send the list-row metadata (id/parser_version/char_len/etc.),
// only the text plus the same company/doc_type/title/filename enrichment.
export interface CachedDocumentDetail {
  content_key: string;
  text_sha256: string;
  full_text: string;
  page_breaks: number[];
  company_id?: string | null;
  doc_type?: string | null;
  title?: string | null;
  filename?: string | null;
}

export type SearchResultType = "company" | "document" | "taxonomy";

export type SearchHit = Served<S["SearchHit"]>;

export type SearchResponse = Served<S["SearchResponse"]>;

// ---- Presentation & Reporting Tool -----------------------------------------

export type AudienceLevel = "executive" | "technical" | "general";
export type Tone = "formal" | "conversational" | "persuasive" | "neutral_analytical";

export type AudienceProfile = Served<S["AudienceProfile"]>;

export type OutputFormat = "pptx" | "docx" | "pdf" | "house_deck";

export type LayoutInstructions = Served<S["LayoutInstructions"]>;

export type ColumnKind = "category" | "number" | "date" | "percent";

export type DatasetColumn = Served<S["DatasetColumn"]>;

export type QuantitativeDataset = Served<S["QuantitativeDataset"]>;

export interface TemplateLayoutInfo {
  index: number;
  name: string;
  placeholder_types: string[];
}

export interface TemplateStyleProfile {
  template_id: string;
  source_filename: string;
  slide_width_emu: number;
  slide_height_emu: number;
  layouts: TemplateLayoutInfo[];
  theme_colors: Record<string, string>;
  major_font?: string | null;
  minor_font?: string | null;
  stored_path: string;
}

export type ChartType =
  | "bar" | "column" | "stacked_column" | "line" | "area" | "pie" | "doughnut"
  | "scatter" | "radar" | "waterfall" | "heatmap" | "table";

export const CHART_TYPES: ChartType[] = [
  "bar", "column", "stacked_column", "line", "area", "pie", "doughnut", "scatter", "radar", "waterfall", "heatmap", "table",
];

export type ChartSpec = Served<S["arp__schemas__reporting__ChartSpec"]>;

export interface TableSpec {
  dataset_id: string;
  columns: string[];
  max_rows: number;
}

export type ContentItem = Served<S["ContentItem"]>;

export type SectionLayoutHint = "standard" | "chart_focus" | "text_only" | "section_header";

export type ReportSection = Served<S["ReportSection"]>;

export interface ReportPlan {
  title: string;
  subtitle: string;
  sections: ReportSection[];
}

export interface ReportRequest {
  title: string;
  qualitative_notes: string;
  datasets: QuantitativeDataset[];
  audience: AudienceProfile;
  layout: LayoutInstructions;
  template_id?: string | null;
  goal?: string;
}

export type ReportStatus = "pending" | "planning" | "plan_ready" | "storyline_ready" | "rendering" | "completed" | "failed";

export interface ReportManifest {
  report_id: string;
  created_at: string;
  updated_at: string;
  status: ReportStatus;
  title: string;
  output_format: OutputFormat;
  template_id?: string | null;
  output_filename?: string | null;
  error?: string | null;
  input_tokens: number;
  output_tokens: number;
  model?: string | null;
  output_files: string[];
}

export type StorylineSlide = Served<S["StorylineSlide"]>;

export type Storyline = Served<S["Storyline"]>;

export interface Finding {
  slide: number;
  slot?: string | null;
  stage: "data" | "lint" | "fit" | "qa";
  rule: string;
  message: string;
}

// ---- Investment Strategy Replication ---------------------------------------

export interface PaperCandidate {
  candidate_id: string;
  title: string;
  url: string;
  snippet: string;
  replication_worthiness_score?: number | null;
  worthiness_reasoning?: string | null;
  suggested_signal_type?: SignalType | null;
}

export type SignalType = "momentum" | "value" | "text_sentiment" | "composite";
export type WeightingScheme = "equal" | "value";
export type RebalanceFrequency = "monthly" | "quarterly" | "annual" | "custom";

export type CompositeSignalComponent = Served<S["CompositeSignalComponent"]>;

export type LegPerformance = Served<S["LegPerformance"]>;

export type ReportedPerformance = Served<S["ReportedPerformance"]>;

export interface ProvenanceInfo {
  extractor_model?: string | null;
  extractor_prompt_version?: string | null;
  verifier_model?: string | null;
  verifier_prompt_version?: string | null;
}

export type StrategySpec = Served<S["StrategySpec"]>;

export interface SpecReviewDecision {
  item_key: string;
  decision: "approve" | "edit" | "reject";
  reviewer?: string | null;
  edited_value?: Record<string, unknown> | null;
  comment?: string | null;
  decided_at: string;
}

export interface SpecReviewState {
  spec_run_id: string;
  spec: StrategySpec;
  approved: boolean;
  history: SpecReviewDecision[];
}

export interface PortfolioPeriodReturn {
  period_end: string;
  long_return_pct: number;
  short_return_pct: number;
  long_short_return_pct: number;
  num_long: number;
  num_short: number;
  benchmark_return_pct?: number | null;
}

export interface BacktestResult {
  result_id: string;
  spec_id: string;
  period_label: string;
  period_start: string;
  period_end: string;
  data_source: string;
  universe_size: number;
  periods: PortfolioPeriodReturn[];
  long_leg: LegPerformance;
  short_leg: LegPerformance;
  long_short: LegPerformance;
  avg_num_long: number;
  avg_num_short: number;
  monthly_turnover_pct?: number | null;
  warnings: string[];
  generated_at: string;
}

export type ReplicationVerdict = "replicated" | "partially_replicated" | "not_replicated" | "decayed_out_of_sample" | "insufficient_data";

export type DeflatedSharpeAssessment = Served<S["DeflatedSharpeAssessment"]>;

export type ReplicationComparisonReport = Served<S["ReplicationComparisonReport"]>;

export type SanityCheckFinding = Served<S["SanityCheckFinding"]>;

export type SanityCheckAssessment = Served<S["SanityCheckAssessment"]>;

export type RegimeBucketPerformance = Served<S["RegimeBucketPerformance"]>;

export type RegimeStratifiedReport = Served<S["RegimeStratifiedReport"]>;

export type ReplicationRunDetail = Served<S["ReplicationRunDetail"]>;

// --- Transition Barrier Assessment (105-cell sector x region
// transition-feasibility matrix: 35 criteria x EU/US/China) ---
// Note H means transition is MORE feasible -- fewer barriers -- not that the
// barrier is high.

export type BarrierRegion = "European Union" | "United States" | "China";
export type BarrierPillar = "Technology" | "Regulation" | "Demand & Economics";
export type BarrierRating = "H" | "M" | "L";
export type BarrierConfidence = "high" | "medium" | "low";
export type BarrierAccessPattern =
  | "periodic_pdf_report"
  | "government_agency_publication"
  | "legal_regulatory_text"
  | "industry_tracker_database"
  | "company_disclosure"
  | "structured_api_or_dashboard";

export interface BarrierPrimarySource {
  source_name: string;
  publisher: string;
  url: string | null;
  access_pattern: BarrierAccessPattern;
  refresh_cadence: string;
  locator: string;
  key: string | null;
}

export interface BarrierFact {
  id: string;
  label: string;
  definition: string;
  type: "number" | "boolean" | "enum" | "date" | null; // null: computed, cannot be entered
  unit: string | null;
  allowed_values: string[] | null;
}

export interface BarrierParam {
  id: string;
  label: string;
  value: number | null;
  unit: string | null;
  rationale: string;
  source: { title: string; url: string | null; locator: string | null } | null;
  by_region: Record<string, { value: number; source: { title: string; url: string | null; locator: string | null } | null }>;
  status: "set" | "open";
  question: string;
}

export interface BarrierCriterion {
  code: string;
  sector: string;
  category: BarrierPillar;
  criterion: string;
  metric: string;
  unit: string;
  rating_rubric: Record<BarrierRating, string>;
  primary_sources: BarrierPrimarySource[];
  rationale: string;
  actions: string[];
  facts: BarrierFact[];
  params: BarrierParam[];
  rule_book_version: number | null;
}

export type BarrierScore = Served<S["BarrierScore"]>;

export interface BarrierMatrixCell extends BarrierScore {
  stale: boolean;
  staleness_days: number;
}

export interface BarrierRegistrySource {
  key: string;
  source_name: string;
  publisher: string;
  used_by_criteria: string[];
  access_pattern: BarrierAccessPattern;
  refresh_cadence: string;
  locator: string;
  url: string | null;
}

export interface BarrierMatrix {
  sectors: string[];
  regions: BarrierRegion[];
  pillars: BarrierPillar[];
  criteria: BarrierCriterion[];
  cells: Record<string, Record<string, BarrierMatrixCell>>;
  distribution: Record<string, Record<BarrierRating, number>>;
}

export interface BarrierCriterionDetail {
  criterion: BarrierCriterion;
  scores: BarrierScore[];
  sources: BarrierRegistrySource[];
}

export type BarrierOutcome = "pass" | "fail" | "unknown" | "mixed";

export interface BarrierCondition {
  text: string;
  outcome: BarrierOutcome;
  clause: string;
}

export interface BarrierLevel {
  outcome: BarrierOutcome;
  detail: string;
  conditions: BarrierCondition[];
}

export interface BarrierValue {
  id: string;
  fact: string;
  value: string | number | boolean | null;
  unit: string | null;
  shown: string | null;
  extracted: string | null;
  document: string | null;
  document_id: number | null;
  page: number | null;
  locator: string | null;
  confidence: BarrierConfidence;
  machine_checked: boolean;
  counted: boolean;
  reason: string | null;
  entered_by: string | null;
  quote: string | null;
  url: string | null;
}

export interface BarrierResult {
  run_id: string;
  rating: BarrierRating | "not_rated" | "conflict";
  confidence: BarrierConfidence;
  missing_facts: string[];
  open_params: string[];
  notes: string[];
  rule_book_version: number;
  levels: Partial<Record<"H" | "M", BarrierLevel>>;
  values: BarrierValue[];
}

export interface BarrierHistoryEntry {
  at: string;
  by: string | null;
  kind: "rating" | "fact" | "choice" | "decision";
  rating?: BarrierRating;
  basis?: "hand_rated" | "derived";
  fact?: string;
  value?: string;
  reason?: string;
  decision?: string;
}

/** GET /cells/{code}/{region}: the current rating, the latest derivation (ratified or not), and the history. */
export interface BarrierCell extends BarrierScore {
  latest_result: BarrierResult | null;
  history: BarrierHistoryEntry[];
}

export interface BarrierFactForm {
  fact: string;
  value: string;
  unit?: string;
  quote?: string;
  page?: string;
  locator?: string;
  source_key?: string;
  file?: File | null;
  title?: string;
  publisher?: string;
  as_of?: string;
  tier?: string;
}

export type BarrierStalenessReport = Served<S["StalenessReport"]>;

export interface BarrierRefreshCoverage {
  total_sources: number;
  automatable: number;
  manual: number;
  enabled_patterns: string[];
}

// --- Decision Mechanism (scoring, ranking, tiering) ---

export type ColumnType = "numeric" | "ordinal" | "boolean" | "categorical" | "identifier" | "text";
export type ColumnRole = "label" | "reference" | "size" | "gate" | "criterion" | "segment" | "excluded";
export type Direction = "higher" | "lower";
export type NormMethod = "percentile" | "minmax" | "zscore";
export type MissingPolicy = "renormalise" | "neutral" | "mean" | "penalise";
export type WeightPreset = "balanced" | "equal" | "entropy" | "manual";
export type CutMode = "quantile" | "breaks" | "absolute";
export type GateOp = "is" | "isnot" | "lt" | "gt" | "eq";
export type GateOutcome = "exclude" | "demote" | "flag";
export type EntityStatus = "scored" | "excluded" | "insufficient";

export const COLUMN_ROLES: ColumnRole[] = ["label", "reference", "size", "gate", "criterion", "segment", "excluded"];

export type ColumnStats = Served<S["ColumnStats"]>;

export type ColumnProfile = Served<S["ColumnProfile"]>;

export type RoleProposal = Served<S["RoleProposal"]>;

// `rule_inputs`: Preview rows typed exactly as the rule engine sees them.
export type DatasetSummary = Served<S["DatasetSummary"]>;

export type Dimension = Served<S["Dimension"]>;

export type Criterion = Served<S["Criterion"]>;

export type GateRule = Served<S["GateRule"]>;

export type VetoRule = Served<S["VetoRule"]>;

export type TierDefinition = Served<S["TierDefinition"]>;

export interface MechanismConfig {
  framework_id: string;
  version: number;
  name: string;
  notes: string;
  ratified: boolean;
  ratified_at?: string | null;
  ratified_by?: string | null;
  created_at: string;
  /** relative: normalised against the other entities. levels: fixed-scale levels from rules over each entity's own data. */
  mode?: ScoringMode;
  level_min?: number;
  level_max?: number;
  /** levels mode: criteria with their level grids. Clusters are `dimensions`. */
  level_criteria?: LevelCriterion[];
  norm: NormMethod;
  winsor_pct: number;
  missing: MissingPolicy;
  weighting: WeightPreset;
  min_coverage_pct: number;
  normalise_within?: string | null;
  min_cohort_size: number;
  require_grounded_coverage: boolean;
  grounded_confidence_min: number;
  dimensions: Dimension[];
  criteria: Criterion[];
  gates: GateRule[];
  cut_mode: CutMode;
  pinned_cuts?: number[] | null;
  veto: VetoRule;
  tiers: TierDefinition[];
  label_column?: string | null;
  size_column?: string | null;
  segment_column?: string | null;
  /** Columns of the table the framework was derived on; anything else it uses comes from its rule graph. */
  source_columns?: string[];
  cluster_threshold: number;
  /** GoRules JSON Decision Model: calculated columns, evaluated per row before scoring. */
  rule_graph?: RuleGraph | null;
  /** GoRules JSON Decision Model setting the final tier after scoring; replaces gates and the dimension floor. */
  tier_graph?: RuleGraph | null;
}

export type ScoringMode = "relative" | "levels";

/** One cell of a level grid: the level an entity gets when `when` (a ZEN expression over its columns) holds. */
export type LevelRule = Served<S["LevelRule"]>;

/** A criterion scored on the fixed scale; rules are tried in order, first match wins, else `otherwise`. */
export interface LevelCriterion {
  id: string;
  name: string;
  dimension_id: string;
  weight: number;
  enabled: boolean;
  rules: LevelRule[];
  otherwise?: number | null;
  /** Whether `otherwise` also applies when a value a rule reads is blank. */
  otherwise_on_blank?: boolean;
  hint?: string;
}

export interface RuleGraph {
  nodes: { id: string; type: string; name?: string; content?: unknown; position?: { x: number; y: number } }[];
  edges: { id: string; sourceId: string; targetId: string; sourceHandle?: string | null; type?: string }[];
}

export type AuditEntry = Served<S["AuditEntry"]>;

export interface MechanismEnvelope {
  config: MechanismConfig;
  audit: AuditEntry[];
}

/** Run types a scoring template can be attached to. */
export type RunScoringKind = "extraction" | "transition_plan" | "financials" | "tnfd";

/** A saved framework and the columns it needs that a table or schema would not supply. */
export type TemplateMatch = Served<S["TemplateMatch"]>;

/** A run's results scored with the template version pinned on it. */
export interface RunDecision {
  framework: { framework_id: string; version: number; name: string };
  /** Only a ratified version can be published. */
  ratified: boolean;
  run_status: string;
  /** When the run's rules step stored this result; absent while the run is still going. */
  scored_at?: string | null;
  missing_columns: string[];
  result: DecisionResult;
  /** Levels mode: [lowest, highest] level, the range an override may set. */
  level_scale?: [number, number] | null;
}

/** A reviewer setting one criterion's level for one entity by hand (levels mode). */
export interface LevelOverride {
  entity_key: string;
  criterion_id: string;
  level: number;
  reason: string;
  reviewer?: string;
  at?: string;
}

// `criterion_id`: Levels mode: the criterion, and when overridden, the rules' level and the override.
export type CriterionContribution = Served<S["CriterionContribution"]>;

export type OverridesView = Served<S["OverridesView"]>;

export type EntityDecision = Served<S["EntityDecision"]>;

export type TierSummary = Served<S["TierSummary"]>;

export type HistogramBin = Served<S["HistogramBin"]>;

// `missing_columns`: Columns the framework uses that this table lacks; such a result cannot be published.
// `tier_inputs`: What a tier graph sees for the first rows (band, score, rank, columns…).
export type DecisionResult = Served<S["DecisionResult"]>;

export type TippingPoint = Served<S["TippingPoint"]>;

export type EntitySensitivity = Served<S["EntitySensitivity"]>;

export type EntityMovement = Served<S["EntityMovement"]>;

export type DecisionComparison = Served<S["DecisionComparison"]>;

// ---------------------------------------------------------------- index

// Named for the index engine specifically: `MissingPolicy` is already taken by
// Decision Studio's missing-data handling, which is a different question about
// a different kind of gap.
export type IndexMissingPolicy = "block" | "fail" | "pass";

export interface RuleBase {
  rule_id?: string;
  label?: string;
  enabled?: boolean;
}

export type ScreenRule = RuleBase &
  (
    | { type: "metric_threshold"; field: string; min_value?: number | null; max_value?: number | null; missing?: IndexMissingPolicy }
    | { type: "flag_exclusion"; field: string; exclude_when?: boolean; missing?: IndexMissingPolicy }
    | { type: "category_screen"; field: string; allow?: string[]; deny?: string[]; missing?: IndexMissingPolicy }
  );

export type SelectionRule = RuleBase &
  (
    | { type: "select_all" }
    | {
        type: "best_in_class_coverage";
        score_field: string;
        group_by?: string;
        target_pct?: number;
        basis?: "float_mcap" | "count";
        buffer_pct?: number;
        higher_is_better?: boolean;
        missing?: IndexMissingPolicy;
      }
    | {
        type: "absolute_threshold";
        score_field: string;
        threshold: number;
        group_by?: string;
        group_thresholds?: Record<string, number>;
        higher_is_better?: boolean;
        on_empty_group?: "leave_empty" | "fallback_relative" | "block";
        fallback_target_pct?: number;
        missing?: IndexMissingPolicy;
      }
    | { type: "top_n"; score_field: string; n: number; group_by?: string; higher_is_better?: boolean; missing?: IndexMissingPolicy }
  );

export type TiltRule = RuleBase &
  (
    | {
        type: "metric_tilt";
        field: string;
        normalisation?: "none" | "max" | "group_max" | "rank_percentile" | "zscore";
        group_by?: string;
        floor?: number;
        ceiling?: number;
        higher_is_better?: boolean;
        missing?: IndexMissingPolicy;
      }
    | { type: "bucket_tilt"; field: string; multipliers: Record<string, number>; default_multiplier?: number; missing?: IndexMissingPolicy }
  );

export interface BaseWeighting {
  scheme: "free_float_mcap" | "equal" | "metric" | "inverse_metric";
  field?: string | null;
  floor?: number;
}

export interface GroupCap {
  dimension: string;
  max_weight: number;
  label?: string;
}

export type RiskModelSpec = Served<S["RiskModelSpec"]>;

export type ConstraintSolver = Served<S["ConstraintSolver"]>;

export interface ConstraintSet {
  single_name_cap?: number | null;
  group_caps: GroupCap[];
  ucits_5_10_40: boolean;
  min_weight?: number | null;
  max_constituents?: number | null;
  min_constituents?: number | null;
  max_iterations?: number;
  solver: ConstraintSolver;
}

export interface DecarbonisationTrajectory {
  enabled: boolean;
  metric_field: string;
  annual_reduction_rate: number;
  base_date?: string | null;
  universe_reduction_pct?: number | null;
  compensate_missed_targets: boolean;
  max_tilt_strength?: number;
  tolerance?: number;
  missing?: IndexMissingPolicy;
}

export interface ConstructionSpec {
  index_currency: string;
  screens: ScreenRule[];
  selection: SelectionRule;
  base_weighting: BaseWeighting;
  tilts: TiltRule[];
  constraints: ConstraintSet;
  trajectory: DecarbonisationTrajectory;
  calendar: { review_frequency: string; selection_lag_days: number; base_level: number };
  rounding: { weight_decimals: number; shares_decimals: number; level_decimals: number };
}

export type IndexCalibration = Served<S["IndexCalibration"]>;

export type StageTrace = Served<S["StageTrace"]>;

export type IndexConstituent = Served<S["Constituent"]>;

export interface IndexState {
  index_id: string;
  review_date: string;
  base_date?: string | null;
  base_metric_value?: number | null;
  required_metric_value?: number | null;
  achieved_metric_value?: number | null;
  universe_metric_value?: number | null;
  shortfall_carry: number;
  binding_constraint: "none" | "trajectory" | "universe_relative";
  divisor?: number | null;
  index_level?: number | null;
}

export type ReviewDiagnostics = Served<S["ReviewDiagnostics"]>;

export type IndexReviewResult = Served<S["ReviewResult"]>;

export interface IndexFieldInventory {
  metrics: string[];
  flags: string[];
  categories: string[];
}

export interface RuleParamSpec {
  name: string;
  kind: string;
  required?: boolean;
  default?: unknown;
  options?: string[];
  help?: string;
}

export interface RuleTypeSpec {
  type: string;
  label: string;
  help: string;
  params: RuleParamSpec[];
}

export interface IndexCatalogue {
  screens: RuleTypeSpec[];
  selection: RuleTypeSpec[];
  base_weighting: { scheme: string; label: string; needs_field: boolean }[];
  tilts: RuleTypeSpec[];
  constraints: RuleParamSpec[];
  constraint_solver: {
    help: string;
    params: RuleParamSpec[];
    available: boolean;
    integer_available: boolean;
    methods: { name: string; label: string; needs_solver: boolean; needs_risk_model: boolean }[];
    risk_model: { help: string; params: RuleParamSpec[] };
  };
  trajectory: { help: string; params: RuleParamSpec[] };
  presets: { name: string; label: string; description: string }[];
  screen_bundles: { name: string; label: string; description: string }[];
  fields: IndexFieldInventory;
}

// Stewardship process page (backend/arp/stewardship/process.py)
export type MetricSource = "live" | "sample" | "portfolio" | "not_built";
export type MetricTone = "neutral" | "good" | "warn" | "bad";

export interface StewardshipMetric {
  label: string;
  value: string | number;
  source: MetricSource;
  tone: MetricTone;
  hint: string | null;
}

export interface EscalationDecisionItem {
  kind: "escalation";
  company_id: string;
  company: string;
  issue_id: string;
  theme: string;
  current: string;
  next: string | null;
  max_step: string;
  promote_tier: boolean;
  reason: string;
}

export interface StyleFlag {
  phrase: string;
  match: string;
  category: string;
  suggestion: string;
  start: number;
  end: number;
  line: number;
  context: string;
}

export type InteractionType = "informational" | "advocacy_pressure" | "other";

export interface OutreachDraft {
  draft_id: string;
  company_id: string;
  company: string;
  issue_id: string;
  theme: string;
  type: string;
  text: string;
  proposed_interaction_type: InteractionType;
  proposed_because: string;
  interaction_type: InteractionType;
  style_flags: StyleFlag[];
  status: "draft" | "approved" | "sent";
  created_by: string;
  created_at: string;
  approved_by?: string;
  history: { at: string; by: string; action: string; note?: string }[];
}

export interface OutreachDecisionItem {
  kind: "outreach";
  draft_id: string;
  company: string;
  theme: string;
  type: string;
  interaction_type: InteractionType;
  proposed_interaction_type: InteractionType;
  proposed_because: string;
  text: string;
  style_flags: StyleFlag[];
  authors: string[];
}

export interface BlocklistEntry {
  phrase: string;
  category: string;
  suggestion?: string;
}

export interface TrackedCommitment {
  company_id: string;
  company: string;
  issue_id: string;
  theme: string;
  commitment_id: string;
  text: string;
  made_at: string;
  target_date: string | null;
  status: "open" | "verified" | "missed";
  overdue: boolean;
  validated_by: string | null;
}

export interface CommitmentDueItem extends TrackedCommitment {
  kind: "commitment_due";
}

export interface TrackedEngagement {
  company_id: string;
  company: string;
  issue_id: string;
  theme: string;
  status: string;
  step: string;
  milestone: string;
}

export interface CaseStudy {
  company: string;
  theme: string;
  status: string;
  text: string;
  style_flags: StyleFlag[];
  provenance: string;
}

export interface ClientExceptionItem {
  kind: "client_exception";
  stream_id: string;
  client: string;
  company_id: string;
  company: string;
  issue_id: string;
  theme: string;
  current: string;
  house: string;
  client_step: string;
  reason: string;
}

export interface TierChangeItem {
  kind: "tier_change";
  issuer_id: string;
  company: string;
  current: string;
  proposed: string;
  rule: string | null;
  reason: string;
}

export interface PolicyDifferenceItem {
  kind: "policy_difference";
  issue_id: string;
  title: string;
  difference: string;
  changes: { field: string; house: unknown; client: unknown; direction?: string }[];
  source: string | null;
  question: string | null;
  direction: string | null;
  flags: string[];
  votes_changed: number | null;
  recommendation: string;
  decision: { decision: string; decided_by: string; note?: string } | null;
}

export interface StewardshipStage {
  id: string;
  number: number;
  title: string;
  layer: "house" | "client";
  summary: string;
  status: "live" | "partial" | "not_built";
  metrics: StewardshipMetric[];
  decisions: (
    | EscalationDecisionItem
    | ClientExceptionItem
    | OutreachDecisionItem
    | CommitmentDueItem
    | TierChangeItem
    | PolicyDifferenceItem
  )[];
  details: { label: string; rows: Record<string, string | number>[] }[];
  can_build?: boolean;
}

export interface StewardshipFlow {
  stream: { stream_id: string; name: string; mandate?: Record<string, string> | null };
  data_note: string;
  stages: StewardshipStage[];
  edges: { from: string; to: string; label?: string }[];
}

export interface StewardshipStream {
  stream_id: string;
  name: string;
  kind: "house" | "client";
}

// Stage studios: versioned house policies (backend/arp/stewardship/policies.py)
export type StewardPolicyId = "monitoring_rules" | "coverage_rules" | "escalation_rules" | "phrase_blocklist" | "house_voting";

export interface PolicyVersionMeta {
  version: number;
  note: string;
  created_by: string;
  created_at: string | null;
}

export interface PolicyActivation {
  version: number;
  approved_by: string;
  approved_at: string;
}

export interface StewardPolicyInfo {
  policy_id: StewardPolicyId;
  active_version: number;
  active: Record<string, unknown>;
  versions: PolicyVersionMeta[];
  activations: PolicyActivation[];
}

export interface CatalogueParameter {
  type: "number" | "bool" | "enum" | "map" | "field";
  description: string;
  unit?: string;
  values?: string[];
  stricter?: "higher" | "lower" | boolean;
}

export interface CatalogueIssue {
  issue_id: string;
  category: string;
  title: string;
  description: string;
  resolution_categories: string[];
  parameters: Record<string, CatalogueParameter>;
  vote_targets: string[];
  data_fields: string[];
}

export interface IssueCatalogue {
  version: string;
  position_actions: string[];
  categories: string[];
  issues: CatalogueIssue[];
}

export interface VotingPosition {
  issue_id: string;
  action: string;
  vote_target: string;
  parameters: Record<string, unknown>;
  scope: Record<string, unknown>;
  rationale: string;
}

export interface VotingPolicy {
  policy_id: string;
  version: string;
  positions: VotingPosition[];
  [key: string]: unknown;
}

export interface CoveragePreview {
  companies: number;
  distribution_candidate: Record<string, number>;
  distribution_active: Record<string, number>;
  rules_fired: Record<string, number>;
  changes: { issuer_id: string; company: string; from: string; to: string; rule: string; reason: string }[];
}

export interface MonitoringTrigger {
  issuer_id: string;
  company: string;
  sector: string;
  type: string;
  theme: string;
  severity: "low" | "medium" | "high";
  rule: string;
  reason: string;
  engagement_id: string | null;
}

export interface MonitoringPreview {
  companies: number;
  triggers_candidate: number;
  triggers_active: number;
  flagged_candidate: number;
  flagged_active: number;
  by_rule_candidate: Record<string, number>;
  by_rule_active: Record<string, number>;
  newly_flagged: { issuer_id: string; company: string }[];
  no_longer_flagged: { issuer_id: string; company: string }[];
  triggers: MonitoringTrigger[];
}

export interface EscalationRecommendation {
  source: "sample" | "live";
  company_id: string;
  company: string;
  issue_id: string | null;
  theme: string;
  tier: string | null;
  max_step: string;
  current: string;
  recommended: string;
  escalate: boolean;
  promote_tier: boolean;
  rule: string;
  reason: string;
}

export interface EscalationPreview {
  engagements: number;
  escalations_candidate: number;
  escalations_active: number;
  promotions_candidate: number;
  promotions_active: number;
  by_rule_candidate: Record<string, number>;
  by_rule_active: Record<string, number>;
  changes: Record<string, string>[];
  recommendations: EscalationRecommendation[];
}

export interface ClientEscalationPreview {
  engagements: number;
  higher_candidate: number;
  higher_active: number;
  rows: Record<string, string | boolean>[];
}

export interface ClientReport {
  client: string;
  stream_id: string;
  as_of: string;
  summary: string[];
  tiers: { tier: string; companies: number }[];
  votes: { vote: string; house: number; client: number }[];
  engagements: Record<string, string>[];
  exceptions: Record<string, string>[];
  policy_decisions: Record<string, string>[];
  notes: string[];
}

export type ProgramParams = Served<S["ProgramParams"]>;

export interface ProgramTarget {
  issuer_id: string;
  company: string;
  theme: string;
  reason: string;
  portfolio_pct: number;
  leverage: number;
  tier: string | null;
  origin: "house" | "client_only";
  weight_ratio: number;
  step_now: string;
  house_step: string;
  client_step: string;
  above_house: boolean;
  max_step: string;
  at_vote_step: boolean;
}

export interface ProgramSimulation {
  client: string;
  benchmark: string;
  vehicle: string;
  voting_policy: string;
  escalation_rules: string;
  params: ProgramParams;
  kpis: Record<string, number>;
  holdings: { company: string; sector: string; clti: number | null; benchmark_pct: number; portfolio_pct: number; active_pct: number; role: string }[];
  candidates: number;
  targets: ProgramTarget[];
  votes: { company: string; resolution: string; house: string; client: string; sanction: string }[];
  checks: { check: string; value: string; status: "green" | "amber" | "red"; note: string }[];
  data_note: string;
  constituents: number;
  score_note: string | null;
}

export interface ProgramVersion {
  version: number;
  params: ProgramParams;
  targets: { issuer_id: string; company: string; theme: string; client_step: string; origin: string }[];
  kpis: Record<string, number>;
  proposed_by: string;
  approved_by: string;
  approved_at: string;
}

export interface ProgramRun {
  as_of: string;
  version: number;
  kpis: Record<string, number>;
  alerts: number;
  recorded_by: string;
}

export interface ProgramMonitor {
  approved: { version: number; proposed_by: string; approved_by: string; approved_at: string; kpis: Record<string, number> } | null;
  calibration_changed?: boolean;
  kpis?: Record<string, number>;
  alerts?: { kpi: string; status: "green" | "amber" | "red" | "not_built"; detail: string }[];
  targets?: Record<string, string>[];
}

export interface BenchmarkInfo {
  benchmark_id: string;
  name: string;
  as_of: string;
  source: string;
  constituents: number;
  dropped: number;
  uploaded_by: string;
  uploaded_at: string;
}

export interface VotingPreview {
  resolutions: number;
  changed: number;
  base_votes: Record<string, number>;
  other_votes: Record<string, number>;
  affected_by_issue: Record<string, number>;
  masked_by_issue: Record<string, number>;
  changed_rows: { resolution_id: string; category: string; base_vote: string; other_vote: string; issues: string[] }[];
  unused_parameters: Record<string, string[]>;
  no_vote_effect: string[];
}

/** A ratified Decision Studio result, frozen for Steward Workflow and Index Construction. */
// `cuts_held_from`: The first publication of this framework version, whose cut-points were reused.
export type PublishedDecision = Served<S["PublishedDecision"]>;

export interface DecisionInput {
  snapshot_id: string;
  framework_name: string;
  framework_version: number;
  dataset_name: string;
  as_of?: string | null;
  published_by: string;
  published_at: string;
  field: string;
  rows: number;
  matched: number;
}

/** One TNFD recommendation as extracted for a company (subset of the backend's DisclosureExtraction). */
export interface TnfdDisclosure {
  recommendation_id: string;
  disclosed: boolean;
  summary: string | null;
  summary_citations: Citation[];
  confidence: number;
  grounded: boolean;
  verifier_notes: string | null;
}

export interface TnfdMetric {
  category: string;
  metric_name: string;
  value: number | null;
  unit: string | null;
  grounded: boolean;
}

/** A company's TNFD extraction (subset of the backend's TNFDExtractionRecord). */
export interface TnfdRecord {
  company_id: string;
  ticker: string | null;
  name: string;
  as_of: string;
  disclosures: TnfdDisclosure[];
  core_global_metrics: TnfdMetric[];
  missing_recommendations: string[];
  overall_confidence: number;
  needs_review: boolean;
}

export type ExtractionProfile = "custom" | "financials" | "tnfd" | "transition_plan";

/** Per-run step settings from the node editor; a key left out keeps the app's setting. */
export interface StepSettings {
  pre_identity_enabled?: boolean | null;
  pre_content_search_enabled?: boolean | null;
  pre_document_mgmt_enabled?: boolean | null;
  pre_parse_index_enabled?: boolean | null;
  hybrid_retrieval_enabled?: boolean | null;
  xbrl_facts_enabled?: boolean | null;
  llm_model?: string | null;
  llm_verifier_model?: string | null;
  grounding_fuzzy_threshold?: number | null;
  confidence_review_threshold?: number | null;
  evidence_max_chunks?: number | null;
  rerank_enabled?: boolean | null;
  extraction_group_size?: number | null;
  vision_fallback_enabled?: boolean | null;
}
export type StepSettingKey = keyof StepSettings;

export interface StepSettingInfo {
  label: string;
  type: "bool" | "number" | "model";
  help: string;
  min?: number;
  max?: number;
  step?: number;
}

export interface PipelineNode {
  id: string;
  label: string;
  about: string;
  /** Runs once per item (field, indicator or company); false for the company-level steps. */
  per_item: boolean;
  settings: StepSettingKey[];
  /** A step before extraction that each run switches on or off. */
  optional?: boolean;
}

/** A profile's steps, read from the per-item graph the backend runs. */
export interface PipelineShape {
  profile: ExtractionProfile;
  nodes: PipelineNode[];
  edges: { source: string; target: string; conditional: boolean }[];
  setting_info: Record<StepSettingKey, StepSettingInfo>;
  defaults: Required<{ [K in StepSettingKey]: NonNullable<StepSettings[K]> }>;
  /** Run modes (cheap / normal / max): each fills these step settings. */
  modes: Record<string, StepSettings>;
}

export interface RunSteps {
  /** Items through each step, for the run or the company asked for. */
  counts: Record<string, number>;
  /** Seconds those items spent in each step, summed. */
  seconds: Record<string, number>;
  /** What each step before extraction found: one company's findings, or numbers summed across the run. */
  details: Record<string, Record<string, string | number | boolean | string[] | null>>;
  /** Still counting: the run is executing in this server process. */
  live: boolean;
  settings: StepSettings | null;
  /** Set when this run is a restart of another from one of its steps. */
  restarted_from: { run_id: string; step: string; company_count: number } | null;
  /** Started from the Extraction screen, so it can be restarted from a step. */
  restartable: boolean;
}

export interface RunCompany {
  company_id: string;
  name: string;
  /** review: a step before extraction stopped it, and its error report waits in the review queue. */
  status: "done" | "failed" | "review" | "waiting";
}

/** Superset BI designer (/api/bi). A refused plan is a 200 with `rejected` reasons and no dashboard. */
export type BIChartSpec = Served<S["ChartSpec-Output"]>;

export type BIChartPlan = Served<S["ChartPlan"]>;

export type BIDesignResult = Served<S["DesignResult"]>;

export type BIEmbedToken = Served<S["EmbedToken"]>;

/** An embeddable Superset dashboard (slug starts with `arp-`), from GET /api/bi/dashboards. */
export type DashboardItem = Served<S["DashboardItem"]>;

/** Projects (/api/projects): a named data set plus its dashboards. */
export type ProjectSummary = Served<S["ProjectSummary"]>;

export type OpenedDashboard = Served<S["OpenedDashboard"]>;

export type OpenResult = Served<S["OpenResult"]>;

export type ExportedDashboard = Served<S["ExportedDashboard"]>;

export interface HolderStatus {
  holder_id: string;
  kind: "index" | "portfolio";
  name: string;
  source: "api" | "file";
  as_of: string | null;
  last_pull_at: string | null;
  last_error: string | null;
  expected_as_of: string;
  stale: boolean;
  age_days: number | null;
}
export interface RowError {
  row: number | null;
  column: string | null;
  message: string;
}
export interface IntakeResult {
  status: "written" | "unchanged";
  revision: number;
  rows: number;
  unresolved: string[];
}

export interface UnifiedTrigger {
  trigger_id: string;
  source: "risk_alert" | "stewardship";
  issuer_id: string;
  type: string;
  theme: string;
  severity: "low" | "medium" | "high";
  reason: string;
  status: "open" | "acknowledged" | "resolved";
  first_seen_month: string;
  is_new: boolean;
  rule: string;
}

// XBRL fact pipeline (wire format: snake_case, mirrors backend arp/xbrl_pipeline/models.py)
export interface XbrlTag {
  taxonomy: string;
  concept: string;
  label: string | null;
  data_type: string | null;
  period_type: string | null;
  balance: string | null;
  documentation: string | null;
  deprecated: boolean;
  extension: boolean;
  seen_count: number;
}

export type XbrlMarket = "sec" | "esef";
/** The Fetch market control: Auto routes each company by its own data. */
export type XbrlRunMarket = "auto" | XbrlMarket;

export interface XbrlCompanyStatus {
  market: XbrlMarket | null; // null for unrouted and no_source rows
  company_id: string;
  cik: string | null;
  status: "ok" | "unchanged" | "no_cik" | "no_lei" | "not_found" | "unrouted" | "no_source";
  note?: string | null;
  source_sha: string | null;
  fact_count: number;
  report: "stored" | "unchanged" | "none" | "error";
}

export interface XbrlReportMeta {
  accession: string;
  form: string;
  filing_date: string | null;
  source_url: string;
  primary_document: string;
  filename: string;
  sha256: string;
  size: number;
  inline_xbrl: boolean;
}

export interface XbrlCompanyFiles {
  market: XbrlMarket;
  cik: string;
  company_id: string;
  name: string | null;
  fetched_at: string;
  fact_count: number;
  tags: string[] | null;
  original_size: number;
  report: XbrlReportMeta | null;
}

export interface XbrlFact {
  market: XbrlMarket;
  company_id: string;
  cik: string;
  taxonomy: string;
  concept: string;
  unit: string;
  value: number;
  period_start: string | null;
  period_end: string;
  fiscal_year: number | null;
  fiscal_period: string | null;
  form: string;
  filed: string | null;
  accession: string | null;
  source_sha: string;
  label: string | null;
}

export interface XbrlPivot {
  years: number[]; // calendar year of the period end, newest first
  rows: { tag_id: string; label: string | null; unit: string; values: Record<string, number | null> }[];
  total: number;
}

export type XbrlRequiredRow = Served<S["RequiredRow"]>;

export interface XbrlVerifyRow {
  company_id: string;
  metric: string;
  fiscal_year: number;
  outcome: "match" | "mismatch" | "missing_in_run" | "missing_in_xbrl";
  run_value: number | null;
  xbrl_value: number | null;
  run_unit: string | null; // unit of the run's value; null when the run has none
  unit: string | null; // the XBRL unit
  detail: string;
}

// Universe workbench (wire format mirrors backend arp/api/routers/universe_workbench.py)
export interface WorkbenchMapping {
  status: "mapped" | "ambiguous" | "unmapped" | "no_identifier";
  issuer_key: string | null;
  key_scheme: string | null;
  identifiers: Partial<Record<"LEI" | "CIK" | "ISIN", string[]>>;
  candidates: string[];
}

export interface WorkbenchRoute {
  market: "sec" | "esef" | null;
  status: "routed" | "no_source" | "unrouted";
  basis: string | null;
  detail: string;
}

export interface WorkbenchAvailability {
  identity: { run_id: string; verdict: string; resolved_cik: string | null; resolved_website: string | null } | null;
  documents: { registered: number; parsed: number; on_disk: number; doc_types: string[]; last_seen_at: string | null };
  extraction: { runs: number; run_types: string[]; last_run_id: string | null; last_run_at: string | null };
  xbrl: { key: string; market: string; fact_count: number; fetched_at: string; report: boolean } | null;
}

export interface WorkbenchRow {
  company: CompanyRef;
  mapping: WorkbenchMapping;
  route: WorkbenchRoute;
  availability: WorkbenchAvailability | null; // null when requested with availability: false
}

export interface WorkbenchResponse {
  rows: WorkbenchRow[];
  counts: {
    routes: { sec: number; esef: number; no_source: number; unrouted: number };
    mapping: { mapped: number; ambiguous: number; unmapped: number; no_identifier: number };
  };
}

// One-company view (backend arp/db/company_view.py)
export type CompanyFactStatus = "auto_accepted" | "approved" | "edited" | "pending_review" | "held";

export type CompanyIdentifier = Served<S["IdentifierOut"]>;

export type CompanySearchHit = Served<S["CompanySearchHit"]>;

export type CompanyHolder = Served<S["HolderOut"]>;

export type CompanySummary = Served<S["CompanySummary"]>;

export interface CompanyFactRow {
  fact_id: number;
  field_id: string;
  kind: "extracted" | "provider";
  period_end: string | null;
  basis: string;
  value: unknown;
  canonical_value: number | null;
  canonical_unit: string | null;
  status: CompanyFactStatus;
  source_kind: "extraction" | "provider" | "xbrl" | "manual";
  source_label: string;
  licence: "internal_only" | "redistributable" | null;
  conflicting_sources: boolean;
  valid_from: string;
  valid_to: string | null;
}

// `company_id`: For the raw-file route, in the document registry's original case.
export type FactCitation = Served<S["CitationOut"]>;

export type FactLoad = Served<S["LoadOut"]>;

export type FactDecision = Served<S["DecisionOut"]>;

export type FactObservation = Served<S["ObservationOut"]>;

export type FactVersion = Served<S["FactVersion"]>;

export type FactTrail = Served<S["FactTrail"]>;

/** GET /api/companies/{ref}/transition (backend arp/schemas/transition_alignment.py). */
export type TransitionBenchmark = Served<S["BenchmarkOut"]>;

export type TransitionShare = Served<S["ShareOut"]>;

export type TransitionAmount = Served<S["AmountOut"]>;

export type TransitionRndResult = Served<S["RndResultOut"]>;

export type TransitionRedline = Served<S["RedlineOut"]>;

export type TransitionCapex = Served<S["CapexOut"]>;

export interface CompanyTransition {
  in_scope: boolean;
  reason: string | null;
  sector: string | null;
  benchmarks_version: number;
  rule_book_version: number;
  capex: TransitionCapex | null;
  regions: string[];
  actions: TransitionAction[];
  b02a: TransitionB02 | null;
  assumptions: TransitionAssumption[];
  targets: TransitionTarget[];
  target_progress: { score: number; text: string } | null;
  coverage: TransitionCoverage | null;
  phaseouts: TransitionPhaseout[];
  flags: TransitionFlag[];
  flags_header: string | null;
  delivery_kpis: TransitionKpi[];
  delivery_kpis_note: string | null;
}

export interface TransitionKpi {
  id: string;
  label: string;
  field_id: string;
  cite: string;
  value: number | null;
  year: number | null;
  fact_ids: number[];
  range_text: string;
  position_pct: number | null;
  action_keys: string[];
}

export interface TransitionFlag {
  id: string;
  title: string;
  state: "raised" | "clear" | "not checked";
  text: string;
  cite: string;
  fact_ids: number[];
}

export interface TransitionTarget {
  key: string;
  scope: string | null;
  pct: number | null;
  year: number | null;
  base_year: number | null;
  base_emissions_shown: string | null;
  kind: "past" | "running" | null;
  ratio: string | null;
  score: number | null;
  reason: string | null;
  citation: string | null;
  fact_ids: number[];
}

export interface TransitionCoverage {
  target_key: string | null;
  percent: number | null;
  text: string | null;
  actions: { key: string; saving_shown: string | null; summed: boolean; reason: string | null }[];
  reason: string | null;
}

export interface TransitionPhaseout {
  key: string;
  activity: string | null;
  share: number | null;
  year: number | null;
  method: string | null;
  share_points: number | null;
  date_points: number | null;
  score: number | null;
  reason: string | null;
  timeline_text: string;
  note: string | null;
  citation: string | null;
  fact_ids: number[];
}

export type TransitionB02 = Served<S["B02Out"]>;

export interface TransitionBarrier {
  code: string;
  region: string;
  rating: string | null;
  basis: string | null;
  evidence: string;
  values: BarrierValue[];
}

export interface TransitionAction {
  key: string;
  action_id: string | null;
  act_lever: { wording: string; citation: string } | null;
  text: string;
  status: string | null;
  year: number | null;
  region: string | null;
  citation: string | null;
  timeframe: string | null;
  b02: Record<string, TransitionB02>;
  barriers: TransitionBarrier[];
  note: string | null;
  fact_ids: number[];
}

export type TransitionComparison = Served<S["ComparisonOut"]>;

export type TransitionAssumption = Served<S["AssumptionOut"]>;
export type TransitionScenario = Served<S["ScenarioOut"]>;

export type CutoffStatus = "none" | "recorded" | "unknown";
export interface SignalWindow {
  window: "in_window" | "post_cutoff";
  periods: number;
  ic: { n: number; mean: number | null; t_nw: number | null; hit_rate: number | null };
}
export interface SignalExperimentSummary {
  experiment_id: string;
  method: string;
  category: string;
  universe: string;
  window_start: string;
  window_end: string;
  n_trials: number;
  model: string | null;
  cutoff: string | null;
  cutoff_status: CutoffStatus;
  decision: "none" | "graduate" | "shelve";
  created_at: string;
}
export interface SignalExperimentDetail {
  experiment_id: string;
  model: string | null;
  cutoff: string | null;
  cutoff_status: CutoffStatus;
  decision: "none" | "graduate" | "shelve";
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
  recipe: { method: string; category: string; universe: string; window_start: string; window_end: string; cost_bps: number };
  evidence: { n_trials: number; contamination_gap_ic: number | null; windows: SignalWindow[] };
}
export type SignalMethod = Served<S["MethodInfo"]>;
export type SignalComparison = Served<S["Comparison"]>;

/** GET /api/themes/runs/{run_id}/layers: theme exposure layers, computed on read. */
export type ThemeLayerRow = Served<S["ThemeLayerRow"]>;

export type ThemeLayers = Served<S["ThemeLayers"]>;
