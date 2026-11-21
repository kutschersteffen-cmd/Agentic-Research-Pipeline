import { generateTypesFromJsonSchema } from "./codemode-portable.js";
import { z } from "zod";
import { maxCalls, checkedResult, ToolError } from "./contracts.js";
import { researchTools, source } from "./research-tools.js";

const snapshot = z.strictObject({ snapshot_id: z.literal("synthetic-votes-v1") });
const sectorRow = z.strictObject({
  sector: z.string().min(1).max(80),
  eligible_votes: z.number().int().min(1).max(60_000),
  against_votes: z.number().int().min(0).max(60_000),
}).refine(row => row.against_votes <= row.eligible_votes);
const aggregate = snapshot.extend({ sectors: z.array(sectorRow).min(1).max(12) });

const votingSource = {
  label: "ARP synthetic voting snapshot",
  synthetic: true,
  as_of: null,
  snapshot_id: "synthetic-votes-v1",
};

export function votingRegistry(voting) {
  const data = aggregate.parse(voting);
  return {
    listVotingSnapshots: {
      description: "List the available synthetic voting snapshots.",
      input: z.strictObject({}),
      output: z.array(snapshot),
      run: () => [{ snapshot_id: data.snapshot_id }],
    },
    aggregateVotesBySector: {
      description: "Get eligible and against vote totals for each sector in the synthetic snapshot.",
      input: snapshot,
      output: aggregate,
      run: () => structuredClone(data),
    },
  };
}

export function describeRegistry(tools) {
  const descriptors = Object.fromEntries(Object.entries(tools).map(([name, tool]) => [
    name, {
      description: tool.description,
      inputSchema: z.toJSONSchema(tool.input, { target: "draft-7", unrepresentable: "any" }),
      outputSchema: z.toJSONSchema(tool.output, { target: "draft-7", unrepresentable: "any" }),
    },
  ]));
  return { tools: Object.keys(descriptors), typescript: generateTypesFromJsonSchema(descriptors) };
}

export function createRegistry({ executionId, voting } = {}) {
  const tools = voting === undefined ? researchTools : votingRegistry(voting);
  const provenance = voting === undefined ? source : votingSource;
  const scopeKey = voting === undefined ? "benchmark_id" : "snapshot_id";
  const scopeValue = voting === undefined ? "arp-synthetic-sample" : votingSource.snapshot_id;
  const calls = [];
  let requests = 0;
  let fatalError = null;

  function reject(code) {
    fatalError ??= code;
    throw new ToolError(code);
  }

  return {
    tools,
    calls,
    get errorCode() { return fatalError; },
    async call(name, args) {
      requests += 1;
      if (requests > maxCalls) reject("CALL_LIMIT");
      if (!Object.hasOwn(tools, name)) reject("UNKNOWN_TOOL");
      if (args && Object.hasOwn(args, scopeKey) && args[scopeKey] !== scopeValue) {
        reject("TOOL_DENIED");
      }

      const tool = tools[name];
      const parsed = tool.input.safeParse(args);
      if (!parsed.success) reject("INVALID_ARGUMENTS");
      const receipt = {
        tool: name,
        args: parsed.data,
        status: "failed",
        timestamp: new Date().toISOString(),
        execution_id: executionId ?? null,
      };
      calls.push(receipt);
      try {
        const result = checkedResult(tool.output.parse(await tool.run(parsed.data)));
        Object.assign(receipt, { status: "ok", source: provenance, result });
        return result;
      } catch (error) {
        reject(error instanceof ToolError ? error.code : "INVALID_RESULT");
      }
    },
  };
}
