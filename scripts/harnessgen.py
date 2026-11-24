#!/usr/bin/env python3
"""harnessgen: wire harness manufacturing drawing generator.

One YAML source -> checks, cut lengths, BOM, wire list, connector tables,
a formboard-style harness drawing, and a WireViz wiring diagram.

Usage:  python3 harnessgen.py harness.yaml [-o outdir] [--check-only] [--no-wireviz]
Needs:  pyyaml.  Optional: wireviz + graphviz (wiring diagram sheet),
        cairosvg + pypdf (combined PDF).
"""
import argparse, csv, html, math, os, re, shutil, subprocess, sys, tempfile, base64
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


def parse_end(s):
    """'P1:3' -> ('P1', '3'); 'SP1' -> ('SP1', '1')."""
    s = str(s)
    if ":" in s:
        c, p = s.split(":", 1)
        return c.strip(), p.strip()
    return s.strip(), "1"


def load(path):
    with open(path) as f:
        d = yaml.safe_load(f)
    d.setdefault("drawing", {})
    d.setdefault("connectors", {})
    d.setdefault("wires", [])
    d.setdefault("layout", {})
    d.setdefault("items", [])
    d.setdefault("cables", {})
    return d


def tol_for(dr, length):
    if length is None:
        return None
    for row in dr.get("tolerance", [{"upto": 300, "tol": 5}, {"upto": 1000, "tol": 10}, {"upto": None, "tol": "1%"}]):
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
    return dict(root=root, parent=parent, children=children, seglen=seglen, depth=depth, order=order, nodes=seen)


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
    rnd = float(dr.get("round_to", 5))
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
                L = float(dr.get("loopback_length", 100))
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

def check(d, T, E):
    C = d["connectors"]
    ids = [w.get("id") for w in d["wires"]]
    for i in {x for x in ids if ids.count(x) > 1}:
        E.error(f"duplicate wire id {i}")
    for k, w in enumerate(d["wires"]):
        if not w.get("id"):
            w["id"] = f"W{k + 1}"
            E.info(f"wire #{k + 1} has no id; using {w['id']}")
    use = defaultdict(list)
    for w in d["wires"]:
        for end in ("from", "to"):
            if end not in w:
                E.error(f"{w['id']}: missing '{end}'"); continue
            c, p = parse_end(w[end])
            if c not in C:
                E.error(f"{w['id']}: {end} connector '{c}' is not defined"); continue
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
        if "from" in w and "to" in w and parse_end(w["from"])[0] == parse_end(w["to"])[0]:
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
    # netlist
    nets_built = build_nets(d)
    exp = d.get("expect", {}).get("nets")
    if exp:
        compare_nets(nets_built, exp, d, E)
    return nets_built


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
        e = bom.setdefault(key, dict(desc=desc, pn=pn, mfr=mfr, qty=0, unit=unit, refs=[], ar=ar))
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
    for cid, cab in d["cables"].items():
        ws = [w for w in d["wires"] if w.get("cable") == cid and w.get("_len")]
        L = max([w["_len"] for w in ws] or [0])
        add(("cab", cab.get("pn", cid)), cab.get("desc", "Cable"), cab.get("pn", ""), cab.get("manufacturer", ""), L / 1000, "m", [cid], ar=True)
    for w in d["wires"]:
        if w.get("cable"):
            continue
        g, col = w.get("gauge", ""), w.get("color", "")
        wt = d["drawing"].get("wire_type", "Hook-up wire")
        pn = w.get("pn") or ""
        add(("wir", g, col, pn), ", ".join(x for x in (w.get('type', wt), g, col) if x), pn, w.get("manufacturer", ""), (w.get("_len") or 0) / 1000, "m", [w["id"]], ar=True)
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
            tot = 0.0
            for cv in covs:
                for s in cv["segments"]:
                    a, b = s.split("-") if isinstance(s, str) else s
                    tot += T["seglen"].get(frozenset((a, b))) or 0
                refs += [s if isinstance(s, str) else "-".join(s) for s in cv["segments"]]
            q, unit = tot / 1000, "m"
        elif q is None and labs:
            q, ar = len(labs), False
            refs += [lb["at"] for lb in labs]
        add(("itm", iid), it["desc"], it.get("pn", ""), it.get("manufacturer", ""),
            q if isinstance(q, (int, float)) else 0, unit, refs, ar=ar)
    rows = []
    for i, (k, e) in enumerate(bom.items(), 1):
        e["find"] = i
        e["key"] = k
        rows.append(e)
    return rows


def find_no(bom, kind, ref):
    return [e["find"] for e in bom if e["key"][0] == kind and ref in e["refs"]]


# ----------------------------------------------------------------------------
# SVG helpers
# ----------------------------------------------------------------------------

