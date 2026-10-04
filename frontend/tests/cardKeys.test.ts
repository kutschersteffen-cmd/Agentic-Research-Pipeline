import test from "node:test";
import assert from "node:assert/strict";
import { cardKeyHandlers, dispatchCardKey } from "../src/lib/cardKeys.ts";

// DOM-less: a target is anything with closest(); a card is an opaque object.
const plain = { closest: () => null } as unknown as EventTarget;
const inInput = { closest: (s: string) => (s.includes("input") ? {} : null) } as unknown as EventTarget;
const card = { id: "card-1" } as unknown as HTMLElement;
const key = (k: string, target = plain, mods: Partial<KeyboardEvent> = {}) =>
  ({ key: k, target, ctrlKey: false, metaKey: false, altKey: false, ...mods }) as KeyboardEvent;

test("a handler for a is called with the focused card", () => {
  const seen: HTMLElement[] = [];
  const handlers = cardKeyHandlers(".review-item", { a: (c) => void seen.push(c) });
  assert.equal(dispatchCardKey(key("a"), handlers, card), true);
  assert.deepEqual(seen, [card]);
});

test("a/c/r do nothing without a focused card", () => {
  let calls = 0;
  const handlers = cardKeyHandlers(".review-item", { c: () => void calls++ });
  assert.equal(dispatchCardKey(key("c"), handlers, null), false);
  assert.equal(calls, 0);
});

test("keys typed inside an input, or with a modifier, are ignored", () => {
  let calls = 0;
  const handlers = cardKeyHandlers(".review-item", { a: () => void calls++, r: () => void calls++ });
  assert.equal(dispatchCardKey(key("a", inInput), handlers, card), false);
  assert.equal(dispatchCardKey(key("r", plain, { ctrlKey: true }), handlers, card), false);
  assert.equal(dispatchCardKey(key("r", plain, { metaKey: true }), handlers, card), false);
  assert.equal(calls, 0);
});

test("a one-argument call registers only j/k", () => {
  assert.deepEqual(Object.keys(cardKeyHandlers(".proposal-card")).sort(), ["j", "k"]);
  assert.equal(dispatchCardKey(key("a"), cardKeyHandlers(".proposal-card"), card), false);
});
