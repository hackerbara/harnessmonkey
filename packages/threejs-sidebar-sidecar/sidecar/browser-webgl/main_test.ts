import {
  cropRgbaColumns,
  imageDataToAnsiFrame,
  parseArgs,
  rgbaToPpmBytes,
  sanitizeChafaAnsi,
} from "./main.ts";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function assertEquals<T>(actual: T, expected: T, message?: string): void {
  if (actual !== expected) {
    throw new Error(
      message || `expected ${String(expected)}, got ${String(actual)}`,
    );
  }
}

function makeGradientRgba(width: number, height: number): Uint8Array {
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      data[i] = 24 + x * 30;
      data[i + 1] = 32 + y * 18;
      data[i + 2] = 88 + ((x + y) % 3) * 36;
      data[i + 3] = 255;
    }
  }
  return data;
}

function makeSolidRgba(
  width: number,
  height: number,
  rgb: [number, number, number],
): Uint8Array {
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      data[i] = rgb[0];
      data[i + 1] = rgb[1];
      data[i + 2] = rgb[2];
      data[i + 3] = 255;
    }
  }
  return data;
}

Deno.test("parseArgs accepts explicit halftone mode and uses supersampled half-block pixels", () => {
  const opts = parseArgs([
    "--width",
    "80",
    "--height",
    "30",
    "--ansi",
    "halftone",
  ]);

  assertEquals(opts.ansi, "halftone");
  assertEquals(opts.pixelWidth, 160);
  assertEquals(opts.pixelHeight, 120);
});

Deno.test("parseArgs accepts CLAUDEMONKEY_THREE_SIDECAR_ANSI=halftone fallback", () => {
  const previous = Deno.env.get("CLAUDEMONKEY_THREE_SIDECAR_ANSI");
  try {
    Deno.env.set("CLAUDEMONKEY_THREE_SIDECAR_ANSI", "halftone");
    const opts = parseArgs(["--width", "40", "--height", "12"]);

    assertEquals(opts.ansi, "halftone");
    assertEquals(opts.pixelWidth, 80);
    assertEquals(opts.pixelHeight, 48);
  } finally {
    if (previous === undefined) {
      Deno.env.delete("CLAUDEMONKEY_THREE_SIDECAR_ANSI");
    } else Deno.env.set("CLAUDEMONKEY_THREE_SIDECAR_ANSI", previous);
  }
});

Deno.test("parseArgs accepts cellfit mode and uses heavier per-cell supersampling", () => {
  const opts = parseArgs([
    "--width",
    "80",
    "--height",
    "30",
    "--ansi",
    "cellfit",
  ]);

  assertEquals(opts.ansi, "cellfit");
  assertEquals(opts.pixelWidth, 640);
  assertEquals(opts.pixelHeight, 240);
});

Deno.test("parseArgs accepts chafa-vhalf mode and uses terminal-cell aspect supersampling", () => {
  const opts = parseArgs([
    "--width",
    "80",
    "--height",
    "30",
    "--ansi",
    "chafa-vhalf",
  ]);

  assertEquals(opts.ansi, "chafa-vhalf");
  assertEquals(opts.pixelWidth, 640);
  assertEquals(opts.pixelHeight, 480);
});

Deno.test("parseArgs accepts two-side layout dimensions for full-width sidecar crops", () => {
  const opts = parseArgs([
    "--width",
    "160",
    "--height",
    "54",
    "--ansi",
    "chafa-vhalf",
    "--layout",
    "two-side",
    "--left-width",
    "30",
    "--right-width",
    "30",
  ]);

  assertEquals(opts.layout, "two-side");
  assertEquals(opts.leftWidth, 30);
  assertEquals(opts.rightWidth, 30);
  assertEquals(opts.pixelWidth, 1280);
  assertEquals(opts.pixelHeight, 864);
});

Deno.test("parseArgs allows 30fps but still caps runaway fps values", () => {
  assertEquals(parseArgs(["--fps", "30"]).fps, 30);
  assertEquals(parseArgs(["--fps", "120"]).fps, 30);
});

Deno.test("halftone encoder emits truecolor density rows at terminal dimensions", () => {
  const width = 4;
  const height = 3;
  const pixelWidth = width * 2;
  const pixelHeight = height * 4;
  const ansi = imageDataToAnsiFrame(
    makeGradientRgba(pixelWidth, pixelHeight),
    pixelWidth,
    pixelHeight,
    width,
    height,
    "halftone",
  );

  const lines = ansi.split("\n");
  assertEquals(lines.length, height);
  assert(
    lines.every((line) => line.includes("\x1b[38;2;")),
    "expected truecolor foreground escapes",
  );
  assertEquals((ansi.match(/[ ░▒▓█]/g) || []).length, width * height);
  assert(
    !/[\u2800-\u28ff]/.test(ansi),
    "halftone should not emit braille glyphs",
  );
});

