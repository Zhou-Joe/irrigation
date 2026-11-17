def pest_modules(manager):
    modules=[
        dict(name='dashboard',label='地图总览',description='地点、边界与现场作业',icon='map',url='/'),
        dict(name='work_reports',label='工单记录',description='作业记录、待跟进与疑难问题',icon='clipboard',url='/work-reports/'),
        dict(name='reports',label='数据报表',description='工作量、工时与地点统计',icon='chart',url='/ops/reports/'),
        dict(name='business_data',label='业务数据',description='植保工作类别与作业层级',icon='activity',url='/ops/business-data/'),
        dict(name='locations',label='区域管理',description='建筑、监测点与共享区域',icon='layers',url='/ops/locations/'),
        dict(name='plans',label='作业计划',description='周期计划、轮转与任务跟进',icon='calendar',url='/ops/plans/'),
    ]
    if manager:modules.append(dict(name='team',label='用户管理',description='用户、审批、通知、班组与邮件报表',icon='users',url='/user-management/'))
    return modules


def landscaping_modules(manager):
    modules = [
        dict(name='dashboard', label='绿化总览', description='区域地图、植物分布与养护待办', icon='map', url='/'),
        dict(name='green_assets', label='树木与绿地', description='树木档案与四类绿地区块', icon='layers', url='/ops/landscaping/assets/'),
        dict(name='green_species', label='植物库', description='植物辨识、科属与特别关注植物', icon='activity', url='/ops/landscaping/species/'),
        dict(name='green_workorders', label='养护工单', description='巡检、养护、整改与复核', icon='clipboard', url='/ops/landscaping/workorders/'),
        dict(name='locations', label='区域管理', description='所属区域与授权共享地点', icon='pin', url='/ops/locations/'),
    ]
    if manager:
        modules.extend([
            dict(name='green_deliveries', label='数据交付', description='供应商交付、验收与整改台账', icon='folder', url='/ops/landscaping/deliveries/'),
            dict(name='user_management', label='用户管理', description='用户、审批、通知、班组与邮件报表', icon='users', url='/user-management/'),
        ])
    return modules
