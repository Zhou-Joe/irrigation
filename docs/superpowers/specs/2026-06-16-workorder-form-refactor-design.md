# 工单表单重构设计文档（现场作业记录 · 结构化层级版）

---

## 1. 项目概述

### 1.1 业务背景

本系统服务于**上海迪士尼度假区（SHDR）灌溉维修团队**的现场作业记录管理。当前 `WorkReport`（维修工作日报 / 工单）的「工作内容」采用**两级**故障分类模型（`FaultCategory → FaultSubType`，明细 `WorkReportFault`）。甲方（客户）现要求按一份**结构化、多层级**的现场作业记录格式重构工单表单，覆盖灌溉现场作业的全部内容。

### 1.2 数据来源（唯一主源）

- 文件：`工单记录格式.md`（仓库根目录）
- 规模：**5472 节点 / 最大 7 层深**（原始 MD 标题 147、字段/选项 5325）
- 顶层结构：`1.1 灌溉现场作业记录` → 头部字段(1.1.1–1.1.12) + `1.1.13 工作内容`(10 个章节) + 安全事件(1.1.14)/优秀事迹(1.1.15)
- 体量分布极不均：`1.1.13.2 灌溉项目`（FAM/WDI 材料明细 BOM）独占约 **86%**（4724 行）；其余 9 个章节为较轻的检查清单
- 文档自述：保留原始顺序与重复节点，不去重

### 1.3 系统目标

- 按 `工单记录格式.md` 原样重建工单「工作内容」的填报结构（完全遵循甲方要求，先做一版）
- 更新数据库模型以承载完整的多层级树
- 提供移动端为主、Django 网页端（服务端渲染 + JS 增强）的填报表单
- 支持按周/年/处理人/章节的统计汇总与 Excel 导出

### 1.4 关键约束（已与甲方/负责人确认）

| # | 约束 | 决定 |
|---|------|------|
| 1 | 覆盖范围 | **全部 10 个章节**（含灌溉项目材料明细 BOM） |
| 2 | 灌溉项目里的「项目1/项目2/…」 | **管理员预先建好的项目实例**，提交时下拉选择（非固定树节点） |
| 3 | PM 阶段（设计/出图/报预算/申请code/材料准备…） | **不单独拆出**，按文档原样做成树节点，与现场计数统一可填 |
| 4 | 填报终端 | **移动端为主**；**仅做 Django 网页端**（Flutter App 已废弃，不再维护） |
| 5 | 数据建模方案 | **方案 A：通用树模型 + 填报明细** |
| 6 | 表单 UX | **单页折叠树 + 全局搜索** |

### 1.5 现状关键事实

- 数据库当前**为空**：`WorkReport` / `WorkReportFault` / `FaultCategory` / `FaultSubType` / `WorkCategory` / `InfoSource` 均为 **0 条**。
- ⇒ **无需历史数据迁移**；旧的 `FaultCategory / FaultSubType / WorkReportFault` 可直接以新模型替换（详见 §8）。

---

## 2. 现状分析

### 2.1 现有工单模型（将被重构）

| 模型 | 位置 | 作用 |
|------|------|------|
| `WorkReport` | `core/models.py:1125` | 工单主体；头部字段已与文档头部基本吻合（日期/天气/处理人/位置CCU/班次/起止时间/人数/工时/疑难标记/通称位置/区域/照片） |
| `FaultCategory` | `core/models.py:1085` | 故障大类（顶层） |
| `FaultSubType` | `core/models.py:1104` | 故障子类型（`category` FK，二级） |
| `WorkReportFault` | `core/models.py:1171` | 明细：`(work_report, fault_subtype, count, equipment)` |

表单：`core/templates/core/work_report_form.html`；视图：`work_report_create` / `work_report_edit`（`core/views.py:5338` / `5429`）；移动端网页：`workorder_mobile_v2`（`core/views.py:5734`）。

### 2.2 现有模型的两点不足

