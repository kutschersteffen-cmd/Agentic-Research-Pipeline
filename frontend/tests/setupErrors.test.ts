import { test } from "node:test";
import assert from "node:assert/strict";
import { plainDetail } from "../src/lib/setupErrors.ts";

test("a service that is not set up is said in plain words, without setting names", () => {
  // seen live on Risk Monitoring, theme runs, Value Chain and Feeds: "set ARP_NEO4J_URI" and the like, in red
  const cases: [string, string][] = [
    ["Superset is not configured: set ARP_SUPERSET_PASSWORD.", "Dashboards are not set up on this server. Ask your administrator."],
    ["company graph not configured: set ARP_NEO4J_URI", "The company graph is not set up on this server, so this view is not available. Ask your administrator."],
    ["value chain not built: run arp io build-full and set ARP_VALUE_CHAIN_DIR", "Value chain data is not set up on this server. Ask your administrator."],
    ["No input-output data available: run arp io build-full and set ARP_VALUE_CHAIN_DIR, or set use_sample_io.",
     "Input-output data is not set up on this server. Tick the sample data box to try it with illustrative data."],
    ["news API is not configured (ARP_NEWS_API_CLIENT_ID, ARP_NEWS_API_CLIENT_SECRET)", "The news feed is not connected on this server. Ask your administrator."],
    ["ESG API is not configured (ARP_ESG_API_URL, ARP_ESG_API_TOKEN)", "The ESG data feed is not connected on this server. Ask your administrator."],
    ["Transition barrier refresh is disabled. Set ARP_TRANSITION_BARRIER_REFRESH_ENABLED=true to enable it.",
     "Re-checking sources is switched off on this server. Ask your administrator."],
  ];
  for (const [raw, plain] of cases) assert.equal(plainDetail(raw), plain);
});

test("any other message is left as it is", () => {
  assert.equal(plainDetail("Keep at least one file in step 2."), "Keep at least one file in step 2.");
  assert.equal(plainDetail("ARP_STANDINS_DIR is set together with a model API key"), "ARP_STANDINS_DIR is set together with a model API key");
});
