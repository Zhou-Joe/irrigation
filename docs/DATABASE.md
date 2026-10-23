# 灌溉运维系统 · 数据库完全文档

> 本文目标：**只读这一篇，即可了解系统的全部数据结构、字段含义、数据之间的关联、数据流动方式，以及四种取数方法。**
> 基准：2026-10-14 生产库快照（SQLite，`internal_server/db.sqlite3`，约 76MB + 4.9G 媒体文件）。

---

## 1. 系统全景

```
                     ┌────────────────────────────────────────────────┐
   浏览器(Web管理端) ──▶│  internal_server (Django 5.2 + DRF + gunicorn) │◀── 定时任务 cron
   手机App(mobile_app)─▶│  SQLite + media/ 照片 + staticfiles            │    ├ maxicom_nightly (08:30/16:30)
                     └───────────────┬────────────────────────────────┘    ├ email_cron (每小时)
                                     │                                       ├ fetch_weather (每小时:15)
              ssh反向隧道(常驻systemd)│                                       └ pm_dispatch (每日06:00)
                                     ▼
                     ┌────────────────┐        ┌──────────────────────┐
                     │ 阿里云 ECS nginx │──TLS──▶ irrigation.zctestbench.asia
                     └────────────────┘        └──────────────────────┘
   Maxicom中控系统(Win7, 192.168.137.1, SMB) ──每日16:01 zip──▶ 夜间导入
   cloud-relay (Cloudflare Worker + KV) ◀── sync_agent(现场无网中转上传) ── 手机App离线工单
```

- **Web 端**：登录后使用（会话认证），主要页面 `/stats/`(统计)、`/irrigation/`(灌溉)、`/work-reports/`(工单)、`/pm/`(PM管理)、`/inventory/manage/`(库存)、`/projects/`(项目)、`/settings/`(系统设置)、`/admin/`(Django后台)。
- **手机端**：专用 v2 接口 `/mobile/*/v2/`，用工号+`Worker.api_token`(UUID) 认证（`/api/auth/login`）。
- **时区约定**：全系统按 **Asia/Shanghai**（灌溉日窗口 = 前日22:00→当日21:59；PM 调度、邮件 send_hour 都依赖本地日期）。

---

## 2. 存储概况

| 项 | 值 |
|---|---|
| 数据库 | 单文件 SQLite，`internal_server/db.sqlite3` |
| 媒体文件 | `internal_server/media/`（工单照片 `workorder_photos/<工单id>/`、工作汇报照片 `workreport/`、AI 会话 `ai_checkpoints.sqlite3` 独立文件） |
| 静态文件 | `staticfiles/`（`collectstatic` 构建产物，可随时重建，不入库不备份） |
| Django app | 仅一个业务 app：`core`（表名前缀 `core_`） |
| JSON 用法 | 大量 `JSONField` 存几何坐标、照片清单、配置快照——**SQLite 里 JSON 是文本**，SQL 直查可用 `json_extract` |

行数总览（业务表）：Zone 2508 / Patch 3377 / MaxicomRuntime 35.8万 / MaxicomSignalLog 3.4万 / WorkReport 1622 / WorkReportEntry 2859 / GeneratedWorkOrder 1732 / MaintenancePlan 719 / InventoryCategory 397 / Worker 16 / User 24。

---

## 3. 核心关系图

```
Region ──1:N──▶ Patch(CCU) ──1:N──▶ Patch(station-N)   ← Patch 双重角色！
                   │  ▲
                   │  └── MaxicomController/Schedule/FlowZone/Runtime.site
                   │
                   ├──1:N──▶ Satellite(SAT) ──1:N──▶ Zone
                   │            (code "1-1"=CCU号-控制器号)
                   │
Land(24块地)──N:M──┤ Crew(班组) ◀──members── Worker(16人)
                   │    ▲patches(负责CCU) ▲lands(负责地块)
                   │    │
                   │ MaintenancePlan(PM计划) ──N:M──▶ Zone
                   │    │crew(可空,自动匹配)  ▲job_plan
                   │    │                       │
                   │    ▼                       JobPlanTemplate(13种作业)
                   │ GeneratedWorkOrder(派发的工单) ──1:1──▶ WorkReport(完成回填)
                   │                              └─1:1──▶ PMWorkOrder
                   │
                   └── Zone ──N:M──▶ Pipeline / WaterRequest / WorkReport

工单域:  WorkReport ──1:N──▶ WorkReportEntry ──▶ WorkItem(树,MPTT) / Project
         WorkReport ──1:N──▶ WorkReportComment / WorkReportEditLog / photos(JSON)

库存域:  InventoryCategory(树) ──▶ InventoryPriceRecord
         InventoryTransaction ──1:N──▶ InventoryTransactionLine ──▶ InventoryCategory
         PurchaseOrder ──1:N──▶ PurchaseOrderLine ──▶ InventoryCategory

Maxicom: Patch(site=CCU) / Patch(station-N) ◀── MaxicomRuntime(35.8万行,运行时长)
         MaxicomFlowZone ──▶ MaxicomFlowDaily(日流量) / MaxicomSignalLog / MaxicomEvent
```

