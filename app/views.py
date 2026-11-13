"""Halaman web."""
from __future__ import annotations

import io
import json
import os
import uuid
from decimal import InvalidOperation

from flask import (Blueprint, Response, abort, current_app, flash, g, jsonify, redirect, render_template, request,
                   send_file, url_for)

from . import services as S
from . import storage as ST
from .auth import ROLES, has_role, login_required, roles_required
from .core import bulk as B
from .core import invoice_suggest
from .core.matching import read_coretax_export
from .core.rules import (BULAN, SECTIONS, default_withholding_date, last_day, masa_label, npwp16, parse_date,
                         parse_tarif, tanggal_indo, to_dec)
from .models import (AppUser, AuditLog, BupotImport, Entity, EntityStamp, OutputLog, Period, Signer, SignaturePreset,
                     TaxInvoice, TaxObjectCode, Transaction, Vendor, db)

bp = Blueprint('main', __name__)
TS, MGR, ADM = 'TAX_SUPPORT', 'MANAGER_FAT', 'ADMIN'


@bp.app_context_processor
def ctx():
    return dict(SECTIONS=SECTIONS, BULAN=BULAN, ROLES=ROLES, has_role=has_role, masa_label=masa_label,
                tanggal_indo=tanggal_indo)


@bp.app_template_filter('rp')
def rp(v):
    try:
        return f'{int(round(float(v))):,}'.replace(',', '.')
    except (TypeError, ValueError):
        return v or ''


@bp.app_template_filter('dt')
def dt(v):
    return v.strftime('%d/%m/%Y') if v else ''


def _period(pid) -> Period:
    p = db.session.get(Period, pid)
    if not p:
        abort(404)
    return p


def _guard(p: Period):
    try:
        S.assert_editable(p)
    except PermissionError as e:
        flash(str(e), 'error')
        return redirect(url_for('main.period', pid=p.id))
    return None


# ----------------------------------------------------------------------------- dashboard
@bp.route('/')
@login_required
def dashboard():
    ents = Entity.query.order_by(Entity.code).all()
    periods = Period.query.order_by(Period.year.desc(), Period.month.desc()).all()
    rows = []
    for p in periods[:24]:
        rep = S.report_for(p)
        rows.append((p, rep.totals))
    t = S.today_wib()
    dm, dy = (12, t.year - 1) if t.month == 1 else (t.month - 1, t.year)
    return render_template('dashboard.html', ents=ents, rows=rows, dm=dm, dy=dy)


@bp.route('/period/open', methods=['POST'])
@roles_required(TS)
def period_open():
    ent = Entity.query.filter_by(code=request.form['entity']).first_or_404()
    m, y = int(request.form['month']), int(request.form['year'])
    existed = Period.query.filter_by(entity_id=ent.id, month=m, year=y).first()
    p = S.get_or_open_period(ent, m, y)
    if not existed:
        n = p.transactions.filter_by(source='RUTIN').count()
        flash(f'Masa {p.label} dibuka. {n} draft transaksi rutin dibuat (perlu konfirmasi).', 'ok')
    return redirect(url_for('main.period', pid=p.id))


# ----------------------------------------------------------------------------- masa & transaksi
@bp.route('/period/<int:pid>')
@login_required
def period(pid):
    p = _period(pid)
    trx = p.transactions.order_by(Transaction.section, Transaction.sort_order, Transaction.id).all()
    by_sec = {s: [t for t in trx if t.section == s] for s in SECTIONS}
    rep = S.report_for(p)
    outs = S.latest_outputs(p)
    history = OutputLog.query.filter_by(period_id=p.id).order_by(OutputLog.created_at.desc()).all()
    sig = S.signature_config(p)
    warn_sig = p.signature_date and p.signature_date < last_day(p.month, p.year)
    return render_template('period.html', p=p, by_sec=by_sec, rep=rep, outs=outs, history=history, sig=sig,
                           warn_sig=warn_sig, drafts=sum(1 for t in trx if t.draft_status == 'PERLU_KONFIRMASI'))


