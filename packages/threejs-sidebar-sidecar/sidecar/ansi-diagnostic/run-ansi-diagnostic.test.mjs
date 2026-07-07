import assert from "node:assert/strict";
import { test } from "node:test";
import { makeDiagnosticFrame, parseArgs, validateAnsiFrame } from "./run-ansi-diagnostic.mjs";

test("parseArgs accepts bridge width height fps and frames", () => {
  const opts = parseArgs(["--width", "80", "--height", "24", "--fps", "2", "--frames", "3"]);
  assert.equal(opts.width, 80);
  assert.equal(opts.height, 24);
  assert.equal(opts.fps, 2);
  assert.equal(opts.frames, 3);
});

test("diagnostic frame is exact bridge-valid ANSI at requested dimensions", () => {
  const frame = makeDiagnosticFrame(80, 24, 1);
  assert.equal(validateAnsiFrame(frame, 80, 24), true);
  assert.equal(frame.split("\n").length, 24);
});

test("diagnostic frame exercises the relevant ANSI families", () => {
  const frame = makeDiagnosticFrame(80, 24, 2);
  assert.match(frame, /\x1b\[38;2;\d+;\d+;\d+;48;2;\d+;\d+;\d+m/);
  assert.match(frame, /\x1b\[38;2;\d+;\d+;\d+m\x1b\[48;2;\d+;\d+;\d+m/);
  assert.match(frame, /\x1b\[48;2;\d+;\d+;\d+m +/);
  assert.match(frame, /\x1b\[38;5;\d+;48;5;\d+m/);
  assert.match(frame, /█/);
  assert.match(frame, /▀/);
});

test("diagnostic frame can stress many unique truecolor style combinations", () => {
  const frame = makeDiagnosticFrame(80, 54, 3);
  const styles = new Set([...frame.matchAll(/\x1b\[([0-9;]*)m/g)].map((m) => m[1]));

  assert.equal(validateAnsiFrame(frame, 80, 54), true);
  assert(styles.size > 900, `expected many unique styles, got ${styles.size}`);
});
