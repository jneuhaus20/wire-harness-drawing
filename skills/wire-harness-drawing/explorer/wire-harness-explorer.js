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
// Wires lie in a flat bed about eight wires across, further rows stacked on top, so every
// wire can be seen and clicked from above.
const bedWidth = 8;

// Sizes of what the 3D view draws. The schematic layout is in drawing units, not millimetres,
// so there wires and bodies take the drawing's proportions; otherwise a metre of harness would
// frame as a hairline. A routed harness is in true units, so it gets nominal true sizes in mm.
function sceneSizes(model) {
  if (model.geometry === "schematic") {
    return { wire: 3, thickened: 1, pitch: 6.4, lay: 48, exit: 52, bodyLength: 64, bodyHeight: 26, bodyWidth: (pins) => Math.min(110, Math.max(44, 8 + pins * 3.2)),
             splice: 26, breakout: 7 };
  }
  const unit = model.units === "in" ? 1 / 25.4 : 1;
  // A wire is about 0.9 mm in radius; over a metre of harness that frames as a hairline, so
  // wires are thickened to at least 1/350 of the harness's extent, and the view says by how much.
  const points = model.segments.flatMap((segment) => segment.points);
  const extent = Math.max(...[0, 1, 2].map((axis) => Math.max(...points.map((p) => p[axis])) - Math.min(...points.map((p) => p[axis]))));
  const wire = Math.max(0.9 * unit, extent / 350);
  const thickened = wire / (0.9 * unit);
  // Twists are drawn at 4 per inch, the rate L3Harris drawings call for on pairs.
  return { wire, thickened, pitch: 2.2 * wire, lay: 6.35 * unit * thickened, exit: 40 * unit, bodyLength: 30 * unit, bodyHeight: 10 * unit,
           bodyWidth: (pins) => Math.min(60, Math.max(10, 4 + pins * 2.5)) * unit, splice: 9 * unit, breakout: 2.5 * unit };
}

// Within a segment, a wire's place across the bed follows where it is going: wires bound for a
// branch higher on the sheet lie on that side, so wires leave the bundle without crossing it.
// Ties keep the order of the wires' far ends, then their ids.
function bedKey(wire, parent, child, nodeById) {
  const towardChild = wire.route.indexOf(child) > wire.route.indexOf(parent);
  const ahead = towardChild ? wire.route.at(-1) : wire.route[0];
  const behind = towardChild ? wire.route[0] : wire.route.at(-1);
  return [-nodeById[ahead].y, nodeById[ahead].x, nodeById[behind].y, wire.id];
}

function compareKeys(a, b) {
  for (let i = 0; i < a.length; i++) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return 0;
}

// The 3D scene in model units: the sheet's placement laid on a table (x across, z toward the
// viewer, y up). Each wire runs as its own tube along its route, in its place in each segment's
// bed; a wire that ends at a splice rises out of the bed into the splice sleeve above it. Each
// connector is a body beyond its node, pointing away from its bundle.
function buildScene(model, overrides = {}) {
  const sizes = { ...sceneSizes(model), ...overrides };
  const routed = model.geometry !== "schematic";
  const positions = {};
  const connectors = Object.fromEntries(model.connectors.map((connector) => [connector.id, connector]));
  const wiresById = Object.fromEntries(model.wires.map((wire) => [wire.id, wire]));
  const nodeById = Object.fromEntries(model.nodes.map((node) => [node.id, node]));
  const segmentByKey = new Map();
  const segments = model.segments.map((segment) => ({ ...segment }));
  for (const segment of segments) {
    const polyline = routed ? segment.points : samplePath(segment.path).map(([x, y]) => [x, 0, y]);
    Object.assign(segment, packSegment(segment, sizes, wiresById, nodeById));
    segment.polyline = routed ? densify(polyline, sizes.pitch * 4) : polyline;
    segmentByKey.set(`${segment.nodes[0]}|${segment.nodes[1]}`, segment);
    positions[segment.nodes[0]] = polyline[0];
    positions[segment.nodes[1]] = polyline[polyline.length - 1];
  }
  // Each splice sits a little above the tallest bed that meets it. Splices placed too close
  // together along the harness to sit side by side are stacked, one sleeve above the next.
  const spliceLift = {}, spliceLevel = {};
  const splices = model.connectors.filter((c) => c.splice);
  for (const [index, connector] of splices.entries()) {
    const crowd = splices.slice(0, index).filter((other) => length(subtract(positions[other.id], positions[connector.id])) < sizes.splice * 1.3);
    spliceLevel[connector.id] = crowd.length ? Math.max(...crowd.map((other) => spliceLevel[other.id])) + 1 : 0;
    const rows = Math.max(1, ...segments.filter((s) => s.nodes.includes(connector.id)).map((s) => s.rows));
    spliceLift[connector.id] = rows * sizes.pitch + sizes.pitch + spliceLevel[connector.id] * (sizes.wire * 3.2 + sizes.pitch);
  }
  const taper = sizes.pitch * 6;
  const blend = sizes.pitch * 5;
  const smooth = (t) => { const c = Math.min(Math.max(t, 0), 1); return c * c * (3 - 2 * c); };
  const wires = model.wires.map((wire) => {
    // The wire's place in each segment, in its own direction of travel; at each node it eases
    // from one segment's place to the next instead of jumping.
    const legs = wire.route.slice(0, -1).map((node, i) => {
      const forward = segmentByKey.get(`${node}|${wire.route[i + 1]}`);
      const segment = forward || segmentByKey.get(`${wire.route[i + 1]}|${node}`);
      const place = segment.placement[wire.id];
      return { segment, forward: !!forward, place, centre: [place.centre[0] * (forward ? 1 : -1), place.centre[1]] };
    });
    const points = [];
    let travelled = 0;
    legs.forEach((leg, i) => {
      const { segment, forward, place } = leg;
      const along = forward ? segment.polyline : [...segment.polyline].reverse();
      const startSplice = i === 0 && wire.route[0] in spliceLift ? spliceLift[wire.route[0]] : null;
      const endSplice = i === legs.length - 1 && wire.route.at(-1) in spliceLift ? spliceLift[wire.route.at(-1)] : null;
      const centre = resample(along, Math.min(sizes.lay / 12, blend / 6));
      const flip = forward ? 1 : -1;
      const distances = runLengths(centre);
      const total = distances.at(-1);
      const reach = Math.min(blend, total / 2);
      const offsets = distances.map((distance) => {
        const turn = place.phase + (2 * Math.PI * (travelled + distance)) / sizes.lay;
        let side = leg.centre[0], up = leg.centre[1];
        if (i > 0) {
          const weight = 0.5 * (1 - smooth(distance / reach));
          side += (legs[i - 1].centre[0] - side) * weight; up += (legs[i - 1].centre[1] - up) * weight;
        }
        if (i < legs.length - 1) {
          const weight = 0.5 * (1 - smooth((total - distance) / reach));
          side += (legs[i + 1].centre[0] - side) * weight; up += (legs[i + 1].centre[1] - up) * weight;
        }
        let offset = [side + place.radius * Math.cos(turn) * flip, up + place.radius * Math.sin(turn)];
        for (const [lift, gap] of [[startSplice, distance], [endSplice, total - distance]]) {
          if (lift === null || gap >= taper) continue;
          const eased = smooth(1 - gap / taper);
          offset = [offset[0] * (1 - eased), offset[1] + (lift - offset[1]) * eased];
        }
        return offset;
      });
      travelled += total;
      const offsetLine = offsetPolyline(centre, offsets);
      points.push(...(i === 0 ? offsetLine : offsetLine.slice(1)));
    });
    return { wire, points, colors: wire.colors.length ? wire.colors.map(hexToRgb) : [[0.62, 0.62, 0.62]] };
  });
  const jackets = cableSheaths(model, segmentByKey, sizes);
  const bodies = model.nodes.filter((node) => node.kind !== "breakout")
    .map((node) => connectorBody(segments, positions[node.id], connectors[node.id], sizes, spliceLift[node.id]));
  const breakouts = model.nodes.filter((node) => node.kind === "breakout").map((node) => positions[node.id]);
  const points = [...wires.flatMap((wire) => wire.points),
    ...bodies.flatMap((body) => [add(body.centre, scale(body.axis, body.size[0] / 2)), subtract(body.centre, scale(body.axis, body.size[0] / 2))])];
  const bounds = [0, 1, 2].map((axis) => [Math.min(...points.map((p) => p[axis])), Math.max(...points.map((p) => p[axis]))]);
  return { wires, jackets, bodies, breakouts, sizes, bounds, segments, positions, spliceLevel, grid: routed ? floorGrid(bounds, model, positions) : { lines: [], plumbs: [] } };
}

