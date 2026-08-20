import type {
  AggregationResult,
  AnalyticRequest,
  CoverageBySource,
  DataPointSchema,
  DemoSeedSummary,
  FinancedEmissionsResult,
  NewsItem,
  NewsRiskFlag,
  PivotRequest,
  PivotResult,
  PortfolioSummary,
  QAAnswer,
  SecurityResolution,
  TrendPoint,
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
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore parse failure */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  base: API_BASE,

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
  startExtractionRun: (body: unknown) =>
    request<{ run_id: string; company_count: number }>("/api/extraction/runs", { method: "POST", body: JSON.stringify(body) }),
  getExtractionResults: (runId: string, offset = 0, limit = 500) =>
    request(`/api/extraction/runs/${runId}/results?offset=${offset}&limit=${limit}`),
  getExtractionReviewQueue: (runId: string) => request(`/api/extraction/runs/${runId}/review-queue`),
  submitExtractionReview: (runId: string, body: unknown) =>
    request(`/api/extraction/runs/${runId}/review`, { method: "POST", body: JSON.stringify(body) }),
  getExtractionReviewDecisions: (runId: string) => request(`/api/extraction/runs/${runId}/review-decisions`),
  getExtractionReviewHistory: (runId: string, itemKey: string) =>
    request(`/api/extraction/runs/${runId}/review-history?item_key=${encodeURIComponent(itemKey)}`),

  // Company Financials (business segments + CapEx + R&D, one combined pass)
  startFinancialsRun: (body: unknown) =>
    request<{ run_id: string; company_count: number }>("/api/financials/runs", { method: "POST", body: JSON.stringify(body) }),
  getFinancialsResults: (runId: string, offset = 0, limit = 500) =>
    request(`/api/financials/runs/${runId}/results?offset=${offset}&limit=${limit}`),
  getFinancialsReviewQueue: (runId: string) => request(`/api/financials/runs/${runId}/review-queue`),
  submitFinancialsReview: (runId: string, body: unknown) =>
    request(`/api/financials/runs/${runId}/review`, { method: "POST", body: JSON.stringify(body) }),
  getFinancialsReviewDecisions: (runId: string) => request(`/api/financials/runs/${runId}/review-decisions`),
  getFinancialsReviewHistory: (runId: string, itemKey: string) =>
    request(`/api/financials/runs/${runId}/review-history?item_key=${encodeURIComponent(itemKey)}`),

  // Documents
  uploadDocument: (companyId: string, docType: string, file: File) => {
    const form = new FormData();
    form.append("company_id", companyId);
    form.append("doc_type", docType);
    form.append("file", file);
    return request("/api/documents/upload", { method: "POST", headers: {}, body: form });
  },
  listDocuments: (companyId: string) => request(`/api/documents/${companyId}`),
  documentRawUrl: (companyId: string, docType: string, filename: string) =>
    `${API_BASE}/api/documents/${encodeURIComponent(companyId)}/${encodeURIComponent(docType)}/${encodeURIComponent(filename)}/raw`,

  // Discovery
  startDiscoveryRun: (body: unknown) =>
    request<{ run_id: string; company_count: number }>("/api/discovery/runs", { method: "POST", body: JSON.stringify(body) }),
  getDiscoveryResults: (runId: string, offset = 0, limit = 500) =>
    request(`/api/discovery/runs/${runId}/results?offset=${offset}&limit=${limit}`),
  getDiscoveryEvents: (since?: string) => request(`/api/discovery/events${since ? `?since=${encodeURIComponent(since)}` : ""}`),
  getDiscoverySchedule: () => request("/api/discovery/schedule"),
  updateDiscoverySchedule: (config: unknown) =>
    request("/api/discovery/schedule", { method: "PUT", body: JSON.stringify(config) }),

  // Identity resolution (agentic name -> website/CIK, ahead of discovery)
  startIdentityRun: (body: unknown) =>
    request<{ run_id: string; company_count: number }>("/api/identity/runs", { method: "POST", body: JSON.stringify(body) }),
  getIdentityRun: (runId: string) => request(`/api/identity/runs/${runId}`),
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
  getRunErrors: (runId: string) => request(`/api/runs/${runId}/errors`),
  exportRunCsvUrl: (runId: string) => `${API_BASE}/api/runs/${runId}/export.csv`,
  cancelRun: (runId: string) => request(`/api/runs/${runId}/cancel`, { method: "POST" }),
  resumeThemeRun: (runId: string) => request(`/api/themes/runs/${runId}/resume`, { method: "POST" }),

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
  getTaxonomy: (taxonomyId: string, version?: number) =>
    request(`/api/taxonomies/${taxonomyId}${version ? `?version=${version}` : ""}`),
  listTaxonomyVersions: (taxonomyId: string) => request<{ versions: unknown[] }>(`/api/taxonomies/${taxonomyId}/versions`),
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

  // Portfolio risk & exposure monitoring
  seedPortfolioDemo: () => request<DemoSeedSummary>("/api/portfolio/demo/seed", { method: "POST" }),
  listPortfolios: () => request<PortfolioSummary[]>("/api/portfolio/portfolios"),
  listSecuritiesNeedingReview: () => request<SecurityResolution[]>("/api/portfolio/securities-needing-review"),
  runPortfolioAggregate: (body: AnalyticRequest) =>
    request<AggregationResult | TrendPoint[]>("/api/portfolio/aggregate", { method: "POST", body: JSON.stringify(body) }),
  runPortfolioPivot: (body: PivotRequest) => request<PivotResult>("/api/portfolio/pivot", { method: "POST", body: JSON.stringify(body) }),
  askPortfolio: (question: string) => request<QAAnswer>("/api/portfolio/ask", { method: "POST", body: JSON.stringify({ question }) }),
  listPortfolioNews: (companyId?: string) => request<NewsItem[]>(`/api/portfolio/news${buildQuery({ company_id: companyId })}`),
  classifyPortfolioNews: () =>
    request<{ classified: number; flags_created: number }>("/api/portfolio/news/classify", { method: "POST" }),
  listNewsFlags: (companyId?: string) => request<NewsRiskFlag[]>(`/api/portfolio/news/flags${buildQuery({ company_id: companyId })}`),

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
  getClimatePivot: (fieldId: string, params: { row_dim?: string; col_dim?: string; as_of?: string; portfolio_id?: string[] }) =>
    request<PivotResult>(`/api/climate/pivot/${fieldId}${buildQuery(params)}`),
};
