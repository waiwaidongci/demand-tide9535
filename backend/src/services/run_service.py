from datetime import timedelta
from sqlalchemy import select,delete
from fastapi import HTTPException
from src.models import ForecastRun,ForecastPoint,Observation,Series
from src.config.queue import queue,QUEUE_NAME
from src.utils.serializers import serialize
from .series_service import get_series
from .forecast_algorithm import forecast
from .joint_forecast import joint_forecast

def get_run(db,run_id):
    run=db.get(ForecastRun,run_id)
    if not run: raise HTTPException(404,'预测任务不存在')
    return run

def detail(db,run_id):
    run=get_run(db,run_id)
    data=serialize(run)
    data['points']=[serialize(x) for x in db.scalars(select(ForecastPoint).where(ForecastPoint.run_id==run_id).order_by(ForecastPoint.day,ForecastPoint.series_id.is_(None),ForecastPoint.series_id))]
    if run.run_type=='joint':
        ids=[run.region_series_id]+list(run.store_series_ids or [])
        data['series_map']={str(s.id):serialize(s) for s in db.scalars(select(Series).where(Series.id.in_(ids)))}
        data['region_series']=serialize(get_series(db,run.region_series_id))
    else:
        data['series']=serialize(get_series(db,run.series_id))
    return data

def create_run(db,data,user):
    get_series(db,data.series_id)
    run=ForecastRun(**data.model_dump(),run_type='single',created_by=user.id)
    db.add(run); db.flush()
    return run

def create_joint_run(db,data,user):
    payload=data.model_dump()
    region_id=payload.pop('region_series_id'); store_ids=payload.pop('store_series_ids')
    get_series(db,region_id)
    if region_id in store_ids: raise HTTPException(422,'区域序列不能同时作为门店序列')
    if len(set(store_ids))!=len(store_ids): raise HTTPException(422,'门店序列不能重复选择')
    for sid in store_ids: get_series(db,sid)
    run=ForecastRun(**payload,run_type='joint',region_series_id=region_id,
                    store_series_ids=store_ids,created_by=user.id)
    db.add(run); db.flush()
    return run

def enqueue(run_id): queue.rpush(QUEUE_NAME,str(run_id))

def _observations(db,series_id):
    rows=list(db.scalars(select(Observation).where(Observation.series_id==series_id).order_by(Observation.day)))
    if any((b.day-a.day).days!=1 for a,b in zip(rows,rows[1:])):
        raise ValueError(f'序列 {series_id} 日期不连续，请补齐缺失日再预测')
    return rows

def _aligned_series(db,member_ids):
    """取各序列在共同日期上的连续对齐数据；重叠不足时明确报错并给出处置口径。"""
    observed={}
    for sid in member_ids:
        rows=_observations(db,sid)
        observed[sid]={row.day:row.value for row in rows}
    common=sorted(set.intersection(*(set(values) for values in observed.values())))
    if not common:
        raise ValueError('区域与门店没有任何重叠日期，无法估计同期关联；请先补齐同一日期区间的观测')
    # 共同日期本身也必须逐日连续
    if any((b-a).days!=1 for a,b in zip(common,common[1:])):
        raise ValueError('共同日期区间存在缺口，无法建立逐日联合预测；请补齐重叠区间内的缺失日')
    return common,{sid:[observed[sid][day] for day in common] for sid in member_ids}

def compute(db,run_id):
    run=get_run(db,run_id)
    if run.status=='completed': return
    run.status='running'; db.commit()
    if run.run_type=='joint':
        _compute_joint(db,run)
    else:
        _compute_single(db,run)

def _compute_single(db,run):
    observations=_observations(db,run.series_id)
    result=forecast([x.value for x in observations],run.horizon,run.season)
    db.execute(delete(ForecastPoint).where(ForecastPoint.run_id==run.id))
    for i,point in enumerate(result.pop('points'),1):
        db.add(ForecastPoint(run_id=run.id,series_id=None,day=observations[-1].day+timedelta(days=i),**point))
    run.result=result; run.status='completed'; run.error=None
    db.commit()

def _compute_joint(db,run):
    member_ids=[run.region_series_id]+list(run.store_series_ids or [])
    dates,series=_aligned_series(db,member_ids)
    result=joint_forecast(series,dates,run.region_series_id,list(run.store_series_ids or []),
                          run.horizon,run.season)
    db.execute(delete(ForecastPoint).where(ForecastPoint.run_id==run.id))
    last_day=dates[-1]
    for point in result['points']:
        day=last_day+timedelta(days=point['offset'])
        for sid in member_ids:
            db.add(ForecastPoint(run_id=run.id,series_id=sid,day=day,
                                 predicted=point['reconciled_point'][sid],
                                 lower=point['lower'][sid],upper=point['upper'][sid]))
    # points 已落库，结果 JSON 保留回测与关联诊断但去掉逐日未来点（避免双份存储）
    result.pop('points')
    run.result=result; run.status='completed'; run.error=None
    db.commit()
