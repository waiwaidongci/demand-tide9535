from src.services.run_service import create_run,create_joint_run,enqueue
from src.utils.serializers import serialize
from src.utils.audit import record

def _enqueue_safely(run):
    try: enqueue(run.id)
    except Exception:
        run.status='failed'; run.error='任务队列不可用，请重新创建'

def create(db,data,user):
    run=create_run(db,data,user)
    record(db,user,'create_forecast',run.name); db.commit()
    _enqueue_safely(run); db.commit()
    return serialize(run)

def create_joint(db,data,user):
    run=create_joint_run(db,data,user)
    record(db,user,'create_joint_forecast',run.name); db.commit()
    _enqueue_safely(run); db.commit()
    return serialize(run)
