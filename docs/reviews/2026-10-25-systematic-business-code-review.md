# 全业务线代码审核 — 2026-10-25

> 本文是修复前的审核快照。后续代码整改、验证结果、发布状态及待处理条件见 [2026-10-26 整改记录](2026-10-26-business-hardening-release.md)。

## 结论与范围

源码基线：`6499a6ef`，分支 `codex/maxicom-data-review`。这份报告记录审核结果，**没有实施或部署下列修复**。本轮没有重新连接生产服务器，没有读取真实 AI 会话、执行真实邮件发送或改动生产业务数据。

确认 **24 项问题：23 项权限、功能或数据缺陷，以及 1 项导航体验问题**，其中 P1 11 项、P2 13 项。另外列出 6 项性能改进和 5 项交互改进。所有 B 项都有隔离复现；性能建议明确区分实测查询数和静态分析。

- **P1**：优先修复，涉及越权、审批绕过、数据破坏、服务端执行隔离或影响大量页面。
- **P2**：随后修复，涉及部分接口不可用、错误汇总、漏记录、状态反馈和流程一致性。
- 这是按业务入口、关键写入、权限、跨模块口径和客户端状态进行的审核，不能视为每条路径均无遗漏的证明。

| 业务线 | 本轮检查重点 | 结果 |
| --- | --- | --- |
| 地图、区域、地标、CAD | 局部更新、有效边界、地标关联、管理权限、数据加载 | B07、B11、B14、B23；S01、S02、S05 |
| 普通工单、维修跟进 | 网页与手机入口权限、旧 API、排序分页、照片与材料链路 | B04、B12、B15；S04 |
| Job Plan、PM、班组 | 轮转、实际日历月、截止日、执行资产范围、延期、幂等提交 | 既有 85 项 PM 回归通过；本轮未确认新的轮转/截止周期缺陷 |
| 库存、预估消耗 | 本人范围、确认状态、编辑、确认/撤销、数值精度 | B05、B09、B18；S04 |
| 采购、项目、预算 | 收货汇总、订单完成、材料计入规则 | B16、B17 |
| 用水需求、审批 | 申请人权限、审批入口、部门用户兼容、时间范围、通知上下文 | B06、B08、B13、B20 |
| 灌溉、Maxicom | 查询聚合、来源身份、已有时间修复和 FS 数据限制 | 既有流量/时间测试通过；S03；K01、K02 |
| 账号、注册、API 认证 | 停用、Token、注册审批事务、网页/API 身份差异 | B10、B19；B04、B13 |
| AI、文件、流式响应 | 执行隔离、会话归属、媒体下载、资源生命周期 | B01–B03；S06、U04 |
| 邮件、报表 | 部分附件失败、调度重入、汇总口径 | B21、B22；B16、B17 |
| PWA、公共 UI、通知、水印 | 角色导航、离线提交边界、已有脚本回归、状态说明 | B24；U01–U05；既有 PWA/水印测试通过 |

## 已复现的 P1 问题

### B01 — AI 的 Python 工具没有实现目录/进程隔离

位置：[ai_agent.py:1740](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/ai_agent.py:1740)。

工具直接使用应用 Python 执行生成的任意代码。设置工作目录、删减环境变量和 30 秒超时不会限制文件访问、网络或子进程权限。工具说明中的“禁止访问网络/数据库/其他目录”没有对应的执行约束。

**复现：**在临时工作区的父目录放置无敏感内容的标记文件，工具成功读取 `../outside.txt`。未读取真实配置或密钥。影响范围是应用进程操作系统账号有权访问的资源；这不是声称具有系统 root 权限。

**修复：**将执行器移到独立受限进程/容器或专用服务，按需挂载输入，只开放输出目录，限制网络、资源和子进程。不能仅靠提示词、环境变量或路径字符串检查实现隔离。

### B02 — 任意已登录角色可以下载 AI 会话数据库

位置：[urls.py:22](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/config/urls.py:22)、[ai_agent.py:1827](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/ai_agent.py:1827)。