Deno.test("halftone encoder is foreground-only so it survives raw ANSI paths that ignore backgrounds", () => {
  const width = 4;
  const height = 3;
  const pixelWidth = width * 2;
  const pixelHeight = height * 4;
  const ansi = imageDataToAnsiFrame(
    makeGradientRgba(pixelWidth, pixelHeight),
    pixelWidth,
    pixelHeight,
    width,
    height,
    "halftone",
  );

  assert(
    !ansi.includes("▀"),
    "halftone should not rely on half-block glyph backgrounds",
  );
  assert(
    !ansi.includes(";48;2;"),
    "halftone should not rely on truecolor background escapes",
  );
  assert(/[░▒▓█]/.test(ansi), "expected foreground-only density glyphs");
});

Deno.test("cellfit encoder emits quadrant-fit block glyphs at terminal dimensions", () => {
  const width = 4;
  const height = 3;
  const pixelWidth = width * 8;
  const pixelHeight = height * 8;
  const ansi = imageDataToAnsiFrame(
    makeGradientRgba(pixelWidth, pixelHeight),
    pixelWidth,
    pixelHeight,
    width,
    height,
    "cellfit",
  );

  const lines = ansi.split("\n");
  assertEquals(lines.length, height);
  assert(
    lines.every((line) => line.includes("\x1b[38;2;")),
    "expected truecolor foreground escapes",
  );
  assertEquals(
    (ansi.match(/[ ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█]/g) || []).length,
    width * height,
  );
  assert(
    !/[░▒▓]/.test(ansi),
    "cellfit should use shape masks, not density glyphs",
  );
  assert(
    !/[\u2800-\u28ff]/.test(ansi),
    "cellfit should not emit braille glyphs",
  );
});

Deno.test("cellfit encoder does not let one white sample dominate a colored cell", () => {
  const width = 1;
  const height = 1;
  const pixelWidth = 8;
  const pixelHeight = 8;
  const data = makeSolidRgba(pixelWidth, pixelHeight, [0, 170, 130]);
  data[0] = 255;
  data[1] = 255;
  data[2] = 255;
  const ansi = imageDataToAnsiFrame(
    data,
    pixelWidth,
    pixelHeight,
    width,
    height,
    "cellfit",
  );

  assert(
    !ansi.includes("255;255;255"),
    "single-pixel highlights should be trimmed before foreground selection",
  );
  assert(
    !/\x1b\[38;2;2[2-9]\d;2[2-9]\d;2[2-9]\d/.test(ansi),
    "foreground should not become near-white",
  );
});

Deno.test("rgbaToPpmBytes flips WebGL bottom-left rows into image top-left rows", () => {
  const data = new Uint8Array([
    255,
    0,
    0,
    255,
    0,
    255,
    0,
    255, // WebGL bottom row: red, green
    0,
    0,
    255,
    255,
    255,
    255,
    255,
    255, // WebGL top row: blue, white
  ]);

  const ppm = rgbaToPpmBytes(data, 2, 2);
  const header = new TextEncoder().encode("P6\n2 2\n255\n");
  assertEquals(ppm.length, header.length + 12);
  assertEquals(
    Array.from(ppm.slice(0, header.length)).join(","),
    Array.from(header).join(","),
  );

  const rgb = Array.from(ppm.slice(header.length));
  assertEquals(
    rgb.join(","),
    [
      0,
      0,
      255,
      255,
      255,
      255, // top row first: blue, white
      255,
      0,
      0,
      0,
      255,
      0, // bottom row second: red, green
    ].join(","),
  );
});

Deno.test("cropRgbaColumns slices terminal-column ranges without flipping WebGL rows", () => {
  const width = 8;
  const height = 2;
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      data[i] = x;
      data[i + 1] = y;
      data[i + 2] = 100;
      data[i + 3] = 255;
    }
  }

  const crop = cropRgbaColumns(data, width, height, 4, 1, 2);

  assertEquals(crop.pixelWidth, 4);
  assertEquals(crop.data.length, 4 * height * 4);
  assertEquals(crop.data[0], 2);
  assertEquals(crop.data[4], 3);
  assertEquals(crop.data[8], 4);
  assertEquals(crop.data[12], 5);
  assertEquals(crop.data[4 * 4], 2);
  assertEquals(crop.data[4 * 4 + 1], 1);
});

Deno.test("sanitizeChafaAnsi removes cursor visibility controls and one trailing newline", () => {
  const ansi = "\x1b[?25l\x1b[38;2;1;2;3m█\nnext\n\x1b[?25h";
  assertEquals(sanitizeChafaAnsi(ansi + "\n"), "\x1b[38;2;1;2;3m█\nnext\n");
});
