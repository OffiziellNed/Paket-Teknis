"""Kirim email lewat Microsoft Graph API (Microsoft 365). MAIL_DRY_RUN=1 -> simpan .eml ke storage/outbox."""
from __future__ import annotations

import base64
from datetime import datetime
from email.message import EmailMessage

import requests
from flask import current_app


def _token():
    import msal
    c = current_app.config
    app = msal.ConfidentialClientApplication(
        c['GRAPH_CLIENT_ID'], client_credential=c['GRAPH_CLIENT_SECRET'],
        authority=f"https://login.microsoftonline.com/{c['GRAPH_TENANT_ID']}")
    res = app.acquire_token_for_client(scopes=['https://graph.microsoft.com/.default'])
    if 'access_token' not in res:
        raise RuntimeError('Gagal ambil token Graph: ' + str(res.get('error_description')))
    return res['access_token']


def send_mail(to: list[str], subject: str, html: str, attachments: list[tuple[str, bytes, str]]) -> str:
    """attachments: (nama_file, isi, content_type). Return (keterangan status, key .eml bila dry run)."""
    c = current_app.config
    if c['MAIL_DRY_RUN'] or not (c['GRAPH_CLIENT_ID'] and c['MAIL_SENDER']):
        msg = EmailMessage()
        msg['From'] = c['MAIL_SENDER'] or 'noreply@qoin.id'
        msg['To'] = ', '.join(to)
        msg['Subject'] = subject
        msg.set_content('Lihat versi HTML.')
        msg.add_alternative(html, subtype='html')
        for name, data, ctype in attachments:
            maintype, subtype = ctype.split('/', 1)
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
        from . import storage as ST
        name = datetime.now().strftime('%Y%m%d-%H%M%S-') + subject.replace('/', '-')[:60] + '.eml'
        key = ST.put(name, bytes(msg), 'message/rfc822')
        return f'DRY RUN – email tidak dikirim, disimpan sebagai {name} (unduh di Riwayat versi)', key
    body = {
        'message': {
            'subject': subject,
            'body': {'contentType': 'HTML', 'content': html},
            'toRecipients': [{'emailAddress': {'address': a}} for a in to],
            'attachments': [{'@odata.type': '#microsoft.graph.fileAttachment', 'name': n, 'contentType': t,
                             'contentBytes': base64.b64encode(d).decode()} for n, d, t in attachments],
        },
        'saveToSentItems': True,
    }
    r = requests.post(f"https://graph.microsoft.com/v1.0/users/{c['MAIL_SENDER']}/sendMail",
                      headers={'Authorization': 'Bearer ' + _token()}, json=body, timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f'Graph sendMail gagal ({r.status_code}): {r.text[:300]}')
    return 'Terkirim via Microsoft Graph', None
