#!/usr/bin/env node
const ESC = "\x1b";
const RESET = `${ESC}[0m`;
const WIDTH_DEFAULT = 80;
const HEIGHT_DEFAULT = 24;
const encoder = new TextEncoder();

export function parseArgs(argv) {
  const out = { width: WIDTH_DEFAULT, height: HEIGHT_DEFAULT, fps: 1, frames: 0 };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === "--width" && next) out.width = clamp(Number(next), 8, 180, WIDTH_DEFAULT), i++;
    else if (arg === "--height" && next) out.height = clamp(Number(next), 6, 120, HEIGHT_DEFAULT), i++;
    else if (arg === "--fps" && next) out.fps = clamp(Number(next), 1, 20, 1), i++;
    else if (arg === "--frames" && next) out.frames = clamp(Number(next), 0, 1000000, 0), i++;
  }
  return out;
}

function clamp(value, min, max, fallback) {
  return Number.isFinite(value) ? Math.max(min, Math.min(max, Math.round(value))) : fallback;
}

function sgr(...codes) {
  return `${ESC}[${codes.join(";")}m`;
}

function fg(r, g, b) {
  return sgr(38, 2, r, g, b);
}

function bg(r, g, b) {
  return sgr(48, 2, r, g, b);
}

function both(f, b) {
  return sgr(38, 2, f[0], f[1], f[2], 48, 2, b[0], b[1], b[2]);
}

function both256(f, b) {
  return sgr(38, 5, f, 48, 5, b);
}

