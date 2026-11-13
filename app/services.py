"""Logika aplikasi yang menghubungkan database dengan modul core."""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import g
from sqlalchemy import func

from .core import invoice_suggest
from .core.faktur_parser import iter_uploads, parse_pdf_bytes
from .core.matching import crosscheck, match_bupot, plan_drafts
from .core.report import build_report
from .core.report_pdf import render_pdf
from .core.report_xlsx import render_xlsx
from .core.rules import (BULAN, default_withholding_date, last_day, masa_label, npwp16, parse_date, to_dec)
from .core.xml_bpu import bpu_xml, validate_rows
from . import storage as ST
from .models import (AuditLog, Entity, OutputLog, Period, Signer, SignaturePreset, EntityStamp, TaxInvoice,
                     TaxObjectCode, Transaction, Vendor, db)

WIB = ZoneInfo('Asia/Jakarta')
CTYPE = {'XML': 'application/xml', 'PDF': 'application/pdf',
         'XLSX': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}


def today_wib() -> date:
    return datetime.now(WIB).date()


def actor():
    return g.user.email if getattr(g, 'user', None) else 'system'


# ----------------------------------------------------------------------------- periode
def get_or_open_period(entity: Entity, month: int, year: int, create_recurring=True) -> Period:
    p = Period.query.filter_by(entity_id=entity.id, month=month, year=year).first()
    if p:
        return p
    p = Period(entity=entity, month=month, year=year)
    db.session.add(p)
    db.session.flush()
    if create_recurring:
        create_recurring_drafts(p)
    db.session.commit()
    return p


def vendor_history(vendor: Vendor, limit=5) -> list[Transaction]:
    return (Transaction.query.filter_by(vendor_id=vendor.id).filter(Transaction.draft_status == 'CONFIRMED')
            .order_by(Transaction.invoice_date.desc(), Transaction.id.desc()).limit(limit).all())


def invoice_history_numbers(vendor: Vendor, limit=5) -> list[str]:
    """Nomor invoice lama urut kronologis (terlama -> terbaru)."""
    nums = [t.invoice_no for t in reversed(vendor_history(vendor, limit))]
    if len(nums) < limit and vendor.seed_invoices:
        nums = [x for x in vendor.seed_invoices if x not in nums][-(limit - len(nums)):] + nums
    return nums


def create_recurring_drafts(p: Period):
    """Draft transaksi rutin saat buka masa: salin transaksi masa sebelumnya untuk vendor tagihan_rutin=Ya."""
    pm, py = (12, p.year - 1) if p.month == 1 else (p.month - 1, p.year)
    prev = Period.query.filter_by(entity_id=p.entity_id, month=pm, year=py).first()
    if not prev:
        return 0
    n = 0
    for t in prev.transactions.filter(Transaction.draft_status == 'CONFIRMED').all():
        if not (t.vendor and t.vendor.is_recurring):
            continue
        try:
            inv_date = t.invoice_date.replace(year=p.year, month=p.month)
        except ValueError:
            inv_date = last_day(p.month, p.year)
        hist = invoice_history_numbers(t.vendor)
        db.session.add(Transaction(
            period=p, section=t.section, sort_order=t.sort_order, invoice_date=inv_date,
            invoice_no=invoice_suggest.predict_next(hist, p.month, p.year) or '', vendor=t.vendor, name=t.name,
            npwp_display=t.npwp_display, npwp16=t.npwp16, service_type=t.service_type, kop=t.kop, dpp=t.dpp,
            rate=t.rate, withholding_date=default_withholding_date(inv_date, p.month, p.year),
            final_choice=t.final_choice, draft_status='PERLU_KONFIRMASI', source='RUTIN',
            notes=f'Draft rutin dari {masa_label(pm, py)} – cek nomor & nilai invoice', created_by=actor()))
        n += 1
    return n


def assert_editable(p: Period):
    if p.locked:
        raise PermissionError('Masa sudah di-approve dan terkunci. Minta Admin membuka kunci.')


def next_sort(p: Period, section: str) -> int:
    m = db.session.query(func.max(Transaction.sort_order)).filter_by(period_id=p.id, section=section).scalar()
    return (m or 0) + 1


def find_vendor(npwp: str):
    return Vendor.query.filter_by(npwp16=npwp16(npwp)).first() if npwp else None


# ----------------------------------------------------------------------------- laporan & output
def output_rows(p: Period) -> list[dict]:
    return [t.as_dict() for t in p.transactions.order_by(Transaction.sort_order, Transaction.id).all() if t.is_output]


