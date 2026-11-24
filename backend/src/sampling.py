"""托盘分层抽检：登记方案、随机定号、逐件判级、加权估计与签核闸门。

完整性约定：
- 件号在抽次发放时随机定号并持久化，中断恢复沿用原件号，绝不重抽。
- 判级按 (pallet_id, item_no) 唯一落库，重试返回原结果，不重复计数。
- 补抽与签核共用方案行锁；已发件号未判齐时签核暂停。
"""

import hashlib
import json
import random
import secrets

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .inspection import audit, lot_row
from .model import predict
from .sampling_stats import (CONFIDENCE, THRESHOLD, Z_PALLET, compute_view, suggest_draw, wilson, z_batch)
from .schemas import CHANNELS

EMPTY_COUNT = {'issued': 0, 'judged': 0, 'c': 0, 'pending': 0}


def plan_row(db, lot_id, lock=False):
    row = db.execute('SELECT * FROM sample_plan WHERE lot_id=%s' + (' FOR UPDATE' if lock else ''),
                     (lot_id,)).fetchone()
    if not row:
        raise HTTPException(404, '该批次尚未登记抽检方案')
    return row


def snapshot(db, plan_id):
    pallets = db.execute('SELECT * FROM sample_pallet WHERE plan_id=%s ORDER BY id', (plan_id,)).fetchall()
    counts = {row['pallet_id']: row for row in db.execute(
        '''SELECT i.pallet_id, count(*) AS issued,
                  count(*) FILTER (WHERE i.state='judged') AS judged,
                  count(*) FILTER (WHERE i.state='judged' AND i.grade='C') AS c,
                  count(*) FILTER (WHERE i.state='pending') AS pending
           FROM sample_item i JOIN sample_pallet p ON p.id=i.pallet_id
           WHERE p.plan_id=%s GROUP BY i.pallet_id''', (plan_id,)).fetchall()}
    return pallets, counts


def draw_round(db, pallet, size, kind, actor):
    """随机定号并持久化一个抽次。种子留档，件号不重复。"""
    if size <= 0:
        return None
    seed = secrets.token_hex(8)
    taken = {row['item_no'] for row in
             db.execute('SELECT item_no FROM sample_item WHERE pallet_id=%s', (pallet['id'],))}
    rng = random.Random(seed)
    picks = set()
    while len(picks) < size:
        need = size - len(picks)
        candidates = rng.sample(range(1, pallet['units'] + 1), min(need + 4, pallet['units']))
        picks.update(no for no in candidates if no not in taken)
    picks = sorted(picks)[:size]
    round_no = db.execute('SELECT COALESCE(MAX(round_no),0)+1 AS n FROM sample_round WHERE pallet_id=%s',
                          (pallet['id'],)).fetchone()['n']
    rnd = db.execute('''INSERT INTO sample_round(pallet_id,round_no,draw_size,seed,kind,created_by)
                        VALUES (%s,%s,%s,%s,%s,%s) RETURNING *''',
                     (pallet['id'], round_no, size, seed, kind, actor)).fetchone()
    with db.cursor() as cursor:
        cursor.executemany('INSERT INTO sample_item(round_id,pallet_id,item_no) VALUES (%s,%s,%s)',
                           [(rnd['id'], pallet['id'], no) for no in picks])
    return rnd


