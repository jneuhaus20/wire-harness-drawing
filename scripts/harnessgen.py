#!/usr/bin/env python3
"""harnessgen: wire harness manufacturing drawing generator.

One YAML source -> checks, cut lengths, BOM, wire list, connector tables,
a formboard-style harness drawing, and a WireViz wiring diagram.

Usage:  python3 harnessgen.py harness.yaml [-o outdir] [--check-only] [--no-wireviz]
Needs:  pyyaml.  Optional: wireviz + graphviz (wiring diagram sheet),
        cairosvg + pypdf (combined PDF).
"""
import argparse, csv, html, math, os, re, shutil, subprocess, sys, textwrap, base64
from collections import defaultdict, OrderedDict

import yaml

# ----------------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------------

COLORS = {  # IEC 60757 two-letter codes -> display hex
    "BK": "#1a1a1a", "BN": "#8b4513", "RD": "#e01e1e", "OG": "#ff8c00", "YE": "#f2d600",
    "GN": "#14a33a", "BU": "#1f5fd6", "VT": "#8a2be2", "GY": "#8c8c8c", "WH": "#f4f4f4",
    "PK": "#ff8fb4", "TQ": "#20c0c0", "SR": "#c0c0c0", "GD": "#d4af37", "OR": "#ff8c00",
    "BL": "#1f5fd6", "VI": "#8a2be2", "BR": "#8b4513", "GR": "#8c8c8c",
}


def color_parts(code):
    code = (code or "").replace("/", "").upper()
    return [code[i:i + 2] for i in range(0, len(code), 2)] or ["GY"]


def hexcolor(code):
    return COLORS.get(color_parts(code)[0], "#888888")


class Err:
    def __init__(self):
        self.items = []

    def _add(self, sev, msg):
        if (sev, msg) not in self.items:
            self.items.append((sev, msg))

    def error(self, msg):
        self._add("ERROR", msg)

    def warn(self, msg):
        self._add("WARN", msg)

    def info(self, msg):
        self.items.append(("INFO", msg))

    @property
    def n_errors(self):
        return sum(1 for s, _ in self.items if s == "ERROR")


# Every default that is a length depends on the drawing's unit, and so does how wire and
# covering is bought. Keep them together so an inch drawing never inherits a millimetre default.
unit_conventions = {
    "mm": dict(tolerance=[{"upto": 300, "tol": 5}, {"upto": 1000, "tol": 10}, {"upto": None, "tol": "1%"}],
               round_to=5, loopback_length=100, label_distance=50, label_limit=300, stand_in_length=300,
               purchase_unit="m", lengths_per_purchase_unit=1000),
    "in": dict(tolerance=[{"upto": 12, "tol": 0.25}, {"upto": 40, "tol": 0.5}, {"upto": None, "tol": "1%"}],
               round_to=0.25, loopback_length=4, label_distance=2, label_limit=12, stand_in_length=12,
               purchase_unit="ft", lengths_per_purchase_unit=12),
}


def conventions(drawing: dict) -> dict:
    """The unit conventions for a drawing; an unknown unit falls back to mm and is reported by check()."""
    return unit_conventions.get(drawing.get("units", "mm"), unit_conventions["mm"])


def parse_end(s):
    """'P1:3' -> ('P1', '3'); 'SP1' -> ('SP1', '1')."""
    s = str(s)
    if ":" in s:
        c, p = s.split(":", 1)
        return c.strip(), p.strip()
    return s.strip(), "1"


# YAML 1.1 reads yes/no/on/off as booleans, which turns a relay contact "NO" or a
# signal "OFF" into false. Harness sources follow YAML 1.2 here: only true/false are booleans.
class HarnessLoader(yaml.SafeLoader):
    """A safe YAML loader whose only boolean words are true and false."""


HarnessLoader.yaml_implicit_resolvers = {
    first_character: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first_character, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
HarnessLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))


def load(path):
    with open(path) as f:
        d = yaml.load(f, Loader=HarnessLoader)
    # A section left empty ("items:") loads as None; treat it as absent.
    for section, empty in (("drawing", {}), ("connectors", {}), ("wires", []), ("layout", {}), ("items", []), ("cables", {})):
        if d.get(section) is None:
            d[section] = empty
    return d


def tol_for(dr, length):
    if length is None:
        return None
    for row in dr.get("tolerance", conventions(dr)["tolerance"]):
        if row.get("upto") is None or length <= row["upto"]:
            t = row["tol"]
            if isinstance(t, str) and t.endswith("%"):
                v = length * float(t[:-1]) / 100.0
                return round(v) if v >= 5 else round(v, 1)
            return t
    return 0


def fmt_len(v):
    if v is None:
        return "TBD"
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def pins_of(c):
    if "pins" in c:
        return [str(p) for p in c["pins"]]
    n = c.get("pincount") or len(c.get("pinlabels", [])) or 1
    return [str(i) for i in range(1, n + 1)]


def pinlabel(c, pin):
    pins = pins_of(c)
    labels = c.get("pinlabels") or []
    if isinstance(labels, dict):
        return str(labels.get(pin, labels.get(int(pin) if pin.isdigit() else pin, "")) or "")
    try:
        i = pins.index(pin)
        return str(labels[i]) if i < len(labels) and labels[i] is not None else ""
    except ValueError:
        return ""


# ----------------------------------------------------------------------------
# Layout tree and lengths
# ----------------------------------------------------------------------------

def build_tree(d, E):
    lay = d["layout"]
    segs = lay.get("segments", [])
    adj = defaultdict(list)
    seglen = {}
    for s in segs:
        a, b, L = (s[0], s[1], s[2]) if isinstance(s, list) else (s["from"], s["to"], s["length"])
        adj[a].append(b)
        adj[b].append(a)
        seglen[frozenset((a, b))] = None if L in (None, "TBD") else float(L)
    nodes = set(adj)
    root = lay.get("root") or (next(iter(d["connectors"])) if d["connectors"] else None)
    if root not in nodes:
        E.error(f"layout.root '{root}' is not on any segment")
        return None
    parent, order, seen = {root: None}, [root], {root}
    i = 0
    while i < len(order):
        n = order[i]; i += 1
        for m in adj[n]:
            if m in seen:
                if parent[n] != m:
                    E.error(f"layout has a loop through {'-'.join(sorted((n, m)))}; a harness layout must be a tree")
                continue
            seen.add(m); parent[m] = n; order.append(m)
    for n in nodes - seen:
        E.error(f"layout node {n} is not connected to root {root}")
    if len(segs) != len(seen) - 1 and not any(s == "ERROR" for s, _ in E.items):
        E.error("layout segment count does not match a tree (duplicate segments?)")
    children = defaultdict(list)
    for n in order[1:]:
        children[parent[n]].append(n)
    depth = {root: 0.0}
    for n in order[1:]:
        L, dp = seglen[frozenset((n, parent[n]))], depth[parent[n]]
        depth[n] = None if L is None or dp is None else dp + L
    return dict(root=root, parent=parent, children=children, seglen=seglen, depth=depth, order=order, nodes=seen,
                stand_in_length=conventions(d["drawing"])["stand_in_length"])


def path(T, a, b):
    """Segment list between nodes a and b (as list of (x,y) node pairs)."""
    pa, x = [], a
    while x is not None:
        pa.append(x); x = T["parent"][x]
    pb, x = [], b
    while x is not None:
        pb.append(x); x = T["parent"][x]
    sa = set(pa)
    lca = next(n for n in pb if n in sa)
    up = pa[:pa.index(lca) + 1]
    down = pb[:pb.index(lca)][::-1]
    nodes = up + down
    return list(zip(nodes, nodes[1:]))


def compute_lengths(d, T, E):
    dr = d["drawing"]
    rnd = float(dr.get("round_to", conventions(dr)["round_to"]))
    extra = float(dr.get("extra_per_wire", 0))
    seg_wires = defaultdict(list)
    for w in d["wires"]:
        (ca, _), (cb, _) = parse_end(w["from"]), parse_end(w["to"])
        if T is None or ca not in T["nodes"] or cb not in T["nodes"]:
            w["_len"] = None
            continue
        if "length" in w:
            w["_len"] = float(w["length"]); w["_path"] = path(T, ca, cb)
        elif any(T["seglen"][frozenset(s)] is None for s in path(T, ca, cb)):
            w["_len"] = None; w["_path"] = path(T, ca, cb)
        else:
            p = path(T, ca, cb)
            L = sum(T["seglen"][frozenset(s)] for s in p)
            if not p:
                L = float(dr.get("loopback_length", conventions(dr)["loopback_length"]))
            L += extra
            L += float(d["connectors"].get(ca, {}).get("wire_allowance", 0))
            L += float(d["connectors"].get(cb, {}).get("wire_allowance", 0))
            w["_len"] = math.ceil(L / rnd) * rnd
            w["_path"] = p
        for s in w["_path"]:
            seg_wires[frozenset(s)].append(w)
    return seg_wires


