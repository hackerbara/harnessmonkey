const ESC = String.fromCharCode(27);
const HALF = String.fromCharCode(9600);
const BRAILLE_BASE = 0x2800;
const BRAILLE_DOTS = [1, 8, 2, 16, 4, 32, 64, 128];
const BACKGROUND_RGB: [number, number, number] = [4, 7, 20];
const BAYER_4X4 = [
  0,
  8,
  2,
  10,
  12,
  4,
  14,
  6,
  3,
  11,
  1,
  9,
  15,
  7,
  13,
  5,
];
const DENSITY_CHARS = [
  " ",
  String.fromCharCode(0x2591),
  String.fromCharCode(0x2592),
  String.fromCharCode(0x2593),
  String.fromCharCode(0x2588),
];
const QUADRANT_GLYPHS = [
  " ",
  String.fromCharCode(0x2598), // top-left
  String.fromCharCode(0x259d), // top-right
  String.fromCharCode(0x2580), // top half
  String.fromCharCode(0x2596), // bottom-left
  String.fromCharCode(0x258c), // left half
  String.fromCharCode(0x259e), // top-right + bottom-left
  String.fromCharCode(0x259b), // top + bottom-left
  String.fromCharCode(0x2597), // bottom-right
  String.fromCharCode(0x259a), // top-left + bottom-right
  String.fromCharCode(0x2590), // right half
  String.fromCharCode(0x259c), // top + bottom-right
  String.fromCharCode(0x2584), // bottom half
  String.fromCharCode(0x2599), // left + bottom-right
  String.fromCharCode(0x259f), // right + bottom-left
  String.fromCharCode(0x2588), // full
];
const encoder = new TextEncoder();
const decoder = new TextDecoder();

export type AnsiMode =
  | "braille"
  | "half"
  | "halftone"
  | "cellfit"
  | "chafa"
  | "chafa-vhalf"
  | "chafa-quad"
  | "chafa-block";
export type LayoutMode = "single" | "two-side";
export type Options = {
  width: number;
  height: number;
  fps: number;
  frames: number;
  scene: string;
  ansi: AnsiMode;
  layout: LayoutMode;
  leftWidth: number;
  rightWidth: number;
  pixelWidth: number;
  pixelHeight: number;
};

let seq = 0;
let helloSent = false;
let stopping = false;
let win: any = null;
const startedAt = Date.now();
const opts = parseArgs(filteredArgs(Deno.args));
const sidecarRoot = readEnv("THREE_SIDECAR_BROWSER_WEBGL_ROOT") || Deno.cwd();
const assetRoot = readEnv("THREE_SIDECAR_BROWSER_WEBGL_ASSET_ROOT") ||
  joinPath(sidecarRoot, "..");

function filteredArgs(argv: string[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--runtime") {
      i++;
      continue;
    }
    out.push(argv[i]);
  }
  return out;
}

export function parseArgs(argv: string[]): Options {
  const envAnsi = readEnv("CLAUDEMONKEY_THREE_SIDECAR_ANSI") ||
    readEnv("THREE_SIDECAR_ANSI");
  const envLayout = readEnv("CLAUDEMONKEY_THREE_SIDECAR_LAYOUT") ||
    readEnv("THREE_SIDECAR_LAYOUT");
  const out: Record<string, string | number> = {
    width: 80,
    height: 32,
    fps: 8,
    frames: 0,
    scene: "browser-orbit-lab",
    ansi: envAnsi || "braille",
    layout: envLayout || "single",
    leftWidth: readEnv("CLAUDEMONKEY_THREE_SIDECAR_SIDE_WIDTH") ||
      readEnv("THREE_SIDECAR_SIDE_WIDTH") || 0,
    rightWidth: readEnv("CLAUDEMONKEY_THREE_SIDECAR_RIGHT_WIDTH") ||
      readEnv("THREE_SIDECAR_RIGHT_WIDTH") || 0,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === "--width" && next) out.width = Number(next), i++;
    else if (arg === "--height" && next) out.height = Number(next), i++;
    else if (arg === "--fps" && next) out.fps = Number(next), i++;
    else if (arg === "--frames" && next) out.frames = Number(next), i++;
    else if (arg === "--scene" && next) out.scene = String(next), i++;
    else if (arg === "--ansi" && next) out.ansi = String(next), i++;
    else if (arg.startsWith("--ansi=")) out.ansi = arg.slice("--ansi=".length);
    else if (arg === "--layout" && next) out.layout = String(next), i++;
    else if (arg === "--left-width" && next) {
      out.leftWidth = Number(next), i++;
    } else if (arg === "--right-width" && next) {
      out.rightWidth = Number(next), i++;
    }
  }
  const ansi = parseAnsiMode(String(out.ansi));
  const width = clampInt(Number(out.width), 8, 300, 80);
  const height = clampInt(Number(out.height), 6, 120, 32);
  const layout = parseLayoutMode(String(out.layout));
  const fallbackSideWidth = layout === "two-side" ? Math.min(30, width) : 0;
  const leftWidth = layout === "two-side"
    ? clampInt(Number(out.leftWidth), 0, width, fallbackSideWidth)
    : 0;
  const rightWidth = layout === "two-side"
    ? clampInt(Number(out.rightWidth), 0, Math.max(0, width - leftWidth), 0)
    : 0;
  return {
    width,
    height,
    fps: clampInt(Number(out.fps), 1, 30, 8),
    frames: clampInt(Number(out.frames), 0, 1000000, 0),
    scene: String(out.scene || "browser-orbit-lab"),
    ansi,
    layout,
    leftWidth,
    rightWidth,
    pixelWidth: pixelWidthForAnsi(width, ansi),
    pixelHeight: pixelHeightForAnsi(height, ansi),
  };
}

function pixelWidthForAnsi(width: number, ansi: AnsiMode): number {
  if (isChafaAnsiMode(ansi)) return width * 8;
  if (ansi === "cellfit") return width * 8;
  if (ansi === "half") return width;
  return width * 2;
}

