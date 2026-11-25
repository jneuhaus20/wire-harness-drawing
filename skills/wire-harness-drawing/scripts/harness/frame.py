"""The sheet frame every sheet shares: border, zones, title block, revision block, release mark."""
from harness.source import HarnessSource
from harness.svg import line, rect, sheet_height, sheet_width, table, text

Box = tuple[float, float, float, float]  # left, top, right, bottom

# The sheet has an outer border and, 12 units inside it, the frame that holds the drawing.
# Zone numbers and letters sit in the margin between the two, clear of everything else.
border_box: Box = (20, 20, sheet_width - 20, sheet_height - 20)
frame_box: Box = (32, 32, sheet_width - 32, sheet_height - 32)
release_mark_box: Box = (frame_box[0] + 10, frame_box[1] + 8, frame_box[0] + 610, frame_box[1] + 46)
title_block_width, title_block_height = 560, 120
not_to_scale = "NONE (NTS)"
revision_block_width = 490


# A package that fails its checks must not pass for a releasable drawing, so every sheet
# of it carries this mark where a reader looks first.
def release_mark(check_errors: int) -> str:
    """The NOT FOR RELEASE mark for a package with check errors."""
    x0, y0, x1, y1 = release_mark_box
    plural = "S" if check_errors != 1 else ""
    return (rect(x0, y0, x1 - x0, y1 - y0, fill="white", stroke="#c00000", stroke_width=2.5)
            + text((x0 + x1) / 2, y0 + 24, f"NOT FOR RELEASE: {check_errors} CHECK ERROR{plural}, SEE CHECKS REPORT",
                   15, "middle", "bold", fill="#c00000"))


# Draw the frame of one sheet. Return its opening SVG elements and the blocks a drawing on
# the sheet must keep clear of.
def frame(source: HarnessSource, sheet: int, sheet_count: int, sheet_title: str, check_errors: int,
          scale: str = not_to_scale) -> tuple[list[str], dict[str, Box]]:
    """The border, zones, title and revision blocks of a sheet, and the boxes the blocks take up."""
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'viewBox="0 0 {sheet_width} {sheet_height}" width="420mm" height="297mm">',
           rect(0, 0, sheet_width, sheet_height, fill="white", stroke="none"),
           rect(border_box[0], border_box[1], border_box[2] - border_box[0], border_box[3] - border_box[1], stroke_width=0.8),
           rect(frame_box[0], frame_box[1], frame_box[2] - frame_box[0], frame_box[3] - frame_box[1], stroke_width=2)]
    out += zone_grid()
    title_box = title_block(out, source["drawing"], sheet, sheet_count, sheet_title, scale)
    revision_box = revision_block(out, source["drawing"])
    if check_errors:
        out.append(release_mark(check_errors))
    return out, {"title block": title_box, "revision block": revision_box, "release mark area": release_mark_box}


def zone_grid() -> list[str]:
    """Numbered columns along the top and bottom, lettered rows along the sides."""
    left, top, right, bottom = frame_box
    zone_width, zone_height = (right - left) / 8, (bottom - top) / 6
    out = []
    for index in range(1, 8):
        x = left + index * zone_width
        out += [line(x, border_box[1], x, top), line(x, bottom, x, border_box[3])]
    for index in range(1, 6):
        y = top + index * zone_height
        out += [line(border_box[0], y, left, y), line(right, y, border_box[2], y)]
    for index in range(8):
        x = left + (index + .5) * zone_width
        out += [text(x, top - 3.5, 8 - index, 8, "middle"), text(x, border_box[3] - 3.5, 8 - index, 8, "middle")]
    for index, letter in enumerate("FEDCBA"):
        y = top + (index + .5) * zone_height + 3
        out += [text(26, y, letter, 8, "middle"), text(sheet_width - 26, y, letter, 8, "middle")]
    return out


def title_block(out: list[str], drawing: dict, sheet: int, sheet_count: int, sheet_title: str, scale: str) -> Box:
    """Draw the title block at the bottom right and return its box."""
    x, y = frame_box[2] - title_block_width, frame_box[3] - title_block_height
    out.append(rect(x, y, title_block_width, title_block_height, fill="white", stroke_width=1.5))
    fields = [
        (x, y, 560, 34, "TITLE", drawing.get("title", "")),
        (x, y + 34, 300, 30, "DWG NO.", drawing.get("number", "")),
        (x + 300, y + 34, 80, 30, "REV", drawing.get("rev", "")),
        (x + 380, y + 34, 180, 30, "SHEET", f"{sheet} OF {sheet_count}"),
        (x, y + 64, 140, 28, "DRAWN", drawing.get("drawn_by", "")),
        (x + 140, y + 64, 120, 28, "DATE", drawing.get("date", "")),
        (x + 260, y + 64, 120, 28, "CHECKED", drawing.get("checked_by", "")),
        (x + 380, y + 64, 180, 28, "SCALE", scale),
        (x, y + 92, 260, 28, "UNITS", drawing.get("units", "mm")),
        (x + 260, y + 92, 300, 28, "THIS SHEET", sheet_title),
    ]
    for field_x, field_y, width, height, caption, value in fields:
        out.append(rect(field_x, field_y, width, height, stroke_width=0.8))
        out.append(text(field_x + 4, field_y + 10, caption, 7.5, fill="#555"))
        out.append(text(field_x + 8, field_y + height - 7, value, 15 if caption == "TITLE" else 12,
                        weight="bold" if caption in ("TITLE", "DWG NO.", "REV") else "normal"))
    return (x, y, x + title_block_width, y + title_block_height)


def revision_block(out: list[str], drawing: dict) -> Box:
    """Draw the revision block at the top right and return its box."""
    revisions = drawing.get("revisions") or [{"rev": drawing.get("rev", "A"), "desc": "Initial release",
                                              "date": drawing.get("date", ""), "by": drawing.get("drawn_by", "")}]
    columns = [("REV", 40, "c"), ("DESCRIPTION", 300, "l"), ("DATE", 90, "c"), ("BY", 60, "c")]
    rows = [[revision.get("rev", ""), revision.get("desc", ""), revision.get("date", ""), revision.get("by", "")]
            for revision in revisions]
    x, y = frame_box[2] - revision_block_width, frame_box[1]
    svg, height, _ = table(x, y, columns, rows, "REVISIONS")
    out.append(svg)
    return (x, y, frame_box[2], y + height)


def close_sheet(elements: list[str]) -> str:
    """A sheet's SVG document from its elements."""
    return "\n".join(elements + ["</svg>"])
