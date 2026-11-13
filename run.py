"""Jalankan aplikasi: python run.py  (membaca .env bila ada)."""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
env = os.path.join(ROOT, '.env')
if os.path.exists(env):
    for line in open(env, encoding='utf-8'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

from app import create_app  # noqa: E402

app = create_app()

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'seed':
        from app.seed import seed_all
        with app.app_context():
            seed_all(sys.argv[2] if len(sys.argv) > 2 else app.config['PAKET_DIR'])
    elif len(sys.argv) > 1 and sys.argv[1] == 'add-user':
        from app.models import AppUser, Signer, db
        email, role = sys.argv[2].lower(), sys.argv[3]
        with app.app_context():
            u = AppUser.query.filter_by(email=email).first() or AppUser(email=email, name=email)
            u.role = role
            db.session.add(u)
            if len(sys.argv) > 4:
                s = Signer.query.filter_by(name=' '.join(sys.argv[4:])).first()
                if s:
                    s.email = email
            db.session.commit()
            print(f'{email} -> {role}')
    else:
        try:
            from waitress import serve
            print('Rekap PPh berjalan di http://localhost:5000')
            serve(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
        except ImportError:
            app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
