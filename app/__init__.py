"""Website Rekap PPh Unifikasi Qoin (QDI & QKI)."""
from __future__ import annotations

import os

import click
from flask import Flask, render_template

from .config import Config
from .models import db, register_audit


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    os.makedirs(app.config['STORAGE_DIR'], exist_ok=True)
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    if uri.startswith('sqlite:///'):
        os.makedirs(os.path.dirname(uri[len('sqlite:///'):]) or '.', exist_ok=True)
    elif app.config.get('ON_VERCEL'):
        # serverless: jangan tahan koneksi antar-invocation (pakai pooler Neon/Vercel Postgres)
        from sqlalchemy.pool import NullPool
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'poolclass': NullPool}
    if app.config.get('ON_VERCEL') or os.environ.get('TRUST_PROXY'):
        # di belakang proxy Vercel: pakai https + host asli untuk redirect URI SSO
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config.update(SESSION_COOKIE_SECURE=True, PREFERRED_URL_SCHEME='https')
    db.init_app(app)
    with app.app_context():
        register_audit(db.session.registry().__class__)
        db.create_all()

    from .auth import bp as auth_bp, load_user
    from .views import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.before_request(load_user)

    @app.context_processor
    def _banner():
        return dict(DB_EPHEMERAL=app.config.get('DB_EPHEMERAL'))

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('error.html', code=403, msg='Anda tidak punya akses untuk aksi ini.'), 403

    @app.errorhandler(404)
    def notfound(e):
        return render_template('error.html', code=404, msg='Halaman tidak ditemukan.'), 404

    @app.cli.command('seed')
    @click.option('--paket', default=None, help="Folder 'Paket Teknis' (default: PAKET_DIR)")
    def seed_cmd(paket):
        """Import master + data historis dari CSV."""
        from .seed import seed_all
        seed_all(paket or app.config['PAKET_DIR'])

    @app.cli.command('add-user')
    @click.argument('email')
    @click.argument('role', type=click.Choice(['TAX_SUPPORT', 'MANAGER_FAT', 'ADMIN']))
    @click.option('--name', default=None)
    @click.option('--signer', default=None, help='Tautkan ke penanda tangan dengan nama ini')
    def add_user(email, role, name, signer):
        """Tambah/ubah user dan role."""
        from .models import AppUser, Signer
        u = AppUser.query.filter_by(email=email.lower()).first() or AppUser(email=email.lower())
        u.role, u.name = role, name or u.name or email
        db.session.add(u)
        if signer:
            s = Signer.query.filter_by(name=signer).first()
            if s:
                s.email = email.lower()
        db.session.commit()
        click.echo(f'{email} -> {role}')

    return app
