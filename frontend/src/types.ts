export type DocType =
  | "10-K"
  | "DEF-14A"
  | "sustainability_report"
  | "earnings_transcript"
  | "investor_presentation"
  | "product_page"
  | "other";

export type JobStatus = "pending" | "running" | "completed" | "partially_completed" | "failed" | "cancelled";

// The run types the Review Queue endpoints exist for -- a subset of every
// run_type, since discovery has no review queue of its own.
export type ReviewableRunKind = "theme" | "extraction" | "financials" | "identity" | "transition_plan" | "tnfd";

export interface CompanyRef {
  company_id: string;
  name: string;
  ticker?: string | null;
  website?: string | null;
  cik?: string | null;
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
  estimated_cost_usd: number;
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

export interface StandardCodeMatch {
  code: string;
  label: string;
}

export interface GicsMatch {
  code: string;
  label: string;
  rationale: string;
}

export interface ActivityStandardsMapping {
  nace_codes: StandardCodeMatch[];
  naics_codes: StandardCodeMatch[];
  sic_codes: StandardCodeMatch[];
  gics: GicsMatch[];
  unmapped_isic_codes: string[];
}

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

export interface ActivityCatalogueMapping {
  activity_id: string;
  metric: RevenueCapexMetric;
  matched_labels: string[];
  rationale: string;
}

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
}

export interface DataPointSchema {
  schema_id: string;
  name: string;
  description: string;
  fields: FieldDefinition[];
  created_at: string;
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
  conflicting_sources: boolean;
}

