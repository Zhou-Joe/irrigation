"""LangChain agent that analyzes irrigation data via @tool functions.

The agent is built on demand from AISettings (configured in admin). Each tool
queries the ORM directly — same process, no HTTP hop — so the LLM gets real data
to ground its analysis on.
"""
import csv
import contextvars
import json
import logging
import os
import subprocess
import sys
from datetime import date, timedelta
from functools import lru_cache

from django.conf import settings
from django.utils import timezone
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from core.models import (
    AISettings, WorkReport, DemandRecord, Zone, Patch,
    Worker, WorkCategory, FaultSubType, WeatherData,
)

logger = logging.getLogger(__name__)

# Holds the active conversation thread id while the agent runs. Tools read this
# to resolve per-session code-execution workspaces (a @tool cannot receive the
# thread_id directly from LangChain's runtime).
_CURRENT_THREAD = contextvars.ContextVar('ai_current_thread', default=None)


def set_current_thread(thread_id):
    """Set by the SSE view before invoking the agent, so tools can resolve a workspace."""
    _CURRENT_THREAD.set(thread_id)


# ── Code-execution workspace management ───────────────────────────────────

WORKSPACE_ROOT = os.path.join(settings.MEDIA_ROOT, 'ai_workspaces')


def ensure_workspace(thread_id):
    """Return the per-session workspace dir, creating it and preloading data on first use."""
    ws = os.path.join(WORKSPACE_ROOT, thread_id)
    marker = os.path.join(ws, '.populated')
    if not os.path.isdir(ws):
        os.makedirs(ws, exist_ok=True)
    if not os.path.exists(marker):
        _populate_workspace_data(ws)
        with open(marker, 'w') as f:
            f.write(timezone.now().isoformat())
    return ws


