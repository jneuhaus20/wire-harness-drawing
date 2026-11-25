// The explorer component's pure parts, run with node --test from tests/test_explorer_component.py.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const root = new URL("..", import.meta.url);
const componentPath = new URL("skills/wire-harness-drawing/explorer/wire-harness-explorer.js", root);
const { bodyMesh, bodyNote, decodeMesh, boxMesh, buildPlan, buildScene, cableEndsTable, pinoutSvg, planSvg, samplePath, version, zoomedViewBox } = await import(componentPath);
const example = JSON.parse(readFileSync(new URL("examples/sensor-branch/sensor-branch.harness.json", root), "utf8"));
const routed = JSON.parse(process.env.ROUTED_MODEL);

const near = (a, b, tolerance) => Math.hypot(...a.map((value, i) => value - b[i])) <= tolerance;

test("the component never closes a script element, so it can be inlined in a page", () => {
  assert.ok(!readFileSync(componentPath, "utf8").includes("</" + "script"));
});

test("the version in the file header matches the exported version", () => {
  assert.match(readFileSync(componentPath, "utf8").split("\n")[0], new RegExp(`> ${version.replaceAll(".", "\\.")} `));
});

test("bundle paths sample through their curves to their end points", () => {
  const points = samplePath("M0,0 C10,0 10,20 20,20 L40,20");
  assert.deepEqual(points[0], [0, 0]);
  assert.deepEqual(points.at(-1), [40, 20]);
  assert.ok(points.length > 20);
});

test("every wire of the example runs from its first route node to its last", () => {
  const scene = buildScene(example);
  assert.equal(scene.wires.length, example.wires.length);
  const nodes = Object.fromEntries(example.nodes.map((node) => [node.id, [node.x, 0, node.y]]));
  for (const { wire, points } of scene.wires) {
    assert.ok(near(points[0], nodes[wire.route[0]], 40), `${wire.id} starts at ${wire.route[0]}`);
    assert.ok(near(points.at(-1), nodes[wire.route.at(-1)], 40), `${wire.id} ends at ${wire.route.at(-1)}`);
  }
  assert.equal(scene.bodies.length, example.nodes.filter((node) => node.kind !== "breakout").length);
});

test("a routed harness is drawn in its true units at nominal sizes", () => {
  const scene = buildScene(routed);
  assert.ok(scene.sizes.wire >= 0.9, "never thinner than a real wire");
  assert.ok(Math.abs(scene.sizes.wire / scene.sizes.thickened - 0.9) < 1e-9, "the thickening is reported exactly");
  const points = scene.wires.flatMap((wire) => wire.points);
  const [xs, zs] = [0, 2].map((axis) => [Math.min(...points.map((p) => p[axis])), Math.max(...points.map((p) => p[axis]))]);
  assert.ok(Math.abs(xs[0] - 0) < 5 && Math.abs(xs[1] - 600) < 5, `x spans ${xs}`);
  assert.ok(zs[1] > 140 && zs[1] < 160, `z reaches ${zs[1]}`);
});

test("a twisted pair winds round its shared centre and a cable gets a jacket", () => {
  const twisted = JSON.parse(process.env.TWISTED_MODEL);
  const scene = buildScene(twisted);
  const [first, second] = ["W1", "W2"].map((id) => scene.wires.find((entry) => entry.wire.id === id).points);
  const heights = first.map((point) => point[1]);
  assert.ok(Math.max(...heights) - Math.min(...heights) > scene.sizes.pitch * 0.9, "W1 rises and falls as it winds");
  const middle = Math.floor(first.length / 2);
  assert.ok(near(first[middle], second[middle], scene.sizes.pitch * 1.2), "the pair stays together");
  assert.deepEqual(scene.jackets.map((jacket) => jacket.cable), ["C1"]);
  const [sheath] = scene.jackets;
  for (const [end, node] of [[sheath.points[0], "P1"], [sheath.points.at(-1), "J1"]]) {
    assert.ok(near(end, scene.positions[node], Infinity) && Math.hypot(end[0] - scene.positions[node][0], end[2] - scene.positions[node][2]) >= scene.sizes.exit * 0.9,
      `the sheath stops short of ${node} so its conductors can leave it`);
  }
  assert.ok(planSvg(twisted, buildPlan(twisted)).includes('data-cable="C1"'));
});

