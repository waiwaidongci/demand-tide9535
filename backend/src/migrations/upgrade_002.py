"""002 联合预测结构的幂等 DDL 升级；新库由 create_all 建表，本模块只处理既有库。

仅依赖 SQLAlchemy 通用 API 与 ALTER TABLE，支持演示环境的 MySQL 8 与本地测试用 SQLite。
"""
from sqlalchemy import inspect, text

RUN_COLUMNS = {
    'run_type': "VARCHAR(20) NOT NULL DEFAULT 'single'",
    'region_series_id': 'INT NULL',
    'store_series_ids': 'JSON NULL',
}
POINT_COLUMNS = {'series_id': 'INT NULL'}


def _inspect(db):
    return inspect(db.bind)


def ensure_joint_schema(db):
    dialect = db.bind.dialect.name
    insp = _inspect(db)
    run_cols = {c['name'] for c in insp.get_columns('forecast_runs')}
    for name, ddl in RUN_COLUMNS.items():
        if name not in run_cols:
            db.execute(text(f'ALTER TABLE forecast_runs ADD COLUMN {name} {ddl}'))
    if 'series_id' in run_cols:
        null_ok = next(c for c in insp.get_columns('forecast_runs')
                       if c['name'] == 'series_id')['nullable']
        if not null_ok:
            if dialect == 'mysql':
                db.execute(text('ALTER TABLE forecast_runs MODIFY series_id INT NULL'))
            else:
                db.execute(text('ALTER TABLE forecast_runs ALTER COLUMN series_id DROP NOT NULL'))
    point_cols = {c['name'] for c in insp.get_columns('forecast_points')}
    if 'series_id' not in point_cols:
        db.execute(text('ALTER TABLE forecast_points ADD COLUMN series_id INT NULL'))
    uniques = {uc['name'] for uc in insp.get_unique_constraints('forecast_points')}
    if 'uq_run_day_series' not in uniques:
        if 'uq_run_day' in uniques:
            db.execute(text('DROP INDEX uq_run_day'))
        if dialect == 'mysql':
            db.execute(text('ALTER TABLE forecast_points ADD CONSTRAINT uq_run_day_series '
                            'UNIQUE (run_id, day, series_id)'))
        else:
            db.execute(text('CREATE UNIQUE INDEX uq_run_day_series '
                            'ON forecast_points (run_id, day, series_id)'))
    # 外键：MySQL 显式补约束；SQLite 不支持 ALTER 加外键，新库由模型 create_all 覆盖
    if dialect == 'mysql':
        point_fks = {fk['name'] for fk in insp.get_foreign_keys('forecast_points')}
        if 'fk_point_series' not in point_fks:
            db.execute(text('ALTER TABLE forecast_points ADD CONSTRAINT fk_point_series '
                            'FOREIGN KEY(series_id) REFERENCES series(id)'))
        run_fks = insp.get_foreign_keys('forecast_runs')
        if 'region_series_id' in run_cols and not any(
                'region_series_id' in (fk.get('constrained_columns') or []) for fk in run_fks):
            db.execute(text('ALTER TABLE forecast_runs ADD CONSTRAINT fk_run_region_series '
                            'FOREIGN KEY(region_series_id) REFERENCES series(id)'))
    db.commit()


if __name__ == '__main__':
    from src.config.database import SessionLocal
    with SessionLocal() as db:
        ensure_joint_schema(db)
    print('joint schema ensured')
