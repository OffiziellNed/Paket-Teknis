"""Upload massal transaksi dari templates/Template_Bulk_Transaksi_PPh23.xlsx atau CSV dengan header yang sama."""
from __future__ import annotations

import csv
import io
from decimal import Decimal

from .rules import (SECTIONS, default_withholding_date, npwp16, parse_date, parse_tarif, section_code, to_dec)

COLS = ['Entitas', 'Masa (1-12)', 'Tahun', 'Section', 'Tanggal Invoice', 'No Invoice', 'Lawan Transaksi', 'NPWP',
        'Deskripsi', 'Jenis Jasa', 'KOP', 'DPP (Rp)', 'Tarif (%)', 'Tanggal Pemotongan', 'No Faktur Pajak', 'No Bupot',
        'Notes']
REQUIRED = ['Entitas', 'Masa (1-12)', 'Tahun', 'Section', 'Tanggal Invoice', 'No Invoice', 'Lawan Transaksi', 'DPP (Rp)']
PPH21_COLS = ['Entitas', 'Masa (1-12)', 'Tahun', 'Total PPh 21 (Rp)']


def _rows_from_sheet(ws):
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    hdr = [str(h or '').strip() for h in rows[0]]
    out = []
    for n, r in enumerate(rows[1:], start=2):
        if not any(v not in (None, '') for v in r):
            continue
        out.append((n, {h: r[i] for i, h in enumerate(hdr) if h and i < len(r)}))
    return out


def read_file(data: bytes, filename: str):
    """Return (rows_transaksi, rows_pph21); setiap row = (nomor_baris, dict)."""
    if filename.lower().endswith('.csv'):
        text = data.decode('utf-8-sig')
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=',;')
        rdr = csv.DictReader(io.StringIO(text), dialect=dialect)
        return [(n, {k.strip(): v for k, v in r.items() if k}) for n, r in enumerate(rdr, start=2)], []
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    trx = _rows_from_sheet(wb['Transaksi'] if 'Transaksi' in wb.sheetnames else wb.worksheets[0])
    p21 = _rows_from_sheet(wb['PPh21_Bulanan']) if 'PPh21_Bulanan' in wb.sheetnames else []
    return trx, p21