# ----------------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------------

def is_number(value) -> bool:
    """True for an int or float read from YAML; a bool is not a number here."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def segment_ends(segment) -> tuple:
    """A layout segment's two nodes, from either its list or its mapping form."""
    return (segment[0], segment[1]) if isinstance(segment, list) else (segment.get("from"), segment.get("to"))


# Reject each value the rest of the generator cannot compute with, and remove it from the
# source so that everything downstream can trust what is left. Every rejection is an ERROR,
# so a package built from what is left is marked not for release.
def validate_source(d: dict, findings: Err) -> None:
    """Report and remove values in the source that are the wrong kind of thing."""
    validate_drawing_numbers(d["drawing"], findings)
    validate_connectors(d["connectors"], findings)
    validate_wires(d, findings)
    validate_layout(d["layout"], findings)


# Drawing-wide lengths fall back to the unit's default when rejected.
def validate_drawing_numbers(drawing: dict, findings: Err) -> None:
    """Check the units and the drawing-wide lengths."""
    units = drawing.get("units", "mm")
    if units not in unit_conventions:
        findings.error(f"drawing.units '{units}' is not one of {', '.join(unit_conventions)}; lengths were read as mm")
    if "round_to" in drawing and not (is_number(drawing["round_to"]) and drawing["round_to"] > 0):
        findings.error(f"drawing.round_to must be a number greater than 0, not '{drawing.pop('round_to')}'")
    for key in ("extra_per_wire", "loopback_length"):
        if key in drawing and not is_number(drawing[key]):
            findings.error(f"drawing.{key} must be a number, not '{drawing.pop(key)}'")
    tolerance_rows = drawing.get("tolerance")
    if tolerance_rows and all(row.get("upto") is not None for row in tolerance_rows):
        largest = max(row["upto"] for row in tolerance_rows)
        findings.error(f"drawing.tolerance has no row with upto: null; lengths over {fmt_len(largest)} have no tolerance")


def validate_connectors(connectors: dict, findings: Err) -> None:
    """Check each connector's wire allowance."""
    for designator, connector in connectors.items():
        if "wire_allowance" in connector and not is_number(connector["wire_allowance"]):
            findings.error(f"{designator}: wire_allowance must be a number, not '{connector.pop('wire_allowance')}'")


# Give every wire an id first, so each later finding can name the wire it is about. A wire
# without both ends cannot be routed, cut or tabled, so it is reported and dropped.
def validate_wires(d: dict, findings: Err) -> None:
    """Name every wire, then check its ends, gauge and length override."""
    for position, wire in enumerate(d["wires"], 1):
        if not wire.get("id"):
            wire["id"] = f"W{position}"
            findings.info(f"wire #{position} has no id; using {wire['id']}")
    complete_wires = []
    for wire in d["wires"]:
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
    d["wires"] = complete_wires


# A segment with an unusable length is kept with its length TBD, so the layout stays whole.
# A covering keeps only the segments the layout has.
def validate_layout(layout: dict, findings: Err) -> None:
    """Check segment lengths and the segments each covering names."""
    segments = layout.get("segments") or []
    for index, segment in enumerate(segments):
        length = segment[2] if isinstance(segment, list) and len(segment) > 2 else (segment.get("length") if isinstance(segment, dict) else None)
        if length is None or length == "TBD" or (is_number(length) and length >= 0):
            continue
        start, end = segment_ends(segment)
        if is_number(length):
            findings.error(f"layout segment {start}-{end}: length {fmt_len(length)} is negative")
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
            ends = covered.split("-") if isinstance(covered, str) else list(covered)
            name = covered if isinstance(covered, str) else "-".join(map(str, covered))
            if frozenset(ends) in declared:
                kept.append(covered)
            else:
                findings.error(f"covering {covering.get('item', '?')}: segment {name} is not in layout.segments")
        covering["segments"] = kept


def check(d, T, E):
    C = d["connectors"]
    ids = [w.get("id") for w in d["wires"]]
    for i in {x for x in ids if ids.count(x) > 1}:
        E.error(f"duplicate wire id {i}")
    use = defaultdict(list)
    for w in d["wires"]:
        for end in ("from", "to"):
            c, p = parse_end(w[end])
            if c not in C:
                E.error(f"{w['id']}: {end} connector '{c}' is not defined"); continue
            pin_count = len(pins_of(C[c]))
            if ":" not in str(w[end]) and pin_count > 1 and C[c].get("type", "").lower() != "splice":
                E.error(f"{w['id']}: {end} '{w[end]}' names no pin, and {c} has {pin_count}")
            if p not in pins_of(C[c]):
                E.error(f"{w['id']}: {c} has no pin '{p}' (pins {pins_of(C[c])[0]}..{pins_of(C[c])[-1]})")
            use[(c, p)].append(w["id"])
            if T and c not in T["nodes"]:
                E.error(f"{w['id']}: connector {c} is not placed in layout.segments")
            lbl = pinlabel(C[c], p)
            sig = w.get("signal")
            if sig and lbl and lbl != sig and not w.get("signal_differs_ok"):
                E.warn(f"{w['id']}: signal '{sig}' but {c}:{p} is labelled '{lbl}'")
            rng = C[c].get("awg")
            g = str(w.get("gauge", ""))
            m = re.match(r"\s*(\d+)\s*AWG", g, re.I)
            if rng and m and not (min(rng) <= int(m.group(1)) <= max(rng)):
                E.error(f"{w['id']}: {g} outside {c} contact range {min(rng)}-{max(rng)} AWG")
            elif rng and not m and g.strip() and g.strip().upper() != "TBD":
                E.warn(f"{w['id']}: gauge '{g}' is not in AWG, so it was not checked against {c}'s {min(rng)}-{max(rng)} AWG range")
        if parse_end(w["from"])[0] == parse_end(w["to"])[0]:
            E.info(f"{w['id']}: loopback on {parse_end(w['from'])[0]}")
    for (c, p), ws in use.items():
        if len(ws) > 1 and C.get(c, {}).get("type", "").lower() != "splice" and p not in [str(x) for x in C[c].get("double_crimp", [])]:
            E.error(f"{c}:{p} has {len(ws)} wires ({', '.join(ws)}); use a splice or list the pin in double_crimp")
    for c, cd in C.items():
        if cd.get("type", "").lower() == "splice":
            n = sum(len(ws) for (cc, _), ws in use.items() if cc == c)
            if n < 3:
                E.warn(f"splice {c} joins {n} wires; a splice normally joins 3 or more")
            continue
        unused = [p for p in pins_of(cd) if (c, p) not in use]
        labelled = [p for p in unused if pinlabel(cd, p) and pinlabel(cd, p).upper() not in ("NC", "N/C", "")]
        if labelled:
            E.warn(f"{c}: labelled pins not wired: {', '.join(f'{p}({pinlabel(cd, p)})' for p in labelled)}")
        if unused and cd.get("sealed"):
            E.info(f"{c}: {len(unused)} empty cavities need sealing plugs")
        if T and c not in T["nodes"] and not any(k[0] == c for k in use):
            E.warn(f"connector {c} is defined but unused")
    # twists
    tw = defaultdict(list)
    for w in d["wires"]:
        if w.get("twist"):
            tw[w["twist"]].append(w)
    for t, ws in tw.items():
        if len(ws) < 2:
            E.error(f"twist {t} has only one wire")
        elif len({frozenset((parse_end(w['from'])[0], parse_end(w['to'])[0])) for w in ws}) > 1:
            E.warn(f"twist {t}: wires go to different connectors; twist only over the shared segments")
    # cables
    for cid, cab in d["cables"].items():
        ws = [w for w in d["wires"] if w.get("cable") == cid]
        if not ws:
            E.warn(f"cable {cid} has no wires")
        if cab.get("conductors") and len(ws) > cab["conductors"]:
            E.error(f"cable {cid}: {len(ws)} wires assigned, only {cab['conductors']} conductors")
    # layout
    if T:
        tbd = [ "-".join(sorted(s)) for s, L in T["seglen"].items() if L is None]
        if tbd:
            E.info(f"{len(tbd)} segment length(s) TBD ({', '.join(tbd)}); cut lengths through them are TBD")
        segs_used = set()
        for w in d["wires"]:
            for s in w.get("_path", []):
                segs_used.add(frozenset(s))
        for s in T["seglen"]:
            if s not in segs_used:
                E.warn(f"segment {'-'.join(sorted(s))} carries no wires")
        for n in T["order"]:
            if n not in C and not T["children"].get(n) and n != T["root"]:
                E.warn(f"layout leaf {n} is not a connector")
    if T:
        check_coverings_and_labels(d, T, E)
    # netlist
    nets_built = build_nets(d)
    exp = d.get("expect", {}).get("nets")
    if exp:
        compare_nets(nets_built, exp, d, E)
    return nets_built


