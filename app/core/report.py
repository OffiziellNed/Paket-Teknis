"""Model laporan per entitas per masa: urutan baris, nomor, subtotal dan total.
Dipakai bersama oleh generator PDF dan XLSX supaya angkanya selalu sama."""
from __future__ import annotations

from dataclasses import dataclass, field

from .rules import masa_label, pph, pph_rounded

SECTION_ORDER = ['PPH23', 'PPH23_QRIS', 'FINAL_4_2', 'PPH21_FREELANCE']


@dataclass
class Report:
    entity_code: str
    style: str                      # 'UNIFIKASI' (QDI) atau 'SIMPLE' (QKI/LPI)
    month: int
    year: int
    title_lines: list[str]
    lines: list[dict] = field(default_factory=list)
    totals: dict = field(default_factory=dict)

    @property
    def masa(self) -> str:
        return masa_label(self.month, self.year)


def _sort_key(r):
    return (SECTION_ORDER.index(r['section']), r.get('sort_order') or 0, r.get('id') or 0)


def build_report(entity: dict, month: int, year: int, rows: list[dict], pph21_total=0, start_no: int = 1) -> Report:
    """entity: dict code, report_title, legal_name, former_name, report_style.
    rows: transaksi terkonfirmasi (dict: section, invoice_date, invoice_no, name, npwp_display, description,
    dpp, rate, bupot_no, notes, service_type, faktur_no, ...)."""
    style = entity.get('report_style') or ('UNIFIKASI' if entity['code'] == 'QDI' else 'SIMPLE')
    masa = masa_label(month, year)
    if style == 'UNIFIKASI':
        titles = [entity['report_title'], f'MASA {masa.upper()}']
    else:
        sub = f"{entity['legal_name']} ({entity['code']})"
        if entity.get('former_name'):
            sub += f" - d/h {entity['former_name']}"
        titles = [entity['report_title'], sub, f'Masa {masa}']
    rep = Report(entity['code'], style, month, year, titles)

    rows = sorted(rows, key=_sort_key)
    by_sec = {s: [r for r in rows if r['section'] == s] for s in SECTION_ORDER}
    no = start_no

    def item(r):
        nonlocal no
        line = dict(kind='item', no=no, row=r, pph=pph(r['dpp'], r['rate']), pph_rp=pph_rounded(r['dpp'], r['rate']))
        no += 1
        return line

    def tot(rs):
        return sum(pph_rounded(r['dpp'], r['rate']) for r in rs)

    t23 = tot(by_sec['PPH23']) + tot(by_sec['PPH23_QRIS'])
    tfinal = tot(by_sec['FINAL_4_2'])
    t21f = tot(by_sec['PPH21_FREELANCE'])
    t21 = int(pph21_total or 0)
    rep.totals = dict(pph23=t23, final=tfinal, pph21_freelance=t21f, unifikasi=t23 + tfinal,
                      pph21=t21, total=t23 + tfinal + t21f + t21, count_bupot=sum(
                          len(by_sec[s]) for s in ('PPH23', 'PPH23_QRIS', 'FINAL_4_2')))
    L = rep.lines.append
    if style == 'UNIFIKASI':
        for r in by_sec['PPH23']:
            L(item(r))
        L(dict(kind='section', label='PPh 23 Project QRIS'))
        for r in by_sec['PPH23_QRIS']:
            L(item(r))
        L(dict(kind='total', label=f'Total PPh 23 (unifikasi) {masa}', amount=t23))
        L(dict(kind='section', label='PPh Final 4 (2) 10% )', offset=True))
        for r in by_sec['FINAL_4_2']:
            L(item(r))
        L(dict(kind='total', label=f'Total PPh Final 4 (2) (10%) (unifikasi) {masa}', amount=tfinal))
        L(dict(kind='section_grey', label='PPh 21 (freelance) 2,5% )'))
        for r in by_sec['PPH21_FREELANCE']:      # baris kosong tidak dicetak
            L(item(r))
        L(dict(kind='total_grey', label='Total PPh 21 ats Freelance (2,5%)', amount=t21f, rp=True))
        L(dict(kind='grand', label=f'PPH Unifikasi {masa} (PPh 23, PPh Ps 4 (2) & PPh Final)', amount=t23 + tfinal))
        L(dict(kind='grand', label=f'PPh 21 Bulan {masa}', amount=t21))
        L(dict(kind='grand_yellow', label=f'TOTAL PAJAK {masa}', amount=rep.totals['total']))
    else:
        bulan = masa.split()[0]
        used = [s for s in SECTION_ORDER if by_sec[s]]
        for s in used:
            if len(used) > 1:
                L(dict(kind='section', label={'PPH23': 'PPh 23 2%', 'PPH23_QRIS': 'PPh 23 Project QRIS',
                                              'FINAL_4_2': 'PPh Final sewa 10%',
                                              'PPH21_FREELANCE': 'PPh 21 Freelance 2,5%'}[s]))
            for r in by_sec[s]:
                L(item(r))
        L(dict(kind='total', label=f"PPH 23 {entity['code']} Bulan {bulan} {year}", amount=t23, rp=True))
        if tfinal:
            L(dict(kind='total', label=f"PPh Final 4 (2) {entity['code']} Bulan {bulan} {year}", amount=tfinal, rp=True))
        if t21f:
            L(dict(kind='total', label=f'PPh 21 Freelance Bulan {bulan} {year}', amount=t21f, rp=True))
        if t21:
            L(dict(kind='total', label=f"PPH 21 {entity['code']} Bulan {bulan} {year}", amount=t21, rp=True))
        if tfinal or t21f or t21:
            L(dict(kind='grand_yellow', label=f"TOTAL PAJAK {entity['code']} Bulan {bulan} {year}",
                   amount=rep.totals['total']))
    return rep
