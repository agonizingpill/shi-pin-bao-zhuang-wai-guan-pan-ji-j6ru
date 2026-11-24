"""托盘分层抽检的区间估计。

- 单托盘结论使用双侧 95% Wilson 计分区间（z=1.96）。
- 整批区间按托盘件数加权合并各托盘区间；为守住整批 95% 置信度，
  各托盘边界使用 Bonferroni 修正的 z 值（同时覆盖 k 个托盘）。
- 托盘抽齐 n=N 时区间退化为实测值，整批结论按实数判定。
- 各抽次的件号在判级前随机定号并持久化，抽次不依赖判级结果，
  因此累计样本始终是托盘的简单随机样本，区间在任意停抽时点有效。
"""

from math import sqrt
from statistics import NormalDist

THRESHOLD = 0.02
CONFIDENCE = 0.95
MIN_STEP = 25

Z_PALLET = NormalDist().inv_cdf(1 - (1 - CONFIDENCE) / 2)


def z_batch(pallets):
    """整批加权区间的单托盘 z 值：Bonferroni 保证 k 个托盘同时覆盖 ≥ 95%。"""
    return NormalDist().inv_cdf(1 - (1 - CONFIDENCE) / 2 / max(pallets, 1))


def wilson(c, n, z):
    """Wilson 计分区间。c 可为外推的非整数件数。"""
    if n <= 0:
        return (0.0, 1.0)
    p = c / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = z / denom * sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def pallet_bounds(c, n, units, z):
    """单托盘 C 级占比区间；抽齐 n=units 时按实数，区间宽度为 0。"""
    if 0 < units <= n:
        rate = c / units
        return (rate, rate)
    return wilson(c, n, z)


def weighted_interval(entries, z):
    """按托盘件数加权合并。entries 为 (units, c, n)，返回 (估计, 下限, 上限)。"""
    total = sum(units for units, _, _ in entries)
    estimate = low = high = 0.0
    for units, c, n in entries:
        w = units / total
        lo, hi = pallet_bounds(c, n, units, z)
        estimate += w * (c / n if n else 0.0)
        low += w * lo
        high += w * hi
    return (estimate, low, high)


def compute_view(plan, pallets, counts):
    """汇总当前快照：各托盘区间（95% Wilson）与整批加权区间（Bonferroni z）。

    pallets 为方案托盘行，counts 为 {pallet_id: {issued, judged, c, pending}}。
    """
    zb = z_batch(len(pallets))
    entries = []
    views = []
    for pallet in pallets:
        cnt = counts.get(pallet['id'], {'issued': 0, 'judged': 0, 'c': 0, 'pending': 0})
        n, c = cnt['judged'], cnt['c']
        lo, hi = pallet_bounds(c, n, pallet['units'], Z_PALLET)
        entries.append((pallet['units'], c, n))
        views.append({**pallet, 'issued': cnt['issued'], 'judged': n, 'c': c, 'pending': cnt['pending'],
                      'rate': (c / n) if n else None, 'low': lo, 'high': hi})
    estimate, low, high = weighted_interval(entries, zb)
    return {'threshold': plan['threshold'], 'confidence': plan['confidence'], 'z_batch': zb,
            'estimate': estimate, 'low': low, 'high': high,
            'total_units': sum(pallet['units'] for pallet in pallets),
            'total_judged': sum(view['judged'] for view in views),
            'total_c': sum(view['c'] for view in views),
            'pending': sum(view['pending'] for view in views),
            'pallets': views}


def suggest_draw(c, n, units, z, min_step=MIN_STEP, threshold=THRESHOLD):
    """按当前观测率外推，给出达到结论（上限低于阈值或下限达到阈值）所需的下抽次件数。"""
    remaining = units - n
    if remaining <= 0:
        return 0
    rate = c / n if n else 0.0

    def decisive(total):
        lo, hi = wilson(rate * total, total, z)
        return hi < threshold or lo >= threshold

    if decisive(units):
        low, high = n + 1, units
        while low < high:
            mid = (low + high) // 2
            if decisive(mid):
                high = mid
            else:
                low = mid + 1
        needed = low
    else:
        needed = units
    return min(remaining, max(min_step, needed - n))
