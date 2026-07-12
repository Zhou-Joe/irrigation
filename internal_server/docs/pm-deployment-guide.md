# PM 功能生产部署指南

> Preventive Maintenance（预防性维护）自动派发系统的上线步骤。
> 适用于从开发机迁移到生产机器（`/home/projects/irrigation`）。

---

## 前置条件

| 项目 | 要求 |
|---|---|
| Python 虚拟环境 | `/home/projects/irrigation/.venv` |
| Django 项目目录 | `/home/projects/irrigation/internal_server` |
| 环境变量文件 | `/home/projects/irrigation/.env.production`（含 `SECRET_KEY`、`MAXICOM_*` 等） |
| `python-dateutil` | 已安装（`pip install python-dateutil`，rrule 日期计算依赖） |
| `openpyxl` | 已安装（Excel 导入依赖） |
| 时区 | `config/settings.py` 中 `TIME_ZONE = 'Asia/Shanghai'` + `USE_TZ = True` |

---

## 一、代码部署

```bash
cd /home/projects/irrigation/internal_server
git pull origin main
pip install -r requirements.txt   # 如有新增依赖
python manage.py collectstatic --noinput
```

## 二、数据库迁移

迁移链：`0091` → `0092` → `0093` → `0094` → `0095` → `0096`

```bash
cd /home/projects/irrigation/internal_server
source /home/projects/irrigation/.env.production && set -a && . /home/projects/irrigation/.env.production && set +a
python manage.py migrate
```

### ⚠️ 关键：迁移 0094 依赖 seed_work_items

迁移 `0094_pm_work_item_leaf.py` 会在 WorkItem 树中创建 `code='1.2.pm'` 的叶子节点（PM 作业计划），但它依赖父节点 `code='1.2'`（维保定期检查）已存在。

**如果生产库还没有跑过 `seed_work_items`，`1.2` 父节点不存在，0094 会静默跳过**（不报错但不创建叶子）。这会导致 PM 工单打开时无法预填工作类别。

检查方法：
```bash
python manage.py shell -c "
from core.models import WorkItem
p = WorkItem.objects.filter(code='1.2').first()
print('1.2 parent:', p.name_zh if p else 'MISSING')
leaf = WorkItem.objects.filter(code='1.2.pm').first()
print('1.2.pm leaf:', leaf.name_zh if leaf else 'MISSING')
"
```

如果 `1.2` MISSING：
```bash
python manage.py seed_work_items
python manage.py migrate core 0094
# 重新检查
python manage.py shell -c "from core.models import WorkItem; print(WorkItem.objects.filter(code='1.2.pm').first())"
```

如果 `1.2` 存在但 `1.2.pm` MISSING（0094 已跑但被跳过）：
```bash
python manage.py shell -c "
from core.models import WorkItem
parent = WorkItem.objects.get(code='1.2')
leaf, created = WorkItem.objects.get_or_create(
    code='1.2.pm',
    defaults={
        'parent': parent, 'name_zh': 'PM作业计划', 'name_en': 'PM Job Plan',
        'order': 999, 'level': parent.level + 1, 'section': 'routine_maint',
        'value_type': 'text', 'is_project_scoped': False, 'active': True,
    })
print('Created' if created else 'Already exists', leaf)
"
```

## 三、导入 PM 数据

### 3.1 放置 Excel 文件

将 Maximo PM 列表 Excel 放到项目上级目录：

```bash
# 默认路径：<repo_parent>/PM list 260711-架构.xlsx
cp "PM list 260711-架构.xlsx" /home/projects/irrigation/

# 或用 --file 指定任意路径
```

### 3.2 导入 JobPlan + MaintenancePlan

```bash
python manage.py import_pm_plans
# 或指定文件路径：
python manage.py import_pm_plans --file "/path/to/PM list XXXXX.xlsx"
```

