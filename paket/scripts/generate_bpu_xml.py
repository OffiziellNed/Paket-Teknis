"""Referensi generator XML BPU Coretax dari CSV transaksi.
Pakai: python generate_bpu_xml.py transaksi.csv QDI 10 2026 > BPU_QDI_Okt2026.xml
CSV butuh kolom: entitas,masa,tahun,section,tanggal_invoice,no_invoice,npwp16,dpp,tarif,kop,tanggal_pemotongan"""
import sys, csv
from xml.sax.saxutils import escape
ENTITAS = {'QDI': '0855609921034000', 'QKI': '0028998276031000'}

def n16(x):
    d = ''.join(c for c in str(x) if c.isdigit()); return d.zfill(16)

def bpu(r, tin):
    cp = n16(r['npwp16'])
    return f"""    <Bpu>
      <TaxPeriodMonth>{int(r['masa'])}</TaxPeriodMonth>
      <TaxPeriodYear>{int(r['tahun'])}</TaxPeriodYear>
      <CounterpartTin>{cp}</CounterpartTin>
      <IDPlaceOfBusinessActivityOfIncomeRecipient>{cp}000000</IDPlaceOfBusinessActivityOfIncomeRecipient>
      <TaxCertificate>N/A</TaxCertificate>
      <TaxObjectCode>{r['kop']}</TaxObjectCode>
      <TaxBase>{int(round(float(r['dpp'])))}</TaxBase>
      <Rate>{float(r['tarif'])*100:g}</Rate>
      <Document>CommercialInvoice</Document>
      <DocumentNumber>{escape(r['no_invoice'])}</DocumentNumber>
      <DocumentDate>{r['tanggal_invoice']}</DocumentDate>
      <IDPlaceOfBusinessActivity>{tin}000000</IDPlaceOfBusinessActivity>
      <GovTreasurerOpt>N/A</GovTreasurerOpt>
      <SP2DNumber />
      <WithholdingDate>{r['tanggal_pemotongan']}</WithholdingDate>
    </Bpu>
"""

if __name__ == '__main__':
    path, ent, masa, tahun = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    tin = ENTITAS[ent]
    rows = [r for r in csv.DictReader(open(path, encoding='utf-8'))
            if r['entitas'] == ent and int(r['masa']) == masa and int(r['tahun']) == tahun
            and r['section'] != 'PPh 21 Freelance']
    print('<?xml version="1.0" encoding="utf-8"?>')
    print('<BpuBulk xsi:noNamespaceSchemaLocation="schema.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">')
    print(f'  <TIN>{tin}</TIN>\n  <ListOfBpu>')
    print(''.join(bpu(r, tin) for r in rows), end='')
    print('  </ListOfBpu>\n</BpuBulk>')