def _form_trx(p: Period, t: Transaction | None):
    f = request.form
    errs = []
    v = db.session.get(Vendor, int(f['vendor_id'])) if f.get('vendor_id') else None
    try:
        inv_date = parse_date(f['invoice_date'])
        dpp = to_dec(f['dpp'].replace('.', '').replace(',', '.')) if ',' in f['dpp'] or f['dpp'].count('.') > 1 \
            else to_dec(f['dpp'])
        rate = parse_tarif(f['rate'])
        wd = parse_date(f.get('withholding_date')) or default_withholding_date(inv_date, p.month, p.year)
    except (ValueError, InvalidOperation, KeyError) as e:
        return None, [f'Input tidak valid: {e}']
    if (wd.year, wd.month) != (p.year, p.month):
        errs.append('Tanggal pemotongan wajib di dalam masa')
    if dpp <= 0:
        errs.append('DPP harus > 0')
    kop = f.get('kop') or None
    section = f['section']
    if section != 'PPH21_FREELANCE' and not kop:
        errs.append('KOP wajib diisi')
    if kop == '28-403-01':
        errs.append('KOP 28-403-01 ditolak Coretax – gunakan 28-403-02')
    np16 = npwp16(f.get('npwp') or (v.npwp16 if v else ''))
    if len(np16) != 16:
        errs.append('NPWP harus 15/16 digit')
    if v and not v.withhold_pph23 and section != 'PPH21_FREELANCE':
        errs.append(f'{v.name} tidak dipotong PPh 23 (master vendor)')
    dup = Transaction.query.filter(Transaction.npwp16 == np16, Transaction.invoice_no == f['invoice_no'].strip())
    if t:
        dup = dup.filter(Transaction.id != t.id)
    if dup.first():
        errs.append('Nomor invoice ini sudah ada untuk vendor yang sama')
    if errs:
        return None, errs
    new = t is None
    if new:
        t = Transaction(period=p, created_by=S.actor(), source='MANUAL', draft_status='CONFIRMED')
        db.session.add(t)
    if new or t.section != section:
        t.sort_order = S.next_sort(p, section)
    t.section, t.invoice_date, t.invoice_no = section, inv_date, f['invoice_no'].strip()
    t.vendor = v
    t.name = f.get('name') or (v.name if v else '')
    t.npwp_display = f.get('npwp') or (v.npwp_display if v else np16)
    t.npwp16, t.kop, t.dpp, t.rate, t.withholding_date = np16, kop, dpp, rate, wd
    t.service_type, t.description, t.notes = f.get('service_type'), f.get('description'), f.get('notes')
    t.faktur_no = f.get('faktur_no') or None
    t.final_choice = f.get('final_choice') if section == 'FINAL_4_2' else None
    t.updated_by = S.actor()
    return t, []


@bp.route('/period/<int:pid>/trx/new', methods=['GET', 'POST'])
@bp.route('/period/<int:pid>/trx/<int:tid>', methods=['GET', 'POST'])
@roles_required(TS)
def trx_edit(pid, tid=None):
    p = _period(pid)
    t = db.session.get(Transaction, tid) if tid else None
    if request.method == 'POST':
        if (r := _guard(p)):
            return r
        obj, errs = _form_trx(p, t)
        if errs:
            for e in errs:
                flash(e, 'error')
        else:
            if request.form.get('confirm'):
                obj.draft_status = 'CONFIRMED'
            db.session.commit()
            flash('Transaksi disimpan.', 'ok')
            if request.form.get('again'):
                return redirect(url_for('main.trx_edit', pid=p.id))
            return redirect(url_for('main.period', pid=p.id))
    kops = TaxObjectCode.query.filter_by(active=True).order_by(TaxObjectCode.code).all()
    return render_template('trx_form.html', p=p, t=t, kops=kops, f=request.form if request.method == 'POST' else None)


@bp.route('/period/<int:pid>/trx/<int:tid>/delete', methods=['POST'])
@roles_required(TS)
def trx_delete(pid, tid):
    p = _period(pid)
    if (r := _guard(p)):
        return r
    t = db.session.get(Transaction, tid)
    db.session.delete(t)
    db.session.commit()
    flash('Transaksi dihapus.', 'ok')
    return redirect(url_for('main.period', pid=p.id))


@bp.route('/period/<int:pid>/confirm', methods=['POST'])
@roles_required(TS)
def trx_confirm(pid):
    """Konfirmasi massal draft (ids terpilih)."""
    p = _period(pid)
    if (r := _guard(p)):
        return r
    ids = [int(x) for x in request.form.getlist('ids')]
    n, skipped = 0, []
    for t in p.transactions.filter(Transaction.id.in_(ids)).all():
        if t.section != 'PPH21_FREELANCE' and not t.kop:
            skipped.append(t.invoice_no)
            continue
        t.draft_status = 'CONFIRMED'
        t.updated_by = S.actor()
        n += 1
    db.session.commit()
    flash(f'{n} transaksi dikonfirmasi.' + (f' Dilewati (KOP kosong): {", ".join(skipped)}' if skipped else ''),
          'ok' if not skipped else 'warn')
    return redirect(url_for('main.period', pid=p.id))