导入内容：
- **13 个 Excel sheet** → 对应的 `JobPlanTemplate`（作业计划模板）
- 每行 → 一个 `MaintenancePlan`（PM 维护计划）
- DRAFT sheet（CCU22、控制器138）→ `active=False`（不参与派发）
- 3 种资产解析模式：`zone_col`（Zone 组）、`desc_sat`（SAT 描述提取）、`asset_ccu`（CCU 资产号）

验证导入：
```bash
python manage.py shell -c "
from core.models import JobPlanTemplate, MaintenancePlan
print('JobPlans:', JobPlanTemplate.objects.count())
print('PM Plans:', MaintenancePlan.objects.count())
print('Active PM Plans:', MaintenancePlan.objects.filter(active=True).count())
"
```

### 3.3 分配班组到 Land（可选，推荐）

班组的负责区域通过 `Crew.lands`（M2M）定义。在生产环境中先创建班组并分配 Land：

> 班组可以暂时不 seed，手动在 `/user-management/?tab=crews` 创建即可。

### 3.4 自动匹配 PM → 班组

```bash
# 预览（不写入）
python manage.py assign_pm_crews --dry-run

# 执行
python manage.py assign_pm_crews
```

匹配逻辑：PM 关联的 Zone → `zone.land` → `Crew.lands`。如果只有一个班组覆盖所有 Land，自动分配；多个班组重叠时取第一个。

验证：
```bash
python manage.py shell -c "
from core.models import MaintenancePlan
total = MaintenancePlan.objects.filter(active=True).count()
no_crew = MaintenancePlan.objects.filter(active=True, crew__isnull=True).count()
print(f'Active: {total}, No crew: {no_crew}')
"
```

## 四、首次派发

```bash
# 预览（不创建任何数据）
python manage.py mark_pm_overdue --dry-run
python manage.py generate_pm_workorders --dry-run

# 执行
python manage.py mark_pm_overdue
python manage.py generate_pm_workorders
```

验证：
```bash
python manage.py shell -c "
from core.models import GeneratedWorkOrder
from django.db.models import Count
print('Total GWOs:', GeneratedWorkOrder.objects.count())
for row in GeneratedWorkOrder.objects.values('status').annotate(c=Count('id')):
    print(f'  {row[\"status\"]}: {row[\"c\"]}')
no_crew = GeneratedWorkOrder.objects.filter(crew__isnull=True).count()
print('GWOs without crew:', no_crew)
"
```

如果有 `GWOs without crew > 0`，重新跑 `assign_pm_crews` 然后再跑 `generate_pm_workorders`（dispatch 引擎会自动补全 crew）。

## 五、安装定时任务

### 5.1 Crontab 配置

```bash
# 编辑 crontab
crontab -e
```

添加以下行（每天早上 6:00 上海时间执行，在 8 点班次之前）：

```cron
# PM 每日派发：先标记逾期，再生成新工单
0 6 * * * /home/projects/irrigation/internal_server/pm_dispatch_cron.sh

# 天气数据抓取（已有，确认存在）
0 7 * * * /home/projects/irrigation/internal_server/fetch_weather_cron.sh
```

### 5.2 确认 cron 脚本

`pm_dispatch_cron.sh` 已经配置好生产路径，内容：

```bash
#!/bin/bash
# Runs: mark_pm_overdue → generate_pm_workorders
# Logs to: /var/log/pm_dispatch.log
PROJECT="/home/projects/irrigation"
PY="$PROJECT/.venv/bin/python"
MANAGE="$PROJECT/internal_server/manage.py"
ENV_FILE="$PROJECT/.env.production"
LOG="/var/log/pm_dispatch.log"

# ... sources .env.production, runs both commands ...
```

确认：
```bash
# 脚本可执行
chmod +x /home/projects/irrigation/internal_server/pm_dispatch_cron.sh

# 日志文件可写
touch /var/log/pm_dispatch.log
chmod 644 /var/log/pm_dispatch.log

# 手动测试一次
/home/projects/irrigation/internal_server/pm_dispatch_cron.sh
tail -5 /var/log/pm_dispatch.log
```

