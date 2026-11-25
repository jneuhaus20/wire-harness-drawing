// <wire-harness-explorer> 1.0.0 — an interactive 2D/3D view of one wire harness.
//
// One self-contained ES module with no dependencies. Load it once per page, then give each
// element its harness model (the <name>.harness.json the wire-harness-drawing generator
// writes), either as a property (element.harness = model) or as the text of an inline child
// script element of type application/json. This file never spells out a closing script tag,
// so it can itself be inlined in a page.
// Attributes: view="3d" | "2d" (default 3d), theme="light" | "dark" (default: follows the page).
// The component does no I/O: every number it shows comes from the model.

const version = "1.0.0";
const modelFormat = "wire-harness-explorer/1";

// ---------- Vector and matrix helpers (column-major 4×4) ----------

const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const subtract = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const length = (a) => Math.hypot(a[0], a[1], a[2]);
const normalize = (a) => { const l = length(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

function perspective(fieldOfView, aspect, near, far) {
  const f = 1 / Math.tan(fieldOfView / 2);
  const m = new Float32Array(16);
  m[0] = f / aspect; m[5] = f; m[10] = (far + near) / (near - far); m[11] = -1; m[14] = (2 * far * near) / (near - far);
  return m;
}

function lookAt(eye, target, up) {
  const z = normalize(subtract(eye, target));
  const x = normalize(cross(up, z));
  const y = cross(z, x);
  return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0,
    -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]);
}

function multiply(a, b) {
  const m = new Float32Array(16);
  for (let column = 0; column < 4; column++) {
    for (let row = 0; row < 4; row++) {
      let sum = 0;
      for (let k = 0; k < 4; k++) sum += a[k * 4 + row] * b[column * 4 + k];
      m[column * 4 + row] = sum;
    }
  }
  return m;
}

function transformPoint(m, p) {
  const x = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
  const y = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
  const z = m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14];
  const w = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
  return [x / w, y / w, z / w];
}

function invert(m) {
  const inv = new Float32Array(16);
  inv[0] = m[5] * m[10] * m[15] - m[5] * m[11] * m[14] - m[9] * m[6] * m[15] + m[9] * m[7] * m[14] + m[13] * m[6] * m[11] - m[13] * m[7] * m[10];
  inv[4] = -m[4] * m[10] * m[15] + m[4] * m[11] * m[14] + m[8] * m[6] * m[15] - m[8] * m[7] * m[14] - m[12] * m[6] * m[11] + m[12] * m[7] * m[10];
  inv[8] = m[4] * m[9] * m[15] - m[4] * m[11] * m[13] - m[8] * m[5] * m[15] + m[8] * m[7] * m[13] + m[12] * m[5] * m[11] - m[12] * m[7] * m[9];
  inv[12] = -m[4] * m[9] * m[14] + m[4] * m[10] * m[13] + m[8] * m[5] * m[14] - m[8] * m[6] * m[13] - m[12] * m[5] * m[10] + m[12] * m[6] * m[9];
  inv[1] = -m[1] * m[10] * m[15] + m[1] * m[11] * m[14] + m[9] * m[2] * m[15] - m[9] * m[3] * m[14] - m[13] * m[2] * m[11] + m[13] * m[3] * m[10];
  inv[5] = m[0] * m[10] * m[15] - m[0] * m[11] * m[14] - m[8] * m[2] * m[15] + m[8] * m[3] * m[14] + m[12] * m[2] * m[11] - m[12] * m[3] * m[10];
  inv[9] = -m[0] * m[9] * m[15] + m[0] * m[11] * m[13] + m[8] * m[1] * m[15] - m[8] * m[3] * m[13] - m[12] * m[1] * m[11] + m[12] * m[3] * m[9];
  inv[13] = m[0] * m[9] * m[14] - m[0] * m[10] * m[13] - m[8] * m[1] * m[14] + m[8] * m[2] * m[13] + m[12] * m[1] * m[10] - m[12] * m[2] * m[9];
  inv[2] = m[1] * m[6] * m[15] - m[1] * m[7] * m[14] - m[5] * m[2] * m[15] + m[5] * m[3] * m[14] + m[13] * m[2] * m[7] - m[13] * m[3] * m[6];
  inv[6] = -m[0] * m[6] * m[15] + m[0] * m[7] * m[14] + m[4] * m[2] * m[15] - m[4] * m[3] * m[14] - m[12] * m[2] * m[7] + m[12] * m[3] * m[6];
  inv[10] = m[0] * m[5] * m[15] - m[0] * m[7] * m[13] - m[4] * m[1] * m[15] + m[4] * m[3] * m[13] + m[12] * m[1] * m[7] - m[12] * m[3] * m[5];
  inv[14] = -m[0] * m[5] * m[14] + m[0] * m[6] * m[13] + m[4] * m[1] * m[14] - m[4] * m[2] * m[13] - m[12] * m[1] * m[6] + m[12] * m[2] * m[5];
  inv[3] = -m[1] * m[6] * m[11] + m[1] * m[7] * m[10] + m[5] * m[2] * m[11] - m[5] * m[3] * m[10] - m[9] * m[2] * m[7] + m[9] * m[3] * m[6];
  inv[7] = m[0] * m[6] * m[11] - m[0] * m[7] * m[10] - m[4] * m[2] * m[11] + m[4] * m[3] * m[10] + m[8] * m[2] * m[7] - m[8] * m[3] * m[6];
  inv[11] = -m[0] * m[5] * m[11] + m[0] * m[7] * m[9] + m[4] * m[1] * m[11] - m[4] * m[3] * m[9] - m[8] * m[1] * m[7] + m[8] * m[3] * m[5];
  inv[15] = m[0] * m[5] * m[10] - m[0] * m[6] * m[9] - m[4] * m[1] * m[10] + m[4] * m[2] * m[9] + m[8] * m[1] * m[6] - m[8] * m[2] * m[5];
  const determinant = m[0] * inv[0] + m[1] * inv[4] + m[2] * inv[8] + m[3] * inv[12];
  for (let i = 0; i < 16; i++) inv[i] /= determinant;
  return inv;
}

