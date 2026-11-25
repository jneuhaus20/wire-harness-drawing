"""A connector's pinout diagram, drawn only from a cavity layout the source states."""
import math
from dataclasses import dataclass

from harness.source import HarnessSource, cavity_positions, color_parts, display_color, wire_end
from harness.svg import ink, rect, text

cavity_pitch = 24
cavity_radius = 8
outline_margin = 14
title_height = 20


# A block drawn at a position the table flow chooses.
@dataclass
class Figure:
    width: float
    height: float
    svg_at: object  # (x, y) -> str

    def draw(self, x: float, y: float) -> str:
        return self.svg_at(x, y)


# Positions in cavity pitches: a grid is already in pitches, a ring is spread so neighbouring
# cavities sit a pitch apart, and explicit positions are scaled so the closest two do.
def scaled_positions(connector: dict) -> dict[str, tuple[float, float]]:
    """Cavity positions in pitches, with the top-left cavity bound at (0, 0)."""
    positions = cavity_positions(connector)
    face = connector.get("face") or {}
    if "ring" in face:
        radius = max(1.0, len(positions) / (2 * math.pi))
        positions = {pin: (x * radius, y * radius) for pin, (x, y) in positions.items()}
    elif "cavities" in face and len(positions) > 1:
        points = list(positions.values())
        closest = min(math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1:]) or 1
        positions = {pin: (x / closest, y / closest) for pin, (x, y) in positions.items()}
    left = min(x for x, _ in positions.values())
    top = min(y for _, y in positions.values())
    return {pin: (x - left, y - top) for pin, (x, y) in positions.items()}


def is_dark(color: str) -> bool:
    red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * red + 0.587 * green + 0.114 * blue < 140


# Each cavity is filled with the colour of the wire in it (its base colour), empty cavities
# are white, and each carries its pin name. A ring or circular connector gets a round outline.
def pinout_figure(source: HarnessSource, designator: str, connector: dict) -> Figure | None:
    """The pinout diagram of a connector with a stated face, or None."""
    positions = scaled_positions(connector) if cavity_positions(connector) else {}
    if not positions:
        return None
    wire_colors = {}
    for wire in source["wires"]:
        for end in ("from", "to"):
            end_designator, pin = wire_end(wire[end])
            if end_designator == designator and pin not in wire_colors and wire.get("color"):
                wire_colors[pin] = display_color(color_parts(wire["color"])[0])
    span_x = max(x for x, _ in positions.values()) * cavity_pitch
    span_y = max(y for _, y in positions.values()) * cavity_pitch
    face = connector["face"]
    round_outline = "ring" in face or connector.get("shape") == "circular"
    title = f"{designator} PINOUT, {face.get('view', 'mating face').upper()}"
    inner = cavity_radius + outline_margin
    width = max(span_x + 2 * inner, len(title) * 6.5)
    height = title_height + span_y + 2 * inner

    def svg_at(x: float, y: float) -> str:
        left = x + (width - span_x) / 2
        top = y + title_height + inner
        out = [f'<g class="pinout" data-connector="{designator}">',
               text(x + width / 2, y + 12, title, 10.5, "middle", "bold")]
        if round_outline:
            radius = max(span_x, span_y) / 2 + inner
            out.append(f'<ellipse cx="{left + span_x / 2:.1f}" cy="{top + span_y / 2:.1f}" rx="{radius:.1f}" ry="{radius:.1f}" '
                       f'fill="#f3f3f3" stroke="{ink}" stroke-width="1.2"/>')
        else:
            out.append(rect(left - inner, top - inner, span_x + 2 * inner, span_y + 2 * inner, fill="#f3f3f3", stroke_width=1.2,
                            extra='rx="6"'))
        for pin, (column, row) in positions.items():
            cx, cy = left + column * cavity_pitch, top + row * cavity_pitch
            fill = wire_colors.get(pin, "white")
            label_color = "white" if fill != "white" and is_dark(fill) else ink
            out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{cavity_radius}" fill="{fill}" stroke="{ink}" stroke-width="1"/>')
            out.append(text(cx, cy + 3, pin, 8, "middle", "bold", fill=label_color))
        out.append("</g>")
        return "".join(out)

    return Figure(width, height, svg_at)
