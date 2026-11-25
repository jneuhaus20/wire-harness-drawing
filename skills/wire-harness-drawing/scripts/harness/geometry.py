"""Optional fixed routing geometry: where each node sits and how each segment bends on the way.

Positions are in the drawing's units: x to the right and y down the sheet, as the harness lies
on the table, and z up from the table when the route is 3D. A 2D route is flat, all in the table.
"""
import math
from dataclasses import dataclass

from harness.source import Findings, HarnessSource, is_number
from harness.validation import segment_ends

Point = tuple[float, float, float]


@dataclass
class RouteGeometry:
    dimensions: int
    positions: dict[str, Point]
    segment_points: dict[tuple[str, str], list[Point]]  # keyed (start, end) as the source declares the segment

    def points(self, start: str, end: str) -> list[Point]:
        """A segment's points from start to end, whichever way the source declared it."""
        if (start, end) in self.segment_points:
            return self.segment_points[(start, end)]
        return self.segment_points[(end, start)][::-1]


def polyline_length(points: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def segment_via(segment: list | dict) -> list | None:
    """The via points a segment gives, from the list form's fourth item or the mapping form."""
    if isinstance(segment, list):
        return segment[3].get("via") if len(segment) > 3 and isinstance(segment[3], dict) else None
    return segment.get("via")


def is_position(value, dimensions: int) -> bool:
    return isinstance(value, list) and len(value) == dimensions and all(is_number(v) for v in value)


def as_point(value: list) -> Point:
    return (float(value[0]), float(value[1]), float(value[2]) if len(value) > 2 else 0.0)


# The geometry is all or nothing: every node gets a position, all positions and via points
# share one dimension. Anything less is an ERROR and the drawing falls back to its automatic,
# not-to-scale layout.
def route_geometry(source: HarnessSource, findings: Findings) -> RouteGeometry | None:
    """The source's routing geometry, or None when it gives none or gives it wrongly."""
    layout = source["layout"]
    positions = layout.get("nodes")
    if not positions:
        return None
    sizes = {len(value) if isinstance(value, list) else 0 for value in positions.values()}
    if not sizes <= {2, 3} or len(sizes) != 1:
        findings.error("layout.nodes mixes 2D and 3D positions" if sizes == {2, 3}
                       else "layout.nodes positions must be [x, y] or [x, y, z] numbers")
        return None
    dimensions = sizes.pop()
    segments = layout.get("segments") or []
    nodes = list(dict.fromkeys(node for segment in segments for node in segment_ends(segment)))
    problems = [f"layout.nodes gives no position for {node}; give every node one, or none" for node in nodes if node not in positions]
    problems += [f"layout.nodes position for {node} is not {dimensions} numbers" for node, value in positions.items()
                 if not is_position(value, dimensions)]
    segment_points = {}
    for segment in segments:
        start, end = segment_ends(segment)
        via = segment_via(segment) or []
        bad = [point for point in via if not is_position(point, dimensions)]
        problems += [f"layout segment {start}-{end}: via point {point} is not a {dimensions}D position" for point in bad]
        if not problems:
            segment_points[(start, end)] = [as_point(positions[start]), *map(as_point, via), as_point(positions[end])]
    for problem in problems:
        findings.error(problem)
    if problems:
        return None
    return RouteGeometry(dimensions, {node: as_point(value) for node, value in positions.items()}, segment_points)