function stripAnsi(row) {
  return row.replace(/\x1b\[[0-9;]*m/g, "");
}

function visibleWidth(row) {
  let w = 0;
  for (let i = 0; i < row.length; i++) {
    const c = row.charCodeAt(i);
    if (c === 27) {
      if (row[i + 1] !== "[") return -1;
      let j = i + 2;
      while (j < row.length && row[j] !== "m") j++;
      if (j >= row.length) return -1;
      const body = row.slice(i + 2, j);
      if (!/^[0-9;]*$/.test(body)) return -1;
      i = j;
      continue;
    }
    if (c < 32) return -1;
    w++;
  }
  return w;
}

function padAnsi(row, width) {
  const w = visibleWidth(row);
  if (w > width) return stripAnsi(row).slice(0, width);
  if (w < width) return row + " ".repeat(width - w);
  return row;
}

function label(text, width = 20) {
  const plain = String(text).slice(0, width);
  return fg(150, 210, 255) + plain.padEnd(width) + RESET;
}

function styledRun(style, ch, count) {
  return style + ch.repeat(Math.max(0, count)) + RESET;
}

function colorBars(width, ch, styleForColor) {
  const colors = [
    [230, 70, 70],
    [240, 170, 50],
    [80, 220, 120],
    [60, 220, 230],
    [70, 110, 255],
    [190, 95, 255],
  ];
  const per = Math.floor(width / colors.length);
  let out = "";
  for (let i = 0; i < colors.length; i++) {
    const n = i === colors.length - 1 ? width - per * i : per;
    out += styledRun(styleForColor(colors[i], i), ch, n);
  }
  return out;
}

function row(title, body, width) {
  return padAnsi(label(title) + body, width);
}

function entropyCellStyle(x, y, seq, withBackground = true) {
  const r = (x * 37 + y * 19 + seq * 13) & 255;
  const g = (x * 17 + y * 43 + seq * 29) & 255;
  const b = (x * 53 + y * 11 + seq * 7) & 255;
  if (!withBackground) return fg(r, g, b);
  const br = (x * 29 + y * 47 + seq * 5) & 255;
  const bgc = (x * 61 + y * 23 + seq * 17) & 255;
  const bb = (x * 13 + y * 31 + seq * 41) & 255;
  return both([r, g, b], [br, bgc, bb]);
}

function entropyRow(title, width, y, seq, ch = "█", withBackground = true) {
  const bodyWidth = Math.max(1, width - 20);
  let body = "";
  for (let x = 0; x < bodyWidth; x++) {
    body += entropyCellStyle(x, y, seq, withBackground) + ch + RESET;
  }
  return row(title, body, width);
}

export function makeDiagnosticFrame(width, height, seq = 1) {
  const bodyWidth = Math.max(1, width - 20);
  const staleA = seq % 2 === 0;
  const rows = [
    row("00 plain control", fg(220, 220, 220) + "plain ASCII baseline; every row should be straight, no bleed" + RESET, width),
    row("01 cmb TC spaces", colorBars(bodyWidth, " ", (c) => both([255, 255, 255], c)), width),
    row("02 split TC spaces", colorBars(bodyWidth, " ", (c) => fg(255, 255, 255) + bg(c[0], c[1], c[2])), width),
    row("03 bg-only spaces", colorBars(bodyWidth, " ", (c) => bg(c[0], c[1], c[2])), width),
    row("04 percell bg sp", Array.from({ length: bodyWidth }, (_, i) => {
      const c = i % 2 ? [15, 18, 28] : [210, 210, 210];
      return bg(c[0], c[1], c[2]) + " " + RESET;
    }).join(""), width),
    row("05 fg full block", colorBars(bodyWidth, "█", (c) => fg(c[0], c[1], c[2])), width),
    row("06 split fullblk", colorBars(bodyWidth, "█", (c) => fg(c[0], c[1], c[2]) + bg(4, 7, 20)), width),
    row("07 half fg/bg", colorBars(bodyWidth, "▀", (c, i) => both(c, [Math.max(0, 40 - i * 3), 7 + i * 12, 30 + i * 18])), width),
    row("08 256 bg spaces", ["196", "208", "46", "51", "33", "129"].map((b, i) => styledRun(both256(15, Number(b)), " ", Math.ceil(bodyWidth / 6))).join("").slice(0, bodyWidth * 30), width),
    row("09 256 blocks", ["196", "208", "46", "51", "33", "129"].map((f) => styledRun(sgr(38, 5, Number(f)), "█", Math.ceil(bodyWidth / 6))).join("").slice(0, bodyWidth * 30), width),
    row("10 reset bg clear", styledRun(bg(staleA ? 32 : 4, staleA ? 36 : 7, staleA ? 48 : 20), " ", bodyWidth), width),
    row("11 stale marker", fg(staleA ? 255 : 50, staleA ? 255 : 255, staleA ? 255 : 180) + (staleA ? "WHITE-FG-BLOCKS ".repeat(5) : "green foreground ".repeat(5)) + RESET, width),
    row("12 no-space glyphs", colorBars(bodyWidth, "▓", (c) => fg(c[0], c[1], c[2])), width),
    row("13 separated SGR", colorBars(bodyWidth, " ", (c) => fg(0, 0, 0) + RESET + bg(c[0], c[1], c[2])), width),
    row("14 black bg spaces", styledRun(bg(0, 0, 0), " ", bodyWidth), width),
    row("15 dark bg spaces", styledRun(bg(4, 7, 20), " ", bodyWidth), width),
    entropyRow("16 entropy fg/bg", width, 16, seq, "█", true),
    entropyRow("17 entropy spaces", width, 17, seq, " ", true),
    entropyRow("18 entropy fgonly", width, 18, seq, "▓", false),
    entropyRow("19 entropy half", width, 19, seq, "▀", true),
  ];
  while (rows.length < height) {
    const n = rows.length;
    if (n < 48) {
      const glyphs = ["█", " ", "▓", "▀"];
      rows.push(entropyRow(String(n).padStart(2, "0") + " entropy " + (seq % 2 ? "A" : "B"), width, n, seq, glyphs[n % glyphs.length], n % 4 !== 2));
    } else {
      rows.push(row(String(n).padStart(2, "0") + " repeat " + (seq % 2 ? "A" : "B"), n % 2 ? styledRun(bg(20, 24, 36), " ", bodyWidth) : styledRun(fg(60, 220, 230), "·", bodyWidth), width));
    }
  }
  return rows.slice(0, height).join("\n");
}

export function validateAnsiFrame(frame, width, height) {
  if (typeof frame !== "string") return false;
  const rows = frame.split("\n");
  if (rows.length !== height) return false;
  return rows.every((r) => visibleWidth(r) === width);
}

function bytesToBase64(bytes) {
  return Buffer.from(bytes).toString("base64");
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

export async function run(argv = process.argv.slice(2)) {
  const opts = parseArgs(argv);
  emit({
    type: "hello",
    protocol: 1,
    renderer: "ansi-diagnostic",
    requestedRenderer: "ansi-diagnostic",
    fallbackReason: null,
    scene: "ansi-diagnostic",
    width: opts.width,
    height: opts.height,
    fps: opts.fps,
    ansi: "diagnostic",
  });
  const frameDelayMs = Math.round(1000 / opts.fps);
  let seq = 0;
  let stopping = false;
  const stop = () => { stopping = true; };
  process.on("SIGTERM", stop);
  process.on("SIGINT", stop);
  while (!stopping) {
    const raw = makeDiagnosticFrame(opts.width, opts.height, ++seq);
    emit({
      type: "frame",
      seq,
      width: opts.width,
      height: opts.height,
      renderer: "ansi-diagnostic",
      encoding: "base64-ansi",
      data: bytesToBase64(encoder.encode(raw)),
    });
    if (opts.frames && seq >= opts.frames) break;
    await sleep(frameDelayMs);
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  run().catch((error) => {
    emit({ type: "error", message: String(error?.stack || error).slice(0, 300) });
    process.exitCode = 1;
  });
}
