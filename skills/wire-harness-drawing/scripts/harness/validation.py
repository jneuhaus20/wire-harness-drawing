"""Reject source values the generator cannot compute with, before anything is computed."""
import re

from harness.source import (Findings, body_color, body_shapes, HarnessSource, connector_genders, connector_shapes, face_layouts, face_views,
                            format_length, iec_color_code, is_number, undecided_colors, pins_of, unit_conventions)


# Reject each value the rest of the generator cannot compute with, and remove it from the
# source so that everything downstream can trust what is left. Every rejection is an ERROR,
# so a package built from what is left is marked not for release.
def validate_source(source: HarnessSource, findings: Findings) -> None:
    """Report and remove values in the source that are the wrong kind of thing."""
    validate_drawing(source["drawing"], findings)
    validate_connectors(source["connectors"], findings)
    read_colors(source, findings)
    expand_cables(source, findings)
    validate_wires(source, findings)
    validate_layout(source["layout"], findings)


def segment_ends(segment: list | dict) -> tuple:
    """A layout segment's two nodes, from either its list or its mapping form."""
    return (segment[0], segment[1]) if isinstance(segment, list) else (segment.get("from"), segment.get("to"))


def segment_length_value(segment: list | dict):
    """A layout segment's length as written, from either form; None when it has none."""
    if isinstance(segment, list):
        return segment[2] if len(segment) > 2 else None
    return segment.get("length")


def parse_segment_length(value) -> tuple[float | None, float | None]:
    """A validated segment length as (length, minimum): a number, TBD (None, None), or {min: N} (None, N)."""
    if isinstance(value, dict):
        return None, float(value["min"])
    return (None, None) if value in (None, "TBD") else (float(value), None)


def is_minimum_length(value) -> bool:
    return isinstance(value, dict) and set(value) == {"min"} and is_number(value["min"]) and value["min"] >= 0


def covered_segment_ends(covered: str | list) -> list:
    """The two nodes of a segment a covering names, as 'A-B' or [A, B]."""
    return covered.split("-") if isinstance(covered, str) else list(covered)


def covered_segment_name(covered: str | list) -> str:
    return covered if isinstance(covered, str) else "-".join(map(str, covered))


# Drawing-wide values fall back to the unit's default when rejected.
def validate_drawing(drawing: dict, findings: Findings) -> None:
    """Check the units, the drawing-wide lengths, the twist take-up and the tolerance table."""
    units = drawing.get("units", "mm")
    if units not in unit_conventions:
        findings.error(f"drawing.units '{units}' is not one of {', '.join(unit_conventions)}; lengths were read as mm")
    if "round_to" in drawing and not (is_number(drawing["round_to"]) and drawing["round_to"] > 0):
        findings.error(f"drawing.round_to must be a number greater than 0, not '{drawing.pop('round_to')}'")
    for key in ("extra_per_wire", "loopback_length"):
        if key in drawing and not is_number(drawing[key]):
            findings.error(f"drawing.{key} must be a number, not '{drawing.pop(key)}'")
    if "twist_takeup" in drawing and not re.fullmatch(r"\d+(\.\d+)?%", str(drawing["twist_takeup"])):
        findings.error(f"drawing.twist_takeup must be a percentage such as 3%, not '{drawing.pop('twist_takeup')}'")
    tolerance_rows = drawing.get("tolerance")
    if tolerance_rows and all(row.get("upto") is not None for row in tolerance_rows):
        largest = max(row["upto"] for row in tolerance_rows)
        findings.error(f"drawing.tolerance has no row with upto: null; lengths over {format_length(largest)} have no tolerance")


def validate_connectors(connectors: dict, findings: Findings) -> None:
    """Check each connector's wire allowance, shape, gender and face layout."""
    for designator, connector in connectors.items():
        if "wire_allowance" in connector and not is_number(connector["wire_allowance"]):
            findings.error(f"{designator}: wire_allowance must be a number, not '{connector.pop('wire_allowance')}'")
        if "shape" in connector and connector["shape"] not in connector_shapes:
            findings.error(f"{designator}: shape '{connector.pop('shape')}' is not {' or '.join(connector_shapes)}")
        if "gender" in connector and connector["gender"] not in connector_genders:
            findings.error(f"{designator}: gender '{connector.pop('gender')}' is not {' or '.join(connector_genders)}")
        if "body" in connector:
            problems = body_problems(designator, connector["body"])
            for problem in problems:
                findings.error(problem)
            if problems:
                connector.pop("body")
        if "face" in connector:
            problems = face_problems(designator, connector)
            for problem in problems:
                findings.error(problem)
            if problems:
                connector.pop("face")