def evaluate(db, plan, actor):
    """重估各托盘与整批结论，推进状态机。所有转移在同一事务内落库。"""
    lot_id = plan['lot_id']
    threshold = plan['threshold']
    pallets, counts = snapshot(db, plan['id'])
    for pallet in pallets:
        cnt = counts.get(pallet['id'], EMPTY_COUNT)
        n, c, pending = cnt['judged'], cnt['c'], cnt['pending']
        if pallet['state'] == 'full_inspection':
            if pending == 0 and n >= pallet['units'] and pallet['conclusion'] is None:
                conclusion = 'pass' if c / pallet['units'] < threshold else 'fail'
                db.execute('UPDATE sample_pallet SET conclusion=%s WHERE id=%s', (conclusion, pallet['id']))
                audit(db, lot_id, actor, 'pallet_concluded', pallet=pallet['label'], conclusion=conclusion,
                      judged=n, c=c, rate=c / pallet['units'], kind='full')
        elif pending == 0 and n > 0 and pallet['conclusion'] != 'pass':
            if n >= pallet['units']:
                conclusion = 'pass' if c / pallet['units'] < threshold else 'fail'
                if pallet['conclusion'] != conclusion:
                    db.execute('UPDATE sample_pallet SET conclusion=%s WHERE id=%s', (conclusion, pallet['id']))
                    audit(db, lot_id, actor, 'pallet_concluded', pallet=pallet['label'], conclusion=conclusion,
                          judged=n, c=c, rate=c / pallet['units'], kind='exact')
            else:
                lo, hi = wilson(c, n, Z_PALLET)
                if hi < threshold:
                    db.execute("UPDATE sample_pallet SET conclusion='pass' WHERE id=%s", (pallet['id'],))
                    audit(db, lot_id, actor, 'pallet_concluded', pallet=pallet['label'], conclusion='pass',
                          judged=n, c=c, low=lo, high=hi, kind='sample')
                elif lo >= threshold:
                    # 下限达到阈值：该托盘转全检，补齐剩余件号。
                    db.execute("UPDATE sample_pallet SET state='full_inspection',conclusion=NULL WHERE id=%s",
                               (pallet['id'],))
                    rnd = draw_round(db, pallet, pallet['units'] - cnt['issued'], 'full', actor)
                    audit(db, lot_id, actor, 'pallet_full_inspection', pallet=pallet['label'], trigger='pallet',
                          judged=n, c=c, low=lo, high=hi, round_no=rnd['round_no'], draw_size=rnd['draw_size'])
    pallets, counts = snapshot(db, plan['id'])
    view = compute_view(plan, pallets, counts)
    if view['low'] >= threshold:
        # 整批加权下限达到阈值：未齐件托盘一并转全检。
        fired = False
        for pallet, pv in zip(pallets, view['pallets'], strict=True):
            if pallet['state'] == 'sampling' and pv['issued'] < pallet['units']:
                db.execute("UPDATE sample_pallet SET state='full_inspection',conclusion=NULL WHERE id=%s",
                           (pallet['id'],))
                rnd = draw_round(db, pallet, pallet['units'] - pv['issued'], 'full', actor)
                audit(db, lot_id, actor, 'pallet_full_inspection', pallet=pallet['label'], trigger='batch',
                      round_no=rnd['round_no'], draw_size=rnd['draw_size'])
                fired = True
        if fired:
            pallets, counts = snapshot(db, plan['id'])
            view = compute_view(plan, pallets, counts)
    all_judged = all(pv['judged'] >= pv['units'] for pv in view['pallets'])
    all_concluded = all(pv['conclusion'] or pv['judged'] >= pv['units'] for pv in view['pallets'])
    if all_judged and view['pending'] == 0:
        # 抽完按实数判。
        actual = view['total_c'] / view['total_units']
        new_state = 'ready' if actual < threshold else 'rejected'
    elif all_concluded and view['pending'] == 0 and view['high'] < threshold:
        new_state = 'ready'
    elif any(pv['state'] == 'full_inspection' for pv in view['pallets']):
        new_state = 'full_inspection'
    else:
        new_state = 'sampling'
    if plan['state'] != new_state and plan['state'] not in ('signed', 'rejected'):
        db.execute('UPDATE sample_plan SET state=%s WHERE id=%s', (new_state, plan['id']))
        if new_state == 'ready':
            audit(db, lot_id, actor, 'plan_ready', estimate=view['estimate'], high=view['high'])
        elif new_state == 'rejected':
            audit(db, lot_id, actor, 'plan_rejected', actual=view['total_c'] / view['total_units'],
                  total_judged=view['total_judged'])
        elif new_state == 'full_inspection':
            audit(db, lot_id, actor, 'plan_full_inspection', low=view['low'])
        plan['state'] = new_state
    return view


