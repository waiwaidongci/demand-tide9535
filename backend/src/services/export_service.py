import io,csv
from fastapi import HTTPException
from .run_service import detail

def _writer():
    stream=io.StringIO(); stream.write('﻿')
    return stream,csv.writer(stream)

def export_csv(db,run_id):
    run=detail(db,run_id)
    if run['status']!='completed': raise HTTPException(409,'预测尚未完成')
    if run['run_type']=='joint':
        return _joint_future_csv(run)
    return _single_csv(run)

def _single_csv(run):
    stream,writer=_writer()
    writer.writerow(['序列','日期','点预测','经验下界','经验上界','模型','口径说明'])
    for p in run['points']:
        writer.writerow([run['series']['name'],p['day'],p['predicted'],p['lower'],p['upper'],run['result']['selected']['model'],run['result']['interval_note']])
    return stream.getvalue()

def _joint_future_csv(run):
    region_id=run['region_series_id']; store_ids=run['store_series_ids']
    names={int(k):v['name'] for k,v in run['series_map'].items()}
    stream,writer=_writer()
    header=['日期','层级','序列ID','序列名称','点预测','联合抽样下界(10%)','联合抽样上界(90%)','门店合计','区域点预测','合计差','口径说明']
    writer.writerow(header)
    by_day={}
    for p in run['points']:
        by_day.setdefault(p['day'],{})[p['series_id']]=p
    note=run['result'].get('interval_note','')
    for day in sorted(by_day):
        rows=by_day[day]
        region=rows[region_id]
        store_sum=round(sum(rows[s]['predicted'] for s in store_ids),2)
        writer.writerow([day,'区域',region_id,names[region_id],region['predicted'],region['lower'],region['upper'],store_sum,region['predicted'],round(region['predicted']-store_sum,2),note])
        for sid in store_ids:
            p=rows[sid]
            writer.writerow([day,'门店',sid,names[sid],p['predicted'],p['lower'],p['upper'],'','','',note])
    return stream.getvalue()

def export_backtest_csv(db,run_id):
    run=detail(db,run_id)
    if run['status']!='completed': raise HTTPException(409,'预测尚未完成')
    if run['run_type']!='joint': raise HTTPException(409,'仅联合预测提供分层回测逐日导出')
    result=run['result']
    region_id=run['region_series_id']; store_ids=run['store_series_ids']
    names={int(k):v['name'] for k,v in run['series_map'].items()}
    stream,writer=_writer()
    writer.writerow(['回测日期','层级','序列ID','序列名称','实际值','校准前点预测','校准前下界','校准前上界','协调后点预测','协调后下界','协调后上界','口径'])
    for row in result['backtest']['rows']:
        for sid in [region_id]+store_ids:
            layer='区域' if sid==region_id else '门店'
            writer.writerow([row['day'],layer,sid,names[sid],row['actual'][sid],
                             row['base_point'][sid],row['base_lower'][sid],row['base_upper'][sid],
                             row['reconciled_point'][sid],row['reconciled_lower'][sid],row['reconciled_upper'][sid],
                             '校准前为各序列独立经验区间；协调后来自同一次联合抽样并强制合计一致'])
        base_total=round(sum(row['base_point'][s] for s in store_ids),2)
        recon_total=round(sum(row['reconciled_point'][s] for s in store_ids),2)
        writer.writerow([row['day'],'门店合计','-','门店逐日合计',row['actual'][region_id],
                         base_total,'不可加(独立区间)','不可加(独立区间)',recon_total,
                         row['reconciled_lower'][region_id],row['reconciled_upper'][region_id],
                         '独立区间相加会误导备货，故校准前聚合层不提供区间'])
    return stream.getvalue()