# A body is drawn only as its datasheet states it; one with any problem is dropped, and the
# connector is drawn as a body not stated.
def body_problems(designator: str, body) -> list[str]:
    """What is wrong with a connector's stated body."""
    if not isinstance(body, dict):
        return [f"{designator}: body must be a mapping with shape, length, width, height and color"]
    problems = []
    if body.get("shape", "box") not in body_shapes:
        problems.append(f"{designator}: body shape '{body['shape']}' is not {', '.join(body_shapes[:-1])} or {body_shapes[-1]}")
    sizes = ("length", "diameter") if body.get("shape") == "cylinder" else ("length", "width", "height")
    for size in sizes:
        if not (is_number(body.get(size)) and float(body[size]) > 0):
            problems.append(f"{designator}: body {size} must be a number above 0")
    if "color" in body and body_color(body["color"]) is None:
        problems.append(f"{designator}: body colour '{body['color']}' is not a colour name or #rrggbb")
    return problems


# A face states one layout that places every pin, seen from a known side. A face with any
# problem is dropped, so no pinout is drawn from it.
def face_problems(designator: str, connector: dict) -> list[str]:
    """What is wrong with a connector's face layout."""
    face = connector["face"]
    if not isinstance(face, dict):
        return [f"{designator}: face must be a mapping with grid, ring or cavities"]
    problems = []
    if face.get("view", "mating face") not in face_views:
        problems.append(f"{designator}: face view '{face['view']}' is not {' or '.join(face_views)}")
    layouts = [layout for layout in face_layouts if layout in face]
    if len(layouts) != 1:
        return problems + [f"{designator}: face must give exactly one of grid, ring or cavities"]
    pins = pins_of(connector)
    if "grid" in face:
        grid = face["grid"]
        if not (isinstance(grid, list) and len(grid) == 2 and all(isinstance(n, int) and n > 0 for n in grid)):
            return problems + [f"{designator}: face grid must be [rows, columns]"]
        if grid[0] * grid[1] < len(pins):
            problems.append(f"{designator}: face grid {grid[0]}×{grid[1]} has {grid[0] * grid[1]} cavities for {len(pins)} pins")
        if face.get("numbering", "rows") not in ("rows", "columns"):
            problems.append(f"{designator}: face numbering '{face['numbering']}' is not rows or columns")
    if "cavities" in face:
        cavities = face["cavities"]
        if not isinstance(cavities, dict):
            return problems + [f"{designator}: face cavities must map each pin to [x, y]"]
        placed = {str(pin) for pin, position in cavities.items()
                  if isinstance(position, list) and len(position) == 2 and all(is_number(v) for v in position)}
        unplaced = [pin for pin in pins if pin not in placed]
        if unplaced:
            problems.append(f"{designator}: face cavities do not place pins {', '.join(unplaced)}")
    return problems


# A colour is read however it is written (BLK, black, WHT/BLU) and kept as its IEC code, so a
# conductor named by colour gets the same name however its colour was spelled. One that is not
# a colour is kept as written, reported, and drawn grey; one left out is simply not known yet.
def read_colors(source: HarnessSource, findings: Findings) -> None:
    """Replace each wire, cable and conductor colour with its IEC code, reporting any that is not a colour."""
    def read(owner: dict, name: str) -> None:
        if owner.get("color") in (None, ""):
            return
        if str(owner["color"]).strip().upper() in undecided_colors:
            owner["color"] = str(owner["color"]).strip().upper()
            return
        code = iec_color_code(owner["color"])
        if code is None:
            findings.warn(f"{name}: colour '{owner['color']}' is not a colour this drawing knows; drawn grey")
        else:
            owner["color"] = code
    for position, wire in enumerate(source["wires"], 1):
        read(wire, wire.get("id") or f"wire #{position}")
    for cable_id, cable in source["cables"].items():
        read(cable, f"cable {cable_id}")
        for position, conductor in enumerate(cable.get("conductors") or [], 1):
            read(conductor, f"cable {cable_id}: conductor {position}")