def create_plan(db, lot_id, data, actor):
    lot = lot_row(db, lot_id, lock=True)
    if db.execute('SELECT 1 FROM sample_plan WHERE lot_id=%s', (lot_id,)).fetchone():
        raise HTTPException(409, '该批次已登记抽检方案')
    labels = [pallet.label for pallet in data.pallets]
    if len(set(labels)) != len(labels):
        raise HTTPException(422, '托盘编号不可重复')
    total = sum(pallet.units for pallet in data.pallets)
    if total != lot['units']:
        raise HTTPException(422, f'托盘件数之和 {total} 须等于批次件数 {lot["units"]}')
    plan = db.execute('INSERT INTO sample_plan(lot_id,created_by) VALUES (%s,%s) RETURNING *',
                      (lot_id, actor)).fetchone()
    zb = z_batch(len(data.pallets))
    for entry in data.pallets:
        pallet = db.execute('INSERT INTO sample_pallet(plan_id,label,units) VALUES (%s,%s,%s) RETURNING *',
                            (plan['id'], entry.label, entry.units)).fetchone()
        # 首轮按「零 C 即达签核线」规划抽量。
        draw_round(db, pallet, suggest_draw(0, 0, pallet['units'], zb), 'sample', actor)
    audit(db, lot_id, actor, 'plan_created', pallets=len(data.pallets), units=total,
          threshold=THRESHOLD, confidence=CONFIDENCE)
    evaluate(db, plan, actor)
    return plan_detail(db, lot_id)


def issue_round(db, lot_id, data, actor):
    """分次补抽：只对已判齐的托盘发放下一抽次；缺省覆盖所有未决托盘。"""
    lot_row(db, lot_id)
    plan = plan_row(db, lot_id, lock=True)
    if plan['state'] in ('signed', 'rejected'):
        raise HTTPException(409, '抽检方案已结案，无法补抽')
    pallets, counts = snapshot(db, plan['id'])
    zb = z_batch(len(pallets))
    specific = data and data.pallet_id is not None
    if specific:
        pallet = next((p for p in pallets if p['id'] == data.pallet_id), None)
        if not pallet:
            raise HTTPException(404, '找不到抽检托盘')
        targets = [pallet]
    else:
        targets = [p for p in pallets if p['state'] == 'sampling']
    issued = []
    for pallet in targets:
        cnt = counts.get(pallet['id'], EMPTY_COUNT)
        remaining = pallet['units'] - cnt['issued']
        if cnt['pending'] > 0:
            if specific:
                raise HTTPException(409, '上一抽次件号未判齐，判齐后再补抽')
            continue
        if remaining <= 0:
            if specific:
                raise HTTPException(409, '该托盘件号已全部发放')
            continue
        size = min(suggest_draw(cnt['c'], cnt['judged'], pallet['units'], zb), remaining)
        if size <= 0:
            continue
        rnd = draw_round(db, pallet, size, 'sample', actor)
        db.execute('UPDATE sample_pallet SET conclusion=NULL WHERE id=%s', (pallet['id'],))
        audit(db, lot_id, actor, 'round_issued', pallet=pallet['label'], round_no=rnd['round_no'],
              draw_size=rnd['draw_size'], seed=rnd['seed'], kind='sample')
        issued.append({**rnd, 'pallet': pallet['label']})
    if not issued:
        raise HTTPException(409, '当前没有可补抽的托盘')
    evaluate(db, plan, actor)
    return {'issued': issued}


def grade_item(db, lot_id, item_id, data, actor):
    """逐件判级。已判件号直接返回原结果，重试不重复计数。"""
    lot_row(db, lot_id)
    plan = plan_row(db, lot_id, lock=True)
    if plan['state'] in ('signed', 'rejected'):
        raise HTTPException(409, '抽检方案已结案，无法再判级')
    item = db.execute('''SELECT i.* FROM sample_item i JOIN sample_pallet p ON p.id=i.pallet_id
                         WHERE i.id=%s AND p.plan_id=%s FOR UPDATE OF i''',
                      (item_id, plan['id'])).fetchone()
    if not item:
        raise HTTPException(404, '找不到抽检件号')
    if item['state'] == 'judged':
        return item
    channels = {key: getattr(data, key) for key in CHANNELS}
    try:
        grade, _evidence = predict(channels)
    except ValueError as exc:
        raise HTTPException(422, '五通道读数无效，模型无法判级') from exc
    digest = hashlib.sha256(json.dumps({'pallet_id': item['pallet_id'], 'item_no': item['item_no'],
                                        'channels': channels}, sort_keys=True).encode()).hexdigest()
    row = db.execute('''UPDATE sample_item SET state='judged',grade=%s,channels=%s,input_sha256=%s,
                        judged_by=%s,judged_at=now() WHERE id=%s RETURNING *''',
                     (grade, Jsonb(channels), digest, actor, item_id)).fetchone()
    evaluate(db, plan, actor)
    return row