function pixelHeightForAnsi(height: number, ansi: AnsiMode): number {
  if (isChafaAnsiMode(ansi)) return Math.max(16, height * 16);
  if (ansi === "cellfit") return Math.max(8, height * 8);
  if (ansi === "half") return Math.max(2, height * 2);
  return Math.max(4, height * 4);
}

function readEnv(name: string): string | undefined {
  try {
    return Deno.env.get(name) || undefined;
  } catch (_) {
    return undefined;
  }
}

function parseAnsiMode(value: string): AnsiMode {
  const normalized = value.trim().toLowerCase();
  if (normalized === "half") return "half";
  if (
    normalized === "halftone" || normalized === "dither" ||
    normalized === "dithered-half"
  ) return "halftone";
  if (
    normalized === "cellfit" || normalized === "quadrant" ||
    normalized === "quadfit" || normalized === "fit"
  ) return "cellfit";
  if (normalized === "chafa" || normalized === "chafa-vhalf") {
    return "chafa-vhalf";
  }
  if (normalized === "chafa-quad" || normalized === "chafa-quadrant") {
    return "chafa-quad";
  }
  if (normalized === "chafa-block" || normalized === "chafa-blocks") {
    return "chafa-block";
  }
  return "braille";
}

function parseLayoutMode(value: string): LayoutMode {
  const normalized = value.trim().toLowerCase();
  if (
    normalized === "two-side" || normalized === "two-sided" ||
    normalized === "both" || normalized === "double"
  ) return "two-side";
  return "single";
}

function isChafaAnsiMode(ansi: AnsiMode): boolean {
  return ansi === "chafa" || ansi === "chafa-vhalf" || ansi === "chafa-quad" ||
    ansi === "chafa-block";
}

function clampInt(
  value: number,
  min: number,
  max: number,
  fallback: number,
): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.max(min, Math.min(max, Math.round(value)));
}

function joinPath(...parts: string[]): string {
  return parts.join("/").replace(/\/+/g, "/");
}

function emit(obj: Record<string, unknown>): void {
  Deno.stdout.writeSync(encoder.encode(JSON.stringify(obj) + "\n"));
}

