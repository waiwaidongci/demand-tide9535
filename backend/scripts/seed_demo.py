"""Idempotent insert-only seed; never overwrites analyst modifications."""
import random,math
from datetime import date,timedelta
from sqlalchemy import select,func
from src.config.database import Base,engine,SessionLocal
from src.models import User,Series,Observation,ForecastRun,Release
from src.utils.security import hash_password
from src.services.run_service import compute

def seed():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for role,name in [('admin','林舟 · 计划负责人'),('analyst','沈雾 · 预测分析师'),('viewer','陈帆 · 配送联络员')]:
            email=role+'@tide.demo'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password_hash=hash_password('Tide2026!')))
        db.commit()
        configs=[('hz-rose','杭州·日配玫瑰','杭州','玫瑰',140),('sh-lily','上海·日配百合','上海','百合',95),('sz-tulip','苏州·日配郁金香','苏州','郁金香',80),('nj-rose','南京·日配玫瑰','南京','玫瑰',110),('nb-daisy','宁波·日配雏菊','宁波','雏菊',65),('wx-lily','无锡·日配百合','无锡','百合',75)]
        for k,(code,name,city,product,base) in enumerate(configs):
            series=db.scalar(select(Series).where(Series.code==code))
            if not series:
                series=Series(code=code,name=name,city=city,product=product,source_file='tide-demand-2026.csv'); db.add(series); db.flush()
            existing=set(db.scalars(select(Observation.day).where(Observation.series_id==series.id)))
            rng=random.Random(42+k)
            for i in range(180):
                day=date(2026,5,16)+timedelta(days=i)
                value=round(max(0,base+.09*i+24*math.sin(2*math.pi*i/7)+rng.gauss(0,7)),2)
                if day not in existing: db.add(Observation(series_id=series.id,day=day,value=value))
        db.commit()
        # 区域-门店层级演示：两个杭州门店共享周季节与同期冲击，区域为门店合计口径
        store_configs=[('hz-store-west','杭州西湖门店·玫瑰',88),('hz-store-east','杭州钱塘门店·玫瑰',62)]
        hrng=random.Random(2026)
        shocks=[16*math.sin(2*math.pi*i/7)+hrng.gauss(0,5) for i in range(180)]
        store_value_sets=[]
        for k,(code,name,base) in enumerate(store_configs):
            series=db.scalar(select(Series).where(Series.code==code))
            if not series:
                series=Series(code=code,name=name,city='杭州',product='玫瑰',source_file='tide-demand-2026.csv'); db.add(series); db.flush()
            existing=set(db.scalars(select(Observation.day).where(Observation.series_id==series.id)))
            rng=random.Random(700+k)
            values=[]
            for i in range(180):
                day=date(2026,5,16)+timedelta(days=i)
                value=round(max(0,base+.05*i+shocks[i]+rng.gauss(0,5)),2)
                values.append(value)
                if day not in existing: db.add(Observation(series_id=series.id,day=day,value=value))
            store_value_sets.append(values)
        region_values=[round(store_value_sets[0][i]+store_value_sets[1][i],2) for i in range(180)]
        region=db.scalar(select(Series).where(Series.code=='hz-region-rose'))
        if not region:
            region=Series(code='hz-region-rose',name='杭州区域·日配玫瑰',city='杭州',product='玫瑰',source_file='tide-demand-2026.csv'); db.add(region); db.flush()
        existing=set(db.scalars(select(Observation.day).where(Observation.series_id==region.id)))
        for i,value in enumerate(region_values):
            day=date(2026,5,16)+timedelta(days=i)
            if day not in existing: db.add(Observation(series_id=region.id,day=day,value=value))
        db.commit()
        user=db.scalar(select(User).where(User.role=='admin'))
        for series in db.scalars(select(Series).order_by(Series.id).limit(2)):
            name='11月周度基线 · '+series.name
            run=db.scalar(select(ForecastRun).where(ForecastRun.name==name))
            if not run:
                run=ForecastRun(name=name,series_id=series.id,horizon=14,season=7,created_by=user.id);db.add(run);db.commit();compute(db,run.id)
                if series.code=='hz-rose': db.add(Release(run_id=run.id,note='例行周度日配参考；节假日需人工复核。',published_by=user.id)); db.commit()
        # 联合预测演示：区域与两个门店在共同日期上协调（演示数据为合成口径）
        joint_name='联合协调 · 杭州区域与门店'
        if not db.scalar(select(ForecastRun).where(ForecastRun.name==joint_name)):
            picked=[db.scalar(select(Series).where(Series.code==code))
                    for code in ('hz-region-rose','hz-store-west','hz-store-east')]
            if all(picked):
                joint=ForecastRun(name=joint_name,run_type='joint',region_series_id=picked[0].id,
                                  store_series_ids=[s.id for s in picked[1:]],horizon=14,season=7,
                                  created_by=user.id)
                db.add(joint); db.commit(); compute(db,joint.id)
        counts={name:db.scalar(select(func.count()).select_from(model)) for name,model in [('users',User),('series',Series),('observations',Observation),('runs',ForecastRun),('releases',Release)]}
        print(counts)
        return counts
if __name__=='__main__': seed()
