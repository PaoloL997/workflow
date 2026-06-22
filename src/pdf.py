"""
Trasmittal PDF generation using fpdf2.
"""

from datetime import date as _date
from pathlib import Path

from fpdf import FPDF, FontFace
from fpdf.enums import TableBordersLayout

BASE_DIR = Path(__file__).resolve().parent.parent
LOGO_PATH = BASE_DIR / "core" / "static" / "core" / "img" / "trasmittal_logo.JPG"

# Column layouts per doc_id_mode (mm): ITEM | … | REV. | DOCUMENT | REQUIRED BY
_TABLE_LAYOUTS = {
    "vendor": {
        "headers": ["ITEM", "VENDOR DOC.", "REV.", "DOCUMENT", "REQUIRED BY"],
        "widths": [20, 45, 12, 83, 20],
    },
    "client": {
        "headers": ["ITEM", "CLIENT DOC.", "REV.", "DOCUMENT", "REQUIRED BY"],
        "widths": [20, 45, 12, 83, 20],
    },
    "both": {
        "headers": ["ITEM", "CLIENT DOC.", "VENDOR DOC.", "REV.", "DOCUMENT", "REQUIRED BY"],
        "widths": [18, 32, 32, 10, 68, 20],
    },
}

VALID_DOC_ID_MODES = frozenset(_TABLE_LAYOUTS)

DELIVERY_OPTIONS = [
    ("attached", "In allegato", "Attached"),
    ("mail", "Per pacco postale", "By mail"),
    ("courier", "Per Corriere", "By Courier"),
    ("brevi_manu", "Brevi manu a \u00bd", "Direct_through Mr."),
]


class TrasmittalPDF(FPDF):
    def __init__(self, testata, address, date_str, our_ref, city, delivery_mode, brevi_manu_name):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.testata = testata
        self.address = address
        self.date_str = date_str
        self.our_ref = our_ref
        self.city = city
        self.delivery_mode = delivery_mode
        self.brevi_manu_name = brevi_manu_name
        self.set_margins(left=15, top=10, right=15)
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        if LOGO_PATH.exists():
            self.image(str(LOGO_PATH), x=15, y=8, w=70)
        self.set_y(34)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Pagina {self.page_no()}/{{nb}}", align="C")
        self.set_text_color(0, 0, 0)


def _fmt_date(date_str, city):
    """Convert ISO date string to 'CITY, DD/MM/YYYY' format."""
    try:
        d = _date.fromisoformat(date_str)
        formatted = d.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        formatted = date_str
    if city:
        return f"{city}, {formatted}"
    return formatted


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
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(left_w, line_h, label)
        else:
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(label_w, line_h, label)
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(left_w - label_w, line_h, value)
        y_left += line_h + 1

    # ── RIGHT COLUMN: bordered address box ───────────────────────────────────
    box_padding = 3
    # Estimate height: count non-empty address fields + labels
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

    box_h = max((len(addr_lines) * (line_h + 1)) + box_padding * 2, 30)

    # Draw box border
    pdf.set_draw_color(0, 0, 0)
    pdf.rect(right_x, y_start, right_w, box_h)

    # Fill address content inside box
    y_right = y_start + box_padding
    for label, value in addr_lines:
        pdf.set_xy(right_x + box_padding, y_right)
        if label:
            pdf.set_font("Helvetica", "B", 9)
            lbl_w = pdf.get_string_width(label) + 2
            pdf.cell(lbl_w, line_h, label)
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(right_w - lbl_w - box_padding * 2, line_h, value, ln=False)
        else:
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(right_w - box_padding * 2, line_h, value)
        y_right += line_h + 1

    y_after = max(y_left, y_start + box_h) + 6
    pdf.set_y(y_after)


def _build_delivery_checkboxes(pdf, delivery_mode, brevi_manu_name):
    """Render the 4 delivery mode checkboxes in a horizontal row."""
    pdf.set_font("Helvetica", "", 8)
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
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_xy(x + 0.3, y + (line_h - box_size) / 2 - 0.3)
            pdf.cell(box_size, box_size + 1, "X", align="C")
            pdf.set_font("Helvetica", "", 8)

        # Label text (Italian / English)
        label_x = x + box_size + 2
        if key == "brevi_manu" and checked and brevi_manu_name:
            full_en = f"{en_label} {brevi_manu_name}"
        else:
            full_en = en_label

        pdf.set_xy(label_x, y)
        pdf.cell(col_w - box_size - 2, line_h / 2, it_label, ln=False)
        pdf.set_xy(label_x, y + line_h / 2)
        pdf.set_font("Helvetica", "I", 7)
        pdf.cell(col_w - box_size - 2, line_h / 2, full_en, ln=False)
        pdf.set_font("Helvetica", "", 8)

    pdf.ln(line_h + 4)


