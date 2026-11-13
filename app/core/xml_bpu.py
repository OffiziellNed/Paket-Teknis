"""Generator XML BPU Coretax – format persis samples/BPU_Template.xml."""
from __future__ import annotations

from xml.sax.saxutils import escape

from .rules import XML_SECTIONS, npwp16, round_rp, to_dec, xml_document_number


def _rate(tarif) -> str:
    v = to_dec(tarif) * 100
    return format(v.normalize(), 'f') if v != v.to_integral() else str(int(v))


def bpu_xml(entity_npwp16: str, month: int, year: int, rows: list[dict]) -> str:
    """rows: dict dengan key section, npwp16, kop, dpp, rate, invoice_no, invoice_date, withholding_date."""
    tin = npwp16(entity_npwp16)
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<BpuBulk xsi:noNamespaceSchemaLocation="schema.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
           f'  <TIN>{tin}</TIN>', '  <ListOfBpu>']
    for r in rows:
        if r['section'] not in XML_SECTIONS:
            continue
        cp = npwp16(r['npwp16'])
        out.append(f"""    <Bpu>
      <TaxPeriodMonth>{month}</TaxPeriodMonth>
      <TaxPeriodYear>{year}</TaxPeriodYear>
      <CounterpartTin>{cp}</CounterpartTin>
      <IDPlaceOfBusinessActivityOfIncomeRecipient>{cp}000000</IDPlaceOfBusinessActivityOfIncomeRecipient>
      <TaxCertificate>N/A</TaxCertificate>
      <TaxObjectCode>{escape(r['kop'] or '')}</TaxObjectCode>
      <TaxBase>{round_rp(r['dpp'])}</TaxBase>
      <Rate>{_rate(r['rate'])}</Rate>
      <Document>CommercialInvoice</Document>
      <DocumentNumber>{escape(xml_document_number(r['invoice_no']))}</DocumentNumber>
      <DocumentDate>{r['invoice_date'].isoformat()}</DocumentDate>
      <IDPlaceOfBusinessActivity>{tin}000000</IDPlaceOfBusinessActivity>
      <GovTreasurerOpt>N/A</GovTreasurerOpt>
      <SP2DNumber />
      <WithholdingDate>{r['withholding_date'].isoformat()}</WithholdingDate>
    </Bpu>""")
    out += ['  </ListOfBpu>', '</BpuBulk>']
    return '\n'.join(out) + '\n'


def validate_rows(month: int, year: int, rows: list[dict]) -> list[str]:
    """Validasi sebelum XML dibuat. Return daftar error (kosong = OK)."""
    errs = []
    for r in rows:
        if r['section'] not in XML_SECTIONS:
            continue
        tag = r.get('invoice_no') or '?'
        if len(npwp16(r['npwp16'])) != 16:
            errs.append(f'{tag}: NPWP lawan transaksi tidak valid')
        if not r.get('kop'):
            errs.append(f'{tag}: KOP kosong')
        if r.get('kop') == '28-403-01':
            errs.append(f'{tag}: KOP 28-403-01 ditolak Coretax, pakai 28-403-02')
        w = r['withholding_date']
        if (w.year, w.month) != (year, month):
            errs.append(f'{tag}: tanggal pemotongan {w} di luar masa')
        if to_dec(r['dpp']) <= 0:
            errs.append(f'{tag}: DPP harus > 0')
    return errs
