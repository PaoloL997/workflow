"""
Trasmittal PDF generation using fpdf2.
"""

import html
import re
from datetime import date, datetime
from pathlib import Path

from fpdf import FPDF, FontFace
from fpdf.enums import TableBordersLayout

from core.date_fmt import format_display_date
from core.services.stato_esterno_colori import cell_colors, hex_to_rgb

BASE_DIR = Path(__file__).resolve().parent.parent
LOGO_PATH = BASE_DIR / "core" / "static" / "core" / "img" / "trasmittal_logo.JPG"

_WINDOWS_FONTS_DIR = Path(r"C:\Windows\Fonts")
_ARIAL_FILES = {"": "arial.ttf", "B": "arialbd.ttf", "I": "ariali.ttf", "BI": "arialbi.ttf"}


def _register_unicode_font(pdf, family):
    """Register Arial (Unicode-capable) under ``family`` on ``pdf``; fall back to
    the core Helvetica font (Latin-1 only) if the TTFs are not installed."""
    paths = {style: _WINDOWS_FONTS_DIR / fname for style, fname in _ARIAL_FILES.items()}
    if all(p.exists() for p in paths.values()):
        for style, p in paths.items():
            pdf.add_font(family, style, str(p))
        return family
    return "Helvetica"

# Usable table width on A4 with 15mm side margins.
_TABLE_WIDTH_MM = 180.0

# Column specs: (field_key, header, preferred_width_mm, align)
# ID columns are inserted based on the multi-select doc_id_cols list.
_COL_ITEM = ("item_no", "ITEM", 16, "CENTER")
_COL_CLIENT = ("client_doc_no", "CLIENT DOC.", 32, "LEFT")
_COL_VENDOR = ("vendor_doc", "VENDOR DOC.", 32, "LEFT")
_COL_CONTRACTOR = ("contractor_doc_no", "CONTRACTOR DOC.", 32, "LEFT")
_COL_REV = ("rev_no", "REV.", 10, "CENTER")
_COL_DOCUMENT = ("doc_title", "DOCUMENT", 60, "LEFT")
_COL_REQUIRED = ("dis_plan_date", "REQUIRED BY", 20, "CENTER")

# ID columns selectable via multi-select (fixed display order).
_ID_COL_ORDER = ("client", "vendor", "contractor")
_ID_COLS = {
    "client": _COL_CLIENT,
    "vendor": _COL_VENDOR,
    "contractor": _COL_CONTRACTOR,
}
VALID_DOC_ID_COLS = frozenset(_ID_COLS)

DELIVERY_OPTIONS = [
    ("attached", "In allegato", "Attached"),
    ("mail", "Per pacco postale", "By mail"),
    ("courier", "Per Corriere", "By Courier"),
    ("brevi_manu", "Brevi manu a \u00bd", "Direct_through Mr."),
]


class TrasmittalPDF(FPDF):
    def __init__(
        self,
        testata,
        address,
        date_str,
        our_ref,
        city,
        delivery_mode,
        brevi_manu_name,
        signer_name="",
        signer_role="",
    ):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.testata = testata
        self.address = address
        self.date_str = date_str
        self.our_ref = our_ref
        self.city = city
        self.delivery_mode = delivery_mode
        self.brevi_manu_name = brevi_manu_name
        self.signer_name = signer_name or ""
        self.signer_role = signer_role or ""
        self._render_signoff = False
        self._signoff_page = None
        self._font_family = _register_unicode_font(self, "TrasArial")
        self.set_margins(left=15, top=10, right=15)
        # Leave room for last-page signoff in the footer.
        self.set_auto_page_break(auto=True, margin=18)

    def header(self):
        if LOGO_PATH.exists():
            self.image(str(LOGO_PATH), x=15, y=8, w=70)
        self.set_y(34)

    def _signoff_lines(self):
        lines = ["Best Regards", "Brembana&Rolle S.p.A."]
        name = (self.signer_name or "").strip()
        role = (self.signer_role or "").strip()
        if name and role:
            lines.append(f"{name} - {role}")
        elif name:
            lines.append(name)
        elif role:
            lines.append(role)
        return lines

    def footer(self):
        # Closing block only on the last page (enabled just before output).
        if self._render_signoff and self.page_no() == self._signoff_page:
            lines = self._signoff_lines()
            line_h = 3.5
            # Pin the block to the bottom edge (small clearance so glyphs are not clipped).
            self.set_y(-(line_h * len(lines) + 2))
            self.set_font(self._font_family, "I", 8)
            self.set_text_color(0, 0, 0)
            for line in lines:
                self.cell(0, line_h, line, align="C", new_x="LMARGIN", new_y="NEXT")


def _fmt_date(date_str, city):
    """Convert ISO date string to 'CITY, 10 jan 2026' format."""
    formatted = format_display_date(date_str) or (date_str or "")
    if city:
        return f"{city}, {formatted}"
    return formatted


def _fit_text_width(pdf, text, max_w_mm, *, preferred=9.0, minimum=5.5, bold=False):
    """Largest Helvetica size in [minimum, preferred] that fits ``text`` in ``max_w_mm``."""
    text = text or ""
    if not text:
        return preferred
    size = preferred
    style = "B" if bold else ""
    while size > minimum + 1e-6:
        pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), style, size)
        if pdf.get_string_width(text) <= max_w_mm:
            return size
        size -= 0.25
    return minimum


def _addr_line_height(font_size):
    return max(4.0, font_size * 0.55 + 1.2)


