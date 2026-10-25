from functools import wraps
from pathlib import Path
from django.utils import timezone


def record_import(func):
    @wraps(func)
    def run(self,*args,**options):
        from .models import DataImportRun, MaxicomRuntime, MaxicomFlowDaily, MaxicomFlowZone
        item=DataImportRun.objects.create(source=Path(options.get('source_archive') or options.get('mdb','')).name,
            flow_only=bool(options.get('flow_only')))
        try:
            result=func(self,*args,**options)
        except Exception as exc:
            DataImportRun.objects.filter(pk=item.pk).update(status='failed',finished_at=timezone.now(),details={'error':str(exc)[:300]})
            raise
        else:
            DataImportRun.objects.filter(pk=item.pk).update(status='success',finished_at=timezone.now(),details={
                'runtime_rows':MaxicomRuntime.objects.count(),'flow_days':MaxicomFlowDaily.objects.count(),
                'flow_zones':MaxicomFlowZone.objects.filter(is_active=True).count()})
            return result
    return run


def status():
    from .models import DataImportRun
    latest=DataImportRun.objects.order_by('-started_at').first()
    success=DataImportRun.objects.filter(status='success').order_by('-finished_at').first()
    seconds=(timezone.now()-success.finished_at).total_seconds() if success and success.finished_at else None
    state='online' if seconds is not None and seconds < 36*3600 else 'offline' if success else 'never_connected'
    if latest and latest.status=='failed':state='offline'
    return {'mode':'backup-import','status':state,'source':success.source if success else '',
        'last_heartbeat':success.finished_at.isoformat() if success and success.finished_at else None,
        'last_sync_display':timezone.localtime(success.finished_at).strftime('%Y-%m-%d %H:%M') if success and success.finished_at else '',
        'seconds_since_heartbeat':int(seconds) if seconds is not None else None,
        'last_sync_counts':success.details if success else {},'agent_version':'',
        'latest_status':latest.status if latest else 'unknown',
        'message':'正在导入备份' if latest and latest.status=='running' else '最近导入失败，请查看同步日志' if latest and latest.status=='failed'
        else '暂无已记录的成功导入，请等待下次同步' if not success else '备份已导入'}
