"""The harness layout as a tree of segments, and each wire's route and cut length through it."""
import math
from collections import defaultdict
from dataclasses import dataclass

from harness.source import Findings, HarnessSource, conventions, format_length, twist_takeup, wire_connectors
from harness.validation import parse_segment_length, segment_ends, segment_length_value

Segment = frozenset  # the two nodes a segment joins, in no order


# The layout read as a tree hanging from its root connector. Every node but the root has
# one parent. A segment's length is None while it is unknown; an unknown length may still
# have a known minimum. Depths are from the root: exact when every segment on the way is
# known, a minimum when every unknown one has a minimum.
@dataclass
class HarnessTree:
    root: str
    parent: dict[str, str | None]
    children: dict[str, list[str]]
    segment_lengths: dict[Segment, float | None]
    segment_minimums: dict[Segment, float]
    depth: dict[str, float | None]
    minimum_depth: dict[str, float | None]
    order: list[str]
    nodes: set[str]
    stand_in_length: float

    def length_or_minimum(self, segment: Segment) -> float | None:
        """A segment's length, or its minimum while the length is unknown, or None."""
        length = self.segment_lengths[segment]
        return length if length is not None else self.segment_minimums.get(segment)

    def path(self, start: str, end: str) -> list[tuple[str, str]]:
        """The segments from start to end, each as an ordered pair of nodes."""
        start_chain, end_chain = self.chain_to_root(start), self.chain_to_root(end)
        on_start_chain = set(start_chain)
        meeting = next(node for node in end_chain if node in on_start_chain)
        nodes = start_chain[:start_chain.index(meeting) + 1] + end_chain[:end_chain.index(meeting)][::-1]
        return list(zip(nodes, nodes[1:]))

    def chain_to_root(self, node: str) -> list[str]:
        chain = []
        while node is not None:
            chain.append(node)
            node = self.parent[node]
        return chain

    def is_leaf(self, node: str) -> bool:
        return not self.children.get(node)

    def neighbour_toward_body(self, node: str) -> str | None:
        """The node next to this one along its own segment: its parent, or the root's first child."""
        if node != self.root:
            return self.parent.get(node)
        return next(iter(self.children[node]), None)

    def drawn_length(self, segment: Segment) -> float:
        """A segment's length for laying out the sheet: a TBD one draws as the median known."""
        length = self.segment_lengths[segment]
        if length is not None:
            return length
        known = sorted(value for value in self.segment_lengths.values() if value is not None)
        stand_in = known[len(known) // 2] if known else float(self.stand_in_length)
        return max(stand_in, self.segment_minimums.get(segment, 0))


# A wire's way through the tree and the length to cut it; both are empty or None when the
# wire's connectors are not on the layout. Through an unknown segment the length is None,
# and its minimum is known when every unknown segment on the way has a minimum.
@dataclass
class Route:
    segments: list[tuple[str, str]]
    cut_length: float | None
    minimum_cut_length: float | None = None

    def cut_length_text(self) -> str:
        """The cut length as printed: the length, ≥ its minimum, or TBD."""
        if self.cut_length is None and self.minimum_cut_length is not None:
            return f"≥{format_length(self.minimum_cut_length)}"
        return format_length(self.cut_length)

    def node_names(self) -> list[str]:
        """The nodes the route passes, in order."""
        if not self.segments:
            return []
        return [start for start, _ in self.segments] + [self.segments[-1][1]]


# Walk the layout breadth-first from its root. A node met twice is a loop, a node never met
# is disconnected; both are errors, and a layout with no usable root has no tree at all.
def build_tree(source: HarnessSource, findings: Findings) -> HarnessTree | None:
    """The layout's tree, or None when it has no root on any segment."""
    layout = source["layout"]
    segments = layout.get("segments") or []
    neighbours = defaultdict(list)
    segment_lengths, segment_minimums = {}, {}
    for segment in segments:
        start, end = segment_ends(segment)
        length, minimum = parse_segment_length(segment_length_value(segment))
        neighbours[start].append(end)
        neighbours[end].append(start)
        segment_lengths[frozenset((start, end))] = length
        if minimum is not None:
            segment_minimums[frozenset((start, end))] = minimum
    root = layout.get("root") or next(iter(source["connectors"]), None)
    if root not in neighbours:
        findings.error(f"layout.root '{root}' is not on any segment")
        return None
    parent, order, seen = {root: None}, [root], {root}
    for node in order:
        for neighbour in neighbours[node]:
            if neighbour in seen:
                if parent[node] != neighbour:
                    findings.error(f"layout has a loop through {'-'.join(sorted((node, neighbour)))}; a harness layout must be a tree")
                continue
            seen.add(neighbour)
            parent[neighbour] = node
            order.append(neighbour)
    for node in set(neighbours) - seen:
        findings.error(f"layout node {node} is not connected to root {root}")
    if len(segments) != len(seen) - 1 and not findings.error_count:
        findings.error("layout segment count does not match a tree (duplicate segments?)")
    children = defaultdict(list)
    for node in order[1:]:
        children[parent[node]].append(node)
    depth, minimum_depth = {root: 0.0}, {root: 0.0}
    for node in order[1:]:
        segment = frozenset((node, parent[node]))
        length, parent_depth = segment_lengths[segment], depth[parent[node]]
        depth[node] = None if length is None or parent_depth is None else parent_depth + length
        least, parent_least = segment_minimums.get(segment) if length is None else length, minimum_depth[parent[node]]
        minimum_depth[node] = None if least is None or parent_least is None else parent_least + least
    return HarnessTree(root, parent, children, segment_lengths, segment_minimums, depth, minimum_depth, order, seen,
                       conventions(source["drawing"])["stand_in_length"])


# Wires twisted together lie twisted only where they run together: the segments every wire
# of the group passes through.
def twisted_segments(source: HarnessSource, tree: HarnessTree) -> list[set[Segment]]:
    """For each wire, in source order, the set of segments over which it is twisted."""
    groups = defaultdict(list)
    for wire in source["wires"]:
        ends = wire_connectors(wire)
        if wire.get("twist") and all(end in tree.nodes for end in ends):
            groups[wire["twist"]].append({frozenset(segment) for segment in tree.path(*ends)})
    shared = {twist: set.intersection(*paths) for twist, paths in groups.items()}
    return [shared.get(wire.get("twist"), set()) for wire in source["wires"]]


# A cut length is the route's segments, plus twist take-up over the twisted run, plus the
# per-wire extra and each end's allowance, rounded up to round_to. A loopback (both ends on
# one connector) has no segments and is cut to loopback_length. A length override is used as
# given. Through unknown segments that all have minimums, the same sum of the minimums is the
# minimum cut length.
def route_wires(source: HarnessSource, tree: HarnessTree | None) -> list[Route]:
    """Each wire's route and cut length, in source order."""
    twisted = twisted_segments(source, tree) if tree else [set() for _ in source["wires"]]
    routes = []
    for wire, twisted_run in zip(source["wires"], twisted):
        start, end = wire_connectors(wire)
        if tree is None or start not in tree.nodes or end not in tree.nodes:
            routes.append(Route([], None))
            continue
        segments = tree.path(start, end)
        if "length" in wire:
            routes.append(Route(segments, float(wire["length"])))
            continue
        lengths = {frozenset(segment): tree.segment_lengths[frozenset(segment)] for segment in segments}
        if None not in lengths.values():
            routes.append(Route(segments, cut_length(source, wire, lengths, twisted_run)))
            continue
        least = {segment: tree.length_or_minimum(segment) for segment in lengths}
        minimum = None if None in least.values() else cut_length(source, wire, least, twisted_run)
        routes.append(Route(segments, None, minimum))
    return routes


def cut_length(source: HarnessSource, wire: dict, lengths: dict[Segment, float], twisted_run: set[Segment]) -> float:
    """The cut length of a wire over segments of the given lengths."""
    drawing = source["drawing"]
    start, end = wire_connectors(wire)
    length = sum(lengths.values()) + twist_takeup(drawing) * sum(lengths[segment] for segment in twisted_run)
    if not lengths:
        length = float(drawing.get("loopback_length", conventions(drawing)["loopback_length"]))
    length += float(drawing.get("extra_per_wire", 0))
    length += float(source["connectors"].get(start, {}).get("wire_allowance", 0))
    length += float(source["connectors"].get(end, {}).get("wire_allowance", 0))
    rounding = float(drawing.get("round_to", conventions(drawing)["round_to"]))
    return math.ceil(round(length / rounding, 9)) * rounding


def wire_counts_by_segment(routes: list[Route]) -> dict[Segment, int]:
    """How many wires run through each segment."""
    counts = defaultdict(int)
    for route in routes:
        for segment in route.segments:
            counts[frozenset(segment)] += 1
    return counts
