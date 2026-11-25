"""Sheet 1: the harness laid flat, as built on a formboard, not to scale."""
import math
import textwrap
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field

from harness.bom import BomLine, find_numbers, item_find_numbers
from harness.frame import Box, frame, frame_box, not_to_scale
from harness.routing import HarnessTree, Route, wire_counts_by_segment
from harness.source import (chosen_color, HarnessSource, color_parts, conventions, default_twist_takeup, display_color, format_length,
                            is_generic, is_splice, pins_of, tolerance_for, wire_end)
from harness.svg import (balloon_pitch, balloon_radius, balloon_row, balloon_stack, horizontal_dimension, ink, line, rect,
                         sheet_height, sheet_width, text, text_width)
from harness.validation import covered_segment_ends

SegmentLine = tuple[float, float, float, float]  # x1, y1, x2, y2

connector_body_width = 64
connector_fan_length = 26


# ---------- What the sheet draws ----------


# Everything sheet 1 draws, recorded by kind, so the sheet can be checked for what lies off
# it, on its blocks, or over other text. A leader or extension line names the items it may touch.
@dataclass
class SheetLayout:
    regions: dict[str, Box]
    texts: list[tuple[str, Box]] = field(default_factory=list)
    dimension_lines: list[tuple[str, Box]] = field(default_factory=list)
    bodies: list[tuple[str, Box]] = field(default_factory=list)
    leaders: list[tuple[str, SegmentLine, set[str]]] = field(default_factory=list)
    extension_lines: list[tuple[str, SegmentLine, set[str]]] = field(default_factory=list)
    labels: list[dict] = field(default_factory=list)  # each label as placed: its source fields and drawn centre
    bundles: list[tuple[str, list[tuple[float, float]], float, set[str]]] = field(default_factory=list)  # name, points, half width, touches
    touches: dict[str, set[str]] = field(default_factory=dict)  # what each drawn item is meant to touch
    owners: dict[str, str] = field(default_factory=dict)  # the node each drawn item belongs to
    placement: "Placement | None" = None

    def related(self, first: str, second: str) -> bool:
        """Whether two drawn items belong together, so one may touch the other."""
        return first == second or second in self.touches.get(first, ()) or first in self.touches.get(second, ())

    def place_label(self, label: dict, toward: str, x: float, y: float) -> None:
        """Record where a label is drawn, for the explorer to show it in the same place."""
        distance = float(label["distance"])
        self.labels.append({"text": label["text"], "at": label["at"], "toward": toward,
                            "distance": int(distance) if distance.is_integer() else distance,
                            "item": label.get("item", ""), "x": round(x, 1), "y": round(y, 1)})

    def boxes(self) -> list[tuple[str, Box]]:
        """Every recorded box, whatever its kind."""
        return self.texts + self.dimension_lines + self.bodies


def boxes_overlap(first: Box, second: Box) -> bool:
    return first[0] < second[2] and second[0] < first[2] and first[1] < second[3] and second[1] < first[3]


# Liang–Barsky clipping: does the segment pass through the inside of the box?
def segment_crosses_box(segment: SegmentLine, box: Box) -> bool:
    (x1, y1, x2, y2), (left, top, right, bottom) = segment, box
    start, end = 0.0, 1.0
    for p, q in ((-(x2 - x1), x1 - left), (x2 - x1, right - x1), (-(y2 - y1), y1 - top), (y2 - y1, bottom - y1)):
        if p == 0:
            if q <= 0:
                return False
            continue
        r = q / p
        if p < 0:
            start = max(start, r)
        else:
            end = min(end, r)
        if start >= end:
            return False
    return end - start > 1e-6


def inset(box: Box, by: float) -> Box:
    return (box[0] + by, box[1] + by, box[2] - by, box[3] - by)


# Everything sheet 1 prints must be readable: no text, balloon or body over another, over a
# bundle, or over a dimension line, and no leader or extension line through text. What belongs
# together may touch: a dimension's text sits on its own line, a connector on its own bundles, a
# label on the bundle it marks, a leader on its balloon and on what it points at.
@dataclass
class Collision:
    over: str  # the item drawn over the other
    under: str
    over_box: Box
    under_box: Box
    wording: str = "over"

    def text(self) -> str:
        return f"{self.over} {self.wording} {self.under}"


def bundle_box(points: list[tuple[float, float]], half_width: float) -> Box:
    return (min(p[0] for p in points) - half_width, min(p[1] for p in points) - half_width,
            max(p[0] for p in points) + half_width, max(p[1] for p in points) + half_width)


solid_gap = 2  # the least clear space between two printed things, so neither reads as part of the other


def collisions(layout: SheetLayout) -> list[Collision]:
    """Every pair of drawn items that lie over each other."""
    found = []
    solids = layout.texts + layout.bodies
    for index, (first, first_box) in enumerate(solids):
        for second, second_box in solids[index + 1:]:
            if not layout.related(first, second) and boxes_overlap(inset(first_box, -solid_gap), second_box):
                found.append(Collision(second, first, second_box, first_box))
    for bundle, points, half_width, ends in layout.bundles:
        for what, box in solids:
            if what in ends or layout.related(what, bundle):
                continue
            widened = (box[0] - half_width + 0.5, box[1] - half_width + 0.5, box[2] + half_width - 0.5, box[3] + half_width - 0.5)
            crossed = [(a, b) for a, b in zip(points, points[1:]) if segment_crosses_box((*a, *b), widened)]
            if crossed:
                found.append(Collision(what, bundle, box, bundle_box([p for pair in crossed for p in pair], half_width)))
    for dimension, line_box in layout.dimension_lines:
        for what, box in solids:
            if not layout.related(what, dimension) and boxes_overlap(inset(box, 0.5), inset(line_box, 3.5)):
                found.append(Collision(what, dimension, box, line_box))
    for leader, segment, exempt in layout.leaders:
        for what, box in solids + layout.dimension_lines:
            if what not in exempt and not layout.related(what, leader) and segment_crosses_box(segment, inset(box, 0.5)):
                found.append(Collision(f"{leader} leader", what, (min(segment[0], segment[2]), min(segment[1], segment[3]),
                                       max(segment[0], segment[2]), max(segment[1], segment[3])), box, "through"))
    for extension, segment, exempt in layout.extension_lines:
        for what, box in layout.texts:
            if what not in exempt and segment_crosses_box(segment, inset(box, 0.5)):
                found.append(Collision(extension, what, (segment[0], segment[1], segment[2], segment[3]), box, "through"))
    return found


def sheet_collisions(layout: SheetLayout) -> list[str]:
    """One line per pair of drawn items that lie over each other, later-drawn first."""
    return list(dict.fromkeys(collision.text() for collision in collisions(layout)))


# Name every part of the drawing that lies outside the sheet frame or on top of a block
# the frame or the notes occupy, so a drawing too big for its sheet is reported, never shipped.
def sheet_misfits(layout: SheetLayout) -> list[str]:
    """For each place a drawn item must not be, the items that are there: one line per place."""
    trespassers = defaultdict(list)
    left, top, right, bottom = frame_box
    for what, box in layout.boxes():
        if box[0] < left or box[1] < top or box[2] > right or box[3] > bottom:
            trespassers["off the sheet"].append(what)
        for region, region_box in layout.regions.items():
            if boxes_overlap(box, region_box):
                trespassers[f"on the {region}"].append(what)
    return [f"{place}: {', '.join(dict.fromkeys(whats))}" for place, whats in trespassers.items()]


# A horizontal dimension: line, arrowheads, label (on the line when it fits, above it when
# not) and extension lines from extension_from=(y1, y2), each recorded under what.
def draw_dimension(layout: SheetLayout, what: str, x1, x2, y, label, extension_from=None) -> str:
    """Draw a horizontal dimension and record its parts."""
    if extension_from:
        for x, start in ((x1, extension_from[0]), (x2, extension_from[1])):
            if start is not None:
                layout.extension_lines.append((f"{what} extension", (x, start, x, y + (4 if y > start else -4)), {what}))
    label_width = text_width(label, 11, False) + 8
    middle = (x1 + x2) / 2
    on_line = x2 - x1 > label_width + 20
    layout.texts.append((what, (middle - label_width / 2, y - 7, middle + label_width / 2, y + 7) if on_line
                         else (middle - label_width / 2, y - 16, middle + label_width / 2, y - 2)))
    layout.dimension_lines.append((what, (x1, y - 4, x2, y + 4)))
    return horizontal_dimension(x1, x2, y, label, extension_from)


# A column of balloons whose first one points at (target_x, target_y). The leader is recorded
# from the balloon's edge, since the balloon covers the part inside it.
def draw_balloons(layout: SheetLayout, what: str, x, y, numbers, target_x, target_y, target: str,
                  quantities=None) -> str:
    """Draw a balloon stack with its leader and record both."""
    widest_quantity = max([text_width(quantity, 10, False) + 3 for quantity in (quantities or {}).values()] or [0])
    layout.texts.append((what, (x - balloon_radius, y - balloon_radius, x + balloon_radius + widest_quantity,
                                y + balloon_pitch * (len(numbers) - 1) + balloon_radius)))
    reach = math.hypot(target_x - x, target_y - y) or 1
    edge_x = x + balloon_radius * (target_x - x) / reach
    edge_y = y + balloon_radius * (target_y - y) / reach
    layout.leaders.append((what, (edge_x, edge_y, target_x, target_y), {what, target}))
    return balloon_stack(x, y, numbers, target_x, target_y, quantities)


