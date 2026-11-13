"""Data sheet Excel per entitas per masa dengan struktur kolom yang sama seperti sheet
'PPH 23 QDI 2026' (QDI) dan 'PPh 23 LPI 2024 - 26' (QKI) di workbook sumber. Rumus PPh/total tetap berupa formula."""
from __future__ import annotations

import io

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .report import Report
from .rules import SECTIONS, to_dec

QDI_HDR = ['No', 'Date', 'Invoice', 'Lawan Transaksi', 'NPWP ', 'DPP', 'Ps 23 / Ps 4 (2)', 'Masa', 'No Bupot',
           'Kirim Bukti Potong', 'Tgl Bayar/Lapor', 'Kirim bukpot ', 'Tanggal email bukpot', 'Notes',
           'Jenis Jasa (Objek PPh)', 'No Faktur Pajak']
QDI_W = [6.51, 13.38, 44.87, 40.12, 20, 18.13, 17, 8.75, 13.38, 15.62, 13.5, 13.62, 16.25, 34, 48, 22]
QKI_HDR = ['No', 'Date', 'Invoice', 'Vendor', 'NPWP ', 'Description', None, 'DPP', 'Art. 23', 'Masa', 'No Bupot', 'NTPN',
           'Tgl Bayar', 'Tgl Pemotongan', 'Tgl Lapor', 'Kirim bukpot ', 'Tgl Kirim', 'Notes']
QKI_W = [5, 11, 30, 30, 20, 18, 3, 16, 14, 7, 13, 20, 12, 14, 12, 12, 12, 40]
RP = '_-"Rp"* #,##0_-;"-Rp"* #,##0_-;_-"Rp"* \\-??_-;_-@_-'
NUM = '#,##0'
DATE = '[$-409]dd\\-mmm\\-yy;@'
THIN = Side(style='thin')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
B = Font(bold=True)
FILL_H = PatternFill('solid', fgColor='9BC2E6')
FILL_T = PatternFill('solid', fgColor='DDEBF7')
FILL_G = PatternFill('solid', fgColor='AEAAAA')
FILL_Y = PatternFill('solid', fgColor='FFFF00')


def _pct(rate) -> str:
    v = to_dec(rate) * 100
    return (format(v.normalize(), 'f') if v != v.to_integral() else str(int(v))) + '%'