1. **只能两级**：无法表达文档的 7 层结构（如 常规维护 → 维保定期检查 → 喷头 → 喷嘴丢/坏 → 弹出数量）。
2. **叶子值类型单一**：仅 `count`，无法表达状态选择（待修/已修复/功能正常）、纯文本、文本+照片。

### 2.3 现有可复用资产

- `WorkReport` 头部字段已对齐文档（直接复用，仅可能微调）。
- `Worker`（处理人）、`Patch`（位置/CCU）、`Zone`（区域）等枚举/外键实体沿用。
- 后台（`core/admin.py`）已注册同类字典模型，可沿用注册模式。
- 统计/报表入口（`custom_report`、AI stats 工具）口径可对齐。

---

## 3. 数据模型设计

采用**通用树模型**：一张自引用模板树承载全部 5472 节点，一张明细表只存「填了的叶子」，外加一张管理员维护的项目实例表。

### 3.1 `WorkItem`（模板树 · 自引用）

承载整棵「工作内容」模板。管理员可在后台增删改；首次由解析 `工单记录格式.md` 灌入。

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | CharField(unique) | 文档点号路径，如 `1.1.13.1.2.1`；作为幂等灌入与外部引用键 |
| `parent` | FK→self (null=根, CASCADE) | 父节点 |
| `name_zh` | CharField | 中文名 |
| `name_en` | CharField(blank) | 英文名（文档部分条目含） |
| `order` | PositiveInt | 同级排序（保持文档原序） |
| `level` | PositiveInt | 层级深度（灌入时计算，便于渲染/裁剪） |
| `section` | CharField(choices) | 顶层章节标签（共 12）：常规维护/灌溉项目/常规配合/温室和苗圃维护/仓库整理/会议和培训/报修应急/其他项目/排水项目/台风应急/安全事件记录/优秀事迹记录。用于表单分区与统计过滤 |
| `value_type` | CharField(choices) | `group`(分组,无值) / `count`(计数) / `status`(状态选择) / `text`(纯文本) / `text_photo`(文本+照片) |
| `status_options` | JSONField(default=list) | 仅 `status` 型：可选状态列表，如 `["待修","已修复","功能正常","漏水"]` |
| `unit` | CharField(blank) | 仅 `count` 型：单位标签，如 `"m"`（管道按米）、`"个"` |
| `is_project_scoped` | BooleanField(default=False) | 该子树是否需要绑定 `Project`（灌溉项目章节下为 True） |
| `active` | BooleanField(default=True) | 启用/停用 |
| `created_at` / `updated_at` | DateTime | — |

- Meta：`ordering = ['section', 'order', 'code']`；`unique_together` 不需要（`code` 已唯一）。

### 3.2 `WorkReportEntry`（填报明细）

只为「填了的叶子」存一行。

| 字段 | 类型 | 说明 |
|------|------|------|
| `work_report` | FK→WorkReport (CASCADE) | 所属工单 |
| `work_item` | FK→WorkItem (PROTECT) | 填报的叶子节点 |
| `project` | FK→Project (null, SET_NULL) | 仅灌溉项目章节使用；其它章节为空 |
| `count` | PositiveInt(default=0) | `count` 型叶子的数量 |
| `status` | CharField(blank) | `status` 型叶子的选中值（须 ∈ `work_item.status_options`） |
| `text_value` | TextField(blank) | `text` / `text_photo` 型叶子的文本 |
| `photos` | JSONField(default=list) | `text_photo` 型叶子的照片路径列表（安全事件/优秀事迹备忘上传） |
| `created_at` / `updated_at` | DateTime | — |

- Meta：`unique_together = ('work_report', 'work_item', 'project')`；同一工单同一叶子（同一项目下）只一行。
- 业务约束：`count/status/text_value/photos` 四者按 `work_item.value_type` 取用（详见 §7 校验）。

### 3.3 `Project`（管理员维护的项目实例）

对应文档「灌溉项目」下的 `项目1 / 项目2 / 项目…`。

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | CharField | 项目名称 |
| `category` | CharField(choices) | `FAM` / `WDI` / `其它`（对应文档 FAM项目/WDI项目） |
| `code` | CharField(blank) | 可选的项目代号/编号 |
| `active` | BooleanField(default=True) | 停用后下拉不再展示 |
| `notes` | TextField(blank) | 备注 |
| `created_at` / `updated_at` | DateTime | — |