# A dashed extension line from (x, y1) down to y2, broken wherever it would cross text, as
# drafting practice keeps text clear of lines.
def draw_broken_extension(layout: SheetLayout, what: str, x, y1, y2, exempt: set[str]) -> str:
    """Draw a vertical dashed extension line with gaps at text."""
    gaps = sorted((box[1] - 3, box[3] + 3) for name, box in layout.texts
                  if name not in exempt and box[0] - 1 <= x <= box[2] + 1 and box[1] < y2 and box[3] > y1)
    pieces, top = [], y1
    for gap_top, gap_bottom in gaps:
        if gap_top > top:
            pieces.append((top, gap_top))
        top = max(top, gap_bottom)
    if top < y2:
        pieces.append((top, y2))
    out = []
    for piece_top, piece_bottom in pieces:
        layout.extension_lines.append((what, (x, piece_top, x, piece_bottom), exempt))
        out.append(line(x, piece_top, x, piece_bottom, 0.5, "#777", 'stroke-dasharray="4 3"'))
    return "".join(out)


# ---------- Placing the nodes ----------


# Where sheet 1 draws each node. A routed harness also has each segment's drawn points, from
# its parent to its child, and the denominator of the scale it is drawn at.
@dataclass
class Placement:
    x: dict[str, float]
    y: dict[str, float]
    segment_points: dict[tuple[str, str], list[tuple[float, float]]] = field(default_factory=dict)
    scale_denominator: float | None = None
    units_to_sheet: float | None = None
    lane_of: dict[str, int] = field(default_factory=dict)  # each node's lane, top to bottom, on a drawing not to scale
    minimum_pitches: list[float] = field(default_factory=list)  # the least space asked for between each pair of lanes
    bends: dict[tuple[str, str], float] = field(default_factory=dict)  # how far across each branch bends to its lane

    def bend(self, parent: str, child: str) -> float:
        return self.bends.get((parent, child), bundle_bend(self.x[parent], self.y[parent], self.x[child], self.y[child]))

    def scale_text(self) -> str:
        return f"1:{format_length(self.scale_denominator)}" if self.scale_denominator else not_to_scale


# How tightly a drawing that is not to scale is laid out: the least space between branch lanes,
# between rows of overall dimensions, and from the lowest branch to the first row. A drawing that
# does not fit its sheet at the first is drawn at the next, as a draftsman would draw it tighter.
# Drawn compact, a leaf connector carries its balloons and caption beside its body instead of
# above and below it, so its lane needs only the body's height.
@dataclass(frozen=True)
class Spacing:
    lane_minimum: float = 80
    dimension_pitch: float = 24
    dimension_clearance: float = 100
    compact: bool = False


spacings = (Spacing(), Spacing(64, 20, 90), Spacing(52, 18, 80, True), Spacing(44, 16, 70, True))


# At each node the child that reaches farthest continues the trunk; the other branches
# alternate below and above it, starting below, counted across the whole harness.
def branch_order(tree: HarnessTree) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Each node's children top to bottom, and the child that continues its trunk."""
    def reach(node):
        return max([reach(child) + tree.drawn_length(frozenset((node, child))) for child in tree.children[node]] or [0])

    order, trunk = {}, {}
    branches_placed = 0
    for node in tree.order:
        children = sorted(tree.children[node], key=lambda child: reach(child) + tree.drawn_length(frozenset((node, child))),
                          reverse=True)
        if not children:
            order[node] = []
            continue
        above, below = [], []
        for branch in children[1:]:
            branches_placed += 1
            (above if branches_placed % 2 == 0 else below).append(branch)
        order[node] = above[::-1] + [children[0]] + below
        trunk[node] = children[0]
    return order, trunk


# Leaves get lanes top to bottom, each pair at least its minimum pitch apart and spread evenly up
# to 170 where the box has room; every other node sits on its trunk's lane. Across, each segment
# is drawn in proportion to its length but no shorter than 110 (or than a label on it needs) or
# longer than 420, scaled down to fit the box and centred in it.
def place_nodes(tree: HarnessTree, box: Box, spacing: Spacing = spacings[0], minimum_pitches: list[float] | None = None,
                minimum_drawn: dict | None = None) -> Placement:
    """Where each node of the tree is drawn."""
    left, top, right, bottom = box
    order, trunk = branch_order(tree)
    leaves = []

    def collect_leaves(node):
        if not order[node]:
            leaves.append(node)
            return
        for child in order[node]:
            collect_leaves(child)

    collect_leaves(tree.root)
    gaps = max(len(leaves) - 1, 0)
    minimums = list(minimum_pitches) if minimum_pitches and len(minimum_pitches) == gaps else [spacing.lane_minimum] * gaps
    even = min(170, max(spacing.lane_minimum, (bottom - top) / max(1, len(leaves))))
    pitches = [max(minimum, even) for minimum in minimums]
    room = bottom - top
    if sum(pitches) > room and sum(pitches) > sum(minimums):
        share = max(0.0, (room - sum(minimums)) / (sum(pitches) - sum(minimums)))
        pitches = [minimum + (pitch - minimum) * share for minimum, pitch in zip(minimums, pitches)]
    offsets = [0.0]
    for pitch in pitches:
        offsets.append(offsets[-1] + pitch)
    first = (top + bottom) / 2 - offsets[-1] / 2
    ys = {leaf: first + offset for leaf, offset in zip(leaves, offsets)}
    lane_of = {leaf: index for index, leaf in enumerate(leaves)}

    def set_lane(node):
        if not order[node]:
            return ys[node]
        for child in order[node]:
            set_lane(child)
        ys[node], lane_of[node] = ys[trunk[node]], lane_of[trunk[node]]
        return ys[node]

    set_lane(tree.root)
    distance = {tree.root: 0.0}
    for node in tree.order[1:]:
        distance[node] = distance[tree.parent[node]] + tree.drawn_length(frozenset((node, tree.parent[node])))
    scale = (right - left) / (max(distance.values()) or 1)
    drawn = {segment: max(min(max(tree.drawn_length(segment) * scale, 110), 420), (minimum_drawn or {}).get(segment, 0))
             for segment in tree.segment_lengths}
    xs = {tree.root: left}
    for node in tree.order[1:]:
        xs[node] = xs[tree.parent[node]] + drawn[frozenset((node, tree.parent[node]))]
    span = max(xs.values()) - left
    if span > (right - left):
        squeeze = (right - left) / span
        xs = {node: left + (x - left) * squeeze for node, x in xs.items()}
    shift = (right - max(xs.values())) / 2
    xs = {node: x + max(0, shift) for node, x in xs.items()}
    return Placement(xs, ys, lane_of=lane_of, minimum_pitches=minimums, bends=sibling_bends(tree, xs, ys))


# Branches leaving a node on the same side all bend over the same run across, so each is the
# one before it stretched further up or down, and no two cross.
def sibling_bends(tree: HarnessTree, xs: dict, ys: dict) -> dict[tuple[str, str], float]:
    """How far across each branch bends from its parent's lane to its own."""
    bends = {}
    for parent in tree.order:
        for side in (-1, 1):
            children = [child for child in tree.children[parent] if (ys[child] - ys[parent]) * side > 0.5]
            if children:
                reach = max(abs(ys[child] - ys[parent]) for child in children)
                bend = min(max(60, reach * 0.9), min((xs[child] - xs[parent]) * 0.55 for child in children))
                bends.update({(parent, child): bend for child in children})
    return bends


# The drawing gets the frame above the overall dimensions, which get the space above the notes.
# A routed drawing has no overall dimensions, so it gets that space too. The notes are counted
# at the longest scale text, since the scale is chosen to fit this box.
def drawing_box(source: HarnessSource, tree: HarnessTree, spacing: Spacing = spacings[0]) -> Box:
    """The box the harness itself is laid out in on sheet 1."""
    leaf_count = sum(1 for node in tree.order if node in source["connectors"] and node != tree.root and tree.is_leaf(node))
    notes = default_notes(source, tree, standard_scales[-1] if drawn_to_scale(tree) else None)
    notes_top = frame_box[3] - 12 - 15 * sum(note.count("\n") + 1 for note in notes) - 30
    dimensions_height = 0 if drawn_to_scale(tree) else spacing.dimension_pitch * leaf_count + 40
    bottom = min(notes_top, sheet_height - 150) - dimensions_height - 70
    return (170, 150, sheet_width - 230, max(bottom, 420))


# A drawing not to scale is laid out, drawn, and its lanes pushed apart wherever something on one
# lane lies over something on another, until nothing does or the lanes stop moving.
def sheet_placement(source: HarnessSource, tree: HarnessTree, routes: list[Route], bom: list[BomLine],
                    spacing: Spacing = spacings[0]) -> Placement:
    """Where sheet 1 draws each node; the explorer's 2D view uses the same placement."""
    box = drawing_box(source, tree, spacing)
    if drawn_to_scale(tree):
        return routed_placement(source, tree, box)
    minimum_drawn = label_drawn_minimums(source, tree)
    placement = place_nodes(tree, box, spacing, None, minimum_drawn)
    for _ in range(20):
        extra = lane_separations(draw_formboard(source, tree, routes, bom, 1, 0, spacing, placement)[1], placement)
        if not extra:
            break
        pitches = [min(pitch + extra.get(gap, 0), 600) for gap, pitch in enumerate(placement.minimum_pitches)]
        if pitches == placement.minimum_pitches:
            break
        placement = place_nodes(tree, box, spacing, pitches, minimum_drawn)
    return placement


