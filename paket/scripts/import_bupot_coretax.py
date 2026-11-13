"""Referensi: cocokkan export data pemotongan Coretax ke transaksi untuk mengisi No Bupot (PRD 7.4).
Pakai: python import_bupot_coretax.py <export.xlsx> <transaksi.csv>
transaksi.csv minimal kolom: entitas,masa,tahun,npwp16,dpp,no_invoice,no_bupot  (lihat data/transaksi_QDI_2026.csv)"""
import sys, csv, openpyxl
BULAN = {b: i for i, b in enumerate(['januari','februari','maret','april','mei','juni','juli','agustus',
          'september','oktober','november','desember'], 1)}
ENTITAS_NITKU = {'0855609921034000000000': 'QDI', '0028998276031000000000': 'QKI'}

def read_export(path):
    ws = openpyxl.load_workbook(path, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h or '').strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(hdr)}            # header by nama kolom
    out = []
    for r in rows[1:]:
        if not r[idx['Nomor Pemotongan']]:
            continue
        bln, thn = str(r[idx['Masa Pajak']]).split()
        out.append(dict(entitas=ENTITAS_NITKU.get(str(r[idx['NITKU/Nomor Identitas Sub Unit Organisasi']])),
                        masa=BULAN[bln.lower()], tahun=int(thn), bupot=r[idx['Nomor Pemotongan']],
                        status=r[idx['Status']], tte=r[idx['Status Tanda Tangan Elektronik']],
                        kop=r[idx['Kode Objek Pajak']], npwp16=str(r[idx['Nomor Identitas WP']]).zfill(16),
                        nama=r[idx['Nama']], dpp=float(r[idx['Dasar Pengenaan Pajak (Rp)']]),
                        pph=float(r[idx['Pajak Penghasilan (Rp)']])))
    return out

def match(export, trx):
    used, result = set(), []
    for e in export:
        cand = [i for i, t in enumerate(trx) if i not in used and t['entitas'] == e['entitas']
                and int(t['masa']) == e['masa'] and int(t['tahun']) == e['tahun']
                and t['npwp16'].zfill(16) == e['npwp16'] and round(float(t['dpp'])) == round(e['dpp'])]
        if len(cand) == 1:
            used.add(cand[0]); t = trx[cand[0]]
            st = 'Cocok' if not t.get('no_bupot') or t['no_bupot'] == e['bupot'] else 'Nomor beda dengan data lama'
            result.append((e['bupot'], e['nama'], e['dpp'], st, t['no_invoice']))
        else:
            result.append((e['bupot'], e['nama'], e['dpp'], 'Pilih manual' if cand else 'Bupot tanpa transaksi', ''))
    belum = [t['no_invoice'] for i, t in enumerate(trx) if i not in used
             and any(int(t['masa']) == e['masa'] and t['entitas'] == e['entitas'] for e in export)]
    return result, belum

if __name__ == '__main__':
    exp = read_export(sys.argv[1])
    trx = list(csv.DictReader(open(sys.argv[2], encoding='utf-8')))
    res, belum = match(exp, trx)
    for r in res: print(*r, sep=' | ')
    print(f"Cocok: {sum(r[3]=='Cocok' for r in res)}/{len(res)}; transaksi belum terbit bupot: {belum}")
