const ASK = "Ask your administrator.";

// A server message that names the setting behind a feature that is not set up, and what a user is told instead.
const NOT_SET_UP: [RegExp, string][] = [
  [/use_sample_io/, "Input-output data is not set up on this server. Tick the sample data box to try it with illustrative data."],
  [/ARP_SUPERSET/, `Dashboards are not set up on this server. ${ASK}`],
  [/ARP_NEO4J_URI/, `The company graph is not set up on this server, so this view is not available. ${ASK}`],
  [/ARP_VALUE_CHAIN_DIR/, `Value chain data is not set up on this server. ${ASK}`],
  [/ARP_NEWS_API/, `The news feed is not connected on this server. ${ASK}`],
  [/ARP_ESG_API/, `The ESG data feed is not connected on this server. ${ASK}`],
  [/ARP_TRANSITION_BARRIER_REFRESH_ENABLED/, `Re-checking sources is switched off on this server. ${ASK}`],
];

/** An API error's detail as a user reads it: setup messages lose their setting names; everything else is unchanged. */
export function plainDetail(detail: string): string {
  return NOT_SET_UP.find(([names]) => names.test(detail))?.[1] ?? detail;
}
