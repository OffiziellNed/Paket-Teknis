"""Baca data historis dari CSV di folder data/ (hasil ekstraksi workbook) menjadi baris transaksi standar."""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal

from .rules import (default_withholding_date, npwp16, parse_date, parse_masa, section_code, to_dec)


def _clean_bupot(v):
    v = (v or '').strip()
    # di sheet LPI ada sel bupot berisi hasil rumus (=H10*11%) -> bukan nomor bupot
    if not v or v == '\xa0' or ('.' in v and v.replace('.', '').isdigit()):
        return None
    return v


def read_qdi_csv(path) -> list[dict]:
    out = []
    with open(path, encoding='utf-8-sig') as f:
        for i, r in enumerate(csv.DictReader(f)):
            m, y = int(r['masa']), int(r['tahun'])
            d = parse_date(r['tanggal_invoice'])
            faktur = (r.get('no_faktur') or '').strip()
            out.append(dict(
                entity=r['entitas'], month=m, year=y, section=section_code(r['section']), invoice_date=d,
                invoice_no=r['no_invoice'].strip(), name=r['lawan_transaksi'].strip(), npwp_display=r['npwp'].strip(),
                npwp16=npwp16(r['npwp16'] or r['npwp']), dpp=to_dec(r['dpp']), rate=to_dec(r['tarif']),
                pph_source=to_dec(r['pph']), bupot_no=_clean_bupot(r.get('no_bupot')),
                service_type=(r.get('jenis_jasa') or '').strip(), notes=(r.get('notes') or '').strip(),
                faktur_no=faktur if faktur.isdigit() else None,
                faktur_note=faktur if faktur and not faktur.isdigit() else None,
                withholding_date=default_withholding_date(d, m, y), sort_order=i, source='IMPORT'))
    return out


def read_qki_csv(path, start_year: int = 2024) -> list[dict]:
    """CSV QKI tidak punya kolom tahun dan formatnya campur ('Mei', '03', dd/mm/yyyy).
    Tahun masa ditentukan berurutan: tahun tidak pernah mundur dan masa tidak boleh sebelum bulan invoice."""
    out, cur = [], start_year
    with open(path, encoding='utf-8-sig') as f:
        for i, r in enumerate(csv.DictReader(f)):
            m = parse_masa(r['masa'])
            d = parse_date(r['tanggal_invoice'])
            y = cur
            while date(y, m, 1) < date(d.year, d.month, 1):
                y += 1
            cur = y
            dpp, p = to_dec(r['dpp']), to_dec(r['pph'])
            rate = (p / dpp).quantize(Decimal('0.001')) if dpp else Decimal('0.02')
            rate = Decimal('0.1') if rate >= Decimal('0.09') else Decimal('0.02')
            out.append(dict(
                entity=r['entitas'], month=m, year=y, section='FINAL_4_2' if rate == Decimal('0.1') else 'PPH23',
                invoice_date=d, invoice_no=r['no_invoice'].strip(), name=r['lawan_transaksi'].strip(),
                npwp_display=r['npwp'].strip(), npwp16=npwp16(r['npwp16'] or r['npwp']), dpp=dpp, rate=rate,
                pph_source=p, bupot_no=_clean_bupot(r.get('no_bupot')), description=(r.get('deskripsi') or '').strip(),
                ntpn=(r.get('ntpn') or '').strip() or None, notes='', service_type='', faktur_no=None,
                withholding_date=default_withholding_date(d, m, y), sort_order=i, source='IMPORT'))
    return out