**编号体系**（读懂数据的钥匙）：
- `Zone.code = "5-1-4"` = **CCU号-控制器号-区域号**（5=CCU5, 1=SAT1, 4=区4）
- `Satellite.code = "5-1"` = CCU号-控制器号；自动从 Zone 代码前缀生成（命令 `generate_satellites`）
- `Patch.code`：`CCU\d+`（25 个中控单元，业务上的"CCU"）或 `station-\d+`（3352 个 Maxicom 站点行，parent→所属 CCU）——**Patch 表同时承载 CCU 和站点两层**，`MaxicomController/Schedule/FlowZone` 的 `site` FK 指向 CCU 层，`MaxicomRuntime` 的 `station` FK 指向 station 层。
- `MaintenancePlan.pm_number`：Maximo 风格 PM 编号（如 `703605MJ1D`：7030=CCU3, 605=job, MJ1=作业级别, D=日频）；中文命名的计划（如 `喷头水检重点区域-5-1-4`）是 zone_group 级，后缀为首个区域代码。

---

## 4. 数据域详解

> 约定：以下每张表列出**业务关键字段**；所有表默认还有 `created_at/updated_at`（不再重复）。`null=True` 表示可空。

### 4.1 组织与人员

| 表 | 行数 | 说明 |
|---|---|---|
| `auth_user` | 24 | Django 账号。1 个 superuser。角色由 profile 决定 |
| `core_worker` | 16 | **现场工人**（App 使用者）。`employee_id` 工号、`full_name`、`department`(FES/FAM/ENT/其他)、`api_token`(UUID,App登录凭据)、1:1 关联可选的 `user` |
| `core_managerprofile` | 4 | 管理人员扩展：`is_super_admin`、`can_approve_registrations`、`can_approve_work_orders` |
| `core_departmentuserprofile` | 0 | 部门用户扩展（预留） |
| `core_registrationrequest` | 3 | App 自助注册申请：`status`(pending/approved/rejected)，审批后生成 User/Worker |
| `core_crew` | 4 | **班组**：组1~组4。`leader`→Worker；M2M `members`(成员)、`lands`(负责地块——**Zone级PM自动指派的依据**)、`patches`(负责CCU——CCU/SAT级PM的指派依据) |

### 4.2 地理资产（系统的骨架）

**Region(1)** 区域 → **Land(24)** 地块（名称如"明日世界""申迪西路""西门BOH"）→ **Patch(3377)** CCU+站点 → **Satellite(149)** SAT控制器 → **Zone(2508)** 灌溉区。

`core_patch` 关键字段：
- `code`（CCU1~CCU25 / station-1~3352）、`parent`(station→CCU)、`region`
- Maxicom 同步字段：`mdb_index`、`site_number`、`controller_number/channel`、`precip_rate`/`flow_rate`(降水/流量速率)、`et_current/default/min/max`(蒸散量)、`crop_coefficient`、`water_pricing`、`rain_shutdown`、`lockout`
- ⚠️ `site_number` 不可靠（站点改过编号，跑坑文档 §5：按控制器**名字前缀**分组，如 SAT 8-x 实际属 mdb site 7）

