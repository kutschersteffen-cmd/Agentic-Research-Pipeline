import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

async function probe() {
  const { url, marker, sentinel_hashes: sentinelHashes = [] } = JSON.parse(await readFile(process.argv[2], "utf8"));
  const endpoint = new URL(url);
  if (!["https:", "http:"].includes(endpoint.protocol) || endpoint.username || endpoint.password
      || typeof marker !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(marker)
      || !Array.isArray(sentinelHashes) || !sentinelHashes.every(value => /^[a-f0-9]{64}$/.test(value))) {
    throw new Error("INVALID_PROBE");
  }
  const credentialsPresent = Object.values(process.env).some(value =>
    sentinelHashes.includes(createHash("sha256").update(value).digest("hex")));
  process.stdout.write("PROBE_STARTED\n");
  try {
    const result = await fetch(endpoint, {
      method: "GET",
      redirect: "error",
      headers: { "X-ARP-Probe": marker },
      signal: AbortSignal.timeout(3_000),
    });
    process.stdout.write(JSON.stringify({ reached: true, status: result.status, credentials_present: credentialsPresent }) + "\n");
    await result.body?.cancel();
  } catch {
    process.stdout.write(JSON.stringify({ reached: false, credentials_present: credentialsPresent }) + "\n");
  }
}

await probe().catch(() => {
  process.stderr.write("INVALID_PROBE\n");
  process.exitCode = 1;
});