# Coverings and labels point at items and layout nodes by name; check that each name exists,
# that every label sits where the standard and its own segment allow, and that an item
# counted per label is bought in the number the labels use.
def check_coverings_and_labels(d: dict, tree: dict, findings: Err) -> None:
    """Report coverings and labels that name things the source lacks or sit where they cannot."""
    item_ids = {item.get("id") for item in d["items"]}
    layout = d["layout"]
    units = d["drawing"].get("units", "mm")
    label_limit = conventions(d["drawing"])["label_limit"]
    for covering in layout.get("coverings") or []:
        if covering.get("item") not in item_ids:
            findings.error(f"covering {covering.get('item')}: item {covering.get('item')} is not in items")
    labels = layout.get("labels") or []
    for label in labels:
        name, node = label.get("text", label.get("at")), label.get("at")
        if label.get("item") and label["item"] not in item_ids:
            findings.error(f"label {name}: item {label['item']} is not in items")
        if node not in tree["nodes"]:
            findings.error(f"label {name}: at {node}, which is not a layout node")
            continue
        distance = label.get("distance", conventions(d["drawing"])["label_distance"])
        if distance > label_limit:
            findings.warn(f"label {name}: {fmt_len(distance)} {units} from {node} exceeds the {fmt_len(label_limit)} {units} limit "
                          "of IPC/WHMA-A-620 §12.4")
        neighbour = tree["parent"].get(node) if node != tree["root"] else next(iter(tree["children"][node]), None)
        segment_length = tree["seglen"].get(frozenset((node, neighbour))) if neighbour else None
        if segment_length is not None and distance > segment_length:
            findings.error(f"label {name}: {fmt_len(distance)} {units} from {node} is beyond the {fmt_len(segment_length)} {units} "
                           f"segment {'-'.join(sorted((node, neighbour)))}")
    for item in d["items"]:
        users = [label for label in labels if label.get("item") == item.get("id")]
        if users and is_number(item.get("qty")) and item["qty"] != len(users):
            findings.error(f"item {item['id']}: qty {fmt_len(item['qty'])} but {len(users)} labels use it")


def build_nets(d):
    par = {}

    def f(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x

    def u(a, b):
        par[f(a)] = f(b)

    C = d["connectors"]
    for w in d["wires"]:
        a, b = parse_end(w.get("from", "?")), parse_end(w.get("to", "?"))
        u(a, b)
    for c, cd in C.items():
        if cd.get("type", "").lower() == "splice":
            ps = [k for k in list(par) if k[0] == c]
            for p in ps[1:]:
                u(ps[0], p)
        for lp in cd.get("loops", []):
            u((c, str(lp[0])), (c, str(lp[1])))
    groups = defaultdict(set)
    for x in list(par):
        if C.get(x[0], {}).get("type", "").lower() != "splice":
            groups[f(x)].add(x)
    return [g for g in groups.values() if len(g) > 1]


def compare_nets(built, exp, d, E):
    where = {}
    for i, g in enumerate(built):
        for x in g:
            where[x] = i
    claimed = {}
    for name, members in exp.items():
        mem = [parse_end(m) for m in members]
        ids = {where.get(m) for m in mem}
        if None in ids:
            miss = [f"{c}:{p}" for c, p in mem if where.get((c, p)) is None]
            E.error(f"net {name}: not wired at {', '.join(miss)}")
        ids.discard(None)
        if len(ids) > 1:
            E.error(f"net {name}: split into {len(ids)} pieces (open between "
                    + " | ".join(",".join(sorted(f'{c}:{p}' for c, p in built[i])) for i in ids) + ")")
        for i in ids:
            if i in claimed and claimed[i] != name:
                E.error(f"SHORT: nets {claimed[i]} and {name} are connected")
            claimed[i] = name
            extra = {f"{c}:{p}" for c, p in built[i]} - {f"{c}:{p}" for c, p in mem}
            if extra:
                E.error(f"net {name}: unexpected members {', '.join(sorted(extra))}")
    for i, g in enumerate(built):
        if i not in claimed:
            E.error(f"wired connection not in expected netlist: {', '.join(sorted(f'{c}:{p}' for c, p in g))}")


# ----------------------------------------------------------------------------
# BOM / find numbers
# ----------------------------------------------------------------------------

def build_bom(d, T):
    C = d["connectors"]
    bom = OrderedDict()  # key -> dict

    def add(key, desc, pn="", mfr="", qty=0, unit="EA", refs=None, ar=False):
        """Add qty to a BOM line; a qty of None is a length still TBD, which makes the whole line TBD."""
        e = bom.setdefault(key, dict(desc=desc, pn=pn, mfr=mfr, qty=0, unit=unit, refs=[], ar=ar, tbd=False))
        if qty is None:
            e["tbd"] = True
        else:
            e["qty"] += qty
        if refs:
            e["refs"] += refs
        return e

    # one contact per pin used: wires double-crimped in a pin share its contact
    used = defaultdict(set)
    for w in d["wires"]:
        for end in ("from", "to"):
            c, p = parse_end(w[end])
            used[c].add(p)
    for c, cd in C.items():
        if cd.get("type", "").lower() == "splice":
            add(("spl", cd.get("pn", "splice")), cd.get("desc", "Splice"), cd.get("pn", ""), cd.get("mpn_mfr", cd.get("manufacturer", "")), 1, refs=[c])
            continue
        desc = cd.get("desc") or " ".join(str(x) for x in [cd.get("type", "Connector"), cd.get("subtype", ""), f"{len(pins_of(cd))}P"] if x)
        add(("con", cd.get("pn") or desc), desc, cd.get("pn", ""), cd.get("manufacturer", ""), 1, refs=[c])
        ct = cd.get("contact")
        if ct:
            spare = int(ct.get("spare", 0))
            add(("ctc", ct.get("pn", ct.get("desc"))), ct.get("desc", "Contact"), ct.get("pn", ""), ct.get("manufacturer", ""), len(used[c]) + spare, refs=[c])
        for acc in cd.get("accessories", []):
            add(("acc", acc.get("pn", acc.get("desc"))), acc.get("desc", ""), acc.get("pn", ""), acc.get("manufacturer", ""), acc.get("qty", 1), refs=[c])
    drawing_units = conventions(d["drawing"])
    purchase_unit, per_purchase_unit = drawing_units["purchase_unit"], drawing_units["lengths_per_purchase_unit"]

    def purchased(length):
        """A drawing length in the unit it is bought in; None (TBD) stays None."""
        return None if length is None else length / per_purchase_unit

    for cid, cab in d["cables"].items():
        cable_lengths = [w.get("_len") for w in d["wires"] if w.get("cable") == cid]
        longest = None if None in cable_lengths else max(cable_lengths or [0])
        add(("cab", cab.get("pn", cid)), cab.get("desc", "Cable"), cab.get("pn", ""), cab.get("manufacturer", ""),
            purchased(longest), purchase_unit, [cid], ar=True)
    for w in d["wires"]:
        if w.get("cable"):
            continue
        g, col = str(w.get("gauge", "")), w.get("color", "")
        wire_type = w.get("type", d["drawing"].get("wire_type", "Hook-up wire"))
        pn = w.get("pn") or ""
        add(("wir", wire_type, g, col, pn), ", ".join(x for x in (wire_type, g, col) if x), pn, w.get("manufacturer", ""),
            purchased(w.get("_len")), purchase_unit, [w["id"]], ar=True)
    lay = d["layout"]
    for it in d["items"]:
        iid = it.get("id") or it.get("pn") or it["desc"]
        q = it.get("qty")
        ar = q in (None, "AR")
        unit = it.get("unit", "EA")
        refs = list(it.get("refs", []))
        covs = [cv for cv in lay.get("coverings", []) if cv.get("item") == iid]
        labs = [lb for lb in lay.get("labels", []) if lb.get("item") == iid]
        if ar and covs:  # length of covered segments
            covered = []
            for cv in covs:
                for s in cv["segments"]:
                    a, b = s.split("-") if isinstance(s, str) else s
                    covered.append(T["seglen"].get(frozenset((a, b))))
                refs += [s if isinstance(s, str) else "-".join(s) for s in cv["segments"]]
            q, unit = purchased(None if None in covered else sum(covered)), purchase_unit
        elif q is None and labs:
            q, ar = len(labs), False
            refs += [lb["at"] for lb in labs]
        add(("itm", iid), it["desc"], it.get("pn", ""), it.get("manufacturer", ""),
            q if isinstance(q, (int, float)) or (ar and covs) else 0, unit, refs, ar=ar)
    rows = []
    for i, (k, e) in enumerate(bom.items(), 1):
        e["find"] = i
        e["key"] = k
        rows.append(e)
    return rows


# The QTY cell on the BOM sheet: "AR" lines show the computed length in brackets, and a
# length that runs through a TBD segment shows TBD rather than a total that leaves it out.
def bom_sheet_quantity(entry: dict) -> str:
    """The text of a BOM line's QTY cell on the drawing."""
    if entry["ar"]:
        if entry["tbd"]:
            return "AR (TBD)"
        return f"AR ({entry['qty']:.2f})" if entry["qty"] else "AR"
    return "TBD" if entry["tbd"] else fmt_len(round(entry["qty"], 3))


# The qty column of bom.csv: a number purchasing can use, or a word when there is none yet.
def bom_csv_quantity(entry: dict) -> str:
    """The text of a BOM line's qty in bom.csv."""
    if entry["tbd"]:
        return "TBD"
    if entry["ar"] and not entry["qty"]:
        return "AR"
    return fmt_len(round(entry["qty"], 3))


def find_no(bom, kind, ref):
    return [e["find"] for e in bom if e["key"][0] == kind and ref in e["refs"]]


# ----------------------------------------------------------------------------
# SVG helpers
# ----------------------------------------------------------------------------

W, H = 1600, 1131  # A3 landscape proportions; 1 unit ~ 0.2625 mm on A3
FONT = "Arial, Helvetica, sans-serif"
INK = "#111"


# Advance widths of Helvetica and Helvetica-Bold (Adobe AFM, 1/1000 em) for printable ASCII.
# Arial, which the sheets name first, shares these metrics.
helvetica_widths = dict(zip(
    [chr(code) for code in range(32, 127)],
    [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
     556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778,
     722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278,
     278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
     556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]))
helvetica_bold_widths = dict(zip(
    [chr(code) for code in range(32, 127)],
    [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
     556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778,
     722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333,
     278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
     611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]))
# The few non-ASCII characters the sheets use; anything else is measured as a full em so
# that an unknown glyph errs toward too much room.
symbol_widths = {"–": 556, "—": 1000, "±": 584, "≤": 549, "≥": 549, "°": 400, "×": 584, "µ": 556}


def text_width(content: str, size: float, bold: bool) -> float:
    """The rendered width of a line of sheet text at a font size."""
    widths = helvetica_bold_widths if bold else helvetica_widths
    return sum(widths.get(character, symbol_widths.get(character, 1000)) for character in content) * size / 1000


# Break text into lines no wider than width, at spaces where it can and inside a word only
# when the word alone is wider than the line. Nothing is dropped.
def wrap_to_width(content: str, width: float, size: float, bold: bool) -> list[str]:
    """Lines of content that each fit in width at the given font."""
    lines = []
    current = ""
    for word in content.split():
        candidate = f"{current} {word}" if current else word
        if text_width(candidate, size, bold) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = ""
        for character in word:
            if current and text_width(current + character, size, bold) > width:
                lines.append(current)
                current = ""
            current += character
    return lines + [current] if current or not lines else lines


def esc(s):
    return html.escape(str(s), quote=True)


def text(x, y, s, size=11, anchor="start", weight="normal", fill=INK, extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
            f'text-anchor="{anchor}" font-weight="{weight}" fill="{fill}" {extra}>{esc(s)}</text>')


def line(x1, y1, x2, y2, w=1, col=INK, extra=""):
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col}" stroke-width="{w}" {extra}/>'