def render_xlsx(rep: Report, extra_rows: list[dict] | None = None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    qdi = rep.style == 'UNIFIKASI'
    ws.title = (f'PPH 23 {rep.entity_code} {rep.year}' if qdi else f'PPh 23 {rep.entity_code} {rep.year}')[:31]
    hdr, widths = (QDI_HDR, QDI_W) if qdi else (QKI_HDR, QKI_W)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for i, t in enumerate(rep.title_lines, 1):
        ws.cell(i, 1, t).font = Font(bold=True, size=12)
        if qdi:
            ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=9)
            ws.cell(i, 1).alignment = Alignment(horizontal='center')
    hr = 3 if qdi else 5
    for c, h in enumerate(hdr, 1):
        cell = ws.cell(hr, c, h)
        cell.font, cell.fill, cell.border = B, FILL_H, BORDER
        cell.alignment = Alignment(horizontal='center')
    # kolom: posisi DPP / PPh / masa / bupot
    cD, cP, cM, cBp = (6, 7, 8, 9) if qdi else (8, 9, 10, 11)
    row = hr + 1
    total_rows, prev_item = {}, None
    cur_block = []
    multi_sec = any(l['kind'] == 'section' for l in rep.lines)
    for ln in rep.lines:
        k = ln['kind']
        if k == 'item':
            r = ln['row']
            ws.cell(row, 1, ln['no'] if prev_item is None else f'=A{prev_item}+1')
            ws.cell(row, 2, r['invoice_date']).number_format = DATE
            ws.cell(row, 3, r['invoice_no'])
            ws.cell(row, 4, r['name'])
            ws.cell(row, 5, r['npwp_display'])
            if not qdi:
                ws.cell(row, 6, r.get('description') or '')
            ws.cell(row, cD, float(to_dec(r['dpp']))).number_format = RP if qdi else NUM
            ws.cell(row, cP, f'={get_column_letter(cD)}{row}*{_pct(r["rate"])}').number_format = NUM
            ws.cell(row, cM, rep.month)
            ws.cell(row, cBp, r.get('bupot_no') or None)
            if qdi:
                ws.cell(row, 11, r.get('paid_date'))
                ws.cell(row, 12, r.get('bukpot_sent'))
                ws.cell(row, 13, r.get('bukpot_email_date'))
                ws.cell(row, 14, r.get('notes') or None)
                ws.cell(row, 15, r.get('service_type') or None)
                ws.cell(row, 16, r.get('faktur_no') or None)
            else:
                ws.cell(row, 13, r.get('paid_date'))
                ws.cell(row, 14, r['withholding_date']).number_format = DATE
                ws.cell(row, 16, r.get('bukpot_sent'))
                ws.cell(row, 17, r.get('bukpot_email_date'))
                ws.cell(row, 18, r.get('notes') or (f"Jenis: {r['service_type']}" if r.get('service_type') else None))
            prev_item = row
            cur_block.append(row)
        elif k in ('section', 'section_grey'):
            ws.cell(row, 4 if (ln.get('offset') or k == 'section_grey') else 1, ln['label']).font = B
            if k == 'section_grey':
                for c in range(1, cM):
                    ws.cell(row, c).fill = FILL_G
            if ln['label'] == 'PPh 23 Project QRIS':
                pass  # blok PPh 23 berlanjut hingga total
            else:
                cur_block = []
            ws.cell(row, cM, rep.month)
        elif k in ('total', 'total_grey'):
            ws.cell(row, 2 if qdi else 1, ln['label']).font = B
            col = get_column_letter(cP)
            simple_val = not qdi and (multi_sec or not ln['label'].upper().startswith('PPH 23'))
            ws.cell(row, cP, ln['amount'] if simple_val else (
                f'=SUM({col}{cur_block[0]}:{col}{cur_block[-1]})' if cur_block else 0))
            ws.cell(row, cP).number_format = RP if ln.get('rp') else NUM
            ws.cell(row, cP).font = B
            ws.cell(row, cM, rep.month)
            total_rows[ln['label']] = row
            for c in range(1, cM):
                ws.cell(row, c).fill = FILL_G if k == 'total_grey' else FILL_T
            cur_block = []
        elif k in ('grand', 'grand_yellow'):
            ws.cell(row, 1, ln['label']).font = B
            col = get_column_letter(cP)
            tr = list(total_rows.values())
            if ln['label'].startswith('PPH Unifikasi') and len(tr) >= 2:
                f = f'={col}{tr[0]}+{col}{tr[1]}'
            elif ln['label'].startswith('PPh 21 Bulan') or ln['label'].startswith('PPH 21'):
                f = ln['amount']
            elif qdi:
                f = f'={col}{row - 2}+{col}{row - 1}+{col}{tr[2]}' if len(tr) >= 3 else ln['amount']
            else:
                f = '=' + '+'.join(f'{col}{x}' for x in tr) if tr else ln['amount']
            ws.cell(row, cP, f).number_format = RP
            ws.cell(row, cP).font = B
            ws.cell(row, cM, rep.month)
            if k == 'grand_yellow':
                for c in range(1, cM):
                    ws.cell(row, c).fill = FILL_Y
            total_rows.setdefault(ln['label'], row)
        for c in range(1, len(hdr) + 1):
            ws.cell(row, c).border = BORDER
        row += 1
    ws.freeze_panes = ws.cell(hr + 1, 1)

    # sheet detail (kolom tambahan yang tidak ada di sheet asli: KOP, tgl pemotongan, status)
    d = wb.create_sheet('Detail')
    cols = ['No', 'Section', 'Tanggal Invoice', 'No Invoice', 'Lawan Transaksi', 'NPWP16', 'KOP', 'DPP', 'Tarif',
            'PPh (desimal)', 'PPh (dibulatkan)', 'Tanggal Pemotongan', 'No Faktur Pajak', 'No Bupot', 'Jenis Jasa', 'Notes']
    d.append(cols)
    for c in d[1]:
        c.font, c.fill = B, FILL_H
    for ln in rep.lines:
        if ln['kind'] != 'item':
            continue
        r = ln['row']
        d.append([ln['no'], SECTIONS[r['section']], r['invoice_date'], r['invoice_no'], r['name'], r['npwp16'],
                  r.get('kop'), float(to_dec(r['dpp'])), float(to_dec(r['rate'])), float(ln['pph']), ln['pph_rp'],
                  r['withholding_date'], r.get('faktur_no'), r.get('bupot_no'), r.get('service_type'), r.get('notes')])
    for col, w in zip('ABCDEFGHIJKLMNOP', [5, 20, 12, 40, 40, 18, 11, 16, 7, 14, 14, 12, 20, 13, 40, 40]):
        d.column_dimensions[col].width = w
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
