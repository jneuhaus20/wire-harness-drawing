// The explorer component's pure parts, run with node --test from tests/test_explorer_component.py.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const root = new URL("..", import.meta.url);
const componentPath = new URL("skills/wire-harness-drawing/explorer/wire-harness-explorer.js", root);
const { buildPlan, buildScene, pinoutSvg, planSvg, samplePath, version } = await import(componentPath);
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
  assert.equal(scene.sizes.wire, 0.9);
  const [xs, , zs] = scene.bounds;
  assert.ok(Math.abs(xs[0] - 0) < 5 && Math.abs(xs[1] - 600) < 5, `x spans ${xs}`);
  assert.ok(zs[1] > 140 && zs[1] < 160, `z reaches ${zs[1]}`);
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
