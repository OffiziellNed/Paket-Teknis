"""Test otomatis: parser faktur, generator XML, perhitungan total, crosscheck, import bupot (data Okt/Sep 2026)."""
import csv
import json
from datetime import date
from decimal import Decimal

from app.core.faktur_parser import parse_folder
from app.core.historical import read_qdi_csv, read_qki_csv
from app.core.matching import crosscheck, match_bupot, plan_drafts, read_coretax_export
from app.core.masters import read_kops, read_vendors
from app.core.report import build_report
from app.core.rules import default_withholding_date, npwp16, nitku, pph_rounded, round_rp
from app.core.xml_bpu import bpu_xml, validate_rows
from app.core.invoice_suggest import predict_next, validate

from conftest import p

ENT = {'0855609921034000': 'QDI', '0028998276031000': 'QKI'}


def vendors():
    vs = read_vendors(p('data', 'master_vendor.csv'))
    for i, v in enumerate(vs):
        v['id'] = i
    return vs


def with_kop(rows):
    by = {v['npwp16']: v['default_kop'] for v in vendors()}
    by['0031881097012000'] = '24-104-24'
    return [dict(r, kop=by.get(r['npwp16'])) for r in rows]


def okt(entity):
    rows = read_qdi_csv(p('data', 'transaksi_QDI_2026.csv')) + read_qki_csv(p('data', 'transaksi_QKI_2024_2026.csv'))
    return with_kop([r for r in rows if r['entity'] == entity and r['month'] == 10 and r['year'] == 2026])


def test_rules():
    assert npwp16('001.614.973.4-062.000') == '0016149734062000'
    assert nitku('16264426015000') == '0016264426015000000000'
    assert round_rp(Decimal('406.5')) == 407 and round_rp(Decimal('378.26')) == 378
    assert pph_rounded(6594211, Decimal('0.1')) == 659421
    assert default_withholding_date(date(2026, 9, 11), 10, 2026) == date(2026, 10, 31)
    assert default_withholding_date(date(2026, 10, 12), 10, 2026) == date(2026, 10, 12)


def test_parser_matches_expected():
    exp = {x['file']: x for x in json.load(open(p('samples', 'expected_parse_faktur_okt2026.json'), encoding='utf-8'))}
    got = parse_folder(p('samples', 'faktur_okt2026'))
    assert len(got) == 20
    for r in got:
        for k, v in exp[r['file']].items():
            assert r[k] == v, (r['file'], k)


def test_xml_identical_to_samples():
    for ent, tin, f in [('QDI', '0855609921034000', 'BPU_QDI_Okt2026.xml'), ('QKI', '0028998276031000', 'BPU_QKI_Okt2026.xml')]:
        rows = okt(ent)
        assert validate_rows(10, 2026, rows) == []
        assert bpu_xml(tin, 10, 2026, rows) == open(p('samples', f), encoding='utf-8').read()


def test_totals_okt_2026():
    rep = build_report({'code': 'QDI', 'report_title': 'REKAPAN PPH UNIFIKASI PT QDI', 'legal_name': 'x'}, 10, 2026, okt('QDI'))
    assert rep.totals['pph23'] == 2373193
    assert rep.totals['final'] == 661191
    assert rep.totals['total'] == 3034384
    assert rep.totals['count_bupot'] == 11
    rk = build_report({'code': 'QKI', 'report_title': 'Rekapan Pajak', 'legal_name': 'x'}, 10, 2026, okt('QKI'))
    assert rk.totals['pph23'] == 2919594 and rk.totals['count_bupot'] == 1


def test_historical_totals_match_source():
    """Total PPh per masa dari data impor = total kolom pph di sumber (dibulatkan)."""
    rows = read_qdi_csv(p('data', 'transaksi_QDI_2026.csv'))
    for m in range(1, 11):
        rs = [r for r in rows if r['month'] == m]
        assert sum(pph_rounded(r['dpp'], r['rate']) for r in rs) == round_rp(sum(r['pph_source'] for r in rs)) or \
            abs(sum(pph_rounded(r['dpp'], r['rate']) for r in rs) - sum(r['pph_source'] for r in rs)) < len(rs)


