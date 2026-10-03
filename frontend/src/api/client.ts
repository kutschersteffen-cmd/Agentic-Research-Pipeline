import type {
  CompanyBallot,
  ClientEscalationPreview,
  BenchmarkInfo,
  CaseStudy,
  ClientReport,
  TrackedCommitment,
  TrackedEngagement,
  InteractionType,
  OutreachDraft,
  StyleFlag,
  ProgramMonitor,
  ProgramParams,
  ProgramRun,
  ProgramSimulation,
  ProgramVersion,
  CoveragePreview,
  EscalationPreview,
  EscalationRecommendation,
  MonitoringPreview,
  MonitoringTrigger,
  IssueCatalogue,
  ResearchDossier,
  StewardPolicyId,
  StewardPolicyInfo,
  StewardshipFlow,
  StewardshipStream,
  TriggerEvent,
  VoteRecord,
  VoteReviewDecision,
  VotingPreview,
} from "../types";
import type {
  AggregationResult,
  DatasetSummary,
  DecisionComparison,
  DecisionResult,
  EntitySensitivity,
  MechanismConfig,
  MechanismEnvelope,
  RuleGraph,
  RunDecision,
  LevelOverride,
  OverridesView,
  RunScoringKind,
  TemplateMatch,
  Alert,
  AlertRule,
  AlertStatus,
  ConstructionSpec,
  IndexCalibration,
  IndexCatalogue,
  IndexReviewResult,
  AnalyticRequest,
  CompanyRef,
  CoverageBySource,
  DataPointObservation,
  DataPointSchema,
  DemoSeedSummary,
  EmergingThemeCandidate,
  EmergingThemesScheduleConfig,
  FinancedEmissionsResult,
  GovernanceDecision,
  GovernanceDecisionType,
  GovernanceItemType,
  NewsItem,
  NewsRiskFlag,
  PivotRequest,
  PivotResult,
  PolicyChange,
  PolicySettingName,
  PortfolioSummary,
  QAAnswer,
  RiskCategoryOwner,
  SecurityResolution,
  SearchResponse,
  TransitionPlanAssessmentRecord,
  ExtractionProfile,
  PipelineShape,
  RunCompany,
  RunSteps,
  TnfdRecord,
  TransitionPlanIndicatorDef,
  TrendPoint,
} from "../types";
import type { DecisionInput, DocType, PublishedDecision, Readiness } from "../types";
import { formatValidationErrors } from "../lib/projects";
import type { BIChartPlan, BIDesignResult, BIEmbedToken, DashboardItem, ExportedDashboard, OpenedDashboard, OpenResult, ProjectSummary } from "../types";
import type { Finding, QuantitativeDataset, ReportManifest, ReportPlan, ReportRequest, Storyline, TemplateStyleProfile } from "../types";
import type { PaperCandidate, ReplicationRunDetail, RegimeStratifiedReport, SanityCheckAssessment, SpecReviewState, StrategySpec } from "../types";
import type {
  BarrierCriterionDetail,
  BarrierMatrix,
  BarrierRefreshCoverage,
  BarrierStalenessReport,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

function buildQuery(params: Record<string, string | string[] | undefined | null>): string {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const v of value) usp.append(key, v);
    } else {
      usp.append(key, value);
    }
  }
  const qs = usp.toString();
  return qs ? `?${qs}` : "";
}

