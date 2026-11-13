"""Import master + data historis dari folder Paket Teknis (data/*.csv) ke database."""
from __future__ import annotations

import os
import re
from collections import Counter

from .core.historical import read_qdi_csv, read_qki_csv
from .core.masters import read_entities, read_kops, read_vendors
from .models import (Entity, Period, Signer, SignaturePreset, TaxObjectCode, Transaction, Vendor, db)

ENTITY_EXTRA = {
    'QDI': dict(report_style='UNIFIKASI', numbering_since_year=None),
    'QKI': dict(report_style='SIMPLE', numbering_since_year=2025, former_name='PT Loyalty Program Indonesia (LPI)'),
}


def _norm(s):
    return re.sub(r'\b(pt|tbk)\b|[^a-z0-9 ]', ' ', s.lower()).split()


def seed_all(paket_dir: str, open_month=(10, 2026), log=print):
    data = lambda f: os.path.join(paket_dir, 'data', f)
    db.session.info['skip_audit'] = True

    # --- entitas
    for e in read_entities(data('entitas.csv')):
        ent = Entity.query.filter_by(code=e['code']).first() or Entity(code=e['code'])
        ent.legal_name, ent.npwp16, ent.nitku, ent.report_title = e['legal_name'], e['npwp16'], e['nitku'], e['report_title']
        for k, v in ENTITY_EXTRA.get(e['code'], {}).items():
            setattr(ent, k, v)
        db.session.add(ent)
    # --- KOP
    kops = read_kops(data('master_kop.csv'))
    for k in kops:
        obj = db.session.get(TaxObjectCode, k['code']) or TaxObjectCode(code=k['code'])
        obj.name, obj.tax_type, obj.is_final, obj.rate, obj.verified = k['name'], k['tax_type'], k['is_final'], k['rate'], k['verified']
        db.session.add(obj)
    db.session.flush()

    # --- transaksi historis (dipakai juga untuk NPWP tampilan vendor)
    rows = read_qdi_csv(data('transaksi_QDI_2026.csv')) + read_qki_csv(data('transaksi_QKI_2024_2026.csv'))
    disp = {}
    for r in rows:
        disp[r['npwp16']] = r['npwp_display']

    # --- vendor
    for v in read_vendors(data('master_vendor.csv')):
        obj = Vendor.query.filter_by(npwp16=v['npwp16'], name=v['name']).first() or Vendor()
        kop = v['default_kop']
        if not kop:   # isi dari kolom 'dipakai_untuk' di master KOP (mis. Venturo -> 24-104-24)
            words = set(_norm(v['name']))
            for k in kops:
                for used in k['used_for'].split(';'):
                    uw = set(_norm(used))
                    if uw and len(uw & words) >= max(1, min(2, len(uw))):
                        kop = k['code']
        for key in ('name', 'npwp16', 'nitku', 'entity_hint', 'group', 'default_service', 'default_rate',
                    'default_section', 'is_qris', 'withhold_pph23', 'is_recurring', 'auto_rules', 'aliases',
                    'special_rules_text'):
            setattr(obj, key, v[key])
        obj.default_kop = kop
        obj.seed_invoices = v['last_invoices']
        obj.npwp_display = disp.get(v['npwp16'], v['npwp16'])
        db.session.add(obj)
    db.session.flush()

    # --- transaksi
    if Transaction.query.count() == 0:
        ents = {e.code: e for e in Entity.query.all()}
        vend_by_npwp = {}
        for v in Vendor.query.all():
            vend_by_npwp.setdefault(v.npwp16, v)
        periods = {}
        for r in rows:
            key = (r['entity'], r['month'], r['year'])
            if key not in periods:
                p = Period.query.filter_by(entity_id=ents[r['entity']].id, month=r['month'], year=r['year']).first()
                if not p:
                    p = Period(entity=ents[r['entity']], month=r['month'], year=r['year'],
                               status='DRAFT' if (r['month'], r['year']) == open_month else 'APPROVED',
                               reviewed_by='import-historis' if (r['month'], r['year']) != open_month else None)
                    db.session.add(p)
                periods[key] = p
            v = vend_by_npwp.get(r['npwp16'])
            if v is None:
                v = Vendor(name=r['name'], npwp16=r['npwp16'], nitku=r['npwp16'] + '000000', npwp_display=r['npwp_display'],
                           entity_hint=r['entity'], group='Non-QRIS', default_section=r['section'], default_rate=r['rate'],
                           aliases=[], auto_rules={})
                db.session.add(v)
                vend_by_npwp[r['npwp16']] = v
            kop = v.default_kop
            if r['section'] == 'FINAL_4_2' and not kop:
                kop = '28-403-02'
            db.session.add(Transaction(
                period=periods[key], section=r['section'], sort_order=r['sort_order'], invoice_date=r['invoice_date'],
                invoice_no=r['invoice_no'], vendor=v, name=r['name'], npwp_display=r['npwp_display'], npwp16=r['npwp16'],
                description=r.get('description'), service_type=r.get('service_type'), kop=kop, dpp=r['dpp'],
                rate=r['rate'], withholding_date=r['withholding_date'], faktur_no=r.get('faktur_no'),
                bupot_no=r.get('bupot_no'), ntpn=r.get('ntpn'), notes=r.get('notes'), source='IMPORT',
                final_choice='DIKENAKAN' if r['section'] == 'FINAL_4_2' else None,
                created_by='import-historis'))
        log(f'Transaksi historis diimpor: {len(rows)} baris, {len(periods)} masa')

    # --- penanda tangan & preset default
    if Signer.query.count() == 0:
        rizal = Signer(name='Rizal Nur Furqon', title='Reconciliation Supervisor & Tax Support')
        sury = Signer(name='Suryawati', title='Manager FAT')
        db.session.add_all([rizal, sury])
        db.session.flush()
        for e in Entity.query.all():
            db.session.add(SignaturePreset(entity_id=e.id, name='Default', is_default=True, city='Jakarta', blocks=[
                {'order': 1, 'label': 'Dibuat oleh', 'signer_id': rizal.id, 'mode': 'BLANK', 'requires_approval': False},
                {'order': 2, 'label': 'Diperiksa oleh', 'signer_id': sury.id, 'mode': 'BLANK', 'requires_approval': True},
            ]))
    db.session.commit()
    db.session.info['skip_audit'] = False
    c = Counter((t.period.entity.code) for t in Transaction.query.all())
    log(f'Selesai. Entitas: {Entity.query.count()}, KOP: {TaxObjectCode.query.count()}, Vendor: {Vendor.query.count()}, '
        f'Transaksi: {dict(c)}')
