# 002 · 区域-门店联合预测结构

单序列任务（`run_type='single'`）口径与旧数据完全兼容；联合任务为新增字段，旧行升级后自动按单序列处理。

## forecast_runs（新增可空列）

- `series_id` 改为可空：单序列任务保留原值；联合任务置空。
- 新增 `run_type VARCHAR(20) NOT NULL DEFAULT 'single'`：`single` / `joint`。
- 新增 `region_series_id INT NULL`，外键 `series.id`。
- 新增 `store_series_ids JSON NULL`：门店序列 id 有序列表。

## forecast_points（唯一约束调整）

- 新增可空列 `series_id INT NULL`，外键 `series.id`。单序列任务旧行与新行均为 NULL；联合任务每成员每日一行。
- 删除旧唯一约束 `uq_run_day`，新增 `uq_run_day_series (run_id, day, series_id)`。
  MySQL 中 NULL 不参与唯一性比较，单序列行 `series_id` 为 NULL 时 `(run_id,day)` 仍保持业务唯一。

## 升级方式

启动时 `src/migrations/upgrade_002.py:ensure_joint_schema` 幂等执行上述 DDL；
新库由 `Base.metadata.create_all` 直接按最新模型建表，升级逻辑检测到结构已存在即跳过。
"""