test("the 2D view draws every wire and connector as something to click", () => {
  for (const model of [example, routed]) {
    const svg = planSvg(model, buildPlan(model));
    for (const wire of model.wires) assert.ok(svg.includes(`data-wire="${wire.id}"`), wire.id);
    for (const connector of model.connectors) assert.ok(svg.includes(`data-connector="${connector.id}"`), connector.id);
  }
});

test("a pinout is drawn only from a stated face, with the chosen pin ringed", () => {
  const j1 = example.connectors.find((c) => c.id === "J1");
  const svg = pinoutSvg(j1, example, "3");
  assert.equal((svg.match(/<circle/g) || []).length, 5, "four cavities and one ring");
  assert.equal(pinoutSvg(example.connectors.find((c) => c.id === "E1"), example, "1"), "");
});

test("a body tilted out of the table is still a right-angled box", () => {
  const mesh = boxMesh([0, 0, 0], [0.6, -0.8, 0], [30, 10, 20], [1, 1, 1]);
  const corners = [];
  for (let i = 0; i < mesh.positions.length; i += 3) corners.push(mesh.positions.slice(i, i + 3).map((v) => Math.round(v * 1e6) / 1e6).join(","));
  const unique = [...new Set(corners)].map((corner) => corner.split(",").map(Number));
  assert.equal(unique.length, 8);
  const distances = unique.flatMap((a, i) => unique.slice(i + 1).map((b) => Math.round(Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) * 1e3) / 1e3));
  const expected = [10, 20, 30, Math.hypot(10, 20), Math.hypot(10, 30), Math.hypot(20, 30), Math.hypot(10, 20, 30)].map((d) => Math.round(d * 1e3) / 1e3);
  assert.deepEqual([...new Set(distances)].sort((a, b) => a - b), expected.sort((a, b) => a - b));
});

test("splices at the same place stack instead of overlapping", () => {
  const scene = buildScene(JSON.parse(process.env.STACKED_MODEL));
  const [first, second] = scene.bodies.filter((body) => body.kind === "splice");
  assert.equal(Math.round(first.centre[0]), Math.round(second.centre[0]));
  assert.ok(Math.abs(first.centre[1] - second.centre[1]) >= scene.sizes.wire * 3, "one sleeve sits above the other");
});

test("a split cable's sheath runs to where its conductors part and stops short of its connector end", () => {
  const split = JSON.parse(process.env.SPLIT_MODEL);
  const scene = buildScene(split);
  const [sheath] = scene.jackets;
  const b2 = scene.positions.B2, p1 = scene.positions.P1;
  assert.ok(Math.abs(sheath.points.at(-1)[0] - b2[0]) < 1 && Math.abs(sheath.points.at(-1)[2] - b2[2]) < scene.sizes.pitch * 3, "ends at B2");
  assert.ok(Math.abs(sheath.points[0][0] - p1[0]) >= scene.sizes.exit * 0.9, "stops short of P1");
  const svg = planSvg(split, buildPlan(split));
  assert.ok(svg.includes('data-cable="W5"'));
  assert.equal((svg.match(/data-segment="B2\|J2"/g) || []).length, 1, "beyond the jacket the conductors are a loose bundle");
  assert.equal((svg.match(/data-segment="B1\|B2"/g) || []).length, 0, "under the jacket they are not drawn as a bundle");
});