- 设计/出图/费用评估/报预算/申请code/材料准备等 **PM 阶段不在此表**，而是 `WorkItem` 模板子树里的节点（见 §4.3），随项目填报一起填，**完全遵循文档**。
- Meta：`ordering = ['category', 'name']`；`unique_together = ('category', 'name')`。

### 3.4 灌溉项目「共享模板 + 项目实例」的建模

文档在 FAM/WDI 下重复出现 `项目1/项目2/项目…`，每个都套用**同一套模板**（设计→…→施工→材料统计→安装→调试）。建模为：

```
WorkItem 模板树（唯一一份，灌入时取 项目1 的模板为正本）
└─ 1.1.13.2 灌溉项目 (section=灌溉项目, is_project_scoped=True)
   └─ 「项目模板」子树：设计/初步方案/出图/费用评估/报预算/申请code/材料准备
       /施工(拆除/控制线/支管/…)/回收材料统计(主管/铸铁件/…→规格→count)
       /安装/安装材料统计/调试

Project 实例表（管理员建）：FAM·项目A、FAM·项目B、WDI·项目C …

填报时：选 Project → 渲染「项目模板」子树 → WorkReportEntry(work_item, project=选定)
```

⇒ 文档里 FAM/WDI 两侧重复的模板只存**一份**；项目数量随管理员增减动态变化，不再硬编码 `项目1/项目2`。

### 3.5 复用 `WorkReport`（头部字段）

`WorkReport` 已对齐文档 1.1.1–1.1.12 头部，**主体保留**，仅做最小调整：

- 沿用：`date / weather / worker / location / shift / work_start_time / work_end_time / team_size / third_party_count / team_hours / third_party_hours / is_difficult / is_difficult_resolved / zones / zone_names / photos / remark`。
- `team_hours / third_party_hours` 仍由 起止时间×人数 自动算（精度 0.5h，沿用现有逻辑）。
- 原 `work_category`(FK→WorkCategory) / `info_source`(FK→InfoSource) / `fault_subtypes`(M2M) 字段：`fault_subtypes` 移除（被 `WorkReportEntry` 取代）；`work_category`/`info_source` 视头部是否仍需要决定保留与否（见 §8.2 待定项）。

### 3.6 ER 关系总览

```
WorkReport (1) ──< WorkReportEntry (N) >── WorkItem (模板树, 自引用)
                        │
                        └── project? ── Project (管理员维护)

WorkReport ── worker ──> Worker
            ── location ──> Patch (位置/CCU)
            ── zones ──> Zone (多对多)
```

---

## 4. 模板树种子数据

### 4.1 来源与解析

- 唯一主源：`工单记录格式.md`。
- 写一个 management command `seed_work_items`，按文档点号层级解析为 `WorkItem`：
  - `code` = 点号路径；`parent` = 去掉最后一段；`level` = 段数；`order` = 同级出现序；`name_zh` = 标题文本；`section` = 所属顶层章节。
  - **幂等**：按 `code` upsert，重复执行不重复创建、可增量更新名称/排序。
  - **容忍文档瑕疵**：处理游离引号（如 `"铜管钥匙破裂`）、按文档要求**保留重复节点不去重**。

### 4.2 `value_type` 推断规则

灌入时按规则推断每个叶子的类型；规则未覆盖者默认 `count`，后台可手改：

| 文档特征 | 推断 `value_type` | 说明 |
|----------|-------------------|------|
| 子节点全是 `弹出数量` | `count` | 故障计数 / 材料数量 |
| 子节点为已知状态词集合（待修/已修复/功能正常/漏水/已疏通/不能开/…） | `status` | `status_options` = 这些子节点名 |
| 章节为「需自行填写 上传做备忘」（安全事件/优秀事迹） | `text_photo` | 文本+照片 |
| 纯分组节点（有子节点且子节点非上述） | `group` | 容器，无值 |
| 其余叶子 | `count`（默认） | 后台可改 |