function emitError(message: unknown): void {
  emit({
    type: "error",
    message: String(message instanceof Error ? message.message : message).slice(
      0,
      220,
    ),
  });
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export function imageDataToAnsiFrame(
  data: Uint8Array,
  pixelWidth: number,
  pixelHeight: number,
  columns: number,
  rows: number,
  ansiMode: AnsiMode,
): string {
  if (isChafaAnsiMode(ansiMode)) {
    throw new Error("chafa ANSI mode requires async chafa process encoding");
  }
  if (ansiMode === "braille") {
    return imageDataToBrailleAnsi(data, pixelWidth, pixelHeight, columns, rows);
  }
  if (ansiMode === "halftone") {
    return imageDataToHalftoneAnsi(
      data,
      pixelWidth,
      pixelHeight,
      columns,
      rows,
    );
  }
  if (ansiMode === "cellfit") {
    return imageDataToCellFitAnsi(data, pixelWidth, pixelHeight, columns, rows);
  }
  return imageDataToHalfBlockAnsi(data, pixelWidth, pixelHeight);
}

async function imageDataToAnsiFrameAsync(
  data: Uint8Array,
  pixelWidth: number,
  pixelHeight: number,
  columns: number,
  rows: number,
  ansiMode: AnsiMode,
): Promise<string> {
  if (isChafaAnsiMode(ansiMode)) {
    return await imageDataToChafaAnsi(
      data,
      pixelWidth,
      pixelHeight,
      columns,
      rows,
      ansiMode,
    );
  }
  return imageDataToAnsiFrame(
    data,
    pixelWidth,
    pixelHeight,
    columns,
    rows,
    ansiMode,
  );
}

async function imageDataToChafaAnsi(
  data: Uint8Array,
  pixelWidth: number,
  pixelHeight: number,
  columns: number,
  rows: number,
  ansiMode: AnsiMode,
): Promise<string> {
  const ppm = rgbaToPpmBytes(data, pixelWidth, pixelHeight);
  const chafaBin = resolveChafaBin();
  const args = [
    "-f",
    "symbols",
    "-c",
    "full",
    "--probe",
    "off",
    "--relative",
    "off",
    "--polite",
    "on",
    "--optimize",
    "0",
    "--passthrough",
    "none",
    "--size",
    `${columns}x${rows}`,
    "--stretch",
    "--bg",
    readEnv("THREE_SIDECAR_CHAFA_BG") || "#040714",
    "--threshold",
    readEnv("THREE_SIDECAR_CHAFA_THRESHOLD") || "1.0",
    "--preprocess",
    readEnv("THREE_SIDECAR_CHAFA_PREPROCESS") || "off",
    "--work",
    readEnv("THREE_SIDECAR_CHAFA_WORK") || "9",
    "--font-ratio",
    readEnv("THREE_SIDECAR_CHAFA_FONT_RATIO") || "1/2",
    "--color-extractor",
    readEnv("THREE_SIDECAR_CHAFA_COLOR_EXTRACTOR") || "median",
    "--color-space",
    readEnv("THREE_SIDECAR_CHAFA_COLOR_SPACE") || "din99d",
    "--symbols",
    chafaSymbolsForMode(ansiMode),
    "-",
  ];
  const child = new Deno.Command(chafaBin, {
    args,
    stdin: "piped",
    stdout: "piped",
    stderr: "piped",
  }).spawn();
  const writer = child.stdin.getWriter();
  await writer.write(ppm);
  await writer.close();
  const output = await child.output();
  if (output.code !== 0) {
    const stderr = decoder.decode(output.stderr).trim();
    throw new Error(
      `chafa failed with exit ${output.code}${
        stderr ? `: ${stderr.slice(0, 260)}` : ""
      }`,
    );
  }
  return sanitizeChafaAnsi(decoder.decode(output.stdout));
}

export function sanitizeChafaAnsi(ansi: string): string {
  return ansi.replace(/\x1b\[\?25[hl]/g, "").replace(/\r?\n$/, "");
}

function resolveChafaBin(): string {
  const configured = readEnv("THREE_SIDECAR_CHAFA_BIN") || readEnv("CHAFA");
  if (configured) return configured;
  try {
    Deno.statSync("/opt/homebrew/bin/chafa");
    return "/opt/homebrew/bin/chafa";
  } catch (_) {
    return "chafa";
  }
}

function chafaSymbolsForMode(ansiMode: AnsiMode): string {
  const configured = readEnv("THREE_SIDECAR_CHAFA_SYMBOLS");
  if (configured) return configured;
  if (ansiMode === "chafa-quad") return "quad";
  if (ansiMode === "chafa-block") return "block+border+space";
  return "block+border+quad+half+space-wide-inverted";
}

export function rgbaToPpmBytes(
  data: Uint8Array,
  width: number,
  height: number,
): Uint8Array {
  const header = encoder.encode(`P6\n${width} ${height}\n255\n`);
  const body = new Uint8Array(width * height * 3);
  let o = 0;
  for (let y = 0; y < height; y++) {
    // WebGL readback is bottom-left origin; PPM consumers expect top-left rows.
    const sourceY = height - 1 - y;
    const row = sourceY * width * 4;
    for (let x = 0; x < width; x++) {
      const i = row + x * 4;
      const r = data[i] || 0;
      const g = data[i + 1] || 0;
      const b = data[i + 2] || 0;
      if (r === 0 && g === 0 && b === 0) {
        body[o++] = BACKGROUND_RGB[0];
        body[o++] = BACKGROUND_RGB[1];
        body[o++] = BACKGROUND_RGB[2];
      } else {
        body[o++] = r;
        body[o++] = g;
        body[o++] = b;
      }
    }
  }
  const out = new Uint8Array(header.length + body.length);
  out.set(header, 0);
  out.set(body, header.length);
  return out;
}

export function cropRgbaColumns(
  data: Uint8Array,
  pixelWidth: number,
  pixelHeight: number,
  sourceColumns: number,
  columnStart: number,
  columnCount: number,
): { data: Uint8Array; pixelWidth: number } {
  const startColumn = clampInt(columnStart, 0, sourceColumns, 0);
  const count = clampInt(
    columnCount,
    0,
    Math.max(0, sourceColumns - startColumn),
    0,
  );
  if (count === sourceColumns && startColumn === 0) {
    return { data, pixelWidth };
  }
  const x0 = Math.floor((startColumn * pixelWidth) / sourceColumns);
  const x1 = Math.max(
    x0,
    Math.floor(((startColumn + count) * pixelWidth) / sourceColumns),
  );
  const cropWidth = Math.max(0, x1 - x0);
  const out = new Uint8Array(cropWidth * pixelHeight * 4);
  if (cropWidth === 0) return { data: out, pixelWidth: 0 };
  const sourceStride = pixelWidth * 4;
  const destStride = cropWidth * 4;
  const copyBytes = cropWidth * 4;
  for (let y = 0; y < pixelHeight; y++) {
    out.set(
      data.subarray(
        y * sourceStride + x0 * 4,
        y * sourceStride + x0 * 4 + copyBytes,
      ),
      y * destStride,
    );
  }
  return { data: out, pixelWidth: cropWidth };
}

function imageDataToBrailleAnsi(
  data: Uint8Array,
  pixelWidth: number,
  pixelHeight: number,
  columns: number,
  rows: number,
): string {
  const rowStrideBytes = pixelWidth * 4;
  const lines: string[] = [];
  const bg = BACKGROUND_RGB;
  const bgKey = bg.join(";");
  for (let row = 0; row < rows; row++) {
    let out = "";
    let last: string | null = null;
    for (let col = 0; col < columns; col++) {
      let bits = 0;
      let rSum = 0;
      let gSum = 0;
      let bSum = 0;
      let lit = 0;
      for (let yy = 0; yy < 4; yy++) {
        for (let xx = 0; xx < 2; xx++) {
          const px = Math.min(pixelWidth - 1, col * 2 + xx);
          const py = Math.min(pixelHeight - 1, row * 4 + yy);
          const rgb = samplePixel(data, rowStrideBytes, pixelHeight, py, px);
          const luminance = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
          const chroma = Math.max(rgb[0], rgb[1], rgb[2]) -
            Math.min(rgb[0], rgb[1], rgb[2]);
          if (luminance > 28 || chroma > 22) {
            bits |= BRAILLE_DOTS[yy * 2 + xx];
            rSum += rgb[0];
            gSum += rgb[1];
            bSum += rgb[2];
            lit++;
          }
        }
      }
      let ch = " ";
      let fg = bg;
      if (bits !== 0) {
        ch = String.fromCharCode(BRAILLE_BASE + bits);
        fg = [
          clampColor(rSum / lit),
          clampColor(gSum / lit),
          clampColor(bSum / lit),
        ];
      }
      const key = `${fg.join(";")};${bgKey}`;
      if (key !== last) {
        out += `${ESC}[38;2;${fg.join(";")};48;2;${bgKey}m`;
        last = key;
      }
      out += ch;
    }
    if (last !== null) out += `${ESC}[0m`;
    lines.push(out);
  }
  return lines.join("\n");
}

function imageDataToHalftoneAnsi(
  data: Uint8Array,
  pixelWidth: number,
  pixelHeight: number,
  columns: number,
  rows: number,
): string {
  const rowStrideBytes = pixelWidth * 4;
  const lines: string[] = [];
  for (let row = 0; row < rows; row++) {
    let out = "";
    let lastFg: string | null = null;
    for (let col = 0; col < columns; col++) {
      const x0 = Math.floor((col * pixelWidth) / columns);
      const x1 = Math.max(
        x0 + 1,
        Math.floor(((col + 1) * pixelWidth) / columns),
      );
      const y0 = Math.floor((row * pixelHeight) / rows);
      const y1 = Math.max(y0 + 1, Math.floor(((row + 1) * pixelHeight) / rows));
      const cell = sampleHalftoneDensityCell(
        data,
        rowStrideBytes,
        pixelHeight,
        x0,
        x1,
        y0,
        y1,
        col,
        row,
      );
      if (cell.ch === " ") {
        if (lastFg !== null) {
          out += `${ESC}[0m`;
          lastFg = null;
        }
        out += cell.ch;
        continue;
      }
      const fg = cell.fg.join(";");
      if (fg !== lastFg) {
        out += `${ESC}[38;2;${fg}m`;
        lastFg = fg;
      }
      out += cell.ch;
    }
    if (lastFg !== null) out += `${ESC}[0m`;
    lines.push(out);
  }
  return lines.join("\n");
}

function imageDataToHalfBlockAnsi(
  data: Uint8Array,
  width: number,
  pixelHeight: number,
): string {
  const rows = Math.floor(pixelHeight / 2);
  const rowStrideBytes = width * 4;
  const lines: string[] = [];
  for (let y = 0; y < rows; y++) {
    let out = "";
    let lastFg: string | null = null;
    let lastBg: string | null = null;
    for (let x = 0; x < width; x++) {
      const top = samplePixel(data, rowStrideBytes, pixelHeight, y * 2, x);
      const bot = samplePixel(data, rowStrideBytes, pixelHeight, y * 2 + 1, x);
      const fg = top.join(";");
      const bg = bot.join(";");
      if (fg !== lastFg || bg !== lastBg) {
        out += `${ESC}[38;2;${fg};48;2;${bg}m`;
        lastFg = fg;
        lastBg = bg;
      }
      out += HALF;
    }
    if (lastFg !== null) out += `${ESC}[0m`;
    lines.push(out);
  }
  return lines.join("\n");
}

function imageDataToCellFitAnsi(
  data: Uint8Array,
  pixelWidth: number,
  pixelHeight: number,
  columns: number,
  rows: number,
): string {
  const rowStrideBytes = pixelWidth * 4;
  const lines: string[] = [];
  for (let row = 0; row < rows; row++) {
    let out = "";
    let lastStyle: string | null = null;
    for (let col = 0; col < columns; col++) {
      const x0 = Math.floor((col * pixelWidth) / columns);
      const x1 = Math.max(
        x0 + 1,
        Math.floor(((col + 1) * pixelWidth) / columns),
      );
      const y0 = Math.floor((row * pixelHeight) / rows);
      const y1 = Math.max(y0 + 1, Math.floor(((row + 1) * pixelHeight) / rows));
      const cell = sampleCellFitCell(
        data,
        rowStrideBytes,
        pixelHeight,
        x0,
        x1,
        y0,
        y1,
      );
      const ch = QUADRANT_GLYPHS[cell.mask] || " ";
      if (cell.mask === 0) {
        if (lastStyle !== null) {
          out += `${ESC}[0m`;
          lastStyle = null;
        }
        out += " ";
        continue;
      }
      const fg = cell.fg.join(";");
      const bg = cell.bg.join(";");
      const style = cell.mask === 15 ? `38;2;${fg}` : `38;2;${fg};48;2;${bg}`;
      if (style !== lastStyle) {
        out += `${ESC}[${style}m`;
        lastStyle = style;
      }
      out += ch;
    }
    if (lastStyle !== null) out += `${ESC}[0m`;
    lines.push(out);
  }
  return lines.join("\n");
}

type RegionSummary = {
  active: boolean;
  color: [number, number, number];
  coverage: number;
  weight: number;
};

function sampleCellFitCell(
  data: Uint8Array,
  rowStrideBytes: number,
  pixelHeight: number,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
): {
  mask: number;
  fg: [number, number, number];
  bg: [number, number, number];
} {
  const xm = Math.max(x0 + 1, Math.floor((x0 + x1) / 2));
  const ym = Math.max(y0 + 1, Math.floor((y0 + y1) / 2));
  const quads: RegionSummary[] = [
    summarizeCellFitRegion(data, rowStrideBytes, pixelHeight, x0, xm, y0, ym),
    summarizeCellFitRegion(data, rowStrideBytes, pixelHeight, xm, x1, y0, ym),
    summarizeCellFitRegion(data, rowStrideBytes, pixelHeight, x0, xm, ym, y1),
    summarizeCellFitRegion(data, rowStrideBytes, pixelHeight, xm, x1, ym, y1),
  ];
  let mask = 0;
  for (let i = 0; i < quads.length; i++) if (quads[i].active) mask |= 1 << i;
  if (mask === 0) return { mask: 0, fg: BACKGROUND_RGB, bg: BACKGROUND_RGB };
  const active = quads.filter((q) => q.active);
  const inactive = quads.filter((q) => !q.active);
  return {
    mask,
    fg: weightedColor(active),
    bg: inactive.length ? weightedColor(inactive) : BACKGROUND_RGB,
  };
}

function summarizeCellFitRegion(
  data: Uint8Array,
  rowStrideBytes: number,
  pixelHeight: number,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
): RegionSummary {
  const all: [number, number, number][] = [];
  const visible: [number, number, number][] = [];
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const rgb = samplePixel(data, rowStrideBytes, pixelHeight, y, x);
      all.push(rgb);
      if (!isNearBackground(rgb)) visible.push(rgb);
    }
  }
  if (all.length === 0) {
    return { active: false, color: BACKGROUND_RGB, coverage: 0, weight: 1 };
  }
  const coverage = visible.length / all.length;
  const active = coverage >= 0.12;
  const source = active ? visible : all;
  const color = robustTrimmedColor(source);
  const energy = active
    ? Math.max(coverage, clampUnit((luminance(color) - 8) / 130))
    : 0.08;
  return { active, color, coverage, weight: Math.max(0.05, energy) };
}