def _wrap_to_width(pdf, text, max_w_mm, size):
    """Word-wrap ``text`` to ``max_w_mm`` at Helvetica ``size``; hard-split overlong tokens."""
    text = (text or "").strip()
    if not text:
        return [""]
    pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", size)
    words = text.split()
    chunks, cur = [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if pdf.get_string_width(trial) <= max_w_mm:
            cur = trial
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        if pdf.get_string_width(word) <= max_w_mm:
            cur = word
            continue
        # Hard-split a single token that still overflows at this size.
        piece = ""
        for ch in word:
            if piece and pdf.get_string_width(piece + ch) > max_w_mm:
                chunks.append(piece)
                piece = ch
            else:
                piece += ch
        cur = piece
    if cur:
        chunks.append(cur)
    return chunks or [text]


def _build_two_column_header(pdf, testata, date_str, our_ref, city, address):
    """
    Render the letter references (left) and recipient box (right) side by side.
    Returns the y position after both columns.
    """
    y_start = pdf.get_y()
    left_x = 15
    right_x = 115
    left_w = 90
    right_w = 75
    line_h = 5.5

    # ── LEFT COLUMN: date + refs ─────────────────────────────────────────────
    label_w = 25
    rows = [
        (_fmt_date(date_str, city), None),  # date line: no label
        ("Our Ref.:", our_ref or ""),
        ("Your Ref.:", testata.get("po_no", "")),
        ("Subject:", "DOCUMENTS"),
    ]

    y_left = y_start
    for label, value in rows:
        pdf.set_xy(left_x, y_left)
        if value is None:
            # date-only line
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", 9)
            pdf.cell(left_w, line_h, label)
        else:
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "B", 9)
            pdf.cell(label_w, line_h, label)
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", 9)
            pdf.cell(left_w - label_w, line_h, value)
        y_left += line_h + 1

    # ── RIGHT COLUMN: bordered address box ───────────────────────────────────
    box_padding = 3
    inner_w = right_w - box_padding * 2
    addr_lines = []
    if address.get("attn"):
        addr_lines.append(("Messr's:", address["attn"]))
    if address.get("consignee"):
        addr_lines.append(("Address:", address["consignee"]))
    street_parts = [
        p
        for p in [address.get("address", ""), address.get("zip_code", ""), address.get("city", "")]
        if p
    ]
    if street_parts:
        addr_lines.append((None, ", ".join(street_parts)))
    if address.get("country"):
        addr_lines.append((None, address["country"]))
    if address.get("ph_no"):
        addr_lines.append(("Ph. No.:", address["ph_no"]))

    # Prefit each line so font size / wrapping stay inside the box.
    fitted = []
    content_h = 0.0
    for label, value in addr_lines:
        value = str(value or "").strip()
        if label:
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "B", 9)
            lbl_w = min(pdf.get_string_width(label) + 2, inner_w * 0.45)
            val_w = max(1.0, inner_w - lbl_w)
            lbl_size = _fit_text_width(pdf, label, lbl_w, preferred=9.0, minimum=5.5, bold=True)
            # Prefer shrinking to one line; wrap only if still too wide at minimum.
            one_line_size = _fit_text_width(pdf, value, val_w, preferred=9.0, minimum=5.5)
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", one_line_size)
            if value and pdf.get_string_width(value) > val_w:
                size = min(lbl_size, 5.5)
                chunks = _wrap_to_width(pdf, value, val_w, size)
                lh = _addr_line_height(size)
                fitted.append(("labeled_wrap", label, chunks, size, lbl_w, lh))
                content_h += lh * len(chunks) + 1
            else:
                size = min(lbl_size, one_line_size)
                lh = _addr_line_height(size)
                fitted.append(("labeled", label, value, size, lbl_w, lh))
                content_h += lh + 1
        else:
            one_line_size = _fit_text_width(pdf, value, inner_w, preferred=9.0, minimum=5.5)
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", one_line_size)
            if value and pdf.get_string_width(value) > inner_w:
                size = 5.5
                chunks = _wrap_to_width(pdf, value, inner_w, size)
                lh = _addr_line_height(size)
                fitted.append(("wrap", None, chunks, size, 0, lh))
                content_h += lh * len(chunks) + 1
            else:
                lh = _addr_line_height(one_line_size)
                fitted.append(("plain", None, value, one_line_size, 0, lh))
                content_h += lh + 1

    box_h = max(content_h + box_padding * 2, 30)

    # Draw box border
    pdf.set_draw_color(0, 0, 0)
    pdf.rect(right_x, y_start, right_w, box_h)

    # Fill address content inside box
    y_right = y_start + box_padding
    for kind, label, value, size, lbl_w, lh in fitted:
        if kind == "labeled":
            pdf.set_xy(right_x + box_padding, y_right)
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "B", size)
            pdf.cell(lbl_w, lh, label)
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", size)
            pdf.cell(inner_w - lbl_w, lh, value)
            y_right += lh + 1
        elif kind == "labeled_wrap":
            for i, chunk in enumerate(value):
                pdf.set_xy(right_x + box_padding, y_right)
                if i == 0:
                    pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "B", size)
                    pdf.cell(lbl_w, lh, label)
                    pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", size)
                    pdf.cell(inner_w - lbl_w, lh, chunk)
                else:
                    pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", size)
                    pdf.set_x(right_x + box_padding + lbl_w)
                    pdf.cell(inner_w - lbl_w, lh, chunk)
                y_right += lh
            y_right += 1
        elif kind == "wrap":
            for chunk in value:
                pdf.set_xy(right_x + box_padding, y_right)
                pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", size)
                pdf.cell(inner_w, lh, chunk)
                y_right += lh
            y_right += 1
        else:
            pdf.set_xy(right_x + box_padding, y_right)
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", size)
            pdf.cell(inner_w, lh, value)
            y_right += lh + 1

    y_after = max(y_left, y_start + box_h) + 6
    pdf.set_y(y_after)


def _build_delivery_checkboxes(pdf, delivery_mode, brevi_manu_name):
    """Render the 4 delivery mode checkboxes in a horizontal row."""
    pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", 8)
    box_size = 3.5
    line_h = 5
    x_start = pdf.l_margin
    y = pdf.get_y()
    col_w = 180 // 4  # 45mm per checkbox

    for i, (key, it_label, en_label) in enumerate(DELIVERY_OPTIONS):
        x = x_start + i * col_w
        checked = delivery_mode == key

        # Draw checkbox square
        pdf.rect(x, y + (line_h - box_size) / 2, box_size, box_size)
        if checked:
            # Fill with X mark
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "B", 7)
            pdf.set_xy(x + 0.3, y + (line_h - box_size) / 2 - 0.3)
            pdf.cell(box_size, box_size + 1, "X", align="C")
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", 8)

        # Label text (Italian / English)
        label_x = x + box_size + 2
        if key == "brevi_manu" and checked and brevi_manu_name:
            full_en = f"{en_label} {brevi_manu_name}"
        else:
            full_en = en_label

        pdf.set_xy(label_x, y)
        pdf.cell(col_w - box_size - 2, line_h / 2, it_label, ln=False)
        pdf.set_xy(label_x, y + line_h / 2)
        pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "I", 7)
        pdf.cell(col_w - box_size - 2, line_h / 2, full_en, ln=False)
        pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", 8)

    pdf.ln(line_h + 4)


_TABLE_PAD_H = 1.5  # horizontal cell padding (mm), matches table padding


def _truncate_to_width(pdf, text, max_w_mm, *, bold=False):
    """Shorten ``text`` with an ellipsis so it fits in ``max_w_mm`` at the current font."""
    style = "B" if bold else ""
    # Font is already set by caller; keep style/size consistent.
    pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), style, pdf.font_size_pt)
    if pdf.get_string_width(text) <= max_w_mm:
        return text
    ell = "..."
    if pdf.get_string_width(ell) > max_w_mm:
        return ""
    lo, hi = 0, len(text)
    best = ell
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = text[:mid].rstrip() + ell
        if pdf.get_string_width(cand) <= max_w_mm:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _fit_table_cell(
    pdf,
    text,
    col_width_mm,
    *,
    preferred=8.0,
    minimum=3.5,
    bold=False,
    fill_color=None,
):
    """Return ``(text, FontFace)`` sized to fit on one line (truncate only as last resort)."""
    text = " ".join(str(text or "").split())
    # Slight extra inset: fpdf table borders/padding can eat a fraction of a mm.
    max_w = max(0.5, float(col_width_mm) - 2 * _TABLE_PAD_H - 0.5)
    style = "B" if bold else ""
    size = float(preferred)
    if text:
        while size > minimum + 1e-6:
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), style, size)
            if pdf.get_string_width(text) <= max_w:
                break
            size -= 0.25
        else:
            size = float(minimum)
            pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), style, size)
            if pdf.get_string_width(text) > max_w:
                text = _truncate_to_width(pdf, text, max_w, bold=bold)

    kwargs = {"size_pt": size}
    if bold:
        kwargs["emphasis"] = "BOLD"
    if fill_color is not None:
        kwargs["fill_color"] = fill_color
    return text, FontFace(**kwargs)


def _normalize_doc_id_cols(doc_id_cols=None, doc_id_mode=None):
    """Resolve selected ID columns; preserve Client → Vendor → Contractor order.

    Accepts a list (preferred) or a legacy single ``doc_id_mode`` string
    (``vendor`` / ``client`` / ``contractor`` / ``all`` / ``both``).
    """
    if doc_id_cols is None and doc_id_mode is not None:
        if doc_id_mode in ("all", "both"):
            doc_id_cols = list(_ID_COL_ORDER)
        elif doc_id_mode in VALID_DOC_ID_COLS:
            doc_id_cols = [doc_id_mode]
        else:
            doc_id_cols = list(_ID_COL_ORDER)
    selected = {c for c in (doc_id_cols or []) if c in VALID_DOC_ID_COLS}
    return [c for c in _ID_COL_ORDER if c in selected]


def _cell_value_for_col(doc, key):
    """Display value for a trasmittal table column key."""
    if key == "dis_plan_date":
        return format_display_date(doc.get("dis_plan_date")) or ""
    if key == "rev_no":
        rev = doc.get("rev_no")
        return "" if rev is None else str(rev)
    return str(doc.get(key) or "").strip()


def _candidate_columns(doc_id_cols):
    """Ordered column specs for the selected ID columns (before empty-column filter)."""
    cols = [_COL_ITEM]
    for key in _normalize_doc_id_cols(doc_id_cols):
        cols.append(_ID_COLS[key])
    cols.extend([_COL_REV, _COL_DOCUMENT, _COL_REQUIRED])
    return cols


def _col_has_values(key, documents):
    return any(_cell_value_for_col(doc, key) for doc in documents or [])