def lane_of_item(layout: SheetLayout, placement: Placement, name: str) -> int | None:
    """The lane a drawn item belongs to, by the node that owns it; None when it belongs to none."""
    owner = layout.owners.get(name.removesuffix(" leader"))
    return placement.lane_of.get(owner) if owner is not None else None


# For each overlap between items on different lanes, the lanes between them are pushed apart by
# the overlap plus a gap, shared over the pitches between them.
def lane_separations(layout: SheetLayout, placement: Placement) -> dict[int, float]:
    """How much more pitch each gap between lanes needs."""
    extra = {}
    for collision in collisions(layout):
        lanes = (lane_of_item(layout, placement, collision.over), lane_of_item(layout, placement, collision.under))
        if None in lanes or lanes[0] == lanes[1]:
            continue
        (upper, upper_box), (lower, lower_box) = sorted(zip(lanes, (collision.over_box, collision.under_box)), key=lambda e: e[0])
        need = max(upper_box[3] - lower_box[1] + 6, 6) / (lower - upper)
        for gap in range(upper, lower):
            extra[gap] = max(extra.get(gap, 0), need)
    return extra


label_gap = 30  # clear space between a label and the node at the far end of its segment


def label_width(label: dict) -> float:
    return max(46, text_width(label["text"], 10, False) + 12)


def label_drawn_minimums(source: HarnessSource, tree: HarnessTree) -> dict:
    """The least each labelled segment is drawn across, so its labels sit on it clear of its far end."""
    minimums = {}
    for label in source["layout"].get("labels") or []:
        node = label.get("at")
        neighbour = tree.neighbour_toward_body(node) if node in tree.nodes else None
        if neighbour is not None:
            segment = frozenset((node, neighbour))
            minimums[segment] = minimums.get(segment, 0) + 60 + label_width(label) / 2 + label_gap + label_width(label) / 2
    return minimums


standard_scales = (1, 2, 2.5, 4, 5, 10, 20, 25, 50, 100, 200)


# A flat (2D) route is the shape the harness lies in on the board, so sheet 1 draws it to scale.
# A 3D route is how it sits in the machine; on the board it lies flattened, so sheet 1 keeps the
# automatic layout with the route's lengths, and the explorer shows the 3D shape.
def drawn_to_scale(tree: HarnessTree) -> bool:
    return tree.geometry is not None and tree.geometry.dimensions == 2
sheet_unit_mm = 0.2625  # one drawing unit printed on A3


# A routed harness is drawn in plan (x across, y down) at the largest standard scale that
# fits the box, centred in it.
def routed_placement(source: HarnessSource, tree: HarnessTree, box: Box) -> Placement:
    """Where sheet 1 draws each node and route point of a routed harness."""
    geometry = tree.geometry
    plan = [point for points in geometry.segment_points.values() for point in points]
    low_x, high_x = min(p[0] for p in plan), max(p[0] for p in plan)
    low_y, high_y = min(p[1] for p in plan), max(p[1] for p in plan)
    unit_mm = 25.4 if source["drawing"].get("units") == "in" else 1
    left, top, right, bottom = box
    for denominator in standard_scales:
        units_to_sheet = unit_mm / (denominator * sheet_unit_mm)
        if (high_x - low_x) * units_to_sheet <= right - left and (high_y - low_y) * units_to_sheet <= bottom - top:
            break
    offset_x = left + (right - left - (high_x - low_x) * units_to_sheet) / 2 - low_x * units_to_sheet
    offset_y = top + (bottom - top - (high_y - low_y) * units_to_sheet) / 2 - low_y * units_to_sheet

    def on_sheet(point):
        return (offset_x + point[0] * units_to_sheet, offset_y + point[1] * units_to_sheet)

    xs = {node: on_sheet(position)[0] for node, position in geometry.positions.items()}
    ys = {node: on_sheet(position)[1] for node, position in geometry.positions.items()}
    segment_points = {(tree.parent[node], node): [on_sheet(point) for point in geometry.points(tree.parent[node], node)]
                      for node in tree.order[1:]}
    return Placement(xs, ys, segment_points, denominator, units_to_sheet)


# A route drawn through its points with each bend rounded, so it reads as a bundle laid on a board.
def polyline_path(points: list[tuple[float, float]], bend_radius: float = 14) -> str:
    """SVG path data for a polyline with rounded corners."""
    points = [point for index, point in enumerate(points) if index == 0 or math.dist(point, points[index - 1]) > 1e-6]
    out = [f"M{points[0][0]:.1f},{points[0][1]:.1f}"]
    for before, corner, after in zip(points, points[1:], points[2:]):
        into, out_of = math.dist(before, corner), math.dist(corner, after)
        radius = min(bend_radius, into / 2, out_of / 2)
        start = (corner[0] + (before[0] - corner[0]) * radius / into, corner[1] + (before[1] - corner[1]) * radius / into)
        end = (corner[0] + (after[0] - corner[0]) * radius / out_of, corner[1] + (after[1] - corner[1]) * radius / out_of)
        out.append(f"L{start[0]:.1f},{start[1]:.1f} C{corner[0]:.1f},{corner[1]:.1f} {corner[0]:.1f},{corner[1]:.1f} "
                   f"{end[0]:.1f},{end[1]:.1f}")
    out.append(f"L{points[-1][0]:.1f},{points[-1][1]:.1f}")
    return " ".join(out)


def point_along(points: list[tuple[float, float]], distance: float) -> tuple[float, float, float]:
    """The point a distance along a polyline (clamped to it), and the polyline's direction there in radians."""
    for start, end in zip(points, points[1:]):
        step = math.dist(start, end)
        if distance <= step or end == points[-1]:
            fraction = min(distance / step, 1) if step else 0
            return (start[0] + (end[0] - start[0]) * fraction, start[1] + (end[1] - start[1]) * fraction,
                    math.atan2(end[1] - start[1], end[0] - start[0]))
        distance -= step
    return (*points[-1], 0.0)


def segment_path(placement: Placement, parent: str, child: str) -> str:
    """The SVG path sheet 1 draws a segment's bundle along."""
    if placement.segment_points:
        return polyline_path(placement.segment_points[(parent, child)])
    return bundle_path(placement.x[parent], placement.y[parent], placement.x[child], placement.y[child], placement.bend(parent, child))[0]


def bundle_bend(parent_x, parent_y, child_x, child_y) -> float:
    """How far across a branch bends from its parent's lane to its own; 0 for a straight segment."""
    if abs(parent_y - child_y) < 0.5:
        return 0
    return min((child_x - parent_x) * 0.55, max(60, abs(child_y - parent_y) * 0.9))


def bundle_path(parent_x, parent_y, child_x, child_y, bend: float | None = None) -> tuple[str, tuple[float, float]]:
    """The SVG path of a segment, and the x range of its straight run after any bend."""
    bend = bundle_bend(parent_x, parent_y, child_x, child_y) if bend is None or abs(parent_y - child_y) < 0.5 else bend
    if not bend:
        return f"M{parent_x:.1f},{parent_y:.1f} L{child_x:.1f},{child_y:.1f}", (parent_x, child_x)
    return (f"M{parent_x:.1f},{parent_y:.1f} C{parent_x + bend * 0.5:.1f},{parent_y:.1f} {parent_x + bend * 0.5:.1f},{child_y:.1f} "
            f"{parent_x + bend:.1f},{child_y:.1f} L{child_x:.1f},{child_y:.1f}"), (parent_x + bend, child_x)