def start_no(p: Period) -> int:
    e = p.entity
    if not e.numbering_since_year:
        return 1
    q = (Transaction.query.join(Period).filter(Period.entity_id == e.id, Period.year >= e.numbering_since_year)
         .filter((Period.year < p.year) | ((Period.year == p.year) & (Period.month < p.month))))
    return 1 + sum(1 for t in q.all() if t.is_output)


def report_for(p: Period):
    return build_report(p.entity.as_dict(), p.month, p.year, output_rows(p), p.pph21_total or 0, start_no(p))


def default_blocks(entity: Entity) -> tuple[str, list]:
    pr = SignaturePreset.query.filter_by(entity_id=entity.id, is_default=True).first()
    if pr:
        return pr.city, pr.blocks
    return 'Jakarta', []


def signature_config(p: Period, for_pdf=True) -> dict:
    city, blocks = default_blocks(p.entity)
    blocks = p.signature_blocks or blocks
    sig_date = p.signature_date or today_wib()
    stamp = EntityStamp.query.filter_by(entity_id=p.entity_id).first()
    out = []
    for b in blocks[:4]:
        s = db.session.get(Signer, b.get('signer_id')) if b.get('signer_id') else None
        mode = b.get('mode', 'BLANK')
        allowed = False
        if s and s.signature_image_path and mode != 'BLANK':
            if b.get('requires_approval'):
                # ttd pemeriksa hanya tercetak setelah Approve oleh orang itu sendiri
                allowed = p.status == 'APPROVED' and (p.reviewed_by or '').lower() == (s.email or '').lower()
            else:
                allowed = (b.get('authorized_by') or '').lower() == (s.email or '').lower() != ''
        out.append(dict(label=b.get('label', 'Dibuat oleh'), name=s.name if s else b.get('name', ''),
                        title=s.title if s else b.get('title', ''), signer_id=s.id if s else None, mode=mode,
                        image=s.signature_image_path if allowed else None,     # key storage
                        stamp=stamp.image_path if allowed and mode == 'IMAGE_STAMP' and stamp else None,
                        printed_image=allowed))
    return dict(city=p.signature_city or city, date=sig_date, date_mode='PILIH' if p.signature_date else 'HARI_INI',
                blocks=out)


def file_names(p: Period):
    base = f"{p.entity.code}_{BULAN[p.month - 1][:3]}{p.year}"
    return {'XML': f'BPU_{base}.xml', 'PDF': f'Rekap_PPh_{base}.pdf', 'XLSX': f'Rekap_PPh_{base}.xlsx'}


def _sig_with_images(sig: dict) -> dict:
    """Ganti key gambar ttd/stempel dengan isi file (bytes) untuk renderer PDF."""
    blocks = []
    for b in sig['blocks']:
        b = dict(b)
        for k in ('image', 'stamp'):
            b[k] = ST.get(b[k]) if ST.exists(b.get(k)) else None
        blocks.append(b)
    return {**sig, 'blocks': blocks}


def build_outputs(p: Period) -> dict:
    """Return dict kind -> (bytes, filename, errors)."""
    rows = output_rows(p)
    errs = validate_rows(p.month, p.year, rows)
    rep = report_for(p)
    sig = signature_config(p)
    names = file_names(p)
    return dict(
        XML=(bpu_xml(p.entity.npwp16, p.month, p.year, rows).encode('utf-8'), names['XML'], errs),
        PDF=(render_pdf(rep, _sig_with_images(sig), draft=p.status != 'APPROVED'), names['PDF'], []),
        XLSX=(render_xlsx(rep), names['XLSX'], []), report=rep, signature=sig)


def generate_outputs(p: Period) -> list[OutputLog]:
    out = build_outputs(p)
    if out['XML'][2]:
        raise ValueError('XML tidak valid:\n' + '\n'.join(out['XML'][2]))
    ver = (db.session.query(func.max(OutputLog.version)).filter_by(period_id=p.id).scalar() or 0) + 1
    snap = {**out['signature'], 'date': out['signature']['date'].isoformat()}
    logs = []
    for kind in ('XML', 'PDF', 'XLSX'):
        data, name, _ = out[kind]
        path = ST.put(name, data, CTYPE[kind])
        lg = OutputLog(period_id=p.id, kind=kind, version=ver, file_path=path,
                       sha256=hashlib.sha256(data).hexdigest(), signature_snapshot=snap if kind == 'PDF' else None,
                       status='FINAL' if p.status == 'APPROVED' else 'DRAFT', is_final=p.status == 'APPROVED',
                       created_by=actor())
        db.session.add(lg)
        logs.append(lg)
    db.session.commit()
    return logs


