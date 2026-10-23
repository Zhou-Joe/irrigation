"""Installable field app shell. Business pages keep their existing permissions."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .role_utils import is_admin


def navigation(request):
    if not request.user.is_authenticated:
        return {}
    # The same destinations as the site's navigation, including manager tools.
    modules = [
        ('dashboard', '区域地图', '定位、区域详情与现场作业', 'map'),
        ('work_reports', '维修日志', '工单、PM任务与维修跟进', 'clipboard'),
        ('water_requests', '用水需求', '浇水申请与协调进度', 'drop'),
        ('inventory_management', '库存管理', '入库、出库、借用与归还', 'box'),
        ('stats_dashboard', '数据报表', '工作统计、分析与导出', 'chart'),
        ('irrigation_dashboard', '灌溉数据', '用水分析与区域热力图', 'activity'),
        ('settings', '区域管理', '区域、设备与地图配置', 'layers'),
    ]
    if is_admin(request.user):
        modules += [
            ('pm_management', '作业计划', 'Job Plan、PM轮转与派工', 'calendar'),
            ('project_management', '项目管理', '项目、预算与采购记录', 'folder'),
            ('user_management', '用户管理', '账号、班组与注册审批', 'users'),
        ]
    modules.append(('profile', '我的账号', '个人资料与账号设置', 'user'))
    return {'pwa_modules': [dict(name=name, label=label, description=desc,
                                 icon=icon, url=reverse('core:' + name))
                            for name, label, desc, icon in modules]}


@require_GET
@never_cache
@login_required(login_url='core:login')
def app_home(request):
    from .views import _pm_gwo_queryset, _serialize_pm_tasks
    tasks = _pm_gwo_queryset(request.user, is_admin(request.user)).order_by('deadline', 'scheduled_date', 'id')
    today = timezone.localdate()
    return render(request, 'core/app_home.html', {
        'app_today': today,
        'app_weekday': '星期' + '一二三四五六日'[today.weekday()],
        'app_task_count': tasks.count(),
        'app_tasks': _serialize_pm_tasks(list(tasks[:4]), is_admin(request.user)),
    })


@require_GET
def manifest(request):
    from django.templatetags.static import static
    response = JsonResponse({
        'id': '/app/', 'name': '灌溉管理 · 现场工作台', 'short_name': '灌溉管理',
        'description': '现场工单、PM任务、区域地图、用水需求与库存管理。',
        'lang': 'zh-CN', 'start_url': '/app/', 'scope': '/', 'display': 'standalone',
        'background_color': '#F5F0E8', 'theme_color': '#1B4332',
        'categories': ['productivity', 'utilities'],
        'icons': [
            {'src': static('pwa/icon-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('pwa/icon-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('pwa/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
        'shortcuts': [
            {'name': '新建工单', 'url': '/?action=workorder'},
            {'name': 'PM任务', 'url': '/work-reports/?tab=pm'},
            {'name': '区域地图', 'url': '/'},
        ],
    }, json_dumps_params={'ensure_ascii': False}, content_type='application/manifest+json')
    response['Cache-Control'] = 'public, max-age=3600'
    return response


@require_GET
def service_worker(request):
    from django.conf import settings
    response = HttpResponse(render_to_string('core/service-worker.js', {'STATIC_URL': settings.STATIC_URL}), content_type='text/javascript')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Service-Worker-Allowed'] = '/'
    return response


@require_GET
def offline(request):
    # Deliberately no user context: this is the only HTML stored by the worker.
    response = HttpResponse(render_to_string('core/offline.html'))
    response['Cache-Control'] = 'public, max-age=0, must-revalidate'
    return response