export interface ExtractionRecord {
  company_id: string;
  ticker?: string | null;
  name: string;
  schema_id: string;
  run_id: string;
  fields: ExtractedField[];
  overall_confidence: number;
  needs_review: boolean;
  generated_at: string;
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

export interface TransitionPlanIndicatorDef {
  number: number;
  identifier: string;
  category: IndicatorCategory;
  walk_or_talk: WalkOrTalk;
  question: string;
  guideline: string;
}

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
  decision: "approve" | "edit" | "reject";
  reviewer?: string | null;
  edited_value?: { value?: unknown } | null;
  comment?: string | null;
  decided_at: string;
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

export interface DiscoveryScheduleConfig {
  enabled: boolean;
  interval_hours: number;
  universe_path?: string | null;
  doc_types: DocType[];
  last_run_id?: string | null;
  next_run_at?: string | null;
}

export interface TaxonomyResearcherScheduleConfig {
  enabled: boolean;
  interval_hours: number;
  taxonomy_ids?: string[] | null;
  last_run_id?: string | null;
}

export interface CalibrationScheduleConfig {
  enabled: boolean;
  interval_hours: number;
  last_run_id?: string | null;
}

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

export interface Taxonomy {
  taxonomy_id: string;
  name: string;
  version: number;
  theme: ThemeDefinition;
  derivation_method: DerivationMethod;
  source_notes: string;
  status: TaxonomyStatus;
  ratified_by?: string | null;
  ratified_at?: string | null;
  based_on_version?: number | null;
  created_at: string;
}

export interface TaxonomyRef {
  taxonomy_id: string;
  version?: number | null;
}

export interface ActivityDuplicateCandidate {
  activity_a_id: string;
  activity_b_id: string;
  similarity_note: string;
}

export interface TaxonomyComparison {
  unique_to_a: string[];
  unique_to_b: string[];
  likely_duplicates: ActivityDuplicateCandidate[];
}

export type SourceCandidateType = "authority" | "thematic_fund";

export interface SourceCandidate {
  candidate_id: string;
  source_type: SourceCandidateType;
  name: string;
  url: string;
  snippet: string;
  authority_score?: number | null;
  authority_reasoning?: string | null;
  discovered_at: string;
}

export interface HoldingsOverlapResult {
  fund_names: string[];
  core_tickers: string[];
  union_tickers: string[];
  ticker_presence: Record<string, string[]>;
  pairwise_overlap_pct: Record<string, number>;
}

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

export interface Contact {
  contact_id: string;
  name: string;
  role: string;
  email?: string | null;
  phone?: string | null;
  last_contacted_at?: string | null;
}

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

export const AGGREGATION_DIMENSIONS = ["portfolio_id", "asset_class", "company_id", "company_name", "sector", "country", "currency"] as const;

export interface PortfolioSummary {
  portfolio_id: string;
  name: string;
  tags: string[];
}

export interface SecurityResolution {
  security_id: string;
  company_id?: string | null;
  confidence: number;
  method: "isin_exact" | "name_fuzzy" | "manual";
  needs_review: boolean;
  resolved_at: string;
}

export interface DataPointObservation {
  company_id: string;
  field_id: string;
  field_name: string;
  value: number | string | boolean | null;
  unit?: string | null;
  period: string;
  observed_at: string;
  source: "internal_api" | "extracted" | "catalogue" | "estimated_proxy";
  conflicting_sources: boolean;
  conflicting_value?: number | string | boolean | null;
  conflicting_source_label?: string | null;
  notes: string;
}

export interface AggregationRow {
  group_value: string;
  market_value_eur?: number | null;
  weighted_avg_value?: number | null;
  coverage_pct?: number | null;
  holding_count: number;
}

export interface AggregationResult {
  spec_name: string;
  as_of: string;
  metric: AggregationMetric;
  group_by: string;
  rows: AggregationRow[];
  total_market_value_eur: number;
  unresolved_market_value_eur: number;
}

export interface TrendPoint {
  as_of: string;
  result: AggregationResult;
}

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

export interface NewsItem {
  news_id: string;
  company_id?: string | null;
  headline: string;
  excerpt: string;
  source_url?: string | null;
  published_at: string;
}

export interface NewsRiskFlag {
  flag_id: string;
  news_id: string;
  company_id: string;
  category: "climate_controversy" | "regulatory" | "litigation" | "other";
  severity: "low" | "medium" | "high";
  rationale: string;
  quote: string;
  grounded: boolean;
  generated_at: string;
}

export type AlertRuleType = "field_threshold" | "concentration_threshold" | "portfolio_aggregate_threshold";
export type AlertComparator = "gt" | "gte" | "lt" | "lte";
export type AlertStatus = "open" | "acknowledged" | "escalated" | "resolved" | "false_positive";
export type BreachType = "holdings_caused" | "data_caused" | "mixed" | "unknown";

export interface AlertRule {
  rule_id: string;
  name: string;
  rule_type: AlertRuleType;
  field_id?: string | null;
  company_ids: string[];
  portfolio_ids: string[];
  comparator: AlertComparator;
  threshold_value: number;
  severity: "low" | "medium" | "high";
  enabled: boolean;
  created_at: string;
}

export interface Alert {
  alert_id: string;
  rule_id?: string | null;
  category: "threshold_breach" | "news_controversy";
  scope_id: string;
  company_id?: string | null;
  portfolio_id?: string | null;
  triggered_at: string;
  observed_value?: number | null;
  threshold_value?: number | null;
  breach_type: BreachType;
  snapshot_date?: string | null;
  data_point_values?: Record<string, number> | null;
  source_flag_id?: string | null;
  rationale: string;
  status: AlertStatus;
  owner?: string | null;
}

export type GovernanceItemType = "entity_resolution" | "climate_conflict";
export type GovernanceDecisionType = "accept" | "override" | "reject";
export type PolicySettingName = "portfolio_confidence_review_threshold" | "climate_validation_tolerance_pct";

export interface GovernanceDecision {
  item_type: GovernanceItemType;
  item_key: string;
  decision: GovernanceDecisionType;
  decided_by: string;
  reason: string;
  override_value?: number | string | boolean | null;
  decided_at: string;
}

export interface RiskCategoryOwner {
  category: string;
  owner: string;
  assigned_by: string;
  assigned_at: string;
}

export interface PolicyChange {
  setting_name: PolicySettingName;
  old_value: number;
  new_value: number;
  changed_by: string;
  reason: string;
  changed_at: string;
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

export interface FinancedEmissionsResult {
  as_of: string;
  financed_emissions_tco2e: number;
  covered_market_value_eur: number;
  uncovered_market_value_eur: number;
  coverage_pct: number;
  uncovered_holding_count: number;
}

export type CoverageBySource = Record<string, number>;

export interface PivotRequest {
  name?: string;
  portfolio_filter?: string[];
  security_filter?: Record<string, string>;
  row_dim: string;
  col_dim: string;
  metric: AggregationMetric;
  data_point_field_id?: string | null;
  as_of?: string | null;
}

export interface PivotCell {
  row_value: string;
  col_value: string;
  market_value_eur?: number | null;
  weighted_avg_value?: number | null;
  coverage_pct?: number | null;
  holding_count: number;
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

export interface PivotResult {
  spec_name: string;
  as_of: string;
  metric: AggregationMetric;
  row_dim: string;
  col_dim: string;
  row_values: string[];
  col_values: string[];
  cells: PivotCell[];
  total_market_value_eur: number;
  unresolved_market_value_eur: number;
}

export type SearchResultType = "company" | "document" | "taxonomy";

export interface SearchHit {
  type: SearchResultType;
  id: string;
  title: string;
  snippet: string;
  score: number;
  company_id?: string | null;
  link?: string | null;
}

export interface SearchResponse {
  query: string;
  total: number;
  hits: SearchHit[];
}

// ---- Presentation & Reporting Tool -----------------------------------------

export type AudienceLevel = "executive" | "technical" | "general";
export type Tone = "formal" | "conversational" | "persuasive" | "neutral_analytical";

export interface AudienceProfile {
  level: AudienceLevel;
  tone: Tone;
  description: string;
  focus_areas: string[];
}

export type OutputFormat = "pptx" | "docx" | "pdf" | "house_deck";

export interface LayoutInstructions {
  output_format: OutputFormat;
  theme?: "light" | "dark";
  target_length?: number | null;
  max_bullets_per_slide: number;
  include_title_slide: boolean;
  include_agenda_slide: boolean;
  include_appendix: boolean;
  section_order_hint: string[];
  free_instructions: string;
}

export type ColumnKind = "category" | "number" | "date" | "percent";

export interface DatasetColumn {
  name: string;
  kind: ColumnKind;
}

export interface QuantitativeDataset {
  dataset_id: string;
  name: string;
  description: string;
  columns: DatasetColumn[];
  rows: Record<string, unknown>[];
}

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

export interface ChartSpec {
  dataset_id: string;
  chart_type: ChartType;
  title: string;
  category_column?: string | null;
  value_columns: string[];
  x_column?: string | null;
  y_column?: string | null;
  value_column?: string | null;
  notes: string;
}

export interface TableSpec {
  dataset_id: string;
  columns: string[];
  max_rows: number;
}

export interface ContentItem {
  text: string;
  bullet: boolean;
}

export type SectionLayoutHint = "standard" | "chart_focus" | "text_only" | "section_header";

export interface ReportSection {
  heading: string;
  layout_hint: SectionLayoutHint;
  narrative: ContentItem[];
  chart?: ChartSpec | null;
  table?: TableSpec | null;
  speaker_notes: string;
  appendix: boolean;
}

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

export interface StorylineSlide {
  headline: string;
  purpose: string;
  source_refs: string[];
}

export interface Storyline {
  title: string;
  subtitle: string;
  slides: StorylineSlide[];
  approved: boolean;
}

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

export interface CompositeSignalComponent {
  signal_type: SignalType;
  weight: number;
  formation_period_months: number;
  skip_month: boolean;
  characteristic_name?: string | null;
  characteristic_lag_months: number;
}

export interface LegPerformance {
  annualized_return_pct?: number | null;
  monthly_mean_return_pct?: number | null;
  annualized_volatility_pct?: number | null;
  sharpe_ratio?: number | null;
  t_stat?: number | null;
  max_drawdown_pct?: number | null;
  alpha_annualized_pct?: number | null;
  beta?: number | null;
}

export interface ReportedPerformance {
  long_leg: LegPerformance;
  short_leg: LegPerformance;
  long_short: LegPerformance;
  benchmark_name?: string | null;
  notes: string;
}

export interface ProvenanceInfo {
  extractor_model?: string | null;
  extractor_prompt_version?: string | null;
  verifier_model?: string | null;
  verifier_prompt_version?: string | null;
}

export interface StrategySpec {
  spec_id: string;
  paper_citation: string;
  paper_title: string;
  strategy_name: string;
  signal_type: SignalType;
  universe_description: string;
  formation_period_months: number;
  skip_month: boolean;
  holding_period_months: number;
  rebalance_frequency: RebalanceFrequency;
  rebalance_interval_months?: number | null;
  rebalance_anchor_month?: number | null;
  characteristic_name?: string | null;
  characteristic_lag_months: number;
  composite_components: CompositeSignalComponent[];
  num_portfolios: number;
  long_leg_portfolio: number;
  short_leg_portfolio: number;
  weighting: WeightingScheme;
  sample_period_start: string;
  sample_period_end: string;
  reported_performance: ReportedPerformance;
  citations: Citation[];
  grounded: boolean;
  confidence: number;
  needs_review: boolean;
  verifier_notes?: string | null;
  provenance: ProvenanceInfo;
  num_trials_attempted: number;
  extraction_notes: string;
  created_at: string;
}

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

export interface DeflatedSharpeAssessment {
  n_obs: number;
  n_trials: number;
  sharpe_ratio_period?: number | null;
  skewness?: number | null;
  kurtosis?: number | null;
  expected_max_sharpe_under_null_period?: number | null;
  probabilistic_sharpe_ratio?: number | null;
  deflated_sharpe_ratio?: number | null;
  notes: string;
}

export interface ReplicationComparisonReport {
  report_id: string;
  spec_id: string;
  in_sample: BacktestResult;
  out_of_sample?: BacktestResult | null;
  reported_performance: ReportedPerformance;
  in_sample_return_gap_pp?: number | null;
  out_of_sample_return_gap_pp?: number | null;
  deflated_sharpe?: DeflatedSharpeAssessment | null;
  verdict: ReplicationVerdict;
  verdict_notes: string;
  generated_at: string;
}

export interface SanityCheckFinding {
  concern: string;
  explanation: string;
}

export interface SanityCheckAssessment {
  plausible: boolean;
  findings: SanityCheckFinding[];
  summary: string;
}

export interface RegimeBucketPerformance {
  regime: "low_volatility" | "mid_volatility" | "high_volatility";
  num_periods: number;
  long_short: LegPerformance;
}

export interface RegimeStratifiedReport {
  trailing_window_months: number;
  buckets: RegimeBucketPerformance[];
  notes: string;
}

export interface ReplicationRunDetail {
  run_id: string;
  spec: StrategySpec;
  in_sample: BacktestResult;
  out_of_sample?: BacktestResult | null;
  comparison: ReplicationComparisonReport;
  sanity_check?: SanityCheckAssessment | null;
  regime_report?: RegimeStratifiedReport | null;
}

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
}

export interface BarrierScore {
  code: string;
  sector: string;
  category: BarrierPillar;
  criterion: string;
  region: BarrierRegion;
  rating: BarrierRating;
  confidence: BarrierConfidence;
  evidence: string;
  source: string;
  last_verified: string;
}

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

export interface BarrierStalenessReport {
  threshold_days: number;
  as_of: string;
  total: number;
  stale: number;
  fresh: number;
  stale_codes: string[];
}

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

export interface ColumnStats {
  count: number;
  min?: number | null;
  p5?: number | null;
  q1?: number | null;
  median?: number | null;
  q3?: number | null;
  p95?: number | null;
  max?: number | null;
  mean?: number | null;
  sd?: number | null;
  true_share?: number | null;
}

export interface ColumnProfile {
  name: string;
  type: ColumnType;
  coverage: number;
  unique: number;
  spread: boolean;
  decimal_comma: boolean;
  stats?: ColumnStats | null;
  levels: string[];
}

export interface RoleProposal {
  column: string;
  role: ColumnRole;
  role_reason: string;
  direction: Direction;
  direction_reason: string;
  needs_check: boolean;
}

export interface DatasetSummary {
  dataset_id: string;
  name: string;
  source: string;
  source_ref?: string | null;
  as_of?: string | null;
  row_count: number;
  columns: string[];
  preview: Record<string, string>[];
  profiles: ColumnProfile[];
  proposals: RoleProposal[];
  has_confidence: boolean;
  /** Preview rows typed exactly as the rule engine sees them. */
  rule_inputs: Record<string, unknown>[];
  calculated_columns: string[];
  rule_audit: AuditEntry[];
}

export interface Dimension {
  id: string;
  name: string;
  weight: number;
  derived_from: string[];
}

export interface Criterion {
  column: string;
  dimension_id: string;
  weight: number;
  enabled: boolean;
  direction: Direction;
}

export interface GateRule {
  id: string;
  column: string;
  op: GateOp;
  value: string;
  outcome: GateOutcome;
}

export interface VetoRule {
  enabled: boolean;
  min_score: number;
  min_criteria: number;
}

export interface TierDefinition {
  rank: number;
  name: string;
  action: string;
}

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
export interface LevelRule {
  level: number;
  when: string;
  note?: string;
}

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

export interface AuditEntry {
  stage: string;
  item: string;
  decision: string;
  why: string;
  needs_check: boolean;
  origin: "derived" | "human";
  at: string;
  by?: string | null;
}

export interface MechanismEnvelope {
  config: MechanismConfig;
  audit: AuditEntry[];
}

/** Run types a scoring template can be attached to. */
export type RunScoringKind = "extraction" | "transition_plan" | "financials" | "tnfd";

/** A saved framework and the columns it needs that a table or schema would not supply. */
export interface TemplateMatch {
  config: MechanismConfig;
  required_columns: string[];
  missing_columns: string[];
}

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
  reviewer: string;
  at?: string;
}

export interface CriterionContribution {
  column: string;
  normalised?: number | null;
  weight: number;
  contribution: number;
  imputed: boolean;
  low_confidence: boolean;
  /** Levels mode: the criterion, and when overridden, the rules' level and the override. */
  criterion_id?: string | null;
  overridden_from?: number | null;
  override?: LevelOverride | null;
}

export interface OverridesView {
  overrides: LevelOverride[];
  history: (Partial<LevelOverride> & { action: "set" | "removed"; at: string })[];
}

export interface EntityDecision {
  entity_key: string;
  name: string;
  segment?: string | null;
  cohort?: string | null;
  score?: number | null;
  coverage: number;
  grounded_coverage?: number | null;
  status: EntityStatus;
  tier?: number | null;
  tier_name?: string | null;
  tier_action?: string | null;
  notes: string[];
  rank?: number | null;
  rank_min?: number | null;
  rank_max?: number | null;
  size?: number | null;
  leverage?: number | null;
  leverage_rank?: number | null;
  dimension_scores: Record<string, number | null>;
  contributions: CriterionContribution[];
}

export interface TierSummary {
  rank: number;
  name: string;
  action: string;
  count: number;
  size_total?: number | null;
}

export interface HistogramBin {
  lower: number;
  upper: number;
  count: number;
}

export interface DecisionResult {
  framework_id: string;
  framework_version: number;
  dataset_id?: string | null;
  computed_at: string;
  norm: NormMethod;
  effective_cuts: number[];
  cuts_origin: CutMode;
  effective_weights: Record<string, number>;
  /** Columns the framework uses that this table lacks; such a result cannot be published. */
  missing_columns?: string[];
  entities: EntityDecision[];
  tier_summary: TierSummary[];
  histogram: HistogramBin[];
  scored_count: number;
  excluded_count: number;
  insufficient_count: number;
  audit: AuditEntry[];
  /** What a tier graph sees for the first rows (band, score, rank, columns…). */
  tier_inputs: Record<string, unknown>[];
}

export interface TippingPoint {
  dimension_id: string;
  dimension_name: string;
  current_weight_pct: number;
  flip_weight_pct?: number | null;
  delta_pct?: number | null;
  new_tier?: number | null;
  robust: boolean;
}

export interface EntitySensitivity {
  entity_key: string;
  name: string;
  tier?: number | null;
  score?: number | null;
  tipping_points: TippingPoint[];
  min_delta_pct?: number | null;
}

export interface EntityMovement {
  entity_key: string;
  name: string;
  tier_before?: number | null;
  tier_after?: number | null;
  tier_delta?: number | null;
  score_before?: number | null;
  score_after?: number | null;
  score_delta?: number | null;
  rank_before?: number | null;
  rank_after?: number | null;
  rank_delta?: number | null;
  status_before?: EntityStatus | null;
  status_after?: EntityStatus | null;
  drivers: string[];
}

export interface DecisionComparison {
  framework_id: string;
  framework_version: number;
  label_before: string;
  label_after: string;
  improved: number;
  worsened: number;
  unchanged: number;
  entered: number;
  left: number;
  movements: EntityMovement[];
  comparable: boolean;
  incomparable_reason?: string | null;
  caveat?: string | null;
  cut_points?: number[];
  cuts_moved?: string | null;
  missing_columns?: string[];
}

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

export interface RiskModelSpec {
  source: "ledoit_wolf" | "sample" | "factor" | "supplied";
  lookback_periods: number;
  min_observations: number;
  periods_per_year: number;
  factor_fields: string[];
}

export interface ConstraintSolver {
  method: "waterfall" | "least_squares" | "min_tracking_error" | "max_score";
  solver: "CLARABEL" | "OSQP" | "SCS";
  verify_tolerance: number;
  fallback_to_waterfall: boolean;
  tracking_error_budget?: number | null;
  score_field?: string | null;
  min_risk_coverage: number;
  risk_model: RiskModelSpec;
  enforce_semicontinuous: boolean;
  mip_solver: "SCIP" | "HIGHS" | "GUROBI" | "MOSEK" | "CPLEX";
  mip_gap: number;
  mip_time_limit_seconds?: number | null;
  tie_break_epsilon: number;
}

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

export interface IndexCalibration {
  calibration_id: string;
  name: string;
  version: number;
  based_on_version?: number | null;
  effective_from: string;
  effective_to?: string | null;
  approved_by: string[];
  notes: string;
  created_at: string;
  spec: ConstructionSpec;
}

export interface StageTrace {
  stage: string;
  rule_type: string;
  label: string;
  candidates_in: number;
  candidates_out: number;
  dropped_sample: string[];
  detail: Record<string, string | number>;
}

export interface IndexConstituent {
  company_id: string;
  name: string;
  sector?: string | null;
  country?: string | null;
  weight: number;
  base_weight: number;
  tilt_multiplier: number;
  capping_factor: number;
  price: number;
  fx_rate: number;
  index_shares: number;
  metrics: Record<string, number>;
}

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

export interface ReviewDiagnostics {
  universe_size: number;
  eligible_size: number;
  selected_size: number;
  final_size: number;
  weighted_metrics: Record<string, number>;
  universe_weighted_metrics: Record<string, number>;
  effective_n: number;
  max_weight: number;
  one_way_turnover?: number | null;
  capping_iterations: number;
  trajectory_iterations: number;
  tracking_error?: number | null;
  integer_constraints?: boolean;
}

export interface IndexReviewResult {
  index_id: string;
  review_date: string;
  calibration_id?: string | null;
  calibration_version?: number | null;
  config_hash: string;
  constituents: IndexConstituent[];
  diagnostics: ReviewDiagnostics;
  trace: StageTrace[];
  state: IndexState;
  exceptions: string[];
  decision_snapshot_ids?: string[];
  input_notes?: string[];
  created_at: string;
}

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

export interface ProgramParams {
  objective: string;
  benchmark: string;
  normalisation: "rank_percentile" | "zscore" | "max";
  tilt_floor: number;
  tilt_ceiling: number;
  leader_clti: number;
  laggard_clti: number;
  include_triggers: boolean;
  max_targets: number;
  min_weight_ratio: number;
  effort_days: number;
  free_capacity_days: number;
}

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
export interface PublishedDecision {
  snapshot_id: string;
  framework_id: string;
  framework_version: number;
  framework_name: string;
  dataset_id: string;
  dataset_name: string;
  as_of?: string | null;
  id_column: string;
  published_by: string;
  published_at: string;
  note: string;
  cut_points?: number[];
  /** The first publication of this framework version, whose cut-points were reused. */
  cuts_held_from?: string | null;
  rows: { entity_id: string; name: string; score: number | null; tier: number | null; tier_name: string | null; rank: number | null; status: string }[];
}

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
export interface BIChartSpec {
  title: string;
  question: string;
  viz_type: string;
  dataset: string;
  metrics: string[];
  groupby: string[];
  filters: Record<string, string>;
}

export interface BIDesignResult {
  dashboard_id: number | null;
  slug: string | null;
  url: string | null;
  plan: { title: string; goal: string; charts: BIChartSpec[] } | null;
  rejected: string[];
  clarification_needed: string | null;
}

export interface BIEmbedToken {
  token: string;
  embedded_id: string;
}
