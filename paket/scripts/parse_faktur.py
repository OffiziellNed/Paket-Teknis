"""Referensi parser faktur pajak masukan Coretax (PDF teks).
Pakai: python parse_faktur.py <folder_atau_zip> > hasil.json
Butuh: poppler-utils (pdftotext). Tim boleh mengganti dengan pdfplumber/pdf.js; aturan regex-nya yang penting."""
import sys, re, json, subprocess, zipfile, tempfile, os, glob

BULAN = {'januari':1,'februari':2,'maret':3,'april':4,'mei':5,'juni':6,'juli':7,
         'agustus':8,'september':9,'oktober':10,'november':11,'desember':12}

def rp(s):  # "6.594.212,00" -> 6594212.0
    return float(s.replace('.', '').replace(',', '.')) if s else None

def parse_pdf(path):
    t = subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True).stdout
    g = lambda p: (m.group(1).strip() if (m := re.search(p, t, re.S)) else None)
    tgl = re.search(r',\s*(\d{1,2})\s+(' + '|'.join(BULAN) + r')\s*(?:\n[^\n]*?)??\s*(\d{4})\b', t, re.I)
    hj = re.findall(r'Harga Jual / Penggantian / Uang Muka / Termin\s+([\d\.,]+)\n', t)
    npwps = re.findall(r'NPWP\s*:\s*(\d{15,16})', t)
    return {
        'file': os.path.basename(path),
        'no_faktur': g(r'Nomor Seri Faktur Pajak:\s*(\d+)'),
        'npwp_penjual': npwps[0] if npwps else None,
        'npwp_pembeli': npwps[1] if len(npwps) > 1 else None,
        'nama_penjual': g(r'Pengusaha Kena Pajak:\s*\n\s*Nama\s*:\s*(.+?)\n'),
        'tanggal': f"{tgl.group(3)}-{BULAN[tgl.group(2).lower()]:02d}-{int(tgl.group(1)):02d}" if tgl and tgl.group(2).lower() in BULAN else None,
        'harga_jual': rp(hj[-1]) if hj else None,
        'dpp_ppn': rp(g(r'Dasar Pengenaan Pajak\s+([\d\.,]+)')),
        'ppn': rp(g(r'Jumlah PPN[^\n]*?\s+([\d\.,]+)\n')),
        'referensi': g(r'\(Referensi:\s*([^\)\n]+)\)'),
        'item': re.findall(r'\n\s{20,}([A-Za-z][^\n]{3,120})\n\s+Rp [\d\.,]+ x', t),
    }

def files(src):
    if src.lower().endswith('.zip'):
        d = tempfile.mkdtemp(); zipfile.ZipFile(src).extractall(d); src = d
    return sorted(glob.glob(os.path.join(src, '**', '*.pdf'), recursive=True))

if __name__ == '__main__':
    print(json.dumps([parse_pdf(f) for f in files(sys.argv[1])], ensure_ascii=False, indent=2))
