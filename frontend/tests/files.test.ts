import test from "node:test";
import assert from "node:assert/strict";
import { filenameFromDisposition, inlineSafe } from "../src/lib/files.ts";

test("filenameFromDisposition reads quoted, bare and RFC 5987 names", () => {
  assert.equal(filenameFromDisposition('attachment; filename="run_1.csv"', "x"), "run_1.csv");
  assert.equal(filenameFromDisposition("inline; filename=report.pdf", "x"), "report.pdf");
  assert.equal(filenameFromDisposition("attachment; filename=\"a.pptx\"; filename*=UTF-8''Gr%C3%BCn.pptx", "x"), "Grün.pptx");
});

test("filenameFromDisposition falls back when absent or empty", () => {
  assert.equal(filenameFromDisposition(null, "fallback.csv"), "fallback.csv");
  assert.equal(filenameFromDisposition('attachment; filename=""', "fallback.csv"), "fallback.csv");
  assert.equal(filenameFromDisposition("attachment; filename*=UTF-8''%E0%A4%A", "f.csv"), "f.csv");
});

test("inlineSafe refuses types that could run script in the app origin", () => {
  for (const t of ["application/pdf", "image/png", "text/csv; charset=utf-8", "application/json"]) assert.ok(inlineSafe(t), t);
  for (const t of ["text/html", "image/svg+xml", "application/xhtml+xml", "", "application/octet-stream"]) assert.ok(!inlineSafe(t), t);
});
