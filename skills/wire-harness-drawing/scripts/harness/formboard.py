"""Sheet 1: the harness laid flat, as built on a formboard, not to scale."""
import math
import textwrap
from collections import defaultdict
from dataclasses import dataclass, field

from harness.bom import BomLine, find_numbers, item_find_numbers
from harness.frame import Box, frame, frame_box
from harness.routing import HarnessTree, Route, wire_counts_by_segment
from harness.source import (HarnessSource, color_parts, conventions, default_twist_takeup, display_color, format_length,
                            is_splice, pins_of, tolerance_for, wire_end)
from harness.svg import (balloon_pitch, balloon_radius, balloon_stack, horizontal_dimension, ink, line, rect,
                         sheet_height, sheet_width, text, text_width)
from harness.validation import covered_segment_ends, parse_segment_length, segment_length_value

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

    def boxes(self) -> list[tuple[str, Box]]:
        """Every recorded box, whatever its kind."""
        return self.texts + self.dimension_lines + self.bodies


def boxes_overlap(first: Box, second: Box) -> bool:
    return first[0] < second[2] and second[0] < first[2] and first[1] < second[3] and second[1] < first[3]


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


@dataclass
class Placement:
    x: dict[str, float]
    y: dict[str, float]


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


# Leaves get evenly spaced lanes top to bottom, and every other node sits on its trunk's lane.
# Across, each segment is drawn in proportion to its length but no shorter than 110 or longer
# than 420, scaled down to fit the box and centred in it.
def place_nodes(tree: HarnessTree, box: Box) -> Placement:
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
    lane = min(170, max(80, (bottom - top) / max(1, len(leaves))))
    middle = (top + bottom) / 2
    ys = {node: middle + (index - (len(leaves) - 1) / 2) * lane for index, node in enumerate(leaves)}

    def set_lane(node):
        if not order[node]:
            return ys[node]
        for child in order[node]:
            set_lane(child)
        ys[node] = ys[trunk[node]]
        return ys[node]

    set_lane(tree.root)
    distance = {tree.root: 0.0}
    for node in tree.order[1:]:
        distance[node] = distance[tree.parent[node]] + tree.drawn_length(frozenset((node, tree.parent[node])))
    scale = (right - left) / (max(distance.values()) or 1)
    drawn = {segment: min(max(tree.drawn_length(segment) * scale, 110), 420) for segment in tree.segment_lengths}
    xs = {tree.root: left}
    for node in tree.order[1:]:
        xs[node] = xs[tree.parent[node]] + drawn[frozenset((node, tree.parent[node]))]
    span = max(xs.values()) - left
    if span > (right - left):
        squeeze = (right - left) / span
        xs = {node: left + (x - left) * squeeze for node, x in xs.items()}
    shift = (right - max(xs.values())) / 2
    xs = {node: x + max(0, shift) for node, x in xs.items()}
    return Placement(xs, ys)


def bundle_path(parent_x, parent_y, child_x, child_y) -> tuple[str, tuple[float, float]]:
    """The SVG path of a segment, and the x range of its straight run after any bend."""
    if abs(parent_y - child_y) < 0.5:
        return f"M{parent_x:.1f},{parent_y:.1f} L{child_x:.1f},{child_y:.1f}", (parent_x, child_x)
    bend = min((child_x - parent_x) * 0.55, max(60, abs(child_y - parent_y) * 0.9))
    return (f"M{parent_x:.1f},{parent_y:.1f} C{parent_x + bend * 0.5:.1f},{parent_y:.1f} {parent_x + bend * 0.5:.1f},{child_y:.1f} "
            f"{parent_x + bend:.1f},{child_y:.1f} L{child_x:.1f},{child_y:.1f}"), (parent_x + bend, child_x)


# ---------- The sheet ----------