test("the initial view fits the whole harness in a frame of any shape, without leaving it small", async () => {
  const { fitDistance, viewBasis, fieldOfView } = await import(componentPath);
  const bounds = [[0, 500], [-20, 20], [-10, 10]];
  const corners = [0, 1, 2, 3, 4, 5, 6, 7].map((k) => bounds.map(([low, high], axis) => ((k >> axis) & 1 ? high : low)));
  const centre = bounds.map(([low, high]) => (low + high) / 2);
  for (const aspect of [0.6, 1, 2.2]) {
    const distance = fitDistance(bounds, -0.35, 0.9, aspect);
    const [right, up, toward] = viewBasis(-0.35, 0.9);
    const tangent = Math.tan(fieldOfView / 2);
    const reach = corners.map((corner) => {
      const offset = corner.map((value, axis) => value - centre[axis]);
      const dot = (a) => a.reduce((sum, value, axis) => sum + value * offset[axis], 0);
      const depth = distance - dot(toward);
      return Math.max(Math.abs(dot(right)) / (depth * tangent * aspect), Math.abs(dot(up)) / (depth * tangent));
    });
    assert.ok(Math.max(...reach) <= 1, `aspect ${aspect}: a corner is out of view`);
    assert.ok(Math.max(...reach) >= 0.75, `aspect ${aspect}: the harness fills too little of the view`);
  }
});

test("the pinout popover puts each numbered contact where the model's face does, scaled evenly", () => {
  const xlr = JSON.parse(readFileSync(new URL("examples/xlr-mic-cable/xlr-mic-cable.harness.json", root), "utf8"));
  for (const connector of xlr.connectors) {
    const svg = pinoutSvg(connector, xlr, null);
    const circles = [...svg.matchAll(/<circle cx="([-\d.]+)" cy="([-\d.]+)" r="10"/g)].map((m) => [Number(m[1]), Number(m[2])]);
    const labels = [...svg.matchAll(/<text[^>]*>([^<]+)<\/text>/g)].map((m) => m[1]);
    const face = connector.face.cavities;
    const [a, b] = Object.keys(face);
    const drawn = Object.fromEntries(labels.map((label, i) => [label, circles[i]]));
    const scale = Math.hypot(drawn[b][0] - drawn[a][0], drawn[b][1] - drawn[a][1]) / Math.hypot(face[b][0] - face[a][0], face[b][1] - face[a][1]);
    for (const [pin, [x, y]] of Object.entries(face)) {
      assert.ok(near(drawn[pin], [drawn[a][0] + scale * (x - face[a][0]), drawn[a][1] + scale * (y - face[a][1])], 0.01), `${connector.id} pin ${pin}`);
    }
  }
});

test("zooming the 2D view keeps the point under the pointer where it is", () => {
  const box = [0, 0, 400, 200];
  const zoomed = zoomedViewBox(box, 0.5, [100, 50]);
  assert.deepEqual(zoomed, [50, 25, 200, 100]);
  const back = zoomedViewBox(zoomed, 2, [100, 50]);
  assert.deepEqual(back, box);
});

test("a cable's ends table reads End, Lead, Strip, To, Conductors, one group of rows per end", () => {
  const model = JSON.parse(readFileSync(new URL("examples/split-cable/split-cable.harness.json", root), "utf8"));
  const [cable] = model.cables;
  const html = cableEndsTable(cable, model);
  const headings = [...html.matchAll(/<th>([^<]+)<\/th>/g)].map((m) => m[1]);
  assert.deepEqual(headings, ["End", "Lead (mm)", "Strip (mm)", "To", "Conductors"]);
  assert.equal([...html.matchAll(/<tbody class="end">/g)].length, cable.ends.length);
  const firstRow = html.match(/<tbody class="end"><tr>(.*?)<\/tr>/s)[1];
  assert.deepEqual([...firstRow.matchAll(/<td>([^<]*)/g)].slice(0, 3).map((m) => m[1]), ["P1", "40", "40"]);
});

test("a shielded cable shows its shield where the jacket ends, in 3D and in 2D", () => {
  const model = JSON.parse(readFileSync(new URL("examples/twist-and-cable/twist-and-cable.harness.json", root), "utf8"));
  const [cable] = model.cables;
  assert.equal(cable.shield, true);
  const scene = buildScene(model);
  const [jacket] = scene.jackets;
  assert.equal(jacket.shield, true);
  assert.equal(scene.shieldBands.length, 2, "a band of shield at each end of the jacket");
  const plain = buildScene({ ...model, cables: [{ ...cable, shield: false }] });
  assert.equal(plain.shieldBands.length, 0);
  assert.match(planSvg(model, buildPlan(model)), /class="shield"/);
  assert.doesNotMatch(planSvg({ ...model, cables: [{ ...cable, shield: false }] }, buildPlan({ ...model, cables: [{ ...cable, shield: false }] })), /class="shield"/);
});