`core_zone` 关键字段（2508 行，地图核心实体）：
- `code`(CCU-SAT-区)、`name`、`patch`/`satellite`/`land` 三个归属 FK（satellite 100% 填写）
- 边界几何：`boundary_points`(JSON 数组，地图画的多边形)、`dxf_boundary_points`(DXF导入的)、`boundary_source`(manual/dxf，当前全部 manual)、`boundary_color`、`area_sqm`(面积㎡)
- 分级与属性：`priority`(critical 28/high 172/medium 2228/low 77/abolished 3)、`current_status`、`sprinkler_type`、`plant_type`、`irrigation_foreman`(灌溉责任人)、`greenery_zone/foreman`(绿化)、`pest_control_zone/foreman`(病虫害)、`soil_moisture`、`equipment_maintenance_notes`、`remarks`(留言板 JSON) / `confirmed_remarks`
- 地图标注：`label_lat/lng/scale/angle`、`heatmap_excluded`(热力图排除)
- `maxicom_runtime`(JSON)：该区最近运行时长快照（由 `populate_zone_maxicom_runtime` 命令刷新）

其他：`core_pipeline`(1条管线，`line_points`/`source_points` JSON 几何，`pipeline_type` 灌溉/冲洗/厕所/套管/控制/通讯)、`core_pipevalve`(阀门，0行)、`core_landmark`/`core_zonelandmarkassignment`(地标，0行)、`core_plant`(植物台账，0行)、`core_region`(1个区域)。

### 4.3 工单/日报域（生产主数据）

**`core_workreport`(1622 行)** —— 一线工人每日工单：
- `date`（2026-06-12~今）、`weather`、`worker`→执行人、`shift`(早班/白班/夜班)、`work_start/end_time`、`team_size/third_party_count/team_hours/third_party_hours`(本队/三方人数与工时)
- 位置：`location`→Patch、`zone_location`→Zone、M2M `zones`、冗余文本 `zone_names`
- 内容：`work_content`(文本)、`remark`、`ticket_number`(工单号)、`is_pm`(是否PM生成)
- 标记：`is_pending_repair`(待维修)/`is_difficult`(难点)/`is_difficult_resolved`、`followup_action`、`parent_work_report`+`collab_status`(协作/跟进链)
- 确认流：`hours_confirmed`/`materials_confirmed`/`project_confirmed`(三步确认)、`removed_project`
- `photos`：JSON 数组，指向 `media/workorder_photos/<report_id>/*.jpg`

**`core_workitem`(1334 行)** —— 工作项字典树（MPTT：`lft/rght/tree_id/level`）：
- `section` 分类：routine_maint 日常养护388 / irrigation_project 灌溉项目368 / other_project 其他项目368 / warehouse 仓库129 / routine_support 日常支持33 / drainage_project 排水26 / greenhouse_nursery 温室10 / meeting_training 培训8 / repair_emergency 抢修3 / typhoon_emergency 防台1
- `value_type`：count(计数)/status(状态)/toggle(开关)/text(文本)/text_photo(文本+照片)/group(分组节点)——决定日报表单控件
- `code`/`name_zh`/`name_en`、`unit`、`status_options`(JSON)、`is_project_scoped`

**`core_workreportentry`(2859 行)** —— 工单×工作项明细：`work_report` 或 `pm_work_order`（二选一）、`work_item`、`project`、`count`/`status`/`text_value`/`photos`。**统计报表的主要数据源**。

**`core_project`(19 行)** —— 项目台账：`category`(IRRIGATION/DRAINAGE/OTHER)、`subcategory`(FAM/FES/WDI/GREEN)、预算（材料/人工/队费率/三方费率）、`is_completed`。

辅助：`core_workreportcomment`(29)、`core_workreporteditlog`(538,编辑审计)、`core_announcement`+`ack`(公告与已读)、`core_notification`(338,站内通知)。

### 4.4 PM 预防性维护域

链路：**JobPlanTemplate → MaintenancePlan →(每日06:00 cron)→ GeneratedWorkOrder →(完成回填)→ PMWorkOrder/WorkReport**