@bp.route('/period/<int:pid>/pph21', methods=['POST'])
@roles_required(TS)
def period_pph21(pid):
    p = _period(pid)
    if (r := _guard(p)):
        return r
    p.pph21_total = to_dec(request.form.get('pph21_total', '0').replace('.', '').replace(',', '.') or 0)
    db.session.commit()
    flash('PPh 21 bulanan disimpan.', 'ok')
    return redirect(url_for('main.period', pid=p.id))


# ----------------------------------------------------------------------------- API (autocomplete & saran invoice)
@bp.route('/api/vendors')
@login_required
def api_vendors():
    q = (request.args.get('q') or '').strip().lower()
    vs = Vendor.query.filter_by(active=True).all()
    res = []
    for v in vs:
        hay = ' '.join([v.name.lower(), v.npwp16] + [a.lower() for a in (v.aliases or [])])
        if not q or q in hay or q.replace('.', '').replace('-', '') in v.npwp16:
            d = v.as_dict()
            d['default_rate'] = float(v.default_rate) if v.default_rate is not None else None
            d['special'] = v.special_rules_text
            res.append(d)
    res.sort(key=lambda d: (not d['name'].lower().replace('pt ', '').startswith(q), d['name']))
    return jsonify(res[:15])


@bp.route('/api/vendor/<int:vid>/invoices')
@login_required
def api_vendor_invoices(vid):
    v = db.session.get(Vendor, vid) or abort(404)
    m, y = int(request.args.get('month', 1)), int(request.args.get('year', 2026))
    last5 = S.vendor_history(v, 5)
    hist = S.invoice_history_numbers(v, 5)
    inv = request.args.get('inv', '')
    exclude = request.args.get('tid', type=int)
    existing = {t.invoice_no for t in Transaction.query.filter_by(npwp16=v.npwp16).all() if t.id != exclude}
    color, msg = invoice_suggest.validate(inv, hist, existing) if inv else ('', '')
    return jsonify(dict(
        last=[dict(invoice_no=t.invoice_no, date=t.invoice_date.isoformat(), dpp=float(t.dpp),
                   masa=masa_label(t.period.month, t.period.year), final_choice=t.final_choice) for t in last5]
        or [dict(invoice_no=x, date='', dpp=None, masa='master', final_choice=None) for x in reversed(hist)],
        prediction=invoice_suggest.predict_next(hist, m, y), color=color, message=msg))


# ----------------------------------------------------------------------------- faktur
@bp.route('/period/<int:pid>/faktur', methods=['GET', 'POST'])
@login_required
def faktur(pid):
    p = _period(pid)
    if request.method == 'POST':
        if not has_role(TS):
            abort(403)
        files = [(f.filename, f.read()) for f in request.files.getlist('files') if f.filename]
        try:
            res = S.upload_fakturs(p, files)
        except ValueError as e:
            flash(str(e), 'error')
            return redirect(url_for('main.faktur', pid=p.id))
        flash(f"{res['saved']} faktur tersimpan. Duplikat dilewati: {len(res['skipped'])}.", 'ok')
        for e in res['errors']:
            flash(e, 'error')
        if res['other_entity']:
            flash('Faktur dengan pembeli entitas lain: ' + ', '.join(res['other_entity']), 'warn')
        if not p.locked and request.form.get('auto_draft'):
            r = S.apply_faktur_drafts(p)
            flash(f"Draft dibuat: {r['new']}, digabung ke draft yang ada: {r['merged']}.", 'ok')
        return redirect(url_for('main.faktur', pid=p.id))
    cc = S.run_crosscheck(p)
    fak = S.period_fakturs(p)
    vendors = {v.npwp16 for v in Vendor.query.all()}
    vendor_baru = [f for f in fak if f.seller_npwp16 not in vendors]
    return render_template('faktur.html', p=p, cc=cc, fak=fak, vendor_baru=vendor_baru)


@bp.route('/period/<int:pid>/faktur/upload', methods=['POST'])
@roles_required(TS)
def faktur_upload_api(pid):
    """Upload bertahap dari browser (dipakai di Vercel: maks ~4,5 MB per request). Return JSON."""
    p = _period(pid)
    files = [(f.filename, f.read()) for f in request.files.getlist('files') if f.filename]
    try:
        res = S.upload_fakturs(p, files)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(res)