def _populate_workspace_data(ws):
    """Export recent business data to CSVs the generated code can pd.read_csv."""
    today = date.today()
    since = today - timedelta(days=90)
    # WorkReports (last 90 days)
    wr_qs = WorkReport.objects.filter(date__gte=since).select_related(
        'worker', 'location', 'work_category'
    ).order_by('-date')
    with open(os.path.join(ws, 'work_reports.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['日期', '处理人', '位置编号', '位置名称', '班次', '工作类别',
                    '灌溉组工时', '第三方工时', '疑难', '工作内容', '备注'])
        for r in wr_qs:
            w.writerow([
                r.date.isoformat(), str(r.worker) if r.worker else '',
                getattr(r.location, 'code', '') if r.location else '',
                str(r.location) if r.location else '',
                r.shift or '',
                str(r.work_category) if r.work_category else '',
                r.team_hours or 0, r.third_party_hours or 0,
                '是' if r.is_difficult else '否',
                (r.work_content or '')[:200],
                (r.remark or '')[:200],
            ])
    # DemandRecords (last 90 days)
    dr_qs = DemandRecord.objects.filter(date__gte=since).select_related(
        'zone', 'category', 'demand_department'
    ).order_by('-date')
    with open(os.path.join(ws, 'demand_records.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['日期', '区域编号', '区域名称', '类别', '提出部门', '状态', '内容'])
        for d in dr_qs:
            w.writerow([
                d.date.isoformat(),
                getattr(d.zone, 'code', '') if d.zone else (d.zone_text or ''),
                str(d.zone) if d.zone else '',
                str(d.category) if d.category else (d.category_text or ''),
                str(d.demand_department) if d.demand_department else (d.demand_department_text or ''),
                d.get_status_display(),
                (d.content or '')[:200],
            ])
    # Zones (all)
    with open(os.path.join(ws, 'zones.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['编号', '通用名称', '片区', '面积㎡', '优先级', '灌水器类型', '当前状态'])
        for z in Zone.objects.select_related('patch'):
            w.writerow([
                z.code, z.name, str(z.patch) if z.patch else '',
                z.area_sqm or '', z.get_priority_display() if z.priority else '',
                z.sprinkler_type or '', z.current_status or '',
            ])


# ── Tool implementations (call ORM directly) ──────────────────────────────


@tool
def query_work_reports(
    start_date: str = "",
    end_date: str = "",
    limit: int = 20,
) -> str:
    """查询维修工作日报。可按日期范围过滤。返回工单列表（日期、处理人、位置、班次、工作类别、工时、内容摘要）。

    Args:
        start_date: 起始日期 YYYY-MM-DD，留空默认最近7天
        end_date: 结束日期 YYYY-MM-DD，留空默认今天
        limit: 最多返回条数，默认20
    """
    today = date.today()
    end = _parse_date(end_date) or today
    start = _parse_date(start_date) or (end - timedelta(days=7))
    qs = WorkReport.objects.filter(date__gte=start, date__lte=end).select_related(
        'worker', 'location', 'work_category'
    ).order_by('-date', '-id')[:limit]
    rows = []
    for r in qs:
        rows.append({
            '日期': r.date.isoformat(),
            '处理人': str(r.worker),
            '位置': str(r.location),
            '班次': r.shift or '',
            '工作类别': str(r.work_category) if r.work_category else '',
            '灌溉组工时': r.team_hours,
            '第三方工时': r.third_party_hours,
            '疑难': r.is_difficult,
            '工作内容': (r.work_content or r.remark or '')[:120],
        })
    return json.dumps({
        'count': WorkReport.objects.filter(date__gte=start, date__lte=end).count(),
        'returned': len(rows),
        'date_range': [start.isoformat(), end.isoformat()],
        'records': rows,
    }, ensure_ascii=False)


@tool
def query_work_report_stats(
    start_date: str = "",
    end_date: str = "",
) -> str:
    """统计维修工作日报的汇总数据：总工单数、总工时、按班次/工作类别/处理人的分布。用于趋势分析和报告制作。

    Args:
        start_date: 起始日期 YYYY-MM-DD，留空默认最近30天
        end_date: 结束日期 YYYY-MM-DD，留空默认今天
    """
    from django.db.models import Sum, Count, Q

    today = date.today()
    end = _parse_date(end_date) or today
    start = _parse_date(start_date) or (end - timedelta(days=30))
    base = WorkReport.objects.filter(date__gte=start, date__lte=end)
    total = base.count()
    agg = base.aggregate(
        team_hours=Sum('team_hours'),
        third_hours=Sum('third_party_hours'),
        difficult=Count('id', filter=Q(is_difficult=True)),
    )

    # by shift
    shift_dist = {}
    for row in base.values('shift').annotate(c=Count('id')):
        shift_dist[row['shift'] or '未指定'] = row['c']
    # by work category
    cat_dist = {}
    for row in base.values('work_category__name').annotate(c=Count('id')).order_by('-c'):
        name = row['work_category__name'] or '未指定'
        cat_dist[name] = row['c']
    # by worker (top 10)
    worker_dist = []
    for row in base.values('worker__full_name').annotate(
        c=Count('id'), h=Sum('team_hours')
    ).order_by('-c')[:10]:
        worker_dist.append({
            '处理人': row['worker__full_name'] or '未知',
            '工单数': row['c'],
            '工时': row['h'] or 0,
        })
    return json.dumps({
        'date_range': [start.isoformat(), end.isoformat()],
        '总工单数': total,
        '总灌溉组工时': agg['team_hours'] or 0,
        '总第三方工时': agg['third_hours'] or 0,
        '疑难工单数': agg['difficult'] or 0,
        '按班次分布': shift_dist,
        '按工作类别分布': cat_dist,
        '处理人工单Top10': worker_dist,
    }, ensure_ascii=False)


@tool
def query_demand_records(
    start_date: str = "",
    end_date: str = "",
    status: str = "",
    limit: int = 20,
) -> str:
    """查询浇水/灌溉需求记录（其他部门提出的灌溉需求）。可按日期、状态过滤。

    Args:
        start_date: 起始日期 YYYY-MM-DD，留空默认最近7天
        end_date: 结束日期 YYYY-MM-DD，留空默认今天
        status: 状态过滤，可选：submitted/approved/rejected/in_progress/completed/info_needed，留空返回全部
        limit: 最多返回条数
    """
    today = date.today()
    end = _parse_date(end_date) or today
    start = _parse_date(start_date) or (end - timedelta(days=7))
    qs = DemandRecord.objects.filter(date__gte=start, date__lte=end)
    if status:
        qs = qs.filter(status=status)
    qs = qs.select_related('zone', 'category', 'demand_department').order_by('-date', '-id')[:limit]
    rows = []
    for d in qs:
        rows.append({
            '日期': d.date.isoformat(),
            '区域': str(d.zone) if d.zone else (d.zone_text or ''),
            '类别': str(d.category) if d.category else (d.category_text or ''),
            '部门': str(d.demand_department) if d.demand_department else (d.demand_department_text or ''),
            '状态': d.get_status_display(),
            '内容': (d.content or '')[:120],
        })
    return json.dumps({
        'returned': len(rows),
        'date_range': [start.isoformat(), end.isoformat()],
        'records': rows,
    }, ensure_ascii=False)


@tool
def query_zones(zone_code: str = "", limit: int = 50) -> str:
    """查询区域(Zone)信息：编号、通用名称、所属片区、面积、优先级、灌水器类型等。可按编号模糊查找。

    Args:
        zone_code: 区域编号或通用名称，部分匹配即可（如 "1-1" 或 "BOH"）；留空返回汇总
        limit: 最多返回条数
    """
    if zone_code:
        from django.db.models import Q
        qs = Zone.objects.filter(
            Q(code__icontains=zone_code) | Q(name__icontains=zone_code)
        ).select_related('patch')[:limit]
        rows = []
        for z in qs:
            rows.append({
                '编号': z.code,
                '通用名称': z.name,
                '片区': str(z.patch) if z.patch else '',
                '面积㎡': z.area_sqm,
                '优先级': z.get_priority_display() if z.priority else '',
                '灌水器类型': z.sprinkler_type,
                '当前状态': z.current_status,
            })
        return json.dumps({'returned': len(rows), 'zones': rows}, ensure_ascii=False)
    # summary
    total = Zone.objects.count()
    by_priority = {}
    for z in Zone.objects.values('priority'):
        p = z['priority'] or '未指定'
        by_priority[p] = by_priority.get(p, 0) + 1
    return json.dumps({
        '总区域数': total,
        '按优先级分布': by_priority,
        '提示': '请用 zone_code 参数查具体区域',
    }, ensure_ascii=False)


@tool
def query_weather(days: int = 7) -> str:
    """查询最近若干天的天气数据记录。

    Args:
        days: 查询最近多少天，默认7
    """
    end = date.today()
    start = end - timedelta(days=days)
    qs = WeatherData.objects.filter(date__gte=start).order_by('-date')[:days]
    rows = []
    for w in qs:
        rows.append({
            '日期': w.date.isoformat() if w.date else '',
            '天气': getattr(w, 'weather', '') or getattr(w, 'description', '') or '',
            '温度': getattr(w, 'temperature', None),
        })
    return json.dumps({'returned': len(rows), 'weather': rows}, ensure_ascii=False)


@tool
def query_irrigation_overview() -> str:
    """查询灌溉系统总览统计：片区/站点/控制器/流量区域/气象站/事件数量、锁定站点数。用于系统健康度概览。"""
    from core.models import (
        MaxicomController, MaxicomSchedule, MaxicomFlowZone,
        MaxicomWeatherStation, MaxicomWeatherLog, MaxicomEvent,
    )
    return json.dumps({
        '片区数': Patch.objects.count(),
        '控制器数': MaxicomController.objects.count(),
        '站点数': Patch.objects.filter(parent__isnull=False).count(),
        '计划数': MaxicomSchedule.objects.count(),
        '流量区域数': MaxicomFlowZone.objects.count(),
        '气象站数': MaxicomWeatherStation.objects.count(),
        '气象日志数': MaxicomWeatherLog.objects.count(),
        '事件数': MaxicomEvent.objects.count(),
        '锁定站点数': Patch.objects.filter(parent__isnull=False, lockout=True).count(),
    }, ensure_ascii=False)


@tool
def get_today_date() -> str:
    """获取服务器当前日期和时间。当用户问"今天/最近"而你需要确定日期范围时调用。"""
    now = timezone.now()
    return json.dumps({
        'today': now.date().isoformat(),
        'now': now.strftime('%Y-%m-%d %H:%M'),
        'weekday': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][now.weekday()],
    }, ensure_ascii=False)


# ── Helpers ───────────────────────────────────────────────────────────────


def _parse_date(s: str):
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


# ── Code execution tool ───────────────────────────────────────────────────


# Generated code runs in a stripped-down environment. No Django/DB credentials
# leak through — the subprocess only sees a minimal PATH and the preloaded CSVs.
_SANDBOX_ENV = {
    'PATH': '/usr/bin:/bin:/usr/local/bin',
    'LANG': 'en_US.UTF-8',
    'LC_ALL': 'en_US.UTF-8',
    'HOME': '/tmp',
    'MPLBACKEND': 'Agg',  # matplotlib headless, in case it's ever installed
}

# Cap output preview to keep the LLM context small.
_MAX_STDOUT = 2000
_MAX_STDERR = 1000
# Allowed output extensions + size guard.
_ALLOWED_EXTS = {'.xlsx', '.xls', '.csv', '.json', '.txt'}
_MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB


@tool
def run_python_code(code: str, description: str = "") -> str:
    """运行 Python 代码进行数据分析、计算、并生成报表文件。

    工作目录已预置以下 CSV 数据文件，用 pandas 读取：
    - work_reports.csv（最近90天维修工单：日期/处理人/位置/班次/工作类别/工时/内容）
    - demand_records.csv（最近90天浇水需求：日期/区域/类别/部门/状态/内容）
    - zones.csv（全部区域：编号/通用名称/片区/面积/优先级）

    用法规则：
    - 用 `import pandas as pd` 然后 `pd.read_csv('work_reports.csv')` 加载数据
    - 生成文件时用相对路径保存到当前目录，如 df.to_excel('工时统计.xlsx', index=False) 或 df.to_csv('result.csv')
    - 仅允许扩展名：.xlsx .csv .json .txt
    - 可用库：pandas, openpyxl, xlsxwriter, json, datetime, math, statistics, collections
    - 执行超时30秒；禁止访问网络/数据库/其他目录
    - 用 print() 输出中间结果和摘要

    Args:
        code: 完整的 Python 代码（可多行）
        description: 对这段代码目的的简短描述
    """
    thread_id = _CURRENT_THREAD.get()
    if not thread_id:
        return json.dumps({'error': '无法确定会话工作区'}, ensure_ascii=False)
    ws = ensure_workspace(thread_id)

    # Snapshot existing files so we can detect newly-created outputs.
    before = set(os.listdir(ws))

    try:
        result = subprocess.run(
            [sys.executable, '-c', code],
            cwd=ws,
            env=_SANDBOX_ENV,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({'error': '代码执行超时（30秒）'}, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        return json.dumps({'error': f'执行失败: {e}'}, ensure_ascii=False)

    # Collect newly-created files matching allowed extensions.
    files = []
    for name in os.listdir(ws):
        if name in before or name.startswith('.'):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in _ALLOWED_EXTS:
            continue
        path = os.path.join(ws, name)
        if not os.path.isfile(path):
            continue
        size = os.path.getsize(path)
        if size > _MAX_FILE_BYTES:
            continue
        files.append({
            'name': name,
            'size': size,
            'url': f'{settings.MEDIA_URL}ai_workspaces/{thread_id}/{name}',
        })

    return json.dumps({
        'exit_code': result.returncode,
        'stdout': (result.stdout or '')[:_MAX_STDOUT],
        'stderr': (result.stderr or '')[:_MAX_STDERR],
        'files': files,
        'generated_count': len(files),
    }, ensure_ascii=False)


ALL_TOOLS = [
    query_work_reports,
    query_work_report_stats,
    query_demand_records,
    query_zones,
    query_weather,
    query_irrigation_overview,
    get_today_date,
    run_python_code,
]


@lru_cache(maxsize=1)
def _checkpoint_saver():
    """A single in-memory checkpointer shared across agent builds (conversation memory)."""
    return InMemorySaver()


def build_agent():
    """Build a fresh LangChain agent from current AISettings.

    Rebuilt per request so config changes (api_key/model) in admin take effect
    immediately. The in-memory checkpointer is reused so a thread_id keeps
    conversation history within the running process.
    """
    cfg = AISettings.get_settings()
    if not (cfg.enabled and cfg.api_base_url and cfg.api_key and cfg.model_name):
        raise RuntimeError('AI 助手未启用或配置不完整，请在管理后台填写 base_url / api_key / model')

    model = ChatOpenAI(
        base_url=cfg.api_base_url,
        api_key=cfg.api_key,
        model=cfg.model_name,
        temperature=cfg.temperature,
        # Many third-party OpenAI-compatible proxies do not support stream_options;
        # disable streaming usage metadata to avoid 400 errors.
        stream_usage=False,
    )
    agent = create_agent(
        model=model,
        tools=ALL_TOOLS,
        system_prompt=cfg.get_system_prompt(),
        checkpointer=_checkpoint_saver(),
    )
    return agent


def is_configured() -> bool:
    """Quick check whether the agent can be built (used by the view to show a hint)."""
    cfg = AISettings.get_settings()
    return bool(cfg.enabled and cfg.api_base_url and cfg.api_key and cfg.model_name)