# Draw sheet 1 in layers: coverings under the bundles, then segment dimensions, breakouts,
# connectors and splices, labels, covering balloons, overall dimensions and notes. Each
# layer records what it draws, so later layers can keep clear of it.
def formboard_sheet(source: HarnessSource, tree: HarnessTree, routes: list[Route], bom: list[BomLine],
                    sheet_count: int, check_errors: int) -> tuple[str, SheetLayout]:
    """Sheet 1's SVG and the record of what it draws where."""
    out, regions = frame(source, 1, sheet_count, "HARNESS DRAWING", check_errors)
    sheet = FormboardSheet(source, tree, bom, out, SheetLayout(regions))
    covering_marks = sheet.draw_coverings()
    sheet.draw_bundles(wire_counts_by_segment(routes))
    sheet.draw_segment_dimensions()
    sheet.draw_breakouts()
    sheet.draw_connectors()
    sheet.draw_labels()
    sheet.draw_covering_balloons(covering_marks)
    sheet.draw_overall_dimensions()
    sheet.draw_notes()
    out.append("</svg>")
    return "\n".join(out), sheet.layout


class FormboardSheet:
    """Sheet 1 while it is being drawn: the source, where each node sits, and what is drawn so far."""

    def __init__(self, source: HarnessSource, tree: HarnessTree, bom: list[BomLine], out: list[str],
                 layout: SheetLayout) -> None:
        self.source, self.tree, self.bom, self.out, self.layout = source, tree, bom, out, layout
        self.drawing = source["drawing"]
        self.connectors = source["connectors"]
        self.box = self.drawing_box()
        placement = place_nodes(tree, self.box)
        self.x, self.y = placement.x, placement.y
        self.caption_bottom: dict[str, float] = {}

    # The drawing gets the frame above the overall dimensions, which get the space above the notes.
    def drawing_box(self) -> Box:
        """The box the harness itself is laid out in."""
        tree = self.tree
        leaf_count = sum(1 for node in tree.order if node in self.connectors and node != tree.root and tree.is_leaf(node))
        notes_top = frame_box[3] - 12 - 15 * sum(note.count("\n") + 1 for note in default_notes(self.source)) - 30
        bottom = min(notes_top, sheet_height - 150) - (24 * leaf_count + 40) - 70
        return (170, 150, sheet_width - 230, max(bottom, 420))

    def parent_and_child(self, ends) -> tuple[str, str]:
        start, end = ends
        return (start, end) if self.tree.parent.get(end) == start else (end, start)

    def draw_coverings(self) -> list[tuple[dict, float, float, bool]]:
        """Shade each covered segment; return where each covering's balloon goes."""
        marks = []
        for covering in self.source["layout"].get("coverings") or []:
            covered = [tuple(covered_segment_ends(segment)) for segment in covering["segments"]]
            drawn = [ends for ends in covered if frozenset(ends) in self.tree.segment_lengths]
            for ends in drawn:
                parent, child = self.parent_and_child(ends)
                path, _ = bundle_path(self.x[parent], self.y[parent], self.x[child], self.y[child])
                self.out.append(f'<path d="{path}" fill="none" stroke="{covering.get("display_color", "#9aa7b8")}" '
                                f'stroke-width="{covering.get("display_width", 16)}" stroke-linecap="butt" opacity="0.55"/>')
            if drawn:
                parent, child = self.parent_and_child(drawn[0])
                marks.append((covering, (self.x[parent] + self.x[child]) / 2, self.y[child], self.y[child] >= self.y[parent]))
        return marks

    def draw_bundles(self, wire_counts: dict) -> None:
        """Each segment as a bundle whose width grows with its wire count; an unknown length shows a break."""
        for node in self.tree.order[1:]:
            parent = self.tree.parent[node]
            thickness = 1.6 * math.sqrt(max(wire_counts.get(frozenset((node, parent)), 0), 1))
            path, (run_start, run_end) = bundle_path(self.x[parent], self.y[parent], self.x[node], self.y[node])
            self.out.append(f'<path d="{path}" fill="none" stroke="#333" stroke-width="{3 + thickness:.1f}" stroke-linecap="round"/>')
            self.out.append(f'<path d="{path}" fill="none" stroke="#9a9a9a" stroke-width="{1 + thickness:.1f}" stroke-linecap="round"/>')
            if self.tree.segment_lengths[frozenset((node, parent))] is None:
                self.out.append(length_break((run_start + run_end) / 2, self.y[node], 3 + thickness))


    # A straight segment gets a dimension line beside it; a bent branch gets its length
    # called out along its run, as NTS drawings do.
    def draw_segment_dimensions(self) -> None:
        """Dimension each segment with its tolerance."""
        for node in self.tree.order[1:]:
            parent = self.tree.parent[node]
            length = self.tree.segment_lengths[frozenset((node, parent))]
            label = segment_dimension_label(self.drawing, length, self.tree.segment_minimums.get(frozenset((node, parent))))
            what = f"dimension {parent}–{node}"
            if abs(self.y[parent] - self.y[node]) < 0.5:
                dimension_y = self.y[node] + (-30 if self.y[node] < self.y[parent] else 34)
                self.out.append(draw_dimension(self.layout, what, self.x[parent], self.x[node], dimension_y, label,
                                               (self.y[parent], self.y[node])))
                continue
            _, (run_start, _) = bundle_path(self.x[parent], self.y[parent], self.x[node], self.y[node])
            label_width = len(label) * 6.2 + 8
            label_x = self.x[parent] + (run_start - self.x[parent]) * 0.5 + 8 + label_width / 2
            label_y = (self.y[parent] + self.y[node]) / 2
            self.layout.texts.append((what, (label_x - label_width / 2, label_y - 7, label_x + label_width / 2, label_y + 7)))
            self.out.append(rect(label_x - label_width / 2, label_y - 7, label_width, 14, fill="white", stroke="none"))
            self.out.append(text(label_x, label_y + 4, label, 11, "middle"))

    def draw_breakouts(self) -> None:
        """A small circle and name at each node that is not a connector."""
        for node in self.tree.order:
            if node in self.connectors:
                continue
            x, y = self.x[node], self.y[node]
            self.out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="white" stroke="{ink}" stroke-width="1.2"/>')
            self.out.append(text(x - 6, y - 10, node, 9, "end", fill="#555"))
            self.layout.texts.append((f"breakout {node}", (x - 6 - text_width(node, 9, False), y - 19, x - 6, y - 8)))

    def draw_connectors(self) -> None:
        for designator, connector in self.connectors.items():
            if designator not in self.x:
                continue
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
        numbers = find_numbers(self.bom, "splice", designator)
        if numbers:
            self.out.append(draw_balloons(self.layout, f"{designator} balloons", x + 30, y - 45, numbers, x + 9, y - 3,
                                          f"splice {designator}"))

    # A connector is a body box with its mating face marked, a fan of its wires in their
    # colours between body and bundle, a caption below and find-number balloons above. The
    # root connector faces left; every other faces right.
    def draw_connector(self, designator: str, connector: dict) -> None:
        """Draw one connector with its wires, caption and balloons."""
        x, y = self.x[designator], self.y[designator]
        faces_left = designator == self.tree.root
        body_height = min(110, max(44, 8 + len(pins_of(connector)) * 3.2))
        body_x = x - connector_body_width if faces_left else x
        self.draw_wire_fan(designator, x, y, body_height, -1 if faces_left else 1)
        self.out.append(rect(body_x, y - body_height / 2, connector_body_width, body_height, fill="#e4e4e4", stroke_width=1.2,
                             extra='rx="3"'))
        mating_x = body_x if faces_left else body_x + connector_body_width - 6
        self.out.append(rect(mating_x, y - body_height / 2 + 6, 6, body_height - 12, fill="#bdbdbd", stroke_width=0.8))
        self.draw_caption(designator, connector, x, y, body_x, body_height, faces_left)
        body_left = body_x - (0 if faces_left else connector_fan_length)
        body_right = body_x + connector_body_width + (connector_fan_length if faces_left else 0)
        self.layout.bodies.append((f"connector {designator}", (body_left, y - body_height / 2, body_right, y + body_height / 2)))
        self.draw_connector_balloons(designator, body_x, y - body_height / 2, faces_left)

    def draw_wire_fan(self, designator: str, x, y, body_height, direction: int) -> None:
        """Each wire at a connector, in its colour, fanning from the bundle into the body; stripes dashed over."""
        wires_here = [wire for wire in self.source["wires"]
                      if wire_end(wire["from"])[0] == designator or wire_end(wire["to"])[0] == designator]
        count = len(wires_here)
        fan_start = x - direction * connector_fan_length
        control_x = x - direction * connector_fan_length * .5
        for index, wire in enumerate(wires_here):
            wire_y = y + (index - (count - 1) / 2) * min(5, (body_height - 10) / max(count, 1))
            path = f"M{fan_start:.1f},{y:.1f} C{control_x:.1f},{y:.1f} {control_x:.1f},{wire_y:.1f} {x:.1f},{wire_y:.1f}"
            base_color, *stripe_colors = color_parts(wire.get("color"))
            self.out.append(f'<path d="{path}" fill="none" stroke="{display_color(base_color)}" stroke-width="2"/>')
            for stripe in stripe_colors[:1]:
                self.out.append(f'<path d="{path}" fill="none" stroke="{display_color(stripe)}" stroke-width="2" '
                                'stroke-dasharray="3 3"/>')

    def draw_caption(self, designator: str, connector: dict, x, y, body_x, body_height, faces_left: bool) -> None:
        """Designator and description, centred under the body but clear of the datum line at x."""
        description = connector.get("label") or connector.get("type", "")
        caption_width = max(text_width(designator, 14, True), text_width(description, 9.5, False))
        centred = body_x + connector_body_width / 2
        caption_x = min(centred, x - 4 - caption_width / 2) if faces_left else max(centred, x + 4 + caption_width / 2)
        self.out.append(text(caption_x, y + body_height / 2 + 18, designator, 14, "middle", "bold",
                             extra='text-decoration="underline"'))
        self.out.append(text(caption_x, y + body_height / 2 + 32, description, 9.5, "middle", fill="#333"))
        self.layout.texts.append((f"connector {designator} caption", (caption_x - caption_width / 2, y + body_height / 2 + 4,
                                                                      caption_x + caption_width / 2, y + body_height / 2 + 35)))
        self.caption_bottom[designator] = y + body_height / 2 + 38

    def draw_connector_balloons(self, designator: str, body_x, body_top, faces_left: bool) -> None:
        """Housing, contact and accessory find numbers above the body; contacts carry their count."""
        numbers = (find_numbers(self.bom, "connector", designator) + find_numbers(self.bom, "contact", designator)
                   + find_numbers(self.bom, "accessory", designator))
        quantities = {}
        contact_numbers = find_numbers(self.bom, "contact", designator)
        if contact_numbers:
            pins_used = {wire_end(wire[end])[1] for wire in self.source["wires"] for end in ("from", "to")
                         if wire_end(wire[end])[0] == designator}
            quantities[contact_numbers[0]] = f"{len(pins_used)}X"  # one contact per pin used, as in the BOM
        balloon_x = body_x - 40 if faces_left else body_x + connector_body_width + 40
        target_x = body_x + connector_body_width * (0.3 if faces_left else 0.7)
        self.out.append(draw_balloons(self.layout, f"{designator} balloons", balloon_x, body_top - 40, numbers,
                                      target_x, body_top, f"connector {designator}", quantities))

    # A label sits on its connector's own segment at its distance, drawn at least 60 and at
    # most 60% of the way along. Its dimension goes on the side away from the segment's
    # parent; its balloon on the same side, beyond the label's far end.
    def draw_labels(self) -> None:
        """Each label box with its position dimension and balloon."""
        for label in self.source["layout"].get("labels") or []:
            node = label["at"]
            if node not in self.x:
                continue
            neighbour = self.tree.neighbour_toward_body(node)
            if neighbour is None:
                continue
            self.draw_label(label, node, neighbour)

    def draw_label(self, label: dict, node: str, neighbour: str) -> None:
        x_node, y = self.x[node], self.y[node]
        distance = float(label.get("distance", conventions(self.drawing)["label_distance"]))
        segment_length = self.tree.drawn_length(frozenset((node, neighbour)))
        x = x_node + (self.x[neighbour] - x_node) * min(distance / segment_length, 0.6)
        x = x_node + math.copysign(max(abs(x - x_node), 60), self.x[neighbour] - x_node)
        content = label["text"]
        width = max(46, text_width(content, 10, False) + 12)
        self.out.append(rect(x - width / 2, y - 9, width, 18, fill="white", stroke_width=1))
        self.out.append(text(x, y + 4, content, 10, "middle"))
        self.layout.texts.append((f"label {content}", (x - width / 2, y - 9, x + width / 2, y + 9)))
        segment_child = node if node != self.tree.root else neighbour
        segment_runs_up = self.y[segment_child] < self.y[self.tree.parent[segment_child]]
        side = 1 if segment_runs_up else -1
        connector_on_right = x_node > x
        extensions = (y + side * 9, y) if connector_on_right else (y, y + side * 9)
        self.out.append(draw_dimension(self.layout, f"label {content} dimension", min(x_node, x), max(x_node, x),
                                       y + side * 26, format_length(distance), extensions))
        numbers = item_find_numbers(self.bom, label["item"]) if label.get("item") else []
        if numbers:
            away = -1 if connector_on_right else 1
            self.out.append(draw_balloons(self.layout, f"label {content} balloon", x + away * (width / 2 + 22), y + side * 44,
                                          numbers, x + away * (width / 2 - 6), y + side * 9, f"label {content}"))

    def draw_covering_balloons(self, marks: list[tuple[dict, float, float, bool]]) -> None:
        """Each covering's AR balloon, on the side of the bundle opposite its segment dimensions."""
        for covering, x, y, dimensions_below in marks:
            numbers = item_find_numbers(self.bom, covering.get("item"))
            if numbers:
                side = -1 if dimensions_below else 1
                self.out.append(draw_balloons(self.layout, f"{covering.get('item')} balloon", x + 25, y + side * 55, numbers,
                                              x, y + side * 8, f"{covering.get('item')} covering", {numbers[0]: "AR"}))

    # Overall dimensions from the root datum to each leaf connector. The segment dimensions
    # already fix these lengths, each with its own tolerance, so an overall tolerance would
    # contradict their stack-up: the overall lengths are reference only.
    def draw_overall_dimensions(self) -> None:
        """Reference dimensions from the root to each leaf connector, with their extension lines."""
        tree, root = self.tree, self.tree.root
        leaves = sorted((node for node in tree.order if node in self.connectors and node != root and tree.is_leaf(node)),
                        key=lambda node: self.x[node])
        first_row = max(max(self.y.values()) + 100, self.box[3] + 60)
        for index, leaf in enumerate(leaves):
            length, minimum = tree.depth[leaf], tree.minimum_depth[leaf]
            label = f"{format_length(length)} REF" if length is not None else f"{unknown_length_text(minimum)} REF"
            what = f"overall dimension {root}–{leaf}"
            row_y = first_row + index * 24
            self.out.append(draw_dimension(self.layout, what, self.x[root], self.x[leaf], row_y, f"{label}  ({root}–{leaf})"))
            self.out.append(draw_broken_extension(self.layout, f"{what} extension", self.x[leaf],
                                                  self.caption_bottom.get(leaf, self.y[leaf] + 20), row_y + 4, {what}))
        if leaves:
            self.out.append(draw_broken_extension(self.layout, f"{root} datum extension", self.x[root],
                                                  self.caption_bottom.get(root, self.y[root] + 20),
                                                  first_row + (len(leaves) - 1) * 24 + 4,
                                                  {f"overall dimension {root}–{leaf}" for leaf in leaves}))

    def draw_notes(self) -> None:
        """The numbered notes at the bottom left, recorded as a block the drawing keeps clear of."""
        lines = []
        for number, note in enumerate(default_notes(self.source), 1):
            for index, content in enumerate(note.split("\n")):
                lines.append((f"{number}.  " if index == 0 else "") + content)
        top = frame_box[3] - 12 - 15 * len(lines)
        left = frame_box[0] + 10
        self.out.append(text(left, top - 8, "NOTES:", 12, weight="bold", extra='text-decoration="underline"'))
        for index, content in enumerate(lines):
            self.out.append(text(left, top + 12 + index * 15, content, 10.5, extra='xml:space="preserve"'))
        widest = max(text_width(content, 10.5, False) for content in lines)
        self.layout.regions["notes"] = (left, top - 20, left + widest, frame_box[3])


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