@bp.route('/period/<int:pid>/faktur/drafts', methods=['POST'])
@roles_required(TS)
def faktur_drafts(pid):
    p = _period(pid)
    if (r := _guard(p)):
        return r
    r = S.apply_faktur_drafts(p)
    flash(f"Draft dibuat: {r['new']}, digabung: {r['merged']}, vendor baru: {len(r['vendor_baru'])}, "
          f"diabaikan: {len(r['diabaikan'])}.", 'ok')
    return redirect(url_for('main.faktur', pid=p.id))


@bp.route('/faktur/<int:fid>/tidak-dipotong', methods=['POST'])
@roles_required(TS)
def faktur_not_withheld(fid):
    f = db.session.get(TaxInvoice, fid) or abort(404)
    if request.form.get('undo'):
        f.not_withheld_reason = None
    else:
        f.not_withheld_reason = request.form.get('reason') or 'Tidak dipotong'
        # hapus draft yang sudah terbuat dari faktur ini (bila belum dikonfirmasi)
        for t in Transaction.query.filter_by(faktur_no=f.serial_no, draft_status='PERLU_KONFIRMASI').all():
            db.session.delete(t)
    db.session.commit()
    return redirect(url_for('main.faktur', pid=f.period_id))


@bp.route('/faktur/<int:fid>/file')
@login_required
def faktur_file(fid):
    f = db.session.get(TaxInvoice, fid) or abort(404)
    return send_file(io.BytesIO(ST.get(f.file_path)), mimetype='application/pdf', download_name=f.file_name)


# ----------------------------------------------------------------------------- upload massal
def _bulk_ctx():
    vs = Vendor.query.all()
    by_name = {v.name.lower(): v.as_dict() for v in vs}
    by_npwp = {}
    for v in vs:
        by_npwp.setdefault(v.npwp16, v.as_dict())
    kops = {k.code: dict(rate=k.rate) for k in TaxObjectCode.query.all()}
    ents = {e.code for e in Entity.query.all()}
    existing = {(t.npwp16, t.invoice_no) for t in Transaction.query.all()}
    locked = {(p.entity.code, p.month, p.year) for p in Period.query.filter_by(status='APPROVED').all()}
    return by_name, by_npwp, kops, ents, existing, locked


@bp.route('/bulk', methods=['GET', 'POST'])
@roles_required(TS)
def bulk():
    if request.method == 'GET':
        return render_template('bulk.html', res=None)
    f = request.files.get('file')
    if not f or not f.filename:
        flash('Pilih file .xlsx atau .csv', 'error')
        return redirect(url_for('main.bulk'))
    try:
        trx, p21 = B.read_file(f.read(), f.filename)
    except Exception as e:
        flash(f'File tidak bisa dibaca: {e}', 'error')
        return redirect(url_for('main.bulk'))
    res = B.validate_rows(trx, *_bulk_ctx())
    pph21 = B.read_pph21(p21)
    token = uuid.uuid4().hex
    ST.put_json(token, dict(res=res, pph21=pph21, file=f.filename))
    res = ST.get_json(token)['res']
    stats = {k: sum(r['status'] == k for r in res) for k in ('OK', 'Peringatan', 'Error')}
    return render_template('bulk.html', res=res, token=token, stats=stats, pph21=pph21, mode=request.form.get('mode', 'TAMBAH'))


@bp.route('/bulk/<token>/koreksi')
@roles_required(TS)
def bulk_koreksi(token):
    res = ST.get_json(token)['res']
    return send_file(io.BytesIO(B.correction_file(res)), download_name='Koreksi_Upload_Transaksi.xlsx',
                     as_attachment=True)


@bp.route('/bulk/<token>/commit', methods=['POST'])
@roles_required(TS)
def bulk_commit(token):
    saved = ST.get_json(token)
    mode = request.form.get('mode', 'TAMBAH')
    rows = [r['data'] for r in saved['res'] if r['data']]
    ents = {e.code: e for e in Entity.query.all()}
    touched = {}
    for d in rows:
        key = (d['entity'], d['month'], d['year'])
        if key not in touched:
            p = S.get_or_open_period(ents[d['entity']], d['month'], d['year'], create_recurring=False)
            if p.locked:
                continue
            if mode == 'GANTI':
                for t in p.transactions.all():
                    db.session.delete(t)
                db.session.flush()
            touched[key] = p
    n = upd = 0
    with db.session.no_autoflush:
        n, upd = _bulk_save(rows, touched, mode)
    for r in saved['pph21']:
        e = ents.get(r['entity'])
        if e:
            p = S.get_or_open_period(e, r['month'], r['year'], create_recurring=False)
            if not p.locked:
                p.pph21_total = to_dec(r['total'])
    db.session.commit()
    flash(f'Upload selesai ({mode}): {n} transaksi baru, {upd} diperbarui, '
          f'{sum(1 for r in saved["res"] if r["status"] == "Error")} baris error dilewati.', 'ok')
    return redirect(url_for('main.dashboard'))


