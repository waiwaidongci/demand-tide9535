"""区域-门店联合预测：利用同期残差关联协调，保证门店逐日合计等于区域且非负。

仅依赖标准库；与 forecast_algorithm 共用 predict/quantile 原语，保证单序列口径不变。
区间由同一次联合抽样（Cholesky 相关多元正态）生成，区域与门店的上下界来自同一批路径，
再做非负、合计一致的协调，因此两层区间可以逐日核对。
回测严格扩展窗口：第 i 天的模型选择、关联估计、抽样只使用 values[:i]。
"""
import math
import random
from .forecast_algorithm import predict, quantile

SAMPLE_SIZE = 500
VARIANCE_FLOOR = 1e-6
PAIR_MIN_BASE = 42


def _es_predictions(values, alpha):
    """指数平滑的一步递推预测序列，pred[t] 只使用 values[:t]。"""
    level = values[0]
    preds = [None]
    for value in values[1:]:
        preds.append(level)
        level = alpha * value + (1 - alpha) * level
    return preds


def _sn_predictions(values, season):
    return [None] * season + values[:-season]


def _candidate_paths(values, season):
    paths = {}
    paths[('seasonal_naive', None)] = _sn_predictions(values, season)
    for alpha in (.2, .5, .8):
        paths[('exponential_smoothing', alpha)] = _es_predictions(values, alpha)
    return paths


def _select_model(values, season):
    """在给定前缀上按滚动一步 MAE 选模型；只看前缀内残差。"""
    warmup = season
    best = None
    for key, preds in _candidate_paths(values, season).items():
        residuals = [values[t] - preds[t] for t in range(warmup, len(values))]
        mae = sum(abs(e) for e in residuals) / len(residuals)
        if best is None or mae < best[0]:
            best = (mae, key[0], key[1])
    return {'model': best[1], 'alpha': best[2]}


def _residual_vector(values, model, alpha, season, end):
    """返回截至 end（不含）的一步残差列表，下标与 values 对齐。"""
    preds = _sn_predictions(values, season) if model == 'seasonal_naive' \
        else _es_predictions(values, alpha)
    warmup = season if model == 'seasonal_naive' else 1
    return [None if t < warmup else values[t] - preds[t] for t in range(end)]


def _sample_covariance(matrix):
    """matrix: n×k 同期残差；返回样本协方差 k×k。"""
    n = len(matrix)
    k = len(matrix[0])
    means = [sum(row[j] for row in matrix) / n for j in range(k)]
    cov = [[0.0] * k for _ in range(k)]
    for row in matrix:
        centered = [row[j] - means[j] for j in range(k)]
        for a in range(k):
            for b in range(a, k):
                cov[a][b] += centered[a] * centered[b]
    for a in range(k):
        for b in range(a, k):
            cov[a][b] /= max(1, n - 1)
            cov[b][a] = cov[a][b]
    for j in range(k):
        cov[j][j] = max(cov[j][j], VARIANCE_FLOOR)
    return cov


def _shrink(cov, matrix):
    """Ledoit-Wolf 风格向对角目标收缩，返回 (收缩后矩阵, λ)；κ 为 0 时直接对角。"""
    k = len(cov)
    n = len(matrix)
    means = [sum(row[j] for row in matrix) / n for j in range(k)]
    pi = 0.0
    for row in matrix:
        x = [row[j] - means[j] for j in range(k)]
        for a in range(k):
            for b in range(k):
                pi += (x[a] * x[b] - cov[a][b]) ** 2
    pi /= n
    rho = 0.0
    for row in matrix:
        for j in range(k):
            xj = row[j] - means[j]
            rho += (xj * xj - cov[j][j]) ** 2
    rho /= n
    kappa = sum(cov[a][b] ** 2 for a in range(k) for b in range(k) if a != b)
    lam = 1.0 if kappa <= 1e-12 else max(0.0, min(1.0, (pi - rho) / (n * kappa)))
    shrunk = [[0.0] * k for _ in range(k)]
    for a in range(k):
        for b in range(k):
            target = cov[a][b] if a == b else 0.0
            shrunk[a][b] = (1 - lam) * cov[a][b] + lam * target
    return shrunk, lam