| 表 | 行数 | 关键字段 |
|---|---|---|
| `core_jobplantemplate` | 13 | `name`(如"喷头水检重点区域")、`asset_level`(**ccu/sat/zone_group** 三级资产，决定计划挂哪) |
| `core_maintenanceplan` | 719 | `pm_number`、`job_plan`、**资产三选一**：`patch`(CCU级)/`satellite`(SAT级)/`zones` M2M(区域组级)；`frequency_value/unit`(周期)、`start_date`(基准日)、`lead_days`(提前28天生成)、`crew`(可空——空则派发时自动匹配) |
| `core_generatedworkorder` | 1732 | `plan`、`scheduled_date`(2026-07-17~10-23)、`deadline`、`crew`、`worker`(接收组长)、`status`(**pending/dispatched/completed/overdue/skipped**；现状: dispatched 459/skipped 1215/overdue 43/completed 15)、1:1 `work_report`/`pm_order`(完成后回填) |
| `core_pmworkorder` | 44 | PM 工单的执行记录（字段同 WorkReport：工时/人数/照片/zones） |
| `core_pmdispatchrun` | 6 | 每次派发的快照：`summary`/`details` JSON（对账用） |
| `core_extensionrequest` | 0 | 工期延长申请及审批 |

**班组自动匹配规则**（`core/pm_utils.py: matching_crew()`，重要！）：
1. `plan.crew` 已填 → 直接用；
2. CCU 级计划 → 找 `patches` 包含该 CCU 的**唯一**活跃班组；
3. SAT 级 → 经 `satellite.patch` 同上；
4. Zone 组级 → 计划全部区域的 `land` 集合，被**唯一**一个班组的 `lands` 完全覆盖才指派；
5. 0 个覆盖→「没有班组覆盖全部区域」；多个→「多个班组…请手动指定」；区域无 Land→「区域缺少Land归属」。
   （可用 `manage.py assign_pm_crews` 批量自动指派，歧义留手动。）

### 4.5 库存与采购域

- `core_inventorycategory`(397)：**配件树**（MPTT，`node_type`: category/part），`current_stock`/`min_stock`(库存与预警线)、`is_main_material`、`unit`
- `core_inventorypricerecord`(9)：历史价格（`is_current` 标当前价）
- `core_inventorytransaction`(152)：出入库单。`operation`(入库/出库)、`entry_subtype`、`worker` 经手人、可关联 `project/zone/work_report/pm_work_order`（消耗追溯到工单）、`consumption_mode`(actual/estimated)、`confirm_status`(pending/confirmed/removed)
- `core_inventorytransactionline`(375)：明细行 → `category` + 数量
- `core_purchaseorder`(16)+`line`(33)+`projectpurchaseorder`(16)：采购单及项目关联
- `core_inventorytransactioneditlog`(66)：审计

### 4.6 Maxicom 中控数据域（导入自 Maxicom2.mdb）

> 来源：Maxicom 中控软件（Win7 电脑 192.168.137.1）每日 16:01 生成 `MC2Backup<MMDDYYYY>.zip`（SMB 共享），夜间脚本经 `import_maxicom_mdb_linux` 导入。**站点改名/编号不可信**，分组按名字前缀（跑坑 §5）。

| 表 | 行数 | 内容 |
|---|---|---|
| `core_maxicomcontroller` | 154 | 控制器台账（`site`→CCU、`controller_type`、`link_number/channel`） |
| `core_maxicomschedule` | 1856 | 灌溉程序（`nominal_et`、`water_budget_factor` 等） |
| `core_maxicomruntime` | **357,631** | **运行时长流水**（2025-08-30~今）：`timestamp`、`site`→CCU、`station`→station-N、`run_time`(分钟)。灌溉时长统计主表 |
| `core_maxicomflowdaily` | 17,379 | **日流量**（2025-08-30~今）：`flow_day`、`zone`→FlowZone、`liters`、`minutes` |
| `core_maxicomflowzone` | 68 | 流量计分区 |
| `core_maxicomsignallog` | 33,764 | 信号日志（2026-06~07：通信/电压类信号，`signal_table/type/value`） |
| `core_maxicomevent` | 101 | 中控事件文本 |
| `core_maxicomweatherstation/log` | 26/0 | 气象站台账/记录 |
| `core_maxicometcheckbook` | 0 | ET 记账本（未启用） |
| `core_maxicomstationflowfactor` | 3496 | 站点流量系数换算 |

### 4.7 其他支撑表

