export const benchmarkScript = String.raw`async () => {
  const [benchmark] = await codemode.listBenchmarks({});
  const input = { benchmark_id: benchmark.benchmark_id };
  const coverage = await codemode.getBenchmarkSectors(input);
  const topSectors = await Promise.all(coverage.sectors.slice(0, 2).map(async (row) => ({
    ...row,
    largest_issuer: (await codemode.listSectorIssuers({ ...input, sector: row.sector }))[0],
  })));
  return {
    benchmark: benchmark.name,
    synthetic: benchmark.synthetic,
    constituents: coverage.constituents,
    total_weight_pct: coverage.total_weight_pct,
    top_sectors: topSectors,
  };
}`;
