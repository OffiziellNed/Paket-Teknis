"""Entry point Vercel (Python runtime). Semua request diarahkan ke sini oleh vercel.json.

vercel.json me-rewrite setiap URL ke /api/index?__path=<path asli>. Di dalam fungsi, path yang terlihat oleh
Flask bisa berubah menjadi /api/index, sehingga semua halaman 404 dan CSS tidak termuat. Middleware di bawah
mengembalikan path asli dari parameter __path (dan tidak melakukan apa-apa bila path asli sudah benar)."""
import os
import sys
from urllib.parse import parse_qsl, unquote, urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

PARAM = '__path'


class RestoreVercelPath:
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        qs = parse_qsl(environ.get('QUERY_STRING', ''), keep_blank_values=True)
        orig = [v for k, v in qs if k == PARAM]
        if orig:
            if environ.get('PATH_INFO', '/').rstrip('/') in ('', '/api/index', '/api/index.py', '/api'):
                environ['PATH_INFO'] = '/' + unquote(orig[0]).lstrip('/')
            environ['QUERY_STRING'] = urlencode([(k, v) for k, v in qs if k != PARAM])
        return self.wsgi_app(environ, start_response)


app = create_app()
app.wsgi_app = RestoreVercelPath(app.wsgi_app)