def bundle_points(parent_x, parent_y, child_x, child_y, bend: float | None = None, steps: int = 16) -> list[tuple[float, float]]:
    """The segment's path as a polyline: the bend sampled along its curve, then the straight run."""
    bend = bundle_bend(parent_x, parent_y, child_x, child_y) if bend is None or abs(parent_y - child_y) < 0.5 else bend
    if not bend:
        return [(parent_x, parent_y), (child_x, child_y)]
    curve = [(parent_x, parent_y), (parent_x + bend * 0.5, parent_y), (parent_x + bend * 0.5, child_y), (parent_x + bend, child_y)]
    points = []
    for step in range(steps + 1):
        t = step / steps
        weights = ((1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3)
        points.append((sum(w * p[0] for w, p in zip(weights, curve)), sum(w * p[1] for w, p in zip(weights, curve))))
    return points + [(child_x, child_y)]


# ---------- The sheet ----------


# Draw sheet 1 in layers: coverings under the bundles, then breakouts, connectors and splices,
# segment dimensions, labels, covering balloons, overall dimensions and notes. Each layer
# records what it draws, so later layers can keep clear of it.
def formboard_sheet(source: HarnessSource, tree: HarnessTree, routes: list[Route], bom: list[BomLine],
                    sheet_count: int, check_errors: int, spacing: Spacing = spacings[0],
                    placement: Placement | None = None) -> tuple[str, SheetLayout]:
    """Sheet 1's SVG and the record of what it draws where."""
    placement = placement or sheet_placement(source, tree, routes, bom, spacing)
    return draw_formboard(source, tree, routes, bom, sheet_count, check_errors, spacing, placement)


def draw_formboard(source: HarnessSource, tree: HarnessTree, routes: list[Route], bom: list[BomLine], sheet_count: int,
                   check_errors: int, spacing: Spacing, placement: Placement) -> tuple[str, SheetLayout]:
    """Sheet 1 drawn with the nodes where the placement puts them."""
    out, regions = frame(source, 1, sheet_count, "HARNESS DRAWING", check_errors, placement.scale_text())
    sheet_class = RoutedFormboardSheet if drawn_to_scale(tree) else FormboardSheet
    sheet = sheet_class(source, tree, bom, out, SheetLayout(regions, placement=placement), placement, spacing)
    covering_marks = sheet.draw_coverings()
    sheet.draw_bundles(wire_counts_by_segment(routes))
    sheet.draw_breakouts()
    sheet.draw_connectors()
    sheet.draw_segment_dimensions()
    sheet.draw_labels()
    sheet.draw_covering_balloons(covering_marks)
    sheet.draw_overall_dimensions()
    sheet.draw_notes()
    out.append("</svg>")
    return "\n".join(out), sheet.layout


def connector_height(connector: dict) -> float:
    """A connector body's height on sheet 1, from its pin count."""
    return min(110, max(44, 8 + len(pins_of(connector)) * 3.2))


class FormboardSheet:
    """Sheet 1 while it is being drawn: the source, where each node sits, and what is drawn so far."""

    def __init__(self, source: HarnessSource, tree: HarnessTree, bom: list[BomLine], out: list[str],
                 layout: SheetLayout, placement: Placement, spacing: Spacing = spacings[0]) -> None:
        self.source, self.tree, self.bom, self.out, self.layout = source, tree, bom, out, layout
        self.drawing = source["drawing"]
        self.connectors = source["connectors"]
        self.spacing = spacing
        self.box = drawing_box(source, tree, spacing)
        self.placement = placement
        self.x, self.y = placement.x, placement.y
        self.caption_bottom: dict[str, float] = {}

    # ---------- Keeping clear ----------

    @contextmanager
    def owned_by(self, node: str):
        """Mark everything drawn inside as belonging to a node, so its lane can be moved for it."""
        records = (self.layout.texts, self.layout.bodies, self.layout.dimension_lines, self.layout.leaders,
                   self.layout.extension_lines, self.layout.bundles)
        marks = [len(record) for record in records]
        yield
        for record, mark in zip(records, marks):
            for item in record[mark:]:
                self.layout.owners.setdefault(item[0], node)

    def clear(self, boxes: list[Box], allowed: set[str] = frozenset(), leaders: list[SegmentLine] = ()) -> bool:
        """Whether boxes (and leader lines) can be drawn without lying over anything drawn so far."""
        left, top, right, bottom = frame_box
        if any(box[0] < left or box[1] < top or box[2] > right or box[3] > bottom for box in boxes):
            return False
        if any(boxes_overlap(box, region) for box in boxes for region in self.layout.regions.values()):
            return False
        for what, other in self.layout.texts + self.layout.bodies:
            if what in allowed:
                continue
            if any(boxes_overlap(inset(box, -solid_gap), other) for box in boxes):
                return False
            if any(segment_crosses_box(leader, inset(other, 0.5)) for leader in leaders):
                return False
        for bundle, points, half_width, _ in self.layout.bundles:
            if bundle in allowed:
                continue
            for box in boxes:
                widened = (box[0] - half_width, box[1] - half_width, box[2] + half_width, box[3] + half_width)
                if any(segment_crosses_box((*a, *b), widened) for a, b in zip(points, points[1:])):
                    return False
        for dimension, line_box in self.layout.dimension_lines:
            if dimension in allowed:
                continue
            if any(boxes_overlap(inset(box, 0.5), inset(line_box, 3.5)) for box in boxes):
                return False
            if any(segment_crosses_box(leader, inset(line_box, 3)) for leader in leaders):
                return False
        return True

    def first_clear(self, candidates: list, boxes_of, allowed: set[str] = frozenset(), leaders_of=lambda candidate: ()):
        """The first candidate whose boxes are clear; the first candidate when none is."""
        return next((candidate for candidate in candidates if self.clear(boxes_of(candidate), allowed, leaders_of(candidate))),
                    candidates[0])

    def balloon_boxes(self, x, y, numbers, quantities=None) -> Box:
        widest_quantity = max([text_width(quantity, 10, False) + 3 for quantity in (quantities or {}).values()] or [0])
        return (x - balloon_radius, y - balloon_radius, x + balloon_radius + widest_quantity,
                y + balloon_pitch * (len(numbers) - 1) + balloon_radius)

    @staticmethod
    def leader_from(x, y, target_x, target_y) -> SegmentLine:
        reach = math.hypot(target_x - x, target_y - y) or 1
        return (x + balloon_radius * (target_x - x) / reach, y + balloon_radius * (target_y - y) / reach, target_x, target_y)

    # ---------- Bundles and coverings ----------

    def parent_and_child(self, ends) -> tuple[str, str]:
        start, end = ends
        return (start, end) if self.tree.parent.get(end) == start else (end, start)

    def record_bundle(self, parent: str, child: str, points: list[tuple[float, float]], thickness: float) -> None:
        """Record a segment's bundle, which may run into the bodies at its two ends."""
        ends = {name for node in (parent, child) for name in (f"connector {node}", f"connector {node} fan", f"splice {node}")}
        self.layout.bundles.append((f"bundle {parent}–{child}", points, (3 + thickness) / 2, ends))

    def draw_coverings(self) -> list[tuple[dict, float, float, bool]]:
        """Shade each covered segment; return where each covering's balloon goes."""
        marks = []
        for covering in self.source["layout"].get("coverings") or []:
            covered = [tuple(covered_segment_ends(segment)) for segment in covering["segments"]]
            drawn = [ends for ends in covered if frozenset(ends) in self.tree.segment_lengths]
            for ends in drawn:
                parent, child = self.parent_and_child(ends)
                path, _ = bundle_path(self.x[parent], self.y[parent], self.x[child], self.y[child], self.placement.bend(parent, child))
                self.out.append(f'<path d="{path}" fill="none" stroke="{covering.get("display_color", "#9aa7b8")}" '
                                f'stroke-width="{covering.get("display_width", 16)}" stroke-linecap="butt" opacity="0.55"/>')
            if drawn:
                parent, child = self.parent_and_child(drawn[0])
                marks.append((covering, (self.x[parent] + self.x[child]) / 2, self.y[child], self.y[child] >= self.y[parent]))
        return marks

    # A segment of unknown length carries a break mark midway along its straight run, or midway
    # along the longer part of the run a label leaves free.
    def draw_bundles(self, wire_counts: dict) -> None:
        """Each segment as a bundle whose width grows with its wire count; an unknown length shows a break."""
        for node in self.tree.order[1:]:
            parent = self.tree.parent[node]
            thickness = 1.6 * math.sqrt(max(wire_counts.get(frozenset((node, parent)), 0), 1))
            bend = self.placement.bend(parent, node)
            path, (run_start, run_end) = bundle_path(self.x[parent], self.y[parent], self.x[node], self.y[node], bend)
            with self.owned_by(node):
                self.out.append(f'<path d="{path}" fill="none" stroke="#333" stroke-width="{3 + thickness:.1f}" stroke-linecap="round"/>')
                self.out.append(f'<path d="{path}" fill="none" stroke="#9a9a9a" stroke-width="{1 + thickness:.1f}" stroke-linecap="round"/>')
                self.record_bundle(parent, node, bundle_points(self.x[parent], self.y[parent], self.x[node], self.y[node], bend), thickness)
                if self.tree.segment_lengths[frozenset((node, parent))] is None:
                    x = self.break_position(parent, node, run_start, run_end)
                    self.out.append(length_break(x, self.y[node], 3 + thickness))
                    half = (3 + thickness) / 2 + 5
                    self.layout.bodies.append((f"break {parent}–{node}", (x - 7, self.y[node] - half, x + 7, self.y[node] + half)))
                    self.layout.touches[f"break {parent}–{node}"] = {f"bundle {parent}–{node}"}

    def break_position(self, parent: str, node: str, run_start: float, run_end: float) -> float:
        """Where along a straight run its break mark goes, clear of any label on it."""
        low, high = sorted((run_start, run_end))
        low, high = low + connector_fan_length, high - connector_fan_length
        free = [(low, high)]
        for label in self.source["layout"].get("labels") or []:
            at = label.get("at")
            if at in (parent, node) and self.tree.neighbour_toward_body(at) in (parent, node):
                x, _, width = self.label_place(label, at, self.tree.neighbour_toward_body(at))
                pieces = []
                for start, end in free:
                    pieces += [piece for piece in ((start, min(end, x - width / 2 - 10)), (max(start, x + width / 2 + 10), end))
                               if piece[1] - piece[0] > 0]
                free = pieces or free
        start, end = max(free, key=lambda piece: piece[1] - piece[0])
        return (start + end) / 2

    # ---------- Segment dimensions ----------

    # A straight segment gets a dimension line below it, lowered past anything in the way; a bent
    # branch gets its length called out beside its bend, on whichever side is clear.
    def draw_segment_dimensions(self) -> None:
        """Dimension each segment with its tolerance."""
        for node in self.tree.order[1:]:
            parent = self.tree.parent[node]
            length = self.tree.segment_lengths[frozenset((node, parent))]
            label = segment_dimension_label(self.drawing, length, self.tree.segment_minimums.get(frozenset((node, parent))))
            what = f"dimension {parent}–{node}"
            with self.owned_by(node):
                if abs(self.y[parent] - self.y[node]) < 0.5:
                    self.draw_straight_dimension(what, parent, node, label)
                else:
                    self.draw_bend_dimension(what, parent, node, label)

    def draw_straight_dimension(self, what: str, parent: str, node: str, label: str) -> None:
        x1, x2, y = self.x[parent], self.x[node], self.y[node]
        label_width = text_width(label, 11, False) + 8
        on_line = x2 - x1 > label_width + 20

        def boxes(offset):
            line_y = y + offset
            middle = (x1 + x2) / 2
            text_box = ((middle - label_width / 2, line_y - 7, middle + label_width / 2, line_y + 7) if on_line
                        else (middle - label_width / 2, line_y - 16, middle + label_width / 2, line_y - 2))
            return [(x1 + 4, line_y - 1, x2 - 4, line_y + 1), text_box]
        ends = {name for end in (parent, node) for name in (f"connector {end}", f"connector {end} fan", f"splice {end}")}
        offset = self.first_clear([34, 48, 62, 76, 90, -30, -44, -58], boxes, ends,
                                  lambda offset: [(x1, self.y[parent], x1, y + offset), (x2, y, x2, y + offset)])
        self.out.append(draw_dimension(self.layout, what, x1, x2, y + offset, label, (self.y[parent], y)))

    def draw_bend_dimension(self, what: str, parent: str, node: str, label: str) -> None:
        bend = self.placement.bend(parent, node)
        width = text_width(label, 11, False) + 8
        middle_x, middle_y = self.x[parent] + bend * 0.5, (self.y[parent] + self.y[node]) / 2
        run_y = self.y[node] + (-12 if self.y[node] < self.y[parent] else 12)
        run_x = self.x[parent] + bend + 6 + width / 2
        candidates = [(middle_x + 8 + width / 2, middle_y), (middle_x - 8 - width / 2, middle_y),
                      (run_x, run_y), (run_x, 2 * self.y[node] - run_y)]
        x, y = self.first_clear(candidates, lambda c: [(c[0] - width / 2, c[1] - 7, c[0] + width / 2, c[1] + 7)])
        self.layout.texts.append((what, (x - width / 2, y - 7, x + width / 2, y + 7)))
        self.out.append(rect(x - width / 2, y - 7, width, 14, fill="white", stroke="none"))
        self.out.append(text(x, y + 4, label, 11, "middle"))

    # ---------- Breakouts, splices and connectors ----------

    def draw_breakouts(self) -> None:
        """A small circle and name at each node that is not a connector."""
        for node in self.tree.order:
            if node in self.connectors:
                continue
            x, y = self.x[node], self.y[node]
            with self.owned_by(node):
                self.out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="white" stroke="{ink}" stroke-width="1.2"/>')
                self.out.append(text(x - 6, y - 10, node, 9, "end", fill="#555"))
                self.layout.texts.append((f"breakout {node}", (x - 6 - text_width(node, 9, False), y - 19, x - 6, y - 8)))

    def draw_connectors(self) -> None:
        for designator, connector in self.connectors.items():
            if designator not in self.x:
                continue
            with self.owned_by(designator):
                if is_splice(connector):
                    self.draw_splice(designator)
                else:
                    self.draw_connector(designator, connector)

    def draw_splice(self, designator: str) -> None:
        """A splice as a diamond, named above, with its find-number balloon."""
        x, y = self.x[designator], self.y[designator]
        self.out.append(f'<rect x="{x - 9:.1f}" y="{y - 7:.1f}" width="18" height="14" fill="#d9d9d9" stroke="{ink}" '
                        f'transform="rotate(45 {x:.1f} {y:.1f})"/>')
        self.out.append(text(x, y - 16, designator, 12, "middle", "bold"))
        self.layout.bodies.append((f"splice {designator}", (x - 13, y - 13, x + 13, y + 13)))
        name_width = text_width(designator, 12, True)
        self.layout.texts.append((f"splice {designator} name", (x - name_width / 2, y - 28, x + name_width / 2, y - 14)))
        self.layout.touches[f"splice {designator} name"] = {f"splice {designator}"}
        numbers = find_numbers(self.bom, "splice", designator)
        if numbers:
            target = f"splice {designator}"
            candidates = [(x + 30, y - 45, x + 9, y - 3), (x - 30, y - 45, x - 9, y - 3), (x + 30, y + 45, x + 9, y + 3),
                          (x - 30, y + 45, x - 9, y + 3)]
            bx, by, tx, ty = self.first_clear(candidates, lambda c: [self.balloon_boxes(c[0], c[1], numbers)], {target},
                                              lambda c: [self.leader_from(*c)])
            self.out.append(draw_balloons(self.layout, f"{designator} balloons", bx, by, numbers, tx, ty, target))

    # A connector is a body box with its mating face marked, a fan of its wires in their
    # colours between body and bundle, a caption below and find-number balloons above. The
    # root connector faces left; every other faces right. Drawn compact, a leaf carries its
    # balloons and then its caption beside its body, on its own lane.
    def draw_connector(self, designator: str, connector: dict) -> None:
        """Draw one connector with its wires, caption and balloons."""
        x, y = self.x[designator], self.y[designator]
        faces_left = designator == self.tree.root
        body_height = connector_height(connector)
        body_x = x - connector_body_width if faces_left else x
        self.draw_wire_fan(designator, x, y, body_height, -1 if faces_left else 1)
        self.out.append(connector_body(connector, body_x, y - body_height / 2, body_height))
        self.out.append(mating_face(connector, body_x, y, body_height, faces_left))
        self.layout.bodies.append((f"connector {designator}", (body_x, y - body_height / 2, body_x + connector_body_width, y + body_height / 2)))
        if self.spacing.compact and not faces_left and self.tree.is_leaf(designator):
            self.draw_compact_furniture(designator, connector, x, y, body_height)
            return
        self.draw_caption(designator, connector, x, y, body_x, body_height, faces_left)
        self.draw_connector_balloons(designator, body_x, y - body_height / 2, faces_left)

    def draw_wire_fan(self, designator: str, x, y, body_height, direction: int) -> None:
        """Each wire at a connector, in its colour, fanning from the bundle into the body; stripes dashed over."""
        wires_here = [wire for wire in self.source["wires"]
                      if wire_end(wire["from"])[0] == designator or wire_end(wire["to"])[0] == designator]
        count = len(wires_here)
        fan_start = x - direction * connector_fan_length
        control_x = x - direction * connector_fan_length * .5
        pitch = min(5, (body_height - 10) / max(count, 1))
        for index, wire in enumerate(wires_here):
            wire_y = y + (index - (count - 1) / 2) * pitch
            path = f"M{fan_start:.1f},{y:.1f} C{control_x:.1f},{y:.1f} {control_x:.1f},{wire_y:.1f} {x:.1f},{wire_y:.1f}"
            base_color, *stripe_colors = color_parts(chosen_color(wire))
            self.out.append(f'<path d="{path}" fill="none" stroke="{display_color(base_color)}" stroke-width="2"/>')
            for stripe in stripe_colors[:1]:
                self.out.append(f'<path d="{path}" fill="none" stroke="{display_color(stripe)}" stroke-width="2" '
                                'stroke-dasharray="3 3"/>')
        spread = max(count - 1, 0) / 2 * pitch + 2
        fan = f"connector {designator} fan"
        self.layout.bodies.append((fan, (min(x, fan_start), y - spread, max(x, fan_start), y + spread)))
        self.layout.touches[fan] = {f"connector {designator}"}

    def caption_text(self, designator: str, connector: dict) -> str:
        description = connector.get("label") or connector.get("type", "")
        if is_generic(connector):
            generic = f"GENERIC {len(pins_of(connector))}-PIN"
            description = f"{description} · {generic}" if description else generic
        return description

    def draw_caption(self, designator: str, connector: dict, x, y, body_x, body_height, faces_left: bool) -> None:
        """Designator and description, centred under the body but clear of the datum line at x."""
        description = self.caption_text(designator, connector)
        caption_width = max(text_width(designator, 14, True), text_width(description, 9.5, False))
        centred = body_x + connector_body_width / 2
        caption_x = min(centred, x - 4 - caption_width / 2) if faces_left else max(centred, x + 4 + caption_width / 2)
        self.out.append(text(caption_x, y + body_height / 2 + 18, designator, 14, "middle", "bold",
                             extra='text-decoration="underline"'))
        self.out.append(text(caption_x, y + body_height / 2 + 32, description, 9.5, "middle", fill="#333"))
        self.layout.texts.append((f"connector {designator} caption", (caption_x - caption_width / 2, y + body_height / 2 + 4,
                                                                      caption_x + caption_width / 2, y + body_height / 2 + 35)))
        self.caption_bottom[designator] = y + body_height / 2 + 38

    def connector_finds(self, designator: str) -> tuple[list, dict]:
        """A connector's housing, accessory and contact find numbers; contacts carry their count."""
        contact_numbers = find_numbers(self.bom, "contact", designator)
        numbers = find_numbers(self.bom, "connector", designator) + contact_numbers + find_numbers(self.bom, "accessory", designator)
        quantities = {}
        if contact_numbers:
            pins_used = {wire_end(wire[end])[1] for wire in self.source["wires"] for end in ("from", "to")
                         if wire_end(wire[end])[0] == designator}
            quantities[contact_numbers[0]] = f"{len(pins_used)}X"  # one contact per pin used, as in the BOM
        return numbers, quantities

    def draw_connector_balloons(self, designator: str, body_x, body_top, faces_left: bool) -> None:
        """Housing, contact and accessory find numbers above the body, on whichever side is clear."""
        numbers, quantities = self.connector_finds(designator)
        if not numbers:
            return
        outside, inside = (body_x - 40, body_x + connector_body_width + 40) if faces_left else (body_x + connector_body_width + 40, body_x - 40)
        target_x = body_x + connector_body_width * (0.3 if faces_left else 0.7)
        target = f"connector {designator}"
        candidates = [(outside, body_top - 40), (inside, body_top - 40), (outside, body_top - 64)]
        bx, by = self.first_clear(candidates, lambda c: [self.balloon_boxes(c[0], c[1], numbers, quantities)], {target},
                                  lambda c: [self.leader_from(c[0], c[1], target_x, body_top)])
        self.out.append(draw_balloons(self.layout, f"{designator} balloons", bx, by, numbers, target_x, body_top, target, quantities))

    def draw_compact_furniture(self, designator: str, connector: dict, x, y, body_height) -> None:
        """A leaf's balloons in a row beside its body, then its designator and description."""
        numbers, quantities = self.connector_finds(designator)
        right = x + connector_body_width
        if numbers:
            first_x = right + 10 + balloon_radius
            self.out.append(balloon_row(first_x, y, numbers, right, y, quantities))
            last_x = first_x + balloon_pitch * (len(numbers) - 1)
            widest_quantity = max([text_width(quantity, 10, False) + 3 for quantity in quantities.values()] or [0])
            what = f"{designator} balloons"
            self.layout.texts.append((what, (first_x - balloon_radius, y - balloon_radius, last_x + balloon_radius + widest_quantity,
                                             y + balloon_radius)))
            self.layout.leaders.append((what, (first_x - balloon_radius, y, right, y), {what, f"connector {designator}"}))
            right = last_x + balloon_radius + widest_quantity
        description = self.caption_text(designator, connector)
        caption_x = right + 8
        caption_width = max(text_width(designator, 14, True), text_width(description, 9.5, False))
        self.out.append(text(caption_x, y - 1, designator, 14, "start", "bold", extra='text-decoration="underline"'))
        self.out.append(text(caption_x, y + 12, description, 9.5, "start", fill="#333"))
        self.layout.texts.append((f"connector {designator} caption", (caption_x, y - 14, caption_x + caption_width, y + 15)))
        self.caption_bottom[designator] = y + body_height / 2 + 3

    # ---------- Labels ----------

    def draw_labels(self) -> None:
        """Each label box with its position dimension and balloon."""
        for label in self.source["layout"].get("labels") or []:
            node = label["at"]
            if node not in self.x:
                continue
            neighbour = self.tree.neighbour_toward_body(node)
            if neighbour is None:
                continue
            with self.owned_by(node):
                self.draw_label(label, node, neighbour)

    def label_place(self, label: dict, node: str, neighbour: str) -> tuple[float, float, float]:
        """Where a label's box is centred on its connector's own segment, and its width."""
        x_node = self.x[node]
        distance = float(label.get("distance", conventions(self.drawing)["label_distance"]))
        segment_length = self.tree.drawn_length(frozenset((node, neighbour)))
        x = x_node + (self.x[neighbour] - x_node) * min(distance / segment_length, 0.6)
        x = x_node + math.copysign(max(abs(x - x_node), 60), self.x[neighbour] - x_node)
        return x, self.y[node], label_width(label)

    # A label sits on its connector's own segment at its distance, drawn at least 60 and at most
    # 60% of the way along. Its dimension goes on the side away from the segment's parent where
    # that is clear; its balloon beyond the label's far end, on whichever side is clear.
    def draw_label(self, label: dict, node: str, neighbour: str) -> None:
        x_node = self.x[node]
        distance = float(label.get("distance", conventions(self.drawing)["label_distance"]))
        x, y, width = self.label_place(label, node, neighbour)
        content = label["text"]
        name = f"label {content} at {node}"
        segment_child = node if node != self.tree.root else neighbour
        bundle = f"bundle {self.tree.parent[segment_child]}–{segment_child}"
        self.out.append(rect(x - width / 2, y - 9, width, 18, fill="white", stroke_width=1))
        self.out.append(text(x, y + 4, content, 10, "middle"))
        self.layout.texts.append((name, (x - width / 2, y - 9, x + width / 2, y + 9)))
        self.layout.touches[name] = {bundle}
        self.layout.place_label({**label, "distance": distance}, neighbour, x, y)
        segment_runs_up = self.y[segment_child] < self.y[self.tree.parent[segment_child]]
        connector_on_right = x_node > x
        dimension_label = format_length(distance)
        dimension_width = text_width(dimension_label, 11, False) + 8
        low, high = min(x_node, x), max(x_node, x)

        def dimension_boxes(side):
            line_y = y + side * 26
            middle = (low + high) / 2
            on_line = high - low > dimension_width + 20
            text_box = ((middle - dimension_width / 2, line_y - 7, middle + dimension_width / 2, line_y + 7) if on_line
                        else (middle - dimension_width / 2, line_y - 16, middle + dimension_width / 2, line_y - 2))
            return [(low + 4, line_y - 1, high - 4, line_y + 1), text_box]
        default_side = 1 if segment_runs_up else -1
        side = self.first_clear([default_side, -default_side], dimension_boxes, {name})
        extensions = (y + side * 9, y) if connector_on_right else (y, y + side * 9)
        dimension = f"{name} dimension"
        self.out.append(draw_dimension(self.layout, dimension, low, high, y + side * 26, dimension_label, extensions))
        self.layout.touches[dimension] = {name, f"connector {node} fan", f"connector {node}"}
        numbers = item_find_numbers(self.bom, label["item"]) if label.get("item") else []
        if numbers:
            away = -1 if connector_on_right else 1
            balloon = f"{name} balloon"
            candidates = [(x + away * (width / 2 + 22), y + side * 44, x + away * (width / 2 - 6), y + side * 9),
                          (x - away * (width / 2 + 22), y + side * 44, x - away * (width / 2 - 6), y + side * 9),
                          (x + away * (width / 2 + 22), y - side * 44, x + away * (width / 2 - 6), y - side * 9),
                          (x - away * (width / 2 + 22), y - side * 44, x - away * (width / 2 - 6), y - side * 9),
                          (x + away * (width / 2 + 22), y + side * 68, x + away * (width / 2 - 6), y + side * 9),
                          (x + away * (width / 2 + 22), y - side * 68, x + away * (width / 2 - 6), y - side * 9)]
            bx, by, tx, ty = self.first_clear(candidates, lambda c: [self.balloon_boxes(c[0], c[1], numbers)], {name},
                                              lambda c: [self.leader_from(*c)])
            self.out.append(draw_balloons(self.layout, balloon, bx, by, numbers, tx, ty, name))

    def draw_covering_balloons(self, marks: list[tuple[dict, float, float, bool]]) -> None:
        """Each covering's AR balloon, on the side of the bundle opposite its segment dimensions where that is clear."""
        for covering, x, y, dimensions_below in marks:
            numbers = item_find_numbers(self.bom, covering.get("item"))
            if numbers:
                side = -1 if dimensions_below else 1
                target = f"{covering.get('item')} covering"
                quantities = {numbers[0]: "AR"}
                candidates = [(x + 25, y + side * 55, x, y + side * 8), (x - 25, y + side * 55, x, y + side * 8),
                              (x + 25, y - side * 55, x, y - side * 8), (x - 25, y - side * 55, x, y - side * 8),
                              (x + 60, y + side * 55, x + 30, y + side * 8), (x - 60, y + side * 55, x - 30, y + side * 8)]
                bx, by, tx, ty = self.first_clear(candidates, lambda c: [self.balloon_boxes(c[0], c[1], numbers, quantities)],
                                                  {target}, lambda c: [self.leader_from(*c)])
                self.out.append(draw_balloons(self.layout, f"{covering.get('item')} balloon", bx, by, numbers, tx, ty, target, quantities))

    # ---------- Overall dimensions and notes ----------

    # Overall dimensions from the root datum to each leaf connector more than one segment away.
    # The segment dimensions already fix these lengths, each with its own tolerance, so an
    # overall tolerance would contradict their stack-up: the overall lengths are reference only.
    # A leaf one segment from the root has its length in that segment's dimension already.
    def draw_overall_dimensions(self) -> None:
        """Reference dimensions from the root to each leaf connector, with their extension lines."""
        tree, root = self.tree, self.tree.root
        leaves = sorted((node for node in tree.order if node in self.connectors and node != root and tree.is_leaf(node)
                         and tree.parent[node] != root), key=lambda node: self.x[node])
        pitch = self.spacing.dimension_pitch
        first_row = max(max(self.y.values()) + self.spacing.dimension_clearance, self.box[3] + 60)
        for index, leaf in enumerate(leaves):
            length, minimum = tree.depth[leaf], tree.minimum_depth[leaf]
            label = f"{format_length(length)} REF" if length is not None else f"{unknown_length_text(minimum)} REF"
            what = f"overall dimension {root}–{leaf}"
            row_y = first_row + index * pitch
            self.out.append(draw_dimension(self.layout, what, self.x[root], self.x[leaf], row_y, f"{label}  ({root}–{leaf})"))
            self.out.append(draw_broken_extension(self.layout, f"{what} extension", self.x[leaf],
                                                  self.caption_bottom.get(leaf, self.y[leaf] + 20), row_y + 4, {what}))
        if leaves:
            self.out.append(draw_broken_extension(self.layout, f"{root} datum extension", self.x[root],
                                                  self.caption_bottom.get(root, self.y[root] + 20),
                                                  first_row + (len(leaves) - 1) * pitch + 4,
                                                  {f"overall dimension {root}–{leaf}" for leaf in leaves}))

    def draw_notes(self) -> None:
        """The numbered notes at the bottom left, recorded as a block the drawing keeps clear of."""
        lines = []
        for number, note in enumerate(default_notes(self.source, self.tree, self.placement.scale_denominator), 1):
            for index, content in enumerate(note.split("\n")):
                lines.append((f"{number}.  " if index == 0 else "") + content)
        top = frame_box[3] - 12 - 15 * len(lines)
        left = frame_box[0] + 10
        self.out.append(text(left, top - 8, "NOTES:", 12, weight="bold", extra='text-decoration="underline"'))
        for index, content in enumerate(lines):
            self.out.append(text(left, top + 12 + index * 15, content, 10.5, extra='xml:space="preserve"'))
        widest = max(text_width(content, 10.5, False) for content in lines)
        self.layout.regions["notes"] = (left, top - 20, left + widest, frame_box[3])


# Sheet 1 for a routed harness: every node and bend where the route puts it, at scale. Each
# connector lies along the direction its bundle arrives in; segment dimensions sit beside their
# bundle's midpoint; labels sit at their true distance; there are no overall dimensions, since
# the drawing is to scale and the wire list gives every length.
class RoutedFormboardSheet(FormboardSheet):
    """Sheet 1 of a harness with routing geometry."""

    def points(self, parent: str, child: str) -> list[tuple[float, float]]:
        return self.placement.segment_points[(parent, child)]

    def midpoint(self, parent: str, child: str) -> tuple[float, float, float]:
        points = self.points(parent, child)
        total = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        return point_along(points, total / 2)

    def draw_coverings(self) -> list[tuple[dict, float, float, bool]]:
        marks = []
        for covering in self.source["layout"].get("coverings") or []:
            covered = [tuple(covered_segment_ends(segment)) for segment in covering["segments"]]
            drawn = [self.parent_and_child(ends) for ends in covered if frozenset(ends) in self.tree.segment_lengths]
            for parent, child in drawn:
                self.out.append(f'<path d="{polyline_path(self.points(parent, child))}" fill="none" '
                                f'stroke="{covering.get("display_color", "#9aa7b8")}" stroke-width="{covering.get("display_width", 16)}" '
                                'stroke-linecap="butt" opacity="0.55"/>')
            if drawn:
                x, y, angle = self.midpoint(*drawn[0])
                marks.append((covering, x, y, angle))
        return marks

    def draw_bundles(self, wire_counts: dict) -> None:
        for node in self.tree.order[1:]:
            parent = self.tree.parent[node]
            thickness = 1.6 * math.sqrt(max(wire_counts.get(frozenset((node, parent)), 0), 1))
            path = polyline_path(self.points(parent, node))
            self.out.append(f'<path d="{path}" fill="none" stroke="#333" stroke-width="{3 + thickness:.1f}" stroke-linecap="round" '
                            'stroke-linejoin="round"/>')
            self.out.append(f'<path d="{path}" fill="none" stroke="#9a9a9a" stroke-width="{1 + thickness:.1f}" stroke-linecap="round" '
                            'stroke-linejoin="round"/>')
            self.record_bundle(parent, node, self.points(parent, node), thickness)
            if self.tree.segment_lengths[frozenset((node, parent))] is None:
                x, y, angle = self.midpoint(parent, node)
                self.out.append(f'<g transform="rotate({math.degrees(angle):.1f} {x:.1f} {y:.1f})">{length_break(x, y, 3 + thickness)}</g>')

    def draw_segment_dimensions(self) -> None:
        """Each segment's length and tolerance beside the middle of its bundle, on its left."""
        for node in self.tree.order[1:]:
            parent = self.tree.parent[node]
            key = frozenset((node, parent))
            label = segment_dimension_label(self.drawing, self.tree.segment_lengths[key], self.tree.segment_minimums.get(key))
            x, y, angle = self.midpoint(parent, node)
            width = text_width(label, 11, False) + 8
            reach = 18 + 0.5 * abs(math.sin(angle)) * width
            label_x, label_y = x + math.sin(angle) * reach, y - math.cos(angle) * reach
            self.layout.texts.append((f"dimension {parent}–{node}", (label_x - width / 2, label_y - 7, label_x + width / 2, label_y + 7)))
            self.out.append(rect(label_x - width / 2, label_y - 7, width, 14, fill="white", stroke="none"))
            self.out.append(text(label_x, label_y + 4, label, 11, "middle"))

    def connector_axis(self, designator: str) -> tuple[float, float]:
        """The direction a connector points: away from its bundle."""
        if designator == self.tree.root:
            points = self.points(designator, self.tree.children[designator][0])
            before, at = points[1], points[0]
        else:
            points = self.points(self.tree.parent[designator], designator)
            before, at = points[-2], points[-1]
        reach = math.dist(before, at) or 1
        return ((at[0] - before[0]) / reach, (at[1] - before[1]) / reach)

    # Draw the connector as on the automatic layout, facing right from its node, inside a
    # rotation onto its axis; its caption and balloons stay upright beside it.
    def draw_connector(self, designator: str, connector: dict) -> None:
        x, y = self.x[designator], self.y[designator]
        axis_x, axis_y = self.connector_axis(designator)
        body_height = min(110, max(44, 8 + len(pins_of(connector)) * 3.2))
        first = len(self.out)
        self.draw_wire_fan(designator, 0, 0, body_height, 1)
        self.out.append(connector_body(connector, 0, -body_height / 2, body_height))
        self.out.append(mating_face(connector, 0, 0, body_height, False))
        drawn = "".join(self.out[first:])
        del self.out[first:]
        self.layout.bodies = [entry for entry in self.layout.bodies if entry[0] != f"connector {designator} fan"]
        self.out.append(f'<g transform="translate({x:.1f} {y:.1f}) rotate({math.degrees(math.atan2(axis_y, axis_x)):.1f})">{drawn}</g>')
        corners = [(along, across) for along in (-connector_fan_length, connector_body_width) for across in (-body_height / 2, body_height / 2)]
        on_sheet = [(x + along * axis_x - across * axis_y, y + along * axis_y + across * axis_x) for along, across in corners]
        box = (min(p[0] for p in on_sheet), min(p[1] for p in on_sheet), max(p[0] for p in on_sheet), max(p[1] for p in on_sheet))
        self.layout.bodies.append((f"connector {designator}", box))
        description = connector.get("label") or connector.get("type", "")
        if is_generic(connector):
            generic = f"GENERIC {len(pins_of(connector))}-PIN"
            description = f"{description} · {generic}" if description else generic
        caption_width = max(text_width(designator, 14, True), text_width(description, 9.5, False))
        centre_x = (box[0] + box[2]) / 2
        self.out.append(text(centre_x, box[3] + 18, designator, 14, "middle", "bold", extra='text-decoration="underline"'))
        self.out.append(text(centre_x, box[3] + 32, description, 9.5, "middle", fill="#333"))
        self.layout.texts.append((f"connector {designator} caption", (centre_x - caption_width / 2, box[3] + 4,
                                                                      centre_x + caption_width / 2, box[3] + 35)))
        numbers = (find_numbers(self.bom, "connector", designator) + find_numbers(self.bom, "contact", designator)
                   + find_numbers(self.bom, "accessory", designator))
        quantities = {}
        contact_numbers = find_numbers(self.bom, "contact", designator)
        if contact_numbers:
            pins_used = {wire_end(wire[end])[1] for wire in self.source["wires"] for end in ("from", "to")
                         if wire_end(wire[end])[0] == designator}
            quantities[contact_numbers[0]] = f"{len(pins_used)}X"
        self.out.append(draw_balloons(self.layout, f"{designator} balloons", box[2] + 30, box[1] - 30, numbers,
                                      centre_x, box[1], f"connector {designator}", quantities))

    def draw_label(self, label: dict, node: str, neighbour: str) -> None:
        """A label at its true distance along its segment, with that distance written under it."""
        distance = float(label.get("distance", conventions(self.drawing)["label_distance"]))
        parent, child = (neighbour, node) if self.tree.parent.get(node) == neighbour else (node, neighbour)
        points = self.points(parent, child)
        points = points[::-1] if node == child else points
        x, y, _ = point_along(points, distance * self.placement.units_to_sheet)
        content = label["text"]
        name = f"label {content} at {node}"
        width = label_width(label)
        self.out.append(rect(x - width / 2, y - 9, width, 18, fill="white", stroke_width=1))
        self.out.append(text(x, y + 4, content, 10, "middle"))
        self.layout.texts.append((name, (x - width / 2, y - 9, x + width / 2, y + 9)))
        self.layout.touches[name] = {f"bundle {parent}–{child}"}
        self.layout.place_label({**label, "distance": distance}, neighbour, x, y)
        note = f"{format_length(distance)} FROM {node}"
        self.out.append(text(x, y + 22, note, 9, "middle", fill="#333"))
        note_width = text_width(note, 9, False)
        self.layout.texts.append((f"{name} distance", (x - note_width / 2, y + 13, x + note_width / 2, y + 25)))
        numbers = item_find_numbers(self.bom, label["item"]) if label.get("item") else []
        if numbers:
            candidates = [(x + width / 2 + 22, y - 32, x + width / 2 - 6, y - 9), (x - width / 2 - 22, y - 32, x - width / 2 + 6, y - 9),
                          (x + width / 2 + 22, y + 40, x + width / 2 - 6, y + 9)]
            bx, by, tx, ty = self.first_clear(candidates, lambda c: [self.balloon_boxes(c[0], c[1], numbers)], {name},
                                              lambda c: [self.leader_from(*c)])
            self.out.append(draw_balloons(self.layout, f"{name} balloon", bx, by, numbers, tx, ty, name))

    def draw_covering_balloons(self, marks) -> None:
        for covering, x, y, angle in marks:
            numbers = item_find_numbers(self.bom, covering.get("item"))
            if numbers:
                normal_x, normal_y = -math.sin(angle), math.cos(angle)
                self.out.append(draw_balloons(self.layout, f"{covering.get('item')} balloon", x + normal_x * 50, y + normal_y * 50,
                                              numbers, x + normal_x * 9, y + normal_y * 9, f"{covering.get('item')} covering",
                                              {numbers[0]: "AR"}))

    def draw_overall_dimensions(self) -> None:
        """None: a routed drawing is to scale, and the wire list gives every cut length."""


# A connector body in side view. A generic part, one not yet chosen, is drawn pale with a
# dashed outline so it cannot be read as a real part; a circular one has rounded ends.
def connector_body(connector: dict, x, top, height) -> str:
    """The body of a connector on sheet 1."""
    generic = is_generic(connector)
    shape = connector.get("shape", "rectangular")
    style = f'rx="{12 if shape == "circular" else 3}" class="connector-body{" generic" if generic else ""} {shape}"'
    if generic:
        style += ' stroke-dasharray="5 3"'
    return rect(x, top, connector_body_width, height, fill="#f4f4f4" if generic else "#e4e4e4", stroke_width=1.2, extra=style)


# The mating face at the body's far end: a plain strip when the gender is not stated, with
# socket openings for a female connector and protruding pins for a male one.
def mating_face(connector: dict, body_x, y, height, faces_left: bool) -> str:
    """The mating face of a connector on sheet 1."""
    face_x = body_x if faces_left else body_x + connector_body_width - 6
    strip = rect(face_x, y - height / 2 + 6, 6, height - 12, fill="#bdbdbd", stroke_width=0.8)
    gender = connector.get("gender")
    if gender is None:
        return strip
    marks_y = [y - height / 4, y, y + height / 4]
    if gender == "female":
        marks = "".join(rect(face_x + 1.5, mark_y - 2, 3, 4, fill="#555", stroke="none") for mark_y in marks_y)
    else:
        tip = face_x - 7 if faces_left else face_x + 13
        root = face_x if faces_left else face_x + 6
        marks = "".join(line(root, mark_y, tip, mark_y, 2, "#555") for mark_y in marks_y)
    return f'<g class="mating-{gender}">{strip}{marks}</g>'


def unknown_length_text(minimum: float | None) -> str:
    """An unknown length as printed: ≥ its minimum, or TBD."""
    return f"≥{format_length(minimum)}" if minimum is not None else "TBD"


def segment_dimension_label(drawing: dict, length: float | None, minimum: float | None) -> str:
    """A segment's dimension: the length with its tolerance, or the unknown length's text."""
    if length is None:
        return unknown_length_text(minimum)
    return f"{format_length(length)} ±{format_length(tolerance_for(drawing, length))}"


# The drafting break: a gap across the bundle between two slanted strokes, marking a
# length that is not drawn to its value.
def length_break(x, y, bundle_width) -> str:
    """A break mark across a bundle at (x, y)."""
    half = bundle_width / 2 + 5
    return (f'<g class="length-break">'
            f'<rect x="{x - 4:.1f}" y="{y - half:.1f}" width="8" height="{2 * half:.1f}" fill="white"/>'
            f'<line x1="{x - 7:.1f}" y1="{y + half:.1f}" x2="{x - 1:.1f}" y2="{y - half:.1f}" stroke="{ink}" stroke-width="1.2"/>'
            f'<line x1="{x + 1:.1f}" y1="{y + half:.1f}" x2="{x + 7:.1f}" y2="{y - half:.1f}" stroke="{ink}" stroke-width="1.2"/>'
            '</g>')


# The standard notes, then any the source adds, each wrapped to 150 characters. A routed
# harness is drawn to scale, and a 3D route is drawn in plan.
unchecked_note = "NOT YET CHECKED: VERIFY PARTS, PINOUTS AND LENGTHS AGAINST THE DATASHEETS AND DESIGN BEFORE RELEASE."


def default_notes(source: HarnessSource, tree: HarnessTree, scale_denominator: float | None) -> list[str]:
    """The notes printed on sheet 1."""
    drawing = source["drawing"]
    datum = drawing.get("datum", "connector rear face")
    tolerances = ", ".join((f"≤{row['upto']}: ±{row['tol']}" if row.get("upto") else f"over: ±{row['tol']}")
                           for row in drawing.get("tolerance", conventions(drawing)["tolerance"]))
    # Until a person signs it as checked, the drawing says it has not been: it was drawn by
    # software from a source that may itself have been written by an assistant.
    unchecked = [] if drawing.get("checked_by") else [unchecked_note]
    notes = unchecked + [
        f"FABRICATE, INSPECT AND TEST PER IPC/WHMA-A-620, CLASS {drawing.get('ipc_class', 2)}.",
        f"ALL DIMENSIONS IN {drawing.get('units', 'mm').upper()}. LENGTHS ARE MEASURED FROM {datum.upper()} TO BREAKOUT CENTRE "
        f"OR TO THE NEXT {datum.upper()}.",
        f"LENGTH TOLERANCES UNLESS OTHERWISE SPECIFIED: {tolerances}."
        + ("" if scale_denominator else " SEGMENT DIMENSIONS GOVERN; OVERALL DIMENSIONS ARE REFERENCE."),
        (f"DRAWN TO SCALE 1:{format_length(scale_denominator)} ON A3; DIMENSIONS GOVERN." if scale_denominator else
         "DRAWING NOT TO SCALE.") + " WIRE CUT LENGTHS PER WIRE LIST; CONNECTIONS PER CONNECTOR TABLES AND WIRING DIAGRAM.",
    ]
    if tree.geometry and tree.geometry.dimensions == 3:
        notes.append("THE 3D ROUTE IS SHOWN FLATTENED, AS LAID ON THE FORMBOARD; SEE THE 3D VIEW FOR ITS SHAPE IN PLACE.")
    if any(wire.get("twist") for wire in source["wires"]):
        notes.append("TWIST INDICATED WIRES PER IPC/WHMA-A-620.")
    # A cable's conductors are cut with their cable, so only a loose twisted wire takes up length.
    if any(wire.get("twist") and not wire.get("cable") for wire in source["wires"]):
        notes.append(f"TWISTED WIRE CUT LENGTHS INCLUDE {drawing.get('twist_takeup', default_twist_takeup)} "
                     "TAKE-UP OVER THE TWISTED RUN.")
    if source["layout"].get("labels"):
        notes.append("LABELS READ TOWARD THE CONNECTOR; POSITION DIMENSIONED FROM DATUM TO LABEL CENTRE.")
    notes.append("CONTINUITY-TEST 100% AGAINST THE WIRE LIST; NO SHORTS BETWEEN NETS.")
    lengths = [(tree.segment_lengths[segment], tree.segment_minimums.get(segment)) for segment in tree.segment_lengths]
    if any(length is None and minimum is None for length, minimum in lengths):
        notes.append("LENGTHS MARKED TBD ARE NOT YET SET; SEGMENTS SO MARKED ARE DRAWN AT A STAND-IN LENGTH. "
                     "DO NOT CUT FROM THIS REVISION.")
    if any(minimum is not None for _, minimum in lengths):
        notes.append("LENGTHS MARKED ≥ ARE MINIMUMS; THE FINAL LENGTH IS NOT YET SET. "
                     "SEGMENTS WITH A BREAK ARE NOT DRAWN TO THEIR LENGTH.")
    notes += drawing.get("notes", [])
    return [textwrap.fill(note, 150, subsequent_indent="     ") for note in notes]
