"""Login SSO Microsoft 365 (Entra ID) via MSAL, dibatasi domain @qoin.id, dan kontrol role."""
from __future__ import annotations

import uuid
from functools import wraps

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for

from .models import AppUser, db

bp = Blueprint('auth', __name__)
ROLES = {'TAX_SUPPORT': 'Tax Support', 'MANAGER_FAT': 'Manager FAT', 'ADMIN': 'Admin'}


def _msal_app():
    import msal
    c = current_app.config
    return msal.ConfidentialClientApplication(
        c['ENTRA_CLIENT_ID'], client_credential=c['ENTRA_CLIENT_SECRET'],
        authority=f"https://login.microsoftonline.com/{c['ENTRA_TENANT_ID']}")


def load_user():
    g.user = None
    uid = session.get('uid')
    if uid:
        u = db.session.get(AppUser, uid)
        if u and u.active:
            g.user = u


def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not g.user:
            return redirect(url_for('auth.login', next=request.full_path))
        return f(*a, **kw)
    return w


def roles_required(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **kw):
            if not g.user:
                return redirect(url_for('auth.login', next=request.full_path))
            if g.user.role != 'ADMIN' and g.user.role not in roles:
                abort(403)
            return f(*a, **kw)
        return w
    return deco


def has_role(*roles):
    return bool(g.user) and (g.user.role == 'ADMIN' or g.user.role in roles)


def _login_email(email, name):
    email = email.lower().strip()
    dom = current_app.config['ALLOWED_DOMAIN']
    if not email.endswith('@' + dom):
        flash(f'Hanya akun @{dom} yang boleh masuk.', 'error')
        return redirect(url_for('auth.login'))
    u = AppUser.query.filter_by(email=email).first()
    if not u:
        role = 'ADMIN' if email in current_app.config['ADMIN_EMAILS'] or AppUser.query.count() == 0 else 'TAX_SUPPORT'
        u = AppUser(email=email, name=name or email, role=role)
        db.session.add(u)
        db.session.commit()
    if not u.active:
        abort(403)
    session.clear()
    session['uid'] = u.id
    return redirect(session.pop('next', None) or url_for('main.dashboard'))


@bp.route('/login')
def login():
    c = current_app.config
    if request.args.get('next'):
        session['next'] = request.args['next']
    sso = bool(c['ENTRA_CLIENT_ID'] and c['ENTRA_TENANT_ID'])
    return render_template('login.html', sso=sso, dev=c['DEV_LOGIN'], users=AppUser.query.all() if c['DEV_LOGIN'] else [])


@bp.route('/login/sso')
def login_sso():
    state = str(uuid.uuid4())
    session['state'] = state
    url = _msal_app().get_authorization_request_url(['User.Read'], state=state,
                                                     redirect_uri=url_for('auth.callback', _external=True))
    return redirect(url)


@bp.route('/auth/callback')
def callback():
    if request.args.get('state') != session.get('state'):
        abort(400)
    res = _msal_app().acquire_token_by_authorization_code(
        request.args.get('code', ''), scopes=['User.Read'], redirect_uri=url_for('auth.callback', _external=True))
    claims = res.get('id_token_claims') or {}
    email = claims.get('preferred_username') or claims.get('email') or ''
    if not email:
        flash('Login Microsoft gagal: ' + str(res.get('error_description', '')), 'error')
        return redirect(url_for('auth.login'))
    return _login_email(email, claims.get('name'))


@bp.route('/login/dev', methods=['POST'])
def login_dev():
    if not current_app.config['DEV_LOGIN']:
        abort(404)
    email = request.form['email']
    r = _login_email(email, request.form.get('name') or email.split('@')[0].title())
    role = request.form.get('role')
    if role in ROLES and g.get('user') is None:
        u = AppUser.query.filter_by(email=email.lower()).first()
        if u and request.form.get('set_role'):
            u.role = role
            db.session.commit()
    return r


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