AI 检查点库位于 `MEDIA_ROOT/ai_checkpoints.sqlite3`，媒体路由对所有已登录用户提供文件服务，仅检查登录状态。前线或部门账号可请求固定路径，缺少 AI 角色和会话所有权校验。

**复现：**用临时假检查点文件替代媒体根目录，前线账号下载得到 HTTP 200 和文件内容。没有下载真实会话库。

**修复：**会话库移出所有媒体服务目录；AI 导出文件改由受保护下载接口提供，并校验文件所属会话和用户。普通媒体与 AI 工作区采用不同访问规则。

### B03 — AI 会话编号只验证格式，没有验证所属用户

位置：[ai_views.py:85](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/ai_views.py:85)。

任何格式合法的 `u<用户编号>-<随机段>` 都会被接受并直接传给共享检查点库及工作区。经理账号知道另一个会话编号时，可复用该会话的上下文或写入其历史。

**复现：**用户 A 的请求携带用户 B 的会话编号，HTTP 200，后端使用 B 的编号。模型输出使用模拟流，没有调用真实模型。

**修复：**由服务端维护会话所有者；继续会话必须查验所有权。编号前缀匹配可作为额外检查，不能替代服务端所属关系。

### B04 — 部门账号可通过桌面工单编辑入口修改他人工单

位置：[workorder_tree_views.py:1308](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/workorder_tree_views.py:1308)。

树形工单入口只检查登录，没有与手机入口、详情页面一致的角色限制。部门用户虽然不具备正常工单详情/手机填报权限，却能直接 POST 桌面编辑地址，修改他人的记录、明细和材料。

**复现：**部门账号将另一名前线员工的工单备注从 Original 改成新内容，记录确实更新。

**修复：**网页、手机、元数据及旧 API 共用工单操作权限。区分查看、协作跟进、编辑、重分配、删除；不得以“页面没有按钮”代替后端检查。

### B05 — 前线员工可以修改他人的已确认库存流水、作废他人的预估消耗

位置：[views.py:11803](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:11803)、[views.py:12064](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:12064)、[views.py:12262](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:12262)。

列表限制前线只看自己的实际流水，但编辑、预估确认、作废入口按任意主键取记录，没有应用相同范围。编辑已确认流水还保留 confirmed，立即调整库存，无需再次经理确认。

**复现：**员工 B 将员工 A 已确认的 5 件出库改为 9 件，库存从 95 变为 91，状态仍为 confirmed；另一场景中，B 成功删除 A 的预估单。

**修复：**共享本人/经理可操作查询范围；已确认单的修改应由经理执行，或撤销原确认并重新进入审核。元数据读取也需要同样范围。

### B06 — 申请人可以通过旧 API 自行批准用水需求

位置：[api.py:303](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/api.py:303)、[api.py:479](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/api.py:479)。

API 使用“所有者或管理员可写”的权限，序列化器又允许写入 status。所有者可以绕过网页的管理员审批入口，直接把自己的状态改成 approved。

**复现：**所有者 PATCH 后状态为 approved，而 approver、processed_at 均为空。

**修复：**申请内容和审批动作分离；普通申请人不能写审批字段。所有状态转换走共同服务，统一校验角色、当前状态、审批人及通知。

### B07 — 区域改名等局部更新会清空手绘边界

位置：[api.py:357](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/api.py:357)。

`perform_update` 在请求没有 boundary_points 时使用默认空数组，并无条件保存该字段。符合 PATCH 语义的局部属性更新会破坏原有几何数据。

**复现：**有 4 个边界点的区域，只 PATCH name，HTTP 200，边界点变成 0 个。

**修复：**仅在请求明确包含边界字段时处理并写入；否则保留已有边界。同时验证手绘/DXF 切换及面积是否同步。

### B08 — API 新建用水需求可以导致管理员的 HTML 页面报错

位置：[api.py:497](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/api.py:497)、[context_processors.py:57](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/context_processors.py:57)。

API 接受多区域 zones，但没有设置旧版单区域 zone。全站管理员通知上下文无条件读取 `req.zone.name`；当该待审批需求进入最近 5 条列表，使用基础模板的管理员页面会触发异常。

