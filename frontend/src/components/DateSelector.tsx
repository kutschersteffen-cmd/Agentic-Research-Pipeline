import { usePortfolioPane } from "../context/usePortfolioPane";
import { trendRangeError } from "../lib/askPortfolio";

/** Latest / as-of-date / trend-range control, reading and writing the
 * shared pane context directly -- Section 2's point-in-time versioning
 * surfaced as a literal, persistent control rather than a per-sub-tab
 * text input re-implemented everywhere. */
export function DateSelector() {
  const { dateMode, setDateMode, asOfDate, setAsOfDate, trendFrom, setTrendFrom, trendTo, setTrendTo } = usePortfolioPane();
  const rangeError = trendRangeError(trendFrom, trendTo);

  return (
    <div>
      <div className="field-label" id="date-mode-label">As of</div>
      <div className="view-toggle" role="group" aria-labelledby="date-mode-label">
        <button className={dateMode === "latest" ? "active" : ""} onClick={() => setDateMode("latest")}>
          Latest
        </button>
        <button className={dateMode === "as_of" ? "active" : ""} onClick={() => setDateMode("as_of")}>
          As of date
        </button>
        <button className={dateMode === "trend" ? "active" : ""} onClick={() => setDateMode("trend")}>
          Trend range
        </button>
      </div>
      {dateMode === "as_of" && (
        <input type="date" aria-label="As-of date" max={new Date().toISOString().slice(0, 10)} value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} />
      )}
      {dateMode === "trend" && (
        <div className="inline-fields">
          <div>
            <label className="field-label">
              From
              <input type="date" aria-label="Trend start date" value={trendFrom} onChange={(e) => setTrendFrom(e.target.value)} />
            </label>
          </div>
          <div>
            <label className="field-label">
              To
              <input type="date" aria-label="Trend end date" value={trendTo} onChange={(e) => setTrendTo(e.target.value)} />
            </label>
          </div>
        </div>
      )}
      {dateMode === "trend" && rangeError && <p className="error-text" role="alert">{rangeError}</p>}
    </div>
  );
}
