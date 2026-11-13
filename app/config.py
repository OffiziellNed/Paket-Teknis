import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def env_bool(name, default=False):
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ('1', 'true', 'yes', 'ya')


ON_VERCEL = bool(os.environ.get('VERCEL'))


def database_url():
    """DATABASE_URL / POSTGRES_URL (Neon, Vercel Postgres) -> URL SQLAlchemy dengan driver psycopg 3."""
    url = (os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_URL') or '').strip()
    if not url:
        # Vercel: filesystem read-only kecuali /tmp -> SQLite sementara (data HILANG). Wajib isi DATABASE_URL.
        base = '/tmp' if ON_VERCEL else os.path.join(BASE, 'instance')
        return 'sqlite:///' + os.path.join(base, 'rekap.db')
    for pre in ('postgres://', 'postgresql://'):
        if url.startswith(pre):
            url = 'postgresql+psycopg://' + url[len(pre):]
    return url


def default_paket_dir():
    """Folder berisi data/, samples/, templates/: <repo>/paket bila ada, kalau tidak folder induk proyek."""
    inside = os.path.join(BASE, 'paket')
    return inside if os.path.isdir(inside) else os.path.dirname(BASE)


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'ganti-di-production')
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}
    # Vercel membatasi body request 4,5 MB -> upload faktur dipecah per file oleh browser
    MAX_CONTENT_LENGTH = (4 if ON_VERCEL else 210) * 1024 * 1024
    UPLOAD_BATCH_BYTES = 3 * 1024 * 1024 if ON_VERCEL else 50 * 1024 * 1024
    STORAGE_DIR = os.environ.get('STORAGE_DIR', '/tmp/rekap_storage' if ON_VERCEL else os.path.join(BASE, 'instance', 'storage'))
    PAKET_DIR = os.environ.get('PAKET_DIR', default_paket_dir())
    ON_VERCEL = ON_VERCEL
    DB_EPHEMERAL = ON_VERCEL and not (os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_URL'))
    TIMEZONE = 'Asia/Jakarta'

    # SSO Microsoft 365 (Entra ID)
    ENTRA_TENANT_ID = os.environ.get('ENTRA_TENANT_ID', '')
    ENTRA_CLIENT_ID = os.environ.get('ENTRA_CLIENT_ID', '')
    ENTRA_CLIENT_SECRET = os.environ.get('ENTRA_CLIENT_SECRET', '')
    ALLOWED_DOMAIN = os.environ.get('ALLOWED_DOMAIN', 'qoin.id')
    ADMIN_EMAILS = [e.strip().lower() for e in os.environ.get('ADMIN_EMAILS', '').split(',') if e.strip()]
    # login tanpa SSO – HANYA untuk komputer lokal; selalu mati di Vercel (URL publik)
    DEV_LOGIN = env_bool('DEV_LOGIN', False) and not ON_VERCEL

    # Email via Microsoft Graph (client credentials, permission Mail.Send)
    GRAPH_TENANT_ID = os.environ.get('GRAPH_TENANT_ID', os.environ.get('ENTRA_TENANT_ID', ''))
    GRAPH_CLIENT_ID = os.environ.get('GRAPH_CLIENT_ID', os.environ.get('ENTRA_CLIENT_ID', ''))
    GRAPH_CLIENT_SECRET = os.environ.get('GRAPH_CLIENT_SECRET', os.environ.get('ENTRA_CLIENT_SECRET', ''))
    MAIL_SENDER = os.environ.get('MAIL_SENDER', '')            # mailbox pengirim, mis. tax@qoin.id
    MAIL_DRY_RUN = env_bool('MAIL_DRY_RUN', True)              # True = simpan .eml ke storage/outbox, tidak kirim