function weightedColor(regions: RegionSummary[]): [number, number, number] {
  let total = 0;
  let r = 0;
  let g = 0;
  let b = 0;
  for (const region of regions) {
    const w = region.weight;
    r += region.color[0] * w;
    g += region.color[1] * w;
    b += region.color[2] * w;
    total += w;
  }
  if (total <= 0) return BACKGROUND_RGB;
  return [clampColor(r / total), clampColor(g / total), clampColor(b / total)];
}

function robustTrimmedColor(
  samples: [number, number, number][],
): [number, number, number] {
  if (samples.length === 0) return BACKGROUND_RGB;
  const sorted = samples.slice().sort((a, b) => luminance(a) - luminance(b));
  const trim = sorted.length >= 8
    ? Math.max(1, Math.floor(sorted.length * 0.18))
    : 0;
  const kept = sorted.slice(trim, Math.max(trim + 1, sorted.length - trim));
  let r = 0;
  let g = 0;
  let b = 0;
  for (const rgb of kept) {
    r += rgb[0];
    g += rgb[1];
    b += rgb[2];
  }
  return [
    clampColor(r / kept.length),
    clampColor(g / kept.length),
    clampColor(b / kept.length),
  ];
}

function sampleHalftoneDensityCell(
  data: Uint8Array,
  rowStrideBytes: number,
  pixelHeight: number,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
  outX: number,
  outY: number,
): { ch: string; fg: [number, number, number] } {
  let rSum = 0;
  let gSum = 0;
  let bSum = 0;
  let ySum = 0;
  let count = 0;
  let visible = 0;
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const rgb = samplePixel(data, rowStrideBytes, pixelHeight, y, x);
      const yLum = luminance(rgb);
      count++;
      if (!isNearBackground(rgb)) {
        rSum += rgb[0];
        gSum += rgb[1];
        bSum += rgb[2];
        ySum += yLum;
        visible++;
      }
    }
  }
  if (count === 0 || visible === 0) return { ch: " ", fg: BACKGROUND_RGB };

  const coverage = visible / count;
  const avgR = rSum / visible;
  const avgG = gSum / visible;
  const avgB = bSum / visible;
  const avgY = ySum / visible;
  const luminanceDensity = clampUnit((avgY - 8) / 150);
  const thresholdJitter = (bayerThreshold(outX, outY) - 0.5) * 0.22;
  const density = clampUnit(
    coverage * 0.72 + luminanceDensity * 0.34 + thresholdJitter,
  );
  const level = Math.max(
    1,
    Math.min(
      DENSITY_CHARS.length - 1,
      Math.round(density * (DENSITY_CHARS.length - 1)),
    ),
  );
  const boost = 1.02 + level * 0.035;
  return {
    ch: DENSITY_CHARS[level],
    fg: [
      clampColor(avgR * boost),
      clampColor(avgG * boost),
      clampColor(avgB * boost),
    ],
  };
}