W, H = 1600, 1131  # A3 landscape proportions; 1 unit ~ 0.2625 mm on A3
FONT = "Arial, Helvetica, sans-serif"
INK = "#111"


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
    out = [line(x, y, tx, ty, 0.7), f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="2" fill="{INK}"/>' if False else "",
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


def table(x, y, cols, rows, title=None, size=9.5, rowh=15, max_h=None):
    """cols: [(header, width, align)]. Returns (svg, height, rows_used)."""
    out = []
    tw = sum(c[1] for c in cols)
    yy = y
    if title:
        out.append(rect(x, yy, tw, rowh + 2, fill="#e8e8e8"))
        out.append(text(x + tw / 2, yy + rowh - 2, title, size + 1, "middle", "bold"))
        yy += rowh + 2
    out.append(rect(x, yy, tw, rowh, fill="#f3f3f3"))
    cx = x
    for h_, w_, a in cols:
        out.append(rect(cx, yy, w_, rowh))
        out.append(text(cx + 3 if a == "l" else cx + w_ / 2, yy + rowh - 4, h_, size, "start" if a == "l" else "middle", "bold"))
        cx += w_
    yy += rowh
    used = 0
    for r in rows:
        if max_h and yy + rowh > y + max_h:
            break
        cx = x
        for (h_, w_, a), v in zip(cols, r):
            out.append(rect(cx, yy, w_, rowh, sw=0.6))
            s = str(v)
            maxc = int(w_ / (size * 0.55))
            if len(s) > maxc:
                s = s[:max(1, maxc - 1)] + "…"
            out.append(text(cx + 3 if a == "l" else cx + w_ / 2, yy + rowh - 4, s, size, "start" if a == "l" else "middle"))
            cx += w_
        yy += rowh
        used += 1
    return "".join(out), yy - y, used


def frame(d, sheet, nsheets, sheet_title):
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
    s, _, _ = table(W - 20 - 490, 20, cols, [[r.get("rev", ""), r.get("desc", ""), r.get("date", ""), r.get("by", "")] for r in revs], "REVISIONS")
    out.append(s)
    return out, (tx, ty)


# ----------------------------------------------------------------------------
# Sheet 1: harness (formboard) drawing
# ----------------------------------------------------------------------------

def drawn_len(T, s):
    """A segment's length for laying out the sheet: a TBD one draws as the median known."""
    L = T["seglen"][s]
    if L is not None:
        return L
    known = sorted(v for v in T["seglen"].values() if v is not None)
    return known[len(known) // 2] if known else 300.0


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
        cy = [sety(c) for c in order[n]]
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


def sheet_drawing(d, T, seg_wires, bom, nsheets):
    dr = d["drawing"]
    C = d["connectors"]
    out, (tbx, tby) = frame(d, 1, nsheets, "HARNESS DRAWING")
    nleaf = sum(1 for n in T["order"] if n in C and n != T["root"] and not T["children"].get(n))
    notes_top = H - 20 - 20 - 15 * sum(x.count("\n") + 1 for x in default_notes(d)) - 50
    dims_h = 24 * nleaf + 40
    bottom = min(notes_top, H - 150) - dims_h - 70
    box = (170, 150, W - 230, max(bottom, 420))
    xs, ys = layout_xy(d, T, seg_wires, box)
    root = T["root"]
    trunk = T.get("trunk", {})
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
        if segs:
            a, b = segs[0]
            p, c = (a, b) if T["parent"].get(b) == a else (b, a)
            cov_marks.append((cv, (xs[p] + xs[c]) / 2, ys[c]))
    # bundles
    for n in T["order"][1:]:
        p = T["parent"][n]
        nw = len(seg_wires.get(frozenset((n, p)), []))
        pth, run = seg_path(xs[p], ys[p], xs[n], ys[n])
        out.append(f'<path d="{pth}" fill="none" stroke="#333" stroke-width="{3 + 1.6 * math.sqrt(max(nw, 1)):.1f}" stroke-linecap="round"/>')
        out.append(f'<path d="{pth}" fill="none" stroke="#9a9a9a" stroke-width="{1 + 1.6 * math.sqrt(max(nw, 1)):.1f}" stroke-linecap="round"/>')
    # segment (chain) dimensions
    for n in T["order"][1:]:
        p = T["parent"][n]
        L = T["seglen"][frozenset((n, p))]
        lab = f"{fmt_len(L)} ±{fmt_len(tol_for(dr, L))}" if L is not None else "TBD"
        is_trunk = trunk.get(p) == n
        above = (ys[n] < ys[p]) or (not is_trunk and ys[n] == ys[p] and False)
        dy = -30 if above else 34
        yd = ys[n] + dy
        if abs(ys[p] - ys[n]) < 0.5:
            out.append(hdim(xs[p], xs[n], yd, lab, (ys[p], ys[n])))
        else:  # bent branch: length called out along its run, as on NTS drawings
            _, (rx0, rx1) = seg_path(xs[p], ys[p], xs[n], ys[n])
            tw = len(lab) * 6.2 + 8
            xm = xs[p] + (rx0 - xs[p]) * 0.5 + 8 + tw / 2
            ym = (ys[p] + ys[n]) / 2
            out.append(rect(xm - tw / 2, ym - 7, tw, 14, fill="white", stroke="none"))
            out.append(text(xm, ym + 4, lab, 11, "middle"))
    # breakout nodes
    for n in T["order"]:
        if n in C:
            continue
        out.append(f'<circle cx="{xs[n]:.1f}" cy="{ys[n]:.1f}" r="4" fill="white" stroke="{INK}" stroke-width="1.2"/>')
        out.append(text(xs[n] - 6, ys[n] - 10, n, 9, "end", fill="#555"))
    # connectors
    qtys_global = {}
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
            nums = find_no(bom, "spl", c)
            if nums:
                out.append(balloons(x + 30, y - 45, nums, x + 6, y - 6))
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
        out.append(rect(bx if not left else bx, y - bh / 2, bw, bh, fill="#e4e4e4", sw=1.2, extra='rx="3"'))
        mate_x = bx + bw if not left else bx
        out.append(rect(mate_x - (6 if not left else 0), y - bh / 2 + 6, 6, bh - 12, fill="#bdbdbd", sw=0.8))
        # designator, description
        cxm = bx + bw / 2
        out.append(text(cxm, y + bh / 2 + 18, c, 14, "middle", "bold", extra='text-decoration="underline"'))
        sub = cd.get("label") or cd.get("type", "")
        out.append(text(cxm, y + bh / 2 + 32, sub, 9.5, "middle", fill="#333"))
        # balloons: housing, contacts, accessories
        nums = find_no(bom, "con", c) + find_no(bom, "ctc", c) + find_no(bom, "acc", c)
        qtys = {}
        ct = find_no(bom, "ctc", c)
        if ct:
            pins = {parse_end(w[e])[1] for w in d["wires"] for e in ("from", "to") if parse_end(w[e])[0] == c}
            qtys[ct[0]] = f"{len(pins)}X"  # one contact per pin used, as in the BOM
        bx_ = bx - 40 if left else bx + bw + 40
        out.append(balloons(bx_, y - bh / 2 - 40, nums, bx + (bw * 0.3 if left else bw * 0.7), y - bh / 2, qtys))
    # labels / markers
    for lb in d["layout"].get("labels", []):
        c = lb["at"]
        if c not in xs:
            continue
        nb = T["parent"].get(c) if c != root else next(iter(T["children"][root]), None)
        if nb is None:
            continue
        dist = float(lb.get("distance", 50))
        segL = drawn_len(T, frozenset((c, nb)))
        frac = min(dist / segL, 0.6)
        x = xs[c] + (xs[nb] - xs[c]) * min(frac, 0.6)
        x = xs[c] + math.copysign(max(abs(x - xs[c]), 60), xs[nb] - xs[c])
        y = ys[c]
        txt = lb["text"]
        tw = max(46, len(txt) * 6.4 + 10)
        out.append(rect(x - tw / 2, y - 9, tw, 18, fill="white", sw=1))
        out.append(text(x, y + 4, txt, 10, "middle"))
        seg_child = c if c != root else nb
        seg_par = T["parent"][seg_child]
        seg_above = ys[seg_child] < ys[seg_par]
        ly = y + 26 if seg_above else y - 26
        out.append(hdim(min(xs[c], x), max(xs[c], x), ly, fmt_len(dist), (y, y + (9 if seg_above else -9))))
        nums = find_no(bom, "itm", lb.get("item")) if lb.get("item") else []
        if lb.get("item"):
            nums = [e["find"] for e in bom if e["key"] == ("itm", lb["item"])]
        if nums:
            out.append(balloons(x + 30, y + 50, nums, x + 10, y + 9))
    for cv, x, y in cov_marks:
        nums = [e["find"] for e in bom if e["key"] == ("itm", cv.get("item"))]
        if nums:
            out.append(balloons(x + 25, y + 70, nums, x, y + 8, {nums[0]: "AR"}))
    # baseline (overall) dimensions from root datum to each leaf connector
    leaves = [n for n in T["order"] if n in C and n != root and not T["children"].get(n)]
    leaves.sort(key=lambda n: xs[n])
    yb = max(max(ys.values()) + 100, box[3] + 60)
    for i, n in enumerate(leaves):
        L = T["depth"][n]
        lab = f"{fmt_len(L)} ±{fmt_len(tol_for(dr, L))}" if L is not None else "TBD"
        out.append(hdim(xs[root], xs[n], yb + i * 24, f"{lab}  ({root}–{n})", (None, None)))
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
    out.append("</svg>")
    return "\n".join(out)


def default_notes(d):
    dr = d["drawing"]
    datum = dr.get("datum", "connector rear face")
    tol = dr.get("tolerance", [{"upto": 300, "tol": 5}, {"upto": 1000, "tol": 10}, {"upto": None, "tol": "1%"}])
    tols = ", ".join((f"≤{r['upto']}: ±{r['tol']}" if r.get("upto") else f"over: ±{r['tol']}") for r in tol)
    n = [
        f"FABRICATE, INSPECT AND TEST PER IPC/WHMA-A-620, CLASS {dr.get('ipc_class', 2)}.",
        f"ALL DIMENSIONS IN {dr.get('units', 'mm').upper()}. LENGTHS ARE MEASURED FROM {datum.upper()} TO BREAKOUT CENTRE OR TO THE NEXT {datum.upper()}.",
        f"LENGTH TOLERANCES UNLESS OTHERWISE SPECIFIED: {tols}.",
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
    import textwrap
    return [textwrap.fill(x, 150, subsequent_indent="     ") for x in n]


# ----------------------------------------------------------------------------
# Sheets 2+: tables
# ----------------------------------------------------------------------------

def table_sheets(d, bom, start_sheet, nsheets_hint):
    C = d["connectors"]
    tabs = []
    tabs.append(("BILL OF MATERIALS", [("FIND", 40, "c"), ("QTY", 55, "c"), ("UNIT", 40, "c"), ("PART NUMBER", 150, "l"),
                                       ("DESCRIPTION", 260, "l"), ("MFR", 90, "l"), ("REF", 140, "l")],
                 [[e["find"], ("AR" if e["ar"] else "") + (f" ({e['qty']:.2f})" if e["ar"] and e["qty"] else ("" if e["ar"] else fmt_len(round(e["qty"], 3)))),
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
    sheet_no = start_sheet

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


def finish_table_sheets(d, sheets, first, nsheets):
    out = []
    for i, body in enumerate(sheets):
        fr, _ = frame(d, first + i, nsheets, "BOM / WIRE LIST / CONNECTORS")
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
        conn = []
        is_sa = C.get(ca, {}).get("type", "").lower() == "splice"
        is_sb = C.get(cb, {}).get("type", "").lower() == "splice"
        conn.append({ca: [pa for _, pa, _ in ws]} if not is_sa else ca)
        conn.append({name: list(range(1, len(ws) + 1))})
        conn.append({cb: [pb for _, _, pb in ws]} if not is_sb else cb)
        if is_sa or is_sb:  # simple connectors take one wire per connection set
            for j, (w, pa, pb) in enumerate(ws, 1):
                wv["connections"].append([ca if is_sa else {ca: [pa]}, {name: [j]}, cb if is_sb else {cb: [pb]}])
        else:
            wv["connections"].append(conn)
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


def sheet_wiring(d, svgpath, sheet, nsheets):
    fr, _ = frame(d, sheet, nsheets, "WIRING DIAGRAM")
    with open(svgpath, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    m = re.search(rb'viewBox="([\d. -]+)"', open(svgpath, "rb").read())
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
    T = build_tree(d, E)
    seg_wires = compute_lengths(d, T, E)
    check(d, T, E)
    rep = "\n".join(f"{s:5}  {m}" for s, m in E.items) or "OK     no findings"
    print(rep)
    with open(os.path.join(outdir, f"{base}.checks.txt"), "w") as f:
        f.write(rep + "\n")
    if a.check_only:
        sys.exit(1 if E.n_errors else 0)
    if T is None:
        print("cannot draw: layout is broken"); sys.exit(1)
    bom = build_bom(d, T)
    # CSVs
    with open(os.path.join(outdir, f"{base}.bom.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["find", "qty", "unit", "pn", "description", "manufacturer", "refs"])
        for e in bom:
            w.writerow([e["find"], round(e["qty"], 3), e["unit"], e["pn"], e["desc"], e["mfr"], " ".join(map(str, dict.fromkeys(e["refs"])))])
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
    tsheets = table_sheets(d, bom, 2, 0)
    n = 1 + len(tsheets) + (1 if wv_svg else 0)
    svgs = [sheet_drawing(d, T, seg_wires, bom, n)] + finish_table_sheets(d, tsheets, 2, n)
    if wv_svg:
        svgs.append(sheet_wiring(d, wv_svg, n, n))
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