def _cholesky(matrix):
    """正定矩阵 Cholesky 分解；非正定返回 None。"""
    k = len(matrix)
    low = [[0.0] * k for _ in range(k)]
    for a in range(k):
        for b in range(a + 1):
            total = sum(low[a][m] * low[b][m] for m in range(b))
            if a == b:
                value = matrix[a][a] - total
                if value <= 1e-12:
                    return None
                low[a][b] = math.sqrt(value)
            else:
                low[a][b] = (matrix[a][b] - total) / low[b][b]
    return low


def _correlation(cov):
    k = len(cov)
    corr = [[0.0] * k for _ in range(k)]
    for a in range(k):
        for b in range(k):
            denom = math.sqrt(cov[a][a] * cov[b][b])
            corr[a][b] = round(cov[a][b] / denom, 4) if denom > 0 else 0.0
    return corr


def _estimate_cov(residual_rows, member_ids, pair_min):
    """同期残差行（key 为 member id）估计协方差；重叠不足/非正定时逐级回退。

    返回 dict：matrix（按 member_ids 排序）、method、shrinkage、reason。
    """
    aligned = []
    for row in residual_rows:
        aligned.append([row[sid] for sid in member_ids])
    n = len(aligned)
    cov = _sample_covariance(aligned)
    if n < pair_min:
        diag = [[0.0] * len(member_ids) for _ in member_ids]
        for j, sid in enumerate(member_ids):
            diag[j][j] = cov[j][j]
        return {'matrix': diag, 'method': 'diagonal', 'shrinkage': 1.0,
                'reason': f'同期重叠仅 {n} 天，低于关联估计下限 {pair_min} 天，按独立序列处理（关联置 0）'}
    shrunk, lam = _shrink(cov, aligned)
    for extra in (0.0, .25, .5, .8, 1.0):
        trial_lam = max(lam, extra)
        trial = [[0.0] * len(member_ids) for _ in member_ids]
        for a in range(len(member_ids)):
            for b in range(len(member_ids)):
                target = cov[a][b] if a == b else 0.0
                trial[a][b] = (1 - trial_lam) * cov[a][b] + trial_lam * target
        if _cholesky(trial) is not None:
            return {'matrix': trial, 'method': 'shrinkage' if trial_lam < 1 else 'diagonal',
                    'shrinkage': round(trial_lam, 4), 'reason': None}
    diag = [[0.0] * len(member_ids) for _ in member_ids]
    for j in range(len(member_ids)):
        diag[j][j] = cov[j][j]
    return {'matrix': diag, 'method': 'diagonal', 'shrinkage': 1.0,
            'reason': '收缩后协方差仍非正定，无法稳定估计关联，回退为对角独立抽样'}


def _reconcile_stores(region_point, store_points, weights):
    """区域点预测为锚的非负 GLS 协调：门店非负、合计严格等于区域。

    weights 为权重（取门店方差倒数），等价于固定区域锚点的 MinT 闭式解。
    """
    k = len(store_points)
    total = sum(store_points)
    if total <= 0:
        share = region_point / k
        return [share for _ in store_points]
    gap = region_point - total
    wsum = sum(weights)
    adjusted = [p + gap * weights[j] / wsum for j, p in enumerate(store_points)]
    # 非负投影：负值截 0 后，缺口在剩余正值门店间按权重再分摊，直至全部非负
    for _ in range(k + 1):
        negatives = [j for j, v in enumerate(adjusted) if v < -1e-12]
        if not negatives:
            break
        deficit = sum(-adjusted[j] for j in negatives)
        for j in negatives:
            adjusted[j] = 0.0
        positive = [j for j, v in enumerate(adjusted) if v > 1e-12]
        if not positive:
            adjusted = [region_point / k for _ in adjusted]
            break
        wpos = sum(weights[j] for j in positive)
        for j in positive:
            adjusted[j] -= deficit * weights[j] / wpos
    return [max(0.0, v) for v in adjusted]