- `unit`：文档中标注 `单位m` 的（管道）→ `unit="m"`；其余默认空。

### 4.3 PM 阶段处理（遵循文档）

设计/初步方案/出图/费用评估/报预算/申请code/材料准备 等，作为「项目模板」子树里的 `WorkItem` 节点存在（`value_type` 默认 `status`，选项如 `待办/进行中/完成`，或 `count`=0/1 勾选；具体在灌入规则中细化，不确定者默认 `count`）。**不拆到 `Project` 单独字段**。

---

## 5. 表单 UX 设计（移动端 · 单页折叠树 + 全局搜索）

### 5.1 页面结构

- **单一页面/URL**（一条滚动），替换/演进现有 `work_report_form.html` 与 `workorder_mobile_v2`。
- **工作内容的 10 个章节**（常规维护、灌溉项目、常规配合、温室和苗圃维护、仓库整理、会议和培训、报修应急、其他项目、排水项目、台风应急）默认折叠为 accordion；另有**安全事件记录 / 优秀事迹记录** 2 个备忘区（`text_photo`）。章节头显示**已填叶子数** `(5)`。
- **顶部吸顶全局搜索框**：输入关键词 → 后端 AJAX 返回命中叶子（带祖先路径，如 `常规维护 › 维保定期检查 › 喷头 › 喷嘴丢/坏`）→ 平铺出来直接填。

### 5.2 性能：懒加载，绝不全量渲染

5472 个 DOM 节点在手机上会卡死，故：

- 页面初始只渲染**章节头**（10 个 accordion）。
- 点开章节才**渲染该章子树**；灌溉项目章节先**下拉选 `Project`**，再展开该项目对应的「项目模板」子树。
- 全局搜索为**后端 AJAX**（不在前端过滤全量 DOM），仅返回命中叶子。

### 5.3 填报原子

| `value_type` | 控件 |
|--------------|------|
| `count` | 数字输入框（+ 单位后缀，如 `m`） |
| `status` | 下拉选择（选项 = `status_options`） |
| `text` | 文本域 |
| `text_photo` | 文本域 + 拍照/上传（安全事件、优秀事迹备忘） |
| `group` | 仅作容器，不可填 |

### 5.4 保存策略

- **字段失焦自动保存**：每个叶子填完失焦即 AJAX 写入 `WorkReportEntry`（防误退/断网丢失）。
- **底部「保存工单」按钮**：最终提交，触发头部必填校验。
- 照片上传沿用现有 `work_report_upload_photo` 模式。

### 5.5 头部字段区

页面顶部填文档 1.1.1–1.1.12：通称位置、单个/多个区域、填写人、班次、时间、人数、工时（自动）、是否疑难（→疑难已处理）。字段与现有 `WorkReport` 对齐，UX 上做移动端友好的分组。

### 5.6 终端与可访问性

- 移动端优先响应式；桌面端同页可用。
- 登录/权限沿用现有角色（`role_utils`：field worker / manager / super admin）。

---

## 6. 校验规则

| # | 规则 |
|---|------|
| 1 | 头部必填：`date` / `worker` / `location` |
| 2 | `count` 型：`count >= 0`（整数） |
| 3 | `status` 型：`status` 值必须 ∈ 该 `work_item.status_options`，否则拒绝 |
| 4 | `text_photo` 型：文本与照片均可空，但至少其中之一非空才算有效条目 |
| 5 | 灌溉项目章节（`work_item.is_project_scoped=True`）的 entry **必须带 `project`** |
| 6 | 非项目章节的 entry `project` 必须为空 |
| 7 | `unique_together(work_report, work_item, project)`：同单同叶同项目唯一 |
| 8 | 工时自动算（沿用现有 `team_hours` / `third_party_hours` 逻辑，精度 0.5h），不由用户手填 |

校验在表单/视图层与 DRF serializer 层双重把关。

---

## 7. 统计与报表

