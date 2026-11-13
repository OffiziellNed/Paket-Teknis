"""PDF laporan per entitas – meniru desain Excel lama (samples/Contoh_Cetak_Okt_2026.pdf).
Kolom jenis jasa & no faktur tidak dicetak; semua sel bergaris penuh; baris kosong PPh 21 freelance disembunyikan."""
from __future__ import annotations

import io
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

from .report import Report
from .rules import tanggal_indo

HEADER_BG = colors.HexColor('#9BC2E6')
TOTAL_BG = colors.HexColor('#DDEBF7')
GREY_BG = colors.HexColor('#AEAAAA')
YELLOW = colors.HexColor('#FFFF00')
FONT, BOLD, SIZE = 'Helvetica', 'Helvetica-Bold', 8
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def fmt_num(v) -> str:
    v = int(v)
    return '-' if v == 0 else f'{v:,}'


def fmt_date(d) -> str:
    return f'{d.day:02d}-{MON[d.month - 1]}-{d.year % 100:02d}'


def clip(s, width, font=FONT, size=SIZE) -> str:
    s = str(s or '')
    pad = 4
    while s and stringWidth(s, font, size) > width - pad:
        s = s[:-1]
    return s


# Lebar kolom Excel (karakter) -> proporsi
QDI_COLS = [('No', 6.0), ('Date', 12.5), ('Invoice', 42.0), ('Lawan Transaksi', 38.0), ('NPWP', 24.0),
            ('Rp', 3.5), ('DPP', 14.63), ('Rp', 3.5), ('Ps 23 / Ps 4 (2)', 13.5), ('Masa', 8.75), ('No Bupot', 13.38)]
QKI_COLS = [('No', 4), ('Date', 9.5), ('Invoice', 26), ('Vendor', 25), ('NPWP', 15), ('Description', 15),
            ('DPP', 15), ('Rp', 3), ('Art. 23', 15), ('Masa', 9), ('No Bupot', 13)]


def _widths(cols, total):
    s = sum(w for _, w in cols)
    return [total * w / s for _, w in cols]


def _table(rep: Report, avail_w: float):
    qdi = rep.style == 'UNIFIKASI'
    cols = QDI_COLS if qdi else QKI_COLS
    W = _widths(cols, avail_w)
    data, st = [], [('FONT', (0, 0), (-1, -1), FONT, SIZE), ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 1.5),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2), ('LEFTPADDING', (0, 0), (-1, -1), 2),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 2)]
    hdr = [c for c, _ in cols]
    if qdi:
        hdr = ['No', 'Date', 'Invoice', 'Lawan Transaksi', 'NPWP', 'DPP', '', 'Ps 23 / Ps 4 (2)', '', 'Masa', 'No Bupot']
        st += [('SPAN', (5, 0), (6, 0)), ('SPAN', (7, 0), (8, 0))]
    else:
        hdr = ['No', 'Date', 'Invoice', 'Vendor', 'NPWP', 'Description', 'DPP', 'Art. 23', '', 'Masa', 'No Bupot']
        st += [('SPAN', (7, 0), (8, 0))]
    data.append(hdr)
    st += [('BACKGROUND', (0, 0), (-1, 0), HEADER_BG), ('FONT', (0, 0), (-1, 0), BOLD, SIZE),
           ('ALIGN', (0, 0), (-1, 0), 'CENTER')]
    m = str(rep.month)
    for ln in rep.lines:
        i = len(data)
        k = ln['kind']
        if k == 'item':
            r = ln['row']
            final = r['section'] == 'FINAL_4_2'
            if qdi:
                data.append([str(ln['no']), fmt_date(r['invoice_date']), clip(r['invoice_no'], W[2]),
                             clip(r['name'], W[3]), clip(r['npwp_display'], W[4]), 'Rp', fmt_num(r['dpp']),
                             'Rp' if final else '', fmt_num(ln['pph_rp']), m, r.get('bupot_no') or ''])
            else:
                data.append([str(ln['no']), fmt_date(r['invoice_date']), clip(r['invoice_no'], W[2]),
                             clip(r['name'], W[3]), clip(r['npwp_display'], W[4]),
                             clip(r.get('description') or '', W[5]), fmt_num(r['dpp']), '', fmt_num(ln['pph_rp']), m,
                             r.get('bupot_no') or ''])
                st += [('ALIGN', (3, i), (3, i), 'CENTER'), ('ALIGN', (5, i), (5, i), 'CENTER')]
            st += [('ALIGN', (0, i), (1, i), 'CENTER'), ('ALIGN', (6, i), (6, i), 'RIGHT'),
                   ('ALIGN', (8, i), (8, i), 'RIGHT'), ('ALIGN', (9, i), (9, i), 'CENTER')]
        elif k in ('section', 'section_grey'):
            row = [''] * 11
            row[9] = m
            if qdi and ln.get('offset') or k == 'section_grey':
                row[3] = ln['label']
                st += [('SPAN', (3, i), (4, i)), ('SPAN', (5, i), (6, i)), ('SPAN', (7, i), (8, i))]
            else:
                row[0] = ln['label']
                st += [('SPAN', (0, i), (6 if qdi else 8, i))]
            st += [('FONT', (0, i), (8, i), BOLD, SIZE), ('ALIGN', (0, i), (-1, i), 'CENTER')]
            if k == 'section_grey':
                st += [('BACKGROUND', (0, i), (8, i), GREY_BG)]
            data.append(row)
        elif k in ('total', 'total_grey'):
            row = [''] * 11
            row[9] = m
            if qdi:
                row[1] = ln['label']
                if ln.get('rp'):
                    row[7], row[8] = 'Rp', fmt_num(ln['amount'])
                    st += [('SPAN', (1, i), (6, i))]
                else:
                    row[7] = fmt_num(ln['amount'])
                    st += [('SPAN', (1, i), (6, i)), ('SPAN', (7, i), (8, i))]
                st += [('BACKGROUND', (0, i), (8, i), GREY_BG if k == 'total_grey' else TOTAL_BG)]
            else:
                row[0], row[7], row[8] = ln['label'], 'Rp', fmt_num(ln['amount'])
                st += [('SPAN', (0, i), (6, i))]
            st += [('FONT', (0, i), (8, i), BOLD, SIZE), ('ALIGN', (0, i), (6, i), 'CENTER'),
                   ('ALIGN', (7, i), (8, i), 'RIGHT'), ('ALIGN', (9, i), (9, i), 'CENTER')]
            if ln.get('rp') or not qdi:
                st += [('ALIGN', (7, i), (7, i), 'LEFT')]
        elif k in ('grand', 'grand_yellow'):
            row = [''] * 11
            row[0], row[7], row[8], row[9] = ln['label'], 'Rp', fmt_num(ln['amount']), m
            st += [('SPAN', (0, i), (6, i)), ('FONT', (0, i), (8, i), BOLD, SIZE), ('ALIGN', (0, i), (6, i), 'CENTER'),
                   ('ALIGN', (8, i), (8, i), 'RIGHT'), ('ALIGN', (9, i), (9, i), 'CENTER')]
            if k == 'grand_yellow':
                st += [('BACKGROUND', (0, i), (8, i), YELLOW)]
            data.append(row)
            continue
        if k in ('total', 'total_grey'):
            data.append(row)
    t = Table(data, colWidths=W, repeatRows=1)
    t.setStyle(TableStyle(st))
    return t