function hexToRgb(hex) {
  const value = parseInt(hex.slice(1), 16);
  return [((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255];
}

// ---------- Geometry from the model ----------

// The bundle paths in the model are SVG path data of M, L and C commands; sample them into
// polylines so both views draw the same route.
function samplePath(pathData) {
  const tokens = pathData.match(/[MLC]|-?\d+(?:\.\d+)?/g);
  const points = [];
  let index = 0;
  let current = [0, 0];
  while (index < tokens.length) {
    const command = tokens[index++];
    if (command === "M" || command === "L") {
      current = [parseFloat(tokens[index++]), parseFloat(tokens[index++])];
      points.push(current);
    } else if (command === "C") {
      const c1 = [parseFloat(tokens[index++]), parseFloat(tokens[index++])];
      const c2 = [parseFloat(tokens[index++]), parseFloat(tokens[index++])];
      const end = [parseFloat(tokens[index++]), parseFloat(tokens[index++])];
      const start = current;
      for (let step = 1; step <= 24; step++) {
        const t = step / 24, u = 1 - t;
        points.push([
          u * u * u * start[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t * t * t * end[0],
          u * u * u * start[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t * t * t * end[1],
        ]);
      }
      current = end;
    }
  }
  return points;
}

// Wires in a bundle pack in hexagonal rings around its centre: one, then six, then twelve.
function packingOffsets(count, pitch) {
  const offsets = [[0, 0]];
  for (let ring = 1; offsets.length < count; ring++) {
    for (let k = 0; k < 6 * ring && offsets.length < count; k++) {
      const angle = (2 * Math.PI * k) / (6 * ring);
      offsets.push([Math.cos(angle) * ring * pitch, Math.sin(angle) * ring * pitch]);
    }
  }
  return offsets;
}

// Sizes of what the 3D view draws. The schematic layout is in drawing units, not millimetres,
// so there wires and bodies take the drawing's proportions; otherwise a metre of harness would
// frame as a hairline. A routed harness is in true units, so it gets nominal true sizes in mm.
function sceneSizes(model) {
  if (model.geometry === "schematic") {
    return { wire: 3, pitch: 6.4, bodyLength: 64, bodyHeight: 26, bodyWidth: (pins) => Math.min(110, Math.max(44, 8 + pins * 3.2)),
             splice: 22, breakout: 7 };
  }
  const unit = model.units === "in" ? 1 / 25.4 : 1;
  return { wire: 0.9 * unit, pitch: 2 * unit, bodyLength: 30 * unit, bodyHeight: 10 * unit,
           bodyWidth: (pins) => Math.min(60, Math.max(10, 4 + pins * 2.5)) * unit, splice: 8 * unit, breakout: 2.5 * unit };
}

// The 3D scene in model units: the sheet's placement laid on a table (x across, z toward the
// viewer, y up). Each wire runs as its own tube along its route, offset within each segment's
// bundle; each connector is a body beyond its node, pointing away from its bundle.
function buildScene(model) {
  const sizes = sceneSizes(model);
  const routed = model.geometry !== "schematic";
  const positions = {};
  const connectors = Object.fromEntries(model.connectors.map((connector) => [connector.id, connector]));
  const segmentByKey = new Map();
  const segments = model.segments.map((segment) => ({ ...segment }));
  for (const segment of segments) {
    const polyline = routed ? segment.points : samplePath(segment.path).map(([x, y]) => [x, 0, y]);
    const ordered = [...segment.wires].sort((a, b) => cableOf(model, a).localeCompare(cableOf(model, b)));
    const offsets = packingOffsets(ordered.length, sizes.pitch);
    segment.offsets = Object.fromEntries(ordered.map((wireId, index) => [wireId, offsets[index]]));
    segment.polyline = routed ? densify(polyline, sizes.pitch * 4) : polyline;
    segmentByKey.set(`${segment.nodes[0]}|${segment.nodes[1]}`, segment);
    positions[segment.nodes[0]] = polyline[0];
    positions[segment.nodes[1]] = polyline[polyline.length - 1];
  }
  const wires = model.wires.map((wire) => {
    const points = [];
    for (let i = 0; i + 1 < wire.route.length; i++) {
      const forward = segmentByKey.get(`${wire.route[i]}|${wire.route[i + 1]}`);
      const segment = forward || segmentByKey.get(`${wire.route[i + 1]}|${wire.route[i]}`);
      const centre = forward ? segment.polyline : [...segment.polyline].reverse();
      const [side, up] = segment.offsets[wire.id] || [0, 0];
      const flip = forward ? 1 : -1;
      const offsetLine = offsetPolyline(centre, side * flip, up);
      const trimmed = i === 0 ? offsetLine : offsetLine.slice(1);
      points.push(...trimmed);
    }
    return { wire, points, colors: wire.colors.length ? wire.colors.map(hexToRgb) : [[0.62, 0.62, 0.62]] };
  });
  const bodies = model.nodes.filter((node) => node.kind !== "breakout")
    .map((node) => connectorBody(segments, positions[node.id], connectors[node.id], sizes));
  const breakouts = model.nodes.filter((node) => node.kind === "breakout").map((node) => positions[node.id]);
  const points = wires.flatMap((wire) => wire.points);
  const bounds = [0, 1, 2].map((axis) => [Math.min(...points.map((p) => p[axis])), Math.max(...points.map((p) => p[axis]))]);
  return { wires, bodies, breakouts, sizes, bounds, segments, positions };
}

// Round a route's corners so tubes bend instead of folding: each corner is replaced by a short
// arc-like run of points no tighter than the given radius allows.
function densify(points, radius) {
  if (points.length < 3) return points;
  const out = [points[0]];
  for (let i = 1; i + 1 < points.length; i++) {
    const before = points[i - 1], corner = points[i], after = points[i + 1];
    const into = length(subtract(corner, before)), outOf = length(subtract(after, corner));
    const reach = Math.min(radius, into / 2, outOf / 2);
    const start = add(corner, scale(normalize(subtract(before, corner)), reach));
    const end = add(corner, scale(normalize(subtract(after, corner)), reach));
    for (let step = 0; step <= 8; step++) {
      const t = step / 8, u = 1 - t;
      out.push(add(add(scale(start, u * u), scale(corner, 2 * u * t)), scale(end, t * t)));
    }
  }
  out.push(points[points.length - 1]);
  return out;
}

function cableOf(model, wireId) {
  return (model.wires.find((wire) => wire.id === wireId) || {}).cable || "";
}

function offsetPolyline(points, side, up) {
  return points.map((point, index) => {
    const before = points[Math.max(index - 1, 0)];
    const after = points[Math.min(index + 1, points.length - 1)];
    const tangent = normalize(subtract(after, before));
    const sideways = normalize(cross([0, 1, 0], tangent));
    return add(add(point, scale(sideways, side)), [0, up, 0]);
  });
}

// The 2D view: the sheet's placement with every wire drawn as its own coloured line, the wires
// of a segment side by side (cable members together), and connectors, splices and breakouts as
// the drawing shows them. Nothing around the harness is drawn; the popovers carry the detail.
const planPitch = 2.6;

function buildPlan(model) {
  const scene = buildScene({ ...model, geometry: "schematic" });
  const segmentByKey = new Map(scene.segments.map((segment) => [`${segment.nodes[0]}|${segment.nodes[1]}`, segment]));
  const wires = model.wires.map((wire) => {
    const points = [];
    for (let i = 0; i + 1 < wire.route.length; i++) {
      const forward = segmentByKey.get(`${wire.route[i]}|${wire.route[i + 1]}`);
      const segment = forward || segmentByKey.get(`${wire.route[i + 1]}|${wire.route[i]}`);
      const order = Object.keys(segment.offsets);
      const side = (order.indexOf(wire.id) - (order.length - 1) / 2) * planPitch * (forward ? 1 : -1);
      const centre = forward ? segment.polyline : [...segment.polyline].reverse();
      const line = offsetPolyline(centre, side, 0).map(([x, , z]) => [x, z]);
      points.push(...(i === 0 ? line : line.slice(1)));
    }
    return { wire, points };
  });
  return { wires, bodies: scene.bodies, nodes: model.nodes, segments: scene.segments };
}

function planSvg(model, plan) {
  const xs = model.nodes.map((node) => node.x), ys = model.nodes.map((node) => node.y);
  const margin = 90;
  const box = [Math.min(...xs) - margin, Math.min(...ys) - margin, Math.max(...xs) - Math.min(...xs) + 2 * margin,
    Math.max(...ys) - Math.min(...ys) + 2 * margin];
  const parts = [];
  for (const segment of plan.segments) {
    const width = 4 + 2.6 * Math.max(segment.wires.length, 1);
    parts.push(`<path d="${segment.path}" fill="none" stroke="var(--line)" stroke-width="${width}" stroke-linecap="round"/>`);
  }
  for (const { wire, points } of plan.wires) {
    const d = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const [base, stripe] = wire.colors.length ? wire.colors : ["var(--muted)"];
    const dashed = wire.colors.length ? "" : ' stroke-dasharray="6 4"';
    parts.push(`<g class="wire" data-wire="${escapeHtml(wire.id)}"><path d="${d}" fill="none" stroke="transparent" stroke-width="9"/>
      <path d="${d}" fill="none" stroke="${base}" stroke-width="2"${dashed}/>${stripe ? `<path d="${d}" fill="none" stroke="${stripe}" stroke-width="2" stroke-dasharray="4 4"/>` : ""}</g>`);
  }
  for (const segment of plan.segments) {
    const points = segment.polyline;
    const [x, , z] = points[Math.floor(points.length / 2)];
    const unknown = segment.known ? "" : ' font-style="italic"';
    parts.push(`<text x="${x.toFixed(1)}" y="${(z + 14 + 1.3 * Math.max(segment.wires.length, 1)).toFixed(1)}" text-anchor="middle" class="length"${unknown}>${escapeHtml(segment.length)}</text>`);
  }
  for (const node of plan.nodes.filter((n) => n.kind === "breakout")) {
    parts.push(`<circle cx="${node.x}" cy="${node.y}" r="4.5" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.2"/>`);
  }
  for (const body of plan.bodies) {
    const id = escapeHtml(body.connector.id);
    const [cx, , cz] = body.centre;
    if (body.kind === "splice") {
      parts.push(`<g class="connector" data-connector="${id}"><rect x="${cx - 8}" y="${cz - 8}" width="16" height="16" fill="var(--panel)" stroke="var(--ink)" transform="rotate(45 ${cx} ${cz})"/>
        <text x="${cx}" y="${cz - 16}" text-anchor="middle" class="name">${id}</text></g>`);
      continue;
    }
    const angle = (Math.atan2(body.axis[2], body.axis[0]) * 180) / Math.PI;
    const [bodyLength, , bodyWidth] = body.size;
    const generic = body.connector.generic;
    const round = body.connector.shape === "circular" ? 12 : 3;
    parts.push(`<g class="connector" data-connector="${id}"><rect x="${cx - bodyLength / 2}" y="${cz - bodyWidth / 2}" width="${bodyLength}" height="${bodyWidth}" rx="${round}"
      fill="${generic ? "var(--ground)" : "var(--panel)"}" stroke="var(--ink)" stroke-width="1.2"${generic ? ' stroke-dasharray="5 3"' : ""} transform="rotate(${angle.toFixed(1)} ${cx} ${cz})"/>
      <text x="${cx}" y="${cz + bodyWidth / 2 + 16}" text-anchor="middle" class="name">${id}</text></g>`);
  }
  return `<svg class="plan" role="img" aria-label="2D layout of the ${escapeHtml(model.title)} harness" viewBox="${box.join(" ")}"
    preserveAspectRatio="xMidYMid meet">${parts.join("")}</svg>`;
}

// A connector body sits beyond its node, along the direction its bundle arrives in; a splice
// sits on its node.
function connectorBody(segments, centre, connector, sizes) {
  if (connector.splice) return { connector, kind: "splice", centre, axis: [1, 0, 0], size: [sizes.splice, sizes.splice, sizes.splice] };
  const segment = segments.find((s) => s.nodes.includes(connector.id));
  const polyline = segment ? segment.polyline : [centre, add(centre, [1, 0, 0])];
  const atStart = segment && segment.nodes[0] === connector.id;
  const near = atStart ? polyline[0] : polyline[polyline.length - 1];
  const inner = atStart ? polyline[1] : polyline[polyline.length - 2];
  const axis = normalize(subtract(near, inner));
  const width = sizes.bodyWidth(connector.pins.length);
  return { connector, kind: "connector", centre: add(near, scale(axis, sizes.bodyLength / 2)), axis,
           size: [sizes.bodyLength, connector.shape === "circular" ? width : sizes.bodyHeight, width] };
}

// ---------- Meshes ----------

function tubeMesh(points, radius, sides, color) {
  const positions = [], normals = [], colors = [], indices = [];
  let normal = normalize(cross(subtract(points[1], points[0]), [0, 1, 0]));
  if (!isFinite(normal[0]) || length(normal) < 0.5) normal = [0, 0, 1];
  for (let i = 0; i < points.length; i++) {
    const tangent = normalize(subtract(points[Math.min(i + 1, points.length - 1)], points[Math.max(i - 1, 0)]));
    normal = normalize(subtract(normal, scale(tangent, dot(normal, tangent))));
    const binormal = cross(tangent, normal);
    for (let k = 0; k < sides; k++) {
      const angle = (2 * Math.PI * k) / sides;
      const direction = add(scale(normal, Math.cos(angle)), scale(binormal, Math.sin(angle)));
      positions.push(...add(points[i], scale(direction, radius)));
      normals.push(...direction);
      colors.push(...(typeof color === "function" ? color(i, k) : color));
    }
  }
  for (let i = 0; i + 1 < points.length; i++) {
    for (let k = 0; k < sides; k++) {
      const a = i * sides + k, b = i * sides + ((k + 1) % sides), c = a + sides, d = b + sides;
      indices.push(a, c, b, b, c, d);
    }
  }
  return { positions, normals, colors, indices };
}

function boxMesh(centre, axis, size, color) {
  const x = axis, y = [0, 1, 0], z = normalize(cross(x, y));
  const half = [size[0] / 2, size[1] / 2, size[2] / 2];
  const faces = [[x, y, z], [scale(x, -1), y, scale(z, -1)], [y, z, x], [scale(y, -1), x, z], [z, x, y], [scale(z, -1), y, x]];
  const extent = (direction) => Math.abs(dot(direction, x)) * half[0] + Math.abs(dot(direction, y)) * half[1] + Math.abs(dot(direction, z)) * half[2];
  const positions = [], normals = [], colors = [], indices = [];
  for (const [n, u, v] of faces) {
    const base = positions.length / 3;
    const centreOfFace = add(centre, scale(n, extent(n)));
    const eu = extent(u), ev = extent(v);
    for (const [su, sv] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
      positions.push(...add(centreOfFace, add(scale(u, su * eu), scale(v, sv * ev))));
      normals.push(...n);
      colors.push(...color);
    }
    indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
  }
  return { positions, normals, colors, indices };
}

function mergeMeshes(meshes) {
  const merged = { positions: [], normals: [], colors: [], indices: [] };
  for (const mesh of meshes) {
    const base = merged.positions.length / 3;
    merged.positions.push(...mesh.positions);
    merged.normals.push(...mesh.normals);
    merged.colors.push(...mesh.colors);
    for (const index of mesh.indices) merged.indices.push(base + index);
  }
  return merged;
}

// ---------- WebGL renderer ----------

const vertexShader = `
attribute vec3 position; attribute vec3 normal; attribute vec3 color;
uniform mat4 viewProjection; varying vec3 vNormal; varying vec3 vColor; varying vec3 vPosition;
void main() { vNormal = normal; vColor = color; vPosition = position; gl_Position = viewProjection * vec4(position, 1.0); }`;

// Matte shading: a sky/ground hemisphere fill, one key light from above and in front, and a
// faint highlight so tube curvature reads. While something is selected it is mixed toward
// the highlight colour and everything else fades toward grey.
const fragmentShader = `
precision mediump float;
varying vec3 vNormal; varying vec3 vColor; varying vec3 vPosition;
uniform vec3 eye; uniform vec3 tint; uniform float tintAmount; uniform float dimAmount; uniform float alpha;
void main() {
  vec3 n = normalize(vNormal);
  vec3 key = normalize(vec3(-0.35, 0.85, 0.4));
  float hemisphere = 0.5 + 0.5 * n.y;
  vec3 base = mix(mix(vColor, vec3(0.52), dimAmount), tint, tintAmount);
  vec3 lit = base * (0.32 + 0.22 * hemisphere + 0.62 * max(dot(n, key), 0.0));
  vec3 view = normalize(eye - vPosition);
  float highlight = pow(max(dot(n, normalize(key + view)), 0.0), 40.0) * 0.22;
  gl_FragColor = vec4(pow(lit + highlight, vec3(1.0 / 1.1)), alpha);
}`;

class Renderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext("webgl", { antialias: true, alpha: true, premultipliedAlpha: false });
    if (!this.gl) return;
    const gl = this.gl;
    this.uintIndices = !!gl.getExtension("OES_element_index_uint");
    const program = gl.createProgram();
    for (const [type, source] of [[gl.VERTEX_SHADER, vertexShader], [gl.FRAGMENT_SHADER, fragmentShader]]) {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      gl.attachShader(program, shader);
    }
    gl.linkProgram(program);
    this.program = program;
    this.location = Object.fromEntries(["position", "normal", "color"].map((name) => [name, gl.getAttribLocation(program, name)]));
    this.uniform = Object.fromEntries(["viewProjection", "eye", "tint", "tintAmount", "dimAmount", "alpha"].map((name) => [name, gl.getUniformLocation(program, name)]));
    this.meshes = [];
  }

  upload(id, mesh, alpha = 1) {
    const gl = this.gl;
    const buffer = (data, target = gl.ARRAY_BUFFER) => {
      const handle = gl.createBuffer();
      gl.bindBuffer(target, handle);
      gl.bufferData(target, data, gl.STATIC_DRAW);
      return handle;
    };
    const large = mesh.positions.length / 3 > 65535;
    this.meshes.push({
      id, alpha, count: mesh.indices.length, indexType: large ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT,
      position: buffer(new Float32Array(mesh.positions)), normal: buffer(new Float32Array(mesh.normals)),
      color: buffer(new Float32Array(mesh.colors)),
      index: buffer(large ? new Uint32Array(mesh.indices) : new Uint16Array(mesh.indices), gl.ELEMENT_ARRAY_BUFFER),
    });
  }

  clear() {
    for (const mesh of this.meshes) for (const key of ["position", "normal", "color", "index"]) this.gl.deleteBuffer(mesh[key]);
    this.meshes = [];
  }

  draw(viewProjection, eye, selected, highlight) {
    const gl = this.gl;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(this.program);
    gl.uniformMatrix4fv(this.uniform.viewProjection, false, viewProjection);
    gl.uniform3fv(this.uniform.eye, eye);
    gl.uniform3fv(this.uniform.tint, highlight);
    const shown = (mesh) => (selected.size && !selected.has(mesh.id) ? mesh.alpha * 0.45 : mesh.alpha);
    const ordered = [...this.meshes].sort((a, b) => shown(b) - shown(a));
    for (const mesh of ordered) {
      gl.depthMask(shown(mesh) >= 1);
      const isSelected = selected.has(mesh.id);
      gl.uniform1f(this.uniform.alpha, shown(mesh));
      gl.uniform1f(this.uniform.tintAmount, isSelected ? 0.35 : 0);
      gl.uniform1f(this.uniform.dimAmount, selected.size && !isSelected ? 0.7 : 0);
      for (const name of ["position", "normal", "color"]) {
        gl.bindBuffer(gl.ARRAY_BUFFER, mesh[name]);
        gl.enableVertexAttribArray(this.location[name]);
        gl.vertexAttribPointer(this.location[name], 3, gl.FLOAT, false, 0, 0);
      }
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mesh.index);
      gl.drawElements(gl.TRIANGLES, mesh.count, mesh.indexType, 0);
    }
    gl.depthMask(true);
  }
}

// ---------- Picking ----------

// Distance from a ray to a line segment, and where along the ray it is closest.
function raySegmentDistance(origin, direction, a, b) {
  const u = subtract(b, a), w = subtract(origin, a);
  const aa = dot(direction, direction), bb = dot(direction, u), cc = dot(u, u), dd = dot(direction, w), ee = dot(u, w);
  const denominator = aa * cc - bb * bb;
  let s = denominator > 1e-9 ? (bb * ee - cc * dd) / denominator : 0;
  let t = denominator > 1e-9 ? (aa * ee - bb * dd) / denominator : ee / cc;
  t = Math.min(Math.max(t, 0), 1);
  s = Math.max((bb * t - dd) / aa, 0);
  const closest = subtract(add(origin, scale(direction, s)), add(a, scale(u, t)));
  return { distance: length(closest), along: s };
}

function rayBox(origin, direction, body) {
  const x = body.axis, y = [0, 1, 0], z = normalize(cross(x, y));
  const local = subtract(origin, body.centre);
  const o = [dot(local, x), dot(local, y), dot(local, z)];
  const d = [dot(direction, x), dot(direction, y), dot(direction, z)];
  let near = -Infinity, far = Infinity;
  for (let i = 0; i < 3; i++) {
    const half = body.size[i] / 2;
    if (Math.abs(d[i]) < 1e-9) { if (Math.abs(o[i]) > half) return null; continue; }
    let t1 = (-half - o[i]) / d[i], t2 = (half - o[i]) / d[i];
    if (t1 > t2) [t1, t2] = [t2, t1];
    near = Math.max(near, t1); far = Math.min(far, t2);
    if (near > far) return null;
  }
  return far < 0 ? null : Math.max(near, 0);
}

// ---------- Styles ----------

const styles = `
:host [hidden] { display: none !important; }
:host { --ground: #f6f5f2; --panel: #ffffff; --ink: #1d1d1b; --muted: #6b6a66; --line: #d9d7d0; --accent: #2457d6;
  --select: #ffb000; display: block; position: relative; font-family: "IBM Plex Sans", system-ui, sans-serif; color: var(--ink);
  container-type: inline-size; }
:host([theme="dark"]) { --ground: #17181a; --panel: #222327; --ink: #ecebe6; --muted: #a2a19b; --line: #3a3b40; --accent: #7aa2ff; }
@media (prefers-color-scheme: dark) { :host(:not([theme="light"])) { --ground: #17181a; --panel: #222327; --ink: #ecebe6;
  --muted: #a2a19b; --line: #3a3b40; --accent: #7aa2ff; } }
.frame { background: var(--ground); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
header { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: baseline; justify-content: space-between; padding: 12px 14px 8px; }
.eyebrow { font: 500 11px/1.3 "IBM Plex Mono", ui-monospace, monospace; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.title { font: 600 17px/1.25 "IBM Plex Sans Condensed", "IBM Plex Sans", system-ui, sans-serif; margin: 2px 0 0; }
.views { display: flex; gap: 4px; }
button { font: 500 12px "IBM Plex Mono", ui-monospace, monospace; color: var(--ink); background: var(--panel); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 10px; cursor: pointer; }
button[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }
button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.stage { position: relative; height: min(62vh, 560px); touch-action: none; }
@container (max-width: 520px) { .stage { height: min(56vh, 420px); } }
canvas, svg.plan { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.labels { position: absolute; inset: 0; pointer-events: none; }
.tag { position: absolute; transform: translate(-50%, -140%); font: 600 11px "IBM Plex Mono", ui-monospace, monospace; color: var(--ink);
  background: color-mix(in srgb, var(--panel) 82%, transparent); border: 1px solid var(--line); border-radius: 4px; padding: 1px 5px; white-space: nowrap; }
.tag.generic { border-style: dashed; }
footer { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 14px; padding: 8px 14px 11px; font-size: 12px; color: var(--muted); }
.mono { font-family: "IBM Plex Mono", ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.popover { position: absolute; z-index: 2; background: var(--panel); color: var(--ink); border: 1px solid var(--line); border-radius: 8px;
  box-shadow: 0 6px 24px rgba(0,0,0,.18); padding: 8px 10px; font-size: 12px; max-width: min(92%, 460px); }
.popover h3 { margin: 0 0 6px; font: 600 12px "IBM Plex Mono", ui-monospace, monospace; letter-spacing: .03em; }
.popover table { border-collapse: collapse; font: 12px "IBM Plex Mono", ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.popover th { text-align: left; font-weight: 600; color: var(--muted); text-transform: uppercase; font-size: 10px; letter-spacing: .05em; }
.popover th, .popover td { padding: 2px 8px 2px 0; border-bottom: 1px solid var(--line); vertical-align: middle; }
.popover tr.lit td { background: color-mix(in srgb, var(--select) 28%, transparent); }
.popover .na { font-style: italic; color: var(--muted); }
.popover.small { padding: 6px; }
.swatch { display: inline-block; width: 18px; height: 8px; border-radius: 4px; border: 1px solid var(--line); vertical-align: middle; }
.close { position: absolute; top: 4px; right: 6px; border: 0; background: none; padding: 2px 4px; color: var(--muted); }
.notice { margin: 0; }
svg.plan text { font-family: "IBM Plex Mono", ui-monospace, monospace; fill: var(--ink); }
svg.plan text.name { font-size: 13px; font-weight: 600; }
svg.plan text.length { font-size: 10px; fill: var(--muted); }
svg.plan .wire, svg.plan .connector { cursor: pointer; }
svg.plan.selecting .wire:not(.lit), svg.plan.selecting .connector:not(.lit) { opacity: .28; }
svg.plan .wire.lit path:nth-child(n+2) { stroke-width: 3.5; }
svg.plan .connector.lit rect { stroke: var(--select); stroke-width: 3; }
`;

// ---------- The element ----------

// Outside a browser (in tests) there is no HTMLElement; the element class still loads so the
// pure functions above can be exercised.
class WireHarnessExplorer extends (globalThis.HTMLElement ?? class {}) {
  static get observedAttributes() { return ["view"]; }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._model = null;
    this._selected = new Set();
    this._camera = { yaw: -0.5, pitch: 0.95, distance: 1, target: [0, 0, 0] };
  }

  set harness(model) { this._model = model; this._render(); }
  get harness() { return this._model; }

  connectedCallback() {
    if (!this._model) {
      const inline = this.querySelector('script[type="application/json"]');
      if (inline) this._model = JSON.parse(inline.textContent);
    }
    this._render();
  }

  disconnectedCallback() {
    this._resizeObserver?.disconnect();
    this._visibility?.disconnect();
  }

  attributeChangedCallback() { if (this._stage) this._showView(); }

  get view() { return this.getAttribute("view") === "2d" ? "2d" : "3d"; }

  _render() {
    if (!this.isConnected || !this._model) return;
    const model = this._model;
    if (model.format !== modelFormat) {
      this.shadowRoot.innerHTML = `<p>wire-harness-explorer ${version} cannot read a model of format ${escapeHtml(String(model.format))}.</p>`;
      return;
    }
    this.shadowRoot.innerHTML = `<style>${styles}</style>
      <div class="frame">
        <header>
          <div><div class="eyebrow">${escapeHtml(model.number)} · ${model.wires.length} wires · rev ${escapeHtml(model.rev)}</div>
            <p class="title">${escapeHtml(model.title)}</p></div>
          <div class="views" role="group" aria-label="View">
            <button data-view="3d">3D</button><button data-view="2d">2D</button><button data-reset>Reset view</button>
          </div>
        </header>
        <div class="stage"><canvas role="img" aria-label="3D view of the ${escapeHtml(model.title)} harness"></canvas>
          <div class="labels"></div><div class="planHolder"></div></div>
        <footer><p class="notice"></p><span class="mono help"></span></footer>
      </div>`;
    this._stage = this.shadowRoot.querySelector(".stage");
    this._canvas = this.shadowRoot.querySelector("canvas");
    this._labels = this.shadowRoot.querySelector(".labels");
    this.shadowRoot.querySelector(".notice").textContent = model.geometry === "schematic"
      ? "No routing geometry given: the 3D view lays the drawing's layout flat. Not to scale."
      : `Routed as specified, in ${model.geometry.toUpperCase()}. Wires and bodies are drawn at nominal size.`;
    for (const button of this.shadowRoot.querySelectorAll("[data-view]")) {
      button.addEventListener("click", () => this.setAttribute("view", button.dataset.view));
    }
    this.shadowRoot.querySelector("[data-reset]").addEventListener("click", () => { this._frame(); this._draw(); });
    this._scene = buildScene(model);
    this._plan = buildPlan(model);
    this._planHolder = this.shadowRoot.querySelector(".planHolder");
    this._planHolder.innerHTML = planSvg(model, this._plan);
    this._planSvg = this._planHolder.querySelector("svg");
    this._planSvg.addEventListener("click", (event) => {
      const bounds = this._stage.getBoundingClientRect();
      const wire = event.target.closest("[data-wire]"), connector = event.target.closest("[data-connector]");
      const hit = connector ? { kind: "connector", id: connector.dataset.connector } : wire ? { kind: "wire", id: wire.dataset.wire } : null;
      this._select(hit, event.clientX - bounds.left, event.clientY - bounds.top);
    });
    this._renderer = new Renderer(this._canvas);
    this._uploadScene();
    this._frame();
    this._bindPointer();
    this._resizeObserver = new ResizeObserver(() => this._draw());
    this._resizeObserver.observe(this._stage);
    this._showView();
  }

  _showView() {
    for (const button of this.shadowRoot.querySelectorAll("[data-view]")) {
      button.setAttribute("aria-pressed", String(button.dataset.view === this.view));
    }
    const plan = this.view === "2d";
    this.shadowRoot.querySelector(".help").textContent = plan ? "Click a connector or wire."
      : "Click a connector or wire. Drag to orbit, right-drag or two fingers to pan, scroll or pinch to zoom.";
    this.shadowRoot.querySelector("[data-reset]").hidden = plan;
    this._canvas.hidden = plan;
    this._labels.hidden = plan;
    this._planHolder.hidden = !plan;
    this._select(null);
  }

  _uploadScene() {
    const renderer = this._renderer;
    if (!renderer.gl) return;
    renderer.clear();
    for (const { wire, points, colors } of this._scene.wires) {
      const stripe = colors.length > 1;
      const color = stripe ? (i, k) => (k % 8 < 3 && (i % 6) < 3 ? colors[1] : colors[0]) : colors[0];
      renderer.upload(`wire:${wire.id}`, tubeMesh(points, this._scene.sizes.wire, 10, color));
    }
    for (const body of this._scene.bodies) {
      const generic = body.connector.generic;
      const color = body.kind === "splice" ? [0.55, 0.56, 0.58] : generic ? [0.86, 0.86, 0.84] : [0.3, 0.31, 0.33];
      const mesh = body.connector.shape === "circular" && body.kind === "connector"
        ? tubeMesh([subtract(body.centre, scale(body.axis, body.size[0] / 2)), add(body.centre, scale(body.axis, body.size[0] / 2))],
          body.size[2] / 2, 24, color)
        : boxMesh(body.centre, body.axis, body.size, color);
      renderer.upload(`connector:${body.connector.id}`, mesh, generic ? 0.55 : 1);
    }
    const radius = this._scene.sizes.breakout;
    const nodeMeshes = this._scene.breakouts.map((point) => tubeMesh([add(point, [-radius * 0.6, 0, 0]), add(point, [radius * 0.6, 0, 0])],
      radius, 16, [0.95, 0.95, 0.93]));
    if (nodeMeshes.length) renderer.upload("breakouts", mergeMeshes(nodeMeshes));
  }

  // Frame the whole harness: aim at the centre of its bounding box from far enough away to fit it.
  _frame() {
    const bounds = this._scene.bounds;
    const minimum = bounds.map(([low]) => low), maximum = bounds.map(([, high]) => high);
    this._camera.target = scale(add(minimum, maximum), 0.5);
    this._camera.distance = Math.max(length(subtract(maximum, minimum)), this._scene.sizes.bodyLength * 3) * 0.95;
    this._camera.yaw = -0.35;
    this._camera.pitch = 0.9;
  }

  _matrices() {
    const width = this._stage.clientWidth, height = this._stage.clientHeight;
    const camera = this._camera;
    const eye = add(camera.target, [
      camera.distance * Math.cos(camera.pitch) * Math.sin(camera.yaw),
      camera.distance * Math.sin(camera.pitch),
      camera.distance * Math.cos(camera.pitch) * Math.cos(camera.yaw),
    ]);
    const projection = perspective((35 * Math.PI) / 180, width / Math.max(height, 1), camera.distance / 50, camera.distance * 6);
    return { eye, viewProjection: multiply(projection, lookAt(eye, camera.target, [0, 1, 0])), width, height };
  }

  _draw() {
    if (this._planSvg) {
      this._planSvg.classList.toggle("selecting", this._selected.size > 0);
      for (const element of this._planSvg.querySelectorAll("[data-wire], [data-connector]")) {
        const key = element.dataset.wire ? `wire:${element.dataset.wire}` : `connector:${element.dataset.connector}`;
        element.classList.toggle("lit", this._selected.has(key));
      }
    }
    if (!this._renderer?.gl || !this._stage || this.view === "2d") return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.round(this._stage.clientWidth * ratio), height = Math.round(this._stage.clientHeight * ratio);
    if (this._canvas.width !== width || this._canvas.height !== height) { this._canvas.width = width; this._canvas.height = height; }
    const { eye, viewProjection, width: cssWidth, height: cssHeight } = this._matrices();
    const highlight = hexToRgb(getComputedStyle(this).getPropertyValue("--select").trim() || "#ffb000");
    this._renderer.draw(viewProjection, eye, this._selected, highlight);
    this._labels.replaceChildren(...this._scene.bodies.filter((body) => body.kind === "connector").map((body) => {
      const [x, y, z] = transformPoint(viewProjection, add(body.centre, [0, body.size[1] / 2 + 4, 0]));
      const tag = document.createElement("span");
      tag.className = `tag${body.connector.generic ? " generic" : ""}`;
      tag.textContent = body.connector.id;
      tag.style.left = `${((x + 1) / 2) * cssWidth}px`;
      tag.style.top = `${((1 - y) / 2) * cssHeight}px`;
      tag.hidden = z > 1;
      return tag;
    }));
  }

  _bindPointer() {
    const pointers = new Map();
    let moved = 0, pinch = null;
    this._stage.addEventListener("contextmenu", (event) => event.preventDefault());
    this._stage.addEventListener("pointerdown", (event) => {
      if (event.target.closest(".popover") || this.view === "2d") return;
      this._stage.setPointerCapture(event.pointerId);
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY, button: event.button, shift: event.shiftKey });
      moved = 0;
      pinch = null;
    });
    this._stage.addEventListener("pointermove", (event) => {
      const previous = pointers.get(event.pointerId);
      if (!previous) return;
      const dx = event.clientX - previous.x, dy = event.clientY - previous.y;
      moved += Math.abs(dx) + Math.abs(dy);
      previous.x = event.clientX; previous.y = event.clientY;
      const camera = this._camera;
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const spread = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinch) camera.distance *= pinch / spread;
        pinch = spread;
        this._pan(dx / 2, dy / 2);
      } else if (previous.button === 2 || previous.shift) {
        this._pan(dx, dy);
      } else {
        camera.yaw -= dx * 0.008;
        camera.pitch = Math.min(Math.max(camera.pitch + dy * 0.008, 0.08), 1.52);
      }
      this._draw();
    });
    const release = (event) => {
      const previous = pointers.get(event.pointerId);
      pointers.delete(event.pointerId);
      if (previous && moved < 5 && pointers.size === 0) this._pick(event);
    };
    this._stage.addEventListener("pointerup", release);
    this._stage.addEventListener("pointercancel", (event) => pointers.delete(event.pointerId));
    this._stage.addEventListener("wheel", (event) => {
      if (this.view === "2d") return;
      event.preventDefault();
      this._camera.distance *= Math.exp(event.deltaY * 0.0012);
      this._draw();
    }, { passive: false });
  }

  _pan(dx, dy) {
    const camera = this._camera;
    const right = [Math.cos(camera.yaw), 0, -Math.sin(camera.yaw)];
    const forward = [Math.sin(camera.yaw), 0, Math.cos(camera.yaw)];
    const perPixel = camera.distance / Math.max(this._stage.clientHeight, 1);
    camera.target = add(camera.target, add(scale(right, -dx * perPixel), scale(forward, -dy * perPixel)));
  }

  // Cast a ray from the click: connector bodies by their boxes, wires by distance to their tubes.
  _pick(event) {
    const bounds = this._stage.getBoundingClientRect();
    const { eye, viewProjection } = this._matrices();
    const inverse = invert(viewProjection);
    const ndc = [((event.clientX - bounds.left) / bounds.width) * 2 - 1, 1 - ((event.clientY - bounds.top) / bounds.height) * 2];
    const far = transformPoint(inverse, [ndc[0], ndc[1], 1]);
    const direction = normalize(subtract(far, eye));
    let best = null;
    for (const body of this._scene.bodies) {
      const hit = rayBox(eye, direction, body);
      if (hit !== null && (!best || hit < best.along)) best = { along: hit, kind: "connector", id: body.connector.id };
    }
    // A wire is hit within its radius, or within about 5 px on screen when it is drawn thinner than that.
    const worldPerPixel = (along) => (2 * along * Math.tan((35 * Math.PI) / 360)) / Math.max(bounds.height, 1);
    for (const { wire, points } of this._scene.wires) {
      for (let i = 0; i + 1 < points.length; i++) {
        const { distance, along } = raySegmentDistance(eye, direction, points[i], points[i + 1]);
        const tolerance = Math.max(this._scene.sizes.wire * 1.8, 5 * worldPerPixel(along));
        if (distance < tolerance && (!best || along < best.along - this._scene.sizes.wire)) best = { along, kind: "wire", id: wire.id };
      }
    }
    this._select(best, event.clientX - bounds.left, event.clientY - bounds.top);
  }

  _select(hit, x, y) {
    for (const popover of this._stage.querySelectorAll(".popover")) popover.remove();
    this._selected = new Set(hit ? [`${hit.kind}:${hit.id}`] : []);
    if (hit?.kind === "connector") this._connectorPopover(hit.id, x, y);
    if (hit?.kind === "wire") this._wirePopovers(hit.id);
    this._draw();
  }

  // Place a popover centred on x, preferring below y, else above (y - gap), and clear of the
  // popovers already shown; each candidate is clamped inside the stage.
  _place(popover, x, y, gap = 0) {
    this._stage.append(popover);
    const width = popover.offsetWidth, height = popover.offsetHeight;
    const stageWidth = this._stage.clientWidth, stageHeight = this._stage.clientHeight;
    const others = [...this._stage.querySelectorAll(".popover")].filter((other) => other !== popover)
      .map((other) => [other.offsetLeft, other.offsetTop, other.offsetLeft + other.offsetWidth, other.offsetTop + other.offsetHeight]);
    const left = Math.min(Math.max(x - width / 2, 6), stageWidth - width - 6);
    const candidates = [y, y - gap - height, ...others.map(([, , , bottom]) => bottom + 6), ...others.map(([, top]) => top - height - 6)]
      .map((top) => Math.min(Math.max(top, 6), stageHeight - height - 6));
    const clear = (top) => others.every(([l, t, r, b]) => left + width <= l || left >= r || top + height <= t || top >= b);
    const top = candidates.find(clear) ?? candidates[0];
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  }

  _popover(className, html) {
    const popover = document.createElement("div");
    popover.className = `popover ${className}`;
    popover.setAttribute("role", "dialog");
    popover.innerHTML = `<button class="close" aria-label="Close">×</button>${html}`;
    popover.querySelector(".close").addEventListener("click", () => this._select(null));
    return popover;
  }

  _connectorPopover(id, x, y) {
    const connector = this._model.connectors.find((c) => c.id === id);
    const rows = connector.pins.map((pin) => {
      const wires = this._model.wires.filter((w) => (w.from.connector === id && w.from.pin === pin.pin) || (w.to.connector === id && w.to.pin === pin.pin));
      if (!wires.length) return `<tr><td>${escapeHtml(pin.pin)}</td><td>${escapeHtml(pin.label) || '<span class="na">—</span>'}</td><td colspan="3" class="na">empty</td></tr>`;
      return wires.map((w) => {
        const other = w.from.connector === id && w.from.pin === pin.pin ? w.to : w.from;
        return `<tr><td>${escapeHtml(pin.pin)}</td><td>${escapeHtml(pin.label || w.signal)}</td><td>${escapeHtml(w.id)}</td>
          <td>${swatch(w)}</td><td>${escapeHtml(other.connector)}:${escapeHtml(other.pin)}</td></tr>`;
      }).join("");
    }).join("");
    const heading = [connector.id, connector.label, connector.generic ? `generic ${connector.pins.length}-pin` : connector.part_number]
      .filter(Boolean).map(escapeHtml).join(" · ");
    this._place(this._popover("", `<h3>${heading}</h3>${pinoutSvg(connector, this._model, null)}
      <table><thead><tr><th>Pin</th><th>Circuit</th><th>Wire</th><th>Colour</th><th>To</th></tr></thead><tbody>${rows}</tbody></table>`), x, y + 12);
  }

  // Where a model point (x, 0, y on the table) shows on the stage, in either view.
  _toScreen(point) {
    if (this.view === "2d") {
      const matrix = this._planSvg.getScreenCTM(), bounds = this._stage.getBoundingClientRect();
      return [matrix.a * point[0] + matrix.c * point[2] + matrix.e - bounds.left, matrix.b * point[0] + matrix.d * point[2] + matrix.f - bounds.top];
    }
    const { viewProjection, width, height } = this._matrices();
    const [x, y] = transformPoint(viewProjection, point);
    return [((x + 1) / 2) * width, ((1 - y) / 2) * height];
  }

  _wirePopovers(id) {
    const wire = this._model.wires.find((w) => w.id === id);
    const toScreen = (point) => this._toScreen(point);
    const plan = this.view === "2d";
    const points = plan ? this._plan.wires.find((entry) => entry.wire.id === id).points.map(([x, y]) => [x, 0, y])
      : this._scene.wires.find((entry) => entry.wire.id === id).points;
    const [mx, my] = toScreen(points[Math.floor(points.length / 2)]);
    this._place(this._popover("", `<h3>${escapeHtml(wire.id)} · ${escapeHtml(wire.signal || "")}</h3>
      <table><thead><tr><th>From</th><th>To</th><th>Gauge</th><th>Colour</th><th>Cut</th></tr></thead>
      <tbody><tr><td>${escapeHtml(wire.from.connector)}:${escapeHtml(wire.from.pin)}</td><td>${escapeHtml(wire.to.connector)}:${escapeHtml(wire.to.pin)}</td>
      <td>${escapeHtml(wire.gauge) || '<span class="na">not stated</span>'}</td><td>${swatch(wire)}</td><td>${escapeHtml(wire.cut_length)}</td></tr></tbody></table>`), mx, my + 14);
    for (const end of [wire.from, wire.to]) {
      const body = (plan ? this._plan : this._scene).bodies.find((b) => b.connector.id === end.connector);
      if (!body) continue;
      const [x, y] = toScreen(body.centre);
      const connector = body.connector;
      const content = connector.face ? pinoutSvg(connector, this._model, end.pin)
        : `<span class="mono">${escapeHtml(end.connector)} pin ${escapeHtml(end.pin)}</span>`;
      this._place(this._popover("small", `<h3>${escapeHtml(end.connector)}:${escapeHtml(end.pin)}</h3>${content}`), x, y + 30, 60);
    }
  }
}