test("a stated body is drawn at its size and colour; an unstated one is drawn plain and says so", () => {
  const model = JSON.parse(readFileSync(new URL("examples/taz6-y-z/taz6-y-z.harness.json", root), "utf8"));
  const stated = { ...model, connectors: model.connectors.map((c) => c.id === "J1" ? { ...c, body: { shape: "box", length: 6.35, width: 13.8, height: 4.5, color: "#ece6d6" } } : { ...c, body: null }) };
  const scene = buildScene(stated);
  const j1 = scene.bodies.find((b) => b.connector.id === "J1"), j2 = scene.bodies.find((b) => b.connector.id === "J2");
  assert.deepEqual(j1.size, [6.35, 4.5, 13.8]);
  assert.equal(j1.stated, true);
  assert.deepEqual(j1.color.map((v) => Math.round(v * 255)), [0xec, 0xe6, 0xd6]);
  assert.equal(j2.stated, false);
  assert.ok(Math.min(...j2.color) > 0.4, "an unstated body is a plain mid grey, not black");
  const dsub = buildScene({ ...stated, connectors: stated.connectors.map((c) => c.id === "J1" ? { ...c, body: { ...c.body, shape: "dsub" } } : c) });
  assert.ok(bodyMesh(dsub.bodies.find((b) => b.connector.id === "J1")).positions.length > bodyMesh(j1).positions.length);
});

test("a maker's model is decoded at its true size, turned so its mating face leads, and set behind its node", () => {
  const mesh = JSON.parse(readFileSync(new URL("tests/fixtures/ph-mesh.json", root), "utf8"));
  const decoded = decodeMesh(mesh);
  assert.equal(decoded.indices.length / 3, mesh.triangles);
  const xs = [], ys = [], zs = [];
  for (let i = 0; i < decoded.positions.length; i += 3) { xs.push(decoded.positions[i]); ys.push(decoded.positions[i + 1]); zs.push(decoded.positions[i + 2]); }
  assert.ok(Math.abs(Math.min(...xs) - mesh.min[0]) < 0.01 && Math.abs(Math.max(...zs) - mesh.max[2]) < 0.01);
  // KiCad's vertical header mates along +z; turned 90° about y, its mating face leads along +x
  // and its width (model x) stands up.
  const model = JSON.parse(readFileSync(new URL("examples/taz6-y-z/taz6-y-z.harness.json", root), "utf8"));
  const withModel = { ...model, connectors: model.connectors.map((c) => c.id === "J1" ? { ...c, body: { shape: "model", mesh, rotate: [0, 90, 0] } } : c) };
  const body = buildScene(withModel).bodies.find((b) => b.connector.id === "J1");
  const height = mesh.max[2] - mesh.min[2], width = mesh.max[0] - mesh.min[0], depth = mesh.max[1] - mesh.min[1];
  assert.ok(near(body.size, [height, width, depth], 0.02), `size ${body.size}`);
  const built = bodyMesh(body);
  const along = (p) => (p[0] - body.centre[0]) * body.axis[0] + (p[1] - body.centre[1]) * body.axis[1] + (p[2] - body.centre[2]) * body.axis[2];
  const points = [];
  for (let i = 0; i < built.positions.length; i += 3) points.push(built.positions.slice(i, i + 3));
  assert.ok(Math.abs(Math.min(...points.map(along)) + body.size[0] / 2) < 0.02, "the rear of the model is at the node");
});

test("a body not stated is a placeholder, drawn faint", () => {
  const model = JSON.parse(readFileSync(new URL("examples/two-wire/two-wire.harness.json", root), "utf8"));
  const body = buildScene(model).bodies.find((b) => b.connector.id === "P1");
  assert.equal(body.placeholder, true);
});

