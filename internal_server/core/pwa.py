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
    if getattr(request, 'operations_shell', False):
        from operations.map_views import is_pest
        if is_pest(request):
            from operations.access import active_membership
            member=active_membership(request)
            from operations.navigation import pest_modules
            modules=pest_modules(request.user.is_superuser or member.role=='manager')
            modules.append(dict(name='pest_profile',label='我的账号',description='个人资料与密码',icon='user',url='/ops/profile/'))
            return {'pwa_modules':modules}
        from operations.access import has_irrigation_access
        if not has_irrigation_access(request.user):return {}
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
    from .role_utils import is_dept_user
    if is_dept_user(request.user):
        modules = [m for m in modules if m[0] in ('dashboard', 'water_requests')]
    modules.append(('profile', '我的账号', '个人资料与账号设置', 'user'))
    return {'pwa_modules': [dict(name=name, label=label, description=desc,
                                 icon=icon, url=reverse('core:' + name))
                            for name, label, desc, icon in modules]}


@require_GET
@never_cache
@login_required(login_url='core:login')
def app_home(request):
    from .views import _pm_gwo_queryset, _serialize_pm_tasks
    manager_view=is_admin(request.user)
    tasks = _pm_gwo_queryset(request.user, manager_view).order_by('deadline', 'scheduled_date', 'id')
    today = timezone.localdate()
    return render(request, 'core/app_home.html', {
        'app_today': today,
        'app_weekday': '星期' + '一二三四五六日'[today.weekday()],
        'app_task_count': tasks.count(),
        'app_tasks': _serialize_pm_tasks(list(tasks[:4]), manager_view),
    })


@require_GET
def manifest(request):
    from django.templatetags.static import static
    from django.conf import settings
    multi = settings.MULTI_TEAM_ENABLED
    response = JsonResponse({
        'id': '/app/', 'name': 'FOS · 现场作业' if multi else '灌溉管理 · 现场工作台',
        'short_name': 'FOS' if multi else '灌溉管理',
        'description': '团队地图、现场工单与作业记录。' if multi else '现场工单、PM任务、区域地图、用水需求与库存管理。',
        'lang': 'zh-CN', 'start_url': '/' if multi else '/app/', 'scope': '/', 'display': 'standalone',
        'background_color': '#F5F7F3', 'theme_color': '#1B4332',
        'categories': ['productivity', 'utilities'],
        'icons': [
            {'src': static('pwa/icon-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('pwa/icon-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('pwa/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
        'shortcuts': ([{'name':'区域地图','url':'/'}, {'name':'工单记录','url':'/work-reports/'}] if multi else [
            {'name': '新建工单', 'url': '/?action=workorder'},
            {'name': 'PM任务', 'url': '/work-reports/?tab=pm'},
            {'name': '区域地图', 'url': '/'},
        ]),
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