// A routed harness hangs in space; a faint floor grid under it, at 100 mm (or 4 in) spacing,
// gives its heights and runs something to be read against.
function floorGrid(bounds, model, positions) {
  const spacing = model.units === "in" ? 4 : 100;
  const [[x0, x1], [y0], [z0, z1]] = bounds;
  const floor = y0 - spacing * 0.1;
  const lines = [];
  const from = (value) => Math.floor(value / spacing - 1) * spacing, to = (value) => Math.ceil(value / spacing + 1) * spacing;
  for (let x = from(x0); x <= to(x1); x += spacing) lines.push([[x, floor, from(z0)], [x, floor, to(z1)]]);
  for (let z = from(z0); z <= to(z1); z += spacing) lines.push([[from(x0), floor, z], [to(x1), floor, z]]);
  // A plumb line from each node down to the floor shows how high it is.
  const plumbs = Object.values(positions).filter(([, y]) => y - floor > spacing * 0.2).map(([x, y, z]) => [[x, y, z], [x, floor, z]]);
  return { lines, plumbs };
}

// A cable is one sheath over the run its conductors share, stopping short of each end by the
// strip-back length where the conductors leave it for their connectors. The conductors inside
// are not drawn through it; only where they leave it.
function cableSheaths(model, segmentByKey, sizes) {
  return (model.cables || []).filter((cable) => cable.run && cable.run.length > 1).map((cable) => {
    const points = [];
    let radius = sizes.wire * 2;
    for (let i = 0; i + 1 < cable.run.length; i++) {
      const [a, b] = [cable.run[i], cable.run[i + 1]];
      const forward = segmentByKey.get(`${a}|${b}`);
      const segment = forward || segmentByKey.get(`${b}|${a}`);
      const sheath = segment.cables[cable.id];
      radius = Math.max(radius, sheath.radius);
      const along = forward ? segment.polyline : [...segment.polyline].reverse();
      const line = offsetPolyline(along, along.map(() => [sheath.offset[0] * (forward ? 1 : -1), sheath.offset[1]]));
      points.push(...(points.length ? line.slice(1) : line));
    }
    // The model gives the breakout in drawing units; the schematic layout is not to scale, so
    // there the jacket stops a fixed distance short, enough for the conductors to be seen leaving.
    const total = runLengths(points).at(-1) || 0;
    const stop = (node) => (cable.breakouts[node] ? (model.geometry === "schematic" ? sizes.exit : cable.breakouts[node]) : 0);
    const from = Math.min(stop(cable.run[0]), total / 3), to = total - Math.min(stop(cable.run.at(-1)), total / 3);
    return { cable: cable.id, points: trimPolyline(points, from, to), radius, color: cable.color };
  }).filter((sheath) => sheath.points.length > 1);
}

// The part of a polyline between two distances along it.
function trimPolyline(points, from, to) {
  const out = [pointAlong(points, from)];
  const distances = runLengths(points);
  points.forEach((point, index) => { if (distances[index] > from && distances[index] < to) out.push(point); });
  out.push(pointAlong(points, to));
  return out;
}

