"""
Trasmittal PDF generation using fpdf2.
"""

from pathlib import Path
from fpdf import FPDF, FontFace
from fpdf.enums import TableBordersLayout


BASE_DIR = Path(__file__).resolve().parent.parent
LOGO_PATH = BASE_DIR / 'static' / 'logo.jpg'

# Column layout: Job, Item No, B&R Doc, Doc. Title, Rev. No, Rev. Let., Req. By
COL_WIDTHS = [15, 20, 30, 65, 15, 15, 30]
COL_HEADERS = ['Job', 'Item No', 'B&R Doc', 'Doc. Title', 'Rev. No', 'Rev. Let.', 'Req. By']


class TrasmittalPDF(FPDF):
    def __init__(self, testata, address, date_str):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.testata = testata
        self.address = address
        self.date_str = date_str
        self.set_margins(left=15, top=10, right=15)
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        if LOGO_PATH.exists():
            self.image(str(LOGO_PATH), x=15, y=8, w=50)
        self.set_y(34)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 7)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f'Pagina {self.page_no()}/{{nb}}', align='C')
        self.set_text_color(0, 0, 0)


def _build_address_block(pdf, address):
    """Render the recipient address block on the right side."""
    pdf.set_font('Helvetica', 'B', 9)
    if address.get('consignee'):
        pdf.cell(0, 5, address['consignee'], new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 9)
    if address.get('attn'):
        pdf.cell(0, 5, f"Att.ne: {address['attn']}", new_x='LMARGIN', new_y='NEXT')
    if address.get('address'):
        pdf.cell(0, 5, address['address'], new_x='LMARGIN', new_y='NEXT')
    line_parts = [p for p in [address.get('zip_code', ''), address.get('city', '')] if p]
    if line_parts:
        pdf.cell(0, 5, ' '.join(line_parts), new_x='LMARGIN', new_y='NEXT')
    if address.get('country'):
        pdf.cell(0, 5, address['country'], new_x='LMARGIN', new_y='NEXT')
    if address.get('ph_no'):
        pdf.cell(0, 5, f"Tel: {address['ph_no']}", new_x='LMARGIN', new_y='NEXT')
    pdf.ln(6)


def _build_letter_header(pdf, testata, date_str):
    label_w = 30
    rows = [
        ('Our Ref:', testata.get('job', '')),
        ('Your Ref:', testata.get('po_no', '')),
        ('Subject:', testata.get('job_detail', '')),
        ('Date:', date_str),
    ]
    for label, value in rows:
        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(label_w, 5, label)  # default new_x=RIGHT, new_y=TOP
        pdf.set_font('Helvetica', '', 9)
        pdf.cell(0, 5, value, new_x='LMARGIN', new_y='NEXT')
    pdf.ln(8)


def _build_doc_table(pdf, documents):
    pdf.set_font('Helvetica', '', 7)
    headings_style = FontFace(emphasis='BOLD', fill_color=(210, 210, 210))
    with pdf.table(
        col_widths=tuple(COL_WIDTHS),
        first_row_as_headings=True,
        headings_style=headings_style,
        borders_layout=TableBordersLayout.ALL,
        text_align='LEFT',
        line_height=int(pdf.font_size * 2.8),
    ) as table:
        header_row = table.row()
        for col in COL_HEADERS:
            header_row.cell(col)
        for doc in documents:
            row = table.row()
            row.cell(str(doc.get('job', '')))
            row.cell(str(doc.get('item_no', '')))
            row.cell(str(doc.get('vendor_doc', '')))
            row.cell(str(doc.get('doc_title', '')))
            row.cell(str(doc.get('rev_no', '')))
            row.cell(str(doc.get('rev_let', '')))
            row.cell(str(doc.get('rec_plan_date', '')))


def genera_trasmittal_pdf(testata, addresses, documents, date_str):
    """
    Generate a trasmittal PDF and return the raw bytes.

    Args:
        testata: dict with keys job, po_no, job_detail, client, ...
        addresses: list of dicts with keys consignee, address, zip_code, city, country, attn, ph_no
        documents: list of dicts with keys job, item_no, vendor_doc, doc_title, rev_no, rev_let, rec_plan_date
        date_str: formatted date string (e.g. '2025-01-15')

    Returns:
        bytes — the PDF content
    """
    # Generate one PDF for the first address (or no address block if empty)
    first_addr = addresses[0] if addresses else {}

    pdf = TrasmittalPDF(testata, first_addr, date_str)
    pdf.alias_nb_pages()
    pdf.add_page()

    # Address block
    if first_addr:
        _build_address_block(pdf, first_addr)

    # Letter header
    _build_letter_header(pdf, testata, date_str)

    # Document table
    _build_doc_table(pdf, documents)

    return bytes(pdf.output())
