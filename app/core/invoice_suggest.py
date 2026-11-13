"""Saran nomor invoice berikutnya + validasi pola (hijau/kuning/merah)."""
from __future__ import annotations

import re

from .rules import ROMAWI

TOKEN = re.compile(r'\d+|[A-Za-z]+|[^A-Za-z\d]')


def shape(s: str) -> str:
    """Pola: digit -> 9 (panjang dipertahankan), romawi bulan -> R, huruf lain apa adanya (uppercase)."""
    out = []
    for tok in TOKEN.findall((s or '').split('|')[0].strip()):
        if tok.isdigit():
            out.append('9' * len(tok))
        elif tok.upper() in ROMAWI:
            out.append('R')
        else:
            out.append(tok.upper())
    return ''.join(out)


def _numbers(s):
    return [(m.start(), m.group()) for m in re.finditer(r'\d+', (s or '').split('|')[0])]


def seq_number(s: str, ref: str | None = None) -> int | None:
    """Nomor urut = grup angka yang berubah antar invoice (default: grup angka terpanjang/pertama)."""
    nums = _numbers(s)
    if not nums:
        return None
    if ref:
        rn = _numbers(ref)
        if len(rn) == len(nums):
            for (_, a), (_, b) in zip(nums, rn):
                if a != b and not (len(a) == 4 and a.startswith('20')):
                    return int(a)
    # grup angka bukan tahun dan bukan bulan
    cands = [n for _, n in nums if not (len(n) == 4 and n.startswith('20')) and not (len(n) <= 2 and int(n) <= 12)]
    return int(cands[0]) if cands else int(nums[0][1])


def predict_next(history: list[str], month: int, year: int) -> str | None:
    """history: invoice lama urut kronologis (terlama -> terbaru)."""
    hist = [h for h in history if h]
    if not hist:
        return None
    last = hist[-1].split('|')[0].strip()
    prev = hist[-2].split('|')[0].strip() if len(hist) > 1 else None
    nums = _numbers(last)
    if not nums:
        return None
    # tentukan grup angka yang dinaikkan
    target = None
    if prev:
        pn = _numbers(prev)
        if len(pn) == len(nums):
            for k, ((_, a), (_, b)) in enumerate(zip(nums, pn)):
                if a != b and not (len(a) == 4 and a.startswith('20')) and int(a) > int(b):
                    target = k
                    break
    if target is None:
        for k, (_, n) in enumerate(nums):
            if not (len(n) == 4 and n.startswith('20')) and not (len(n) <= 2 and int(n) <= 12 and len(nums) > 1):
                target = k
                break
    if target is None:
        target = 0
    pos, n = nums[target]
    new = str(int(n) + 1).zfill(len(n))
    res = last[:pos] + new + last[pos + len(n):]
    # bulan romawi & tahun mengikuti masa
    # bulan romawi / angka bulan & tahun di akhir nomor mengikuti masa
    res = re.sub(r'(?<=/)(XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I)(?=/(?:20)?\d\d$)', ROMAWI[month - 1], res)
    res = re.sub(r'(?<=/)(0[1-9]|1[0-2])(?=/20\d\d$)', f'{month:02d}', res)
    res = re.sub(r'(?<=/)20\d\d$', str(year), res)
    res = re.sub(r'(?<=/[IVX]/)\d\d$|(?<=/[IVX]{2}/)\d\d$|(?<=/[IVX]{3}/)\d\d$|(?<=/[IVX]{4}/)\d\d$',
                 f'{year % 100:02d}', res)
    return res


def validate(invoice_no: str, history: list[str], existing_for_vendor: set[str] | None = None) -> tuple[str, str]:
    """Return (warna, pesan). merah = duplikat / pola sama sekali beda; kuning = pola mirip tapi urutan janggal;
    hijau = sesuai pola dan nomor urut naik."""
    inv = (invoice_no or '').strip()
    if not inv:
        return 'merah', 'Nomor invoice kosong'
    if existing_for_vendor and inv in existing_for_vendor:
        return 'merah', 'Nomor invoice sudah pernah dipakai untuk vendor ini'
    hist = [h for h in history if h]
    if not hist:
        return 'kuning', 'Belum ada riwayat invoice vendor ini'
    shapes = {shape(h) for h in hist}
    if shape(inv) not in shapes:
        # pola mirip bila jumlah grup angka sama
        if any(len(_numbers(h)) == len(_numbers(inv)) for h in hist):
            return 'kuning', 'Pola sedikit berbeda dari invoice sebelumnya'
        return 'merah', 'Pola nomor invoice berbeda dari riwayat vendor'
    last = hist[-1]
    a, b = seq_number(inv, last), seq_number(last, inv)
    if a is not None and b is not None and a <= b:
        return 'kuning', f'Nomor urut lebih kecil/sama dari invoice terakhir ({last})'
    return 'hijau', 'Sesuai pola'