function isNearBackground(rgb: [number, number, number]): boolean {
  const dr = rgb[0] - BACKGROUND_RGB[0];
  const dg = rgb[1] - BACKGROUND_RGB[1];
  const db = rgb[2] - BACKGROUND_RGB[2];
  return dr * dr + dg * dg + db * db < 120;
}

function bayerThreshold(x: number, y: number): number {
  return (BAYER_4X4[(y & 3) * 4 + (x & 3)] + 0.5) / 16;
}

function luminance(rgb: [number, number, number]): number {
  return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
}

function clampUnit(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function samplePixel(
  data: Uint8Array,
  rowStrideBytes: number,
  pixelHeight: number,
  y: number,
  x: number,
): [number, number, number] {
  // WebGL readRenderTargetPixels is bottom-left origin; ANSI frames are top-left origin.
  const sourceY = Math.max(0, Math.min(pixelHeight - 1, pixelHeight - 1 - y));
  const i = sourceY * rowStrideBytes + x * 4;
  const r = data[i] || 0;
  const g = data[i + 1] || 0;
  const b = data[i + 2] || 0;
  if (r === 0 && g === 0 && b === 0) return BACKGROUND_RGB;
  return [r, g, b];
}

function clampColor(value: number): number {
  return Math.max(0, Math.min(255, Math.round(value)));
}

async function emitFrameFromPixels(pixels: Uint8Array): Promise<void> {
  if (opts.layout === "two-side") {
    const leftCrop = cropRgbaColumns(
      pixels,
      opts.pixelWidth,
      opts.pixelHeight,
      opts.width,
      0,
      opts.leftWidth,
    );
    const rightCrop = cropRgbaColumns(
      pixels,
      opts.pixelWidth,
      opts.pixelHeight,
      opts.width,
      opts.width - opts.rightWidth,
      opts.rightWidth,
    );
    const leftAnsi = opts.leftWidth > 0
      ? await imageDataToAnsiFrameAsync(
        leftCrop.data,
        leftCrop.pixelWidth,
        opts.pixelHeight,
        opts.leftWidth,
        opts.height,
        opts.ansi,
      )
      : "";
    const rightAnsi = opts.rightWidth > 0
      ? await imageDataToAnsiFrameAsync(
        rightCrop.data,
        rightCrop.pixelWidth,
        opts.pixelHeight,
        opts.rightWidth,
        opts.height,
        opts.ansi,
      )
      : "";
    emit({
      type: "frame-pair",
      seq: ++seq,
      width: opts.width,
      height: opts.height,
      leftWidth: opts.leftWidth,
      rightWidth: opts.rightWidth,
      renderer: "browser-webgl-cef",
      encoding: "base64-ansi",
      leftData: bytesToBase64(encoder.encode(leftAnsi)),
      rightData: bytesToBase64(encoder.encode(rightAnsi)),
    });
    return;
  }

  const ansi = await imageDataToAnsiFrameAsync(
    pixels,
    opts.pixelWidth,
    opts.pixelHeight,
    opts.width,
    opts.height,
    opts.ansi,
  );
  emit({
    type: "frame",
    seq: ++seq,
    width: opts.width,
    height: opts.height,
    renderer: "browser-webgl-cef",
    encoding: "base64-ansi",
    data: bytesToBase64(encoder.encode(ansi)),
  });
}

function resolveCapybaraWideVideoPath(): string {
  return readEnv("THREE_SIDECAR_EIDOVERSE_CAPY_VIDEO") ||
    "/Users/MAC/Documents/eidoverse-video/work/capybara-onsen-v2/wide-gap-capybara-onsen-video.mp4";
}

async function serveVideoFile(
  req: Request,
  path: string,
  contentType: string,
): Promise<Response> {
  const stat = await Deno.stat(path);
  const size = stat.size;
  const range = req.headers.get("range");
  const headers = new Headers({
    "content-type": contentType,
    "accept-ranges": "bytes",
    "cache-control": "no-store",
  });
  if (range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(range.trim());
    if (!match) return new Response("bad range", { status: 416, headers });
    let start = match[1] ? Number(match[1]) : 0;
    let end = match[2] ? Number(match[2]) : size - 1;
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0) {
      return new Response("bad range", { status: 416, headers });
    }
    end = Math.min(end, size - 1);
    if (start > end || start >= size) {
      headers.set("content-range", `bytes */${size}`);
      return new Response(null, { status: 416, headers });
    }
    const length = end - start + 1;
    const file = await Deno.open(path, { read: true });
    try {
      await file.seek(start, Deno.SeekMode.Start);
      const chunk = new Uint8Array(length);
      let offset = 0;
      while (offset < length) {
        const read = await file.read(chunk.subarray(offset));
        if (read === null) break;
        offset += read;
      }
      headers.set("content-length", String(offset));
      headers.set(
        "content-range",
        `bytes ${start}-${start + offset - 1}/${size}`,
      );
      return new Response(chunk.subarray(0, offset), {
        status: 206,
        headers,
      });
    } finally {
      file.close();
    }
  }
  headers.set("content-length", String(size));
  return new Response(await Deno.readFile(path), { headers });
}