**复现：**正常 API 创建返回 201；随后管理员通知上下文抛出 `AttributeError`。该风险跨页面，不能只修用水列表。

**修复：**通知使用安全的多区域标签，兼容旧单区域及空区域数据；创建服务统一新旧字段约定，并加入“创建需求后渲染管理员页面”的链路测试。

### B09 — 库存确认的并发请求可以重复扣减

位置：[views.py:12145](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:12145)，同类结构存在于取消确认、移除和恢复入口。

候选流水在事务外读取；两个请求都读到 pending 后，各自进入事务保存 confirmed 并扣库存。F 表达式只能保证单次加减不丢失，不能保证状态转换只执行一次。

**复现方式：**确定性模拟“两个请求先读 pending，再依次完成写入”的执行顺序。单条 5 件出库把库存从 100 扣至 90，正确结果应为 95。这是受控交错复现，不是生产压测结果。

**修复：**在事务内以条件更新认领状态转换，并按受影响行数决定是否移动库存。当前 SQLite 上仅添加 `select_for_update()` 不能提供行锁保证；确认、撤销、移除、恢复及预估转实际需统一处理。

### B10 — Django 账号停用后，已发出的 API Token 仍能使用

位置：[authentication.py:33](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/authentication.py:33)。

Token 认证只检查 Worker/ManagerProfile/DepartmentUserProfile 的 active，没有检查关联 User 的 is_active。

**复现：**User.is_active=False、Worker.active=True，原 Token 仍认证成功。该问题指 Django 账号停用与档案停用不一致，并非所有停用入口都无效。

**修复：**统一账号和档案启用判断；显式停用时使会话与 Token 同步失效，并覆盖无关联 User 的历史档案策略。

### B11 — 地标增删改和重新计算缺少管理权限

位置：[views.py:5506](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:5506)、[views.py:5553](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:5553)、[views.py:5582](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:5582)。

这些写入入口只要求登录，批量删除也如此，与区域/管线管理入口的权限不一致。

**复现：**部门账号删除地标返回 HTTP 200，地标实际消失。

**修复：**增删改、批量删除和重新计算统一使用地图管理权限；只读地标接口继续按查看权限提供。

## 已复现的 P2 问题