### 5.3 时区确认

确保服务器时区为 `Asia/Shanghai`：
```bash
timedatectl | grep "Time zone"
# 如不是 Asia/Shanghai：
# sudo timedctl set-timezone Asia/Shanghai
```

## 六、功能验证清单

部署完成后，逐项验证：

### 6.1 后端验证
```bash
python manage.py check                          # 0 issues
python manage.py generate_pm_workorders --dry-run  # 正常输出
python manage.py mark_pm_overdue --dry-run        # 正常输出
```

### 6.2 前端验证（浏览器）

| 页面 | 验证内容 |
|---|---|
| `/pm/?tab=jobplans` | JobPlan 模板列表，13 个 |
| `/pm/?tab=plans` | PM 维护计划，按 JobPlan 分子 tab |
| `/pm/?tab=assets` | 资产关联视图，能加载出来 |
| `/pm/?tab=completion` | 完成率概览 + 逾期列表 + 延期审批 |
| `/work-reports/?tab=pm` | PM 工单 tab，角标显示真实总数，"去完成"按钮可跳转 |
| 首页通知铃铛 | 角标包含 PM 任务数，点击展开有 PM 任务列表 |

### 6.3 一线工人验证

用一线工人账号登录（如 `GONGX018`）：
- [ ] 首页通知铃铛角标有数字
- [ ] 点击铃铛展开 → 有「今日PM任务」列表
- [ ] 点击「填写」→ 打开工单 modal，工作类别预填为「常规维护 › 维保定期检查」
- [ ] 工单 modal 底部有「申请延期」区域
- [ ] `/work-reports/?tab=pm` 能看到自己班组的 PM 工单

### 6.4 经理验证

用经理账号登录：
- [ ] `/pm/?tab=completion` 完成率数据正确
- [ ] 审批延期申请能正常批准/拒绝
- [ ] 批准后 plan.start_date 更新
- [ ] `/work-reports/?tab=pm` 能看到所有班组的工单，含班组列

---

## 附：PM 系统架构

```
JobPlanTemplate (作业计划模板)
  └─ MaintenancePlan (PM 维护计划, 含频率/资产/班组)
       └─ GeneratedWorkOrder (派发工单, status: dispatched→overdue→completed)
            └─ WorkReport (一线工单, ticket_number: PM-{gwo_id})

ExtensionRequest (延期申请) → 经理审批 → plan.start_date 更新

Crew (班组)
  ├─ members (M2M Worker)
  ├─ leader (FK Worker)
  └─ lands (M2M Land) → 匹配 PM 的 zone.land

每日 cron:
  mark_pm_overdue → dispatched 中过期的标 overdue
  generate_pm_workorders → 从 plan.start_date + rrule 算到期日，生成 GWO + WorkReport
```

## 附：管理命令速查

| 命令 | 用途 | 频率 |
|---|---|---|
| `import_pm_plans` | 从 Excel 导入 JobPlan + PM 计划 | 一次性（数据更新时重跑） |
| `assign_pm_crews` | 自动匹配 PM → 班组 | 按需（新增 PM 或班组后） |
| `mark_pm_overdue` | 标记逾期工单 | 每日（cron 自动） |
| `generate_pm_workorders` | 生成到期工单 | 每日（cron 自动） |
| `seed_work_items` | WorkItem 树种子 | 一次性（0094 前必须跑过） |

## 附：回滚

如果需要回退 PM 功能：

```bash
# 回滚迁移
python manage.py migrate core 0090

# 清理 PM 数据（可选）
python manage.py shell -c "
from core.models import *
GeneratedWorkOrder.objects.all().delete()
ExtensionRequest.objects.all().delete()
MaintenancePlan.objects.all().delete()
JobPlanTemplate.objects.all().delete()
WorkItem.objects.filter(code='1.2.pm').delete()
print('PM data cleared')
"

# 移除 crontab 条目
crontab -e  # 删除 pm_dispatch_cron.sh 行
```
