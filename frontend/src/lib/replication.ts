// Helpers of the Strategy Replication screen (docs/superpowers/specs/2026-11-23-strategy-replication-fixes.md, slice 3).

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** What the screen shows once a data file has been stored. */
export function uploadSummary(
  fileName: string,
  res: { tickers: string[]; rows: number; first_date: string; last_date: string },
): string {
  return `Uploaded ${fileName}: ${plural(res.tickers.length, "ticker")}, ${plural(res.rows, "row")}, ${res.first_date} to ${res.last_date}.`;
}

/** The text of an upload failure: the client's `<status>: <detail>` as it is, or a fixed line when nothing answered. */
export function uploadErrorText(err: unknown): string {
  if (err instanceof Error && /^\d{3}: /.test(err.message)) return err.message;
  return "Upload failed: no answer from the server.";
}

/** The ticker box after a price upload: an empty or blank box takes the file's tickers, a filled one is left alone. */
export function tickersAfterUpload(current: string, fileTickers: string[]): string {
  return current.trim() === "" ? fileTickers.join(", ") : current;
}

/** Drawdown DEPTH (always >= 0, 0 = at a new high) rather than signed
 * drawdown -- LineChart assumes a non-negative 0-based magnitude scale
 * (every other caller only ever charts positive metrics like WACI or
 * emissions); feeding it negative values breaks its y-axis scaling
 * entirely. A bigger depth number still reads as "worse", same as a
 * signed drawdown would, just flipped to fit the chart's actual scale.
 * While the peak is 0 or below (a period lost everything) the depth is 0. */
export function drawdownDepthSeries(index: number[]): number[] {
  let peak = -Infinity;
  return index.map((v) => {
    peak = Math.max(peak, v);
    return peak > 0 ? (1 - v / peak) * 100 : 0;
  });
}