| 编号 | 业务线与位置 | 触发条件及实际影响 | 建议修复 |
| --- | --- | --- | --- |
| B12 | 工单 API — [api.py:854](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/api.py:854) | `/api/work-reports/` 仍 select_related 已删除的 work_category、info_source，并预取已删除的 fault_entries。正常查询抛 FieldError，不能正常供客户端使用。 | 迁移到 WorkItem/entries 模型；对列表、详情、编辑、照片动作逐一验证，保留角色检查。 |
| B13 | 部门需求 API — [api.py:497](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/api.py:497) | 部门用户没有 worker_profile；创建需求时直接访问该属性，抛异常，而正常网页支持 submitter_user。 | API 与手机网页共享提交人解析，正确记录部门 User；不能随意借用其他 Worker。 |
| B14 | 地图几何接口 — [views.py:10965](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:10965) | 连续排除两个边界空数组，实际要求手绘、DXF 都非空。只有有效手绘或只有 DXF 的区域会漏掉；同类内部 helper 也有该条件。有效手绘区域复现返回空列表。 | 按 active_boundary_points 判断是否可用，统一来源选择与坐标格式；避免各接口复制筛选逻辑。此问题不等于主页使用的 zones-payload 一定同样漏图。 |
| B15 | 工单分页 — [views.py:9630](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:9630) | 人员排序仍用 id 小于上一页最后一条作为游标。31 条记录中，A 的 30 条先显示，B 的较新一条永远加载不到，下一页为空。其他分布也可能重复。 | 游标必须包含完整排序键，例如姓名与 ID；切换排序/筛选必须重置游标。 |
| B16 | 项目材料 — [workorder_tree_views.py:413](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/workorder_tree_views.py:413) | 只排除 removed，pending actual 仍计入材料消耗。复现待确认 5 件已进入项目汇总，库存仍是 100。 | 实际项目消耗遵守 actual + confirmed，并保留工单材料关联确认规则；待确认另列，不计入已发生数量。 |
| B17 | 采购收货 — [views.py:12881](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:12881) | 收货汇总没有限制确认状态/实际类型。已移除的 5 件收货仍能使计划 5 件的订单完成；待确认也被累计。 | 采购页、完成判定、Excel、AI 共用同一已确认实际收货口径；确认变化应重新校验完成状态。 |
| B18 | 库存数量精度 — [views.py:11866](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:11866)、[workorder_tree_views.py:1775](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/workorder_tree_views.py:1775) | 代码按 float 接收数量，流水模型却是整数。输入 1.5，流水存 1，SQLite 原始库存变成 98.5；后续按流水回滚只能退 1，账实漂移。 | 明确计量精度：继续整数则所有入口拒绝小数/非有限值/错误结构；如允许米、升等小数则统一 Decimal 字段、验证和计算。禁止静默取绝对值或截断。 |
| B19 | 注册审批事务 — [views.py:6208](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:6208)，旧审批页存在同类结构 | 先创建 User，再创建角色档案，没有覆盖整体的事务。工号冲突或档案创建异常会留下 User，申请仍 pending，重试又撞用户名。 | 预检用户名/工号，在单个事务中锁定申请并创建 User、档案、审批结果；数据库唯一约束冲突转成清楚错误。 |
| B20 | 需求时间 — [views.py:11453](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:11453) | 只解析开始/结束时间，不检查顺序。18:00 开始、06:00 结束的同日申请仍成功保存，影响审批和地图提示。 | 两端统一转上海时区并校验结束晚于开始，前端就地提示，后端强制执行。 |
| B21 | 邮件部分失败 — [send_report_email.py:175](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/management/commands/send_report_email.py:175) | 配置要求两份附件，一份失败，另一份发送后记录 success，失败附件被隐藏。模拟发送场景已复现，没有发送真实邮件。 | 记录 partial_success，保存逐附件结果；界面提示缺失项和重试状态。 |
| B22 | 邮件调度重入 — [send_report_email.py:143](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/management/commands/send_report_email.py:143) | 调度只检查日期/小时，不以配置 + 调度时段去重。同一发送时段重复运行两次，模拟 send 被调用两次。last_sent_at 没有用于防重复。 | 用唯一调度执行记录认领每个发送时段，区分正常调度、失败重试和管理员明确重发。 |
| B23 | DXF 地标关联 — [views.py:5453](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:5453) | 地标重算只取手绘 boundary_points，忽略正在生效的 DXF。完全相同的地标和有效 DXF 区域仍得到 0 个关联，筛选分组随之漏项。 | 统一读取有效边界；重算在临时结果完整后原子替换，防止中间空结果。 |
| B24 | PWA 角色导航 — [pwa.py:19](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/pwa.py:19) | 工作台向部门用户展示库存管理入口，但点击后被拒绝并跳回主页。该项是已复现的体验缺陷，不是库存页访问控制失效。 | 模块入口按真实查看权限生成；区分无权限、未配置、空数据，避免循环跳转和“按钮点了没反应”。 |

## 性能改进