async function handleRequest(req: Request): Promise<Response> {
  const url = new URL(req.url);
  try {
    if (url.pathname.startsWith("/vendor/")) {
      const file = decodeURIComponent(url.pathname.slice("/vendor/".length));
      if (file.includes("..") || file.includes("/")) {
        return new Response("bad vendor path", { status: 400 });
      }
      const data = await Deno.readFile(
        joinPath(assetRoot, "node_modules", "three", "build", file),
      );
      return new Response(data, {
        headers: {
          "content-type": "text/javascript; charset=utf-8",
          "cache-control": "no-store",
        },
      });
    }
    if (url.pathname === "/eidoverse/capybara-wide.mp4") {
      return await serveVideoFile(
        req,
        resolveCapybaraWideVideoPath(),
        "video/mp4",
      );
    }
    if (url.pathname === "/app.js") {
      return new Response(browserAppJs(), {
        headers: {
          "content-type": "text/javascript; charset=utf-8",
          "cache-control": "no-store",
        },
      });
    }
    if (url.pathname === "/hello" && req.method === "POST") {
      const info = await req.json().catch(() => ({}));
      if (!helloSent) {
        helloSent = true;
        emit({
          type: "hello",
          protocol: 1,
          renderer: "browser-webgl-cef",
          requestedRenderer: "browser-webgl",
          fallbackReason: null,
          scene: opts.scene,
          width: opts.width,
          height: opts.height,
          fps: opts.fps,
          ansi: opts.ansi,
          layout: opts.layout,
          leftWidth: opts.leftWidth,
          rightWidth: opts.rightWidth,
          threeRevision: (info as Record<string, unknown>)?.threeRevision ||
            null,
          webglRenderer: (info as Record<string, unknown>)?.webgl2
            ? "webgl2"
            : "webgl1",
          maxTextureSize: (info as Record<string, unknown>)?.maxTextureSize ||
            null,
        });
      }
      return json({ ok: true });
    }
    if (url.pathname === "/frame" && req.method === "POST") {
      if (stopping) return json({ ok: true, stop: true });
      const pixels = new Uint8Array(await req.arrayBuffer());
      if (pixels.length < opts.pixelWidth * opts.pixelHeight * 4) {
        throw new Error("short pixel payload");
      }
      await emitFrameFromPixels(pixels);
      if (seq % Math.max(1, opts.fps) === 0) {
        emit({
          type: "metric",
          fps: opts.fps,
          renderer: "browser-webgl-cef",
          elapsedMs: Date.now() - startedAt,
        });
      }
      if (opts.frames && seq >= opts.frames) {
        stopping = true;
        setTimeout(shutdownCleanly, 250);
        return json({ ok: true, stop: true });
      }
      return json({ ok: true, stop: false });
    }
    if (url.pathname === "/error" && req.method === "POST") {
      const body = await req.text();
      emitError(body);
      return json({ ok: false }, 500);
    }
    return new Response(browserHtml(), {
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  } catch (error) {
    emitError(error);
    return json({
      ok: false,
      error: String(error instanceof Error ? error.message : error),
    }, 500);
  }
}

function json(obj: Record<string, unknown>, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function browserHtml(): string {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>three.js browser-webgl sidecar</title>
<style>
  html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: #040714; color: #9ed9ff; font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }
  #c { display: block; width: ${opts.pixelWidth}px; height: ${opts.pixelHeight}px; image-rendering: pixelated; }
  #hud { position: fixed; left: 8px; bottom: 6px; opacity: 0.65; pointer-events: none; }
</style>
</head>
<body>
<canvas id="c" width="${opts.pixelWidth}" height="${opts.pixelHeight}"></canvas>
<div id="hud">three.js WebGL → ANSI sidecar</div>
<script src="/app.js"></script>
</body>
</html>`;
}

function browserAppJs(): string {
  return `
const cfg = ${
    JSON.stringify({
      width: opts.width,
      height: opts.height,
      fps: opts.fps,
      frames: opts.frames,
      scene: opts.scene,
      ansi: opts.ansi,
      layout: opts.layout,
      leftWidth: opts.leftWidth,
      rightWidth: opts.rightWidth,
      pixelWidth: opts.pixelWidth,
      pixelHeight: opts.pixelHeight,
    })
  };

async function reportError(error) {
  await fetch('/error', { method: 'POST', headers: { 'content-type': 'text/plain' }, body: String(error && error.stack ? error.stack : error) }).catch(() => {});
}

(async function main() {
  try {
    const THREE = await import('/vendor/three.module.js');
    const canvas = document.getElementById('c');
    canvas.width = cfg.pixelWidth;
    canvas.height = cfg.pixelHeight;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
    renderer.setPixelRatio(1);
    renderer.setSize(cfg.pixelWidth, cfg.pixelHeight, false);
    renderer.setClearColor(0x020614, 1);
    if ('outputColorSpace' in renderer) renderer.outputColorSpace = THREE.SRGBColorSpace;
    const target = new THREE.WebGLRenderTarget(cfg.pixelWidth, cfg.pixelHeight, { depthBuffer: true, stencilBuffer: false, samples: 0 });
    const sceneState = await createScene(THREE, cfg);
    const pixels = new Uint8Array(cfg.pixelWidth * cfg.pixelHeight * 4);
    let running = true;
    let last = 0;
    await fetch('/hello', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ threeRevision: THREE.REVISION, webgl2: renderer.capabilities.isWebGL2, maxTextureSize: renderer.capabilities.maxTextureSize })
    });
    async function loop(now) {
      if (!running) return;
      const minDelta = 1000 / Math.max(1, cfg.fps);
      if (now - last < minDelta) return requestAnimationFrame(loop);
      last = now;
      try {
        const t = now / 1000;
        sceneState.update(t);
        renderer.setRenderTarget(target);
        renderer.render(sceneState.scene, sceneState.camera);
        renderer.readRenderTargetPixels(target, 0, 0, cfg.pixelWidth, cfg.pixelHeight, pixels);
        renderer.setRenderTarget(null);
        renderer.render(sceneState.scene, sceneState.camera);
        const res = await fetch('/frame', { method: 'POST', headers: { 'content-type': 'application/octet-stream' }, body: pixels });
        const msg = await res.json().catch(() => ({}));
        if (msg.stop) {
          running = false;
          try { renderer.dispose(); target.dispose(); } catch (_) {}
          return;
        }
      } catch (error) {
        running = false;
        await reportError(error);
        return;
      }
      requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);
  } catch (error) {
    await reportError(error);
  }
})();

async function createScene(THREE, cfg) {
  if (cfg.scene === 'eidoverse-capybara-onsen-wide' || cfg.scene === 'capybara-onsen-wide') {
    return await createCapybaraWideVideoScene(THREE, cfg);
  }
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x020614);
  scene.fog = new THREE.FogExp2(0x020614, 0.05);
  const camera = new THREE.PerspectiveCamera(46, cfg.pixelWidth / Math.max(1, cfg.pixelHeight), 0.1, 100);
  camera.position.set(0, 1.25, 6.4);
  const group = new THREE.Group();
  scene.add(group);
  scene.add(new THREE.HemisphereLight(0x88ccff, 0x1a1035, 2.1));
  const key = new THREE.PointLight(0x7cfffc, 110, 18);
  key.position.set(3.5, 4.5, 4.0);
  scene.add(key);
  const magenta = new THREE.PointLight(0xff5dd6, 80, 14);
  magenta.position.set(-4.5, -1.5, 3.0);
  scene.add(magenta);
  const core = new THREE.Mesh(
    new THREE.TorusKnotGeometry(1.05, 0.32, 128, 18, 2, 3),
    new THREE.MeshStandardMaterial({ color: 0x39ffcc, roughness: 0.28, metalness: 0.72, emissive: 0x082a22, emissiveIntensity: 0.75 })
  );
  group.add(core);
  const inner = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.72, 2),
    new THREE.MeshStandardMaterial({ color: 0x294dff, roughness: 0.38, metalness: 0.38, emissive: 0x050570, emissiveIntensity: 0.85 })
  );
  group.add(inner);
  const ringA = new THREE.Mesh(new THREE.TorusGeometry(2.28, 0.018, 8, 160), new THREE.MeshBasicMaterial({ color: 0xffd36b, transparent: true, opacity: 0.92 }));
  const ringB = new THREE.Mesh(new THREE.TorusGeometry(2.88, 0.014, 8, 160), new THREE.MeshBasicMaterial({ color: 0xaa76ff, transparent: true, opacity: 0.82 }));
  ringA.rotation.x = Math.PI * 0.5;
  ringB.rotation.x = Math.PI * 0.5;
  ringB.rotation.y = Math.PI * 0.17;
  group.add(ringA, ringB);
  const satellites = [];
  const satColors = [0xffec99, 0x7df9ff, 0xff66d9, 0x9dff7a, 0xffffff];
  for (let i = 0; i < 7; i++) {
    const sat = new THREE.Mesh(new THREE.SphereGeometry(0.08 + (i % 3) * 0.025, 16, 8), new THREE.MeshBasicMaterial({ color: satColors[i % satColors.length] }));
    satellites.push(sat);
    group.add(sat);
  }
  const stars = makeStars(THREE, 260, 12, 41);
  scene.add(stars);
  const floor = new THREE.Mesh(new THREE.RingGeometry(3.2, 3.28, 160), new THREE.MeshBasicMaterial({ color: 0x173d70, transparent: true, opacity: 0.55 }));
  floor.rotation.x = Math.PI * 0.5;
  floor.position.y = -1.58;
  scene.add(floor);
  return {
    scene,
    camera,
    update(time) {
      const breathe = Math.sin(time * 1.7) * 0.08;
      group.rotation.y = time * 0.34;
      group.rotation.x = Math.sin(time * 0.37) * 0.16;
      core.rotation.x = time * 0.58;
      core.rotation.z = time * 0.31;
      inner.rotation.y = -time * 0.82;
      inner.scale.setScalar(0.93 + breathe);
      ringA.rotation.z = time * 0.22;
      ringB.rotation.z = -time * 0.18;
      satellites.forEach((sat, i) => {
        const radius = 1.78 + (i % 4) * 0.34;
        const speed = 0.46 + i * 0.055;
        const a = time * speed + i * 0.897;
        sat.position.set(Math.cos(a) * radius, Math.sin(a * 1.7 + i) * 0.65, Math.sin(a) * radius * 0.54);
      });
      stars.rotation.y = time * 0.018;
      stars.rotation.x = Math.sin(time * 0.13) * 0.035;
      camera.position.x = Math.sin(time * 0.21) * 0.32;
      camera.position.y = 1.20 + Math.sin(time * 0.27) * 0.18;
      camera.lookAt(0, 0, 0);
    }
  };
}

