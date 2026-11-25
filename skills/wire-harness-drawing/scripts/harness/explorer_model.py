"""The harness model the explorer component draws: one JSON document per harness, built from the same analysis as the drawing."""
from harness.formboard import segment_dimension_label, segment_path, sheet_placement
from harness.pinout import scaled_positions
from harness.source import body_color, chosen_color, format_length, color_parts, display_color, is_generic, is_splice, pin_label, pins_of, wire_end

model_format = "wire-harness-explorer/1"


def connector_entry(designator: str, connector: dict) -> dict:
    """One connector: what it is, its pins, and its face when the source states one."""
    face = None
    if connector.get("face"):
        face = {"view": connector["face"].get("view", "mating face"),
                "round": "ring" in connector["face"] or connector.get("shape") == "circular",
                "cavities": {pin: [round(x, 3), round(y, 3)] for pin, (x, y) in scaled_positions(connector).items()}}
    return {"id": designator, "label": connector.get("label", ""), "type": connector.get("type", ""),
            "part_number": connector.get("pn", ""), "manufacturer": connector.get("manufacturer", ""),
            "splice": is_splice(connector), "generic": is_generic(connector),
            "shape": connector.get("shape"), "gender": connector.get("gender"),
            "pins": [{"pin": pin, "label": pin_label(connector, pin)} for pin in pins_of(connector)], "face": face,
            "body": body_entry(connector.get("body"))}


def body_entry(body: dict | None) -> dict | None:
    """A stated body as the explorer draws it: its maker's mesh, or its datasheet shape, size and colour;
    None when not stated."""
    if not body:
        return None
    if body.get("mesh"):
        rotate = [float(angle) for angle in body.get("rotate", [0, 0, 0])]
        return {"shape": "model", "mesh": body["mesh"], "rotate": [int(a) if a.is_integer() else a for a in rotate]}
    sizes = {"diameter": "width"} if body.get("shape") == "cylinder" else {}
    entry = {"shape": body.get("shape", "box"), "length": float(body["length"])}
    for key in (("diameter",) if body.get("shape") == "cylinder" else ("width", "height")):
        entry[sizes.get(key, key)] = float(body[key])
    if body.get("shape") == "cylinder":
        entry["height"] = entry["width"]
    entry["color"] = body_color(body.get("color", "grey"))
    return {key: (int(value) if isinstance(value, float) and value.is_integer() else value) for key, value in entry.items()}


# A cable is one item: its jacket's run and where along it the jacket stops, its cut length,
# and at each end the jacket to strip back and each conductor's lead beyond it.
def cable_entry(source: dict, cable_id: str, cable: dict, cut) -> dict:
    """One cable as the explorer draws it."""
    conductors = [wire["id"] for wire in source["wires"] if wire.get("cable") == cable_id]
    entry = {"id": cable_id, "description": cable.get("desc", ""), "part_number": cable.get("pn", ""),
             "conductors": len(conductors), "wires": conductors, "shield": bool(cable.get("shield")),
             "color": display_color(color_parts(chosen_color(cable))[0]) if chosen_color(cable) else None}
    if cut:
        entry.update(run=cut.run, breakouts={end.node: whole(end.breakout) for end in cut.ends},
                     cut_length=format_length(cut.cut_length), jacket_length=format_length(cut.jacket_length),
                     ends=[{"node": end.node, "strip_back": format_length(end.strip_back()),
                            "leads": {conductor: format_length(lead) for conductor, lead in end.leads.items()}} for end in cut.ends])
    return entry


def whole(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


def wire_entry(source: dict, wire: dict, route) -> dict:
    """One wire: its ends, signal, gauge, colours (none when not chosen), cut length and route."""
    start, end = wire_end(wire["from"]), wire_end(wire["to"])
    return {"id": wire["id"], "from": {"connector": start[0], "pin": start[1]}, "to": {"connector": end[0], "pin": end[1]},
            "signal": wire.get("signal") or pin_label(source["connectors"].get(start[0], {}), start[1]),
            "gauge": str(wire.get("gauge", "")), "color": wire.get("color", ""),
            "colors": [display_color(part) for part in color_parts(chosen_color(wire))] if chosen_color(wire) else [],
            "cut_length": "" if wire.get("cable") else route.cut_length_text(), "twist": wire.get("twist", ""), "cable": wire.get("cable", ""),
            "route": route.node_names()}


def world_point(point: tuple[float, float, float]) -> list[float]:
    """A route point in the explorer's 3D frame: x across, y up from the table, z toward the viewer."""
    x, y, height = (round(value, 3) for value in point)
    return [int(v) if float(v).is_integer() else v for v in (x, height, y)]


# Placement and bundle paths come from sheet 1's layout, so the explorer's 2D view is the
# drawing's. With routing geometry each segment also carries its route in true units for the
# 3D view; without it the model says geometry "schematic" and the 3D view lays the 2D layout flat.
def harness_model(analysis) -> dict:
    """The explorer's model of an analysed harness."""
    source, tree, routes = analysis.source, analysis.tree, analysis.routes
    drawing = source["drawing"]
    placement = sheet_placement(source, tree, analysis.spacing)
    connectors = source["connectors"]
    wires_by_segment = {}
    for wire, route in zip(source["wires"], routes):
        for segment in route.segments:
            wires_by_segment.setdefault(frozenset(segment), []).append(wire["id"])
    segments = []
    for node in tree.order[1:]:
        parent = tree.parent[node]
        key = frozenset((node, parent))
        entry = {"nodes": [parent, node], "known": tree.segment_lengths[key] is not None,
                 "length": segment_dimension_label(drawing, tree.segment_lengths[key], tree.segment_minimums.get(key)),
                 "path": segment_path(placement, parent, node), "wires": wires_by_segment.get(key, [])}
        if tree.geometry:
            entry["points"] = [world_point(point) for point in tree.geometry.points(parent, node)]
        segments.append(entry)
    nodes = [{"id": node, "kind": ("splice" if is_splice(connectors[node]) else "connector") if node in connectors else "breakout",
              "x": round(placement.x[node], 1), "y": round(placement.y[node], 1)} for node in tree.order]
    cuts = {cut.cable: cut for cut in analysis.cable_cuts}
    cables = [cable_entry(source, cable_id, cable, cuts.get(cable_id)) for cable_id, cable in source["cables"].items()]
    return {"format": model_format, "title": drawing.get("title", ""), "number": drawing.get("number", ""),
            "rev": drawing.get("rev", ""), "units": drawing.get("units", "mm"),
            "geometry": f"{tree.geometry.dimensions}d" if tree.geometry else "schematic", "root": tree.root,
            "connectors": [connector_entry(designator, connector) for designator, connector in connectors.items()],
            "wires": [wire_entry(source, wire, route) for wire, route in zip(source["wires"], routes)],
            "cables": cables, "nodes": nodes, "segments": segments}
