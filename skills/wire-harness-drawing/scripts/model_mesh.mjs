// Convert a connector's STEP or IGES model into the compact mesh the harness explorer draws.
//
// Usage: node model_mesh.mjs <model.step> <mesh.json> [--max-triangles N] [--converter DIR]
//
// The model is tessellated by occt-import-js (OpenCascade compiled to WebAssembly, LGPL-2.1),
// which is not bundled: it is installed once into the converter directory (default
// ~/.cache/wire-harness-drawing/converter) with `npm install occt-import-js`. The tessellation
// tolerance starts fine, relative to the model's size, and is coarsened until the mesh is
// within the triangle cap. Positions are quantised to 16 bits across the model's bounds; the
// mesh is written with its colours as a small palette.
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

const defaultConverter = join(homedir(), ".cache", "wire-harness-drawing", "converter");

function option(argv, name, fallback) {
  const index = argv.indexOf(name);
  return index >= 0 ? argv[index + 1] : fallback;
}

// The meshes of one tessellation, merged into one list of triangles with a colour each.
function merge(result) {
  const positions = [], colors = [], indices = [];
  for (const mesh of result.meshes) {
    const base = positions.length / 3;
    positions.push(...mesh.attributes.position.array);
    const faceColors = new Array(mesh.index.array.length / 3).fill(mesh.color ?? [0.6, 0.6, 0.6]);
    for (const face of mesh.brep_faces ?? []) {
      if (face.color) for (let t = face.first; t <= face.last; t++) faceColors[t] = face.color;
    }
    for (let t = 0; t < mesh.index.array.length / 3; t++) {
      indices.push(base + mesh.index.array[3 * t], base + mesh.index.array[3 * t + 1], base + mesh.index.array[3 * t + 2]);
      colors.push(faceColors[t]);
    }
  }
  return { positions, colors, indices };
}

// Quantise positions to 16 bits across the bounds, and colours to a palette of 8-bit RGB.
function encode({ positions, colors, indices }) {
  const min = [0, 1, 2].map((axis) => Math.min(...positions.filter((_, i) => i % 3 === axis)));
  const max = [0, 1, 2].map((axis) => Math.max(...positions.filter((_, i) => i % 3 === axis)));
  const quantised = new Uint16Array(positions.length);
  positions.forEach((value, i) => {
    const axis = i % 3, span = max[axis] - min[axis] || 1;
    quantised[i] = Math.round(((value - min[axis]) / span) * 65535);
  });
  const palette = [], triangleColors = new Uint8Array(colors.length);
  colors.forEach((color, t) => {
    const rgb = color.map((value) => Math.round(Math.min(Math.max(value, 0), 1) * 255));
    let index = palette.findIndex((entry) => entry.every((value, k) => value === rgb[k]));
    if (index < 0) { index = palette.length; palette.push(rgb); }
    triangleColors[t] = Math.min(index, 255);
  });
  const indexArray = positions.length / 3 > 65535 ? new Uint32Array(indices) : new Uint16Array(indices);
  const base64 = (array) => Buffer.from(array.buffer, array.byteOffset, array.byteLength).toString("base64");
  return {
    format: "wire-harness-mesh/1", units: "mm", min: min.map((v) => +v.toFixed(4)), max: max.map((v) => +v.toFixed(4)),
    triangles: indices.length / 3, palette, positions: base64(quantised), indices: base64(indexArray),
    index_bytes: indexArray.BYTES_PER_ELEMENT, triangle_colors: base64(triangleColors),
  };
}

async function main(argv) {
  const [input, output] = argv;
  if (!input || !output) {
    console.error("usage: node model_mesh.mjs <model.step> <mesh.json> [--max-triangles N] [--converter DIR]");
    return 2;
  }
  const maxTriangles = Number(option(argv, "--max-triangles", 8000));
  const converter = resolve(option(argv, "--converter", process.env.WIRE_HARNESS_CONVERTER || defaultConverter));
  let occtFactory;
  try {
    occtFactory = createRequire(join(converter, "package.json"))("occt-import-js");
  } catch {
    console.error(`occt-import-js is not installed in ${converter}; run: npm install --prefix "${converter}" occt-import-js`);
    return 3;
  }
  const occt = await occtFactory();
  const content = new Uint8Array(readFileSync(input));
  const read = /\.ige?s$/i.test(input) ? occt.ReadIgesFile : occt.ReadStepFile;
  let deflection = 0.002, merged = null;
  for (let attempt = 0; attempt < 8; attempt++, deflection *= 2) {
    const result = read(content, { linearUnit: "millimeter", linearDeflectionType: "bounding_box_ratio",
      linearDeflection: deflection, angularDeflection: 0.35 + attempt * 0.15 });
    if (!result.success || !result.meshes.length) {
      console.error(`could not read ${input}`);
      return 1;
    }
    merged = merge(result);
    if (merged.indices.length / 3 <= maxTriangles) break;
  }
  if (merged.indices.length / 3 > maxTriangles) {
    console.error(`${input}: ${merged.indices.length / 3} triangles even at the coarsest tolerance; cap is ${maxTriangles}`);
    return 1;
  }
  writeFileSync(output, JSON.stringify(encode(merged)));
  return 0;
}

process.exitCode = await main(process.argv.slice(2));