def latest_outputs(p: Period) -> dict:
    ver = db.session.query(func.max(OutputLog.version)).filter(
        OutputLog.period_id == p.id, OutputLog.kind != 'EMAIL').scalar()
    if not ver:
        return {}
    return {o.kind: o for o in OutputLog.query.filter_by(period_id=p.id, version=ver).all() if o.kind != 'EMAIL'}


def send_period_email(periods: list[Period]) -> str:
    from .mailer import send_mail
    ctype = CTYPE
    atts, rows, to = [], [], set()
    for p in periods:
        if p.status != 'APPROVED':
            raise PermissionError(f'{p.label} belum di-approve')
        outs = latest_outputs(p)
        if not outs or not all(o.is_final for o in outs.values()):
            outs = {o.kind: o for o in generate_outputs(p)}
        for k in ('XML', 'PDF', 'XLSX'):
            atts.append((ST.basename(outs[k].file_path), ST.get(outs[k].file_path), ctype[k]))
        rep = report_for(p)
        rows.append(f"<tr><td>{p.entity.code}</td><td>{rep.totals['count_bupot']}</td>"
                    f"<td style='text-align:right'>{rep.totals['pph23']:,}</td>"
                    f"<td style='text-align:right'>{rep.totals['final']:,}</td>"
                    f"<td style='text-align:right'><b>{rep.totals['total']:,}</b></td></tr>")
        to.update(x.strip() for x in (p.entity.email_to or '').split(',') if x.strip())
    masa = masa_label(periods[0].month, periods[0].year)
    html = (f"<p>Dengan hormat,</p><p>Terlampir rekap PPh Unifikasi masa <b>{masa}</b> (XML BPU Coretax, PDF laporan, "
            f"dan data sheet Excel per entitas) yang sudah di-approve.</p>"
            f"<table border='1' cellpadding='4' cellspacing='0'><tr><th>Entitas</th><th>Bupot</th><th>PPh 23</th>"
            f"<th>PPh Final</th><th>Total Pajak</th></tr>{''.join(rows)}</table><p>Terima kasih.</p>")
    status, eml_key = send_mail(sorted(to), f'Rekap PPh Unifikasi {masa}', html, atts)
    for p in periods:
        db.session.add(OutputLog(period_id=p.id, kind='EMAIL', version=None, recipients=', '.join(sorted(to)),
                                 status=status, file_path=eml_key, created_by=actor()))
    db.session.commit()
    return status


# ----------------------------------------------------------------------------- faktur
ENTITY_BY_NPWP = lambda: {e.npwp16: e.code for e in Entity.query.all()}


def upload_fakturs(p: Period, files: list[tuple[str, bytes]]) -> dict:
    """Simpan & parse faktur. Faktur yang sudah pernah di-upload (no seri sama) dilewati."""
    res = dict(saved=0, skipped=[], errors=[], other_entity=[])
    for name, data in iter_uploads(files):
        try:
            f = parse_pdf_bytes(data, name)
        except Exception as e:  # pragma: no cover
            res['errors'].append(f'{name}: {e}')
            continue
        if not f['no_faktur']:
            res['errors'].append(f'{name}: nomor seri faktur tidak terbaca')
            continue
        if TaxInvoice.query.filter_by(serial_no=f['no_faktur']).first():
            res['skipped'].append(f['no_faktur'])
            continue
        if f['npwp_pembeli'] != p.entity.npwp16:
            res['other_entity'].append(f"{f['no_faktur']} (pembeli {f['npwp_pembeli']})")
        path = ST.put(name, data, 'application/pdf')
        db.session.add(TaxInvoice(
            serial_no=f['no_faktur'], period_id=p.id, seller_npwp16=f['npwp_penjual'], buyer_npwp16=f['npwp_pembeli'],
            seller_name=f['nama_penjual'], invoice_date=parse_date(f['tanggal']),
            sale_amount=to_dec(f['harga_jual']) if f['harga_jual'] is not None else None,
            vat_base=to_dec(f['dpp_ppn']) if f['dpp_ppn'] is not None else None,
            vat=to_dec(f['ppn']) if f['ppn'] is not None else None, reference=f['referensi'], items=f['item'],
            file_name=name, file_path=path, uploaded_by=actor()))
        res['saved'] += 1
    db.session.commit()
    return res


def period_fakturs(p: Period) -> list[TaxInvoice]:
    return TaxInvoice.query.filter_by(period_id=p.id).order_by(TaxInvoice.invoice_date, TaxInvoice.serial_no).all()


def run_crosscheck(p: Period) -> list[dict]:
    trx = [t.as_dict() for t in p.transactions.order_by(Transaction.section, Transaction.sort_order).all()
           if t.final_choice != 'DIBEBASKAN']
    fak = [f.as_parsed() for f in period_fakturs(p)]
    vend = {v.npwp16: v.name for v in Vendor.query.all()}
    for f in fak:
        f['vendor_name'] = vend.get(f['npwp_penjual'])
    return crosscheck(trx, fak, ENTITY_BY_NPWP())


