// The explorer component's pure parts, run with node --test from tests/test_explorer_component.py.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const root = new URL("..", import.meta.url);
const componentPath = new URL("skills/wire-harness-drawing/explorer/wire-harness-explorer.js", root);
const { boxMesh, buildPlan, buildScene, pinoutSvg, planSvg, samplePath, version } = await import(componentPath);
const example = JSON.parse(readFileSync(new URL("example/example.harness.json", root), "utf8"));
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