def _bulk_save(rows, touched, mode):
    n = upd = 0
    for d in rows:
        p = touched.get((d['entity'], d['month'], d['year']))
        if not p:
            continue
        v = db.session.get(Vendor, d['vendor_id']) if d.get('vendor_id') else None
        if v is None:
            v = Vendor(name=d['name'], npwp16=d['npwp16'], nitku=d['npwp16'] + '000000', npwp_display=d['npwp_display'],
                       entity_hint=d['entity'], group='Non-QRIS', default_section=d['section'], default_kop=d['kop'],
                       default_rate=to_dec(d['rate']), default_service=d.get('service_type'), aliases=[], auto_rules={})
            db.session.add(v)
            db.session.flush()
        existing = Transaction.query.filter_by(npwp16=d['npwp16'], invoice_no=d['invoice_no']).first() \
            if mode == 'TAMBAH' else None
        t = existing or Transaction(period=p, created_by=S.actor(), source='BULK')
        if existing:
            if existing.period.locked:
                continue
            upd += 1
        else:
            db.session.add(t)
            t.sort_order = S.next_sort(p, d['section'])
            n += 1
        t.period = p
        for k in ('section', 'invoice_no', 'name', 'npwp_display', 'npwp16', 'description', 'service_type', 'kop',
                  'faktur_no', 'bupot_no', 'notes'):
            setattr(t, k, d.get(k))
        t.invoice_date, t.withholding_date = parse_date(d['invoice_date']), parse_date(d['withholding_date'])
        t.dpp, t.rate, t.vendor, t.draft_status = to_dec(d['dpp']), to_dec(d['rate']), v, 'CONFIRMED'
        t.final_choice = 'DIKENAKAN' if d['section'] == 'FINAL_4_2' else None
        t.updated_by = S.actor()
        db.session.flush()      # baris sudah lengkap -> aman di-flush agar nomor urut berikutnya benar
    return n, upd


@bp.route('/bulk/template')
@login_required
def bulk_template():
    path = os.path.join(current_app.config['PAKET_DIR'], 'templates', 'Template_Bulk_Transaksi_PPh23.xlsx')
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True)


# ----------------------------------------------------------------------------- tanda tangan
@bp.route('/period/<int:pid>/signature', methods=['GET', 'POST'])
@roles_required(TS, MGR)
def signature(pid):
    p = _period(pid)
    signers = Signer.query.filter_by(active=True).all()
    presets = SignaturePreset.query.filter_by(entity_id=p.entity_id).all()
    if request.method == 'POST':
        f = request.form
        if f.get('preset_id'):
            pr = db.session.get(SignaturePreset, int(f['preset_id']))
            p.signature_blocks, p.signature_city = pr.blocks, pr.city
        else:
            blocks = []
            me = (g.user.email or '').lower()
            for i in range(1, 5):
                if not f.get(f'label_{i}'):
                    continue
                sid = int(f[f'signer_{i}']) if f.get(f'signer_{i}') else None
                s = db.session.get(Signer, sid) if sid else None
                mode = f.get(f'mode_{i}', 'BLANK')
                b = dict(order=i, label=f[f'label_{i}'], signer_id=sid, mode=mode,
                         requires_approval=bool(f.get(f'approval_{i}')))
                old = next((x for x in (p.signature_blocks or []) if x.get('signer_id') == sid), {})
                if mode != 'BLANK' and s and (s.email or '').lower() == me:
                    b['authorized_by'] = me          # setiap orang hanya bisa memakai ttd-nya sendiri
                elif mode != 'BLANK' and old.get('authorized_by') and old.get('mode') == mode:
                    b['authorized_by'] = old['authorized_by']
                blocks.append(b)
            p.signature_blocks = blocks
            p.signature_city = f.get('city') or 'Jakarta'
        p.signature_date = parse_date(f.get('sig_date')) if f.get('date_mode') == 'PILIH' else None
        if f.get('save_preset'):
            db.session.add(SignaturePreset(entity_id=p.entity_id, name=f['save_preset'], city=p.signature_city,
                                           blocks=p.signature_blocks))
        db.session.commit()
        if p.signature_date and p.signature_date < last_day(p.month, p.year):
            flash('Peringatan: tanggal tanda tangan sebelum akhir masa.', 'warn')
        flash('Pengaturan tanda tangan disimpan.', 'ok')
        return redirect(url_for('main.period', pid=p.id))
    city, blocks = S.default_blocks(p.entity)
    return render_template('signature.html', p=p, signers=signers, presets=presets,
                           blocks=p.signature_blocks or blocks, city=p.signature_city or city)


