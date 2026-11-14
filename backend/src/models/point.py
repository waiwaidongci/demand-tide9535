from datetime import date
from sqlalchemy import ForeignKey,Date,Float,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from src.config.database import Base
class ForecastPoint(Base):
    __tablename__='forecast_points'
    # 单序列任务 series_id 为空；联合任务每个成员每日一行
    __table_args__=(UniqueConstraint('run_id','day','series_id',name='uq_run_day_series'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    run_id:Mapped[int]=mapped_column(ForeignKey('forecast_runs.id'))
    series_id:Mapped[int|None]=mapped_column(ForeignKey('series.id'),nullable=True)
    day:Mapped[date]=mapped_column(Date)
    predicted:Mapped[float]=mapped_column(Float)
    lower:Mapped[float]=mapped_column(Float)
    upper:Mapped[float]=mapped_column(Float)