// A pinout from the connector's stated face: each cavity in its wire's colour, the chosen pin
// ringed. Without a stated face there is no diagram.
function pinoutSvg(connector, model, highlightPin) {
  if (!connector.face) return "";
  const pitch = 28, radius = 10, margin = 12;
  const cavities = Object.entries(connector.face.cavities);
  const spanX = Math.max(...cavities.map(([, [x]]) => x)) * pitch, spanY = Math.max(...cavities.map(([, [, y]]) => y)) * pitch;
  const width = spanX + 2 * (radius + margin), height = spanY + 2 * (radius + margin);
  const colorOf = (pin) => {
    const wire = model.wires.find((w) => (w.from.connector === connector.id && w.from.pin === pin) || (w.to.connector === connector.id && w.to.pin === pin));
    return wire?.colors?.[0] || "none";
  };
  const outline = connector.face.round
    ? `<ellipse cx="${width / 2}" cy="${height / 2}" rx="${Math.max(width, height) / 2 - 1}" ry="${Math.max(width, height) / 2 - 1}" fill="var(--ground)" stroke="var(--ink)"/>`
    : `<rect x="1" y="1" width="${width - 2}" height="${height - 2}" rx="6" fill="var(--ground)" stroke="var(--ink)"/>`;
  const marks = cavities.map(([pin, [x, y]]) => {
    const cx = radius + margin + x * pitch, cy = radius + margin + y * pitch;
    const ring = pin === highlightPin ? `<circle cx="${cx}" cy="${cy}" r="${radius + 3.5}" fill="none" stroke="var(--select)" stroke-width="3"/>` : "";
    return `${ring}<circle cx="${cx}" cy="${cy}" r="${radius}" fill="${colorOf(pin)}" stroke="var(--ink)"/>
      <text x="${cx}" y="${cy + 3.5}" text-anchor="middle" font-size="10" font-weight="600" fill="var(--ink)" paint-order="stroke" stroke="var(--panel)" stroke-width="2">${escapeHtml(pin)}</text>`;
  }).join("");
  return `<svg role="img" aria-label="${escapeHtml(connector.id)} pinout, ${escapeHtml(connector.face.view)}" width="${width}" height="${height}"
    viewBox="0 0 ${width} ${height}" style="display:block;margin:0 auto 6px">${outline}${marks}</svg>
    <div class="eyebrow" style="text-align:center">${escapeHtml(connector.face.view)}</div>`;
}

function swatch(wire) {
  if (!wire.colors?.length) return '<span class="na">not chosen</span>';
  const fill = wire.colors.length > 1
    ? `repeating-linear-gradient(90deg, ${wire.colors[0]} 0 5px, ${wire.colors[1]} 5px 8px)` : wire.colors[0];
  return `<span class="swatch" style="background:${fill}"></span> ${escapeHtml(wire.color)}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

if (globalThis.customElements && !customElements.get("wire-harness-explorer")) {
  customElements.define("wire-harness-explorer", WireHarnessExplorer);
}

export { WireHarnessExplorer, version, samplePath, buildScene, buildPlan, planSvg, pinoutSvg };
