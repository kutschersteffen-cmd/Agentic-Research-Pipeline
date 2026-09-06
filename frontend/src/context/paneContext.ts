import { createContext } from "react";
import type { DataPointSchema, PortfolioSummary } from "../types";

export type DateMode = "latest" | "as_of" | "trend";

export interface PortfolioGroup {
  name: string;
  portfolioIds: string[];
}

export interface PaneState {
  portfolios: PortfolioSummary[];
  refreshPortfolios: () => Promise<void>;
  climateSchema: DataPointSchema | null;

  selectedPortfolioIds: string[];
  setSelectedPortfolioIds: (ids: string[]) => void;

  groups: PortfolioGroup[];
  saveCurrentAsGroup: (name: string) => void;
  loadGroup: (name: string) => void;
  deleteGroup: (name: string) => void;

  dateMode: DateMode;
  setDateMode: (mode: DateMode) => void;
  asOfDate: string;
  setAsOfDate: (date: string) => void;
  trendFrom: string;
  setTrendFrom: (date: string) => void;
  trendTo: string;
  setTrendTo: (date: string) => void;

  /** as_of param for a point-in-time query -- undefined lets the backend pick "latest". */
  effectiveAsOf: string | undefined;
  /** date_range param for a trend query -- null when not in trend mode or the range isn't complete. */
  effectiveDateRange: [string, string] | null;
  /** Human-readable summary of the current selection, e.g. "Core Equity Europe, as of 2026-08-12". */
  selectionLabel: string;
}

export const PortfolioPaneContext = createContext<PaneState | null>(null);