def rect(x, y, w, h, fill="none", stroke=INK, sw=1, extra=""):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" {extra}/>'


def arrowhead(x, y, ang):
    a1, a2 = ang + math.radians(160), ang - math.radians(160)
    return (f'<polygon points="{x:.1f},{y:.1f} {x + 9 * math.cos(a1):.1f},{y + 9 * math.sin(a1):.1f} '
            f'{x + 9 * math.cos(a2):.1f},{y + 9 * math.sin(a2):.1f}" fill="{INK}"/>')


def hdim(x1, x2, y, label, ext_from=None):
    """Horizontal dimension with extension lines from ext_from=(y1,y2)."""
    out = []
    if ext_from:
        for x, yy in ((x1, ext_from[0]), (x2, ext_from[1])):
            if yy is not None:
                out.append(line(x, yy, x, y + (4 if y > yy else -4), 0.6, "#555"))
    out.append(line(x1, y, x2, y, 0.8))
    out.append(arrowhead(x1, y, math.pi)); out.append(arrowhead(x2, y, 0))
    tw = len(label) * 6.2 + 8
    xm = (x1 + x2) / 2
    if x2 - x1 > tw + 20:
        out.append(rect(xm - tw / 2, y - 7, tw, 14, fill="white", stroke="none"))
        out.append(text(xm, y + 4, label, 11, "middle"))
    else:
        out.append(text(xm, y - 5, label, 11, "middle"))
    return "".join(out)


def balloon(x, y, n, tx, ty, qty=None, r=11):
    out = [line(x, y, tx, ty, 0.7),
           arrowhead(tx, ty, math.atan2(ty - y, tx - x)),
           f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="white" stroke="{INK}" stroke-width="1"/>',
           text(x, y + 4, n, 11, "middle")]
    if qty:
        out.append(text(x + r + 3, y + 4, qty, 10))
    return "".join(out)


def balloons(x, y, nums, tx, ty, qtys=None):
    out = []
    for i, n in enumerate(nums):
        yy = y + i * 23
        q = (qtys or {}).get(n)
        if i == 0:
            out.append(balloon(x, yy, n, tx, ty, q))
        else:
            out.append(f'<circle cx="{x:.1f}" cy="{yy:.1f}" r="11" fill="white" stroke="{INK}"/>' + text(x, yy + 4, n, 11, "middle"))
            if q:
                out.append(text(x + 14, yy + 4, q, 10))
    return "".join(out)


cell_padding = 3


def table(x, y, cols, rows, title=None, size=9.5, rowh=15, max_h=None):
    """cols: [(header, width, align)]. Returns (svg, height, rows_used).

    Text that is wider than its cell wraps onto more lines and the row grows to hold them."""
    out = []
    tw = sum(c[1] for c in cols)
    line_pitch = round(size * 1.2, 1)

    def wrapped_row(cells, cell_size, bold):
        """Each cell's lines and the height of a row that holds the tallest."""
        lines = [wrap_to_width(str(v), w_ - 2 * cell_padding, cell_size, bold) for (_, w_, _), v in zip(cols, cells)]
        return lines, rowh + line_pitch * (max(len(cell) for cell in lines) - 1)

    def cell_text(cx, cy, w_, a, lines, cell_size, weight):
        """The lines of one cell, the first on the row's usual baseline."""
        tx = cx + cell_padding if a == "l" else cx + w_ / 2
        return "".join(text(tx, cy + rowh - 4 + k * line_pitch, ln, cell_size, "start" if a == "l" else "middle", weight)
                       for k, ln in enumerate(lines))

    yy = y
    if title:
        title_lines = wrap_to_width(title, tw - 2 * cell_padding, size + 1, True)
        title_h = rowh + 2 + line_pitch * (len(title_lines) - 1)
        out.append(rect(x, yy, tw, title_h, fill="#e8e8e8"))
        out.append(cell_text(x, yy + 2, tw, "c", title_lines, size + 1, "bold"))
        yy += title_h
    header_lines, header_h = wrapped_row([h_ for h_, _, _ in cols], size, True)
    out.append(rect(x, yy, tw, header_h, fill="#f3f3f3"))
    cx = x
    for (h_, w_, a), lines in zip(cols, header_lines):
        out.append(rect(cx, yy, w_, header_h))
        out.append(cell_text(cx, yy, w_, a, lines, size, "bold"))
        cx += w_
    yy += header_h
    used = 0
    for r in rows:
        lines_per_cell, row_h = wrapped_row(r, size, False)
        if max_h and yy + row_h > y + max_h:
            break
        cx = x
        for (h_, w_, a), lines in zip(cols, lines_per_cell):
            out.append(rect(cx, yy, w_, row_h, sw=0.6))
            out.append(cell_text(cx, yy, w_, a, lines, size, "normal"))
            cx += w_
        yy += row_h
        used += 1
    return "".join(out), yy - y, used


release_mark_box = (40, 38, 640, 76)  # x0, y0, x1, y1, inside the border at top left


# A package that fails its checks must not pass for a releasable drawing, so every sheet
# of it carries this mark where a reader looks first.
def release_mark(check_errors: int) -> str:
    """The NOT FOR RELEASE mark for a package with check errors."""
    x0, y0, x1, y1 = release_mark_box
    plural = "S" if check_errors != 1 else ""
    return (rect(x0, y0, x1 - x0, y1 - y0, fill="white", stroke="#c00000", sw=2.5)
            + text((x0 + x1) / 2, y0 + 24, f"NOT FOR RELEASE: {check_errors} CHECK ERROR{plural}, SEE CHECKS REPORT",
                   15, "middle", "bold", fill="#c00000"))


