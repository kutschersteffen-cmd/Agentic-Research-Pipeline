import type { PortfolioSummary } from "../types";

export function PortfolioFilterPicker({
  portfolios,
  selected,
  onChange,
}: {
  portfolios: PortfolioSummary[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  function toggle(portfolioId: string) {
    onChange(selected.includes(portfolioId) ? selected.filter((id) => id !== portfolioId) : [...selected, portfolioId]);
  }

  if (portfolios.length === 0) {
    return <p className="muted">No portfolios yet.</p>;
  }

  return (
    <div>
      <label className="field-label">Portfolios (none selected = all)</label>
      {portfolios.map((p) => (
        <label key={p.portfolio_id} className="checkbox-label">
          <input type="checkbox" checked={selected.includes(p.portfolio_id)} onChange={() => toggle(p.portfolio_id)} />
          {p.name}
        </label>
      ))}
    </div>
  );
}