| 编号 | 位置与证据 | 改进方向、边界及验收 |
| --- | --- | --- |
| S01 — 区域管理查询数随片区增长 | [views.py:2398](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:2398)。40 个 Patch 的隔离数据产生 **40 次独立 children.count 查询，视图渲染前总计 47 次查询**，还未计模板查询。全部 Patch 还包含 station 类型。 | 用聚合 annotate/batched count；按实际显示内容加载各 tab，清楚区分地理片区和站点。验收查询数不随每个 Patch 增长。本轮不把本地查询数当作生产耗时。 |
| S02 — 只读 API 的关系查询未批量加载 | [api.py:813](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/api.py:813)。8 个 Patch、同一 Region，仍额外查询 Region **8 次**，接口总计 11 次。Region 的 patch_count 也逐项 count。 | Patch select_related(region)，Region annotate 有效片区数量；用 1/10/100 条数据验证查询数稳定，并按客户端用途分页或提供精简投影。 |
| S03 — 长时间灌溉查询加载全部运行记录 | [views.py:7498](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:7498)、[views.py:7533](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:7533)。按每条运行记录实例化 ORM 对象及关联，再在 Python 归组；“重置全部范围”会放大内存和响应时间。每个 CCU 还单独查站点。属于静态确认的扩展性问题，未进行生产压测。 | 在 SQL 按 Site/Station SUM 后读取必要列；一次加载站点/控制器元数据，跨 CCU 复用。保留 24 行矩阵、孤立站点提示、时区秒边界及导出一致性。不要用改动用户已核对分钟值来换性能。 |
| S04 — 隐藏 tab 仍一次性加载和渲染 | [views.py:11911](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:11911)、[views.py:9666](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:9666)。库存已确认/待确认/移除、全部预估、采购和目录都准备；工单页还扫描区域 JSON 备注并构造其他 tab。目录和流水规模增长时浪费手机网络和 DOM。 | 按 tab 延迟加载，流水游标分页；备注逐步关系化并索引 workorder_id。避免先全部下载再只隐藏 DOM。保留筛选和返回位置。 |
| S05 — 地标全量两两计算 | [views.py:5457](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/views.py:5457)。地标 × 区域循环中反复转换几何，并逐条 INSERT；先删旧关联再重建。静态算法与事务风险已确认，未测生产几何规模。 | 几何只转换一次，包围盒/空间索引先筛候选，bulk_create，完整结果原子替换；几何编辑后增量更新。同时修 B23。 |
| S06 — AI 流的资源生命周期 | [ai_views.py:120](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/ai_views.py:120)。每个流起线程，无界队列，q.get 无超时；客户端停止接收不会主动取消后台模型/工具，缺少心跳和全程预算。 | 有界队列、心跳、断连清理、执行取消和总超时、每用户并发限制；将长分析移出普通同步页面请求容量。验收断连后工具能收尾、其他页面仍响应。该项未进行真实模型并发压测。 |

## UI/UX 逻辑改进

| 编号 | 当前问题 | 建议 |
| --- | --- | --- |
| U01 — 来源、精度与新鲜度 | 流量区目前标升，但原始值的物理单位/采样积分仍有 K01 限制；不同页面混合显示原始值、台账状态和统计值时不易理解。 | 显示数据来源、最近一次成功导入、查询时间范围和异常状态；已确认/待确认/预估分别显示，不能把未知当零。单位未确认时明确说明，避免把“与数据库一致”展示成“已核准升数”。 |
| U02 — 现场表单与弱网 | PWA 目前阻止离线提交并提示先核对，合理；但缺少服务端请求唯一键，响应丢失后的人工重试仍可能新增重复库存/需求。页面切换或手机回收后也不等于有可靠草稿。 | 增加每次提交唯一键和结果查询；提供“正在提交/已提交/结果待确认”状态。草稿必须按用户隔离、提供恢复与清除，不应把离线写入自动重放当默认。 |
| U03 — 数据窗口与翻页 | 用水需求只截取前 200 条，没有完整分页；工单 B15 会漏记录。全局时间筛选与每类模块的筛选范围也需要清楚区分。 | 展示总数、当前条数、加载更多/分页；所有导出说明使用哪组筛选；切换 tab 保留本 tab 筛选但明确作用范围。 |
| U04 — AI 会话与工具反馈 | 工作区首次生成后依赖 .populated 标记，后续对话可一直使用旧 CSV；覆盖同名结果文件又不会出现在“新文件”列表。流停止的实际行为也应与文案匹配。 | 显示快照时间，支持主动刷新/按数据版本更新；检测新增和已修改文件；持久化可恢复会话列表前先完成 B02/B03。对断连、部分工具失败和空结果给出明确状态。 |
| U05 — 同步与错误入口 | 主图仍轮询已退役 agent 的心跳，正常批量导入也可能显示从未连接/离线；很多 AJAX 接口返回登录重定向，前端随后按 JSON 解析，只显示笼统失败。 | 用批量导入任务的最后成功时间/源备份版本作为同步状态；AJAX 统一返回 401/403/校验错误结构，保留表单并指引重新登录。删除无实际用途的逐页通知查询。 |

## 需要保留的已知限制