@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    me = Signer.query.filter(db.func.lower(Signer.email) == g.user.email.lower()).first()
    if request.method == 'POST':
        f = request.files.get('image')
        if not me:
            flash('Akun Anda belum ditautkan ke data penanda tangan. Minta Admin mengisi email di Master Penanda Tangan.',
                  'error')
        elif f and f.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            ST.delete(me.signature_image_path)
            me.signature_image_path = ST.put(f'signer_{me.id}{os.path.splitext(f.filename)[1].lower()}', f.read(),
                                             f.mimetype or 'image/png')
            db.session.commit()
            flash('Gambar tanda tangan disimpan.', 'ok')
        return redirect(url_for('main.profile'))
    return render_template('profile.html', me=me)


# ----------------------------------------------------------------------------- output, approval, email
@bp.route('/period/<int:pid>/preview/<kind>')
@login_required
def preview(pid, kind):
    p = _period(pid)
    out = S.build_outputs(p)
    data, name, errs = out[kind.upper()]
    mt = {'XML': 'application/xml', 'PDF': 'application/pdf',
          'XLSX': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}[kind.upper()]
    if kind.upper() == 'XML' and errs:
        return Response('<!-- PERINGATAN:\n' + '\n'.join(errs) + '\n-->\n' + data.decode(), mimetype='text/plain')
    return send_file(io.BytesIO(data), mimetype=mt, download_name=name, as_attachment=kind.upper() == 'XLSX')


@bp.route('/period/<int:pid>/generate', methods=['POST'])
@roles_required(TS, MGR)
def generate(pid):
    p = _period(pid)
    if p.transactions.filter_by(draft_status='PERLU_KONFIRMASI').count():
        flash('Masih ada draft "Perlu konfirmasi" – draft tidak ikut di output.', 'warn')
    try:
        logs = S.generate_outputs(p)
        flash(f'Output versi {logs[0].version} dibuat ({logs[0].status}).', 'ok')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('main.period', pid=p.id))


@bp.route('/output/<int:oid>')
@login_required
def output_file(oid):
    o = db.session.get(OutputLog, oid) or abort(404)
    if not o.file_path:
        abort(404)
    return send_file(io.BytesIO(ST.get(o.file_path)), as_attachment=True, download_name=ST.basename(o.file_path))


@bp.route('/period/<int:pid>/submit', methods=['POST'])
@roles_required(TS)
def submit(pid):
    p = _period(pid)
    if p.transactions.filter_by(draft_status='PERLU_KONFIRMASI').count():
        flash('Konfirmasi atau hapus semua draft sebelum mengajukan approval.', 'error')
        return redirect(url_for('main.period', pid=p.id))
    errs = S.validate_rows(p.month, p.year, S.output_rows(p))
    if errs:
        flash('Data belum valid: ' + '; '.join(errs), 'error')
        return redirect(url_for('main.period', pid=p.id))
    p.status, p.submitted_by, p.submitted_at = 'SUBMITTED', S.actor(), S.datetime.now(S.WIB)
    db.session.commit()
    S.generate_outputs(p)
    flash('Diajukan ke Manager FAT untuk approval.', 'ok')
    return redirect(url_for('main.period', pid=p.id))


@bp.route('/period/<int:pid>/approve', methods=['POST'])
@roles_required(MGR)
def approve(pid):
    p = _period(pid)
    if p.status != 'SUBMITTED':
        flash('Masa harus diajukan dulu oleh Tax Support.', 'error')
        return redirect(url_for('main.period', pid=p.id))
    if request.form.get('action') == 'reject':
        p.status, p.review_note = 'DRAFT', request.form.get('note')
        flash('Dikembalikan ke Tax Support.', 'ok')
    else:
        p.status, p.reviewed_by, p.reviewed_at = 'APPROVED', g.user.email, S.datetime.now(S.WIB)
        p.review_note = request.form.get('note')
        flash('Masa di-approve dan dikunci. Output final dibuat.', 'ok')
    db.session.commit()
    if p.status == 'APPROVED':
        S.generate_outputs(p)
    return redirect(url_for('main.period', pid=p.id))


