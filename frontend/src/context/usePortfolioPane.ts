import { useContext } from "react";
import { PortfolioPaneContext, type PaneState } from "./paneContext";

export function usePortfolioPane(): PaneState {
  const ctx = useContext(PortfolioPaneContext);
  if (!ctx) throw new Error("usePortfolioPane must be used within a PortfolioPaneProvider");
  return ctx;
}