- 数据源：`WorkReportEntry`。
- 聚合维度：
  - **周小计 / 年小计**：按 `work_item` 汇总 `count`（对应旧规格的周/年汇总行）。
  - **按处理人 / 按章节 / 按班次**：JOIN `WorkReport` 取维度。
  - **按 Project**：灌溉项目材料用量。
- 入口对齐现有：`custom_report`（`/custom-report/`）、AI stats 工具（`query_work_report_stats`，`core/ai_agent.py`）口径更新为基于 `WorkReportEntry`。
- **Excel 导出**：兼容旧模板列结构（头部 + 按 `work_item` 展开的计数列）。

---

## 8. 模型替换与清理

### 8.1 直接替换（库为空，无数据迁移）

| 旧模型 | 处理 |
|--------|------|
| `FaultCategory` | **删除**（被通用 `WorkItem` 树取代） |
| `FaultSubType` | **删除** |
| `WorkReportFault` | **删除**（被 `WorkReportEntry` 取代） |

### 8.2 待定项（实现期确认）

- `WorkCategory` / `InfoSource`：若头部仍需「工作分类」「信息来源」下拉则保留并继续管理员维护；若文档头部不再需要则一并清理。文档头部 1.1.1–1.1.12 未显式列这两项 → 倾向**保留**以兼容既有统计口径，最终实现期确认。
- `WorkReport.work_category` / `info_source` / `fault_subtypes` 字段：`fault_subtypes` 移除；另两个随 §8.2 决定。
- 旧表单 `work_report_form.html` 与 `workorder_mobile_v2`：重构后统一为新表单，旧模板删除或重定向。

### 8.3 Admin

- 注册 `WorkItem`（树状编辑，按 `section`/`parent` 过滤）、`WorkReportEntry`（只读明细）、`Project`（管理员增删项目）。
- 移除旧 `FaultCategory/FaultSubType/WorkReportFault` 的 admin 注册。

---

## 9. 实施分期

| 期 | 内容 | 产出 |
|----|------|------|
| ① | **模型 + 迁移 + 种子** | 新模型(`WorkItem`/`WorkReportEntry`/`Project`)、删除旧故障模型、`seed_work_items` 解析 `工单记录格式.md` 灌树、admin 注册 | 
| ② | **后端 API/视图 + 表单** | 单页折叠树+全局搜索表单、懒加载、字段失焦自动保存、头部字段、校验、照片上传 | 
| ③ | **统计 / 报表 / Excel 导出** | `WorkReportEntry` 聚合、周/年小计、对齐 `custom_report` 与 AI stats、Excel 兼容旧模板 | 
| ④ | **清理与收尾** | 移除旧表单/旧 admin、确认 §8.2 待定项、端到端验证 | 

每期独立可验证；①是地基，必须先完成。

---

## 10. 范围外 / 后续

- **Flutter App**：已废弃，本次不动；其 `WorkReportFormScreen` 等代码保留但不维护（后续可整体删除）。
- **离线填报 / 草稿**：本期不做（依赖自动保存降低风险）。
- **多语言**：`name_en` 字段预留，本期前端默认中文。
- **项目模板可视化编辑器**：本期靠 `seed_work_items` + admin；图形化模板编辑器后续视需要再加。
- **历史 Excel 批量导入**：库为空暂不需要；如甲方后续要导入旧 Excel，另起数据导入任务。

---

## 11. 风险与对策

| 风险 | 对策 |
|------|------|
| 5472 节点表单卡顿 | 懒加载 + 后端 AJAX 搜索，绝不全量渲染（§5.2） |
| `value_type` 推断不准 | 默认 `count` + 后台可改；首版灌入后人工抽查关键章节 |
| 文档存在瑕疵/重复节点 | 解析器容忍瑕疵、保留重复（按文档自述） |
| 灌溉项目模板体量大 | 「共享模板 + 项目实例」 collapsing，避免树爆炸（§3.4） |
| 甲方后续改条目 | `WorkItem` 后台可改 + 种子幂等可重灌 |

---

*本设计为「先做一版」基线，完全遵循甲方 `工单记录格式.md`；实现期遇到文档歧义以文档原文为准，并在本文件追加修订记录。*