def frame(d, sheet, nsheets, sheet_title, check_errors):
    """The border, zones, title and revision blocks of a sheet, and the boxes the blocks take up."""
    dr = d["drawing"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'viewBox="0 0 {W} {H}" width="420mm" height="297mm">',
           rect(0, 0, W, H, fill="white", stroke="none"),
           rect(20, 20, W - 40, H - 40, sw=2)]
    # zone grid
    for i in range(1, 8):
        x = 20 + i * (W - 40) / 8
        out += [line(x, 20, x, 30), line(x, H - 30, x, H - 20)]
    for i in range(8):
        out.append(text(20 + (i + .5) * (W - 40) / 8, 29, 8 - i, 8, "middle"))
    for i, L in enumerate("FEDCBA"):
        y = 20 + (i + .5) * (H - 40) / 6
        out.append(text(25, y, L, 8, "middle"))
    # title block (bottom right)
    tx, ty, tw_, th = W - 20 - 560, H - 20 - 120, 560, 120
    out.append(rect(tx, ty, tw_, th, fill="white", sw=1.5))
    rows = [
        (tx, ty, 560, 34, "TITLE", dr.get("title", "")),
        (tx, ty + 34, 300, 30, "DWG NO.", dr.get("number", "")),
        (tx + 300, ty + 34, 80, 30, "REV", dr.get("rev", "")),
        (tx + 380, ty + 34, 180, 30, "SHEET", f"{sheet} OF {nsheets}"),
        (tx, ty + 64, 140, 28, "DRAWN", dr.get("drawn_by", "")),
        (tx + 140, ty + 64, 120, 28, "DATE", dr.get("date", "")),
        (tx + 260, ty + 64, 120, 28, "CHECKED", dr.get("checked_by", "")),
        (tx + 380, ty + 64, 180, 28, "SCALE", "NONE (NTS)"),
        (tx, ty + 92, 260, 28, "UNITS", dr.get("units", "mm")),
        (tx + 260, ty + 92, 300, 28, "THIS SHEET", sheet_title),
    ]
    for x, y, w_, h_, lab, val in rows:
        out.append(rect(x, y, w_, h_, sw=0.8))
        out.append(text(x + 4, y + 10, lab, 7.5, fill="#555"))
        out.append(text(x + 8, y + h_ - 7, val, 15 if lab == "TITLE" else 12, weight="bold" if lab in ("TITLE", "DWG NO.", "REV") else "normal"))
    # revision block (top right)
    revs = dr.get("revisions") or [{"rev": dr.get("rev", "A"), "desc": "Initial release", "date": dr.get("date", ""), "by": dr.get("drawn_by", "")}]
    cols = [("REV", 40, "c"), ("DESCRIPTION", 300, "l"), ("DATE", 90, "c"), ("BY", 60, "c")]
    s, revision_h, _ = table(W - 20 - 490, 20, cols, [[r.get("rev", ""), r.get("desc", ""), r.get("date", ""), r.get("by", "")] for r in revs], "REVISIONS")
    out.append(s)
    if check_errors:
        out.append(release_mark(check_errors))
    regions = {"title block": (tx, ty, tx + tw_, ty + th), "revision block": (W - 20 - 490, 20, W - 20, 20 + revision_h),
               "release mark area": release_mark_box}
    return out, regions


# ----------------------------------------------------------------------------
# Sheet 1: harness (formboard) drawing
# ----------------------------------------------------------------------------