async function createCapybaraWideVideoScene(THREE, cfg) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x01030a);
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const video = document.createElement('video');
  video.src = '/eidoverse/capybara-wide.mp4';
  video.muted = true;
  video.loop = true;
  video.playsInline = true;
  video.autoplay = true;
  video.preload = 'auto';
  video.crossOrigin = 'anonymous';
  video.style.display = 'none';
  document.body.appendChild(video);
  const canPlay = new Promise((resolve) => {
    let done = false;
    function finish() {
      if (done) return;
      done = true;
      resolve();
    }
    video.addEventListener('loadeddata', finish, { once: true });
    video.addEventListener('canplay', finish, { once: true });
    setTimeout(finish, 1500);
  });
  video.play().catch(() => {});
  await canPlay;

  const texture = new THREE.VideoTexture(video);
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.generateMipmaps = false;
  if ('colorSpace' in texture) texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    toneMapped: false,
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
  scene.add(mesh);

  function fitContain() {
    const videoWidth = video.videoWidth || 1280;
    const videoHeight = video.videoHeight || 720;
    const videoAspect = videoWidth / Math.max(1, videoHeight);
    const canvasAspect = cfg.pixelWidth / Math.max(1, cfg.pixelHeight);
    if (canvasAspect > videoAspect) {
      mesh.scale.set(videoAspect / canvasAspect, 1, 1);
    } else {
      mesh.scale.set(1, canvasAspect / videoAspect, 1);
    }
  }

  fitContain();
  return {
    scene,
    camera,
    update() {
      if (video.paused) video.play().catch(() => {});
      fitContain();
      texture.needsUpdate = true;
    }
  };
}

