"""Pencocokan invoice <-> faktur, draft otomatis dari faktur, dan import No Bupot Coretax."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from .rules import (BULAN, BULAN_IDX, default_withholding_date, norm_key, normalize_ref, npwp16, parse_date,
                    prev_month, round_rp, to_dec)

BLN3 = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']


# --------------------------------------------------------------------------- referensi faktur
def apply_ref_fix(ref: str, rules: dict | None) -> tuple[str, bool]:
    """Koreksi referensi faktur sesuai aturan vendor (mis. ALTO 'P126.00472' -> 'PI26.00472')."""
    ref = normalize_ref(ref)
    if rules and rules.get('ref_fix') == 'P1->PI' and re.match(r'^P1\d', ref):
        return 'PI' + ref[2:], True
    return ref, False


def _keys(s: str) -> set[str]:
    k = norm_key(s)
    out = {k, norm_key(s.split('|')[0])}
    if re.match(r'^P1\d', k):
        out.add('PI' + k[2:])
    return {x for x in out if x}


def invoice_matches_ref(invoice_no: str, ref: str) -> int:
    """0 = tidak cocok, 2 = sama persis, 1 = salah satu memuat yang lain (mis. ref Rintis memuat no invoice)."""
    if not invoice_no or not ref:
        return 0
    a, b = _keys(invoice_no), _keys(ref)
    if a & b:
        return 2
    for x in a:
        for y in b:
            if len(x) >= 6 and len(y) >= 6 and (x in y or y in x):
                return 1
    return 0


# --------------------------------------------------------------------------- crosscheck
def crosscheck(transactions: list[dict], fakturs: list[dict], entity_by_npwp: dict) -> list[dict]:
    """transactions: dict id, entity, invoice_no, name, npwp16, dpp, faktur_no, source, draft_status, is_qris.
    fakturs: hasil parser + optional 'tidak_dipotong' (alasan) dan 'vendor_name'.
    Return baris: entitas,no_invoice,lawan_transaksi,dpp_rekap,no_faktur,harga_jual_faktur,status,catatan,
    transaction_id."""
    f_ent = [(f, entity_by_npwp.get(npwp16(f.get('npwp_pembeli')))) for f in fakturs]
    used_f, match_of = set(), {}

    # 1) tautan eksplisit (no faktur sudah tersimpan di transaksi)
    for t in transactions:
        for i, (f, ent) in enumerate(f_ent):
            if i not in used_f and t.get('faktur_no') and t['faktur_no'] == f['no_faktur']:
                match_of[t['id']] = i
                used_f.add(i)
                break
    # 2) seller NPWP + nomor invoice/referensi
    for t in transactions:
        if t['id'] in match_of:
            continue
        cands = []
        for i, (f, ent) in enumerate(f_ent):
            if i in used_f or ent != t['entity'] or npwp16(f['npwp_penjual']) != npwp16(t['npwp16']):
                continue
            score = invoice_matches_ref(t['invoice_no'], f.get('referensi') or '')
            if score:
                same_amt = f.get('harga_jual') is not None and abs(to_dec(t['dpp']) - to_dec(f['harga_jual'])) < 1
                cands.append((score, same_amt, i))
        if cands:
            cands.sort(reverse=True)
            match_of[t['id']] = cands[0][2]
            used_f.add(cands[0][2])

    out = []
    for t in transactions:
        i = match_of.get(t['id'])
        f = f_ent[i][0] if i is not None else None
        draft_faktur = t.get('source') == 'FAKTUR'
        row = dict(entitas=t['entity'], no_invoice=t['invoice_no'], lawan_transaksi=t['name'],
                   dpp_rekap=t['dpp'], no_faktur=f['no_faktur'] if f else '', harga_jual_faktur=f['harga_jual'] if f else '',
                   catatan='', transaction_id=t['id'])
        if f is None:
            row['status'] = 'Faktur belum ada'
        elif draft_faktur and not t.get('is_qris') and t.get('draft_status') == 'PERLU_KONFIRMASI':
            row.update(status='Faktur tanpa transaksi', dpp_rekap='', catatan='Draft dibuat dari faktur – perlu konfirmasi')
        else:
            diff = round_rp(to_dec(f['harga_jual']) - to_dec(t['dpp']))
            if diff:
                row.update(status='Selisih nilai', catatan=f'Selisih Rp {abs(diff):,}'.replace(',', '.'))
            elif draft_faktur and t.get('is_qris'):
                row['status'] = 'Cocok (draft otomatis QRIS)'
            else:
                row['status'] = 'Cocok'
                if invoice_matches_ref(t['invoice_no'], f.get('referensi') or '') == 1:
                    row['catatan'] = f"Referensi faktur {f.get('referensi')} memuat no invoice"
        out.append(row)
    for i, (f, ent) in enumerate(f_ent):
        if i in used_f:
            continue
        base = dict(entitas=ent or '?', no_invoice=normalize_ref(f.get('referensi')) or '(tanpa referensi)',
                    lawan_transaksi=f.get('vendor_name') or (f.get('nama_penjual') or '').title(), dpp_rekap='',
                    no_faktur=f['no_faktur'], harga_jual_faktur=f['harga_jual'], transaction_id=None)
        if f.get('tidak_dipotong') is not None:
            base.update(status='Tidak dipotong (ditandai user)', catatan=f.get('tidak_dipotong') or '')
        else:
            base.update(status='Faktur tanpa transaksi', catatan='; '.join(f.get('item') or [])[:120])
        out.append(base)
    return out


# --------------------------------------------------------------------------- draft dari faktur
def _clean_item(s: str) -> str:
    s = re.sub(r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s*-\s*\d{1,2}[./-]\d{1,2}[./-]\d{2,4}', '', s)
    s = s.replace('–', ' ').replace(' - ', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def draft_notes(vendor: dict, f: dict, d: date) -> str:
    ref = f.get('referensi') or ''
    m = re.search(r'dari\s+([A-Za-z]+)', ref)
    if m and 'PTEN' in ref.upper():
        return m.group(1).upper()
    items = f.get('item') or []
    if items:
        return f"{_clean_item(items[0])} prd {BLN3[d.month - 1]}'{d.year % 100:02d}"
    return ''


def faktur_to_draft(f: dict, vendor: dict, kop_rates: dict, month: int, year: int) -> dict:
    """Buat draft transaksi dari faktur untuk vendor master. vendor: dict name, npwp_display, npwp16, group,
    default_section, default_service, default_kop, default_rate, auto_rules."""
    rules = vendor.get('auto_rules') or {}
    d = parse_date(f['tanggal'])
    ref, fixed = apply_ref_fix(f.get('referensi') or '', rules)
    section = vendor.get('default_section') or {'QRIS': 'PPH23_QRIS', 'Final': 'FINAL_4_2'}.get(vendor.get('group'), 'PPH23')
    notes = draft_notes(vendor, f, d)
    items = ' '.join(f.get('item') or [])
    for rule in rules.get('item_rules', []):
        if rule['contains'].lower() in items.lower():
            section = rule.get('section', section)
            if rule.get('notes'):
                pm, py = prev_month(d)
                notes = rule['notes'].replace('{bulan_sebelum}', f'{BULAN[pm - 1]} {py}')
            break
    if fixed:
        notes = (notes + f" (ref. faktur: {normalize_ref(f.get('referensi'))})").strip()
    kop = vendor.get('default_kop') or None
    rate = vendor.get('default_rate') or kop_rates.get(kop) or Decimal('0.02')
    if rules.get('auto_qris_draft'):   # Rintis / ALTO / PTEN: KOP 24-104-18, tarif 2%, DPP = harga jual
        kop, rate = '24-104-18', Decimal('0.02')
    return dict(section=section, invoice_date=d, invoice_no=ref or f['no_faktur'], name=vendor['name'],
                npwp_display=vendor.get('npwp_display') or vendor['npwp16'], npwp16=vendor['npwp16'],
                service_type=vendor.get('default_service') or '', kop=kop, dpp=to_dec(f['harga_jual']),
                rate=to_dec(rate), withholding_date=default_withholding_date(d, month, year),
                faktur_no=f['no_faktur'], notes=notes, source='FAKTUR', draft_status='PERLU_KONFIRMASI',
                vendor_id=vendor.get('id'))


def plan_drafts(fakturs: list[dict], vendors_by_npwp: dict, crosscheck_rows: list[dict], existing_drafts: list[dict],
                kop_rates: dict, month: int, year: int, entity_code: str):
    """Tentukan aksi per faktur yang belum cocok: draft baru / gabung ke draft yang ada / vendor baru / diabaikan.
    Return dict(new=[draft], merge=[(draft_id, draft)], vendor_baru=[faktur], diabaikan=[(faktur, alasan)])."""
    unmatched = {r['no_faktur'] for r in crosscheck_rows
                 if r['status'] == 'Faktur tanpa transaksi' and r['transaction_id'] is None}
    res = dict(new=[], merge=[], vendor_baru=[], diabaikan=[])
    taken = set()
    for f in fakturs:
        if f['no_faktur'] not in unmatched or f.get('tidak_dipotong') is not None:
            continue
        v = vendors_by_npwp.get(npwp16(f['npwp_penjual']))
        if v is None:
            res['vendor_baru'].append(f)
            continue
        if not v.get('withhold_pph23', True):
            res['diabaikan'].append((f, f"{v['name']}: tidak dipotong PPh 23 (master vendor)"))
            continue
        draft = faktur_to_draft(f, v, kop_rates, month, year)
        draft['entity'] = entity_code
        # gabung dengan draft yang sudah ada (mis. draft rutin) untuk vendor yang sama
        target = None
        for e in existing_drafts:
            if e['id'] in taken or npwp16(e['npwp16']) != v['npwp16'] or e.get('faktur_no'):
                continue
            if invoice_matches_ref(e['invoice_no'], f.get('referensi') or '') or \
                    abs(to_dec(e['dpp']) - draft['dpp']) < 1:
                target = e
                break
        if target:
            taken.add(target['id'])
            res['merge'].append((target['id'], draft))
        else:
            res['new'].append(draft)
    return res


# --------------------------------------------------------------------------- import No Bupot Coretax (PRD 7.4)
EXPORT_COLS = {
    'masa': 'Masa Pajak', 'bupot': 'Nomor Pemotongan', 'status': 'Status', 'tte': 'Status Tanda Tangan Elektronik',
    'nitku': 'NITKU/Nomor Identitas Sub Unit Organisasi', 'kop': 'Kode Objek Pajak', 'npwp': 'Nomor Identitas WP',
    'nama': 'Nama', 'dpp': 'Dasar Pengenaan Pajak (Rp)', 'pph': 'Pajak Penghasilan (Rp)', 'spt': 'Dilaporkan Dalam SPT',
}


def read_coretax_export(fileobj, entity_by_nitku: dict) -> list[dict]:
    import openpyxl
    ws = openpyxl.load_workbook(fileobj, data_only=True, read_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h or '').strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(hdr)}
    missing = [v for v in EXPORT_COLS.values() if v not in idx]
    if missing:
        raise ValueError('Kolom tidak ditemukan di file export: ' + ', '.join(missing))
    col = lambda r, k: r[idx[EXPORT_COLS[k]]]
    out = []
    for r in rows[1:]:
        if not col(r, 'bupot'):
            continue
        bln, thn = str(col(r, 'masa')).split()
        out.append(dict(entitas=entity_by_nitku.get(str(col(r, 'nitku')).strip()), masa=BULAN_IDX[bln.lower()],
                        tahun=int(thn), bupot=str(col(r, 'bupot')).strip(), status=col(r, 'status'),
                        tte=col(r, 'tte'), kop=col(r, 'kop'), npwp16=npwp16(col(r, 'npwp')), nama=col(r, 'nama'),
                        dpp=to_dec(col(r, 'dpp')), pph=to_dec(col(r, 'pph')), spt=bool(col(r, 'spt'))))
    return out


def match_bupot(export: list[dict], trx: list[dict]):
    """trx: dict id, entity, month, year, npwp16, dpp, kop, invoice_no, bupot_no.
    Cocok per entitas (NITKU) + masa + NPWP + DPP (+KOP bila masih ganda)."""
    used, result = set(), []
    for e in export:
        cand = [t for t in trx if t['id'] not in used and t['entity'] == e['entitas'] and t['month'] == e['masa']
                and t['year'] == e['tahun'] and npwp16(t['npwp16']) == e['npwp16']
                and round_rp(t['dpp']) == round_rp(e['dpp'])]
        if len(cand) > 1:
            cand = [t for t in cand if t.get('kop') == e['kop']] or cand
        row = dict(export=e, transaction_id=None, invoice_no='')
        if len(cand) == 1:
            t = cand[0]
            used.add(t['id'])
            row.update(transaction_id=t['id'], invoice_no=t['invoice_no'],
                       status='Cocok' if not t.get('bupot_no') or t['bupot_no'] == e['bupot']
                       else 'Nomor beda dengan data lama', old_bupot=t.get('bupot_no'))
            if t.get('kop') and e['kop'] and t['kop'] != e['kop']:
                row['catatan'] = f"KOP di Coretax {e['kop']} berbeda dengan transaksi {t['kop']}"
        else:
            row['status'] = 'Pilih manual' if cand else 'Bupot tanpa transaksi'
            row['candidates'] = [t['id'] for t in cand]
        result.append(row)
    periods = {(e['entitas'], e['masa'], e['tahun']) for e in export}
    belum = [t for t in trx if t['id'] not in used and (t['entity'], t['month'], t['year']) in periods]
    return result, belum