def drawn_len(T, s):
    """A segment's length for laying out the sheet: a TBD one draws as the median known."""
    L = T["seglen"][s]
    if L is not None:
        return L
    known = sorted(v for v in T["seglen"].values() if v is not None)
    return known[len(known) // 2] if known else float(T["stand_in_length"])


def layout_xy(d, T, seg_wires, box):
    x0, y0, x1, y1 = box
    ch = T["children"]

    def far(n):
        return max([far(c) + drawn_len(T, frozenset((n, c))) for c in ch[n]] or [0])

    # order children: trunk = farthest-reaching; branches alternate up/down
    order = {}
    for n in T["order"]:
        cs = sorted(ch[n], key=lambda c: far(c) + drawn_len(T, frozenset((n, c))), reverse=True)
        if not cs:
            order[n] = []; continue
        trunk, rest = cs[0], cs[1:]
        up, down = [], []
        for r in rest:
            (up if T.setdefault("_flip", [0])[0] % 2 == 0 else down).append(r)
            T["_flip"][0] += 1
        order[n] = up[::-1] + [trunk] + down
        T.setdefault("trunk", {})[n] = trunk
    leaves = []

    def dfs(n):
        if not order[n]:
            leaves.append(n); return
        for c in order[n]:
            dfs(c)

    dfs(T["root"])
    nl = len(leaves)
    lane = min(170, max(80, (y1 - y0) / max(1, nl)))
    ymid = (y0 + y1) / 2
    ys = {n: ymid + (i - (nl - 1) / 2) * lane for i, n in enumerate(leaves)}

    def sety(n):
        if not order[n]:
            return ys[n]
        for c in order[n]:
            sety(c)
        ys[n] = ys[T["trunk"][n]]
        return ys[n]

    sety(T["root"])
    # x: drawn (not-to-scale) segment lengths
    dd = {T["root"]: 0.0}
    for n in T["order"][1:]:
        dd[n] = dd[T["parent"][n]] + drawn_len(T, frozenset((n, T["parent"][n])))
    maxpath = max(dd.values()) or 1
    k = (x1 - x0) / maxpath
    drawn = {s: min(max(drawn_len(T, s) * k, 110), 420) for s in T["seglen"]}
    xs = {T["root"]: x0}
    for n in T["order"][1:]:
        p = T["parent"][n]
        xs[n] = xs[p] + drawn[frozenset((n, p))]
    span = max(xs.values()) - x0
    if span > (x1 - x0):
        f = (x1 - x0) / span
        xs = {n: x0 + (x - x0) * f for n, x in xs.items()}
    # centre horizontally
    sh = (x1 - max(xs.values())) / 2
    xs = {n: x + max(0, sh) for n, x in xs.items()}
    return xs, ys


def seg_path(px, py, cx, cy):
    if abs(py - cy) < 0.5:
        return f"M{px:.1f},{py:.1f} L{cx:.1f},{cy:.1f}", (px, cx)
    run = cx - px
    bend = min(run * 0.55, max(60, abs(cy - py) * 0.9))
    return (f"M{px:.1f},{py:.1f} C{px + bend * 0.5:.1f},{py:.1f} {px + bend * 0.5:.1f},{cy:.1f} {px + bend:.1f},{cy:.1f} "
            f"L{cx:.1f},{cy:.1f}"), (px + bend, cx)


def balloon_stack_box(x, y, nums, qtys=None):
    """The box a column of balloons drawn by balloons() takes up."""
    widest_quantity = max([text_width(q, 10, False) + 3 for q in (qtys or {}).values()] or [0])
    return (x - 11, y - 11, x + 11 + widest_quantity, y + 23 * (len(nums) - 1) + 11)


def hdim_box(x1, x2, y, label):
    """The box a horizontal dimension drawn by hdim() takes up, its label included."""
    label_w = text_width(label, 11, False) + 8
    xm = (x1 + x2) / 2
    top = y - 7 if x2 - x1 > label_w + 20 else y - 16
    return (min(x1, xm - label_w / 2), top, max(x2, xm + label_w / 2), y + 7)


# Name every part of the drawing that lies outside the sheet border or on top of a block
# the frame or the notes occupy, so a drawing too big for its sheet is reported, never shipped.
def sheet_misfits(placed, regions):
    """For each place a drawn item must not be, the items that are there: one line per place."""
    trespassers = defaultdict(list)
    for what, (x0, y0, x1, y1) in placed:
        if x0 < 20 or y0 < 20 or x1 > W - 20 or y1 > H - 20:
            trespassers["off the sheet"].append(what)
        for region, (rx0, ry0, rx1, ry1) in regions.items():
            if x0 < rx1 and rx0 < x1 and y0 < ry1 and ry0 < y1:
                trespassers[f"on the {region}"].append(what)
    return [f"{place}: {', '.join(dict.fromkeys(whats))}" for place, whats in trespassers.items()]


def sheet_drawing(d, T, seg_wires, bom, nsheets, check_errors):
    """Sheet 1's SVG and the list of what on it does not fit the sheet."""
    dr = d["drawing"]
    C = d["connectors"]
    out, regions = frame(d, 1, nsheets, "HARNESS DRAWING", check_errors)
    placed = []

    def occupy(what, box_):
        placed.append((what, box_))

    nleaf = sum(1 for n in T["order"] if n in C and n != T["root"] and not T["children"].get(n))
    notes_top = H - 20 - 20 - 15 * sum(x.count("\n") + 1 for x in default_notes(d)) - 50
    dims_h = 24 * nleaf + 40
    bottom = min(notes_top, H - 150) - dims_h - 70
    box = (170, 150, W - 230, max(bottom, 420))
    xs, ys = layout_xy(d, T, seg_wires, box)
    root = T["root"]
    # coverings first (under bundle)
    cov_marks = []
    for cv in d["layout"].get("coverings", []):
        segs = [tuple(s.split("-")) if isinstance(s, str) else tuple(s) for s in cv["segments"]]
        for a, b in segs:
            if frozenset((a, b)) not in T["seglen"]:
                continue
            p, c = (a, b) if T["parent"].get(b) == a else (b, a)
            pth, _ = seg_path(xs[p], ys[p], xs[c], ys[c])
            out.append(f'<path d="{pth}" fill="none" stroke="{cv.get("display_color", "#9aa7b8")}" stroke-width="{cv.get("display_width", 16)}" stroke-linecap="butt" opacity="0.55"/>')
        drawn_segs = [(a, b) for a, b in segs if frozenset((a, b)) in T["seglen"]]
        if drawn_segs:
            a, b = drawn_segs[0]
            p, c = (a, b) if T["parent"].get(b) == a else (b, a)
            cov_marks.append((cv, (xs[p] + xs[c]) / 2, ys[c]))
    # bundles
    for n in T["order"][1:]:
        p = T["parent"][n]
        nw = len(seg_wires.get(frozenset((n, p)), []))
        pth, _ = seg_path(xs[p], ys[p], xs[n], ys[n])
        out.append(f'<path d="{pth}" fill="none" stroke="#333" stroke-width="{3 + 1.6 * math.sqrt(max(nw, 1)):.1f}" stroke-linecap="round"/>')
        out.append(f'<path d="{pth}" fill="none" stroke="#9a9a9a" stroke-width="{1 + 1.6 * math.sqrt(max(nw, 1)):.1f}" stroke-linecap="round"/>')
    # segment (chain) dimensions
    for n in T["order"][1:]:
        p = T["parent"][n]
        L = T["seglen"][frozenset((n, p))]
        lab = f"{fmt_len(L)} ±{fmt_len(tol_for(dr, L))}" if L is not None else "TBD"
        dy = -30 if ys[n] < ys[p] else 34
        yd = ys[n] + dy
        if abs(ys[p] - ys[n]) < 0.5:
            out.append(hdim(xs[p], xs[n], yd, lab, (ys[p], ys[n])))
            occupy(f"dimension {p}–{n}", hdim_box(xs[p], xs[n], yd, lab))
        else:  # bent branch: length called out along its run, as on NTS drawings
            _, (rx0, rx1) = seg_path(xs[p], ys[p], xs[n], ys[n])
            tw = len(lab) * 6.2 + 8
            xm = xs[p] + (rx0 - xs[p]) * 0.5 + 8 + tw / 2
            ym = (ys[p] + ys[n]) / 2
            occupy(f"dimension {p}–{n}", (xm - tw / 2, ym - 7, xm + tw / 2, ym + 7))
            out.append(rect(xm - tw / 2, ym - 7, tw, 14, fill="white", stroke="none"))
            out.append(text(xm, ym + 4, lab, 11, "middle"))
    # breakout nodes
    for n in T["order"]:
        if n in C:
            continue
        out.append(f'<circle cx="{xs[n]:.1f}" cy="{ys[n]:.1f}" r="4" fill="white" stroke="{INK}" stroke-width="1.2"/>')
        out.append(text(xs[n] - 6, ys[n] - 10, n, 9, "end", fill="#555"))
        occupy(f"breakout {n}", (xs[n] - 6 - text_width(n, 9, False), ys[n] - 19, xs[n] + 4, ys[n] + 4))
    # connectors
    for c, cd in C.items():
        if c not in xs:
            continue
        x, y = xs[c], ys[c]
        left = (c == root)
        wires_here = [w for w in d["wires"] if parse_end(w["from"])[0] == c or parse_end(w["to"])[0] == c]
        splice = cd.get("type", "").lower() == "splice"
        if splice:
            out.append(f'<rect x="{x - 9:.1f}" y="{y - 7:.1f}" width="18" height="14" fill="#d9d9d9" stroke="{INK}" transform="rotate(45 {x:.1f} {y:.1f})"/>')
            out.append(text(x, y - 16, c, 12, "middle", "bold"))
            occupy(f"splice {c}", (x - 13, y - 28, x + 13, y + 13))
            nums = find_no(bom, "spl", c)
            if nums:
                out.append(balloons(x + 30, y - 45, nums, x + 6, y - 6))
                occupy(f"{c} balloons", balloon_stack_box(x + 30, y - 45, nums))
            continue
        npin = len(pins_of(cd))
        bh = min(110, max(44, 8 + npin * 3.2))
        bw = 64
        fan = 26
        sgn = -1 if left else 1
        bx = x if not left else x - bw
        # wire fan between bundle end and connector body
        k = len(wires_here)
        for i, w in enumerate(wires_here):
            yy = y + (i - (k - 1) / 2) * min(5, (bh - 10) / max(k, 1))
            col = hexcolor(w.get("color"))
            x0_ = x - sgn * fan
            out.append(f'<path d="M{x0_:.1f},{y:.1f} C{x - sgn * fan * .5:.1f},{y:.1f} {x - sgn * fan * .5:.1f},{yy:.1f} {x:.1f},{yy:.1f}" fill="none" stroke="{col}" stroke-width="2"/>')
        out.append(rect(bx, y - bh / 2, bw, bh, fill="#e4e4e4", sw=1.2, extra='rx="3"'))
        mate_x = bx + bw if not left else bx
        out.append(rect(mate_x - (6 if not left else 0), y - bh / 2 + 6, 6, bh - 12, fill="#bdbdbd", sw=0.8))
        # designator, description
        cxm = bx + bw / 2
        out.append(text(cxm, y + bh / 2 + 18, c, 14, "middle", "bold", extra='text-decoration="underline"'))
        sub = cd.get("label") or cd.get("type", "")
        out.append(text(cxm, y + bh / 2 + 32, sub, 9.5, "middle", fill="#333"))
        caption_w = max(text_width(c, 14, True), text_width(sub, 9.5, False))
        occupy(f"connector {c}", (min(bx, cxm - caption_w / 2) - (fan if left else 0), y - bh / 2,
                                  max(bx + bw, cxm + caption_w / 2) + (0 if left else fan), y + bh / 2 + 35))
        # balloons: housing, contacts, accessories
        nums = find_no(bom, "con", c) + find_no(bom, "ctc", c) + find_no(bom, "acc", c)
        qtys = {}
        ct = find_no(bom, "ctc", c)
        if ct:
            pins = {parse_end(w[e])[1] for w in d["wires"] for e in ("from", "to") if parse_end(w[e])[0] == c}
            qtys[ct[0]] = f"{len(pins)}X"  # one contact per pin used, as in the BOM
        bx_ = bx - 40 if left else bx + bw + 40
        out.append(balloons(bx_, y - bh / 2 - 40, nums, bx + (bw * 0.3 if left else bw * 0.7), y - bh / 2, qtys))
        occupy(f"{c} balloons", balloon_stack_box(bx_, y - bh / 2 - 40, nums, qtys))
    # labels / markers
    for lb in d["layout"].get("labels", []):
        c = lb["at"]
        if c not in xs:
            continue
        nb = T["parent"].get(c) if c != root else next(iter(T["children"][root]), None)
        if nb is None:
            continue
        dist = float(lb.get("distance", conventions(dr)["label_distance"]))
        segL = drawn_len(T, frozenset((c, nb)))
        x = xs[c] + (xs[nb] - xs[c]) * min(dist / segL, 0.6)
        x = xs[c] + math.copysign(max(abs(x - xs[c]), 60), xs[nb] - xs[c])
        y = ys[c]
        txt = lb["text"]
        tw = max(46, len(txt) * 6.4 + 10)
        out.append(rect(x - tw / 2, y - 9, tw, 18, fill="white", sw=1))
        out.append(text(x, y + 4, txt, 10, "middle"))
        occupy(f"label {txt}", (x - tw / 2, y - 9, x + tw / 2, y + 9))
        seg_child = c if c != root else nb
        seg_par = T["parent"][seg_child]
        seg_above = ys[seg_child] < ys[seg_par]
        ly = y + 26 if seg_above else y - 26
        out.append(hdim(min(xs[c], x), max(xs[c], x), ly, fmt_len(dist), (y, y + (9 if seg_above else -9))))
        occupy(f"label {txt} dimension", hdim_box(min(xs[c], x), max(xs[c], x), ly, fmt_len(dist)))
        nums = [e["find"] for e in bom if e["key"] == ("itm", lb["item"])] if lb.get("item") else []
        if nums:
            out.append(balloons(x + 30, y + 50, nums, x + 10, y + 9))
            occupy(f"label {txt} balloon", balloon_stack_box(x + 30, y + 50, nums))
    for cv, x, y in cov_marks:
        nums = [e["find"] for e in bom if e["key"] == ("itm", cv.get("item"))]
        if nums:
            out.append(balloons(x + 25, y + 70, nums, x, y + 8, {nums[0]: "AR"}))
            occupy(f"{cv.get('item')} balloon", balloon_stack_box(x + 25, y + 70, nums, {nums[0]: "AR"}))
    # Overall dimensions from the root datum to each leaf connector. The segment dimensions
    # above already fix these lengths, each with its own tolerance, so an overall tolerance
    # would contradict their stack-up: the overall lengths are reference only.
    leaves = [n for n in T["order"] if n in C and n != root and not T["children"].get(n)]
    leaves.sort(key=lambda n: xs[n])
    yb = max(max(ys.values()) + 100, box[3] + 60)
    for i, n in enumerate(leaves):
        L = T["depth"][n]
        lab = f"{fmt_len(L)} REF" if L is not None else "TBD REF"
        out.append(hdim(xs[root], xs[n], yb + i * 24, f"{lab}  ({root}–{n})", (None, None)))
        occupy(f"overall dimension {root}–{n}", hdim_box(xs[root], xs[n], yb + i * 24, f"{lab}  ({root}–{n})"))
        out.append(line(xs[n], ys[n] + 20, xs[n], yb + i * 24 + 4, 0.5, "#777", 'stroke-dasharray="4 3"'))
    if leaves:
        out.append(line(xs[root], ys[root] + 20, xs[root], yb + (len(leaves) - 1) * 24 + 4, 0.5, "#777", 'stroke-dasharray="4 3"'))
    # notes
    notes = default_notes(d)
    lines = []
    for i, nt in enumerate(notes, 1):
        for j, ln in enumerate(nt.split("\n")):
            lines.append((f"{i}.  " if j == 0 else "") + ln)
    ny = H - 20 - 20 - 15 * len(lines)
    out.append(text(40, ny - 40, "DRAWING NOT TO SCALE", 11, fill="#555"))
    out.append(text(40, ny - 8, "NOTES:", 12, weight="bold", extra='text-decoration="underline"'))
    for k, ln in enumerate(lines):
        out.append(text(40, ny + 12 + k * 15, ln, 10.5, extra='xml:space="preserve"'))
    regions["notes"] = (40, ny - 51, 40 + max(text_width(ln, 10.5, False) for ln in lines), H - 20)
    out.append("</svg>")
    return "\n".join(out), sheet_misfits(placed, regions)


def default_notes(d):
    dr = d["drawing"]
    datum = dr.get("datum", "connector rear face")
    tol = dr.get("tolerance", conventions(dr)["tolerance"])
    tols = ", ".join((f"≤{r['upto']}: ±{r['tol']}" if r.get("upto") else f"over: ±{r['tol']}") for r in tol)
    n = [
        f"FABRICATE, INSPECT AND TEST PER IPC/WHMA-A-620, CLASS {dr.get('ipc_class', 2)}.",
        f"ALL DIMENSIONS IN {dr.get('units', 'mm').upper()}. LENGTHS ARE MEASURED FROM {datum.upper()} TO BREAKOUT CENTRE OR TO THE NEXT {datum.upper()}.",
        f"LENGTH TOLERANCES UNLESS OTHERWISE SPECIFIED: {tols}. SEGMENT DIMENSIONS GOVERN; OVERALL DIMENSIONS ARE REFERENCE.",
        "DRAWING NOT TO SCALE. WIRE CUT LENGTHS PER WIRE LIST; CONNECTIONS PER CONNECTOR TABLES AND WIRING DIAGRAM.",
    ]
    if any(w.get("twist") for w in d["wires"]):
        n.append("TWIST INDICATED WIRES PER IPC/WHMA-A-620.")
    if d["layout"].get("labels"):
        n.append("LABELS READ TOWARD THE CONNECTOR; POSITION DIMENSIONED FROM DATUM TO LABEL CENTRE.")
    n.append("CONTINUITY-TEST 100% AGAINST THE WIRE LIST; NO SHORTS BETWEEN NETS.")
    if any(len(s) > 2 and s[2] in (None, "TBD") for s in d["layout"].get("segments", []) if isinstance(s, list)):
        n.append("LENGTHS MARKED TBD ARE NOT YET SET; SEGMENTS SO MARKED ARE DRAWN AT A STAND-IN LENGTH. DO NOT CUT FROM THIS REVISION.")
    n += dr.get("notes", [])
    return [textwrap.fill(x, 150, subsequent_indent="     ") for x in n]


# ----------------------------------------------------------------------------
# Sheets 2+: tables
# ----------------------------------------------------------------------------

def table_sheets(d, bom):
    C = d["connectors"]
    tabs = []
    tabs.append(("BILL OF MATERIALS", [("FIND", 40, "c"), ("QTY", 55, "c"), ("UNIT", 40, "c"), ("PART NUMBER", 150, "l"),
                                       ("DESCRIPTION", 260, "l"), ("MFR", 90, "l"), ("REF", 140, "l")],
                 [[e["find"], bom_sheet_quantity(e),
                   e["unit"], e["pn"], e["desc"], e["mfr"], ", ".join(dict.fromkeys(str(r) for r in e["refs"]))] for e in bom]))
    rows = []
    for w in d["wires"]:
        (ca, pa), (cb, pb) = parse_end(w["from"]), parse_end(w["to"])
        rows.append([w["id"], ca, pa, w.get("signal") or pinlabel(C.get(ca, {}), pa), cb, pb, w.get("gauge", ""), w.get("color", ""),
                     fmt_len(w.get("_len")), w.get("twist") or w.get("cable") or "", w.get("note", "")])
    tabs.append(("WIRE LIST (FROM–TO)", [("WIRE", 50, "c"), ("FROM", 46, "c"), ("PIN", 34, "c"), ("SIGNAL", 110, "l"), ("TO", 46, "c"),
                                         ("PIN", 34, "c"), ("GAUGE", 62, "c"), ("COLOR", 50, "c"), ("CUT LEN", 58, "c"), ("TWIST/CBL", 64, "c"), ("NOTE", 120, "l")], rows))
    for c, cd in C.items():
        if cd.get("type", "").lower() == "splice":
            continue
        r = []
        for p in pins_of(cd):
            ws = [w for w in d["wires"] if parse_end(w["from"]) == (c, p) or parse_end(w["to"]) == (c, p)]
            if not ws:
                r.append([p, pinlabel(cd, p) or "—", "", "", "", "empty" + (" (seal)" if cd.get("sealed") else "")])
            for w in ws:
                other = w["to"] if parse_end(w["from"]) == (c, p) else w["from"]
                r.append([p, pinlabel(cd, p) or w.get("signal", ""), w["id"], w.get("color", ""), w.get("gauge", ""), other])
        title = f"{c} — {cd.get('label') or ''} {cd.get('type', '')} {cd.get('subtype', '')} {cd.get('pn', '')}".strip()
        if cd.get("view"):
            title += f"  [{cd['view']}]"
        tabs.append((title, [("PIN", 34, "c"), ("SIGNAL", 110, "l"), ("WIRE", 50, "c"), ("COLOR", 50, "c"), ("GAUGE", 60, "c"), ("TO", 70, "c")], r))
    # flow tables into columns/sheets
    sheets = []
    area = (40, 150, W - 40, H - 170)
    cur, cx, cy, colw = [], area[0], area[1], 0

    def new_sheet():
        nonlocal cur, cx, cy, colw
        if cur:
            sheets.append(cur)
        cur, cx, cy, colw = [], area[0], area[1], 0

    for title, cols, rows in tabs:
        tw = sum(c[1] for c in cols)
        i = 0
        first = True
        while i < len(rows) or (first and not rows):
            first = False
            if cx + tw > area[2]:
                new_sheet()
            avail = area[3] - cy
            if avail < 80:
                cx += colw + 25; cy = area[1]; colw = 0
                if cx + tw > area[2]:
                    new_sheet()
                avail = area[3] - cy
            s, h, used = table(cx, cy, cols, rows[i:], title + (" (cont.)" if i else ""), max_h=avail)
            cur.append(s)
            colw = max(colw, tw)
            cy += h + 22
            i += used
            if used == 0 and rows[i:]:
                cx += colw + 25; cy = area[1]; colw = 0
                if cx + tw > area[2]:
                    new_sheet()
            if not rows:
                break
    if cur:
        sheets.append(cur)
    return sheets


def finish_table_sheets(d, sheets, first, nsheets, check_errors):
    out = []
    for i, body in enumerate(sheets):
        fr, _ = frame(d, first + i, nsheets, "BOM / WIRE LIST / CONNECTORS", check_errors)
        out.append("\n".join(fr + body + ["</svg>"]))
    return out


# ----------------------------------------------------------------------------
# WireViz wiring diagram
# ----------------------------------------------------------------------------

def wireviz_yaml(d):
    pv = lambda p: int(p) if str(p).isdigit() else p
    C = d["connectors"]
    wv = {"metadata": {"title": d["drawing"].get("title", "")}, "options": {"fontname": "arial"}, "connectors": {}, "cables": {}, "connections": []}
    for c, cd in C.items():
        if cd.get("type", "").lower() == "splice":
            wv["connectors"][c] = {"style": "simple", "type": "Splice", "show_name": True}
            continue
        e = {k: cd[k] for k in ("type", "subtype", "pn", "manufacturer", "mpn", "notes") if k in cd}
        e["pins"] = [pv(p) for p in pins_of(cd)]
        e["pinlabels"] = [pinlabel(cd, p) for p in pins_of(cd)]
        e["hide_disconnected_pins"] = bool(cd.get("hide_unused", False))
        wv["connectors"][c] = e
    groups = OrderedDict()
    for w in d["wires"]:
        (ca, pa), (cb, pb) = parse_end(w["from"]), parse_end(w["to"])
        key = (ca, cb, str(w.get("gauge", "")))
        groups.setdefault(key, []).append((w, pv(pa), pv(pb)))
    for i, ((ca, cb, g), ws) in enumerate(groups.items(), 1):
        name = f"B{i}"
        cab = {"category": "bundle", "wirelabels": [w["id"] for w, _, _ in ws], "show_name": False}
        if all(w.get("color") for w, _, _ in ws):
            cab["colors"] = ["".join(color_parts(w.get("color"))) for w, _, _ in ws]
        else:  # colours not chosen yet: count only, no stand-in colour
            cab["wirecount"] = len(ws)
        if g and re.match(r"\s*\d+(\.\d+)?(\s+\S+)?\s*$", g):  # a number, or number and unit; TBD stays out
            cab["gauge"] = g
        Ls = [w.get("_len") for w, _, _ in ws if w.get("_len")]
        if Ls:
            cab["length"] = round(max(Ls) / 1000, 3)
        wv["cables"][name] = cab
        is_sa = C.get(ca, {}).get("type", "").lower() == "splice"
        is_sb = C.get(cb, {}).get("type", "").lower() == "splice"
        if is_sa or is_sb:  # simple connectors take one wire per connection set
            for j, (w, pa, pb) in enumerate(ws, 1):
                wv["connections"].append([ca if is_sa else {ca: [pa]}, {name: [j]}, cb if is_sb else {cb: [pb]}])
        else:
            wv["connections"].append([{ca: [pa for _, pa, _ in ws]}, {name: list(range(1, len(ws) + 1))}, {cb: [pb for _, _, pb in ws]}])
    return wv


def run_wireviz(d, outdir, base):
    if not shutil.which("wireviz") or not shutil.which("dot"):
        return None, "wireviz or graphviz (dot) not on PATH; wiring diagram sheet skipped"
    wv = wireviz_yaml(d)
    p = os.path.join(outdir, f"{base}.wireviz.yaml")
    with open(p, "w") as f:
        yaml.safe_dump(wv, f, sort_keys=False)
    r = subprocess.run(["wireviz", "-f", "sp", "-o", outdir, "-O", f"{base}.wiring", p], capture_output=True, text=True)
    svg = os.path.join(outdir, f"{base}.wiring.svg")
    if r.returncode or not os.path.exists(svg):
        return None, "wireviz failed: " + (r.stderr or r.stdout)[-800:]
    return svg, None


def sheet_wiring(d, svgpath, sheet, nsheets, check_errors):
    fr, _ = frame(d, sheet, nsheets, "WIRING DIAGRAM", check_errors)
    with open(svgpath, "rb") as f:
        raw = f.read()
    data = base64.b64encode(raw).decode()
    m = re.search(rb'viewBox="([\d. -]+)"', raw)
    vw, vh = (float(v) for v in m.group(1).split()[2:]) if m else (1000, 700)
    ax, ay, aw, ah = 40, 150, W - 80, H - 150 - 160
    s = min(aw / vw, ah / vh)
    w_, h_ = vw * s, vh * s
    fr.append(f'<image x="{ax + (aw - w_) / 2:.1f}" y="{ay + (ah - h_) / 2:.1f}" width="{w_:.1f}" height="{h_:.1f}" href="data:image/svg+xml;base64,{data}"/>')
    fr.append("</svg>")
    return "\n".join(fr)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("yaml")
    ap.add_argument("-o", "--outdir")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--no-wireviz", action="store_true")
    a = ap.parse_args()
    d = load(a.yaml)
    base = os.path.splitext(os.path.basename(a.yaml))[0]
    outdir = a.outdir or os.path.join(os.path.dirname(os.path.abspath(a.yaml)), f"{base}-out")
    os.makedirs(outdir, exist_ok=True)
    E = Err()
    validate_source(d, E)
    T = build_tree(d, E)
    seg_wires = compute_lengths(d, T, E)
    check(d, T, E)
    # Whether the drawing fits its sheet is a check too, so lay sheet 1 out before reporting.
    bom = build_bom(d, T) if T else None
    if T:
        _, misfits = sheet_drawing(d, T, seg_wires, bom, 1, 0)
        if misfits:
            E.error("harness drawing does not fit sheet 1: " + "; ".join(misfits)
                    + ". Split the harness into sub-harnesses or shorten its text")
    rep = "\n".join(f"{s:5}  {m}" for s, m in E.items) or "OK     no findings"
    print(rep)
    with open(os.path.join(outdir, f"{base}.checks.txt"), "w") as f:
        f.write(rep + "\n")
    if a.check_only:
        sys.exit(1 if E.n_errors else 0)
    if T is None:
        print("cannot draw: layout is broken"); sys.exit(1)
    # CSVs
    with open(os.path.join(outdir, f"{base}.bom.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["find", "qty", "unit", "pn", "description", "manufacturer", "refs"])
        for e in bom:
            w.writerow([e["find"], bom_csv_quantity(e), e["unit"], e["pn"], e["desc"], e["mfr"], " ".join(map(str, dict.fromkeys(e["refs"])))])
    with open(os.path.join(outdir, f"{base}.wirelist.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["wire", "from", "from_pin", "to", "to_pin", "signal", "gauge", "color", "cut_length", "twist", "cable", "strip_a", "strip_b", "path"])
        for x in d["wires"]:
            (ca, pa), (cb, pb) = parse_end(x["from"]), parse_end(x["to"])
            w.writerow([x["id"], ca, pa, cb, pb, x.get("signal", ""), x.get("gauge", ""), x.get("color", ""), fmt_len(x.get("_len")), x.get("twist", ""),
                        x.get("cable", ""), d["connectors"].get(ca, {}).get("strip", ""), d["connectors"].get(cb, {}).get("strip", ""),
                        " > ".join([s[0] for s in x.get("_path", [])] + ([x["_path"][-1][1]] if x.get("_path") else []))])
    wv_svg, wv_err = (None, "skipped (--no-wireviz)") if a.no_wireviz else run_wireviz(d, outdir, base)
    if wv_err:
        print("NOTE  ", wv_err)
    tsheets = table_sheets(d, bom)
    n = 1 + len(tsheets) + (1 if wv_svg else 0)
    drawing, _ = sheet_drawing(d, T, seg_wires, bom, n, E.n_errors)
    svgs = [drawing] + finish_table_sheets(d, tsheets, 2, n, E.n_errors)
    if wv_svg:
        svgs.append(sheet_wiring(d, wv_svg, n, n, E.n_errors))
    paths = []
    for i, s in enumerate(svgs, 1):
        p = os.path.join(outdir, f"{base}.sheet{i}.svg")
        with open(p, "w") as f:
            f.write(s)
        paths.append(p)
    try:
        import cairosvg
        from pypdf import PdfWriter, PdfReader
        wr = PdfWriter()
        for p in paths:
            pdf = p[:-4] + ".pdf"
            cairosvg.svg2pdf(url=p, write_to=pdf)
            for pg in PdfReader(pdf).pages:
                wr.add_page(pg)
            os.remove(pdf)
        with open(os.path.join(outdir, f"{base}.pdf"), "wb") as f:
            wr.write(f)
    except Exception as ex:  # noqa
        print("NOTE   PDF not written:", ex)
    print(f"wrote {len(paths)} sheets to {outdir}")
    sys.exit(1 if E.n_errors else 0)


if __name__ == "__main__":
    main()