def _active_trasmittal_columns(documents, doc_id_cols):
    """Candidate columns minus those empty across all documents; widths sum to table width."""
    candidates = _candidate_columns(doc_id_cols)
    active = [col for col in candidates if _col_has_values(col[0], documents)]
    if not active:
        # Degenerate: keep DOCUMENT so the table still has a structure.
        active = [_COL_DOCUMENT]
    prefs = [float(col[2]) for col in active]
    total = sum(prefs) or 1.0
    scale = _TABLE_WIDTH_MM / total
    widths = [round(p * scale, 2) for p in prefs]
    # Fix rounding drift on the last column.
    widths[-1] = round(_TABLE_WIDTH_MM - sum(widths[:-1]), 2)
    return active, widths


def _build_doc_table(pdf, documents, doc_id_cols=None):
    """Render the documents table (omit fully empty columns; fit widths to page)."""
    cols, widths = _active_trasmittal_columns(documents, doc_id_cols)
    headers = [c[1] for c in cols]
    aligns = [c[3] for c in cols]
    keys = [c[0] for c in cols]

    pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", 8)
    headings_style = FontFace(emphasis="BOLD", fill_color=(255, 255, 255), size_pt=8)
    with pdf.table(
        col_widths=tuple(widths),
        first_row_as_headings=True,
        headings_style=headings_style,
        borders_layout=TableBordersLayout.ALL,
        text_align=tuple(aligns),
        line_height=int(pdf.font_size * 2.6),
        padding=(1.2, _TABLE_PAD_H),
        wrapmode="CHAR",
    ) as table:
        header_row = table.row()
        for header, w in zip(headers, widths):
            label, style = _fit_table_cell(
                pdf,
                header,
                w,
                preferred=8.0,
                bold=True,
                fill_color=(255, 255, 255),
            )
            header_row.cell(label, style=style)

        for doc in documents:
            row = table.row()
            for key, w in zip(keys, widths):
                value = _cell_value_for_col(doc, key)
                text, style = _fit_table_cell(pdf, value, w)
                row.cell(text, style=style)


def _build_notes_header(pdf):
    """Left-aligned 'Note' section header below the documents table."""
    pdf.ln(6)
    pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "B", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 6, "Note", align="L", new_x="LMARGIN", new_y="NEXT")