@bp.route('/period/<int:pid>/unlock', methods=['POST'])
@roles_required(ADM)
def unlock(pid):
    p = _period(pid)
    p.status = 'DRAFT'
    db.session.commit()
    flash('Kunci masa dibuka (tercatat di audit trail).', 'warn')
    return redirect(url_for('main.period', pid=p.id))


@bp.route('/send', methods=['POST'])
@roles_required(TS, MGR)
def send():
    ids = [int(x) for x in request.form.getlist('pids')]
    ps = [_period(i) for i in ids]
    try:
        st = S.send_period_email(ps)
        flash('Email: ' + st, 'ok')
    except Exception as e:
        flash(f'Gagal kirim email: {e}', 'error')
    return redirect(request.referrer or url_for('main.dashboard'))


# ----------------------------------------------------------------------------- import No Bupot Coretax
@bp.route('/bupot-import', methods=['GET', 'POST'])
@roles_required(TS)
def bupot_import():
    if request.method == 'GET':
        return render_template('bupot.html', res=None)
    f = request.files.get('file')
    try:
        exp = read_coretax_export(io.BytesIO(f.read()), {e.nitku: e.code for e in Entity.query.all()})
    except Exception as e:
        flash(f'File export tidak bisa dibaca: {e}', 'error')
        return redirect(url_for('main.bupot_import'))
    res, belum, periods = S.preview_bupot(exp)
    not_approved = [f'{k[0]} {masa_label(k[1], k[2])}' for k, p in periods.items() if not p or p.status != 'APPROVED']
    token = uuid.uuid4().hex
    ST.put_json(token, dict(res=res, file=f.filename))
    trx = {t.id: t for t in Transaction.query.filter(Transaction.id.in_(
        [c for r in res for c in r.get('candidates', [])] + [r['transaction_id'] for r in res if r['transaction_id']])).all()}
    return render_template('bupot.html', res=res, belum=belum, token=token, not_approved=not_approved, trx=trx,
                           matched=sum(r['status'] == 'Cocok' for r in res))


@bp.route('/bupot-import/<token>', methods=['POST'])
@roles_required(TS)
def bupot_commit(token):
    saved = ST.get_json(token)
    res = saved['res']
    overwrite = {int(x) for x in request.form.getlist('overwrite')}
    manual = {int(k[7:]): int(v) for k, v in request.form.items() if k.startswith('manual_') and v}
    n = S.commit_bupot(res, overwrite, manual)
    db.session.add(BupotImport(file_name=saved['file'], rows_total=len(res), rows_matched=n, result=res,
                               imported_by=S.actor()))
    db.session.commit()
    # regenerate PDF/XLSX untuk masa terkait
    regen = set()
    for r in res:
        tid = r.get('transaction_id')
        if tid:
            t = db.session.get(Transaction, tid)
            regen.add(t.period_id)
    for pid in regen:
        S.generate_outputs(db.session.get(Period, pid))
    flash(f'No Bupot terisi untuk {n} transaksi; output {len(regen)} masa dibuat ulang.', 'ok')
    return redirect(url_for('main.dashboard'))


# ----------------------------------------------------------------------------- master
@bp.route('/master/vendors')
@login_required
def vendors():
    q = request.args.get('q', '').lower()
    vs = [v for v in Vendor.query.order_by(Vendor.name).all() if q in v.name.lower() or q in v.npwp16]
    return render_template('vendors.html', vs=vs, q=q)


@bp.route('/master/vendors/new', methods=['GET', 'POST'])
@bp.route('/master/vendors/<int:vid>', methods=['GET', 'POST'])
@roles_required(TS)
def vendor_edit(vid=None):
    v = db.session.get(Vendor, vid) if vid else None
    if request.method == 'POST':
        f = request.form
        if not v:
            v = Vendor(aliases=[], auto_rules={})
            db.session.add(v)
        v.name = f['name'].strip()
        v.npwp16 = npwp16(f['npwp'])
        v.npwp_display = f.get('npwp_display') or f['npwp']
        v.nitku = f.get('nitku') or v.npwp16 + '000000'
        v.entity_hint, v.group = f.get('entity_hint'), f.get('group')
        v.default_service, v.default_kop = f.get('default_service'), f.get('default_kop') or None
        v.default_rate = parse_tarif(f['default_rate']) if f.get('default_rate') else None
        v.default_section = f.get('default_section')
        v.is_qris = v.group == 'QRIS'
        v.withhold_pph23 = bool(f.get('withhold_pph23'))
        v.is_recurring = bool(f.get('is_recurring'))
        v.active = bool(f.get('active'))
        v.aliases = [a.strip().lower() for a in f.get('aliases', '').split(',') if a.strip()]
        try:
            v.auto_rules = json.loads(f.get('auto_rules') or '{}')
        except json.JSONDecodeError:
            flash('Aturan otomatis bukan JSON valid – tidak diubah.', 'warn')
        db.session.commit()
        flash('Vendor disimpan.', 'ok')
        return redirect(f.get('next') or url_for('main.vendors'))
    pre = dict(name=request.args.get('name', ''), npwp=request.args.get('npwp', ''))
    kops = TaxObjectCode.query.order_by(TaxObjectCode.code).all()
    return render_template('vendor_form.html', v=v, pre=pre, kops=kops,
                           hist=S.vendor_history(v, 5) if v else [], next=request.args.get('next', ''))


