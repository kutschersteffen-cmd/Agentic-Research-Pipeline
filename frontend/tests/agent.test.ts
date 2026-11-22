import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import {
  answerActions, budgetLine, canTurnIntoPlan, chipLabel, composerModes, composerRequest, ctrlJTarget, draftPlanFromAsk, INBOX_KIND, lineDiff,
  askingIn, COMPOSER_COPY, draftPlanFromExploration, explorationBadge, focusAfterDraft, nearEnd, needsYouLine, resultTable, scriptLines, streamResized, wasNearEnd, sendsComposer, stepState,
  threadRows, threadTitle, untilCancelled, usd,
} from "../src/lib/agent.ts";
import type { Plan } from "../src/lib/plans.ts";
import type { AskThread, Exploration } from "../src/types.ts";
import { HUBS, redirectHash } from "../src/lib/nav.ts";

// Agent screen shell (docs/superpowers/specs/2026-11-21-agent-panel-code-mode.md, slice 6).

test("a thread's chip names the status as the spec spells it (AC-27, AC-29)", () => {
  const statuses = ["draft", "approved", "running", "awaiting_review", "done", "failed", "cancelled"];
  assert.deepEqual(statuses.map(chipLabel), ["draft", "approved", "running", "awaiting review", "done", "failed", "cancelled"]);
});

test("a thread's title is the brief's first 60 characters", () => {
  assert.equal(threadTitle("x".repeat(80)), "x".repeat(60));
  assert.equal(threadTitle("short brief"), "short brief");
});

test("the Script tab numbers every line from 1 to the last (AC-29b)", () => {
  const script = 'u = universe_build(taxonomy_id="t", source="s.csv")\n\ne = extraction(universe_run_id=u.run_id, schema_id="x")\n';
  assert.deepEqual(scriptLines(script), [
    { n: 1, text: 'u = universe_build(taxonomy_id="t", source="s.csv")' },
    { n: 2, text: "" },
    { n: 3, text: 'e = extraction(universe_run_id=u.run_id, schema_id="x")' },
  ]);
  assert.deepEqual(scriptLines("one line"), [{ n: 1, text: "one line" }]);
});

test("Enter sends the composer; Shift+Enter and IME composition do not (AC-35)", () => {
  assert.equal(sendsComposer({ key: "Enter", shiftKey: false }), true);
  assert.equal(sendsComposer({ key: "Enter", shiftKey: true }), false);
  assert.equal(sendsComposer({ key: "Enter", shiftKey: false, isComposing: true }), false);
  assert.equal(sendsComposer({ key: "a", shiftKey: false }), false);
});

test("an old plan link opens the same plan on the Agent screen (AC-37)", () => {
  assert.equal(redirectHash("#/plans/p_1"), "#/agent/p_1");
  assert.equal(redirectHash("#/plans"), "#/agent");
  assert.equal(redirectHash("#/plansx"), null);
  assert.equal(redirectHash("#/agent/p_1"), null);
});

test("the Runs group shows Agent and no Research plans (AC-38)", () => {
  const labels = HUBS.find((h) => h.label === "Runs")!.tabs.map(([, label]) => label);
  assert.ok(labels.includes("Agent"));
  assert.ok(!labels.some((l) => /research plans/i.test(l)));
});

// Stage tabs: Diff and Audit (slice 8).

test("the Diff header counts the - and + lines of diff -u between two script versions (AC-32)", () => {
  const v1 = 'u = universe_build(taxonomy_id="t", source="s.csv")\ne = extraction(universe_run_id=u.run_id, schema_id="x")\nr = report_render(source_ids=[e.run_id])\n';
  const v2 = 'u = universe_build(taxonomy_id="t", source="s.csv")\ne = extraction(universe_run_id=u.run_id, schema_id="y")\nf = financials_extraction(universe_run_id=u.run_id)\nr = report_render(source_ids=[e.run_id])\n';
  const d = lineDiff(v1, v2);
  // diff -u: 1 line removed (schema_id="x"), 2 added (schema_id="y" and the financials step).
  assert.deepEqual([d.removed, d.added], [1, 2]);
  assert.deepEqual(d.lines.map((l) => l.op).join(""), " -++ ");
  assert.equal(d.lines[1].text, 'e = extraction(universe_run_id=u.run_id, schema_id="x")');
});

