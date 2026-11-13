"""Penyimpanan file (faktur, output XML/PDF/XLSX, gambar ttd, stempel, file sementara) di DATABASE.

Alasan: di Vercel disk tidak permanen. Dengan menyimpan di Postgres, file tetap privat (tidak ada URL publik)
dan tidak perlu layanan tambahan. Ukuran tipikal: faktur ~150 KB, output < 100 KB per masa."""
from __future__ import annotations

import json
import os
import uuid

from .models import StoredFile, db


def put(name: str, data: bytes, content_type: str = 'application/octet-stream', commit=False) -> str:
    key = f'db:{uuid.uuid4().hex}/{os.path.basename(name)}'
    db.session.add(StoredFile(key=key, name=os.path.basename(name), content_type=content_type, size=len(data),
                              data=data))
    if commit:
        db.session.commit()
    return key


def get(key: str) -> bytes:
    if key and key.startswith('db:'):
        f = StoredFile.query.filter_by(key=key).first()
        if not f:
            raise FileNotFoundError(key)
        return f.data
    with open(key, 'rb') as fh:          # kompatibel dengan path lokal lama
        return fh.read()


def exists(key: str | None) -> bool:
    if not key:
        return False
    if key.startswith('db:'):
        return db.session.query(StoredFile.id).filter_by(key=key).first() is not None
    return os.path.exists(key)


def basename(key: str) -> str:
    return key.rsplit('/', 1)[-1]


def delete(key: str | None):
    if key and key.startswith('db:'):
        StoredFile.query.filter_by(key=key).delete()


def tmp_key(token: str) -> str:
    return f'db:tmp-{token}'


def put_json(token: str, obj):
    """Simpan data sementara (preview upload massal / import bupot) dengan token acak."""
    data = json.dumps(obj, default=str).encode('utf-8')
    db.session.add(StoredFile(key=tmp_key(token), name=f'{token}.json', content_type='application/json',
                              size=len(data), data=data))
    db.session.commit()


def get_json(token: str):
    return json.loads(get(tmp_key(token)).decode('utf-8'))