- `core_weatherdata`(156)：逐日气象（2026-05-18~10-20，含预报+ERA5回填），`hourly_data` JSON；来源 Open-Meteo（`fetch_weather` 命令，坐标 31.15,121.67）
- `core_waterrequest`(1)：停水/水量调整申请（App 提交，`request_type`: 停水需求/新苗程序/减小水量/加大水量/其他，状态流 submitted→approved/rejected/info_needed）
- `core_syncagentheartbeat`(1)：sync_agent 心跳（`last_sync_counts` JSON）
- `core_emailreportconfig`(2)：邮件报表订阅（`report_type`: work_reports/irrigation/projects/inventory_catalog/inventory_txn/purchase_orders/zones；`frequency` daily/weekly/monthly + `send_hour`；现行 1 条"每日推送"每日 09:00）
- `core_emailsmtpsetting`(1)：SMTP（QQ 邮箱 465+SSL；后台「用户管理→邮件报表」维护）
- `core_aisettings`(1)：AI 助手（OpenAI 兼容 `api_base_url/api_key/model_name`，当前 DeepSeek）
- `core_sitecalibration`(3)：DXF 图纸标定（点对标定 `points`/`check_points`，`drawing_token` 对应图纸）
- `core_mapstylesettings`(1)：地图样式 JSON
- `core_equipmentcatalog`/`core_zoneequipment`(0/0)：设备台账（预留）
- Django 内置：`django_session`(495)、`django_admin_log`(199)、`auth_*`

---

## 5. 数据链路（数据怎么流动）

1. **Maxicom 夜间导入**（`maxicom_nightly.sh` 08:30/16:30 cron）：
   `smbclient` 连 `192.168.137.1` 共享 → 取最新 `MC2Backup*.zip` → `unzip -P`(密码在 .env.production) 出 `Maxicom2.mdb` → `import_maxicom_mdb_linux` 导入 Controller/Schedule/Runtime/FlowDaily/SignalLog → 幂等去重 → 清理临时。**导入有滞后**（zip 16:01 生成，最迟 16:30 才入库），对账先想滞后。
2. **PM 派发**（`pm_dispatch_cron.sh` 每日 06:00）：
   `mark_pm_overdue`(过期标记) → `generate_pm_workorders`(按频率+lead_days 生成 GWO，自动匹配班组，规则见 §4.4) → 组长在 App「待办」看到工单 → 完成→回填 `PMWorkOrder/WorkReport`（工时/照片/工作项）。
3. **邮件报表**（`email_cron.sh` 每小时整点）：读 `EmailReportConfig`，到 `send_hour` 且数据新鲜度达标（不新鲜会先补跑 Maxicom 导入）→ `core/excel_exports` 生成 xlsx 附件 → SMTP 发送。
4. **手机 App**：在线直连 `/mobile/*/v2/`（工号+token）；**弱网离线**时工单走 `cloud-relay`（Cloudflare Worker+KV）：App POST `/api/upload` → KV → `sync_agent`(现场电脑) 轮询 `/api/pending-uploads` 拉回 → `sync_relay` 命令入库 → `/api/mark-processed`。
5. **天气**：每小时 :15 `fetch_weather`（Open-Meteo，含 7 天预报 + ERA5 回填）→ `WeatherData`。
6. **AI 助手**：`/api/ai/chat` → `ai_agent.py`(LangChain/LangGraph) → 按 `AISettings` 调 OpenAI 兼容接口；会话记忆存 `media/ai_checkpoints.sqlite3`。

---

## 6. 如何取数（四种方式）

### 6.1 REST API（DRF，前缀 `/api/`）
只读 ViewSet（支持 `.json` 后缀、DRF 过滤按代码实现）：
`/api/zones/` `/api/plants/` `/api/workers/` `/api/water-requests/` `/api/equipment-catalog/` `/api/zone-equipment/` `/api/pipelines/` `/api/patches/` `/api/regions/` `/api/locations/`(=Land) `/api/work-reports/`(含 `upload-photos`/`remove-photo` action)。

业务 JSON 接口（会话登录后）：
`/api/zone-geo/` `/api/zones-payload/`(地图全量) `/api/pipelines-payload/` `/api/today-weather/` `/api/irrigation/zone-heatmap/` `/api/stats/zone-heatmap/` `/api/maxicom-dashboard`(中控总览) `/api/sync/status` `/api/ai/status` `/api/report-exports/<type>/` `/api/custom-report`。

