import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createInterface } from "node:readline";
import { benchmarkScript } from "./src/benchmark.mjs";
import { maxRequestBytes, ToolError } from "./src/contracts.js";
import { createGateway } from "./src/gateway.mjs";
import { describeRegistry, votingRegistry } from "./src/registry.js";
import { researchTools } from "./src/research-tools.js";

function emit(value) {
  process.stdout.write(JSON.stringify(value) + "\n");
}

async function runDynamic(input) {
  const { startRuntime } = await import("./local-runtime.mjs");
  const runtime = await startRuntime();
  try {
    const response = await runtime.fetch("/execute", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
    emit(await response.json());
  } finally {
    await runtime.close();
  }
}

function parseLine(line) {
  if (!line || Buffer.byteLength(line) > maxRequestBytes) throw new ToolError("INVALID_REQUEST");
  return JSON.parse(line);
}

async function hostWithInput(mode) {
  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  const iterator = lines[Symbol.asyncIterator]();
  try {
    const input = parseLine((await iterator.next()).value);
    if (mode === "dynamic") {
      await runDynamic(input);
      return;
    }
    const gateway = await createGateway(input);
    try {
      emit({ port: gateway.port });
      for (;;) {
        const next = await iterator.next();
        if (next.done) break;
        const request = parseLine(next.value);
        if (request.command === "trace") {
          emit({ calls: gateway.calls, error_code: gateway.errorCode });
        } else if (request.command === "close") {
          break;
        } else {
          emit({ error_code: "INVALID_REQUEST" });
        }
      }
    } finally {
      await gateway.close();
    }
  } finally {
    lines.close();
  }
}

async function main(mode) {
  switch (mode) {
    case "benchmark-fixture": {
      const bytes = await readFile(new URL("./src/sample-holdings.json", import.meta.url));
      emit({
        code: benchmarkScript,
        ...describeRegistry(researchTools),
        snapshot_sha256: createHash("sha256").update(bytes).digest("hex"),
        snapshot_id: "arp-synthetic-sample",
      });
      break;
    }
    case "voting-tools":
      emit(describeRegistry(votingRegistry({
        snapshot_id: "synthetic-votes-v1",
        sectors: [{ sector: "Sample", eligible_votes: 1, against_votes: 0 }],
      })));
      break;
    case "gateway":
    case "dynamic":
      await hostWithInput(mode);
      break;
    default:
      throw new ToolError("INVALID_REQUEST");
  }
}

await main(process.argv[2]).catch(error => {
  emit({ result: null, error_code: error instanceof ToolError ? error.code : "HOST_FAILURE" });
  process.exitCode = 1;
});