// A segment's wires pack into units laid side by side on the bed, left to right, wrapping
// into a row above when a row is full: a lone wire is a unit; a twist group is one unit its
// wires wind around; a cable is one unit, its sheath round its own conductors (lone or
// twisted) packed tight inside. Units sort by where they are going (bedKey). Each wire's
// place is its centre (side, up), the radius it winds at (zero for a lone wire) and its
// starting angle; each cable's is its sheath's centre and radius.
function packSegment(segment, sizes, wiresById, nodeById) {
  const [parent, child] = segment.nodes;
  const groups = new Map();
  for (const id of segment.wires) {
    const wire = wiresById[id];
    const key = wire.cable ? `cable:${wire.cable}` : wire.twist ? `twist:${wire.twist}` : `wire:${id}`;
    groups.set(key, [...(groups.get(key) || []), id]);
  }
  const keyOf = (ids) => ids.map((id) => bedKey(wiresById[id], parent, child, nodeById)).sort(compareKeys)[0];
  const ordered = [...groups.entries()].sort(([, a], [, b]) => compareKeys(keyOf(a), keyOf(b)));
  const strands = (ids) => {
    const byTwist = new Map();
    for (const id of ids) {
      const key = wiresById[id].twist ? `twist:${wiresById[id].twist}` : `wire:${id}`;
      byTwist.set(key, [...(byTwist.get(key) || []), id]);
    }
    return [...byTwist.values()];
  };
  const twistRadius = (count) => (count > 1 ? sizes.pitch / 2 / Math.sin(Math.PI / count) : 0);
  // Lay out one unit's strands around its own centre; return their places and the unit's radius.
  const layUnit = (ids) => {
    const inner = strands(ids);
    const pitch = Math.max(...inner.map((strand) => 2 * twistRadius(strand.length) + sizes.pitch));
    const offsets = inner.length === 1 ? [[0, 0]] : inner.map((_, k) => {
      const ring = (pitch / 2) / Math.sin(Math.PI / inner.length);
      const angle = Math.PI / 2 + (2 * Math.PI * k) / inner.length;
      return [Math.cos(angle) * ring, Math.sin(angle) * ring];
    });
    const places = {};
    inner.forEach((strand, k) => strand.forEach((id, j) => {
      places[id] = { offset: offsets[k], radius: twistRadius(strand.length), phase: (2 * Math.PI * j) / strand.length };
    }));
    const reach = Math.max(...inner.map((strand, k) => Math.hypot(...offsets[k]) + twistRadius(strand.length))) + sizes.wire;
    return { places, reach };
  };
  const units = ordered.map(([key, ids]) => ({ key, ids, ...layUnit(ids) }))
    .map((unit) => ({ ...unit, width: 2 * (unit.key.startsWith("cable:") ? unit.reach + sizes.wire * 1.4 : unit.reach) + sizes.pitch - 2 * sizes.wire }));
  const rowLimit = bedWidth * sizes.pitch;
  const rows = [[]];
  for (const unit of units) {
    const row = rows.at(-1);
    if (row.length && row.reduce((sum, u) => sum + u.width, 0) + unit.width > rowLimit) rows.push([unit]);
    else row.push(unit);
  }
  const placement = {}, cables = {};
  let up = 0;
  rows.forEach((row) => {
    const rowWidth = row.reduce((sum, u) => sum + u.width, 0);
    const rowHeight = Math.max(...row.map((u) => u.width));
    let cursor = -rowWidth / 2;
    for (const unit of row) {
      const centre = [cursor + unit.width / 2, up + rowHeight / 2 - sizes.pitch / 2];
      cursor += unit.width;
      for (const [id, place] of Object.entries(unit.places)) {
        placement[id] = { centre: [centre[0] + place.offset[0], centre[1] + place.offset[1]], radius: place.radius, phase: place.phase };
      }
      if (unit.key.startsWith("cable:")) cables[unit.key.slice(6)] = { offset: centre, radius: unit.reach + sizes.wire * 0.9 };
    }
    up += rowHeight;
  });
  return { placement, cables, order: ordered.flatMap(([, ids]) => ids), rows: Math.max(1, Math.round(up / sizes.pitch)) };
}

// Points along a polyline no further apart than spacing, keeping its corners.
function resample(points, spacing) {
  const out = [points[0]];
  for (let i = 1; i < points.length; i++) {
    const steps = Math.max(1, Math.ceil(length(subtract(points[i], points[i - 1])) / spacing));
    for (let step = 1; step <= steps; step++) out.push(add(points[i - 1], scale(subtract(points[i], points[i - 1]), step / steps)));
  }
  return out;
}

function pointAlong(points, distance) {
  for (let i = 1; i < points.length; i++) {
    const step = length(subtract(points[i], points[i - 1]));
    if (distance <= step || i === points.length - 1) return add(points[i - 1], scale(subtract(points[i], points[i - 1]), Math.min(distance / (step || 1), 1)));
    distance -= step;
  }
  return points[0];
}

