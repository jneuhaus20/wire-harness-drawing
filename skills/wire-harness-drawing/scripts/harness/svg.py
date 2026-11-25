"""SVG drawing primitives, text measurement and the table every sheet uses."""
import html
import math

# An A3 landscape sheet in drawing units; one unit is about 0.2625 mm on A3.
sheet_width, sheet_height = 1600, 1131
font_family = "Arial, Helvetica, sans-serif"
ink = "#111"

# ---------- Text measurement ----------

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


# ---------- Primitives ----------


def text(x, y, content, size=11, anchor="start", weight="normal", fill=ink, extra="") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font_family}" font-size="{size}" '
            f'text-anchor="{anchor}" font-weight="{weight}" fill="{fill}" {extra}>{html.escape(str(content), quote=True)}</text>')


def line(x1, y1, x2, y2, width=1, color=ink, extra="") -> str:
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{width}" {extra}/>'


def rect(x, y, width, height, fill="none", stroke=ink, stroke_width=1, extra="") -> str:
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}" {extra}/>')


def arrowhead(x, y, angle) -> str:
    """A filled arrowhead with its point at (x, y), pointing along angle."""
    left, right = angle + math.radians(160), angle - math.radians(160)
    return (f'<polygon points="{x:.1f},{y:.1f} {x + 9 * math.cos(left):.1f},{y + 9 * math.sin(left):.1f} '
            f'{x + 9 * math.cos(right):.1f},{y + 9 * math.sin(right):.1f}" fill="{ink}"/>')


def horizontal_dimension(x1, x2, y, label, extension_from=None) -> str:
    """A horizontal dimension, with extension lines from extension_from=(y1, y2) when given."""
    out = []
    if extension_from:
        for x, start in ((x1, extension_from[0]), (x2, extension_from[1])):
            if start is not None:
                out.append(line(x, start, x, y + (4 if y > start else -4), 0.6, "#555"))
    out.append(line(x1, y, x2, y, 0.8))
    out.append(arrowhead(x1, y, math.pi))
    out.append(arrowhead(x2, y, 0))
    label_width = len(label) * 6.2 + 8
    middle = (x1 + x2) / 2
    if x2 - x1 > label_width + 20:
        out.append(rect(middle - label_width / 2, y - 7, label_width, 14, fill="white", stroke="none"))
        out.append(text(middle, y + 4, label, 11, "middle"))
    else:
        out.append(text(middle, y - 5, label, 11, "middle"))
    return "".join(out)


balloon_radius = 11
balloon_pitch = 23


# A column of find-number balloons; the first carries the leader to (target_x, target_y), and
# a quantity such as "4X" sits beside its balloon.
def balloon_stack(x, y, numbers, target_x, target_y, quantities=None) -> str:
    """Draw find-number balloons with one leader."""
    out = []
    for index, number in enumerate(numbers):
        balloon_y = y + index * balloon_pitch
        quantity = (quantities or {}).get(number)
        if index == 0:
            out += [line(x, balloon_y, target_x, target_y, 0.7),
                    arrowhead(target_x, target_y, math.atan2(target_y - balloon_y, target_x - x)),
                    f'<circle cx="{x:.1f}" cy="{balloon_y:.1f}" r="{balloon_radius}" fill="white" stroke="{ink}" stroke-width="1"/>',
                    text(x, balloon_y + 4, number, 11, "middle")]
        else:
            out.append(f'<circle cx="{x:.1f}" cy="{balloon_y:.1f}" r="{balloon_radius}" fill="white" stroke="{ink}"/>'
                       + text(x, balloon_y + 4, number, 11, "middle"))
        if quantity:
            out.append(text(x + balloon_radius + 3, balloon_y + 4, quantity, 10))
    return "".join(out)


# A row of find-number balloons left to right; the first carries the leader to (target_x,
# target_y), and a quantity such as "4X" follows the last balloon.
def balloon_row(x, y, numbers, target_x, target_y, quantities=None) -> str:
    """Draw find-number balloons side by side with one leader."""
    out = [line(x - balloon_radius, y, target_x, target_y, 0.7),
           arrowhead(target_x, target_y, math.atan2(target_y - y, target_x - x + balloon_radius))]
    for index, number in enumerate(numbers):
        balloon_x = x + index * balloon_pitch
        out.append(f'<circle cx="{balloon_x:.1f}" cy="{y:.1f}" r="{balloon_radius}" fill="white" stroke="{ink}" stroke-width="1"/>'
                   + text(balloon_x, y + 4, number, 11, "middle"))
        quantity = (quantities or {}).get(number)
        if quantity:
            out.append(text(balloon_x + balloon_radius + 3, y + 4, quantity, 10))
    return "".join(out)


# ---------- Tables ----------

cell_padding = 3
Column = tuple[str, float, str]  # header, width, alignment ("l" left, "c" centre)


# A table with an optional title row, a header row and data rows. Text wider than its cell
# wraps onto more lines and the row grows to hold them. Rows that would pass max_height are
# left for the caller to continue elsewhere.
def table(x, y, columns: list[Column], rows: list[list], title=None, size=9.5, row_height=15,
          max_height=None) -> tuple[str, float, int]:
    """Draw a table; return its SVG, its height and how many rows it holds."""
    out = []
    total_width = sum(width for _, width, _ in columns)
    line_pitch = round(size * 1.2, 1)

    def wrapped_row(cells, cell_size, bold):
        """Each cell's lines and the height of a row that holds the tallest."""
        lines = [wrap_to_width(str(value), width - 2 * cell_padding, cell_size, bold)
                 for (_, width, _), value in zip(columns, cells)]
        return lines, row_height + line_pitch * (max(len(cell) for cell in lines) - 1)

    def cell_text(cell_x, cell_y, width, alignment, lines, cell_size, weight):
        """The lines of one cell, the first on the row's usual baseline."""
        text_x = cell_x + cell_padding if alignment == "l" else cell_x + width / 2
        anchor = "start" if alignment == "l" else "middle"
        return "".join(text(text_x, cell_y + row_height - 4 + index * line_pitch, content, cell_size, anchor, weight)
                       for index, content in enumerate(lines))

    top = y
    if title:
        title_lines = wrap_to_width(title, total_width - 2 * cell_padding, size + 1, True)
        title_height = row_height + 2 + line_pitch * (len(title_lines) - 1)
        out.append(rect(x, top, total_width, title_height, fill="#e8e8e8"))
        out.append(cell_text(x, top + 2, total_width, "c", title_lines, size + 1, "bold"))
        top += title_height
    header_lines, header_height = wrapped_row([header for header, _, _ in columns], size, True)
    out.append(rect(x, top, total_width, header_height, fill="#f3f3f3"))
    cell_x = x
    for (_, width, alignment), lines in zip(columns, header_lines):
        out.append(rect(cell_x, top, width, header_height))
        out.append(cell_text(cell_x, top, width, alignment, lines, size, "bold"))
        cell_x += width
    top += header_height
    rows_used = 0
    for row in rows:
        lines_per_cell, height = wrapped_row(row, size, False)
        if max_height and top + height > y + max_height:
            break
        cell_x = x
        for (_, width, alignment), lines in zip(columns, lines_per_cell):
            out.append(rect(cell_x, top, width, height, stroke_width=0.6))
            out.append(cell_text(cell_x, top, width, alignment, lines, size, "normal"))
            cell_x += width
        top += height
        rows_used += 1
    return "".join(out), top - y, rows_used