test("the line diff of equal scripts, and of a missing final newline, matches diff -u", () => {
  assert.deepEqual(lineDiff("a\nb\n", "a\nb\n"), { removed: 0, added: 0, lines: [{ op: " ", text: "a" }, { op: " ", text: "b" }] });
  // diff -u marks a last line that lost its newline as changed.
  assert.deepEqual([lineDiff("a\nb\n", "a\nb").removed, lineDiff("a\nb\n", "a\nb").added], [1, 1]);
  assert.deepEqual([lineDiff("", "a\n").removed, lineDiff("", "a\n").added], [0, 1]);
});

test("a step reads started once called, skipped when the plan ended without it, else planned", () => {
  assert.equal(stepState("running", true), "started");
  assert.equal(stepState("running", false), "planned");
  assert.equal(stepState("failed", false), "planned"); // a resume can still run it
  assert.equal(stepState("done", false), "skipped");
  assert.equal(stepState("cancelled", false), "skipped");
});

test("the Audit tab shows a cost as the API serves it (AC-33)", () => {
  assert.equal(usd(1.2), "$1.20");
  assert.equal(usd(0), "$0.00");
  assert.equal(usd(0.123456), "$0.123456");
  assert.equal(usd(0.0123456789), "$0.0123456789"); // never rounded: equal to GET /api/plans/{id}
  assert.equal(usd(1234.5), "$1234.50");
  assert.equal(usd(null), "–");
  assert.equal(budgetLine(2.05, 5), "spent $2.05 of $5.00");
  assert.equal(budgetLine(2.05, null), "spent $2.05, no budget set");
});

// Slice 7: the inbox column.

test("the inbox footer counts what waits in Needs you (AC-31, amended in slice 13)", () => {
  assert.equal(needsYouLine(7), "7 more in Needs you");
  assert.equal(needsYouLine(0), "0 more in Needs you");
});

test("every inbox kind the route serves has a label", () => {
  assert.deepEqual(Object.keys(INBOX_KIND).sort(), ["exploration", "plan_approval", "step_review"]);
});

// Slice 13: ask threads (Phase 7).

test("the composer's modes: Ask first and pressed, Plan only for a viewer, Explore appended once slice 10 is merged (AC-78)", () => {
  assert.deepEqual(composerModes(true), { modes: ["Ask", "Plan", "Explore"], initial: "Ask" });
  assert.deepEqual(composerModes(false), { modes: ["Plan", "Explore"], initial: "Plan" });
});

test("Ctrl/⌘J opens the Agent screen, or nothing for a viewer (AC-79)", () => {
  assert.equal(ctrlJTarget(false), null);
  assert.equal(ctrlJTarget(true), "#/agent");
});

test("Plan mode never sends source_ask_id, even with an ask thread selected (AC-79b)", () => {
  assert.deepEqual(composerRequest("Plan", "b", { kind: "ask", id: "T" }), { path: "/api/plans", body: { brief: "b" } });
});

test("Ask mode follows up in the selected ask thread, else starts one", () => {
  assert.deepEqual(composerRequest("Ask", "q", { kind: "ask", id: "T" }), { path: "/api/agent/asks", body: { question: "q", thread_id: "T" } });
  assert.deepEqual(composerRequest("Ask", "q", { kind: "plan", id: "P" }), { path: "/api/agent/asks", body: { question: "q" } });
  assert.deepEqual(composerRequest("Ask", "q", null), { path: "/api/agent/asks", body: { question: "q" } });
});

test("a viewer gets no buttons under an answer (AC-79c)", () => {
  assert.deepEqual(answerActions(false), []);
  assert.deepEqual(answerActions(true), ["Draft a plan"]);
});

test("Draft a plan shows the API's detail when the request fails (AC-77b)", async () => {
  const ask = { id: "a1", standalone_question: "Sector weights of MSCI World?" };
  assert.deepEqual(await draftPlanFromAsk(ask, () => Promise.reject(new Error("422: line 1: bad"))), { ok: false, error: "line 1: bad" });
});

test("Draft a plan sends the standalone question and the ask's id", async () => {
  const sent: unknown[] = [];
  const plan = { id: "plan_1" } as Plan;
  const out = await draftPlanFromAsk({ id: "a1", standalone_question: "S?" }, (path, body) => (sent.push([path, body]), Promise.resolve(plan)));
  assert.deepEqual(out, { ok: true, plan });
  assert.deepEqual(sent, [["/api/plans", { brief: "S?", source_ask_id: "a1" }]]);
});

test("plans and ask threads share one list, newest first", () => {
  const plans = [{ id: "p", brief: "b".repeat(70), status: "draft", created_at: "2026-11-22T10:00:00Z" }] as Plan[];
  const asks = [{ thread_id: "t", title: "q", status: "answered", created_at: "2026-11-22T11:00:00+00:00", asks: 1 }] as AskThread[];
  assert.deepEqual(threadRows(plans, asks).map((r) => [r.kind, r.id, r.title.length]), [["ask", "t", 1], ["plan", "p", 60]]);
});

