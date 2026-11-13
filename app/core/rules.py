"""Aturan bisnis inti (tanpa ketergantungan ke Flask/DB) – lihat PROMPT_BUILD.md bagian 'Aturan bisnis penting'."""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus',
         'September', 'Oktober', 'November', 'Desember']
BULAN_IDX = {b.lower(): i for i, b in enumerate(BULAN, 1)}
ROMAWI = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII']

# Section internal -> label yang dipakai di Excel/CSV/PDF
SECTIONS = {
    'PPH23': 'PPh 23',
    'PPH23_QRIS': 'PPh 23 Project QRIS',
    'FINAL_4_2': 'PPh Final 4(2)',
    'PPH21_FREELANCE': 'PPh 21 Freelance',
}
SECTION_BY_LABEL = {v.lower(): k for k, v in SECTIONS.items()}
SECTION_BY_LABEL.update({'pph final 4 (2)': 'FINAL_4_2', 'pph final': 'FINAL_4_2', 'pph 21': 'PPH21_FREELANCE',
                         'pph 23 qris': 'PPH23_QRIS'})
XML_SECTIONS = ('PPH23', 'PPH23_QRIS', 'FINAL_4_2')   # PPh 21 tidak masuk XML


def section_code(label: str) -> str:
    s = (label or '').strip()
    if s.upper() in SECTIONS:
        return s.upper()
    code = SECTION_BY_LABEL.get(re.sub(r'\s+', ' ', s.lower()))
    if not code:
        raise ValueError(f'Section tidak dikenal: {label!r}')
    return code


def digits(x) -> str:
    return ''.join(c for c in str(x or '') if c.isdigit())


def npwp16(x) -> str:
    """NPWP 15 digit -> 16 digit dengan menambah '0' di depan."""
    d = digits(x)
    if not d:
        return ''
    if len(d) > 16:
        raise ValueError(f'NPWP terlalu panjang: {x!r}')
    return d.zfill(16)


def nitku(npwp) -> str:
    return npwp16(npwp) + '000000'


def to_dec(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if x is None or x == '':
        return Decimal(0)
    return Decimal(str(x))


def round_rp(x) -> int:
    """Pembulatan ke rupiah terdekat, 0,5 ke atas (seperti Coretax)."""
    return int(to_dec(x).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def pph(dpp, tarif) -> Decimal:
    """PPh desimal = DPP x tarif (tarif desimal, mis. 0.02)."""
    return to_dec(dpp) * to_dec(tarif)


def pph_rounded(dpp, tarif) -> int:
    return round_rp(pph(dpp, tarif))


def last_day(month: int, year: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def in_period(d: date, month: int, year: int) -> bool:
    return d.year == year and d.month == month


def default_withholding_date(invoice_date: date, month: int, year: int) -> date:
    """Tanggal pemotongan wajib di dalam masa; invoice di luar masa -> akhir bulan masa."""
    return invoice_date if in_period(invoice_date, month, year) else last_day(month, year)


def masa_label(month: int, year: int) -> str:
    return f'{BULAN[month - 1]} {year}'


def tanggal_indo(d: date) -> str:
    return f'{d.day} {BULAN[d.month - 1]} {d.year}'


def parse_date(v) -> date | None:
    """Terima date/datetime, 'YYYY-MM-DD', 'dd/mm/yyyy', 'dd-mm-yyyy'."""
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d', '%d-%b-%y', '%d-%b-%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f'Format tanggal tidak dikenal: {v!r}')


def parse_masa(v) -> int:
    """'10', '03', 'Mei', 'Oktober' -> int bulan."""
    s = str(v).strip()
    if s.isdigit():
        m = int(s)
    else:
        m = BULAN_IDX.get(s.lower(), 0)
    if not 1 <= m <= 12:
        raise ValueError(f'Masa tidak valid: {v!r}')
    return m


def parse_tarif(v) -> Decimal:
    """Tarif boleh '2', '2%', '0.02', '2.5' -> Decimal desimal (0.02)."""
    s = str(v).strip().replace('%', '').replace(',', '.')
    d = Decimal(s)
    return d / 100 if d >= 1 else d


def xml_document_number(invoice_no: str) -> str:
    """Nomor invoice untuk XML: bagian sebelum '|' (keterangan PTEN tidak ikut)."""
    return (invoice_no or '').split('|')[0].strip()


def normalize_ref(s: str) -> str:
    """Bersihkan referensi faktur: buang awalan 'Inv.' / 'Invoice :' dan spasi."""
    s = (s or '').strip()
    s = re.sub(r'^(invoice|inv)(\.|\s*:|\s)\s*', '', s, flags=re.I)
    return s.strip()


def norm_key(s: str) -> str:
    return re.sub(r'[\s]+', '', normalize_ref(s)).upper()


def prev_month(d: date) -> tuple[int, int]:
    return (12, d.year - 1) if d.month == 1 else (d.month - 1, d.year)