def apply_faktur_drafts(p: Period) -> dict:
    """Buat / gabungkan draft transaksi dari faktur yang belum punya transaksi + tautkan faktur yang cocok."""
    assert_editable(p)
    fak_objs = {f.serial_no: f for f in period_fakturs(p)}
    fak = [f.as_parsed() for f in fak_objs.values() if f.buyer_npwp16 == p.entity.npwp16]
    cc = run_crosscheck(p)
    # tautkan no faktur ke transaksi yang sudah cocok
    for r in cc:
        if r['transaction_id'] and r['no_faktur']:
            t = db.session.get(Transaction, r['transaction_id'])
            if t and t.faktur_no != r['no_faktur'] and not p.locked:
                t.faktur_no = r['no_faktur']
                t.tax_invoice_id = fak_objs[r['no_faktur']].id if r['no_faktur'] in fak_objs else None
    vendors = {v.npwp16: v.as_dict() for v in Vendor.query.filter_by(active=True).all()}
    kops = {k.code: k.rate for k in TaxObjectCode.query.all()}
    existing = [t.as_dict() for t in p.transactions.filter_by(draft_status='PERLU_KONFIRMASI').all()]
    plan = plan_drafts(fak, vendors, cc, existing, kops, p.month, p.year, p.entity.code)
    for d in plan['new']:
        v = db.session.get(Vendor, d['vendor_id'])
        t = Transaction(period=p, vendor=v, sort_order=next_sort(p, d['section']), created_by=actor(),
                        tax_invoice_id=fak_objs[d['faktur_no']].id,
                        final_choice='DIKENAKAN' if d['section'] == 'FINAL_4_2' else None,
                        **{k: d[k] for k in ('section', 'invoice_date', 'invoice_no', 'name', 'npwp_display', 'npwp16',
                                             'service_type', 'kop', 'dpp', 'rate', 'withholding_date', 'faktur_no',
                                             'notes', 'source', 'draft_status')})
        db.session.add(t)
        db.session.flush()
    for tid, d in plan['merge']:
        t = db.session.get(Transaction, tid)
        for k in ('invoice_date', 'invoice_no', 'dpp', 'withholding_date', 'faktur_no'):
            setattr(t, k, d[k])
        t.tax_invoice_id = fak_objs[d['faktur_no']].id
        t.notes = ((t.notes or '') + ' | digabung dengan faktur ' + d['faktur_no']).strip(' |')
        t.updated_by = actor()
    db.session.commit()
    return dict(new=len(plan['new']), merged=len(plan['merge']), vendor_baru=plan['vendor_baru'],
                diabaikan=plan['diabaikan'])


# ----------------------------------------------------------------------------- import No Bupot (PRD 7.4)
def bupot_candidates():
    rows = []
    for t in Transaction.query.join(Period).all():
        if t.is_output:
            d = t.as_dict()
            rows.append(dict(id=t.id, entity=d['entity'], month=d['month'], year=d['year'], npwp16=t.npwp16, dpp=t.dpp,
                             kop=t.kop, invoice_no=t.invoice_no, bupot_no=t.bupot_no))
    return rows


def preview_bupot(export_rows):
    res, belum = match_bupot(export_rows, bupot_candidates())
    periods = {}
    for e in export_rows:
        ent = Entity.query.filter_by(code=e['entitas']).first()
        p = Period.query.filter_by(entity_id=ent.id, month=e['masa'], year=e['tahun']).first() if ent else None
        periods[(e['entitas'], e['masa'], e['tahun'])] = p
    return res, belum, periods


def commit_bupot(res: list[dict], overwrite_ids: set[int], manual: dict[int, int]) -> int:
    """res dari preview; manual: index baris -> transaction_id pilihan user. Return jumlah transaksi terisi."""
    n = 0
    now = datetime.now(WIB)
    for i, r in enumerate(res):
        tid = manual.get(i) or r.get('transaction_id')
        if not tid:
            continue
        if r['status'] == 'Nomor beda dengan data lama' and tid not in overwrite_ids:
            continue
        t = db.session.get(Transaction, tid)
        e = r['export']
        t.bupot_no, t.bupot_status, t.bupot_tte_status = e['bupot'], e['status'], e['tte']
        t.reported_in_spt, t.bupot_imported_at = e.get('spt'), now
        n += 1
    db.session.commit()
    return n


def audit_for(table, row_id):
    return AuditLog.query.filter_by(table_name=table, row_id=row_id).order_by(AuditLog.at.desc()).all()
