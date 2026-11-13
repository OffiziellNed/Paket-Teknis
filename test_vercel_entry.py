"""Entry point Vercel: path asli dikembalikan dari ?__path= saat request tiba sebagai /api/index."""
import importlib.util
import os

from conftest import ROOT


def load_index(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path}/v.db')
    monkeypatch.setenv('STORAGE_DIR', str(tmp_path / 's'))
    spec = importlib.util.spec_from_file_location('vercel_index', os.path.join(ROOT, 'api', 'index.py'))
    mod = importlib.util.module_from_spec(spec)
    # config dibaca saat import modul app.config; set URI langsung untuk test
    import app.config as cfg
    monkeypatch.setattr(cfg.Config, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{tmp_path}/v.db')
    spec.loader.exec_module(mod)
    return mod.app


def test_path_restored(tmp_path, monkeypatch):
    app = load_index(tmp_path, monkeypatch)
    c = app.test_client()
    r = c.get('/api/index?__path=/static/style.css')
    assert r.status_code == 200 and b'--pri' in r.data
    r = c.get('/api/index?__path=/login&next=/x')
    assert r.status_code == 200 and b'Masuk' in r.data
    r = c.get('/api/index?__path=/')                 # halaman utama -> redirect ke login
    assert r.status_code == 302 and '/login' in r.headers['Location']
    r = c.get('/login?__path=/login')                # runtime yang sudah meneruskan path asli
    assert r.status_code == 200