function makeStars(THREE, count, radius, seed) {
  let s = seed >>> 0;
  function rand() { s = (s * 1664525 + 1013904223) >>> 0; return s / 0xffffffff; }
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const u = rand() * 2 - 1;
    const theta = rand() * Math.PI * 2;
    const r = radius * (0.35 + rand() * 0.65);
    const q = Math.sqrt(Math.max(0, 1 - u * u));
    positions[i * 3 + 0] = Math.cos(theta) * q * r;
    positions[i * 3 + 1] = u * r;
    positions[i * 3 + 2] = Math.sin(theta) * q * r - 2.5;
    const c = 0.34 + rand() * 0.66;
    colors[i * 3 + 0] = c * 0.65;
    colors[i * 3 + 1] = c * 0.82;
    colors[i * 3 + 2] = c;
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geom.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  return new THREE.Points(geom, new THREE.PointsMaterial({ size: 0.045, vertexColors: true, transparent: true, opacity: 0.82 }));
}
`;
}

function shutdownCleanly(): void {
  try {
    win?.close?.();
  } catch (_) {}
  setTimeout(() => Deno.exit(0), 150);
}

function browserWindowMode(): string {
  const raw = (readEnv("THREE_SIDECAR_BROWSER_WEBGL_WINDOW_MODE") ||
    readEnv("THREE_SIDECAR_BROWSER_WEBGL_WINDOW") || "visible").trim()
    .toLowerCase();
  if (raw === "hidden" || raw === "hide") return "hidden";
  if (raw === "offscreen" || raw === "headless" || raw === "background") {
    return "offscreen";
  }
  return "visible";
}

function startSidecar(): void {
  try {
    Deno.serve(handleRequest);
    const BrowserWindow = (Deno as unknown as {
      BrowserWindow?: new (opts?: Record<string, unknown>) => any;
    }).BrowserWindow;
    if (!BrowserWindow) {
      throw new Error(
        "Deno.BrowserWindow unavailable; run through deno desktop",
      );
    }
    const mode = browserWindowMode();
    win = new BrowserWindow({
      title: "three.js browser-webgl sidecar",
      width: Math.max(320, Math.min(980, opts.pixelWidth + 24)),
      height: Math.max(240, Math.min(760, opts.pixelHeight + 56)),
      x: mode === "offscreen" ? -32000 : undefined,
      y: mode === "offscreen" ? -32000 : undefined,
      resizable: mode === "visible",
      noActivate: mode !== "visible",
      frameless: mode !== "visible",
    });
    if (mode === "hidden") {
      setTimeout(() => {
        try {
          win?.hide?.();
        } catch (_) {}
      }, 250);
    }
  } catch (error) {
    emitError(error);
    Deno.exit(2);
  }

  Deno.addSignalListener("SIGTERM", () => shutdownCleanly());
  Deno.addSignalListener("SIGINT", () => shutdownCleanly());
}

if (import.meta.main) startSidecar();
