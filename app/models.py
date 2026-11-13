"""Model database (SQLAlchemy) – mengikuti schema/database.sql dengan beberapa kolom tambahan (lihat ASSUMPTIONS.md).
Default SQLite; set DATABASE_URL=postgresql+psycopg://... untuk PostgreSQL."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON, UniqueConstraint, event, inspect

from .core.rules import SECTIONS, pph, pph_rounded

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc)


class AppUser(db.Model):
    __tablename__ = 'app_user'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    name = db.Column(db.String(200))
    role = db.Column(db.String(20), nullable=False, default='TAX_SUPPORT')  # TAX_SUPPORT / MANAGER_FAT / ADMIN
    active = db.Column(db.Boolean, default=True)


class Entity(db.Model):
    __tablename__ = 'entity'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(5), unique=True, nullable=False)
    legal_name = db.Column(db.Text, nullable=False)
    former_name = db.Column(db.Text)
    npwp16 = db.Column(db.String(16), nullable=False)
    nitku = db.Column(db.String(22), nullable=False)
    report_title = db.Column(db.Text, nullable=False)
    report_style = db.Column(db.String(10), default='UNIFIKASI')  # UNIFIKASI (QDI) / SIMPLE (QKI)
    numbering_since_year = db.Column(db.Integer)                  # None = nomor mulai 1 tiap masa
    email_to = db.Column(db.Text, default='finance@qoin.id,reconcile@qoin.id')

    def as_dict(self):
        return dict(code=self.code, legal_name=self.legal_name, former_name=self.former_name,
                    report_title=self.report_title, report_style=self.report_style)


class TaxObjectCode(db.Model):
    __tablename__ = 'tax_object_code'
    code = db.Column(db.String(12), primary_key=True)
    name = db.Column(db.Text, nullable=False)
    tax_type = db.Column(db.String(20), nullable=False)
    is_final = db.Column(db.Boolean, nullable=False, default=False)
    rate = db.Column(db.Numeric(6, 4), nullable=False)
    verified = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)


class Vendor(db.Model):
    __tablename__ = 'vendor'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    npwp_display = db.Column(db.Text)
    npwp16 = db.Column(db.String(16), nullable=False, index=True)
    nitku = db.Column(db.String(22), nullable=False)
    entity_hint = db.Column(db.String(5))
    group = db.Column(db.String(10))                # QRIS / Non-QRIS / Final
    default_service = db.Column(db.Text)
    default_kop = db.Column(db.String(12), db.ForeignKey('tax_object_code.code'))
    default_rate = db.Column(db.Numeric(6, 4))
    default_section = db.Column(db.String(30))
    is_qris = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    withhold_pph23 = db.Column(db.Boolean, default=True)
    is_recurring = db.Column(db.Boolean, default=False)
    aliases = db.Column(JSON, default=list)
    auto_rules = db.Column(JSON, default=dict)
    special_rules_text = db.Column(db.Text)
    seed_invoices = db.Column(JSON, default=list)   # 3 invoice terakhir dari master (sebelum ada transaksi)

    def as_dict(self):
        return dict(id=self.id, name=self.name, npwp_display=self.npwp_display, npwp16=self.npwp16, group=self.group,
                    default_service=self.default_service, default_kop=self.default_kop,
                    default_rate=self.default_rate, default_section=self.default_section, is_qris=self.is_qris,
                    withhold_pph23=self.withhold_pph23, auto_rules=self.auto_rules or {})


class Period(db.Model):
    __tablename__ = 'period'
    __table_args__ = (UniqueConstraint('entity_id', 'month', 'year'),)
    id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.Integer, db.ForeignKey('entity.id'), nullable=False)
    entity = db.relationship(Entity)
    month = db.Column(db.SmallInteger, nullable=False)
    year = db.Column(db.SmallInteger, nullable=False)
    status = db.Column(db.String(12), nullable=False, default='DRAFT')   # DRAFT / SUBMITTED / APPROVED
    pph21_total = db.Column(db.Numeric(18, 2), default=0)
    signature_city = db.Column(db.Text, default='Jakarta')
    signature_date = db.Column(db.Date)        # NULL = 'Hari ini' (WIB saat generate)
    signature_blocks = db.Column(JSON)          # NULL = preset default entitas
    submitted_by = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime(timezone=True))
    reviewed_by = db.Column(db.Text)
    reviewed_at = db.Column(db.DateTime(timezone=True))
    review_note = db.Column(db.Text)

    @property
    def locked(self):
        return self.status == 'APPROVED'

    @property
    def label(self):
        from .core.rules import masa_label
        return f'{self.entity.code} – {masa_label(self.month, self.year)}'


class TaxInvoice(db.Model):           # faktur pajak masukan
    __tablename__ = 'tax_invoice'
    id = db.Column(db.Integer, primary_key=True)
    serial_no = db.Column(db.String(17), unique=True, nullable=False)
    period_id = db.Column(db.Integer, db.ForeignKey('period.id'))
    seller_npwp16 = db.Column(db.String(16))
    buyer_npwp16 = db.Column(db.String(16))
    seller_name = db.Column(db.Text)
    invoice_date = db.Column(db.Date)
    sale_amount = db.Column(db.Numeric(18, 2))
    vat_base = db.Column(db.Numeric(18, 2))
    vat = db.Column(db.Numeric(18, 2))
    reference = db.Column(db.Text)
    items = db.Column(JSON, default=list)
    file_name = db.Column(db.Text)
    file_path = db.Column(db.Text)
    not_withheld_reason = db.Column(db.Text)       # terisi = ditandai 'Tidak dipotong'
    uploaded_by = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=now)

    def as_parsed(self):
        d = dict(file=self.file_name, no_faktur=self.serial_no, npwp_penjual=self.seller_npwp16,
                 npwp_pembeli=self.buyer_npwp16, nama_penjual=self.seller_name,
                 tanggal=self.invoice_date.isoformat() if self.invoice_date else None,
                 harga_jual=float(self.sale_amount) if self.sale_amount is not None else None,
                 referensi=self.reference or '', item=self.items or [], id=self.id)
        if self.not_withheld_reason is not None:
            d['tidak_dipotong'] = self.not_withheld_reason
        return d


class Transaction(db.Model):
    __tablename__ = 'transaction'
    id = db.Column(db.Integer, primary_key=True)
    period_id = db.Column(db.Integer, db.ForeignKey('period.id'), nullable=False, index=True)
    period = db.relationship(Period, backref=db.backref('transactions', lazy='dynamic'))
    section = db.Column(db.String(30), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    invoice_date = db.Column(db.Date, nullable=False)
    invoice_no = db.Column(db.Text, nullable=False)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'))
    vendor = db.relationship(Vendor)
    name = db.Column(db.Text, nullable=False)            # nama lawan transaksi seperti dicetak
    npwp_display = db.Column(db.Text)
    npwp16 = db.Column(db.String(16), nullable=False)
    description = db.Column(db.Text)
    service_type = db.Column(db.Text)
    kop = db.Column(db.String(12), db.ForeignKey('tax_object_code.code'))
    dpp = db.Column(db.Numeric(18, 2), nullable=False)
    rate = db.Column(db.Numeric(6, 4), nullable=False)
    withholding_date = db.Column(db.Date, nullable=False)
    final_choice = db.Column(db.String(12))               # Mahesa: DIKENAKAN (default) / DIBEBASKAN
    faktur_no = db.Column(db.String(17))
    tax_invoice_id = db.Column(db.Integer, db.ForeignKey('tax_invoice.id'))
    draft_status = db.Column(db.String(20), default='CONFIRMED')  # PERLU_KONFIRMASI / CONFIRMED
    source = db.Column(db.String(12), default='MANUAL')           # MANUAL / FAKTUR / RUTIN / BULK / IMPORT
    bupot_no = db.Column(db.Text)
    bupot_status = db.Column(db.String(20))
    bupot_tte_status = db.Column(db.String(20))
    reported_in_spt = db.Column(db.Boolean)
    bupot_imported_at = db.Column(db.DateTime(timezone=True))
    ntpn = db.Column(db.Text)
    paid_date = db.Column(db.Date)
    bukpot_sent = db.Column(db.Text)
    bukpot_email_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_by = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now)
    updated_by = db.Column(db.Text)
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=now)

    @property
    def pph(self) -> Decimal:
        return pph(self.dpp, self.rate)

    @property
    def pph_rp(self) -> int:
        return pph_rounded(self.dpp, self.rate)

    @property
    def section_label(self):
        return SECTIONS.get(self.section, self.section)

    @property
    def is_output(self):
        """Ikut di XML/PDF/XLSX: sudah dikonfirmasi dan tidak dibebaskan."""
        return self.draft_status == 'CONFIRMED' and self.final_choice != 'DIBEBASKAN'

    def as_dict(self):
        p = self.period
        return dict(id=self.id, entity=p.entity.code, month=p.month, year=p.year, section=self.section,
                    sort_order=self.sort_order, invoice_date=self.invoice_date, invoice_no=self.invoice_no,
                    name=self.name, npwp_display=self.npwp_display or self.npwp16, npwp16=self.npwp16,
                    description=self.description, service_type=self.service_type, kop=self.kop, dpp=self.dpp,
                    rate=self.rate, withholding_date=self.withholding_date, faktur_no=self.faktur_no,
                    bupot_no=self.bupot_no, notes=self.notes, source=self.source, draft_status=self.draft_status,
                    paid_date=self.paid_date, bukpot_sent=self.bukpot_sent, bukpot_email_date=self.bukpot_email_date,
                    is_qris=bool(self.vendor and (self.vendor.auto_rules or {}).get('auto_qris_draft')))


class Signer(db.Model):
    __tablename__ = 'signer'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    title = db.Column(db.Text, nullable=False)
    email = db.Column(db.Text)
    entity_id = db.Column(db.Integer, db.ForeignKey('entity.id'))
    signature_image_path = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)


class EntityStamp(db.Model):
    __tablename__ = 'entity_stamp'
    id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.Integer, db.ForeignKey('entity.id'))
    image_path = db.Column(db.Text)


class SignaturePreset(db.Model):
    __tablename__ = 'signature_preset'
    id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.Integer, db.ForeignKey('entity.id'))
    name = db.Column(db.Text)
    is_default = db.Column(db.Boolean, default=False)
    city = db.Column(db.Text, default='Jakarta')
    blocks = db.Column(JSON, nullable=False)


class OutputLog(db.Model):
    __tablename__ = 'output_log'
    id = db.Column(db.Integer, primary_key=True)
    period_id = db.Column(db.Integer, db.ForeignKey('period.id'))
    kind = db.Column(db.String(10))        # XML / PDF / XLSX / EMAIL
    version = db.Column(db.Integer)
    file_path = db.Column(db.Text)
    sha256 = db.Column(db.String(64))
    signature_snapshot = db.Column(JSON)
    recipients = db.Column(db.Text)
    status = db.Column(db.Text)
    is_final = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now)


class BupotImport(db.Model):
    __tablename__ = 'bupot_import'
    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.Text)
    rows_total = db.Column(db.Integer)
    rows_matched = db.Column(db.Integer)
    result = db.Column(JSON)
    imported_by = db.Column(db.Text)
    imported_at = db.Column(db.DateTime(timezone=True), default=now)


class StoredFile(db.Model):
    """Isi file disimpan di database (lihat app/storage.py)."""
    __tablename__ = 'stored_file'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(200), unique=True, nullable=False, index=True)
    name = db.Column(db.Text)
    content_type = db.Column(db.String(120))
    size = db.Column(db.Integer)
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now)


class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.Text)
    row_id = db.Column(db.Integer)
    action = db.Column(db.Text)
    old_value = db.Column(JSON)
    new_value = db.Column(JSON)
    actor = db.Column(db.Text)
    at = db.Column(db.DateTime(timezone=True), default=now)


# ----------------------------------------------------------------------------- audit trail otomatis
AUDITED = (Transaction, Vendor, Period, TaxObjectCode, Entity, TaxInvoice, Signer, AppUser)


def _jsonable(v):
    if isinstance(v, Decimal):
        return str(v)
    if hasattr(v, 'isoformat'):
        return v.isoformat()
    return v


def _actor():
    try:
        from flask import g, has_request_context
        if has_request_context() and getattr(g, 'user', None):
            return g.user.email
    except Exception:
        pass
    return 'system'


_REGISTERED = set()


def register_audit(session_cls):
    if session_cls in _REGISTERED:
        return
    _REGISTERED.add(session_cls)
    @event.listens_for(session_cls, 'before_flush')
    def before_flush(session, ctx, instances):
        if session.info.get('skip_audit'):
            return
        actor = _actor()
        for obj in list(session.new) + list(session.dirty) + list(session.deleted):
            if not isinstance(obj, AUDITED):
                continue
            st = inspect(obj)
            if obj in session.new:
                action, old, new = 'INSERT', None, {c.key: _jsonable(getattr(obj, c.key)) for c in st.mapper.column_attrs}
            elif obj in session.deleted:
                action, old, new = 'DELETE', {c.key: _jsonable(getattr(obj, c.key)) for c in st.mapper.column_attrs}, None
            else:
                old, new = {}, {}
                for c in st.mapper.column_attrs:
                    h = st.attrs[c.key].history
                    if h.has_changes():
                        old[c.key] = _jsonable(h.deleted[0]) if h.deleted else None
                        new[c.key] = _jsonable(h.added[0]) if h.added else None
                if not new:
                    continue
                action = 'UPDATE'
            session.info.setdefault('pending_audit', []).append((obj, action, old, new, actor))

    @event.listens_for(session_cls, 'after_flush')
    def after_flush(session, ctx):
        pend = session.info.pop('pending_audit', [])
        if pend:
            session.connection().execute(AuditLog.__table__.insert(), [
                dict(table_name=obj.__tablename__, row_id=None if isinstance(obj, TaxObjectCode) else obj.id,
                     action=action, old_value=old, new_value=new, actor=actor, at=now())
                for obj, action, old, new, actor in pend])
