import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { PortfolioPaneContext, type PaneState, type PortfolioGroup, type DateMode } from "./paneContext";
import type { DataPointSchema, PortfolioSummary } from "../types";

const GROUPS_STORAGE_KEY = "arp_portfolio_groups";

function loadGroupsFromStorage(): PortfolioGroup[] {
  try {
    const raw = localStorage.getItem(GROUPS_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PortfolioGroup[]) : [];
  } catch {
    return [];
  }
}

function saveGroupsToStorage(groups: PortfolioGroup[]) {
  try {
    localStorage.setItem(GROUPS_STORAGE_KEY, JSON.stringify(groups));
  } catch {
    /* localStorage unavailable (private window, quota) -- groups just won't persist this session */
  }
}

export function PortfolioPaneProvider({ children }: { children: ReactNode }) {
  const [portfolios, setPortfolios] = useState<PortfolioSummary[]>([]);
  const [climateSchema, setClimateSchema] = useState<DataPointSchema | null>(null);
  const [selectedPortfolioIds, setSelectedPortfolioIds] = useState<string[]>([]);
  const [groups, setGroups] = useState<PortfolioGroup[]>(() => loadGroupsFromStorage());
  const [dateMode, setDateMode] = useState<DateMode>("latest");
  const [asOfDate, setAsOfDate] = useState("");
  const [trendFrom, setTrendFrom] = useState("");
  const [trendTo, setTrendTo] = useState("");

  const refreshPortfolios = useCallback(async () => {
    try {
      setPortfolios(await api.listPortfolios());
    } catch {
      setPortfolios([]);
    }
  }, []);

  useEffect(() => {
    refreshPortfolios();
    api.getClimateSchema().then(setClimateSchema).catch(() => setClimateSchema(null));
  }, [refreshPortfolios]);

  const saveCurrentAsGroup = useCallback(
    (name: string) => {
      const trimmed = name.trim();
      if (!trimmed) return;
      setGroups((prev) => {
        const next = [...prev.filter((g) => g.name !== trimmed), { name: trimmed, portfolioIds: selectedPortfolioIds }];
        saveGroupsToStorage(next);
        return next;
      });
    },
    [selectedPortfolioIds]
  );

  const loadGroup = useCallback(
    (name: string) => {
      const group = groups.find((g) => g.name === name);
      if (group) setSelectedPortfolioIds(group.portfolioIds);
    },
    [groups]
  );

  const deleteGroup = useCallback((name: string) => {
    setGroups((prev) => {
      const next = prev.filter((g) => g.name !== name);
      saveGroupsToStorage(next);
      return next;
    });
  }, []);

  const effectiveAsOf = dateMode === "as_of" && asOfDate ? asOfDate : undefined;
  const effectiveDateRange = useMemo<[string, string] | null>(
    () => (dateMode === "trend" && trendFrom && trendTo ? [trendFrom, trendTo] : null),
    [dateMode, trendFrom, trendTo]
  );

  const selectionLabel = useMemo(() => {
    const names =
      selectedPortfolioIds.length === 0
        ? "all portfolios"
        : selectedPortfolioIds.map((id) => portfolios.find((p) => p.portfolio_id === id)?.name ?? id).join(", ");
    if (dateMode === "trend" && effectiveDateRange) return `${names}, trend ${effectiveDateRange[0]} to ${effectiveDateRange[1]}`;
    if (dateMode === "as_of" && effectiveAsOf) return `${names}, as of ${effectiveAsOf}`;
    return `${names}, latest`;
  }, [selectedPortfolioIds, portfolios, dateMode, effectiveAsOf, effectiveDateRange]);

  const value: PaneState = {
    portfolios,
    refreshPortfolios,
    climateSchema,
    selectedPortfolioIds,
    setSelectedPortfolioIds,
    groups,
    saveCurrentAsGroup,
    loadGroup,
    deleteGroup,
    dateMode,
    setDateMode,
    asOfDate,
    setAsOfDate,
    trendFrom,
    setTrendFrom,
    trendTo,
    setTrendTo,
    effectiveAsOf,
    effectiveDateRange,
    selectionLabel,
  };

  return <PortfolioPaneContext.Provider value={value}>{children}</PortfolioPaneContext.Provider>;
}
