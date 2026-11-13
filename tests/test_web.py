"""Test alur web end-to-end dengan data Oktober/September 2026 (SQLite sementara, login development)."""
import io
import os
import re
import zipfile

import pytest

from conftest import PAKET, p


@pytest.fixture(scope='module')
def app(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('rekap')
    from app import create_app
    # TEST_DATABASE_URL=postgresql+psycopg://... untuk menguji di Postgres (database akan dikosongkan!)
    uri = os.environ.get('TEST_DATABASE_URL') or f'sqlite:///{tmp}/t.db'
    if uri.startswith('postgresql'):
        import sqlalchemy as sa
        eng = sa.create_engine(uri)
        with eng.begin() as con:
            con.execute(sa.text('DROP SCHEMA public CASCADE; CREATE SCHEMA public'))
        eng.dispose()
    a = create_app({'SQLALCHEMY_DATABASE_URI': uri, 'DEV_LOGIN': True, 'TESTING': True,
                    'STORAGE_DIR': str(tmp / 'storage'), 'PAKET_DIR': PAKET, 'MAIL_DRY_RUN': True,
                    'WTF_CSRF_ENABLED': False})
    with a.app_context():
        from app.seed import seed_all
        seed_all(PAKET, log=lambda *x: None)
        from app.models import AppUser, Signer, db
        db.session.add_all([AppUser(email='rizal@qoin.id', name='Rizal', role='TAX_SUPPORT'),
                            AppUser(email='suryawati@qoin.id', name='Suryawati', role='MANAGER_FAT'),
                            AppUser(email='admin@qoin.id', name='Admin', role='ADMIN')])
        Signer.query.filter_by(name='Suryawati').first().email = 'suryawati@qoin.id'
        Signer.query.filter_by(name='Rizal Nur Furqon').first().email = 'rizal@qoin.id'
        db.session.commit()
    return a


def login(c, email):
    c.get('/logout')
    r = c.post('/login/dev', data={'email': email})
    assert r.status_code == 302


def pid_of(app, code, m, y):
    from app.models import Entity, Period
    with app.app_context():
        e = Entity.query.filter_by(code=code).first()
        return Period.query.filter_by(entity_id=e.id, month=m, year=y).first().id


def test_domain_restriction(app):
    c = app.test_client()
    c.post('/login/dev', data={'email': 'orang@gmail.com'})
    assert c.get('/').status_code == 302


def test_october_flow(app):
    c = app.test_client()
    login(c, 'rizal@qoin.id')
    assert c.get('/').status_code == 200
    qdi = pid_of(app, 'QDI', 10, 2026)
    assert b'3.034.384' in c.get(f'/period/{qdi}').data

    # upload 20 faktur sebagai satu ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        folder = p('samples', 'faktur_okt2026')
        for f in os.listdir(folder):
            z.write(os.path.join(folder, f), f)
    r = c.post(f'/period/{qdi}/faktur', data={'files': (io.BytesIO(buf.getvalue()), 'faktur.zip')},
               content_type='multipart/form-data', follow_redirects=True)
    assert b'20 faktur tersimpan' in r.data

    from app.models import TaxInvoice, db
    with app.app_context():
        fid = TaxInvoice.query.filter_by(serial_no='04002600431060608').first().id
    c.post(f'/faktur/{fid}/tidak-dipotong', data={'reason': 'Annual Fee QRIS – tidak dipotong (revisi 6-Nov-2026)'})
    r = c.post(f'/period/{qdi}/faktur/drafts', follow_redirects=True)
    assert r.status_code == 200
    page = c.get(f'/period/{qdi}/faktur').data.decode()
    assert 'Selisih Rp 1' in page and 'Tidak dipotong (ditandai user)' in page
    assert 'PEMBAYARAN LINTAS USAHA SUKSES' in page             # panel vendor baru

    with app.app_context():
        from app import services as S
        from app.models import Period
        per = db.session.get(Period, qdi)
        drafts = per.transactions.filter_by(draft_status='PERLU_KONFIRMASI').all()
        # draft dibuat untuk vendor master non-QRIS (LPPI, Dotcom, Sentral x2, Qontak x2, LMI); BCA/Telkom diabaikan
        assert len(drafts) == 7
        assert S.report_for(per).totals['total'] == 3034384     # draft tidak ikut total
        draft_ids = [t.id for t in drafts]
    # submit ditolak selama masih ada draft
    r = c.post(f'/period/{qdi}/submit', follow_redirects=True)
    assert b'Konfirmasi atau hapus semua draft' in r.data
    for tid in draft_ids:   # draft bulan ini tidak dipakai -> hapus
        c.post(f'/period/{qdi}/trx/{tid}/delete')
    # tanggal tanda tangan pilihan 6 Nov 2026
    c.post(f'/period/{qdi}/signature', data={'label_1': 'Dibuat oleh', 'signer_1': '1', 'mode_1': 'BLANK',
                                              'label_2': 'Diperiksa oleh', 'signer_2': '2', 'mode_2': 'IMAGE',
                                              'approval_2': '1', 'city': 'Jakarta', 'date_mode': 'PILIH',
                                              'sig_date': '2026-11-06'})
    r = c.post(f'/period/{qdi}/submit', follow_redirects=True)
    assert b'Diajukan ke Manager FAT' in r.data
    # Tax Support tidak boleh approve
    assert c.post(f'/period/{qdi}/approve').status_code == 403

    login(c, 'suryawati@qoin.id')
    r = c.post(f'/period/{qdi}/approve', data={'action': 'approve'}, follow_redirects=True)
    assert b'di-approve' in r.data
    with app.app_context():
        from app import services as S
        from app.models import Period
        per = db.session.get(Period, qdi)
        outs = S.latest_outputs(per)
        assert outs['XML'].is_final
        from app import storage as ST
        assert ST.get(outs['XML'].file_path).decode('utf-8') == \
            open(p('samples', 'BPU_QDI_Okt2026.xml'), encoding='utf-8').read()
        assert outs['PDF'].signature_snapshot['date'] == '2026-11-06'
    # masa terkunci: edit ditolak
    login(c, 'rizal@qoin.id')
    r = c.post(f'/period/{qdi}/pph21', data={'pph21_total': '5'}, follow_redirects=True)
    assert b'terkunci' in r.data

    # QKI: submit + approve, lalu kirim email kedua entitas (dry run)
    qki = pid_of(app, 'QKI', 10, 2026)
    c.post(f'/period/{qki}/submit')
    login(c, 'suryawati@qoin.id')
    c.post(f'/period/{qki}/approve', data={'action': 'approve'})
    with app.app_context():
        from app import services as S
        from app.models import Period
        per = db.session.get(Period, qki)
        assert S.report_for(per).totals['pph23'] == 2919594
        assert S.report_for(per).lines[0]['no'] == 9           # penomoran QKI berlanjut sejak 2025
        from app import storage as ST
        assert ST.get(S.latest_outputs(per)['XML'].file_path).decode('utf-8') == \
            open(p('samples', 'BPU_QKI_Okt2026.xml'), encoding='utf-8').read()
    r = c.post('/send', data={'pids': [str(qdi), str(qki)]}, follow_redirects=True)
    assert b'DRY RUN' in r.data
    with app.app_context():
        from app.models import StoredFile
        eml = StoredFile.query.filter_by(content_type='message/rfc822').first().data
    assert b'finance@qoin.id' in eml and b'reconcile@qoin.id' in eml
    assert len(re.findall(rb'filename="?[^"\r\n]+\.(?:xml|pdf|xlsx)', eml)) == 6


def test_bupot_import_september(app):
    c = app.test_client()
    login(c, 'rizal@qoin.id')
    with open(p('samples', 'coretax_export_bupot_sep2026.xlsx'), 'rb') as f:
        r = c.post('/bupot-import', data={'file': (f, 'export.xlsx')}, content_type='multipart/form-data')
    html = r.data.decode()
    assert '<b>15/15</b> cocok' in html
    token = re.search(r'/bupot-import/([0-9a-f]{32})', html).group(1)
    r = c.post(f'/bupot-import/{token}', follow_redirects=True)
    assert b'No Bupot terisi untuk 15 transaksi' in r.data


def test_autocomplete_and_invoice_suggestion(app):
    c = app.test_client()
    login(c, 'rizal@qoin.id')
    vs = c.get('/api/vendors?q=rin').get_json()
    assert vs[0]['name'] == 'PT Rintis Sejahtera' and vs[0]['default_kop'] == '24-104-18'
    kti = [v for v in c.get('/api/vendors?q=konsultasi').get_json() if 'Konsultasi' in v['name']][0]
    j = c.get(f"/api/vendor/{kti['id']}/invoices?month=11&year=2026&inv=15/KTI/X/2026").get_json()
    assert j['color'] == 'merah'          # sudah dipakai
    j = c.get(f"/api/vendor/{kti['id']}/invoices?month=11&year=2026&inv=16/KTI/XI/2026").get_json()
    assert j['color'] == 'hijau' and len(j['last']) == 5


def test_open_period_creates_recurring_drafts_and_bulk_upload(app):
    c = app.test_client()
    login(c, 'rizal@qoin.id')
    r = c.post('/period/open', data={'entity': 'QDI', 'month': '11', 'year': '2026'}, follow_redirects=True)
    assert b'draft transaksi rutin dibuat' in r.data
    nov = pid_of(app, 'QDI', 11, 2026)
    with app.app_context():
        from app.models import Period, db
        per = db.session.get(Period, nov)
        rutin = per.transactions.filter_by(source='RUTIN').all()
        assert {t.vendor.name for t in rutin} >= {'Artha Telekomindo', 'PT Mahesa Cipta'}
    csv_data = ('Entitas,Masa (1-12),Tahun,Section,Tanggal Invoice,No Invoice,Lawan Transaksi,NPWP,Deskripsi,Jenis Jasa,'
                'KOP,DPP (Rp),Tarif (%),Tanggal Pemotongan,No Faktur Pajak,No Bupot,Notes\n'
                'QDI,11,2026,PPh 23,03/11/2026,INV/2026/00600,PT Venturo Pro Indonesia,,,,,16887500,2,,,,\n'
                'QDI,11,2026,PPh 23,03/11/2026,X1,PT Bank Central Asia Tbk,,,,,1000,2,,,,\n'
                'QDI,11,2026,PPh Final 4(2),20/10/2026,300/MC-QDI/X/2026,PT Mahesa Cipta,,,,28-403-01,500000,10,,,,\n')
    r = c.post('/bulk', data={'file': (io.BytesIO(csv_data.encode()), 'upload.csv')}, content_type='multipart/form-data')
    html = r.data.decode()
    assert 'ditolak Coretax' in html and 'tidak dipotong PPh 23' in html
    token = re.search(r'/bulk/([0-9a-f]{32})/commit', html).group(1)
    assert c.get(f'/bulk/{token}/koreksi').status_code == 200
    r = c.post(f'/bulk/{token}/commit', data={'mode': 'TAMBAH'}, follow_redirects=True)
    assert b'1 transaksi baru' in r.data
    with app.app_context():
        from app.models import Transaction
        t = Transaction.query.filter_by(invoice_no='INV/2026/00600').first()
        assert t.kop == '24-104-24' and t.withholding_date.isoformat() == '2026-11-03'


def test_audit_trail(app):
    c = app.test_client()
    login(c, 'suryawati@qoin.id')
    r = c.get('/audit')
    assert r.status_code == 200 and b'APPROVED' in r.data