App 专用：`/api/auth/login`(工号+token→会话) `/mobile/workorder/v2/` `/mobile/water-request/v2/` `/mobile/inventory/v2/`。

示例：
```bash
curl -b cookies.txt http://SERVER/api/zones/?format=json        # 先 /login/ 拿会话
curl -H "Authorization: Token <api_token>" .../mobile/workorder/v2/
```

### 6.2 管理命令（`internal_server/` 下执行，先 `set -a; . ../.env.production; set +a`）
| 命令 | 用途 |
|---|---|
| `fetch_weather` | 拉天气 |
| `generate_pm_workorders` / `mark_pm_overdue` / `reset_pm_overdue` / `level_pm_schedule` | PM 生成/过期 |
| `assign_pm_crews [--dry-run]` | 批量自动指派班组 |
| `send_report_email [--dry-run] [--config-id N]` | 手动/补发邮件报表 |
| `import_maxicom_mdb_linux` / `import_maxicom` / `populate_zone_maxicom_runtime` | Maxicom 导入/刷新 Zone 运行时长 |
| `import_zones` / `generate_satellites` / `import_pm_plans` / `seed_*` | 初始化/导入工具 |
| `backfill_thumbnails` / `merge_inventory_from_md` / `parse_maintenance_notes` | 数据修复工具 |
| `sync_relay` | 云端中转工单落地 |

### 6.3 Django shell（推荐 exploratory）
```bash
cd ~/irrigation/internal_server && set -a && . ../.env.production && set +a
../.venv/bin/python manage.py shell
>>> from core.models import Zone, MaxicomRuntime
>>> Zone.objects.filter(priority='critical').count()
>>> from core.pm_utils import plan_zones, matching_crew   # 复用业务逻辑
```

### 6.4 直连 SQL（只读！生产写入一律走 ORM）
```bash
sqlite3 file:db.sqlite3?mode=ro "SELECT substr(timestamp,1,8) d, sum(run_time)
  FROM core_maxicomruntime WHERE site_id=(SELECT id FROM core_patch WHERE code='CCU5')
  GROUP BY d ORDER BY d DESC LIMIT 7;"
# 无 sqlite3 CLI 时在线安全备份：
python -c "import sqlite3; s=sqlite3.connect('db.sqlite3'); d=sqlite3.connect('backup.sqlite3'); s.backup(d)"
```
⚠️ JSON 字段直查：`json_extract(photos,'$[0]')`；时间戳 `timestamp` 为 `YYYYMMDDHHMMSS` 字符串。

---

## 7. 运维要点（必读）

1. **备份顺序**：动库前先备份（§6.4 在线备份命令，不停服保一致）；媒体目录 4.9G 随库一起备。
2. **时区**：必须 Asia/Shanghai，灌溉日窗口（前日22:00→当日21:59）与 PM/邮件调度全依赖本地日期。
3. **Maxicom 数据特性**：SiteNumber 不可信按名字前缀分组；运行时长 = XA_LOG 与 XA_RuntimeProject **择优合并不是相加**；STATN_CF 取 `DateClose` 为空且 `DateOpen` 最新；流量计停报是传感器问题不是导入问题。
4. **PM 班组匹配**：计划级 `crew` 优先；Zone 级靠班组 `lands` 覆盖、CCU/SAT 级靠班组 `patches`；歧义即报错留手动——这是设计行为（避免部分覆盖的错派）。
5. **缓存**：`CACHES` 为 FileBasedCache(`/tmp/django_cache`、`/tmp/django_dxf_cache`)，跨 worker 共享；改代码后 `systemctl restart horticulture`（或 `kill -HUP` gunicorn master）。
6. **QQ SMTP 风控**：换网络出口 IP 后登录被断（"Connection unexpectedly closed"）→ 本机浏览器登一次网页版 QQ 邮箱解除；配置务必 465+SSL。
7. **部署结构**：gunicorn(4 workers, :8000, systemd `horticulture`) ← ssh隧道(systemd `domain-tunnel`) ← 阿里云 nginx(TLS)。cron 四件套见 §5。

---

*生成：2026-10-14，基于 Django 模型自省 + 生产库统计。模型有变更时以 `manage.py shell` 里 `apps.get_models()` 的自省结果为准。*