test("the Ask panel and its session storage are gone (AC-76b)", () => {
  const src = new URL("../src/", import.meta.url);
  assert.ok(!existsSync(new URL("components/AskPanel.tsx", src)));
  assert.ok(!existsSync(new URL("lib/askHistory.ts", src)));
  const files = (dir: string): string[] =>
    readdirSync(dir).flatMap((f) => (statSync(`${dir}/${f}`).isDirectory() ? files(`${dir}/${f}`) : [`${dir}/${f}`]));
  assert.deepEqual(files(src.pathname).filter((f) => readFileSync(f, "utf8").includes("arp.ask.turns")), []);
});

test("the question in flight shows only in the thread it was sent from", () => {
  const followUp = { question: "and the top 3?", threadId: "A" };
  assert.equal(askingIn(followUp, "A"), "and the top 3?");
  assert.equal(askingIn(followUp, "B"), null);
  assert.equal(askingIn(followUp, null), null);
  const fresh = { question: "new?", threadId: null };
  assert.equal(askingIn(fresh, null), "new?");
  assert.equal(askingIn(fresh, "A"), null);
  assert.equal(askingIn(null, "A"), null);
});

test("a thread's asks that answer after another thread was picked are dropped", async () => {
  const shown: string[] = [];
  const errors: string[] = [];
  let resolveA!: (v: string) => void;
  let rejectC!: (e: Error) => void;
  const cancelA = untilCancelled(new Promise<string>((r) => { resolveA = r; }), (v) => shown.push(v), (e) => errors.push(e.message));
  cancelA(); // B picked: the effect cleanup cancels A
  untilCancelled(Promise.resolve("B"), (v) => shown.push(v), (e) => errors.push(e.message));
  await Promise.resolve();
  resolveA("A");
  const cancelC = untilCancelled(new Promise<string>((_, j) => { rejectC = j; }), (v) => shown.push(v), (e) => errors.push(e.message));
  cancelC();
  rejectC(new Error("late"));
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual([shown, errors], [["B"], []]);
});

// Explorations (slice 10).

const exp = (id: string, created_at: string, label: "exploratory" | "accepted" = "exploratory") =>
  ({ id, question: `question ${id} ${"x".repeat(70)}`, created_at, label }) as unknown as Exploration;

test("explorations join the thread list, newest first, with their label as chip", () => {
  const plans = [{ id: "p1", brief: "plan one", status: "draft", created_at: "2026-11-22T10:00:00Z" }] as Plan[];
  const rows = threadRows(plans, [], [exp("e1", "2026-11-22T11:00:00Z"), exp("e0", "2026-11-22T09:00:00Z", "accepted")]);
  assert.deepEqual(rows.map((r) => [r.kind, r.id, r.status]), [["exploration", "e1", "exploratory"], ["plan", "p1", "draft"], ["exploration", "e0", "accepted"]]);
  assert.equal(rows[0].title.length, 60);
});

test("Explore mode sends the question to the sandbox lane, never with source_ask_id", () => {
  assert.deepEqual(composerRequest("Explore", "q", { kind: "ask", id: "T" }), { path: "/api/agent/explorations", body: { question: "q" } });
  const { label, submit, sending, help } = COMPOSER_COPY.Explore;
  assert.deepEqual({ label, submit, sending, help }, { label: "Question", submit: "Explore", sending: "Exploring…", help: "Enter runs an exploration; Shift+Enter adds a line." });
});

test("an exploration shows the badge Exploratory: not reviewed until accepted (AC-49)", () => {
  assert.equal(explorationBadge({ label: "exploratory" }), "Exploratory: not reviewed");
  assert.equal(explorationBadge({ label: "accepted" }), null);
});

test("a result is a table only when it is a list of flat objects", () => {
  assert.deepEqual(resultTable([{ sector: "Energy", w: 4.5 }, { sector: "IT", ok: true, w: null }]), {
    columns: ["sector", "w", "ok"],
    rows: [["Energy", 4.5, null], ["IT", null, true]],
  });
  for (const json of [1, "x", null, [], [1, 2], [{ a: { b: 1 } }], [{ a: [1] }], { a: 1 }]) assert.equal(resultTable(json), null);
});

