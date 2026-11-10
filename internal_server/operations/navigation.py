def pest_modules(manager):
    modules=[
        dict(name='dashboard',label='地图总览',description='地点、边界与现场作业',icon='map',url='/'),
        dict(name='work_reports',label='工单记录',description='作业记录、待跟进与疑难问题',icon='clipboard',url='/work-reports/'),
        dict(name='reports',label='数据报表',description='工作量、工时与地点统计',icon='chart',url='/ops/reports/'),
        dict(name='business_data',label='业务数据',description='植保工作类别与作业层级',icon='activity',url='/ops/business-data/'),
        dict(name='locations',label='区域管理',description='建筑、监测点与共享区域',icon='layers',url='/ops/locations/'),
        dict(name='plans',label='作业计划',description='周期计划、轮转与任务跟进',icon='calendar',url='/ops/plans/'),
    ]
    if manager:modules.append(dict(name='team',label='用户管理',description='团队账号、角色与权限',icon='users',url='/ops/team/'))
    return modules