def _cell_style_for_text(text, col_width_mm):
    """Pick a smaller font when cell content is long for the column width."""
    if not text:
        return None
    max_chars_per_line = max(len(line) for line in text.split("\n"))
    # Rough heuristic: ~1.6mm per char at 8pt Helvetica
    capacity = max(8, int(col_width_mm / 1.5))
    if max_chars_per_line > capacity * 1.4:
        return FontFace(size_pt=6)
    if max_chars_per_line > capacity:
        return FontFace(size_pt=7)
    return None


def _doc_id_values(doc, mode):
    vendor = (doc.get("vendor_doc") or "").strip()
    client = (doc.get("client_doc_no") or "").strip()
    if mode == "vendor":
        return [vendor]
    if mode == "client":
        return [client]
    return [client, vendor]


def _build_doc_table(pdf, documents, time_cli_doc_rev, doc_id_mode="both"):
    """Render the documents table."""
    mode = doc_id_mode if doc_id_mode in VALID_DOC_ID_MODES else "both"
    layout = _TABLE_LAYOUTS[mode]
    headers = layout["headers"]
    widths = layout["widths"]
    required_by = f"{time_cli_doc_rev} DAYS" if time_cli_doc_rev else ""

    # Left-align ID and title columns; keep ITEM/REV centered
    aligns = []
    for h in headers:
        if h in ("CLIENT DOC.", "VENDOR DOC.", "DOCUMENT"):
            aligns.append("LEFT")
        else:
            aligns.append("CENTER")

    pdf.set_font("Helvetica", "", 8)
    headings_style = FontFace(emphasis="BOLD", fill_color=(210, 210, 210))
    heading_size = FontFace(emphasis="BOLD", fill_color=(210, 210, 210), size_pt=7)
    with pdf.table(
        col_widths=tuple(widths),
        first_row_as_headings=True,
        headings_style=headings_style,
        borders_layout=TableBordersLayout.ALL,
        text_align=tuple(aligns),
        line_height=int(pdf.font_size * 2.6),
        padding=(1.2, 1.5),
        wrapmode="CHAR",
    ) as table:
        header_row = table.row()
        for col, w in zip(headers, widths):
            style = heading_size if len(col) > 10 else None
            header_row.cell(col, style=style)

        id_widths = [w for h, w in zip(headers, widths) if h in ("CLIENT DOC.", "VENDOR DOC.")]
        title_width = next(w for h, w in zip(headers, widths) if h == "DOCUMENT")

        for doc in documents:
            id_values = _doc_id_values(doc, mode)
            title = str(doc.get("doc_title", "") or "").strip()
            title_style = _cell_style_for_text(title, title_width)

            row = table.row()
            row.cell(str(doc.get("item_no", "")))

            if mode == "both":
                client_val, vendor_val = id_values
                row.cell(
                    client_val,
                    style=_cell_style_for_text(client_val, id_widths[0]),
                )
                row.cell(
                    vendor_val,
                    style=_cell_style_for_text(vendor_val, id_widths[1]),
                )
            else:
                id_val = id_values[0]
                row.cell(
                    id_val,
                    style=_cell_style_for_text(id_val, id_widths[0] if id_widths else widths[1]),
                )

            row.cell(str(doc.get("rev_no", "")))
            row.cell(title, style=title_style)
            row.cell(required_by)


def genera_trasmittal_pdf(
    testata,
    addresses,
    documents,
    date_str,
    our_ref="",
    city="",
    delivery_mode="attached",
    brevi_manu_name="",
    doc_id_mode="both",
):
    """
    Generate a trasmittal PDF and return the raw bytes.

    Args:
        testata: dict with keys job, po_no, job_detail, client, time_cli_doc_rev
        addresses: list of dicts with keys consignee, address, zip_code, city, country, attn, ph_no
        documents: list of dicts with keys item_no, vendor_doc, client_doc_no, doc_title, rev_no
        date_str: ISO date string (e.g. '2025-01-15')
        our_ref: trasmittal reference number (user-provided)
        city: city name for the date header (e.g. 'Schio')
        delivery_mode: one of 'attached', 'mail', 'courier', 'brevi_manu'
        brevi_manu_name: name after "Mr." when delivery_mode is 'brevi_manu'
        doc_id_mode: 'vendor' | 'client' | 'both' — which document IDs to include in the table

    Returns:
        bytes — the PDF content
    """
    first_addr = addresses[0] if addresses else {}
    time_cli_doc_rev = testata.get("time_cli_doc_rev")

    pdf = TrasmittalPDF(
        testata,
        first_addr,
        date_str,
        our_ref=our_ref,
        city=city,
        delivery_mode=delivery_mode,
        brevi_manu_name=brevi_manu_name,
    )
    pdf.alias_nb_pages()
    pdf.add_page()

    # Two-column header: refs (left) + address box (right)
    _build_two_column_header(pdf, testata, date_str, our_ref, city, first_addr)

    # Intro text
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, "Please find herewith the following documents", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Delivery checkboxes
    _build_delivery_checkboxes(pdf, delivery_mode, brevi_manu_name)

    # Document table
    _build_doc_table(pdf, documents, time_cli_doc_rev, doc_id_mode=doc_id_mode)

    return bytes(pdf.output())