// Chat-style stream: the composer stays at the bottom and the stream follows new turns only for a reader at its end.
test("the stream counts as at its end within 80 px of the bottom", () => {
  assert.equal(nearEnd({ scrollTop: 920, scrollHeight: 1500, clientHeight: 500 }), true); // 80 px left
  assert.equal(nearEnd({ scrollTop: 919, scrollHeight: 1500, clientHeight: 500 }), false); // 81 px left
  assert.equal(nearEnd({ scrollTop: 1000, scrollHeight: 1500, clientHeight: 500 }), true);
  assert.equal(nearEnd({ scrollTop: 0, scrollHeight: 300, clientHeight: 500 }), true); // nothing to scroll
  assert.equal(nearEnd({ scrollTop: 0, scrollHeight: 2000, clientHeight: 500 }), false);
});

test("new content scrolls a reader at the end down, and offers Jump to latest to one who scrolled up", () => {
  const at = { contentGrew: true, boxShrank: false, nowNearEnd: false };
  assert.deepEqual(streamResized({ ...at, wasNearEnd: true }), { scrollToEnd: true, jump: false });
  assert.deepEqual(streamResized({ ...at, wasNearEnd: false }), { scrollToEnd: false, jump: true });
});

test("a taller composer keeps a reader at the end pinned but never raises Jump to latest", () => {
  const squeezed = { contentGrew: false, boxShrank: true, nowNearEnd: false };
  assert.deepEqual(streamResized({ ...squeezed, wasNearEnd: true }), { scrollToEnd: true, jump: false });
  assert.deepEqual(streamResized({ ...squeezed, wasNearEnd: false }), { scrollToEnd: false, jump: null });
});

test("Jump to latest goes once the end is in view without a scroll, as when the box grows to fit everything", () => {
  assert.deepEqual(streamResized({ wasNearEnd: false, contentGrew: false, boxShrank: false, nowNearEnd: true }), { scrollToEnd: false, jump: false });
});

test("the accepted chip writes its word in ink and keeps the green on the square only (contrast on a selected row)", () => {
  const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");
  assert.match(css, /\.status-accepted \{ color: var\(--ink\); \}/);
  assert.match(css, /\.status-accepted::before \{ background: var\(--high\); \}/);
});

test("a fast answer is still followed when the follow-down's scroll event lands after it", () => {
  // Followed down to the end of `Working…` (1000 + 87 px of content, a 500 px box): scrollTop 587. The answer (+800 px)
  // then grows the stream before that scroll's event fires, which reads as scrolled up and clears `atEnd`.
  const before = { scrollHeight: 1087, clientHeight: 500 };
  assert.equal(wasNearEnd(false, 587, before), true);
  assert.deepEqual(streamResized({ wasNearEnd: wasNearEnd(false, 587, before), contentGrew: true, boxShrank: false, nowNearEnd: false }),
    { scrollToEnd: true, jump: false });
  // A reader who really scrolled up stays put and gets the button.
  assert.equal(wasNearEnd(false, 0, before), false);
  assert.equal(wasNearEnd(true, 0, before), true); // your own send sets `atEnd`
});

// Write action: exploration to draft plan (agent-panel-code-mode slice 12).

test("only a done, accepted exploration offers Turn into a plan (AC-66, AC-66b)", () => {
  const at = "2026-11-22T10:00:00Z";
  assert.equal(canTurnIntoPlan({ status: "done", accepted_at: at }), true);
  assert.equal(canTurnIntoPlan({ status: "done", accepted_at: null }), false);
  assert.equal(canTurnIntoPlan({ status: "failed", accepted_at: at }), false);
  assert.equal(canTurnIntoPlan({ status: "timeout", accepted_at: at }), false);
});

test("Draft plan posts the brief to the exploration's plan route and returns the plan", async () => {
  const sent: [string, unknown][] = [];
  const plan = { id: "plan_1" } as Plan;
  const out = await draftPlanFromExploration({ id: "e/1" }, "fetch missing reports", async (path, body) => { sent.push([path, body]); return plan; });
  assert.deepEqual(sent, [["/api/agent/explorations/e%2F1/plan", { brief: "fetch missing reports" }]]);
  assert.deepEqual(out, { ok: true, plan });
});

test("a refused Draft plan keeps the field open with the detail and drafts no thread (AC-65c)", async () => {
  const drafted: Plan[] = [];
  const out = await draftPlanFromExploration({ id: "e1" }, "q", async () => { throw new Error("422: line 1: bad"); });
  if (out.ok) drafted.push(out.plan);
  assert.deepEqual(out, { ok: false, error: "line 1: bad" });
  assert.deepEqual(drafted, []);
});

test("after Draft plan, focus goes to the error when refused and leaves the card when drafted", () => {
  assert.equal(focusAfterDraft({ ok: false }), "error");
  assert.equal(focusAfterDraft({ ok: true }), null);
});