function runLengths(points) {
  const distances = [0];
  for (let i = 1; i < points.length; i++) distances.push(distances[i - 1] + length(subtract(points[i], points[i - 1])));
  return distances;
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

// Offset each point of a polyline sideways (in the table plane, square to the run) and up, by
// that point's own [side, up].
function offsetPolyline(points, offsets) {
  return points.map((point, index) => {
    const before = points[Math.max(index - 1, 0)];
    const after = points[Math.min(index + 1, points.length - 1)];
    const tangent = normalize(subtract(after, before));
    const sideways = normalize(cross([0, 1, 0], tangent));
    const [side, up] = offsets[index];
    return add(add(point, scale(sideways, side)), [0, up, 0]);
  });
}

// ---------- The 2D view ----------

// The 2D view is the drawing redrawn as a clean diagram: each segment one bundle, as thick as
// its wire count, every wire shown in its colour where it fans into its connector, splices and
// breakouts as the drawing marks them. Selecting a wire traces its whole route in its colour.
const fanLength = 26;

function buildPlan(model) {
  // In 2D a cable's jacket runs right up to where its conductors fan into their connector.
  const scene = buildScene({ ...model, geometry: "schematic" }, { exit: fanLength + 2 });
  const nodes = Object.fromEntries(model.nodes.map((node) => [node.id, [node.x, node.y]]));
  const fans = [];
  for (const body of scene.bodies.filter((b) => b.kind === "connector")) {
    const id = body.connector.id;
    const [x, y] = nodes[id];
    const axis = [body.axis[0], body.axis[2]];
    const across = [-axis[1], axis[0]];
    const wires = model.wires.filter((wire) => wire.from.connector === id || wire.to.connector === id);
    const spread = Math.min(5, (body.size[2] - 10) / Math.max(wires.length, 1));
    wires.forEach((wire, index) => {
      const shift = (index - (wires.length - 1) / 2) * spread;
      const start = [x - axis[0] * fanLength, y - axis[1] * fanLength];
      const control = [x - axis[0] * fanLength / 2, y - axis[1] * fanLength / 2];
      const end = [x + across[0] * shift, y + across[1] * shift];
      fans.push({ wire, d: `M${start[0].toFixed(1)},${start[1].toFixed(1)} C${control[0].toFixed(1)},${control[1].toFixed(1)} `
        + `${(control[0] + across[0] * shift).toFixed(1)},${(control[1] + across[1] * shift).toFixed(1)} ${end[0].toFixed(1)},${end[1].toFixed(1)}` });
    });
  }
  const sheaths = scene.jackets.map((jacket) => ({ ...jacket, points: jacket.points.map(([x, , z]) => [x, z]) }));
  return { fans, sheaths, bodies: scene.bodies, nodes: model.nodes, segments: scene.segments, spliceLevel: scene.spliceLevel };
}

function polylineData(points) {
  return points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
}

function stripePaths(d, wire, width, extra = "") {
  if (!wire.colors.length) return `<path d="${d}" fill="none" stroke="var(--muted)" stroke-width="${width}" stroke-dasharray="5 4"${extra}/>`;
  const [base, stripe] = wire.colors;
  return `<path d="${d}" fill="none" stroke="${base}" stroke-width="${width}"${extra}/>`
    + (stripe ? `<path d="${d}" fill="none" stroke="${stripe}" stroke-width="${width * 0.45}" stroke-dasharray="4 5"${extra}/>` : "");
}

function planSvg(model, plan) {
  const xs = model.nodes.map((node) => node.x), ys = model.nodes.map((node) => node.y);
  const margin = 90;
  const box = [Math.min(...xs) - margin, Math.min(...ys) - margin, Math.max(...xs) - Math.min(...xs) + 2 * margin,
    Math.max(...ys) - Math.min(...ys) + 2 * margin];
  const parts = [];
  // Loose wires make the bundle, drawn beside any cable sheath that shares the segment; a
  // segment that carries only cables has no loose bundle.
  // A conductor is under its sheath in the segments of its cable's run, and loose beyond them.
  const sheathed = new Set((model.cables || []).flatMap((cable) => (cable.run || []).slice(0, -1).flatMap((node, i) =>
    cable.wires.flatMap((id) => [`${id}|${node}|${cable.run[i + 1]}`, `${id}|${cable.run[i + 1]}|${node}`]))));
  for (const segment of plan.segments) {
    const loose = segment.wires.filter((id) => !sheathed.has(`${id}|${segment.nodes[0]}|${segment.nodes[1]}`));
    if (!loose.length) continue;
    const thickness = 1.6 * Math.sqrt(loose.length);
    const sides = loose.map((id) => segment.placement[id].centre[0]);
    const side = sides.length === segment.wires.length ? 0 : (Math.min(...sides) + Math.max(...sides)) / 2;
    const d = side ? polylineData(offsetPolyline(segment.polyline, segment.polyline.map(() => [side, 0])).map(([x, , z]) => [x, z])) : segment.path;
    const key = `${segment.nodes[0]}|${segment.nodes[1]}`;
    parts.push(`<g class="bundle" data-segment="${escapeHtml(key)}"><path d="${d}" fill="none" stroke="transparent" stroke-width="14"/>
      <path d="${d}" fill="none" stroke="var(--bundle-edge)" stroke-width="${(3 + thickness).toFixed(1)}" stroke-linecap="round"/>
      <path d="${d}" fill="none" stroke="var(--bundle)" stroke-width="${(1 + thickness).toFixed(1)}" stroke-linecap="round"/></g>`);
  }
  for (const wire of model.wires) {
    const paths = model.segments.filter((segment) => segment.wires.includes(wire.id)).map((segment) => segment.path);
    const casing = paths.map((d) => `<path d="${d}" fill="none" stroke="var(--select)" stroke-opacity=".6" stroke-width="7" stroke-linecap="round"/>`).join("");
    parts.push(`<g class="route" data-route="${escapeHtml(wire.id)}">${casing}${paths.map((d) => stripePaths(d, wire, 3.2, ' stroke-linecap="round"')).join("")}</g>`);
  }
  for (const sheath of plan.sheaths) {
    const d = sheath.points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    parts.push(`<g class="jacket" data-cable="${escapeHtml(sheath.cable)}"><path d="${d}" fill="none" stroke="transparent" stroke-width="14"/>
      <path d="${d}" fill="none" stroke="var(--bundle-edge)" stroke-width="${(sheath.radius * 1.05 + 2).toFixed(1)}" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="${d}" fill="none" stroke="${sheath.color ? `color-mix(in srgb, ${sheath.color} 70%, var(--bundle))` : "var(--sheath)"}" stroke-width="${(sheath.radius * 1.05).toFixed(1)}" stroke-linecap="round" stroke-linejoin="round"/></g>`);
  }
  for (const { wire, d } of plan.fans) {
    parts.push(`<g class="wire" data-wire="${escapeHtml(wire.id)}"><path d="${d}" fill="none" stroke="transparent" stroke-width="7"/>${stripePaths(d, wire, 2)}</g>`);
  }
  for (const segment of plan.segments) {
    const [x, , z] = pointAlong(segment.polyline, runLengths(segment.polyline).at(-1) / 2);
    const unknown = segment.known ? "" : ' font-style="italic"';
    parts.push(`<text x="${x.toFixed(1)}" y="${(z + 18).toFixed(1)}" text-anchor="middle" class="length"${unknown}>${escapeHtml(segment.length)}</text>`);
  }
  for (const node of plan.nodes.filter((n) => n.kind === "breakout")) {
    parts.push(`<circle cx="${node.x}" cy="${node.y}" r="4" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.2"/>`);
  }
  for (const body of plan.bodies) {
    const id = escapeHtml(body.connector.id);
    const node = plan.nodes.find((n) => n.id === body.connector.id);
    if (body.kind === "splice") {
      const lift = (plan.spliceLevel[body.connector.id] || 0) * 22, y = node.y - lift;
      const stem = lift ? `<line x1="${node.x}" y1="${node.y}" x2="${node.x}" y2="${y}" stroke="var(--ink)" stroke-width="1"/>` : "";
      parts.push(`<g class="connector" data-connector="${id}">${stem}<rect x="${node.x - 7}" y="${y - 7}" width="14" height="14" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.2" transform="rotate(45 ${node.x} ${y})"/>
        <text x="${lift ? node.x + 12 : node.x}" y="${lift ? y + 4 : y - 15}" text-anchor="${lift ? "start" : "middle"}" class="name">${id}</text></g>`);
      continue;
    }
    const [cx, , cz] = body.centre;
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

// A connector body sits beyond its node, along the direction its bundle arrives in. A splice is
// a sleeve along the bundle, lifted above the bed so the wires it joins can be seen meeting in it.
function connectorBody(segments, centre, connector, sizes, lift) {
  const segment = segments.find((s) => s.nodes.includes(connector.id));
  const polyline = segment ? segment.polyline : [centre, add(centre, [1, 0, 0])];
  const atStart = segment && segment.nodes[0] === connector.id;
  const near = atStart ? polyline[0] : polyline[polyline.length - 1];
  const inner = atStart ? polyline[1] : polyline[polyline.length - 2];
  const axis = normalize(subtract(near, inner));
  if (connector.splice) {
    return { connector, kind: "splice", centre: add(centre, [0, lift, 0]), axis, size: [sizes.splice, sizes.wire * 3.2, sizes.wire * 3.2] };
  }
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

// A body's frame: x along its axis, y as near straight up as that allows, z square to both.
// A body tilted out of the table plane still gets a true right-angled frame.
function bodyFrame(axis) {
  const x = normalize(axis);
  let z = cross(x, [0, 1, 0]);
  z = length(z) < 1e-6 ? [0, 0, 1] : normalize(z);
  return [x, cross(z, x), z];
}

function boxMesh(centre, axis, size, color) {
  const [x, y, z] = bodyFrame(axis);
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
  const [x, y, z] = bodyFrame(body.axis);
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
  --bundle: #cfcdc6; --bundle-edge: #8e8c85; --sheath: #4a4a4c; --select: #e0a21b; display: block; position: relative; font-family: "IBM Plex Sans", system-ui, sans-serif; color: var(--ink);
  container-type: inline-size; }
:host([theme="dark"]) { --ground: #17181a; --panel: #222327; --ink: #ecebe6; --muted: #a2a19b; --line: #3a3b40; --accent: #7aa2ff;
  --bundle: #4b4c52; --bundle-edge: #2c2d31; --sheath: #6f6f73; }
@media (prefers-color-scheme: dark) { :host(:not([theme="light"])) { --ground: #17181a; --panel: #222327; --ink: #ecebe6;
  --muted: #a2a19b; --line: #3a3b40; --accent: #7aa2ff; --bundle: #4b4c52; --bundle-edge: #2c2d31; --sheath: #6f6f73; } }
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
svg.plan .wire, svg.plan .connector, svg.plan .bundle, svg.plan .jacket { cursor: pointer; }
svg.plan .route:not(.lit) { display: none; }
svg.plan.selecting .wire:not(.lit), svg.plan.selecting .connector:not(.lit), svg.plan.selecting .bundle:not(.lit),
  svg.plan.selecting .jacket:not(.lit) { opacity: .3; }
svg.plan .jacket.lit path:nth-child(2) { stroke: var(--select); }
svg.plan .connector.lit rect { stroke: var(--select); stroke-width: 3; }
svg.plan .bundle.lit path:nth-child(2) { stroke: var(--select); }
.popover tbody tr[data-pick] { cursor: pointer; }
.popover tbody tr[data-pick]:hover td { background: color-mix(in srgb, var(--select) 18%, transparent); }
`;

// ---------- Framing ----------

const fieldOfView = (35 * Math.PI) / 180;

// The camera's right, up and toward-the-camera directions for a yaw and pitch about the target.
function viewBasis(yaw, pitch) {
  const toward = [Math.cos(pitch) * Math.sin(yaw), Math.sin(pitch), Math.cos(pitch) * Math.cos(yaw)];
  const right = normalize(cross([0, 1, 0], toward));
  return [right, cross(toward, right), toward];
}

// How far from the centre of a bounding box the camera must stand, at a yaw and pitch, for
// every corner of the box to be in a view of the given aspect, with a small margin.
function fitDistance(bounds, yaw, pitch, aspect) {
  const [right, up, toward] = viewBasis(yaw, pitch);
  const centre = bounds.map(([low, high]) => (low + high) / 2);
  const tangent = Math.tan(fieldOfView / 2);
  let distance = 0;
  for (let k = 0; k < 8; k++) {
    const offset = bounds.map(([low, high], axis) => ((k >> axis) & 1 ? high : low) - centre[axis]);
    const across = Math.max(Math.abs(dot(offset, right)) / aspect, Math.abs(dot(offset, up))) / tangent;
    distance = Math.max(distance, dot(offset, toward) + across * 1.08);
  }
  return distance;
}

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
          <div><div class="eyebrow">${escapeHtml(model.number)} · ${contentsText(model)} · rev ${escapeHtml(model.rev)}</div>
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
    this._scene = buildScene(model);
    this.shadowRoot.querySelector(".notice").textContent = model.geometry === "schematic"
      ? "No routing geometry given: the 3D view lays the drawing's layout flat. Not to scale."
      : `Routed as specified, in ${model.geometry.toUpperCase()}, over a ${model.units === "in" ? "4 in" : "100 mm"} floor grid. `
        + (this._scene.sizes.thickened > 1.05 ? `Wires drawn ${this._scene.sizes.thickened.toFixed(1)}× thicker than nominal to stay visible; bodies at nominal size.`
          : "Wires and bodies at nominal size.");
    for (const button of this.shadowRoot.querySelectorAll("[data-view]")) {
      button.addEventListener("click", () => this.setAttribute("view", button.dataset.view));
    }
    this.shadowRoot.querySelector("[data-reset]").addEventListener("click", () => { this._frame(); this._draw(); });
    this._plan = buildPlan(model);
    this._planHolder = this.shadowRoot.querySelector(".planHolder");
    this._planHolder.innerHTML = planSvg(model, this._plan);
    this._planSvg = this._planHolder.querySelector("svg");
    this._planSvg.addEventListener("click", (event) => {
      const bounds = this._stage.getBoundingClientRect();
      const wire = event.target.closest("[data-wire]"), connector = event.target.closest("[data-connector]");
      const bundle = event.target.closest("[data-segment]"), cable = event.target.closest("[data-cable]");
      const hit = connector ? { kind: "connector", id: connector.dataset.connector } : wire ? { kind: "wire", id: wire.dataset.wire }
        : cable ? { kind: "cable", id: cable.dataset.cable } : bundle ? { kind: "segment", id: bundle.dataset.segment } : null;
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
    this.shadowRoot.querySelector(".help").textContent = plan ? "Click a connector, a wire where it fans out, or a bundle."
      : "Click a connector or wire. Drag to orbit, right-drag or two fingers to pan, pinch or Ctrl-scroll to zoom.";
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
    // A striped wire carries its stripe as a helix round the insulation, as a tracer stripe
    // runs, so it shows from every side.
    const sides = 12, stripePitch = this._scene.sizes.wire * 14;
    for (const { wire, points, colors } of this._scene.wires) {
      const distances = runLengths(points);
      const color = colors.length > 1
        ? (i, k) => (((k / sides + distances[i] / stripePitch) % 1) < 0.34 ? colors[1] : colors[0]) : colors[0];
      renderer.upload(`wire:${wire.id}`, tubeMesh(points, this._scene.sizes.wire, sides, color));
    }
    for (const jacket of this._scene.jackets) {
      renderer.upload(`cable:${jacket.cable}`, tubeMesh(jacket.points, jacket.radius, 20, jacket.color ? hexToRgb(jacket.color) : [0.27, 0.27, 0.28]));
    }
    for (const body of this._scene.bodies) {
      const generic = body.connector.generic;
      const color = body.kind === "splice" ? [0.72, 0.72, 0.7] : generic ? [0.86, 0.86, 0.84] : [0.3, 0.31, 0.33];
      const mesh = (body.connector.shape === "circular" && body.kind === "connector") || body.kind === "splice"
        ? tubeMesh([subtract(body.centre, scale(body.axis, body.size[0] / 2)), add(body.centre, scale(body.axis, body.size[0] / 2))],
          body.size[2] / 2, 24, color)
        : boxMesh(body.centre, body.axis, body.size, color);
      renderer.upload(`connector:${body.connector.id}`, mesh, generic ? 0.55 : 1);
    }
    const lineWidth = this._scene.sizes.wire * 0.45;
    const gridMeshes = this._scene.grid.lines.map(([a, b]) => {
      const direction = normalize(subtract(b, a)), across = scale(normalize(cross(direction, [0, 1, 0])), lineWidth);
      return { positions: [...subtract(a, across), ...add(a, across), ...add(b, across), ...subtract(b, across)],
               normals: [0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0], colors: Array(4).fill([0.62, 0.62, 0.6]).flat(), indices: [0, 1, 2, 0, 2, 3] };
    });
    if (gridMeshes.length) renderer.upload("grid", mergeMeshes(gridMeshes), 0.5);
    const plumbs = this._scene.grid.plumbs.map(([a, b]) => tubeMesh([a, b], lineWidth * 0.6, 6, [0.62, 0.62, 0.6]));
    if (plumbs.length) renderer.upload("plumbs", mergeMeshes(plumbs), 0.45);
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
    this._camera.yaw = -0.35;
    this._camera.pitch = 0.9;
    const aspect = this._stage.clientWidth / Math.max(this._stage.clientHeight, 1) || 1.5;
    this._camera.distance = Math.max(fitDistance(bounds, this._camera.yaw, this._camera.pitch, aspect), this._scene.sizes.bodyLength * 3);
  }

  _matrices() {
    const width = this._stage.clientWidth, height = this._stage.clientHeight;
    const camera = this._camera;
    const eye = add(camera.target, [
      camera.distance * Math.cos(camera.pitch) * Math.sin(camera.yaw),
      camera.distance * Math.sin(camera.pitch),
      camera.distance * Math.cos(camera.pitch) * Math.cos(camera.yaw),
    ]);
    const projection = perspective(fieldOfView, width / Math.max(height, 1), camera.distance / 50, camera.distance * 6);
    return { eye, viewProjection: multiply(projection, lookAt(eye, camera.target, [0, 1, 0])), width, height };
  }

  _draw() {
    if (this._planSvg) {
      this._planSvg.classList.toggle("selecting", this._selected.size > 0);
      for (const element of this._planSvg.querySelectorAll("[data-wire], [data-connector], [data-route], [data-segment], [data-cable]")) {
        const { wire, connector, route, segment, cable } = element.dataset;
        const key = wire || route ? `wire:${wire || route}` : connector ? `connector:${connector}` : cable ? `cable:${cable}` : `segment:${segment}`;
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
    // A plain wheel scrolls the page the explorer sits in; Ctrl or ⌘ with the wheel, or a
    // trackpad pinch (which browsers send as a Ctrl-wheel), zooms.
    this._stage.addEventListener("wheel", (event) => {
      if (this.view === "2d" || !(event.ctrlKey || event.metaKey)) return;
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
    for (const jacket of this._scene.jackets) {
      for (let i = 0; i + 1 < jacket.points.length; i++) {
        const { distance, along } = raySegmentDistance(eye, direction, jacket.points[i], jacket.points[i + 1]);
        if (distance < jacket.radius && (!best || along < best.along)) best = { along: along - jacket.radius, kind: "cable", id: jacket.cable };
      }
    }
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

  // A splice joins every wire in it into one circuit, so selecting it selects them too.
  _select(hit, x, y) {
    for (const popover of this._stage.querySelectorAll(".popover")) popover.remove();
    this._selected = new Set(hit ? [`${hit.kind}:${hit.id}`] : []);
    const connector = hit?.kind === "connector" && this._model.connectors.find((c) => c.id === hit.id);
    if (connector?.splice) {
      for (const wire of this._wiresAt(hit.id)) this._selected.add(`wire:${wire.id}`);
      this._splicePopover(connector, x, y);
    } else if (connector) {
      this._connectorPopover(hit.id, x, y);
    }
    if (hit?.kind === "wire") {
      const cable = this._model.wires.find((w) => w.id === hit.id).cable;
      if (cable) this._selected.add(`cable:${cable}`);
      this._wirePopovers(hit.id, x, y);
    }
    if (hit?.kind === "cable") {
      const cable = this._model.cables.find((c) => c.id === hit.id);
      for (const id of cable.wires) this._selected.add(`wire:${id}`);
      this._cablePopover(cable, x, y);
    }
    if (hit?.kind === "segment") this._segmentPopover(hit.id, x, y);
    this._draw();
  }

  _wiresAt(designator) {
    return this._model.wires.filter((w) => w.from.connector === designator || w.to.connector === designator);
  }

  // A splice has no pins and carries one circuit: its popover names the circuit once and lists
  // the wires joined in it and where each goes.
  _splicePopover(connector, x, y) {
    const wires = this._wiresAt(connector.id);
    const circuits = [...new Set(wires.map((w) => w.signal).filter(Boolean))];
    const rows = wires.map((w) => {
      const other = w.from.connector === connector.id ? w.to : w.from;
      return `<tr data-pick="${escapeHtml(w.id)}"><td>${escapeHtml(w.id)}</td><td>${swatch(w)}</td><td>${escapeHtml(w.gauge)}</td>
        <td>${escapeHtml(other.connector)}:${escapeHtml(other.pin)}</td></tr>`;
    }).join("");
    const heading = [connector.id, circuits.join(" / ") || "signal not named", connector.part_number || "splice"].map(escapeHtml).join(" · ");
    this._place(this._picking(this._popover("", `<h3>${heading}</h3>
      <table><thead><tr><th>Wire</th><th>Colour</th><th>Gauge</th><th>To</th></tr></thead><tbody>${rows}</tbody></table>`)), [x - 6, y - 6, x + 6, y + 6]);
  }

  // A cable's popover lists its conductors; picking one selects it, lighting the sheath with it.
  // A cable is cut as one item: its popover gives the cut and jacket lengths, and at each end
  // the jacket to strip back and the leads, grouped by the connector they go to.
  _cablePopover(cable, x, y) {
    const wires = cable.wires.map((id) => this._model.wires.find((w) => w.id === id));
    const endRows = (cable.ends || []).flatMap((end) => {
      const groups = new Map();
      for (const wire of wires) {
        const key = `${endBeyond(wire.route, end.node, cable.run)}|${end.leads[wire.id]}`;
        groups.set(key, [...(groups.get(key) || []), wire]);
      }
      return [...groups.entries()].map(([key, members], index) => {
        const [connector, lead] = key.split("|");
        return `<tr>${index ? "<td></td><td></td>" : `<td>${escapeHtml(end.node)}</td><td>${escapeHtml(end.strip_back)}</td>`}
          <td>${escapeHtml(connector)}</td><td>${members.map((w) => swatch(w)).join(" ")}</td><td>${escapeHtml(lead)}</td></tr>`;
      });
    }).join("");
    const heading = [cable.id, cable.description, cable.part_number].filter(Boolean).map(escapeHtml).join(" · ");
    const summary = cable.cut_length ? `<p class="mono">Cut <b>${escapeHtml(cable.cut_length)}</b> · jacket ${escapeHtml(cable.jacket_length)} · ${cable.conductors} conductors</p>` : "";
    const conductorRows = wires.map((w) => `<tr data-pick="${escapeHtml(w.id)}"><td>${escapeHtml(w.id)}</td><td>${swatch(w)}</td>
      <td>${escapeHtml(w.signal)}</td><td>${escapeHtml(w.from.connector)}:${escapeHtml(w.from.pin)} → ${escapeHtml(w.to.connector)}:${escapeHtml(w.to.pin)}</td></tr>`).join("");
    this._place(this._picking(this._popover("", `<h3>${heading}</h3>${summary}
      <table><thead><tr><th>End</th><th>Strip</th><th>To</th><th>Conductors</th><th>Lead</th></tr></thead><tbody>${endRows}</tbody></table>
      <table><thead><tr><th>Conductor</th><th>Colour</th><th>Signal</th><th>From → to</th></tr></thead><tbody>${conductorRows}</tbody></table>`)),
      [x - 6, y - 6, x + 6, y + 6]);
  }

  // A bundle's popover lists the wires in it; picking a row selects that wire.
  _segmentPopover(key, x, y) {
    const segment = this._model.segments.find((s) => `${s.nodes[0]}|${s.nodes[1]}` === key);
    const rows = segment.wires.map((id) => this._model.wires.find((w) => w.id === id)).map((w) =>
      `<tr data-pick="${escapeHtml(w.id)}"><td>${escapeHtml(w.id)}</td><td>${swatch(w)}</td><td>${escapeHtml(w.signal)}</td>
        <td>${escapeHtml(w.from.connector)}:${escapeHtml(w.from.pin)} → ${escapeHtml(w.to.connector)}:${escapeHtml(w.to.pin)}</td></tr>`).join("");
    this._place(this._picking(this._popover("", `<h3>${escapeHtml(segment.nodes.join("–"))} · ${escapeHtml(segment.length)} · ${segment.wires.length} wires</h3>
      <table><thead><tr><th>Wire</th><th>Colour</th><th>Signal</th><th>From → to</th></tr></thead><tbody>${rows}</tbody></table>`)), [x - 6, y - 6, x + 6, y + 6]);
  }

  _picking(popover) {
    for (const row of popover.querySelectorAll("[data-pick]")) {
      row.addEventListener("click", () => {
        const bounds = this._stage.getBoundingClientRect(), place = popover.getBoundingClientRect();
        this._select({ kind: "wire", id: row.dataset.pick }, place.left - bounds.left + place.width / 2, place.top - bounds.top);
      });
    }
    return popover;
  }

  // Place a popover beside a box on the stage (below it, above it, right of it, then left),
  // clear of the popovers already shown and of any boxes it must not cover, such as the
  // connectors a wire's popovers are about. Each candidate is kept inside the stage.
  _place(popover, around, keepClear = []) {
    this._stage.append(popover);
    const width = popover.offsetWidth, height = popover.offsetHeight;
    const stageWidth = this._stage.clientWidth, stageHeight = this._stage.clientHeight;
    const blocked = [...[...this._stage.querySelectorAll(".popover")].filter((other) => other !== popover)
      .map((other) => [other.offsetLeft, other.offsetTop, other.offsetLeft + other.offsetWidth, other.offsetTop + other.offsetHeight]),
      ...keepClear, around];
    const [l, t, r, b] = around, cx = (l + r) / 2, cy = (t + b) / 2, gap = 8;
    const candidates = [[cx - width / 2, b + gap], [cx - width / 2, t - height - gap], [r + gap, cy - height / 2], [l - width - gap, cy - height / 2],
      ...blocked.flatMap(([bl, bt, br, bb]) => [[cx - width / 2, bb + gap], [cx - width / 2, bt - height - gap], [br + gap, bt], [bl - width - gap, bt]])]
      .map(([x, y]) => [Math.min(Math.max(x, 6), stageWidth - width - 6), Math.min(Math.max(y, 6), stageHeight - height - 6)]);
    const clear = ([x, y]) => blocked.every(([bl, bt, br, bb]) => x + width <= bl || x >= br || y + height <= bt || y >= bb);
    const [left, top] = candidates.find(clear) ?? candidates[0];
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  }

  // The box a body takes up on the stage, from its projected corners.
  _bodyBox(body) {
    const [x, , z] = bodyFrame(body.axis).map((axis) => axis);
    const half = body.size.map((size) => size / 2);
    const corners = [-1, 1].flatMap((a) => [-1, 1].flatMap((b) => [-1, 1].map((c) =>
      add(body.centre, add(add(scale(x, a * half[0]), scale([0, 1, 0], b * half[1])), scale(z, c * half[2]))))));
    const points = corners.map((corner) => this._toScreen(corner));
    return [Math.min(...points.map((p) => p[0])), Math.min(...points.map((p) => p[1])), Math.max(...points.map((p) => p[0])), Math.max(...points.map((p) => p[1]))];
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
      <table><thead><tr><th>Pin</th><th>Signal</th><th>Wire</th><th>Colour</th><th>To</th></tr></thead><tbody>${rows}</tbody></table>`),
      this._bodyBox((this.view === "2d" ? this._plan : this._scene).bodies.find((b) => b.connector.id === id)));
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

  // The wire's row sits by the wire (in 3D, at its middle; in 2D, where it was picked), and a
  // small popover at each end shows the pin it lands in.
  _wirePopovers(id, x, y) {
    const wire = this._model.wires.find((w) => w.id === id);
    const toScreen = (point) => this._toScreen(point);
    const plan = this.view === "2d";
    const points = this._scene.wires.find((entry) => entry.wire.id === id).points;
    const [mx, my] = plan ? [x, y] : toScreen(points[Math.floor(points.length / 2)]);
    const leads = conductorLeads(this._model, wire);
    // Wire ends at a splice have no popover of their own: the splice's sleeve shows them meeting.
    const ends = [wire.from, wire.to].map((end) => ({ end, body: (plan ? this._plan : this._scene).bodies.find((b) => b.connector.id === end.connector) }))
      .filter(({ body }) => body && body.kind === "connector").map((entry) => ({ ...entry, box: this._bodyBox(entry.body) }));
    this._place(this._popover("", `<h3>${escapeHtml(wire.id)} · ${escapeHtml(wire.signal || "")}</h3>
      <table><thead><tr><th>From</th><th>To</th><th>Gauge</th><th>Colour</th><th>${leads ? "Leads" : "Cut"}</th></tr></thead>
      <tbody><tr><td>${escapeHtml(wire.from.connector)}:${escapeHtml(wire.from.pin)}</td><td>${escapeHtml(wire.to.connector)}:${escapeHtml(wire.to.pin)}</td>
      <td>${escapeHtml(wire.gauge) || '<span class="na">not stated</span>'}</td><td>${swatch(wire)}</td>
      <td>${leads ? `${escapeHtml(leads[0])} / ${escapeHtml(leads[1])} <span class="na">(in ${escapeHtml(wire.cable)})</span>` : escapeHtml(wire.cut_length)}</td></tr></tbody></table>`),
      [mx - 10, my - 10, mx + 10, my + 10], ends.map(({ box }) => box));
    for (const { end, body, box } of ends) {
      const connector = body.connector;
      const content = connector.face ? pinoutSvg(connector, this._model, end.pin)
        : `<span class="mono">${escapeHtml(end.connector)} pin ${escapeHtml(end.pin)}</span>`;
      this._place(this._popover("small", `<h3>${escapeHtml(end.connector)}:${escapeHtml(end.pin)}</h3>${content}`), box,
        ends.map((other) => other.box));
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

// The end of a conductor's route that lies beyond the given end of its cable's jacket run.
function endBeyond(route, runEnd, run) {
  const inner = runEnd === run[0] ? run[1] : run.at(-2);
  return route.indexOf(inner) > route.indexOf(runEnd) ? route[0] : route.at(-1);
}

// A conductor's leads beyond its cable's jacket, at its from end and its to end.
function conductorLeads(model, wire) {
  const cable = (model.cables || []).find((c) => c.id === wire.cable);
  if (!cable?.ends) return null;
  const leadAt = (connector) => cable.ends.find((end) => endBeyond(wire.route, end.node, cable.run) === connector)?.leads[wire.id] ?? "";
  return [leadAt(wire.from.connector), leadAt(wire.to.connector)];
}

// What a harness is made of, counted the way it is built: loose wires, and cables as one each.
function contentsText(model) {
  const loose = model.wires.filter((wire) => !wire.cable).length, cables = (model.cables || []).length;
  const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;
  return [loose || !cables ? plural(loose, "wire") : "", cables ? plural(cables, "cable") : ""].filter(Boolean).join(" · ");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

if (globalThis.customElements && !customElements.get("wire-harness-explorer")) {
  customElements.define("wire-harness-explorer", WireHarnessExplorer);
}

export { WireHarnessExplorer, version, samplePath, buildScene, buildPlan, planSvg, pinoutSvg, boxMesh, fitDistance, viewBasis, fieldOfView };
