import json

import numpy as np

from src.auth import password_hash
from src.db import connect
from src.disposition import close_lot, sign_grade
from src.inspection import add_mark, capture, create_lot, enqueue, latest_grade, latest_measure, review_mark
from src.model import PROFILES, SPREAD
from src.queue import grade_next
from src.sampling import create_plan, grade_item, issue_round, sign_plan
from src.schemas import (CHANNELS, GradeReview, ItemGradeInput, LotInput, MarkInput, MarkReview, MeasureInput,
                         PalletInput, PlanInput, PlanSignInput)

STAFF = [('operator', '林珂 · 线边操作'), ('supervisor', '周遥 · 质检主管'), ('viewer', '顾宁 · 排产查看')]
STOCK = [('FILM-MT-220', '哑光阻隔膜 · 220 mm', 'B-04', 620),
         ('FILM-GL-180', '高光印刷膜 · 180 mm', 'A-12', 360),
         ('FILM-KR-250', '牛皮复合膜 · 250 mm', 'C-09', 110)]
SAMPLES = [
    ('PK-261121-01', '海盐燕麦脆片 120 g', 'VS-01', 2400, 'FILM-MT-220', (0.32, 0.19, 0.83, 0.14, 1.9), 'closed'),
    ('PK-261121-02', '青柠米饼 90 g', 'VS-03', 1600, 'FILM-KR-250', None, 'new'),
    ('PK-261121-03', '伯爵茶曲奇 150 g', 'VS-01', 1800, 'FILM-MT-220', (1.61, None, 2.76, 0.24, 3.95), 'blocked'),
    ('PK-261121-04', '黑芝麻薄脆 80 g', 'VS-02', 2200, 'FILM-GL-180', (0.39, 0.42, 1.31, 0.22, 2.4), 'override'),
    ('PK-261121-05', '山椒豌豆 65 g', 'VS-02', 3200, 'FILM-GL-180', (1.79, 0.81, 2.83, 0.42, 5.3), 'review'),
]


def seed_sampling(db):
    """托盘抽检演示：PK-261121-02 抽检进行中，PK-261121-06 已签核。"""
    if not db.execute('SELECT 1 FROM pack_lot WHERE code=%s', ('PK-261121-06',)).fetchone():
        create_lot(db, LotInput(code='PK-261121-06', product='海苔米果 100 g', machine='VS-03',
                                units=1200, film_sku='FILM-KR-250'), 'operator')
    rng = np.random.default_rng(20261124)

    def reading(profile):
        noise = rng.normal(0, 1, len(CHANNELS)) * SPREAD * 0.5
        values = (PROFILES[profile] + noise).clip(0)
        return dict(zip(CHANNELS, (round(float(value), 4) for value in values), strict=True))

    def pending_items(lot_id, pallet_label=None):
        return db.execute('''SELECT i.id FROM sample_item i
                             JOIN sample_pallet p ON p.id=i.pallet_id
                             JOIN sample_plan s ON s.id=p.plan_id
                             WHERE s.lot_id=%s AND i.state='pending' AND (%s::text IS NULL OR p.label=%s)
                             ORDER BY i.id''', (lot_id, pallet_label, pallet_label)).fetchall()

    def grade_pending(lot_id, pallet_label=None, leave=0, c_count=0):
        rows = pending_items(lot_id, pallet_label)
        targets = rows[:len(rows) - leave] if leave else rows
        for index, row in enumerate(targets):
            profile = 2 if index >= len(targets) - c_count else 0
            grade_item(db, lot_id, row['id'], ItemGradeInput(**reading(profile)), 'operator')

    def open_plan(code, pallets):
        lot = db.execute('SELECT * FROM pack_lot WHERE code=%s', (code,)).fetchone()
        if db.execute('SELECT 1 FROM sample_plan WHERE lot_id=%s', (lot['id'],)).fetchone():
            return None
        create_plan(db, lot['id'],
                    PlanInput(pallets=[PalletInput(label=label, units=units) for label, units in pallets]),
                    'operator')
        return lot['id']

    # 进行中：P1 已判齐合格，P2 检出 2 件 C 级待补抽，P3 留 12 件待判。
    lot_id = open_plan('PK-261121-02', [('P1', 600), ('P2', 500), ('P3', 500)])
    if lot_id:
        grade_pending(lot_id, 'P1')
        grade_pending(lot_id, 'P2', c_count=2)
        grade_pending(lot_id, 'P3', leave=12)

    # 已签核：三个托盘判齐且加权区间上限低于 2%。
    lot_id = open_plan('PK-261121-06', [('T1', 400), ('T2', 400), ('T3', 400)])
    if lot_id:
        grade_pending(lot_id)
        for _ in range(4):
            if db.execute('SELECT state FROM sample_plan WHERE lot_id=%s', (lot_id,)).fetchone()['state'] == 'ready':
                break
            issue_round(db, lot_id, None, 'operator')
            grade_pending(lot_id)
        sign_plan(db, lot_id, PlanSignInput(note='三托盘判齐，加权区间上限低于 2%，同意放行。'), 'supervisor')


def seed():
    with connect() as db:
        db.execute('SELECT pg_advisory_xact_lock(106501)')
        for role, display in STAFF:
            if not db.execute('SELECT 1 FROM staff WHERE username=%s', (role,)).fetchone():
                db.execute('INSERT INTO staff VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                           (role, display, role, password_hash('PackDemo2026!')))
        for stock in STOCK:
            db.execute('INSERT INTO material_stock VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING', stock)
        for code, product, machine, units, film_sku, values, target in SAMPLES:
            if db.execute('SELECT 1 FROM pack_lot WHERE code=%s', (code,)).fetchone():
                continue
            lot = create_lot(db, LotInput(code=code, product=product, machine=machine, units=units, film_sku=film_sku), 'operator')
            lot_id = lot['id']
            if values is None:
                continue
            fields = dict(zip(CHANNELS, values, strict=True))
            capture(db, lot_id, MeasureInput(sample=f'{code}-S01', machine=machine, **fields), 'operator')
            if target == 'blocked':
                continue
            if target in ('review', 'override'):
                marked = add_mark(db, lot_id, MarkInput(kind='wrinkle' if target == 'review' else 'seal',
                                  zone='top-seal', x_pct=67, y_pct=18, note='热封边有一道连续压痕，保留实物复核。'), 'operator')
                if target == 'override':
                    review_mark(db, lot_id, marked['id'], MarkReview(state='confirmed', note='复核实物确认封口折边。'), 'supervisor')
            enqueue(db, lot_id, 'operator')
            grade_next(db, lot_id)
            if target == 'review':
                continue
            current = latest_measure(db, lot_id)
            decision = latest_grade(db, current['id'])
            if decision['model_grade'] != 'A':
                raise RuntimeError(f'Seed fixture {code} expected A, got {decision}')
            if target == 'closed':
                sign_grade(db, lot_id, GradeReview(grade='A'), 'supervisor')
                close_lot(db, lot_id, 'supervisor')
            else:
                sign_grade(db, lot_id, GradeReview(grade='B', reason='实物热封带折入膜层，抽检区段需重新换膜。',
                                                 rework_units=160), 'supervisor')
        seed_sampling(db)
        tables = ('staff', 'material_stock', 'pack_lot', 'visual_measure', 'defect_mark', 'grade_decision',
                  'rework_issue', 'audit_event', 'sample_plan', 'sample_pallet', 'sample_round', 'sample_item')
        print(json.dumps({table: db.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] for table in tables}, sort_keys=True))


if __name__ == '__main__':
    seed()