def _reconcile_sample(region_draw, store_draws):
    """单条联合抽样路径的协调：区域、门店均非负，门店合计等于区域抽样值。"""
    region_draw = max(0.0, region_draw)
    k = len(store_draws)
    draws = [max(0.0, v) for v in store_draws]
    total = sum(draws)
    if total <= 0:
        return region_draw, [region_draw / k for _ in draws]
    if total != region_draw:
        scale = region_draw / total
        draws = [v * scale for v in draws]
    return region_draw, draws


def _round_coherent(region_value, store_values):
    """两位小数舍入，尾差并入最大门店，保证合计严格相等且非负。"""
    region_value = max(0.0, round(region_value, 2))
    stores = [max(0.0, round(v, 2)) for v in store_values]
    diff = round(region_value - sum(stores), 2)
    if abs(diff) >= 0.01:
        idx = max(range(len(stores)), key=lambda j: stores[j])
        stores[idx] = max(0.0, round(stores[idx] + diff, 2))
    return region_value, stores


def _metrics(actual, pairs):
    """pairs 为 (pred, low, high|None) 列表；返回 MAE、WAPE、80% 覆盖率。

    独立序列的区间不能相加：聚合层校准前没有区间时覆盖率返回 None，由页面标注口径。
    """
    errors = [a - p for a, (p, _, _) in zip(actual, pairs)]
    denom = sum(actual)
    mae = round(sum(abs(e) for e in errors) / len(errors), 4)
    wape = round(sum(abs(e) for e in errors) / denom, 6) if denom else None
    bounded = [(a, lo, hi) for a, (_, lo, hi) in zip(actual, pairs) if hi is not None]
    covered = sum(1 for a, lo, hi in bounded if lo <= a <= hi)
    coverage = round(covered / len(bounded), 4) if bounded else None
    return {'mae': mae, 'wape': wape, 'coverage': coverage}


