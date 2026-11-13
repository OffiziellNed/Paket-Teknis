"""Parser faktur pajak masukan Coretax (PDF teks). Aturan regex mengikuti scripts/parse_faktur.py.

Ekstraksi teks: pakai `pdftotext -layout` (poppler) bila tersedia, kalau tidak pakai pdfplumber.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from .rules import BULAN_IDX

MAX_FILES = 300
MAX_BYTES = 200 * 1024 * 1024


def _rp(s):
    return float(s.replace('.', '').replace(',', '.')) if s else None


def pdf_text(data: bytes) -> str:
    exe = shutil.which('pdftotext')
    if exe:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(data)
            path = f.name
        try:
            return subprocess.run([exe, '-layout', path, '-'], capture_output=True, text=True,
                                  encoding='utf-8').stdout
        finally:
            os.unlink(path)
    import pdfplumber  # fallback (Windows tanpa poppler)
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return '\n'.join((p.extract_text(layout=True) or '') for p in pdf.pages)


def parse_text(t: str, filename: str = '') -> dict:
    def g(p):
        m = re.search(p, t, re.S)
        return m.group(1).strip() if m else None

    tgl = re.search(r',\s*(\d{1,2})\s+(' + '|'.join(BULAN_IDX) + r')\s*(?:\n[^\n]*?)??\s*(\d{4})\b', t, re.I)
    hj = re.findall(r'Harga Jual / Penggantian / Uang Muka / Termin\s+([\d\.,]+)\s*\n', t)
    npwps = re.findall(r'NPWP\s*:\s*(\d{15,16})', t)
    nama = g(r'Pengusaha Kena Pajak:\s*\n\s*Nama\s*:\s*(.+?)\n')
    return {
        'file': filename,
        'no_faktur': g(r'Nomor Seri Faktur Pajak:\s*(\d+)'),
        'npwp_penjual': npwps[0].zfill(16) if npwps else None,
        'npwp_pembeli': npwps[1].zfill(16) if len(npwps) > 1 else None,
        'nama_penjual': nama.strip() if nama else None,
        'tanggal': (f"{tgl.group(3)}-{BULAN_IDX[tgl.group(2).lower()]:02d}-{int(tgl.group(1)):02d}"
                    if tgl and tgl.group(2).lower() in BULAN_IDX else None),
        'harga_jual': _rp(hj[-1]) if hj else None,
        'dpp_ppn': _rp(g(r'Dasar Pengenaan Pajak\s+([\d\.,]+)')),
        'ppn': _rp(g(r'Jumlah PPN[^\n]*?\s+([\d\.,]+)\s*\n')),
        'referensi': (g(r'\(Referensi:\s*([^\)\n]*)\)') or ''),
        'item': [i.strip() for i in re.findall(r'\n[^\S\n]{10,}([A-Za-z][^\n]{3,120}?)[^\S\n]*\n[^\S\n]+Rp [\d\.,]+ x', t)],
    }


def parse_pdf_bytes(data: bytes, filename: str = '') -> dict:
    return parse_text(pdf_text(data), filename)


def iter_uploads(files):
    """files: iterable (filename, bytes). ZIP diekstrak. Return list (filename, bytes) PDF.
    Batas: maks 300 faktur atau 200 MB total."""
    out, total = [], 0
    for name, data in files:
        total += len(data)
        if name.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.filename.lower().endswith('.pdf') and not info.is_dir():
                        total += info.file_size
                        out.append((os.path.basename(info.filename), z.read(info)))
        elif name.lower().endswith('.pdf'):
            out.append((os.path.basename(name), data))
        if len(out) > MAX_FILES:
            raise ValueError(f'Maksimal {MAX_FILES} faktur per upload')
        if total > MAX_BYTES:
            raise ValueError('Total upload melebihi 200 MB')
    return sorted(out)


def parse_folder(path: str) -> list[dict]:
    res = []
    for root, _, fs in os.walk(path):
        for f in sorted(fs):
            if f.lower().endswith('.pdf'):
                with open(os.path.join(root, f), 'rb') as fh:
                    res.append(parse_pdf_bytes(fh.read(), f))
    return sorted(res, key=lambda r: r['file'])