**K01 — FS 水量单位和采样语义尚未独立核准。** 本轮没有重新向用户索要 Rain Bird 对照值。已部署代码保留原始 value × multiplier，并已验证来源、归属、时间筛选和 JoinSite；这些不等同于物理升数转换或流量积分已核准。见[水量专项报告](/C:/Users/ZC/ZCodeProject/irrigation/docs/reviews/2026-10-25-maxicom-water-volume-review.md)。

**K02 — 无 CCU 前缀的控制器仍有 Site 内部键回退问题。** [导入代码:154](/C:/Users/ZC/ZCodeProject/irrigation/internal_server/core/management/commands/import_maxicom_mdb_linux.py:154) 对 SAT1/SAT2 等名称无法解析 CCU 时直接使用 StationSiteNumber 匹配 CCU，仍可能混淆 Site 内部编号和显示编号。这是上轮记录的未修项，本轮没有重新核对生产分钟记录。后续修复必须保留明确的子区域/共享归属，不能全局按显示 Site 强行覆盖名字可解析的 CCU。

PM 的既有轮转、完整月度截止窗口、闰年、日截止边界、重复完成、延期、资产范围等测试继续通过。FS 修复也未改动 runtime。本报告没有据此宣称所有 PM 并发场景或生产调度安装状态都已重新验证。

## 验证记录与复现方式

- 现有 Django **231 项测试：230 通过、1 项既有缺失 CAD 样本跳过**，21.873 秒。包括既有 85 项 PM 测试。
- 现有 Node **54 项测试全部通过**，覆盖地图、PWA 导航/缓存、AI 活动与文件、动态水印、DXF 放置。
- 新增隔离诊断 **27 个场景全部完成并符合观察结果**，2.179 秒，不含建库迁移时间。它们证明当前问题可以复现，**不是 27 项修复已通过**。B05 用两场景验证，其余场景包括 24 个 B 问题和 S01/S02 的查询数。
- 使用 Django 临时内存测试库及测试专用内存缓存，未触碰普通开发库或生产库。文件访问仅用临时假文件/标记文件；模型流、邮件和并发候选读取按场景模拟。
- B09 采用确定性交错模拟；S03–S06 是源码分析，未测量生产延迟或并发容量。没有进行新的真机屏幕、GPS、摄像头和离线存储验收，也未运行 Flutter/云中继的完整端到端测试。
- 现有测试通过但仍发现上述问题，说明原测试矩阵缺少权限负例、跨模块确认口径、旧接口、排序分页、部分失败和并发状态转换，不能将绿灯当作业务无误保证。

可复用诊断：[business_review_probe_20261025.py](/C:/Users/ZC/ZCodeProject/irrigation/docs/reviews/diagnostics/business_review_probe_20261025.py)。

在本项目根目录运行：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.venv/Scripts/python.exe docs/reviews/diagnostics/business_review_probe_20261025.py
```

脚本使用临时测试库；断言有意描述 **2026-10-25 当前缺陷表现**，不得作为期望长期保留的业务规则。修复时将对应场景改为断言正确权限/正确数值，并纳入正式回归测试。诊断 JSON 为[本次证据快照](/C:/Users/ZC/ZCodeProject/irrigation/docs/reviews/2026-10-25-business-audit-evidence.json)，新运行结果写入项目忽略的 `.tmp-pm-review/`。

## 建议实施顺序

1. **访问边界和数据保护**：B01–B07、B10、B11，先封住 AI 执行与下载风险、越权和边界误清；相应操作保留正常员工流程。
2. **台账与审批一致性**：B08、B09、B16–B20，统一状态转换服务、条件认领和计量验证；在隔离副本做前后库存核对，避免直接修改历史账。
3. **接口可用性与漏记录**：B12–B15、B23、B24，恢复旧客户端兼容、正确分页及有效边界路径。
4. **调度、性能与交互**：B21、B22、S01–S06、U01–U05。先消除逐条查询和无界加载，再扩展弱网体验。每批带实际业务链路回归后发布。

本轮交付为审核报告、复现脚本和脱敏证据；应用源码和生产服务未作修改。
