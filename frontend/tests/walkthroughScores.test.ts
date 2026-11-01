import { test } from "node:test";
import assert from "node:assert/strict";
import { retrievalLine, scoreText, scoresMissing } from "../src/lib/walkthrough.ts";
import type { Walkthrough } from "../src/types.ts";

// why-this-evidence spec: the "Find evidence" step's method line, score text and old-trace note.
const base = { recorded: true, passages: [{ rank: 1, doc_id: "d", doc_title: "10-K", section: null, char_start: 0, char_end: 9, text: "x" }] } as unknown as Walkthrough;

test("method line names the method, re-ranking and candidates", () => {
  assert.equal(retrievalLine({ method: "hybrid", reranked: true, candidates: 214 }), "BM25 + vectors (RRF), re-ranked · 214 candidates");
  assert.equal(retrievalLine({ method: "bm25", reranked: false, candidates: 1200 }), "BM25 · 1,200 candidates");
  assert.equal(retrievalLine({ method: "unranked", reranked: false, candidates: 3 }), "No keyword hit: first passages in document order · 3 candidates");
  assert.equal(retrievalLine({ method: "hybrid", reranked: false, candidates: 1 }), "BM25 + vectors (RRF) · 1 candidate");
});

test("score text shows only the computed scores, in order", () => {
  assert.equal(scoreText({ bm25: 7.4211, vector_rank: 3, rrf: 0.03278, rerank: 0.914 }), "BM25 7.42 · vector #3 · RRF 0.033 · rerank 0.91");
  assert.equal(scoreText({ vector_rank: 2, rrf: 0.016 }), "vector #2 · RRF 0.016");
  assert.equal(scoreText({}), "");
  assert.equal(scoreText(undefined), "");
});

test("old traces say scores were not recorded", () => {  // AC-28
  assert.equal(scoresMissing(base), true);
  assert.equal(scoresMissing({ ...base, retrieval: null }), true);
  assert.equal(scoresMissing({ ...base, retrieval: { method: "bm25", reranked: false, candidates: 1 } }), false);
  assert.equal(scoresMissing({ ...base, passages: [] }), false);
});

test("an old passage line gets no score suffix", () => {  // AC-29
  assert.equal(scoreText(base.passages[0].scores), "");
});
