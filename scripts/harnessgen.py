#!/usr/bin/env python3
"""harnessgen: wire harness manufacturing drawing generator.

One YAML source -> checks, cut lengths, BOM, wire list, connector tables,
a formboard-style harness drawing, and a WireViz wiring diagram.

Usage:  python3 harnessgen.py harness.yaml [-o outdir] [--check-only] [--no-wireviz]
Needs:  pyyaml.  Optional: wireviz + graphviz (wiring diagram sheet),
        cairosvg + pypdf (combined PDF).
"""
import sys

from harness.package import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