@bp.route('/master/kop', methods=['GET', 'POST'])
@login_required
def kop():
    if request.method == 'POST':
        if not has_role(ADM, TS):
            abort(403)
        f = request.form
        k = db.session.get(TaxObjectCode, f['code']) or TaxObjectCode(code=f['code'])
        k.name, k.tax_type = f['name'], f['tax_type']
        k.is_final = bool(f.get('is_final'))
        k.rate = parse_tarif(f['rate'])
        k.verified = f.get('verified')
        k.active = bool(f.get('active', '1'))
        db.session.add(k)
        db.session.commit()
        flash('KOP disimpan.', 'ok')
        return redirect(url_for('main.kop'))
    return render_template('kop.html', kops=TaxObjectCode.query.order_by(TaxObjectCode.code).all())


@bp.route('/master/entities', methods=['GET', 'POST'])
@roles_required(ADM)
def entities():
    if request.method == 'POST':
        f = request.form
        e = db.session.get(Entity, int(f['id']))
        for k in ('legal_name', 'former_name', 'report_title', 'report_style', 'email_to'):
            setattr(e, k, f.get(k) or None)
        e.npwp16 = npwp16(f['npwp16'])
        e.nitku = e.npwp16 + '000000'
        e.numbering_since_year = int(f['numbering_since_year']) if f.get('numbering_since_year') else None
        st = request.files.get('stamp')
        if st and st.filename:
            es = EntityStamp.query.filter_by(entity_id=e.id).first() or EntityStamp(entity_id=e.id)
            ST.delete(es.image_path)
            es.image_path = ST.put(f'stamp_{e.id}{os.path.splitext(st.filename)[1].lower()}', st.read(),
                                   st.mimetype or 'image/png')
            db.session.add(es)
        db.session.commit()
        flash('Entitas disimpan.', 'ok')
        return redirect(url_for('main.entities'))
    return render_template('entities.html', ents=Entity.query.all())


@bp.route('/master/signers', methods=['GET', 'POST'])
@roles_required(ADM)
def signers():
    if request.method == 'POST':
        f = request.form
        s = db.session.get(Signer, int(f['id'])) if f.get('id') else Signer()
        s.name, s.title, s.email = f['name'], f['title'], (f.get('email') or '').lower() or None
        s.active = bool(f.get('active'))
        db.session.add(s)
        db.session.commit()
        flash('Penanda tangan disimpan.', 'ok')
        return redirect(url_for('main.signers'))
    return render_template('signers.html', signers=Signer.query.all())


@bp.route('/master/users', methods=['GET', 'POST'])
@roles_required(ADM)
def users():
    if request.method == 'POST':
        f = request.form
        u = db.session.get(AppUser, int(f['id'])) if f.get('id') else AppUser(email=f['email'].lower())
        u.name, u.role, u.active = f.get('name'), f['role'], bool(f.get('active'))
        db.session.add(u)
        db.session.commit()
        flash('User disimpan.', 'ok')
        return redirect(url_for('main.users'))
    return render_template('users.html', users=AppUser.query.order_by(AppUser.email).all())


@bp.route('/admin/seed', methods=['POST'])
@roles_required(ADM)
def admin_seed():
    """Import master + data historis dari folder paket/ (sekali, saat database masih kosong)."""
    from .seed import seed_all
    msgs = []
    seed_all(current_app.config['PAKET_DIR'], log=msgs.append)
    flash(' '.join(msgs), 'ok')
    return redirect(url_for('main.dashboard'))


@bp.route('/audit')
@roles_required(MGR, ADM)
def audit():
    q = AuditLog.query
    if request.args.get('table'):
        q = q.filter_by(table_name=request.args['table'])
    if request.args.get('row'):
        q = q.filter_by(row_id=int(request.args['row']))
    return render_template('audit.html', logs=q.order_by(AuditLog.at.desc()).limit(500).all())