/** Policy endpoints act on the house by default, or on a client stream's own policies. */
const streamQuery = (stream?: string) => (stream ? `?stream=${encodeURIComponent(stream)}` : "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: isFormData ? init?.headers : { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = Array.isArray(body.detail)
        ? formatValidationErrors(body.detail)
        : typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail ?? body);
    } catch {
      /* ignore parse failure */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  base: API_BASE,

  // Search
  searchAll: (q: string, types?: string[], limit?: number) =>
    request<SearchResponse>(`/api/search${buildQuery({ q, types, limit: limit ? String(limit) : undefined })}`),

  // Universe
  uploadUniverse: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ path: string; company_count: number; sample: unknown[] }>("/api/universe/upload", {
      method: "POST",
      headers: {},
      body: form,
    });
  },

  // Themes
  decomposeTheme: (name: string, description: string) =>
    request("/api/themes/decompose", { method: "POST", body: JSON.stringify({ name, description }) }),
  startThemeRun: (body: unknown) => request<{ run_id: string; company_count: number }>("/api/themes/runs", { method: "POST", body: JSON.stringify(body) }),
  getThemeResults: (runId: string, offset = 0, limit = 500) =>
    request(`/api/themes/runs/${runId}/results?offset=${offset}&limit=${limit}`),
  getThemeReviewQueue: (runId: string) => request(`/api/themes/runs/${runId}/review-queue`),
  submitThemeReview: (runId: string, body: unknown) =>
    request(`/api/themes/runs/${runId}/review`, { method: "POST", body: JSON.stringify(body) }),

  // Extraction
  draftSchema: (criteriaText: string) =>
    request("/api/extraction/schemas/draft", { method: "POST", body: JSON.stringify({ criteria_text: criteriaText }) }),
  getExtractionResults: (runId: string, offset = 0, limit = 500) =>
    request(`/api/extraction/runs/${runId}/results?offset=${offset}&limit=${limit}`),
  getExtractionReviewQueue: (runId: string) => request(`/api/extraction/runs/${runId}/review-queue`),
  submitExtractionReview: (runId: string, body: unknown) =>
    request(`/api/extraction/runs/${runId}/review`, { method: "POST", body: JSON.stringify(body) }),
  getExtractionReviewDecisions: (runId: string) => request(`/api/extraction/runs/${runId}/review-decisions`),
  getExtractionReviewHistory: (runId: string, itemKey: string) =>
    request(`/api/extraction/runs/${runId}/review-history?item_key=${encodeURIComponent(itemKey)}`),
  getExtractionResultsForCompany: (companyId: string) =>
    request(`/api/extraction/companies/${encodeURIComponent(companyId)}/results`),

  // Company Financials (business segments + CapEx + R&D, one combined pass)
  /** One entry point for every extraction profile; returns which run type it started. */
  startExtraction: (body: { profile: ExtractionProfile } & Record<string, unknown>) =>
    request<{ run_id: string; company_count: number; run_type: RunScoringKind }>("/api/extraction/start", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getExtractionPipeline: (profile: ExtractionProfile) => request<PipelineShape>(`/api/extraction/pipeline?profile=${profile}`),
  getRunSteps: (runId: string, companyId?: string | null) =>
    request<RunSteps>(`/api/extraction/runs/${runId}/steps${companyId ? `?company_id=${encodeURIComponent(companyId)}` : ""}`),
  getRunCompanies: (runId: string) => request<{ companies: RunCompany[] }>(`/api/extraction/runs/${runId}/companies`),
  /** A new run from `from_step` on (the same run, rescored, from the rules step). */
  restartRun: (runId: string, body: { from_step: string; company_ids?: string[] }) =>
    request<{ run_id: string; run_type: RunScoringKind; rescored?: boolean }>(`/api/extraction/runs/${runId}/restart`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getTnfdResults: (runId: string, offset = 0, limit = 500) =>
    request<{ total: number; results: TnfdRecord[] }>(`/api/tnfd/runs/${runId}/results?offset=${offset}&limit=${limit}`),
  getFinancialsResults: (runId: string, offset = 0, limit = 500) =>
    request(`/api/financials/runs/${runId}/results?offset=${offset}&limit=${limit}`),
  getFinancialsReviewQueue: (runId: string) => request(`/api/financials/runs/${runId}/review-queue`),
  submitFinancialsReview: (runId: string, body: unknown) =>
    request(`/api/financials/runs/${runId}/review`, { method: "POST", body: JSON.stringify(body) }),
  getFinancialsReviewDecisions: (runId: string) => request(`/api/financials/runs/${runId}/review-decisions`),
  getFinancialsReviewHistory: (runId: string, itemKey: string) =>
    request(`/api/financials/runs/${runId}/review-history?item_key=${encodeURIComponent(itemKey)}`),
  getFinancialsResultsForCompany: (companyId: string) =>
    request(`/api/financials/companies/${encodeURIComponent(companyId)}/results`),

  // Transition Plan Assessment (64-indicator walk/talk RAG disclosure assessment)
  getTransitionPlanIndicators: () => request<TransitionPlanIndicatorDef[]>("/api/transition-plan/indicators"),
  getTransitionPlanResults: (runId: string, offset = 0, limit = 500) =>
    request<{ total: number; results: TransitionPlanAssessmentRecord[] }>(
      `/api/transition-plan/runs/${runId}/results?offset=${offset}&limit=${limit}`,
    ),
  getTransitionPlanReviewQueue: (runId: string) => request(`/api/transition-plan/runs/${runId}/review-queue`),
  getTnfdReviewQueue: (runId: string) => request(`/api/tnfd/runs/${runId}/review-queue`),
  getTnfdReviewHistory: (runId: string, itemKey: string) =>
    request(`/api/tnfd/runs/${runId}/review-history?item_key=${encodeURIComponent(itemKey)}`),
  submitTnfdReview: (runId: string, body: unknown) =>
    request(`/api/tnfd/runs/${runId}/review`, { method: "POST", body: JSON.stringify(body) }),
  submitTransitionPlanReview: (runId: string, body: unknown) =>
    request(`/api/transition-plan/runs/${runId}/review`, { method: "POST", body: JSON.stringify(body) }),
  getTransitionPlanReviewDecisions: (runId: string) => request(`/api/transition-plan/runs/${runId}/review-decisions`),
  getTransitionPlanReviewHistory: (runId: string, itemKey: string) =>
    request(`/api/transition-plan/runs/${runId}/review-history?item_key=${encodeURIComponent(itemKey)}`),

  // Transition Barrier Assessment (105-cell sector x region feasibility matrix)
  getBarrierMatrix: () => request<BarrierMatrix>("/api/transition-barrier/matrix"),
  getBarrierCriterionDetail: (code: string) =>
    request<BarrierCriterionDetail>(`/api/transition-barrier/criteria/${encodeURIComponent(code)}`),
  getBarrierStaleness: () => request<BarrierStalenessReport>("/api/transition-barrier/staleness"),
  getBarrierRefreshCoverage: () => request<BarrierRefreshCoverage>("/api/transition-barrier/refresh/coverage"),
  startBarrierRefreshRun: () =>
    request<{ run_id: string; source_count: number }>("/api/transition-barrier/refresh/runs", { method: "POST" }),

  // Documents
  listDocuments: (companyId: string) => request(`/api/documents/${companyId}`),
  uploadDocument: (companyId: string, docType: DocType, file: File) => {
    const form = new FormData();
    form.append("company_id", companyId);
    form.append("doc_type", docType);
    form.append("file", file);
    return request<{ path: string }>("/api/documents/upload", { method: "POST", headers: {}, body: form });
  },
  documentRawUrl: (companyId: string, docType: string, filename: string) =>
    `${API_BASE}/api/documents/${encodeURIComponent(companyId)}/${encodeURIComponent(docType)}/${encodeURIComponent(filename)}/raw`,
  documentReadiness: (body: { universe_path?: string; companies?: unknown[] }) =>
    request<{ ready: (CompanyRef & { readiness: Readiness })[]; onboard: CompanyRef[]; readiness: Record<string, Readiness> }>(
      "/api/documents/readiness",
      { method: "POST", body: JSON.stringify(body) },
    ),
  listCachedDocuments: (offset = 0, limit = 25) => request(`/api/documents/cache?offset=${offset}&limit=${limit}`),
  getCachedDocumentText: (rowId: number) => request(`/api/documents/cache/${rowId}`),

  // Discovery
  startDiscoveryRun: (body: unknown) =>
    request<{ run_id: string; company_count: number }>("/api/discovery/runs", { method: "POST", body: JSON.stringify(body) }),
  getDiscoveryResults: (runId: string, offset = 0, limit = 500) =>
    request(`/api/discovery/runs/${runId}/results?offset=${offset}&limit=${limit}`),
  getDiscoveryEvents: (since?: string) => request(`/api/discovery/events${since ? `?since=${encodeURIComponent(since)}` : ""}`),
  getDiscoverySchedule: () => request("/api/discovery/schedule"),
  updateDiscoverySchedule: (config: unknown) =>
    request("/api/discovery/schedule", { method: "PUT", body: JSON.stringify(config) }),

  // Taxonomy Researcher (standing agent)
  startTaxonomyResearcherRun: (body: unknown) =>
    request<{ run_id: string }>("/api/taxonomy-researcher/runs", { method: "POST", body: JSON.stringify(body) }),
  getTaxonomyResearcherResults: (runId: string, offset = 0, limit = 200) =>
    request(`/api/taxonomy-researcher/runs/${runId}/results?offset=${offset}&limit=${limit}`),
  getTaxonomyResearcherSchedule: () => request("/api/taxonomy-researcher/schedule"),
  updateTaxonomyResearcherSchedule: (config: unknown) =>
    request("/api/taxonomy-researcher/schedule", { method: "PUT", body: JSON.stringify(config) }),

  // Calibration Agent (standing agent)
  startCalibrationRun: () => request<{ run_id: string }>("/api/calibration/runs", { method: "POST" }),
  getCalibrationResults: (runId: string, offset = 0, limit = 200) =>
    request(`/api/calibration/runs/${runId}/results?offset=${offset}&limit=${limit}`),
  getCalibrationSchedule: () => request("/api/calibration/schedule"),
  updateCalibrationSchedule: (config: unknown) =>
    request("/api/calibration/schedule", { method: "PUT", body: JSON.stringify(config) }),

  // Emerging Themes Scanner ("Tool 0")
  startEmergingThemesRun: (body: { companies?: unknown[]; universe_path?: string }) =>
    request<{ run_id: string; company_count: number }>("/api/emerging-themes/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getEmergingThemesCandidates: (runId: string) =>
    request<{ total: number; candidates: EmergingThemeCandidate[] }>(
      `/api/emerging-themes/runs/${encodeURIComponent(runId)}/candidates`,
    ),
  promoteEmergingThemeCandidate: (runId: string, themeId: string, reason: string, taxonomyId?: string | null) =>
    request<EmergingThemeCandidate>(
      `/api/emerging-themes/runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(themeId)}/promote`,
      { method: "POST", body: JSON.stringify({ reason, taxonomy_id: taxonomyId ?? null }) },
    ),
  rejectEmergingThemeCandidate: (runId: string, themeId: string, reason: string) =>
    request<{ theme_id: string; status: string }>(
      `/api/emerging-themes/runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(themeId)}/reject`,
      { method: "POST", body: JSON.stringify({ reason }) },
    ),
  disconfirmEmergingThemeCandidate: (runId: string, themeId: string, reason: string) =>
    request<{ theme_id: string; status: string }>(
      `/api/emerging-themes/runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(themeId)}/disconfirm`,
      { method: "POST", body: JSON.stringify({ reason }) },
    ),
  getEmergingThemesSchedule: () => request<EmergingThemesScheduleConfig>("/api/emerging-themes/schedule"),
  updateEmergingThemesSchedule: (config: EmergingThemesScheduleConfig) =>
    request<EmergingThemesScheduleConfig>("/api/emerging-themes/schedule", {
      method: "PUT",
      body: JSON.stringify(config),
    }),

  // Identity resolution (agentic name -> website/CIK, ahead of discovery)
  startIdentityRun: (body: unknown) =>
    request<{ run_id: string; company_count: number }>("/api/identity/runs", { method: "POST", body: JSON.stringify(body) }),
  getIdentityResults: (runId: string, offset = 0, limit = 500) =>
    request(`/api/identity/runs/${runId}/results?offset=${offset}&limit=${limit}`),
  getIdentityReviewQueue: (runId: string) => request(`/api/identity/runs/${runId}/review-queue`),
  submitIdentityReview: (runId: string, body: unknown) =>
    request(`/api/identity/runs/${runId}/review`, { method: "POST", body: JSON.stringify(body) }),
  getEnrichedUniverse: (runId: string) =>
    request<{ companies: Record<string, unknown>[] }>(`/api/identity/runs/${runId}/enriched-universe`),

  // Runs (generic)
  listRuns: (runType?: string) => request(`/api/runs${runType ? `?run_type=${runType}` : ""}`),
  getRun: (runId: string) => request(`/api/runs/${runId}`),
  exportRunCsvUrl: (runId: string) => `${API_BASE}/api/runs/${runId}/export.csv`,
  cancelRun: (runId: string) => request(`/api/runs/${runId}/cancel`, { method: "POST" }),
  resumeThemeRun: (runId: string) => request(`/api/themes/runs/${runId}/resume`, { method: "POST" }),
  listKnownCompanies: (runType: string) => request(`/api/runs/known-companies?run_type=${runType}`),

  // Universe from an in-hand company list (e.g. filtered thematic-run matches)
  universeFromCompanies: (companies: unknown[], name: string) =>
    request<{ path: string; company_count: number; sample: unknown[] }>("/api/universe/from-companies", {
      method: "POST",
      body: JSON.stringify({ companies, name }),
    }),

  // Taxonomy library
  discoverTaxonomySources: (name: string) =>
    request<{ authority_sources: unknown[]; thematic_funds: unknown[] }>("/api/taxonomies/discover-sources", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  inspectSourceUrl: (url: string) => `${API_BASE}/api/taxonomies/sources/inspect?url=${encodeURIComponent(url)}`,
  createTaxonomy: (body: unknown) => request("/api/taxonomies", { method: "POST", body: JSON.stringify(body) }),
  listTaxonomies: () => request<{ taxonomies: unknown[] }>("/api/taxonomies"),
  newTaxonomyVersion: (taxonomyId: string, body: unknown) =>
    request(`/api/taxonomies/${taxonomyId}/versions`, { method: "POST", body: JSON.stringify(body) }),
  ratifyTaxonomy: (taxonomyId: string, body: unknown) =>
    request(`/api/taxonomies/${taxonomyId}/ratify`, { method: "POST", body: JSON.stringify(body) }),
  compareTaxonomies: (body: unknown) => request("/api/taxonomies/compare", { method: "POST", body: JSON.stringify(body) }),
  mergeTaxonomies: (body: unknown) => request("/api/taxonomies/merge", { method: "POST", body: JSON.stringify(body) }),
  mapStandards: (taxonomyId: string, body: unknown) =>
    request(`/api/taxonomies/${taxonomyId}/map-standards`, { method: "POST", body: JSON.stringify(body) }),
  standardsCsvUrl: (taxonomyId: string) => `${API_BASE}/api/taxonomies/${taxonomyId}/standards.csv`,

  // Universe builder
  rawUpload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ path: string }>("/api/universe/raw-upload", { method: "POST", headers: {}, body: form });
  },
  universeFromHoldings: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ path: string; company_count: number; sample: unknown[] }>("/api/universe/from-holdings", {
      method: "POST",
      headers: {},
      body: form,
    });
  },

  // ETF holdings overlap
  computeOverlap: (funds: Record<string, string>) =>
    request("/api/etf-overlap", { method: "POST", body: JSON.stringify({ funds }) }),

  // Revenue/CapEx catalogue mapping
  suggestCatalogueMapping: (body: { taxonomy_id: string; taxonomy_version?: number | null; catalogue_path: string }) =>
    request("/api/revenue-catalogue/suggest-mapping", { method: "POST", body: JSON.stringify(body) }),

  // Engagement (stewardship)
  listStewardshipStreams: () => request<{ streams: StewardshipStream[] }>("/api/stewardship/streams"),
  createStewardshipStream: (body: { name: string; vehicle_type: string; client_policy?: unknown }) =>
    request<{ stream_id: string }>("/api/stewardship/streams", { method: "POST", body: JSON.stringify(body) }),
  getStewardshipFlow: (streamId: string) => request<StewardshipFlow>(`/api/stewardship/streams/${encodeURIComponent(streamId)}/flow`),
  recordPolicyDecision: (streamId: string, body: { issue_id: string; decision: string; decided_by: string; note?: string }) =>
    request(`/api/stewardship/streams/${encodeURIComponent(streamId)}/decisions`, { method: "POST", body: JSON.stringify(body) }),
  confirmTiers: (body: { decided_by: string; issuer_ids?: string[] }) =>
    request<{ confirmed: number }>("/api/stewardship/tiers/confirm", { method: "POST", body: JSON.stringify(body) }),
  getStewardPolicy: (policyId: StewardPolicyId, stream?: string) =>
    request<StewardPolicyInfo>(`/api/stewardship/policies/${policyId}${streamQuery(stream)}`),
  getStewardPolicyVersion: (policyId: StewardPolicyId, version: number, stream?: string) =>
    request<Record<string, unknown>>(`/api/stewardship/policies/${policyId}/versions/${version}${streamQuery(stream)}`),
  saveStewardPolicyVersion: (policyId: StewardPolicyId, body: { content: unknown; note: string; created_by: string }, stream?: string) =>
    request<{ version: number }>(`/api/stewardship/policies/${policyId}/versions${streamQuery(stream)}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  activateStewardPolicy: (policyId: StewardPolicyId, body: { version: number; approved_by: string }, stream?: string) =>
    request(`/api/stewardship/policies/${policyId}/activate${streamQuery(stream)}`, { method: "POST", body: JSON.stringify(body) }),
  listBenchmarks: () => request<{ benchmarks: BenchmarkInfo[] }>("/api/stewardship/benchmarks"),
  uploadBenchmark: (text: string, uploadedBy: string) =>
    request<BenchmarkInfo>("/api/stewardship/benchmarks", { method: "POST", body: JSON.stringify({ text, uploaded_by: uploadedBy }) }),
  getProgram: (streamId: string) =>
    request<{
      saved: { params: ProgramParams; updated_by: string; updated_at: string } | null;
      versions: ProgramVersion[];
      runs: ProgramRun[];
      simulation: ProgramSimulation;
    }>(
      `/api/stewardship/streams/${encodeURIComponent(streamId)}/program`,
    ),
  simulateProgram: (streamId: string, params: ProgramParams) =>
    request<ProgramSimulation>(`/api/stewardship/streams/${encodeURIComponent(streamId)}/program/simulate`, {
      method: "POST",
      body: JSON.stringify({ params }),
    }),
  saveProgram: (streamId: string, params: ProgramParams, updatedBy: string) =>
    request(`/api/stewardship/streams/${encodeURIComponent(streamId)}/program`, {
      method: "PUT",
      body: JSON.stringify({ params, updated_by: updatedBy }),
    }),
  approveProgram: (streamId: string, approvedBy: string) =>
    request<ProgramVersion>(`/api/stewardship/streams/${encodeURIComponent(streamId)}/program/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: approvedBy }),
    }),
  monitorProgram: (streamId: string) => request<ProgramMonitor>(`/api/stewardship/streams/${encodeURIComponent(streamId)}/program/monitor`),
  recordProgramRun: (streamId: string, recordedBy: string) =>
    request<ProgramRun>(`/api/stewardship/streams/${encodeURIComponent(streamId)}/program/runs`, {
      method: "POST",
      body: JSON.stringify({ recorded_by: recordedBy }),
    }),
  programProposalUrl: (streamId: string) => `${API_BASE}/api/stewardship/streams/${encodeURIComponent(streamId)}/program/proposal.pptx`,
  checkStyle: (text: string) =>
    request<{ flags: StyleFlag[] }>("/api/stewardship/style/check", { method: "POST", body: JSON.stringify({ text }) }),
  listDrafts: () => request<{ drafts: OutreachDraft[] }>("/api/stewardship/drafts"),
  createDraft: (body: { company_id: string; issue_id: string; type: string; text: string; created_by: string }) =>
    request<OutreachDraft>("/api/stewardship/drafts", { method: "POST", body: JSON.stringify(body) }),
  updateDraft: (draftId: string, body: { updated_by: string; text?: string; interaction_type?: InteractionType }) =>
    request<OutreachDraft>(`/api/stewardship/drafts/${encodeURIComponent(draftId)}`, { method: "PUT", body: JSON.stringify(body) }),
  approveDraft: (draftId: string, body: { approved_by: string; note?: string }) =>
    request<OutreachDraft>(`/api/stewardship/drafts/${encodeURIComponent(draftId)}/approve`, { method: "POST", body: JSON.stringify(body) }),
  markDraftSent: (draftId: string, sentBy: string) =>
    request<OutreachDraft>(`/api/stewardship/drafts/${encodeURIComponent(draftId)}/sent`, {
      method: "POST",
      body: JSON.stringify({ sent_by: sentBy }),
    }),
  getTracking: () => request<{ commitments: TrackedCommitment[]; engagements: TrackedEngagement[] }>("/api/stewardship/tracking"),
  addCommitment: (body: { company_id: string; issue_id: string; text: string; target_date?: string; recorded_by: string }) =>
    request("/api/stewardship/tracking/commitments", { method: "POST", body: JSON.stringify(body) }),
  setCommitmentStatus: (commitmentId: string, body: { company_id: string; issue_id: string; status: "verified" | "missed"; decided_by: string }) =>
    request(`/api/stewardship/tracking/commitments/${encodeURIComponent(commitmentId)}`, { method: "POST", body: JSON.stringify(body) }),
  closeEngagement: (body: { company_id: string; issue_id: string; status: "resolved" | "closed"; outcome: string; decided_by: string }) =>
    request("/api/stewardship/tracking/close", { method: "POST", body: JSON.stringify(body) }),
  getCaseStudy: (companyId: string, issueId: string) =>
    request<CaseStudy>(`/api/stewardship/tracking/case-study/${encodeURIComponent(companyId)}/${encodeURIComponent(issueId)}`),
  getClientReport: (streamId: string) => request<ClientReport>(`/api/stewardship/streams/${encodeURIComponent(streamId)}/report`),
  clientReportPptxUrl: (streamId: string) => `${API_BASE}/api/stewardship/streams/${encodeURIComponent(streamId)}/report.pptx`,
  getClientEscalationExample: () => request<Record<string, unknown>>("/api/stewardship/studio/escalation/client-example"),
  previewClientEscalation: (streamId: string, graph: unknown) =>
    request<ClientEscalationPreview>(`/api/stewardship/streams/${encodeURIComponent(streamId)}/studio/escalation/preview`, {
      method: "POST",
      body: JSON.stringify({ graph }),
    }),
  decideClientException: (
    streamId: string,
    body: { issue_id: string; client_step: string; decision: "adopt" | "decline"; decided_by: string; note?: string },
  ) => request(`/api/stewardship/streams/${encodeURIComponent(streamId)}/exceptions`, { method: "POST", body: JSON.stringify(body) }),
  getIssueCatalogue: () => request<IssueCatalogue>("/api/stewardship/catalogue"),
  getCoverageInputs: () => request<{ contexts: Record<string, unknown>[] }>("/api/stewardship/studio/coverage/inputs"),
  previewCoverage: (graph: unknown) =>
    request<CoveragePreview>("/api/stewardship/studio/coverage/preview", { method: "POST", body: JSON.stringify({ graph }) }),
  getMonitoringTriggers: () => request<{ triggers: MonitoringTrigger[] }>("/api/stewardship/studio/monitoring/triggers"),
  previewMonitoring: (graph: unknown) =>
    request<MonitoringPreview>("/api/stewardship/studio/monitoring/preview", { method: "POST", body: JSON.stringify({ graph }) }),
  openEngagementFromTrigger: (body: { issuer_id: string; rule: string; decided_by: string }) =>
    request<{ issue_id: string }>("/api/stewardship/monitoring/open-engagement", { method: "POST", body: JSON.stringify(body) }),
  getEscalationRecommendations: () =>
    request<{ recommendations: EscalationRecommendation[] }>("/api/stewardship/studio/escalation/recommendations"),
  previewEscalation: (graph: unknown) =>
    request<EscalationPreview>("/api/stewardship/studio/escalation/preview", { method: "POST", body: JSON.stringify({ graph }) }),
  previewVoting: (policy: unknown) =>
    request<VotingPreview>("/api/stewardship/studio/voting/preview", { method: "POST", body: JSON.stringify({ policy }) }),
  buildStreamPolicy: (streamId: string) =>
    request<{ positions_from_client: number }>(`/api/stewardship/streams/${encodeURIComponent(streamId)}/build`, { method: "POST" }),
  listEngagementRecords: () => request<{ records: unknown[] }>("/api/engagement/records"),
  createEngagementRecord: (body: { company_id: string; name: string; sector?: string | null }) =>
    request("/api/engagement/records", { method: "POST", body: JSON.stringify(body) }),
  getEngagementRecord: (companyId: string) => request(`/api/engagement/records/${encodeURIComponent(companyId)}`),
  addEngagementContact: (companyId: string, body: unknown) =>
    request(`/api/engagement/records/${encodeURIComponent(companyId)}/contacts`, { method: "POST", body: JSON.stringify(body) }),
  openEngagementIssue: (companyId: string, name: string, body: { theme: string; severity?: string; source_detail?: string; sector?: string | null }) =>
    request(`/api/engagement/records/${encodeURIComponent(companyId)}/issues?name=${encodeURIComponent(name)}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getEngagementNextAction: (companyId: string, issueId: string) =>
    request(`/api/engagement/records/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/next-action`),
  escalateEngagementIssue: (companyId: string, issueId: string, body: { stage: string; decided_by: string; reason?: string }) =>
    request(`/api/engagement/records/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/escalate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  triggerScan: (body: { companies: unknown[]; signals: unknown[] }) =>
    request<{ events: TriggerEvent[] }>("/api/engagement/trigger-scan", { method: "POST", body: JSON.stringify(body) }),
  draftDossier: (companyId: string, issueId: string, company: unknown) =>
    request<{ dossier: ResearchDossier; needs_review: boolean }>(
      `/api/engagement/records/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/dossier`,
      { method: "POST", body: JSON.stringify(company) },
    ),
  draftOutreachLetter: (companyId: string, issueId: string, body: { company_name: string; recipient: string; dossier: unknown; house_style_notes?: string }) =>
    request(`/api/engagement/records/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/outreach-letter`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  draftTalkingPoints: (companyId: string, issueId: string, body: { company_name: string; dossier: unknown }) =>
    request(`/api/engagement/records/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/talking-points`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  draftMeetingSummary: (companyId: string, issueId: string, body: { company_name: string; notes_or_transcript: string }) =>
    request(`/api/engagement/records/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/meeting-summary`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  logOutreachSent: (companyId: string, issueId: string, body: { summary: string; sent_by: string; doc_ref?: string | null }) =>
    request(`/api/engagement/records/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/log-outreach-sent`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  logMeetingSummaryValidated: (
    companyId: string,
    issueId: string,
    body: { summary: string; commitments?: string[]; validated_by: string },
  ) =>
    request(`/api/engagement/records/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/log-meeting-summary-validated`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  verifyCommitment: (companyId: string, issueId: string, body: { commitment_id: string; verified_by: string }) =>
    request(`/api/engagement/records/${encodeURIComponent(companyId)}/issues/${encodeURIComponent(issueId)}/verify-commitment`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Voting (proxy)
  startVotingRun: (body: { companies?: unknown[]; universe_path?: string; meeting_dates?: Record<string, string> }) =>
    request<{ run_id: string; company_count: number }>("/api/voting/runs", { method: "POST", body: JSON.stringify(body) }),
  getVotingBallots: (runId: string) => request<{ ballots: CompanyBallot[] }>(`/api/voting/runs/${runId}/ballots`),
  getVotingReviewQueue: (runId: string) =>
    request<{ pending: Record<string, unknown>[]; decided: { item: Record<string, unknown>; decision: VoteReviewDecision }[] }>(
      `/api/voting/runs/${runId}/review-queue`,
    ),
  submitVotingReview: (
    runId: string,
    body: { item_key: string; decision: "approve" | "edit" | "reject"; reviewer: string; vote?: string | null; co_signed_by?: string | null; comment?: string | null },
  ) => request(`/api/voting/runs/${runId}/review`, { method: "POST", body: JSON.stringify(body) }),
  castVotes: (runId: string) => request<{ cast_count: number; votes: VoteRecord[] }>(`/api/voting/runs/${runId}/cast`, { method: "POST" }),
  getCastVotes: (runId: string) => request<{ votes: VoteRecord[] }>(`/api/voting/runs/${runId}/cast`),
  // Portfolio risk & exposure monitoring
  seedPortfolioDemo: () => request<DemoSeedSummary>("/api/portfolio/demo/seed", { method: "POST" }),
  seedTransitionPlanDemo: () => request<{ run_id: string; company_count: number }>("/api/transition-plan/demo/seed", { method: "POST" }),
  listPortfolios: () => request<PortfolioSummary[]>("/api/portfolio/portfolios"),
  listSecuritiesNeedingReview: () => request<SecurityResolution[]>("/api/portfolio/securities-needing-review"),
  holdingsUniverse: (body: { portfolio_ids: string[]; as_of?: string }) =>
    request<{ path: string; company_count: number; as_of: string; unresolved: number }>("/api/portfolio/universe", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listPortfolioCompanies: () => request<CompanyRef[]>("/api/portfolio/companies"),
  listConflictingObservations: () => request<DataPointObservation[]>("/api/portfolio/climate-conflicts"),
  runPortfolioAggregate: (body: AnalyticRequest) =>
    request<AggregationResult | TrendPoint[]>("/api/portfolio/aggregate", { method: "POST", body: JSON.stringify(body) }),
  runPortfolioPivot: (body: PivotRequest) => request<PivotResult>("/api/portfolio/pivot", { method: "POST", body: JSON.stringify(body) }),
  askPortfolio: (question: string) => request<QAAnswer>("/api/portfolio/ask", { method: "POST", body: JSON.stringify({ question }) }),
  listPortfolioNews: (companyId?: string) => request<NewsItem[]>(`/api/portfolio/news${buildQuery({ company_id: companyId })}`),
  listNewsFlags: (companyId?: string) => request<NewsRiskFlag[]>(`/api/portfolio/news/flags${buildQuery({ company_id: companyId })}`),
  listMonitoringRules: () => request<AlertRule[]>("/api/portfolio/monitoring/rules"),
  createMonitoringRule: (rule: Omit<AlertRule, "rule_id" | "created_at">) =>
    request<AlertRule>("/api/portfolio/monitoring/rules", { method: "POST", body: JSON.stringify(rule) }),
  listAlerts: (status?: AlertStatus) => request<Alert[]>(`/api/portfolio/monitoring/alerts${buildQuery({ status })}`),
  transitionAlert: (scopeId: string, alertId: string, body: { status: AlertStatus; decided_by: string; reason?: string; owner?: string }) =>
    request<Alert>(`/api/portfolio/monitoring/alerts/${encodeURIComponent(scopeId)}/${encodeURIComponent(alertId)}/transition`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  evaluateMonitoringNow: () =>
    request<{ threshold_alerts_raised: number; news_alerts_raised: number }>("/api/portfolio/monitoring/evaluate-now", { method: "POST" }),
  listPendingGovernanceReviews: () =>
    request<{ entity_resolution: SecurityResolution[]; climate_conflict: DataPointObservation[] }>("/api/portfolio/governance/pending-reviews"),
  recordGovernanceDecision: (body: {
    item_type: GovernanceItemType;
    item_key: string;
    decision: GovernanceDecisionType;
    decided_by: string;
    reason?: string;
    override_value?: number | string | boolean | null;
  }) => request<GovernanceDecision>("/api/portfolio/governance/decisions", { method: "POST", body: JSON.stringify(body) }),
  listGovernanceDecisions: (itemType?: GovernanceItemType) =>
    request<GovernanceDecision[]>(`/api/portfolio/governance/decisions${buildQuery({ item_type: itemType })}`),
  getGovernancePolicy: () =>
    request<{ values: Record<PolicySettingName, number>; history: PolicyChange[] }>("/api/portfolio/governance/policy"),
  updateGovernancePolicy: (body: { setting_name: PolicySettingName; new_value: number; changed_by: string; reason?: string }) =>
    request<PolicyChange>("/api/portfolio/governance/policy", { method: "PUT", body: JSON.stringify(body) }),
  listGovernanceOwners: () => request<RiskCategoryOwner[]>("/api/portfolio/governance/owners"),
  assignGovernanceOwner: (category: string, body: { owner: string; assigned_by: string }) =>
    request<RiskCategoryOwner>(`/api/portfolio/governance/owners/${encodeURIComponent(category)}`, { method: "PUT", body: JSON.stringify(body) }),

  // Superset BI designer (/api/bi): drafts dashboards in Superset itself
  designBI: (body: { brief: string }) => request<BIDesignResult>("/api/bi/design", { method: "POST", body: JSON.stringify(body) }),
  askBI: (question: string) => request<BIDesignResult>("/api/bi/ask", { method: "POST", body: JSON.stringify({ question }) }),
  biDashboards: () => request<DashboardItem[]>("/api/bi/dashboards"),
  biEmbedToken: (dashboardId: number) =>
    request<BIEmbedToken>("/api/bi/embed-token", { method: "POST", body: JSON.stringify({ dashboard_id: String(dashboardId) }) }),

  // Projects (/api/projects)
  listProjects: () => request<ProjectSummary[]>("/api/projects"),
  createProject: (body: { name: string; description: string }) =>
    request<{ id: string; name: string }>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  uploadProjectData: (id: string, file: File, notionalEur: number) => {
    const form = new FormData();
    form.append("file", file);
    form.append("notional_eur", String(notionalEur));
    return request<{ id: string }>(`/api/projects/${encodeURIComponent(id)}/data`, { method: "POST", body: form });
  },
  openProject: (id: string) => request<OpenResult>(`/api/projects/${encodeURIComponent(id)}/open`, { method: "POST" }),
  saveProjectDashboard: (id: string, body: { title: string; plan: BIChartPlan }) =>
    request<OpenedDashboard>(`/api/projects/${encodeURIComponent(id)}/dashboards`, { method: "POST", body: JSON.stringify(body) }),
  exportProjectDashboard: (id: string, dashboardId: number) =>
    request<ExportedDashboard>(`/api/projects/${encodeURIComponent(id)}/dashboards/export`, {
      method: "POST",
      body: JSON.stringify({ dashboard_id: dashboardId }),
    }),

  // Climate analytics
  getClimateSchema: () => request<DataPointSchema>("/api/climate/schema"),
  getWaci: (params: { as_of?: string; group_by?: string; portfolio_id?: string[] }) =>
    request<AggregationResult>(`/api/climate/waci${buildQuery(params)}`),
  getWaciTrend: (params: { group_by?: string; portfolio_id?: string[] }) =>
    request<TrendPoint[]>(`/api/climate/waci/trend${buildQuery(params)}`),
  getFinancedEmissions: (params: { as_of?: string; portfolio_id?: string[] }) =>
    request<FinancedEmissionsResult>(`/api/climate/financed-emissions${buildQuery(params)}`),
  getClimateCoverage: (fieldId: string, asOf?: string) =>
    request<CoverageBySource>(`/api/climate/coverage/${fieldId}${buildQuery({ as_of: asOf })}`),

  // Presentation & Reporting Tool
  uploadReportTemplate: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<TemplateStyleProfile>("/api/reports/templates", { method: "POST", headers: {}, body: form });
  },
  listReportTemplates: () => request<{ templates: TemplateStyleProfile[] }>("/api/reports/templates"),
  uploadReportDataset: (file: File, name?: string) => {
    const form = new FormData();
    form.append("file", file);
    return request<QuantitativeDataset>(`/api/reports/datasets/upload${buildQuery({ name })}`, { method: "POST", headers: {}, body: form });
  },
  createReport: (body: ReportRequest, render = false) =>
    request<ReportManifest>(`/api/reports${buildQuery({ render: String(render) })}`, { method: "POST", body: JSON.stringify(body) }),
  listReports: () => request<{ reports: ReportManifest[] }>("/api/reports"),
  getReport: (reportId: string) => request<ReportManifest>(`/api/reports/${encodeURIComponent(reportId)}`),
  getReportPlan: (reportId: string) => request<ReportPlan>(`/api/reports/${encodeURIComponent(reportId)}/plan`),
  updateReportPlan: (reportId: string, plan: ReportPlan) =>
    request<ReportPlan>(`/api/reports/${encodeURIComponent(reportId)}/plan`, { method: "PUT", body: JSON.stringify(plan) }),
  renderReport: (reportId: string) => request<ReportManifest>(`/api/reports/${encodeURIComponent(reportId)}/render`, { method: "POST" }),
  getStoryline: (reportId: string) => request<Storyline>(`/api/reports/${encodeURIComponent(reportId)}/storyline`),
  updateStoryline: (reportId: string, storyline: Storyline) =>
    request<Storyline>(`/api/reports/${encodeURIComponent(reportId)}/storyline`, { method: "PUT", body: JSON.stringify(storyline) }),
  approveStoryline: (reportId: string) =>
    request<ReportManifest>(`/api/reports/${encodeURIComponent(reportId)}/storyline/approve`, { method: "POST" }),
  getReportFindings: (reportId: string) => request<{ findings: Finding[] }>(`/api/reports/${encodeURIComponent(reportId)}/findings`),
  reportDownloadUrl: (reportId: string, file?: string) =>
    `${API_BASE}/api/reports/${encodeURIComponent(reportId)}/download${buildQuery({ file })}`,
  getReportPreview: (reportId: string) => request<{ page_count: number }>(`/api/reports/${encodeURIComponent(reportId)}/preview`),
  reportPreviewPageUrl: (reportId: string, page: number) => `${API_BASE}/api/reports/${encodeURIComponent(reportId)}/preview/${page}`,


  // Investment Strategy Replication
  discoverReplicationPapers: (topic: string, maxCandidates = 10) =>
    request<{ candidates: PaperCandidate[] }>("/api/replication/discover", {
      method: "POST",
      body: JSON.stringify({ topic, max_candidates: maxCandidates }),
    }),
  createSpecDraft: (paperCitation: string, paperText: string) =>
    request<{ spec_run_id: string; spec: StrategySpec; approved: boolean }>("/api/replication/specs", {
      method: "POST",
      body: JSON.stringify({ paper_citation: paperCitation, paper_text: paperText }),
    }),
  getSpecDraft: (specRunId: string) => request<SpecReviewState>(`/api/replication/specs/${encodeURIComponent(specRunId)}`),
  updateSpecDraft: (specRunId: string, spec: StrategySpec) =>
    request<{ spec_run_id: string; spec: StrategySpec; approved: boolean }>(`/api/replication/specs/${encodeURIComponent(specRunId)}`, {
      method: "PUT",
      body: JSON.stringify(spec),
    }),
  reviseSpecDraft: (specRunId: string, instruction: string) =>
    request<{ spec_run_id: string; spec: StrategySpec; approved: boolean }>(`/api/replication/specs/${encodeURIComponent(specRunId)}/revise`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    }),
  approveSpecDraft: (specRunId: string, reviewer?: string) =>
    request<{ spec_run_id: string; spec: StrategySpec; approved: boolean }>(`/api/replication/specs/${encodeURIComponent(specRunId)}/approve`, {
      method: "POST",
      body: JSON.stringify({ reviewer }),
    }),
  uploadPriceDataset: (specRunId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ ref: string }>(`/api/replication/specs/${encodeURIComponent(specRunId)}/datasets/prices`, {
      method: "POST",
      headers: {},
      body: form,
    });
  },
  uploadCharacteristicsDataset: (specRunId: string, name: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ ref: string }>(
      `/api/replication/specs/${encodeURIComponent(specRunId)}/datasets/characteristics/${encodeURIComponent(name)}`,
      { method: "POST", headers: {}, body: form }
    );
  },
  runReplicationBacktest: (
    specRunId: string,
    body: {
      tickers: string[];
      prices_ref: string;
      characteristics_refs?: Record<string, string>;
      price_kind?: string;
      benchmark?: string | null;
      out_of_sample_start?: string | null;
      out_of_sample_end?: string | null;
    }
  ) =>
    request<{ run_id: string; verdict: string }>(`/api/replication/specs/${encodeURIComponent(specRunId)}/backtest`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getReplicationRunDetail: (runId: string) => request<ReplicationRunDetail>(`/api/replication/runs/${encodeURIComponent(runId)}`),
  runReplicationSanityCheck: (runId: string) =>
    request<SanityCheckAssessment>(`/api/replication/runs/${encodeURIComponent(runId)}/sanity-check`, { method: "POST" }),
  runReplicationRegimeReport: (runId: string, trailingWindowMonths = 12) =>
    request<RegimeStratifiedReport>(
      `/api/replication/runs/${encodeURIComponent(runId)}/regime-report${buildQuery({ trailing_window_months: String(trailingWindowMonths) })}`,
      { method: "POST" }
    ),

  // trail records.
  uploadDecisionDataset: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DatasetSummary>("/api/decision/datasets", { method: "POST", body: form });
  },
  decisionDatasetFromSource: (body: { source: string; run_id?: string; run_ids?: string[]; as_of?: string; portfolio_ids?: string[]; region?: string; sectors?: string[]; include_indicators?: boolean }) =>
    request<DatasetSummary>("/api/decision/datasets/from-source", { method: "POST", body: JSON.stringify(body) }),
  listDecisionDatasets: () => request<DatasetSummary[]>("/api/decision/datasets"),
  calculatedColumns: (datasetId: string, ruleGraph: RuleGraph) =>
    request<DatasetSummary>(`/api/decision/datasets/${datasetId}/calculated`, { method: "POST", body: JSON.stringify({ rule_graph: ruleGraph }) }),
  deriveMechanism: (body: { dataset_id: string; name?: string; cluster_threshold?: number; save?: boolean; framework_id?: string }) =>
    request<MechanismEnvelope>("/api/decision/mechanisms/derive", { method: "POST", body: JSON.stringify(body) }),
  saveMechanism: (body: { config: MechanismConfig; base_version?: number | null; by?: string | null }) =>
    request<MechanismEnvelope>("/api/decision/mechanisms", { method: "POST", body: JSON.stringify(body) }),
  ratifyMechanism: (frameworkId: string, version: number | undefined, ratifiedBy: string) =>
    request<MechanismConfig>(`/api/decision/mechanisms/${frameworkId}/ratify${buildQuery({ version: version ? String(version) : undefined, ratified_by: ratifiedBy })}`, {
      method: "POST",
    }),
  scoreDecision: (body: { dataset_id: string; config?: MechanismConfig; framework_id?: string; version?: number }) =>
    request<DecisionResult>("/api/decision/score", { method: "POST", body: JSON.stringify(body) }),
  decisionSensitivity: (body: { dataset_id: string; config?: MechanismConfig; entity_keys?: string[]; steps?: number }) =>
    request<EntitySensitivity[]>("/api/decision/sensitivity", { method: "POST", body: JSON.stringify(body) }),
  compareDecisions: (body: { dataset_id_before: string; dataset_id_after: string; config?: MechanismConfig; framework_id?: string; version?: number }) =>
    request<DecisionComparison>("/api/decision/compare", { method: "POST", body: JSON.stringify(body) }),
  decisionExportUrl: () => `${API_BASE}/api/decision/export.csv`,
  getMechanism: (frameworkId: string, version?: number) =>
    request<MechanismEnvelope>(`/api/decision/mechanisms/${frameworkId}${buildQuery({ version: version ? String(version) : undefined })}`),
  exportMechanismUrl: (frameworkId: string, version?: number) =>
    `${API_BASE}/api/decision/mechanisms/${frameworkId}/export${buildQuery({ version: version ? String(version) : undefined })}`,
  importMechanism: (template: unknown, by?: string) =>
    request<MechanismEnvelope>("/api/decision/mechanisms/import", { method: "POST", body: JSON.stringify({ template, by }) }),
  importIndicatorList: (file: File, name: string, by?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    if (by) form.append("by", by);
    return request<MechanismEnvelope>("/api/decision/mechanisms/from-indicators", { method: "POST", body: form });
  },
  matchTemplates: (body: { run_type?: RunScoringKind; field_names?: string[]; columns?: string[] }) =>
    request<TemplateMatch[]>("/api/decision/templates/match", { method: "POST", body: JSON.stringify(body) }),
  attachRunFramework: (runId: string, frameworkId: string, version?: number) =>
    request(`/api/decision/runs/${runId}/framework`, { method: "PUT", body: JSON.stringify({ framework_id: frameworkId, version }) }),
  getRunDecision: (runId: string) => request<RunDecision>(`/api/decision/runs/${runId}/decision`),
  setRunOverride: (runId: string, body: LevelOverride) =>
    request<RunDecision>(`/api/decision/runs/${runId}/overrides`, { method: "POST", body: JSON.stringify(body) }),
  removeRunOverride: (runId: string, body: { entity_key: string; criterion_id: string; reviewer: string; reason: string }) =>
    request<RunDecision>(`/api/decision/runs/${runId}/overrides/remove`, { method: "POST", body: JSON.stringify(body) }),
  getDatasetOverrides: (datasetId: string) => request<OverridesView>(`/api/decision/datasets/${datasetId}/overrides`),
  setDatasetOverride: (datasetId: string, body: LevelOverride) =>
    request<OverridesView>(`/api/decision/datasets/${datasetId}/overrides`, { method: "POST", body: JSON.stringify(body) }),
  removeDatasetOverride: (datasetId: string, body: { entity_key: string; criterion_id: string; reviewer: string; reason: string }) =>
    request<OverridesView>(`/api/decision/datasets/${datasetId}/overrides/remove`, { method: "POST", body: JSON.stringify(body) }),
  rescoreRunDecision: (runId: string) => request<RunDecision>(`/api/decision/runs/${runId}/decision/rescore`, { method: "POST" }),
  publishRunDecision: (runId: string, publishedBy: string) =>
    request<PublishedDecision>(`/api/decision/runs/${runId}/publish`, { method: "POST", body: JSON.stringify({ published_by: publishedBy }) }),
  publishDecision: (body: { dataset_id: string; framework_id: string; version?: number; published_by: string; id_column?: string; note?: string }) =>
    request<PublishedDecision>("/api/decision/publish", { method: "POST", body: JSON.stringify(body) }),
  listPublishedDecisions: () => request<PublishedDecision[]>("/api/decision/published"),
  getHouseUniverse: () =>
    request<{ source: "sample" | "portfolio"; set_by: string | null; set_at: string | null; issuers: number; note: string | null }>(
      "/api/stewardship/universe",
    ),
  setHouseUniverse: (body: { source: "sample" | "portfolio"; set_by: string }) =>
    request<{ source: "sample" | "portfolio"; issuers: number }>("/api/stewardship/universe", { method: "PUT", body: JSON.stringify(body) }),
  getDecisionInputs: () => request<{ in_scope: number; published: DecisionInput[] }>("/api/stewardship/decision-inputs"),
  // Index construction
  getIndexCatalogue: () => request<IndexCatalogue>("/api/index/catalogue"),
  getIndexPreset: (name: string) => request<ConstructionSpec>(`/api/index/presets/${name}`),
  getIndexScreenBundle: (name: string) =>
    request<{ name: string; screens: ConstructionSpec["screens"] }>(`/api/index/screen-bundles/${name}`),
  listIndexCalibrations: () => request<IndexCalibration[]>("/api/index/calibrations"),
  getIndexCalibration: (calibrationId: string, version?: number) =>
    request<IndexCalibration>(`/api/index/calibrations/${calibrationId}${buildQuery({ version: version?.toString() })}`),
  listIndexCalibrationVersions: (calibrationId: string) =>
    request<IndexCalibration[]>(`/api/index/calibrations/${calibrationId}/versions`),
  createIndexCalibration: (body: { name: string; effective_from: string; spec: ConstructionSpec; notes?: string; approved_by?: string[] }) =>
    request<IndexCalibration>("/api/index/calibrations", { method: "POST", body: JSON.stringify(body) }),
  createIndexCalibrationVersion: (
    calibrationId: string,
    body: { name: string; effective_from: string; spec: ConstructionSpec; notes?: string; approved_by?: string[] },
  ) => request<IndexCalibration>(`/api/index/calibrations/${calibrationId}/versions`, { method: "POST", body: JSON.stringify(body) }),
  runIndexReview: (body: {
    index_id: string;
    review_date: string;
    spec?: ConstructionSpec;
    calibration_id?: string;
    persist?: boolean;
    use_prior_state?: boolean;
    decision_snapshot_ids?: string[];
  }) => request<IndexReviewResult>("/api/index/run", { method: "POST", body: JSON.stringify(body) }),
};