test("a datasheet body shows its cavities on its mating face, laid out as the face states", () => {
  const source = JSON.parse(readFileSync(new URL("examples/sensor-branch/sensor-branch.harness.json", root), "utf8"));
  const model = { ...source, connectors: source.connectors.map((c) => c.id === "J1" ? { ...c, body: { shape: "box", length: 12, width: 12, height: 5, color: "#ece6d6" } } : c) };
  const j1 = model.connectors.find((c) => c.id === "J1");
  assert.ok(j1.face, "the example states J1's face");
  const body = buildScene(model).bodies.find((b) => b.connector.id === "J1");
  const plain = bodyMesh({ ...body, connector: { ...body.connector, face: null } });
  const withFace = bodyMesh(body);
  assert.equal((withFace.positions.length - plain.positions.length) / 3, 24 * Object.keys(j1.face.cavities).length, "one small box per cavity");
});

test("the 2D view draws every loose wire in its colour along each bundle it runs in, not only where it fans out", () => {
  for (const model of [example, routed]) {
    const svg = planSvg(model, buildPlan(model));
    for (const wire of model.wires.filter((w) => w.colors.length && !w.cable)) {
      const strands = [...svg.matchAll(new RegExp(`<path[^>]*data-strand="${wire.id}"[^>]*>`, "g"))].map((m) => m[0]);
      assert.equal(strands.length, wire.route.length - 1, `${wire.id}: one strand per segment of its route`);
      assert.ok(strands.every((path) => path.includes(`stroke="${wire.colors[0]}"`)), `${wire.id} is drawn in ${wire.colors[0]}`);
    }
  }
});

test("the 2D view names every breakout, and gives each connector its label under its designator", () => {
  const svg = planSvg(example, buildPlan(example));
  for (const node of example.nodes.filter((n) => n.kind === "breakout")) {
    assert.match(svg, new RegExp(`<text[^>]*class="breakout"[^>]*>${node.id}</text>`), node.id);
  }
  for (const connector of example.connectors.filter((c) => c.label && !c.splice)) {
    assert.ok(svg.includes(`class="caption">${connector.label}</text>`), connector.id);
  }
});

test("the 2D view shows each label where sheet 1 draws it", () => {
  const svg = planSvg(example, buildPlan(example));
  assert.ok(example.labels.length > 0);
  for (const label of example.labels) {
    assert.match(svg, new RegExp(`<g class="label"[^>]*data-label="${label.text}"[^>]*>[^]*?x="${label.x}" y="${label.y}"`), label.text);
  }
});

test("2D text keeps its size on screen however the drawing is scaled to fit", async () => {
  const { planUnit } = await import(componentPath);
  assert.equal(planUnit([0, 0, 1000, 500], 500, 500), 2, "a wide box fits by its width");
  assert.equal(planUnit([0, 0, 1000, 500], 2000, 500), 1, "a tall stage fits by its height");
  const svg = planSvg(example, buildPlan(example));
  assert.doesNotMatch(svg, /<text[^>]*font-size=/, "no text carries its size in drawing units");
});

test("a model in one plain colour takes the body's stated colour", () => {
  const mesh = JSON.parse(readFileSync(new URL("examples/sensor-branch/meshes/22-01-3047.json", root), "utf8"));
  assert.equal(mesh.palette.length, 1);
  const model = JSON.parse(readFileSync(new URL("examples/two-wire/two-wire.harness.json", root), "utf8"));
  const tinted = { ...model, connectors: model.connectors.map((c) => c.id === "J1" ? { ...c, body: { shape: "model", mesh, rotate: [0, 90, 0], color: "#ece6d6" } } : c) };
  const body = buildScene(tinted).bodies.find((b) => b.connector.id === "J1");
  assert.deepEqual(body.model.colors[0].map((v) => Math.round(v * 255)), [0xec, 0xe6, 0xd6]);
});

test("a connector's popover notes its body only where the drawing could mislead: an outline or a placeholder", () => {
  assert.equal(bodyNote({ body: { shape: "model", mesh: {} } }, "mm"), "");
  assert.equal(bodyNote({ splice: true }, "mm"), "");
  assert.match(bodyNote({ body: { shape: "box", length: 12.7, width: 10.72, height: 6.63 } }, "mm"), /outline only, 12\.7 × 10\.72 × 6\.63 mm/);
  assert.match(bodyNote({ body: null }, "mm"), /not stated/);
});
