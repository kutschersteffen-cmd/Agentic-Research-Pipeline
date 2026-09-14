import { usePortfolioPane } from "../context/usePortfolioPane";

/** Latest / as-of-date / trend-range control, reading and writing the
 * shared pane context directly -- Section 2's point-in-time versioning
 * surfaced as a literal, persistent control rather than a per-sub-tab
 * text input re-implemented everywhere. */
export function DateSelector() {
  const { dateMode, setDateMode, asOfDate, setAsOfDate, trendFrom, setTrendFrom, trendTo, setTrendTo } = usePortfolioPane();

  return (
    <div>
      <label className="field-label">As of</label>
      <div className="view-toggle">
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
        <input type="text" placeholder="YYYY-MM-DD" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} />
      )}
      {dateMode === "trend" && (
        <div className="inline-fields">
          <div>
            <label className="field-label">From</label>
            <input type="text" placeholder="YYYY-MM-DD" value={trendFrom} onChange={(e) => setTrendFrom(e.target.value)} />
          </div>
          <div>
            <label className="field-label">To</label>
            <input type="text" placeholder="YYYY-MM-DD" value={trendTo} onChange={(e) => setTrendTo(e.target.value)} />
          </div>
        </div>
      )}
    </div>
  );
}