def genera_trasmittal_pdf(
    testata,
    addresses,
    documents,
    date_str,
    our_ref="",
    city="",
    delivery_mode="attached",
    brevi_manu_name="",
    doc_id_cols=None,
    doc_id_mode=None,
    signer_name="",
    signer_role="",
):
    """
    Generate a trasmittal PDF and return the raw bytes.

    Args:
        testata: dict with keys job, po_no, job_detail, client
        addresses: list of dicts with keys consignee, address, zip_code, city, country, attn, ph_no
        documents: list of dicts with keys item_no, vendor_doc, client_doc_no,
            contractor_doc_no, doc_title, rev_no, dis_plan_date (ISO; shown in REQUIRED BY)
        date_str: ISO date string (e.g. '2025-01-15')
        our_ref: trasmittal reference number (user-provided)
        city: city name for the date header (e.g. 'Schio')
        delivery_mode: one of 'attached', 'mail', 'courier', 'brevi_manu'
        brevi_manu_name: name after "Mr." when delivery_mode is 'brevi_manu'
        doc_id_cols: list of 'vendor' | 'client' | 'contractor' to include as ID columns
            (fully empty columns are omitted regardless). Default: all three.
        doc_id_mode: legacy single-mode string; used only if ``doc_id_cols`` is None
        signer_name: full name for the closing block (e.g. 'Gianni Sartore')
        signer_role: role/title for the closing block (e.g. 'PM')

    Returns:
        bytes — the PDF content
    """
    first_addr = addresses[0] if addresses else {}
    id_cols = _normalize_doc_id_cols(doc_id_cols, doc_id_mode)
    if not id_cols and doc_id_cols is None and doc_id_mode is None:
        id_cols = list(_ID_COL_ORDER)

    pdf = TrasmittalPDF(
        testata,
        first_addr,
        date_str,
        our_ref=our_ref,
        city=city,
        delivery_mode=delivery_mode,
        brevi_manu_name=brevi_manu_name,
        signer_name=signer_name,
        signer_role=signer_role,
    )
    pdf.add_page()

    # Two-column header: refs (left) + address box (right)
    _build_two_column_header(pdf, testata, date_str, our_ref, city, first_addr)

    # Intro text
    pdf.set_font(getattr(pdf, "_font_family", "Helvetica"), "", 9)
    pdf.cell(0, 6, "Please find herewith the following documents", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Delivery checkboxes
    _build_delivery_checkboxes(pdf, delivery_mode, brevi_manu_name)

    # Document table
    _build_doc_table(pdf, documents, doc_id_cols=id_cols)

    # Notes section header (left)
    _build_notes_header(pdf)

    # Enable last-page signoff just before footer is finalized on output.
    pdf._signoff_page = pdf.page_no()
    pdf._render_signoff = True

    return bytes(pdf.output())


# ── Situazione documenti PDF ─────────────────────────────────────────────────

# Reference Document Status header is A3 landscape; coordinates are PDF points.
_PT = 25.4 / 72  # mm per PDF point
_HEADER_BOTTOM_PT = 135.12
_YELLOW = (255, 255, 153)
_A3_LANDSCAPE_W = 420.0
_A3_LANDSCAPE_H = 297.0
_TABLE_MARGIN_MM = 8.0
_TABLE_BORDER = (185, 185, 185)

# Header column offsets at the reference width (pt from left edge).
# When the table is wider, everything before STATUS scales proportionally.
_H_OFF_PO = 292.40  # CLIENT | PO
_H_OFF_JOB = 651.88  # PO | JOB
_H_OFF_REPORT = 762.56  # logo area | REPORT DATE
_H_OFF_STATUS = 871.00  # content area | STATUS
_H_STATUS_WIDTH = 238.28  # fixed STATUS column
_HEADER_NATURAL_WIDTH_PT = _H_OFF_STATUS + _H_STATUS_WIDTH
_H_OFF_VALBREMBO = 304.10  # "Valbrembo (BG) - ITALY" label
_H_OFF_LOGO0, _H_OFF_LOGO1 = 6.2, 208.3

_STATUS_LEGEND = [
    ("A", "Approved"),
    ("C", "Commented-To be resubmitted-Work can proceed"),
    ("F", "Final - As Built"),
    ("I", "Commented-To be issued as Final"),
    ("O", "Old"),
    ("R", "Rejected - Work can not proceed"),
    ("S", "Superseeded"),
    ("Z", "For Information"),
]

# Canonical swatch colors (aligned with import_old / StatoEsterno defaults).
_STATUS_COLORS = {
    "A": (0, 176, 80),
    "C": (214, 29, 9),
    "F": (255, 192, 0),
    "I": (214, 29, 9),
    "O": (214, 29, 9),
    "R": (214, 29, 9),
    "S": (184, 184, 184),
    "Z": (255, 192, 0),
}


def _pt(value: float) -> float:
    return value * _PT


def _fmt_dd_mm_yyyy(value) -> str:
    """Format a date/datetime/ISO string as DD/MM/YYYY."""
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        value = value.date()
    elif isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    elif not isinstance(value, date):
        return str(value)
    return f"{value.day:02d}/{value.month:02d}/{value.year}"


class SituazioneDocumentiPDF(FPDF):
    def __init__(self, page_width_mm=None):
        # A3 landscape is 420 x 297 mm; widen when many revision columns are needed.
        # Use portrait orientation with an explicit (width, height) tuple so fpdf2
        # does not swap the custom dimensions.
        w = max(_A3_LANDSCAPE_W, float(page_width_mm or _A3_LANDSCAPE_W))
        super().__init__(orientation="P", unit="mm", format=(w, _A3_LANDSCAPE_H))
        self.set_margins(left=0, top=0, right=0)
        self.set_auto_page_break(auto=False)
        fonts = Path(r"C:\Windows\Fonts")
        arial = fonts / "arial.ttf"
        arial_bd = fonts / "arialbd.ttf"
        if arial.exists() and arial_bd.exists():
            self.add_font("SitArial", "", str(arial))
            self.add_font("SitArial", "B", str(arial_bd))
            self._sit_font = "SitArial"
        else:
            self._sit_font = "Helvetica"
        self._sit_testata = None
        self._sit_report_date = None
        self._sit_header_left_pt = None
        self._sit_header_right_pt = None
        self._sit_table_meta = None
        self._sit_include_status = True
        self._sit_draw_col_headers = True

    def header(self):
        # Document Status block + column headers on every page.
        if self._sit_testata is None:
            return
        left_pt = self._sit_header_left_pt
        right_pt = self._sit_header_right_pt
        if left_pt is None or right_pt is None:
            return
        _build_situazione_header(
            self,
            self._sit_testata,
            self._sit_report_date or "",
            left_pt=left_pt,
            right_pt=right_pt,
            include_status=bool(self._sit_include_status),
        )
        meta = self._sit_table_meta
        if meta and self._sit_draw_col_headers:
            _draw_situazione_col_headers(self, meta)

    def footer(self):
        pass


def _fill_pt(pdf: FPDF, x0: float, y0: float, x1: float, y1: float, rgb) -> None:
    pdf.set_fill_color(*rgb)
    pdf.rect(_pt(x0), _pt(y0), _pt(x1 - x0), _pt(y1 - y0), style="F")


# Uniform header rule thickness in PDF points.
_HEADER_LINE_PT = 0.55


def _h_line_pt(pdf: FPDF, x0: float, x1: float, y: float, thickness: float = None) -> None:
    """Horizontal rule as a stroked line (crisper joins than filled rects)."""
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(_pt(thickness if thickness is not None else _HEADER_LINE_PT))
    pdf.line(_pt(x0), _pt(y), _pt(x1), _pt(y))


def _v_line_pt(pdf: FPDF, x: float, y0: float, y1: float, thickness: float = None) -> None:
    """Vertical rule as a stroked line (crisper joins than filled rects)."""
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(_pt(thickness if thickness is not None else _HEADER_LINE_PT))
    pdf.line(_pt(x), _pt(y0), _pt(x), _pt(y1))


def _text_pt(
    pdf: FPDF, x_pt: float, y_top_pt: float, text: str, size: float, bold: bool = True
) -> None:
    """Draw text at reference PDF-point coordinates (y = top of glyph bbox)."""
    font = getattr(pdf, "_sit_font", "Helvetica")
    pdf.set_font(font, "B" if bold else "", size)
    baseline_pt = y_top_pt + size * 0.82
    pdf.text(_pt(x_pt), _pt(baseline_pt), html.unescape(text))


def _fit_font_size(
    pdf: FPDF,
    text: str,
    max_width_pt: float,
    preferred: float,
    minimum: float = 4.5,
    bold: bool = True,
    step: float = 0.25,
) -> float:
    """Largest font size in [minimum, preferred] that fits ``text`` in ``max_width_pt``."""
    font = getattr(pdf, "_sit_font", "Helvetica")
    size = preferred
    max_w_mm = _pt(max_width_pt)
    while size > minimum + 1e-6:
        pdf.set_font(font, "B" if bold else "", size)
        if pdf.get_string_width(text) <= max_w_mm:
            return size
        size -= step
    return minimum


def _cell_text_pt(
    pdf: FPDF,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    text: str,
    *,
    preferred: float = 7.7,
    minimum: float = 4.5,
    bold: bool = True,
    align: str = "left",
    pad_x: float = 4.0,
    pad_y: float = 1.5,
) -> None:
    """Draw ``text`` inside a cell, shrinking the font so it fits the width."""
    text = html.unescape((text or "").strip())
    if not text:
        return

    max_w = max(1.0, (x1 - x0) - 2 * pad_x)
    max_h = max(1.0, (y1 - y0) - 2 * pad_y)
    # Cap preferred size so a single line also fits the cell height.
    preferred = min(preferred, max_h)
    minimum = min(minimum, preferred)

    size = _fit_font_size(pdf, text, max_w, preferred, minimum=minimum, bold=bold)
    font = getattr(pdf, "_sit_font", "Helvetica")
    pdf.set_font(font, "B" if bold else "", size)
    max_w_mm = _pt(max_w)
    # Last resort: trim if still too wide at the minimum size.
    while len(text) > 1 and pdf.get_string_width(text) > max_w_mm:
        text = text[:-1]
        pdf.set_font(font, "B" if bold else "", size)

    tw_pt = pdf.get_string_width(text) / _PT
    if align == "center":
        x = x0 + ((x1 - x0) - tw_pt) / 2
    elif align == "right":
        x = x1 - pad_x - tw_pt
    else:
        x = x0 + pad_x
    y_top = y0 + ((y1 - y0) - size) / 2
    _text_pt(pdf, x, y_top, text, size, bold=bold)


def _planned_dates_for_latest_rev(revs: list) -> dict:
    """Mirror UI plannedDatesForLatestRev for Submission / Receipt planning cols."""
    if not revs:
        return {"planned_send": None, "planned_receipt": None}
    latest = revs[-1]
    ext_label = (latest.get("ext_status_label") or "").strip().lower()
    if ext_label == "approved":
        return {"planned_send": None, "planned_receipt": None}
    int_status = (latest.get("int_status") or "").strip()
    if int_status == "inviato_al_cliente":
        return {"planned_send": None, "planned_receipt": latest.get("rec_plan_date")}
    if int_status != "ricevuto":
        return {"planned_send": latest.get("dis_plan_date"), "planned_receipt": None}
    return {"planned_send": None, "planned_receipt": None}


def _is_date_overdue(iso) -> bool:
    if not iso:
        return False
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return False
    return d < date.today()


def _format_rev_label(rev_no, rev_let, rev_let_flag: bool) -> str:
    """Local copy of format_revisione_label to keep pdf.py free of Django imports."""
    if rev_let_flag:
        if rev_let:
            return str(rev_let)
        return str(rev_no) if rev_no is not None else ""
    return str(rev_no) if rev_no is not None else ""


def _rev_group_label(revs_by_index: list, rev_idx: int, rev_let_flag: bool) -> str:
    for revs in revs_by_index:
        if rev_idx < len(revs):
            rev = revs[rev_idx]
            label = _format_rev_label(rev.get("rev_no"), rev.get("rev_let") or "", rev_let_flag)
            if label:
                return f"Rev. {label}"
    return f"Rev. {rev_idx}"


def _revs_for_doc(revisioni_by_doc: dict, doc_id) -> list:
    if not revisioni_by_doc:
        return []
    if doc_id in revisioni_by_doc:
        return list(revisioni_by_doc[doc_id] or [])
    key = str(doc_id)
    if key in revisioni_by_doc:
        return list(revisioni_by_doc[key] or [])
    try:
        as_int = int(doc_id)
    except (TypeError, ValueError):
        return []
    return list(revisioni_by_doc.get(as_int) or [])


# Fixed document columns shown before Planning (order preserved in export).
_FIXED_DOC_COLUMNS = [
    {"key": "client_doc_no", "label": "Client Doc No", "width": 28},
    {"key": "client_doc_class", "label": "Client Doc Class", "width": 24},
    {"key": "contractor_doc_no", "label": "Contractor Doc No", "width": 28},
    {"key": "vendor_doc", "label": "Vendor Document", "width": 32},
    {"key": "doc_title", "label": "Title", "width": 48},
    {"key": "item_no", "label": "Item", "width": 14},
    {"key": "penalty", "label": "Penalty", "width": 14, "is_penalty": True},
]


def _fixed_col_value(doc: dict, col: dict) -> str:
    if col.get("is_penalty"):
        return "Yes" if doc.get("doc_penalty") else "No"
    return str(doc.get(col["key"]) or "").strip()


def _fixed_col_has_values(col: dict, documenti: list) -> bool:
    if col.get("is_penalty"):
        return any(doc.get("doc_penalty") for doc in documenti)
    key = col["key"]
    return any(str(doc.get(key) or "").strip() for doc in documenti)


def _active_fixed_doc_columns(documenti: list) -> list:
    """Return fixed columns that have at least one non-empty value in the export."""
    docs = list(documenti or [])
    return [col for col in _FIXED_DOC_COLUMNS if _fixed_col_has_values(col, docs)]


def _situazione_column_widths(max_revs: int, active_fixed: list | None = None) -> list:
    """Return mm widths for fixed + planning + revision columns."""
    fixed_cols = active_fixed or list(_FIXED_DOC_COLUMNS)
    fixed = [col["width"] for col in fixed_cols]
    fixed.extend([22, 22])  # Submission date, Receipt date
    rev_w = [20, 20, 12]  # Dispatch, Received, Status
    widths = list(fixed)
    for _ in range(max(1, max_revs)):
        widths.extend(rev_w)
    return widths


def _situazione_page_width_mm(max_revs: int, active_fixed: list | None = None) -> float:
    widths = _situazione_column_widths(max_revs, active_fixed)
    needed = _TABLE_MARGIN_MM * 2 + sum(widths)
    return max(_A3_LANDSCAPE_W, needed)


def _header_layout(left: float, right: float, *, include_status: bool = True) -> dict:
    """Scale header columns to fill ``[left, right]``.

    When ``include_status`` is True, STATUS stays fixed on the right and the
    remaining content scales. When False, content fills the full band.
    """
    if include_status:
        x_status = right - _H_STATUS_WIDTH
        content_w = max(1.0, x_status - left)
        scale = content_w / _H_OFF_STATUS
        content_right = x_status
    else:
        content_w = max(1.0, right - left)
        scale = content_w / _H_OFF_STATUS
        content_right = right
        x_status = right
    return {
        "scale": scale,
        "include_status": include_status,
        "x_po": left + _H_OFF_PO * scale,
        "x_job": left + _H_OFF_JOB * scale,
        "x_report": left + _H_OFF_REPORT * scale,
        "x_status": x_status,
        "content_right": content_right,
        "valbrembo_x": left + _H_OFF_VALBREMBO * scale,
    }


def _build_situazione_header(
    pdf: FPDF,
    testata: dict,
    report_date_str: str,
    *,
    left_pt: float,
    right_pt: float,
    include_status: bool = True,
) -> None:
    """Draw the Document Status header fitted to ``[left_pt, right_pt]``.

    The block spans exactly the table width. When ``include_status`` is True,
    STATUS keeps a fixed width on the right; otherwise content fills the band.
    """
    left = float(left_pt)
    right = float(right_pt)
    lay = _header_layout(left, right, include_status=include_status)
    x_po = lay["x_po"]
    x_job = lay["x_job"]
    x_report = lay["x_report"]
    x_status = lay["x_status"]
    content_right = lay["content_right"]

    top = 28.80
    bottom = _HEADER_BOTTOM_PT
    y_report_mid = 53.88
    y_meta = 85.80
    y_deliv = 110.64
    y_req = 122.88

    client = (testata.get("client") or "").strip()
    po_no = (testata.get("po_no") or "").strip()
    job = (testata.get("job") or "").strip()
    job_detail = (testata.get("job_detail") or "").strip()
    delivery_date = _fmt_dd_mm_yyyy(testata.get("delivery_date"))
    delivery_term = (testata.get("delivery_term") or "").strip()
    # Bid No. in the UI; printed as "Req. No." on the Document Status header.
    requisition = (testata.get("requisition") or "").strip()

    # Yellow fills — meta rows only (STATUS stays white when present)
    _fill_pt(pdf, left, y_meta, content_right, bottom, _YELLOW)

    # Logo
    if LOGO_PATH.exists():
        lx0 = left + _H_OFF_LOGO0
        ly0 = 31.1
        box_w = (_H_OFF_LOGO1 - _H_OFF_LOGO0) * 0.90
        pdf.image(str(LOGO_PATH), x=_pt(lx0), y=_pt(ly0), w=_pt(box_w))

    # Outer frame — flush with table left/right
    _h_line_pt(pdf, left, right, top)
    _h_line_pt(pdf, left, right, bottom)
    _v_line_pt(pdf, left, top, bottom)
    _v_line_pt(pdf, right, top, bottom)

    # Horizontal internals
    _h_line_pt(pdf, x_report, content_right, y_report_mid)
    _h_line_pt(pdf, left, content_right, y_meta)
    _h_line_pt(pdf, left, content_right, y_deliv)
    _h_line_pt(pdf, left, x_job, y_req)

    # Vertical internals
    _v_line_pt(pdf, x_po, y_meta, y_req)
    _v_line_pt(pdf, x_job, y_meta, bottom)
    _v_line_pt(pdf, x_report, top, y_meta)
    if include_status:
        _v_line_pt(pdf, x_status, top, bottom)

    # Static labels
    font = getattr(pdf, "_sit_font", "Helvetica")
    _text_pt(pdf, lay["valbrembo_x"], 78.3, "Valbrembo (BG) - ITALY", 7.7)
    _cell_text_pt(
        pdf,
        x_report,
        content_right,
        top,
        y_report_mid,
        "REPORT DATE",
        preferred=11.0,
        minimum=6.0,
        align="center",
    )

    if include_status:
        _cell_text_pt(
            pdf,
            x_status,
            right,
            32.0,
            46.0,
            "STATUS",
            preferred=8.5,
            minimum=6.0,
            align="center",
        )

        # STATUS legend — fixed-width column on the right
        legend_ys = [49.5, 59.2, 68.9, 78.6, 88.3, 98.1, 107.8, 117.5]
        legend_max_w = _H_STATUS_WIDTH - 6.0 - 14.0
        swatch = 8.0  # pt
        for (code, label), ly in zip(_STATUS_LEGEND, legend_ys):
            rgb = _STATUS_COLORS.get(code, (158, 158, 158))
            sx, sy = x_status + 3.0, ly + 1.0
            pdf.set_fill_color(*rgb)
            pdf.set_draw_color(120, 120, 120)
            pdf.set_line_width(0.1)
            pdf.rect(_pt(sx), _pt(sy), _pt(swatch), _pt(swatch), style="DF")
            line = f"{code}: {label}"
            size = _fit_font_size(pdf, line, legend_max_w, preferred=7.7, minimum=4.5, bold=True)
            pdf.set_font(font, "B", size)
            while len(line) > len(code) + 2 and pdf.get_string_width(line) > _pt(legend_max_w):
                label = label[:-1]
                line = f"{code}: {label}"
                pdf.set_font(font, "B", size)
            text_x = x_status + 3.0 + swatch + 3.0
            _text_pt(pdf, text_x, ly, code, size, bold=True)
            pdf.set_font(font, "B", size)
            code_w_pt = pdf.get_string_width(code) / _PT
            _text_pt(pdf, text_x + code_w_pt, ly, f": {label}", size, bold=False)

    # Dynamic fields
    _cell_text_pt(pdf, left, x_po, y_meta, y_deliv, f"CLIENT: {client}")
    _cell_text_pt(pdf, x_po, x_job, y_meta, y_deliv, f"PO No. {po_no}")
    _cell_text_pt(pdf, x_job, content_right, y_meta, y_deliv, f"JOB:  {job}")
    _cell_text_pt(pdf, left, x_po, y_deliv, y_req, f"Delivery Date: {delivery_date}")
    _cell_text_pt(pdf, x_po, x_job, y_deliv, y_req, f"Delivery Terms: {delivery_term}")
    _cell_text_pt(pdf, x_job, content_right, y_deliv, bottom, job_detail)
    _cell_text_pt(
        pdf,
        left,
        x_job,
        y_req,
        bottom,
        f"Req. No. {requisition}".rstrip(),
        preferred=10.0,
        minimum=5.0,
        align="center",
    )
    _cell_text_pt(
        pdf,
        x_report,
        content_right,
        y_report_mid,
        y_meta,
        report_date_str,
        preferred=12.0,
        minimum=6.0,
        align="center",
    )

    pdf.set_y(_pt(_HEADER_BOTTOM_PT))


def _draw_mm_cell(
    pdf: FPDF,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    *,
    bold: bool = False,
    align: str = "L",
    fill_rgb=None,
    text_rgb=(0, 0, 0),
    font_size: float = 6.5,
) -> None:
    """Draw a lightly bordered table cell in mm coordinates."""
    pdf.set_draw_color(*_TABLE_BORDER)
    pdf.set_line_width(0.15)
    if fill_rgb:
        pdf.set_fill_color(*fill_rgb)
        pdf.rect(x, y, w, h, style="DF")
    else:
        pdf.rect(x, y, w, h, style="D")

    text = html.unescape((text or "").strip())
    if not text:
        return

    font = getattr(pdf, "_sit_font", "Helvetica")
    size = font_size
    pdf.set_font(font, "B" if bold else "", size)
    max_w = max(0.5, w - 1.2)
    while size > 4.0 and pdf.get_string_width(text) > max_w:
        size -= 0.25
        pdf.set_font(font, "B" if bold else "", size)
    while len(text) > 1 and pdf.get_string_width(text) > max_w:
        text = text[:-1]
        pdf.set_font(font, "B" if bold else "", size)

    pdf.set_text_color(*text_rgb)
    tw = pdf.get_string_width(text)
    if align == "C":
        tx = x + (w - tw) / 2
    elif align == "R":
        tx = x + w - 0.6 - tw
    else:
        tx = x + 0.6
    ty = y + h / 2 + size * 0.28
    pdf.text(tx, ty, text)
    pdf.set_text_color(0, 0, 0)


def _draw_situazione_col_headers(pdf: FPDF, meta: dict) -> None:
    """Draw the 2-row column header for the situazione table."""
    widths = meta["widths"]
    max_revs = meta["max_revs"]
    rev_labels = meta["rev_labels"]
    fixed_labels = meta["fixed_labels"]
    x0 = meta.get("x0", _TABLE_MARGIN_MM)
    y = pdf.get_y()
    h1, h2 = 5.5, 5.5
    fixed_n = len(fixed_labels)
    plan_n = 2
    fixed_w = sum(widths[:fixed_n])
    plan_w = sum(widths[fixed_n : fixed_n + plan_n])

    # Row 1: fixed labels spanning 2 rows + Planning + Rev groups (white bg, bold)
    x = x0
    for i, label in enumerate(fixed_labels):
        _draw_mm_cell(
            pdf,
            x,
            y,
            widths[i],
            h1 + h2,
            label,
            bold=True,
            align="C",
            font_size=6.0,
        )
        x += widths[i]

    _draw_mm_cell(
        pdf,
        x,
        y,
        plan_w,
        h1,
        "Planning",
        bold=True,
        align="C",
        font_size=6.5,
    )
    x += plan_w

    for r in range(max_revs):
        rw = sum(widths[fixed_n + plan_n + r * 3 : fixed_n + plan_n + (r + 1) * 3])
        _draw_mm_cell(
            pdf,
            x,
            y,
            rw,
            h1,
            rev_labels[r],
            bold=True,
            align="C",
            font_size=6.5,
        )
        x += rw

    # Row 2: planning + revision sub-headers
    y2 = y + h1
    x = x0 + fixed_w
    for label, w in zip(
        ["Submission date", "Receipt date"],
        widths[fixed_n : fixed_n + plan_n],
    ):
        _draw_mm_cell(
            pdf,
            x,
            y2,
            w,
            h2,
            label,
            bold=True,
            align="C",
            font_size=5.5,
        )
        x += w

    sub = ["Dispatch", "Received", "Status"]
    for r in range(max_revs):
        for si, label in enumerate(sub):
            w = widths[fixed_n + plan_n + r * 3 + si]
            _draw_mm_cell(
                pdf,
                x,
                y2,
                w,
                h2,
                label,
                bold=True,
                align="C",
                font_size=5.5,
            )
            x += w

    pdf.set_y(y + h1 + h2)


def _tint_rgb(hex_color: str, pct: float = 0.20):
    """Blend hex color toward white (stessa quota della UI: --status-tint-strong-pct)."""
    rgb = hex_to_rgb(hex_color)
    if not rgb:
        return None
    return tuple(int(c * pct + 255 * (1.0 - pct)) for c in rgb)


def _status_cell_rgb(hex_color: str):
    """``(fondo, testo)`` pieni per una cella risposta cliente, come nella UI.

    Stessa coppia colore/testo usata dalle celle di situazione documenti
    (``core.services.stato_esterno_colori``), così stampa e schermo coincidono.
    """
    if not hex_to_rgb(hex_color):
        return None
    cella = cell_colors(hex_color)
    return hex_to_rgb(cella["bg"]), hex_to_rgb(cella["fg"])


def _latest_ext_status_color(revs: list) -> str:
    """Hex color of the latest revision that has an external status."""
    for rev in reversed(revs or []):
        color = (rev.get("ext_status_colore") or "").strip()
        if color:
            return color
    return ""


def _is_iso_overdue(iso) -> bool:
    """True when ``iso`` (YYYY-MM-DD…) is strictly before today."""
    if not iso:
        return False
    day = str(iso).strip()[:10]
    if len(day) < 10:
        return False
    return day < date.today().isoformat()


def _situazione_row_values(doc: dict, revs: list, max_revs: int, active_fixed: list) -> list:
    """Flat list of cell values for one document row (aligned with widths)."""
    planned = _planned_dates_for_latest_rev(revs)
    send_iso = planned["planned_send"]
    recv_iso = planned["planned_receipt"]
    values = [(_fixed_col_value(doc, col), False) for col in active_fixed]
    values.extend(
        [
            (_fmt_dd_mm_yyyy(send_iso), False),
            (_fmt_dd_mm_yyyy(recv_iso), False),
        ]
    )
    for r in range(max_revs):
        rev = revs[r] if r < len(revs) else None
        if rev:
            letter = (rev.get("ext_status_lettera") or "").strip()
            values.extend(
                [
                    (_fmt_dd_mm_yyyy(rev.get("dis_act_date")), False),
                    (_fmt_dd_mm_yyyy(rev.get("rec_act_date")), False),
                    (letter, False),
                ]
            )
        else:
            values.extend([("", False), ("", False), ("", False)])
    return values


def _vendor_doc_sort_key(doc: dict):
    """Natural sort key for B&R Doc (vendor_doc), mirroring the UI table."""
    s = str(doc.get("vendor_doc") or "").strip().lower()
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", s) if p]


def _situazione_table_meta(
    documenti: list,
    revisioni_by_doc: dict,
    rev_let_flag: bool,
    page_w_mm: float,
) -> dict:
    """Build column layout meta for the situazione export table."""
    docs = sorted(list(documenti or []), key=_vendor_doc_sort_key)
    revs_list = []
    for doc in docs:
        revs = _revs_for_doc(revisioni_by_doc, doc.get("id"))
        revs.sort(key=lambda r: (r.get("rev_no") is None, r.get("rev_no") or 0, r.get("id") or 0))
        revs_list.append(revs)

    max_revs = max((len(r) for r in revs_list), default=1) or 1
    active_fixed = _active_fixed_doc_columns(docs)
    widths = _situazione_column_widths(max_revs, active_fixed)
    table_w = sum(widths)
    # Header and table share exactly the same width (header scales when narrower).
    band_w = table_w
    band_x0 = max(_TABLE_MARGIN_MM, (page_w_mm - band_w) / 2)
    table_x0 = band_x0
    rev_labels = [_rev_group_label(revs_list, i, rev_let_flag) for i in range(max_revs)]
    vendor_col_idx = next(
        (i for i, col in enumerate(active_fixed) if col["key"] == "vendor_doc"),
        None,
    )
    return {
        "widths": widths,
        "max_revs": max_revs,
        "rev_labels": rev_labels,
        "x0": table_x0,
        "band_x0": band_x0,
        "band_w": band_w,
        "fixed_labels": [col["label"] for col in active_fixed],
        "fixed_n": len(active_fixed),
        "active_fixed": active_fixed,
        "vendor_col_idx": vendor_col_idx,
        "docs": docs,
        "revs_list": revs_list,
    }


def _build_situazione_table(
    pdf: SituazioneDocumentiPDF,
    documenti: list,
    revisioni_by_doc: dict,
    rev_let_flag: bool,
) -> None:
    """Prepare table meta and draw data rows (headers come from FPDF.header)."""
    meta = _situazione_table_meta(documenti, revisioni_by_doc, rev_let_flag, pdf.w)
    pdf._sit_table_meta = meta

    docs = meta["docs"]
    revs_list = meta["revs_list"]
    widths = meta["widths"]
    max_revs = meta["max_revs"]
    active_fixed = meta["active_fixed"]
    table_x0 = meta["x0"]
    vendor_col_idx = meta["vendor_col_idx"]

    # First page: header() already drew Document Status + column headers.
    # If we somehow have no page yet, add one (triggers header).
    if pdf.page_no() == 0:
        pdf.add_page()
    elif pdf.get_y() < _pt(_HEADER_BOTTOM_PT):
        # Header was drawn; ensure we sit below it + column headers.
        pass

    row_h = 5.2
    bottom_limit = _A3_LANDSCAPE_H - _TABLE_MARGIN_MM

    for doc, revs in zip(docs, revs_list):
        if pdf.get_y() + row_h > bottom_limit:
            pdf.add_page()
        cells = _situazione_row_values(doc, revs, max_revs, active_fixed)
        vendor_colors = _status_cell_rgb(_latest_ext_status_color(revs))
        x = table_x0
        y = pdf.get_y()
        for i, ((text, overdue), w) in enumerate(zip(cells, widths)):
            color = (180, 0, 0) if overdue and text else (0, 0, 0)
            fill = None
            if i == vendor_col_idx and vendor_colors:
                fill, color = vendor_colors
            _draw_mm_cell(
                pdf,
                x,
                y,
                w,
                row_h,
                text,
                bold=overdue,
                align="C" if w <= 22 else "L",
                fill_rgb=fill,
                text_rgb=color,
                font_size=6.0,
            )
            x += w
        pdf.set_y(y + row_h)


def _int_status_export_label(rev: dict | None) -> str:
    """Match UI getIntStatusMeta: empty int_status → \"Da inviare\"."""
    if not rev:
        return "Da inviare"
    code = (rev.get("int_status") or "").strip()
    if not code:
        return "Da inviare"
    return (rev.get("int_status_label") or code).strip()


def _row_highlight_hex(rev: dict | None) -> str:
    """Tint from client response color only; otherwise white (no fill)."""
    if not rev:
        return ""
    return (rev.get("ext_status_colore") or "").strip()


def _situazione_verticale_flat_rows(
    documenti: list,
    revisioni_by_doc: dict,
    rev_let_flag: bool,
) -> list:
    """One flat row per revision (same shape as the verticale UI table)."""
    rows = []
    for doc in sorted(list(documenti or []), key=_vendor_doc_sort_key):
        revs = _revs_for_doc(revisioni_by_doc, doc.get("id"))
        revs = sorted(
            revs,
            key=lambda r: (r.get("rev_no") is None, r.get("rev_no") or 0),
        )
        if not revs:
            revs = [None]
        for rev in revs:
            rows.append(
                {
                    "item_no": doc.get("item_no") or "",
                    "vendor_doc": doc.get("vendor_doc") or "",
                    "client_doc_no": doc.get("client_doc_no") or "",
                    "contractor_doc_no": doc.get("contractor_doc_no") or "",
                    "client_doc_class": doc.get("client_doc_class") or "",
                    "doc_title": doc.get("doc_title") or "",
                    "department": (doc.get("reparto_acronimo") or doc.get("reparto_label") or ""),
                    "penalty": "Yes" if doc.get("doc_penalty") else "",
                    "payment": "Yes" if doc.get("doc_payment") else "",
                    "rev_label": (
                        _format_rev_label(
                            rev.get("rev_no"),
                            rev.get("rev_let") or "",
                            rev_let_flag,
                        )
                        if rev
                        else ""
                    ),
                    "dis_plan_date": (rev.get("dis_plan_date") if rev else None),
                    "dis_act_date": (rev.get("dis_act_date") if rev else None),
                    "rec_plan_date": (rev.get("rec_plan_date") if rev else None),
                    "rec_act_date": (rev.get("rec_act_date") if rev else None),
                    "int_status": _int_status_export_label(rev),
                    "ext_status": ((rev.get("ext_status_label") or "") if rev else ""),
                    "_row_fill": _row_highlight_hex(rev),
                }
            )
    return rows


_SITUAZIONE_VERTICALE_PDF_COLUMNS = [
    ("Item", "item_no", False),
    ("B&R Doc", "vendor_doc", False),
    ("Client Doc N°", "client_doc_no", False),
    ("Contractor Doc N°", "contractor_doc_no", False),
    ("Client Doc Class", "client_doc_class", False),
    ("Title", "doc_title", False),
    ("Department", "department", False),
    ("Penalty", "penalty", False),
    ("Payment", "payment", False),
    ("Rev.", "rev_label", False),
    # Same labels/order as orizzontale Planning + Actual groups.
    ("Submission date", "dis_plan_date", True),
    ("Receipt date", "rec_plan_date", True),
    ("Dispatch", "dis_act_date", True),
    ("Received", "rec_act_date", True),
    ("Internal status", "int_status", False),
    ("Client response", "ext_status", False),
]

_PLAN_ACT_GROUP_KEYS = {
    "dis_plan_date": "Planning",
    "rec_plan_date": "Planning",
    "dis_act_date": "Actual",
    "rec_act_date": "Actual",
}


def genera_situazione_documenti_pdf(
    testata,
    documenti=None,
    revisioni_by_doc=None,
    rev_let_flag=False,
    vista="orizzontale",
):
    """
    Generate a Situazione documenti PDF (Document Status header + table).

    Args:
        testata: dict with keys client, po_no, job, job_detail,
            delivery_date, delivery_term, requisition (Bid No.;
            ISO date strings accepted for dates).
        documenti: list of serialized documenti (from list_situazione).
        revisioni_by_doc: map documento_id -> list of serialized revisioni.
        rev_let_flag: whether revision headers use letters.
        vista: 'orizzontale' | 'verticale' — selects table layout.

    Returns:
        bytes — the PDF content
    """
    docs = list(documenti or [])
    rev_map = revisioni_by_doc or {}

    if vista == "verticale":
        rows = _situazione_verticale_flat_rows(docs, rev_map, bool(rev_let_flag))
        return genera_planned_docs_pdf(
            testata or {},
            rows,
            columns=_SITUAZIONE_VERTICALE_PDF_COLUMNS,
            include_status=True,
            omit_empty_columns=True,
            grouped_plan_actual_headers=True,
        )

    active_fixed = _active_fixed_doc_columns(docs)
    max_revs = 1
    for doc in docs:
        max_revs = max(max_revs, len(_revs_for_doc(rev_map, doc.get("id"))))

    report_date_str = _fmt_dd_mm_yyyy(date.today())
    page_w_mm = _situazione_page_width_mm(max_revs, active_fixed)
    pdf = SituazioneDocumentiPDF(page_width_mm=page_w_mm)

    meta = _situazione_table_meta(docs, rev_map, bool(rev_let_flag), page_w_mm)
    # Header left/right = shared band with the table (STATUS grows when table is wide).
    band_x0 = meta["band_x0"]
    band_w = meta["band_w"]
    pdf._sit_table_meta = meta
    pdf._sit_testata = testata or {}
    pdf._sit_report_date = report_date_str
    pdf._sit_include_status = True
    pdf._sit_draw_col_headers = True
    pdf._sit_header_left_pt = band_x0 / _PT
    pdf._sit_header_right_pt = (band_x0 + band_w) / _PT

    pdf.add_page()  # draws Document Status + column headers via header()
    _build_situazione_table(pdf, docs, rev_map, bool(rev_let_flag))
    return bytes(pdf.output())


def _planned_col_has_values(key: str, is_date: bool, documenti: list) -> bool:
    """True if at least one document has a non-empty value for ``key``."""
    for doc in documenti or []:
        raw = doc.get(key)
        if is_date:
            if raw:
                return True
            continue
        if key == "latest_rev_display":
            if raw and raw != "\u2014":
                return True
            continue
        if raw is not None and str(raw).strip():
            return True
    return False


def _planned_col_max_len(key: str, is_date: bool, documenti: list) -> int:
    best = 0
    for doc in documenti or []:
        raw = doc.get(key)
        if is_date:
            text = _fmt_dd_mm_yyyy(raw) if raw else ""
        elif key == "latest_rev_display" and (not raw or raw == "\u2014"):
            text = ""
        else:
            text = "" if raw is None else str(raw)
        best = max(best, len(text.strip()))
    return best


def _planned_column_widths_mm(cols: list, docs: list, band_w_mm: float) -> list:
    """Content-aware widths: Title gets space, compact cols (Department…) stay narrow."""
    compact_keys = {
        "item_no",
        "department",
        "penalty",
        "payment",
        "rev_label",
        "latest_rev_display",
    }
    compact_headers = {"Item", "Department", "Penalty", "Payment", "Rev."}
    title_keys = {"doc_title"}
    title_headers = {"Title"}

    weights = []
    for header, key, is_date in cols:
        content_len = _planned_col_max_len(key, is_date, docs)
        if key in title_keys or header in title_headers:
            # Dominant readable column.
            weights.append(float(max(40.0, min(content_len * 0.7 + 8.0, 70.0))))
        elif key in compact_keys or header in compact_headers:
            weights.append(float(max(5.0, min(max(content_len, 3) + 2.0, 9.0))))
        elif is_date:
            weights.append(12.0)
        elif key in ("int_status", "ext_status") or header in (
            "Internal status",
            "Client response",
        ):
            weights.append(float(max(12.0, min(content_len + 2.0, 22.0))))
        else:
            # Doc numbers / class: content only (headers wrap if needed).
            weights.append(float(max(8.0, min(content_len + 2.0, 28.0))))

    total = sum(weights) or 1.0
    return [band_w_mm * (w / total) for w in weights]


def _draw_plan_actual_grouped_headers(pdf, x0, y_pos, cols, widths, *, h1=5.5, h2=5.5):
    """Two-row headers: fixed cols span both rows; Planning/Actual group dates.

    Sub-labels match the orizzontale export (Submission date, Receipt date,
    Dispatch, Received).
    """
    n = len(cols)
    i = 0
    x = x0
    # Row 1: spanning fixed + group labels
    while i < n:
        _header, key, _is_date = cols[i]
        group = _PLAN_ACT_GROUP_KEYS.get(key)
        if not group:
            _draw_mm_cell(
                pdf,
                x,
                y_pos,
                widths[i],
                h1 + h2,
                _header,
                bold=True,
                align="C",
                font_size=6.0,
            )
            x += widths[i]
            i += 1
            continue
        # Contiguous columns sharing the same group label.
        j = i
        group_w = 0.0
        while j < n and _PLAN_ACT_GROUP_KEYS.get(cols[j][1]) == group:
            group_w += widths[j]
            j += 1
        _draw_mm_cell(
            pdf,
            x,
            y_pos,
            group_w,
            h1,
            group,
            bold=True,
            align="C",
            font_size=6.5,
        )
        x += group_w
        i = j

    # Row 2: sub-labels only under Planning / Actual
    y2 = y_pos + h1
    x = x0
    for (header, key, _is_date), w in zip(cols, widths):
        if key in _PLAN_ACT_GROUP_KEYS:
            _draw_mm_cell(
                pdf,
                x,
                y2,
                w,
                h2,
                header,
                bold=True,
                align="C",
                font_size=5.5,
            )
        x += w

    return y_pos + h1 + h2


def genera_planned_docs_pdf(
    testata,
    docs,
    *,
    columns,
    include_status=False,
    omit_empty_columns=False,
    grouped_plan_actual_headers=False,
):
    """PDF with Document Status header (optionally without STATUS) + flat table.

    Table styling matches the situazione orizzontale export (light borders,
    white header cells, centered labels). Planned date columns render overdue
    values in red.

    Args:
        testata: serialized testata dict.
        docs: list of document dicts (same shape as list_documenti items).
        columns: list of ``(header, key, is_date)`` tuples.
        include_status: when False, omit the STATUS legend column.
        omit_empty_columns: when True, drop columns with no values in ``docs``.
        grouped_plan_actual_headers: when True, draw Planning/Actual macro
            headers above date columns (situazione verticale).

    Returns:
        bytes — the PDF content
    """
    cols = list(columns or [])
    if not cols:
        cols = [("B&R Doc", "vendor_doc", False)]
    if omit_empty_columns:
        kept = [
            (header, key, is_date)
            for header, key, is_date in cols
            if _planned_col_has_values(key, is_date, docs)
        ]
        if kept:
            cols = kept

    use_groups = bool(grouped_plan_actual_headers) and any(
        key in _PLAN_ACT_GROUP_KEYS for _h, key, _d in cols
    )

    # Band width: natural header content width (no STATUS) or full reference.
    if include_status:
        header_w_pt = _HEADER_NATURAL_WIDTH_PT
    else:
        header_w_pt = _H_OFF_STATUS
    band_w_mm = max(_A3_LANDSCAPE_W - 2 * _TABLE_MARGIN_MM, header_w_pt * _PT)
    page_w_mm = band_w_mm + 2 * _TABLE_MARGIN_MM

    widths = _planned_column_widths_mm(cols, docs or [], band_w_mm)

    pdf = SituazioneDocumentiPDF(page_width_mm=page_w_mm)
    pdf._sit_testata = testata or {}
    pdf._sit_report_date = _fmt_dd_mm_yyyy(date.today())
    pdf._sit_include_status = bool(include_status)
    pdf._sit_draw_col_headers = False
    pdf._sit_table_meta = None
    pdf._sit_header_left_pt = _TABLE_MARGIN_MM / _PT
    pdf._sit_header_right_pt = (_TABLE_MARGIN_MM + band_w_mm) / _PT

    pdf.add_page()

    x0 = _TABLE_MARGIN_MM
    # Flush under Document Status bottom rule (same as situazione).
    y = _pt(_HEADER_BOTTOM_PT)
    pdf.set_y(y)
    row_h = 5.2
    header_h = 5.5

    def _draw_header_row(y_pos):
        if use_groups:
            return _draw_plan_actual_grouped_headers(
                pdf,
                x0,
                y_pos,
                cols,
                widths,
                h1=header_h,
                h2=header_h,
            )
        x = x0
        for (header, _key, _is_date), w in zip(cols, widths):
            _draw_mm_cell(
                pdf,
                x,
                y_pos,
                w,
                header_h,
                header,
                bold=True,
                align="C",
                font_size=6.0,
            )
            x += w
        return y_pos + header_h

    y = _draw_header_row(y)

    def _cell_value(doc, key, is_date):
        raw = doc.get(key)
        if is_date:
            return _fmt_dd_mm_yyyy(raw) if raw else ""
        if key == "latest_rev_display" and (not raw or raw == "\u2014"):
            return ""
        return "" if raw is None else str(raw)

    page_bottom = _A3_LANDSCAPE_H - _TABLE_MARGIN_MM
    for doc in docs or []:
        if y + row_h > page_bottom:
            pdf.add_page()
            y = _pt(_HEADER_BOTTOM_PT)
            pdf.set_y(y)
            y = _draw_header_row(y)

        x = x0
        row_fill = _tint_rgb(doc.get("_row_fill") or "")
        for (_header, key, is_date), w in zip(cols, widths):
            raw = doc.get(key)
            text = _cell_value(doc, key, is_date)
            # Only planning dates go red when late (not actual emission dates).
            is_plan = key in ("latest_dis_plan_date", "latest_rec_plan_date")
            overdue = bool(is_plan and text and _is_iso_overdue(raw))
            _draw_mm_cell(
                pdf,
                x,
                y,
                w,
                row_h,
                text,
                bold=overdue,
                align="C" if w <= 28 else "L",
                fill_rgb=row_fill,
                text_rgb=(180, 0, 0) if overdue else (0, 0, 0),
                font_size=6.0,
            )
            x += w
        y += row_h

    return bytes(pdf.output())