# The standard notes, then any the source adds, each wrapped to 150 characters.
def default_notes(source: HarnessSource) -> list[str]:
    """The notes printed on sheet 1."""
    drawing = source["drawing"]
    datum = drawing.get("datum", "connector rear face")
    tolerances = ", ".join((f"≤{row['upto']}: ±{row['tol']}" if row.get("upto") else f"over: ±{row['tol']}")
                           for row in drawing.get("tolerance", conventions(drawing)["tolerance"]))
    notes = [
        f"FABRICATE, INSPECT AND TEST PER IPC/WHMA-A-620, CLASS {drawing.get('ipc_class', 2)}.",
        f"ALL DIMENSIONS IN {drawing.get('units', 'mm').upper()}. LENGTHS ARE MEASURED FROM {datum.upper()} TO BREAKOUT CENTRE "
        f"OR TO THE NEXT {datum.upper()}.",
        f"LENGTH TOLERANCES UNLESS OTHERWISE SPECIFIED: {tolerances}. SEGMENT DIMENSIONS GOVERN; OVERALL DIMENSIONS ARE REFERENCE.",
        "DRAWING NOT TO SCALE. WIRE CUT LENGTHS PER WIRE LIST; CONNECTIONS PER CONNECTOR TABLES AND WIRING DIAGRAM.",
    ]
    if any(wire.get("twist") for wire in source["wires"]):
        notes.append("TWIST INDICATED WIRES PER IPC/WHMA-A-620.")
        notes.append(f"TWISTED WIRE CUT LENGTHS INCLUDE {drawing.get('twist_takeup', default_twist_takeup)} "
                     "TAKE-UP OVER THE TWISTED RUN.")
    if source["layout"].get("labels"):
        notes.append("LABELS READ TOWARD THE CONNECTOR; POSITION DIMENSIONED FROM DATUM TO LABEL CENTRE.")
    notes.append("CONTINUITY-TEST 100% AGAINST THE WIRE LIST; NO SHORTS BETWEEN NETS.")
    lengths = [parse_segment_length(segment_length_value(segment)) for segment in source["layout"].get("segments") or []]
    if any(length is None and minimum is None for length, minimum in lengths):
        notes.append("LENGTHS MARKED TBD ARE NOT YET SET; SEGMENTS SO MARKED ARE DRAWN AT A STAND-IN LENGTH. "
                     "DO NOT CUT FROM THIS REVISION.")
    if any(minimum is not None for _, minimum in lengths):
        notes.append("LENGTHS MARKED ≥ ARE MINIMUMS; THE FINAL LENGTH IS NOT YET SET. "
                     "SEGMENTS WITH A BREAK ARE NOT DRAWN TO THEIR LENGTH.")
    notes += drawing.get("notes", [])
    return [textwrap.fill(note, 150, subsequent_indent="     ") for note in notes]