# A cable is one item; its conductors are named within it, by colour or number (W5-RD, W5-1), and its
# shield's drain wire as SH (W5-SH), bare tinned copper.
# Each conductor becomes a wire of the cable for the checks, the netlist and the tables, so a
# wire's own cable key, from the older form, is refused rather than guessed at.
def expand_cables(source: HarnessSource, findings: Findings) -> None:
    """Turn each cable's conductors into wires of that cable."""
    for wire in source["wires"]:
        if "cable" in wire:
            findings.error(f"{wire.get('id', '?')}: list a cable's conductors under cables.{wire['cable']}.conductors; "
                           "a wire's cable key is not read")
            wire.pop("cable")
    for cable_id, cable in source["cables"].items():
        for position, conductor in enumerate(cable.get("conductors") or [], 1):
            if conductor.get("drain"):
                name, conductor = "SH", {"color": "SR", **conductor}
            else:
                name = conductor.get("color", conductor.get("number"))
            if name is None:
                findings.error(f"cable {cable_id}: conductor {position} needs a color or a number")
                continue
            wire = {key: value for key, value in conductor.items() if key not in ("number", "drain")}
            wire.update(id=f"{cable_id}-{name}", cable=cable_id)
            if "gauge" in cable and "gauge" not in wire:
                wire["gauge"] = cable["gauge"]
            source["wires"].append(wire)


# Give every wire an id first, so each later finding can name the wire it is about. A wire
# without both ends cannot be routed, cut or tabled, so it is reported and dropped.
def validate_wires(source: HarnessSource, findings: Findings) -> None:
    """Name every wire, then check its ends, gauge and length override."""
    for position, wire in enumerate(source["wires"], 1):
        if not wire.get("id"):
            wire["id"] = f"W{position}"
            findings.info(f"wire #{position} has no id; using {wire['id']}")
    complete_wires = []
    for wire in source["wires"]:
        missing_ends = [end for end in ("from", "to") if end not in wire]
        for end in missing_ends:
            findings.error(f"{wire['id']}: missing '{end}'")
        if "gauge" in wire and (is_number(wire["gauge"]) or str(wire["gauge"]).strip().isdigit()):
            findings.error(f"{wire['id']}: gauge '{wire['gauge']}' has no unit; write '{wire['gauge']} AWG' or the size in mm²")
            wire["gauge"] = str(wire["gauge"])
        if "length" in wire and not is_number(wire["length"]):
            findings.error(f"{wire['id']}: length '{wire.pop('length')}' must be a number")
        if not missing_ends:
            complete_wires.append(wire)
    source["wires"] = complete_wires


# A segment with an unusable length is kept with its length TBD, so the layout stays whole.
# A label needs a place; a covering keeps only the segments the layout has.
def validate_layout(layout: dict, findings: Findings) -> None:
    """Check segment lengths, label places and distances, and the segments each covering names."""
    segments = layout.get("segments") or []
    for index, segment in enumerate(segments):
        length = segment_length_value(segment)
        if length is None or length == "TBD" or (is_number(length) and length >= 0) or is_minimum_length(length):
            continue
        start, end = segment_ends(segment)
        if is_number(length):
            findings.error(f"layout segment {start}-{end}: length {format_length(length)} is negative")
        elif isinstance(length, dict) and set(length) == {"min"}:
            findings.error(f"layout segment {start}-{end}: minimum length '{length['min']}' must be a number of 0 or more")
        elif isinstance(length, dict):
            findings.error(f"layout segment {start}-{end}: length {length} must be a number, TBD or {{min: N}}")
        else:
            findings.error(f"layout segment {start}-{end}: length '{length}' must be a number or TBD")
        segments[index] = [start, end, "TBD"]
    placed_labels = []
    for label in layout.get("labels") or []:
        name = label.get("text", label.get("at", "?"))
        if "at" not in label:
            findings.error(f"label {name}: missing 'at'")
            continue
        if "distance" in label and not is_number(label["distance"]):
            findings.error(f"label {name}: distance '{label.pop('distance')}' must be a number")
        placed_labels.append(label)
    layout["labels"] = placed_labels
    declared = {frozenset(segment_ends(segment)) for segment in segments}
    for covering in layout.get("coverings") or []:
        kept = []
        for covered in covering.get("segments") or []:
            if frozenset(covered_segment_ends(covered)) in declared:
                kept.append(covered)
            else:
                findings.error(f"covering {covering.get('item', '?')}: segment {covered_segment_name(covered)} is not in layout.segments")
        covering["segments"] = kept
