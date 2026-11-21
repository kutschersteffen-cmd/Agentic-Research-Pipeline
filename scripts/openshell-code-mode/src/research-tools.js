import { generateTypesFromJsonSchema } from "./codemode-portable.js";
import { z } from "zod";
import holdings from "./sample-holdings.json" with { type: "json" };

const benchmarkId = "arp-synthetic-sample";
export const source = {
  label: "ARP synthetic stewardship sample",
  synthetic: true,
  as_of: null,
  url: "https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/c7e65f54cc4d9b2ce95e680d234d6e0132b36992/backend/arp/stewardship/data/examples/sample_meetings.json",
};
const benchmark = z.strictObject({ benchmark_id: z.literal(benchmarkId) });
const weight = z.number().nonnegative();
const sector = z.object({ sector: z.string(), weight_pct: weight });
const issuer = sector.extend({ issuer_id: z.string(), name: z.string() });

export const researchTools = {
  listBenchmarks: {
    description: "List available benchmarks. The pilot includes one fictional sample.",
    input: z.strictObject({}),
    output: z.array(benchmark.extend({ name: z.string(), synthetic: z.boolean() })),
    run: () => [{ benchmark_id: benchmarkId, name: "ARP synthetic sample", synthetic: true }],
  },
  getBenchmarkSectors: {
    description: "Get ranked sector weights and coverage for one benchmark. Weights are in percentage points.",
    input: benchmark,
    output: z.object({ sectors: z.array(sector), constituents: z.number().int(), total_weight_pct: weight }),
    run: () => {
      const sectorBasisPoints = new Map();
      let totalBasisPoints = 0;
      for (const row of holdings) {
        const weight = Math.round(row.weight_pct * 100);
        sectorBasisPoints.set(row.sector, (sectorBasisPoints.get(row.sector) ?? 0) + weight);
        totalBasisPoints += weight;
      }
      const sectors = Array.from(sectorBasisPoints, ([sector, points]) => ({ sector, weight_pct: points / 100 }));
      sectors.sort((a, b) => b.weight_pct - a.weight_pct || a.sector.localeCompare(b.sector));
      return { sectors, constituents: holdings.length, total_weight_pct: totalBasisPoints / 100 };
    },
  },
  listSectorIssuers: {
    description: "Get fictional issuers in one benchmark sector, largest weight first.",
    input: benchmark.extend({ sector: z.string().trim().min(1).max(80) }),
    output: z.array(issuer),
    run: ({ sector }) => holdings.filter((row) => row.sector === sector)
      .sort((a, b) => b.weight_pct - a.weight_pct || a.issuer_id.localeCompare(b.issuer_id)),
  },
};

export function discoverTools(query) {
  const search = query.trim().toLowerCase();
  const descriptors = {};
  for (const [name, tool] of Object.entries(researchTools)) {
    if (![name, tool.description].some((text) => text.toLowerCase().includes(search))) continue;
    descriptors[name] = {
      description: tool.description,
      inputSchema: z.toJSONSchema(tool.input, { target: "draft-7" }),
      outputSchema: z.toJSONSchema(tool.output, { target: "draft-7" }),
    };
  }
  return { tools: Object.keys(descriptors), typescript: generateTypesFromJsonSchema(descriptors) };
}