def test_crosscheck_and_drafts_match_expected():
    vs = vendors()
    vb = {v['npwp16']: v for v in vs}
    kops = {k['code']: k['rate'] for k in read_kops(p('data', 'master_kop.csv'))}
    fak = parse_folder(p('samples', 'faktur_okt2026'))
    for f in fak:  # Rintis Annual Fee QRIS ditandai Tidak dipotong (revisi 6-Nov-2026)
        if f['no_faktur'] == '04002600431060608':
            f['tidak_dipotong'] = 'Annual Fee for QRIS - tidak dipotong PPh 23'
    trx = [dict(id=i, entity=r['entity'], invoice_no=r['invoice_no'], name=r['name'], npwp16=r['npwp16'], dpp=r['dpp'],
                source='MANUAL', is_qris=False)
           for i, r in enumerate(okt('QDI') + okt('QKI')) if r['section'] != 'PPH23_QRIS']
    plan = plan_drafts(fak, vb, crosscheck(trx, fak, ENT), [], kops, 10, 2026, 'QDI')
    assert [f['nama_penjual'] for f in plan['vendor_baru']] == ['PEMBAYARAN LINTAS USAHA SUKSES']
    assert len(plan['diabaikan']) == 2  # BCA & Telkom
    qris = [d for d in plan['new'] if vb[d['npwp16']]['auto_rules'].get('auto_qris_draft')]
    assert sorted(d['invoice_no'] for d in qris) == sorted([
        'AR#261003968#5614-003968/I/RS/X/26', 'PI26.00472', 'PTEN.INV/Q116/10/2026|Fee LS QRIS Domestik dari ALTO.',
        'PTEN.INV/Q115/10/2026|Fee LS QRIS Domestik dari RINTIS.'])
    assert all(d['kop'] == '24-104-18' and d['rate'] == Decimal('0.02') for d in qris)
    alto = [d for d in qris if d['invoice_no'] == 'PI26.00472'][0]
    assert alto['notes'] == "QR MPM prd Okt'26 (ref. faktur: P126.00472)"
    for j, d in enumerate(plan['new']):
        trx.append(dict(id=1000 + j, entity='QDI', invoice_no=d['invoice_no'], name=d['name'], npwp16=d['npwp16'],
                        dpp=d['dpp'], faktur_no=d['faktur_no'], source='FAKTUR', draft_status='PERLU_KONFIRMASI',
                        is_qris=bool(vb[d['npwp16']]['auto_rules'].get('auto_qris_draft'))))
    got = {(r['entitas'], r['no_faktur'] or r['no_invoice'], r['status']) for r in crosscheck(trx, fak, ENT)}
    with open(p('samples', 'expected_crosscheck_okt2026.csv'), encoding='utf-8') as f:
        exp = {(r['entitas'], r['no_faktur'] or r['no_invoice'], r['status']) for r in csv.DictReader(f)}
    assert got == exp


def test_bupot_import_sep_2026_15_of_15():
    rows = read_qdi_csv(p('data', 'transaksi_QDI_2026.csv'))
    trx = [dict(id=i, entity=r['entity'], month=r['month'], year=r['year'], npwp16=r['npwp16'], dpp=r['dpp'],
                kop=None, invoice_no=r['invoice_no'], bupot_no=r['bupot_no']) for i, r in enumerate(rows)]
    exp = read_coretax_export(p('samples', 'coretax_export_bupot_sep2026.xlsx'),
                              {'0855609921034000000000': 'QDI', '0028998276031000000000': 'QKI'})
    res, belum = match_bupot(exp, trx)
    assert len(res) == 15
    assert sum(r['status'] == 'Cocok' for r in res) == 15
    assert belum == []


def test_invoice_suggestion():
    assert validate('15/KTI/X/2026', ['29/KTI/VIII/2026', '29/KTI/IX/2026'])[0] == 'kuning'
    assert validate('260024808', ['260021769', '260024008', '260024808'], {'260024808'})[0] == 'merah'
    assert validate('INV/2026/00500', ['INV/2026/00477', 'INV/2026/00491'])[0] == 'hijau'
    assert predict_next(['273/MC-QDI/X/2026', '281/MC-QDI/X/2026'], 11, 2026) == '282/MC-QDI/XI/2026'
