"""Baca master entitas / KOP / vendor dari CSV di folder data/."""
from __future__ import annotations

import csv

from .rules import npwp16, to_dec

# Aturan khusus vendor (dari kolom aturan_khusus di master_vendor.csv), dalam bentuk yang bisa dieksekusi
AUTO_RULES = {
    '0015430614062000': {  # PT Rintis Sejahtera
        'item_rules': [{'contains': 'Administration Virtual Account', 'section': 'PPH23',
                        'notes': 'Adm VA Qoin periode {bulan_sebelum}'}],
        'aliases': ['rintis', 'rts'], 'auto_qris_draft': True,
    },
    '0016264426015000': {'ref_fix': 'P1->PI', 'aliases': ['alto'], 'auto_qris_draft': True},          # PT ALTO Network
    '0840718738071000': {'aliases': ['pten'], 'auto_qris_draft': True},
    '0031880503012000': {'final_choice': True, 'aliases': ['mahesa']},       # Dikenakan / Dibebaskan per tagihan
}
# Nama tampilan NPWP (format bertitik) dari riwayat transaksi
GROUP_SECTION = {'QRIS': 'PPH23_QRIS', 'Final': 'FINAL_4_2', 'Non-QRIS': 'PPH23'}


def read_entities(path):
    with open(path, encoding='utf-8-sig') as f:
        return [dict(code=r['kode'], legal_name=r['nama_legal'], npwp16=npwp16(r['npwp16']), nitku=r['nitku'],
                     report_title=r['judul_laporan'], notes=r.get('catatan') or '') for r in csv.DictReader(f)]


def read_kops(path):
    out = []
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            out.append(dict(code=r['kop'], name=r['nama_objek'], tax_type='PS4_2' if '4' in r['jenis_pajak'] and 'ayat' in r['jenis_pajak'] else 'PS23',
                            is_final=r['sifat'].strip().lower() == 'final', rate=to_dec(r['tarif_persen']) / 100,
                            verified=r['status_verifikasi_coretax'], used_for=r.get('dipakai_untuk') or ''))
    return out


def read_vendors(path):
    out = []
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            n16 = npwp16(r['npwp16'])
            rules = dict(AUTO_RULES.get(n16, {}))
            aliases = rules.pop('aliases', [])
            out.append(dict(
                name=r['nama'].strip(), npwp16=n16, nitku=r['nitku'] or n16 + '000000', entity_hint=r['entitas'],
                group=r['grup'], default_service=r['jenis_jasa_default'] or '', default_kop=r['kop_default'] or None,
                default_rate=to_dec(r['tarif_default']) if r['tarif_default'] else None,
                default_section=GROUP_SECTION.get(r['grup'], 'PPH23'), is_qris=r['grup'] == 'QRIS',
                last_invoices=[x.strip() for x in (r['3_invoice_terakhir'] or '').split(' | ') if x.strip()],
                withhold_pph23=r['dipotong_pph23'].strip().lower() == 'ya',
                is_recurring=r['tagihan_rutin'].strip().lower() == 'ya', special_rules_text=r.get('aturan_khusus') or '',
                auto_rules=rules, aliases=aliases))
    return out