def _signature_table(sig: dict, avail_w: float):
    """sig: dict city, date, blocks=[{label, name, title, image, stamp}] (1–4 blok)."""
    blocks = sig.get('blocks') or []
    n = max(1, len(blocks))
    w = avail_w / n
    ps = ParagraphStyle('c', fontName=FONT, fontSize=SIZE + 1, alignment=1, leading=11)
    pb = ParagraphStyle('b', parent=ps, fontName=BOLD)
    place = f"{sig.get('city') or 'Jakarta'}, {tanggal_indo(sig['date'])}"
    rows = [[Paragraph(place, ps)] + [''] * (n - 1), [Paragraph(b['label'] + ',', ps) for b in blocks], [], [], []]
    img_row = []
    for b in blocks:
        cell = ''
        imgs = []
        for key in ('image', 'stamp'):
            p = b.get(key)
            if isinstance(p, (bytes, bytearray)):
                imgs.append(Image(io.BytesIO(p), width=30 * mm, height=15 * mm, kind='proportional'))
            elif p and os.path.exists(p):
                imgs.append(Image(p, width=30 * mm, height=15 * mm, kind='proportional'))
        if len(imgs) == 1:
            cell = imgs[0]
        elif imgs:
            cell = Table([imgs], colWidths=[32 * mm] * len(imgs))
        img_row.append(cell)
    rows[2] = img_row
    rows[3] = [Paragraph(b.get('name') or '', pb) for b in blocks]
    rows[4] = [Paragraph(b.get('title') or '', ps) for b in blocks]
    t = Table(rows, colWidths=[w] * n, rowHeights=[12, 12, 52, 12, 12])
    t.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    return t


def render_pdf(rep: Report, sig: dict, draft: bool = False) -> bytes:
    buf = io.BytesIO()
    page = landscape(A4)
    margin = 10 * mm
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=margin, rightMargin=margin, topMargin=12 * mm,
                            bottomMargin=10 * mm, title=f'{rep.title_lines[0]} {rep.masa}', author='Rekap PPh Qoin')
    avail = page[0] - 2 * margin
    story = []
    if rep.style == 'UNIFIKASI':
        tst = ParagraphStyle('t', fontName=BOLD, fontSize=10, alignment=1, leading=13)
    else:
        tst = ParagraphStyle('t', fontName=BOLD, fontSize=9, alignment=0, leading=12)
        story.append(Spacer(1, 6 * mm))
    for i, line in enumerate(rep.title_lines):
        st = tst if not (rep.style != 'UNIFIKASI' and i == 0) else ParagraphStyle('t0', parent=tst, fontSize=10)
        story.append(Paragraph(line, st))
    story.append(Spacer(1, 3 * mm if rep.style == 'UNIFIKASI' else 5 * mm))
    story.append(_table(rep, avail))
    story.append(Spacer(1, 10 * mm))
    story.append(_signature_table(sig, avail * 0.85))

    def on_page(c, d):
        if draft:
            c.saveState()
            c.setFont(BOLD, 90)
            c.setFillColor(colors.Color(1, 0, 0, alpha=0.12))
            c.translate(page[0] / 2, page[1] / 2)
            c.rotate(25)
            c.drawCentredString(0, 0, 'DRAFT')
            c.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