def joint_forecast(series, dates, region_id, store_ids, horizon, season, seed=42):
    """联合预测主入口。

    series: {series_id: 与 dates 对齐的非负日值列表}，dates 为各序列共同日期。
    返回点预测、联合抽样区间、回测指标与关联诊断；所有约束在返回前已强制。
    """
    if not 1 <= horizon <= 30 or not 2 <= season <= 30:
        raise ValueError('预测期1–30天，季节周期2–30天')
    if region_id not in series:
        raise ValueError('区域序列不存在，无法建立联合预测')
    if not store_ids or len(set(store_ids)) != len(store_ids):
        raise ValueError('请至少选择一个门店，且门店不能重复')
    if region_id in store_ids:
        raise ValueError('区域序列不能同时作为门店序列')
    if any(sid not in series for sid in store_ids):
        raise ValueError('门店序列不存在，无法建立联合预测')
    if len(store_ids) > 10:
        raise ValueError('单次联合预测最多协调 10 个门店')
    member_ids = [region_id] + list(store_ids)
    n = len(dates)
    need = max(42, season * 3)
    for sid in member_ids:
        values = series[sid]
        if len(values) != n:
            raise ValueError('各序列必须在共同日期上对齐后再联合预测')
        if len(values) < need:
            raise ValueError(f'序列 {sid} 观测不足：共同区间至少 {need} 天且不少于 3 个季节周期')
        if any(not math.isfinite(x) or x < 0 for x in values):
            raise ValueError(f'序列 {sid} 需求必须为非负有限数')
    pair_min = max(PAIR_MIN_BASE, season * 3)
    rng = random.Random(seed)
    holdout = min(28, n // 3)
    start = n - holdout

    # ---- 同步回测：每个起点仅使用此前数据 ----
    back_rows = []
    accum = {sid: {'actual': [], 'base': [], 'recon': []} for sid in member_ids}
    accum['store_total'] = {'actual': [], 'base': [], 'recon': []}
    origin_events = []
    for i in range(start, n):
        member_residuals, base_points = [], {}
        for sid in member_ids:
            prefix = series[sid][:i]
            chosen = _select_model(prefix, season)
            residuals = _residual_vector(prefix, chosen['model'], chosen['alpha'], season, i)
            member_residuals.append({t: residuals[t] for t in range(i) if residuals[t] is not None})
            base_points[sid] = predict(prefix, chosen['model'], season, chosen['alpha'])
        common_idx = sorted(set.intersection(*(set(row) for row in member_residuals)))
        aligned_rows = [{sid: member_residuals[j][t] for j, sid in enumerate(member_ids)}
                        for t in common_idx]
        estimate = _estimate_cov(aligned_rows, member_ids, pair_min)
        if estimate['reason']:
            origin_events.append({'day': dates[i].isoformat(), 'reason': estimate['reason']})
        low = _cholesky(estimate['matrix'])
        # 经验残差分位带（校准前区间），同样只来自此前残差
        base_bounds = {}
        for sid in member_ids:
            past = [row[sid] for row in aligned_rows]
            base_bounds[sid] = (quantile(past, .1), quantile(past, .9))
        # 同一次联合抽样：所有成员、所有路径共享该起点的随机数
        draws = {sid: [] for sid in member_ids}
        for _ in range(SAMPLE_SIZE):
            z = [rng.gauss(0, 1) for _ in member_ids]
            innovation = [sum(low[a][m] * z[m] for m in range(a + 1)) for a in range(len(member_ids))]
            region_draw, store_draws = _reconcile_sample(
                base_points[region_id] + innovation[0],
                [base_points[sid] + innovation[j + 1] for j, sid in enumerate(store_ids)])
            draws[region_id].append(region_draw)
            for j, sid in enumerate(store_ids):
                draws[sid].append(store_draws[j])
        weights = [1.0 / max(estimate['matrix'][j + 1][j + 1], VARIANCE_FLOOR)
                   for j in range(len(store_ids))]
        recon_stores = _reconcile_stores(base_points[region_id],
                                         [base_points[sid] for sid in store_ids], weights)
        row = {'day': dates[i].isoformat(),
               'actual': {sid: series[sid][i] for sid in member_ids},
               'base_point': {sid: round(base_points[sid], 2) for sid in member_ids},
               'base_lower': {sid: round(max(0, base_points[sid] + base_bounds[sid][0]), 2)
                              for sid in member_ids},
               'base_upper': {sid: round(max(0, base_points[sid] + base_bounds[sid][1]), 2)
                              for sid in member_ids},
               'reconciled_point': {},
               'reconciled_lower': {}, 'reconciled_upper': {}}
        region_r, stores_r = _round_coherent(base_points[region_id], recon_stores)
        row['reconciled_point'][region_id] = region_r
        for j, sid in enumerate(store_ids):
            row['reconciled_point'][sid] = stores_r[j]
        for sid in member_ids:
            row['reconciled_lower'][sid] = round(quantile(draws[sid], .1), 2)
            row['reconciled_upper'][sid] = round(quantile(draws[sid], .9), 2)
        back_rows.append(row)
        for sid in member_ids:
            accum[sid]['actual'].append(series[sid][i])
            accum[sid]['base'].append((row['base_point'][sid], row['base_lower'][sid],
                                       row['base_upper'][sid]))
            accum[sid]['recon'].append((row['reconciled_point'][sid], row['reconciled_lower'][sid],
                                        row['reconciled_upper'][sid]))
        actual_region = series[region_id][i]
        base_total = sum(row['base_point'][sid] for sid in store_ids)
        recon_total = sum(row['reconciled_point'][sid] for sid in store_ids)
        accum['store_total']['actual'].append(actual_region)
        # 校准前：各门店独立区间不能相加，聚合层只有点预测、无区间
        accum['store_total']['base'].append((round(base_total, 2), 0, None))
        # 协调后：门店合计即区域锚点，区间与区域完全一致
        accum['store_total']['recon'].append(
            (round(recon_total, 2), row['reconciled_lower'][region_id],
             row['reconciled_upper'][region_id]))

    # ---- 全量重训，未来多步联合预测 ----
    final_selected, member_residuals, histories = {}, [], {}
    for sid in member_ids:
        chosen = _select_model(series[sid], season)
        final_selected[sid] = chosen
        residuals = _residual_vector(series[sid], chosen['model'], chosen['alpha'], season, n)
        member_residuals.append({t: residuals[t] for t in range(n) if residuals[t] is not None})
        histories[sid] = list(series[sid])
    common_idx = sorted(set.intersection(*(set(row) for row in member_residuals)))
    aligned_rows = [{sid: member_residuals[j][t] for j, sid in enumerate(member_ids)}
                    for t in common_idx]
    final_estimate = _estimate_cov(aligned_rows, member_ids, pair_min)
    if final_estimate['reason']:
        origin_events.append({'day': None, 'reason': final_estimate['reason']})
    low = _cholesky(final_estimate['matrix'])
    point_rows = []
    for h in range(horizon):
        base_points = {sid: predict(histories[sid], final_selected[sid]['model'], season,
                                    final_selected[sid]['alpha']) for sid in member_ids}
        draws = {sid: [] for sid in member_ids}
        for _ in range(SAMPLE_SIZE):
            z = [rng.gauss(0, 1) for _ in member_ids]
            innovation = [sum(low[a][m] * z[m] for m in range(a + 1)) for a in range(len(member_ids))]
            region_draw, store_draws = _reconcile_sample(
                base_points[region_id] + innovation[0],
                [base_points[sid] + innovation[j + 1] for j, sid in enumerate(store_ids)])
            draws[region_id].append(region_draw)
            for j, sid in enumerate(store_ids):
                draws[sid].append(store_draws[j])
        weights = [1.0 / max(final_estimate['matrix'][j + 1][j + 1], VARIANCE_FLOOR)
                   for j in range(len(store_ids))]
        recon_stores = _reconcile_stores(base_points[region_id],
                                         [base_points[sid] for sid in store_ids], weights)
        region_r, stores_r = _round_coherent(base_points[region_id], recon_stores)
        point = {'offset': h + 1,
                 'base_point': {sid: round(base_points[sid], 2) for sid in member_ids},
                 'reconciled_point': {region_id: region_r},
                 'lower': {}, 'upper': {}}
        for j, sid in enumerate(store_ids):
            point['reconciled_point'][sid] = stores_r[j]
        for sid in member_ids:
            point['lower'][sid] = round(quantile(draws[sid], .1), 2)
            point['upper'][sid] = round(quantile(draws[sid], .9), 2)
        point_rows.append(point)
        for sid in member_ids:
            histories[sid].append(point['reconciled_point'][sid])

    metrics = {}
    for sid in member_ids + ['store_total']:
        metrics[str(sid)] = {
            'base': _metrics(accum[sid]['actual'], accum[sid]['base']),
            'reconciled': _metrics(accum[sid]['actual'], accum[sid]['recon'])}
    reasons = []
    seen = set()
    for event in origin_events:
        if event['reason'] not in seen:
            seen.add(event['reason'])
            reasons.append(event['reason'])
    return {
        'run_type': 'joint',
        'region_series_id': region_id,
        'store_series_ids': list(store_ids),
        'member_series_ids': member_ids,
        'common_days': n,
        'overlap_days': len(common_idx),
        'pair_min_days': pair_min,
        'validation_days': holdout,
        'horizon': horizon,
        'season': season,
        'samples': SAMPLE_SIZE,
        'seed': seed,
        'selected': {str(sid): final_selected[sid] for sid in member_ids},
        'covariance': {'method': final_estimate['method'],
                       'shrinkage': final_estimate['shrinkage'],
                       'reason': final_estimate['reason']},
        'fallback_events': origin_events,
        'handling_notes': reasons,
        'correlation': _correlation(final_estimate['matrix']),
        'points': point_rows,
        'backtest': {'metrics': metrics, 'rows': back_rows},
        'interval_note': '同一次联合抽样生成区域与门店的 10%/90% 分位区间；门店逐日非负且合计等于区域，区间覆盖率为回测经验值，未建模节假日冲击。',
        'checksum': {str(sid): round(sum(series[sid]), 4) for sid in member_ids},
    }