def sign_plan(db, lot_id, data, actor):
    """签核闸门：判齐、各托盘有结论、加权区间上限低于阈值，三者同时满足。"""
    lot_row(db, lot_id)
    plan = plan_row(db, lot_id, lock=True)
    if plan['state'] == 'signed':
        raise HTTPException(409, '抽检方案已签核')
    if plan['state'] == 'rejected':
        raise HTTPException(409, '实测 C 级占比达到 2%，方案已判退')
    view = evaluate(db, plan, actor)
    if view['pending'] > 0:
        raise HTTPException(409, {'message': '已发件号未判齐，暂停签核', 'pending': view['pending']})
    inconclusive = [pv['label'] for pv in view['pallets'] if not pv['conclusion']]
    if inconclusive:
        raise HTTPException(409, {'message': '尚有托盘无结论，继续抽检', 'pallets': inconclusive})
    if view['high'] >= plan['threshold']:
        raise HTTPException(409, {'message': '加权区间上限未低于 2%，不得签核', 'high': view['high']})
    basis = {'threshold': plan['threshold'], 'confidence': plan['confidence'], 'z_batch': view['z_batch'],
             'estimate': view['estimate'], 'low': view['low'], 'high': view['high'],
             'total_units': view['total_units'], 'total_judged': view['total_judged'],
             'total_c': view['total_c'], 'note': data.note,
             'pallets': [{'label': pv['label'], 'units': pv['units'], 'judged': pv['judged'], 'c': pv['c'],
                          'rate': pv['rate'], 'low': pv['low'], 'high': pv['high'], 'state': pv['state'],
                          'conclusion': pv['conclusion']} for pv in view['pallets']]}
    row = db.execute('''UPDATE sample_plan SET state='signed',signed_by=%s,signed_at=now(),basis=%s
                        WHERE id=%s RETURNING *''', (actor, Jsonb(basis), plan['id'])).fetchone()
    audit(db, lot_id, actor, 'plan_signed', note=data.note, estimate=view['estimate'], low=view['low'],
          high=view['high'], total_judged=view['total_judged'], total_c=view['total_c'])
    return row


def plan_detail(db, lot_id):
    lot = lot_row(db, lot_id)
    plan = db.execute('SELECT * FROM sample_plan WHERE lot_id=%s', (lot_id,)).fetchone()
    if not plan:
        return {'lot': lot, 'plan': None}
    pallets, counts = snapshot(db, plan['id'])
    view = compute_view(plan, pallets, counts)
    rounds = db.execute('''SELECT r.*, p.label AS pallet_label,
                                  count(i.id) FILTER (WHERE i.state='judged') AS judged,
                                  count(i.id) FILTER (WHERE i.state='pending') AS pending
                           FROM sample_round r JOIN sample_pallet p ON p.id=r.pallet_id
                           LEFT JOIN sample_item i ON i.round_id=r.id
                           WHERE p.plan_id=%s GROUP BY r.id, p.label ORDER BY r.id DESC''',
                        (plan['id'],)).fetchall()
    pending_items = db.execute('''SELECT i.id, i.pallet_id, i.item_no, i.round_id, r.round_no, p.label AS pallet_label
                                  FROM sample_item i
                                  JOIN sample_pallet p ON p.id=i.pallet_id
                                  JOIN sample_round r ON r.id=i.round_id
                                  WHERE p.plan_id=%s AND i.state='pending' ORDER BY i.id LIMIT 200''',
                               (plan['id'],)).fetchall()
    recent_items = db.execute('''SELECT i.id, i.item_no, i.grade, i.judged_by, i.judged_at, p.label AS pallet_label
                                 FROM sample_item i JOIN sample_pallet p ON p.id=i.pallet_id
                                 WHERE p.plan_id=%s AND i.state='judged'
                                 ORDER BY i.judged_at DESC, i.id DESC LIMIT 50''', (plan['id'],)).fetchall()
    events = db.execute('''SELECT * FROM audit_event WHERE lot_id=%s
                           AND (action LIKE 'plan_%%' OR action LIKE 'round_%%' OR action LIKE 'pallet_%%')
                           ORDER BY id DESC LIMIT 50''', (lot_id,)).fetchall()
    return {'lot': lot, 'plan': plan, 'evaluation': view, 'rounds': rounds,
            'pending_items': pending_items, 'recent_items': recent_items, 'events': events}