def validate_rows(rows, vendors_by_name: dict, vendors_by_npwp: dict, kops: dict, entities: set,
                  existing_keys: set, locked_periods: set):
    """vendors_by_name: nama.lower() -> vendor dict; kops: kode -> dict(rate, tax_type).
    existing_keys: set (npwp16, invoice_no) yang sudah ada di DB.
    Return list dict: line, status (OK/Peringatan/Error), messages, data (siap disimpan) dan raw."""
    seen, out = set(), []
    for line, raw in rows:
        msgs, err = [], False
        g = lambda k: (raw.get(k) if raw.get(k) is not None else '')
        if str(g('Notes')).upper().startswith('CONTOH'):
            continue
        for k in REQUIRED:
            if str(g(k)).strip() == '':
                msgs.append(f'{k} wajib diisi')
                err = True
        data = {}
        try:
            ent = str(g('Entitas')).strip().upper()
            if ent not in entities:
                raise ValueError(f'Entitas tidak dikenal: {ent}')
            data['entity'] = ent
            data['month'] = int(float(g('Masa (1-12)')))
            data['year'] = int(float(g('Tahun')))
            if not 1 <= data['month'] <= 12:
                raise ValueError('Masa harus 1-12')
            data['section'] = section_code(str(g('Section')))
            data['invoice_date'] = parse_date(g('Tanggal Invoice'))
            data['invoice_no'] = str(g('No Invoice')).strip()
            data['name'] = str(g('Lawan Transaksi')).strip()
            data['dpp'] = to_dec(str(g('DPP (Rp)')).replace(',', '')) if g('DPP (Rp)') != '' else Decimal(0)
        except (ValueError, ArithmeticError) as e:
            msgs.append(str(e))
            err = True
        if not err:
            v = vendors_by_name.get(data['name'].lower())
            np = str(g('NPWP')).strip()
            try:
                data['npwp16'] = npwp16(np) if np else (v['npwp16'] if v else '')
                if np and len(''.join(c for c in np if c.isdigit())) not in (15, 16):
                    raise ValueError('NPWP harus 15 atau 16 digit')
            except ValueError as e:
                msgs.append(str(e))
                err = True
            if not v and data.get('npwp16'):
                v = vendors_by_npwp.get(data['npwp16'])
            if not data.get('npwp16'):
                msgs.append('NPWP kosong dan vendor tidak ada di master')
                err = True
            if v is None:
                msgs.append('Vendor baru (belum ada di master) – akan ditambahkan')
            elif not v.get('withhold_pph23', True) and data['section'] != 'PPH21_FREELANCE':
                msgs.append(f"{v['name']} tidak dipotong PPh 23 (master vendor)")
                err = True
            data['vendor_id'] = v['id'] if v else None
            data['npwp_display'] = np or (v.get('npwp_display') if v else '') or data.get('npwp16', '')
            data['service_type'] = str(g('Jenis Jasa')).strip() or (v.get('default_service') if v else '') or ''
            data['description'] = str(g('Deskripsi')).strip()
            kop = str(g('KOP')).strip() or (v.get('default_kop') if v else '') or ''
            if kop == '28-403-01':
                msgs.append('KOP 28-403-01 ditolak Coretax – gunakan 28-403-02')
                err = True
            elif data['section'] != 'PPH21_FREELANCE':
                if not kop:
                    msgs.append('KOP kosong')
                    err = True
                elif kop not in kops:
                    msgs.append(f'KOP {kop} tidak ada di master KOP')
                    err = True
            data['kop'] = kop or None
            try:
                t = g('Tarif (%)')
                data['rate'] = parse_tarif(t) if str(t).strip() else (
                    kops[kop]['rate'] if kop in kops else (v.get('default_rate') if v else None))
                if data['rate'] is None:
                    raise ValueError('Tarif kosong')
                if kop in kops and to_dec(data['rate']) != to_dec(kops[kop]['rate']):
                    msgs.append(f"Tarif {data['rate'] * 100}% berbeda dengan tarif KOP {kops[kop]['rate'] * 100}%")
            except (ValueError, ArithmeticError) as e:
                msgs.append(str(e))
                err = True
            if data['dpp'] <= 0:
                msgs.append('DPP harus > 0')
                err = True
            try:
                w = parse_date(g('Tanggal Pemotongan'))
                data['withholding_date'] = w or default_withholding_date(data['invoice_date'], data['month'], data['year'])
                wd = data['withholding_date']
                if (wd.year, wd.month) != (data['year'], data['month']):
                    msgs.append('Tanggal pemotongan harus di dalam masa')
                    err = True
            except ValueError as e:
                msgs.append(str(e))
                err = True
            data['faktur_no'] = str(g('No Faktur Pajak')).strip() or None
            data['bupot_no'] = str(g('No Bupot')).strip() or None
            data['notes'] = str(g('Notes')).strip()
            key = (data.get('npwp16'), data['invoice_no'])
            if key in seen:
                msgs.append('Duplikat di file (NPWP + No Invoice sama)')
                err = True
            seen.add(key)
            if key in existing_keys:
                msgs.append('Sudah ada di database (NPWP + No Invoice sama)')
                data['_exists'] = True
            if (data['entity'], data['month'], data['year']) in locked_periods:
                msgs.append('Masa sudah di-approve/terkunci')
                err = True
        status = 'Error' if err else ('Peringatan' if msgs else 'OK')
        out.append(dict(line=line, status=status, messages=msgs, data=data if not err else None,
                        raw={k: (str(v) if v is not None else '') for k, v in raw.items()}))
    return out


def read_pph21(rows):
    out = []
    for line, raw in rows:
        try:
            out.append(dict(entity=str(raw['Entitas']).strip().upper(), month=int(float(raw['Masa (1-12)'])),
                            year=int(float(raw['Tahun'])), total=to_dec(raw.get('Total PPh 21 (Rp)') or 0)))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def correction_file(results) -> bytes:
    """File koreksi: baris Error/Peringatan + kolom Status & Pesan, siap diperbaiki dan di-upload ulang."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Transaksi'
    ws.append(COLS + ['Status Upload', 'Pesan', 'Baris Asal'])
    for c in ws[1]:
        c.font = Font(bold=True)
    red, yel = PatternFill('solid', fgColor='F8CBAD'), PatternFill('solid', fgColor='FFF2CC')
    for r in results:
        if r['status'] == 'OK':
            continue
        ws.append([r['raw'].get(c, '') for c in COLS] + [r['status'], '; '.join(r['messages']), r['line']])
        for c in ws[ws.max_row]:
            c.fill = red if r['status'] == 'Error' else yel
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


SECTION_LABELS = list(SECTIONS.values())
