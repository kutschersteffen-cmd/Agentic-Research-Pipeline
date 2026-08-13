export type DocType =
  | "10-K"
  | "DEF-14A"
  | "sustainability_report"
  | "earnings_transcript"
  | "investor_presentation"
  | "product_page"
  | "other";

export type JobStatus = "pending" | "running" | "completed" | "partially_completed" | "failed" | "cancelled";

export interface CompanyRef {
  company_id: string;
  name: string;
  ticker?: string | null;
  website?: string | null;
  cik?: string | null;
  country?: string | null;
  sector?: string | null;
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

export interface DiscoveryScheduleConfig {
  enabled: boolean;
  interval_hours: number;
  universe_path?: string | null;
  doc_types: DocType[];
  last_run_id?: string | null;
  next_run_at?: string | null;
}

export interface ReviewQueueResponse {
  pending: Record<string, unknown>[];
  decided: { item: Record<string, unknown>; decision: Record<string, unknown> }[];
}

// --- Taxonomy library ---

export type DerivationMethod =
  | "llm_draft"
  | "industry_anchored"
  | "authority_source"
  | "etf_index_holdings"
  | "news_transcript_mining"
  | "empirical"
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

export interface DiscoverSourcesResponse {
  authority_sources: SourceCandidate[];
  thematic_funds: SourceCandidate[];
}

export interface HoldingRow {
  ticker: string;
  name?: string | null;
  weight?: number | null;
  sector?: string | null;
}

export interface HoldingsOverlapResult {
  fund_names: string[];
  core_tickers: string[];
  union_tickers: string[];
  ticker_presence: Record<string, string[]>;
  pairwise_overlap_pct: Record<string, number>;
}

// --- Portfolio risk & exposure monitoring ---

export type AssetClass = "equity" | "corporate_bond" | "government_bond" | "fund" | "etf" | "derivative" | "cash" | "other";
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
