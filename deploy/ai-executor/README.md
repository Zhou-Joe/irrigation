# AI 计算执行器与业务修复发布

本次代码不再在 Django 进程权限下运行生成的 Python。查询和报表导出仍可直接使用；Python 分析必须配置容器镜像。未配置或运行失败时会明确报错，不会回退到主机 Python。

## 执行器准备

在 Linux 上为应用运行账号配置 **rootless Docker**，依照 [Docker 官方安装说明](https://docs.docker.com/engine/security/rootless/)操作。应用账号不加入拥有主机 root 权限的 Docker 组。确认该账号能运行 `docker info`，并让其用户服务随 WSL 启动；不要向公网开放 Docker 接口。启用 rootless 资源限制前，确认主机支持并启用了 cgroup v2 的 CPU/内存委派。

从仓库根目录构建镜像（构建阶段需要访问官方镜像库和 PyPI）：

```sh
docker build --pull -t irrigation-ai-executor:20261026 deploy/ai-executor
```

在 horticulture 服务的环境文件中添加：

```dotenv
AI_EXECUTOR_IMAGE=irrigation-ai-executor:20261026
AI_EXECUTOR_BINARY=/usr/bin/docker
DOCKER_HOST=unix:///run/user/<应用账号UID>/docker.sock
```

`AI_EXECUTOR_BINARY` 使用实际安装路径；`DOCKER_HOST` 中的 UID 用应用账号的 `id -u` 替换。环境必须由服务进程继承。根目录 `AI_PRIVATE_ROOT` 默认是 `internal_server/private_ai`，不可在任何媒体或静态目录内。

运行时使用 `--pull=never`，无外部网络、只读镜像、非特权用户、无 Linux capabilities、有限内存/CPU/进程数。只挂载临时复制的 CSV/XLSX/JSON 输入；可写工作区和临时区均为限额 tmpfs。结果文件有类型、名称、大小和数量限制。执行时间最多 35 秒，结束后强制清理容器。未把应用源码、数据库、环境文件或 Docker socket 挂载到计算容器。

使用与生产服务一致的环境、应用账号和虚拟环境，先执行：

```sh
cd internal_server
../.venv/bin/python manage.py check_ai_executor
```

该命令只创建临时假数据，不调用模型、不读取业务记录。它验证非特权账号、根目录不可写、仅 loopback 网络、读表及导出 Excel。必须出现 `Isolated AI executor verified with synthetic data.` 才能把计算功能记作已启用。它不能替代资源限制/并发压测或主机隔离评估。

## 应用发布顺序

1. 记录当前 Git revision，检查工作区，准备 SQLite 在线备份与 media/private_ai 备份。保留回滚代码、环境文件和定时任务。暂停导入/邮件定时任务并停止 horticulture，避免新旧进程同时写 AI 检查点。
2. 取到经过测试的 `codex/business-hardening` 提交，以既有部署流程更新代码。不要覆盖生产 `.env.production` 或数据库。
3. 加载生产服务环境，执行 `manage.py migrate --noinput`，确认 `0134_business_operations_guardrails` 已应用。该迁移只新增会话、执行租约、提交回执、邮件调度记录和导入状态表，不回填或重算历史库存。
4. **服务启动前**执行 `manage.py migrate_private_ai`。它复制并注册旧会话和文件，不覆盖已存在的私有文件。检查私有检查点库及目录归属为应用账号；不要把旧工作区重新放进公开下载路径。
5. 如果前面有独立 Nginx/media alias，另行拒绝 `/media/ai_*` 和数据库文件请求；应用层拒绝规则不能阻止代理直接读盘。AI 文件应仅走 `/ai/files/<会话>/<文件>` 的归属检查接口。
6. 执行 `manage.py collectstatic --noinput`，完成执行器 smoke check，启动 horticulture。检查服务和登录页，验证前线/部门/经理各一条正常流程及越权拒绝。不要用真实业务表单制造测试流水。
7. 恢复定时任务。下一次成功导入才会生成真实的新鲜度记录；升级后首次显示“暂无记录”是正常现象。现有分钟值不重算。K02 归属与元数据在正常下一次导入更新，再执行既有 `populate_zone_maxicom_runtime` 步骤。
8. 验证手机收到 PWA 更新提示并重新打开；检查新的脚本版本和 `irrigation-shell-20261026-business-1`。有未提交表单时不要强制刷新。

本次 SSH 只读检查发现生产服务运行旧版 `8bb190d`，未安装 Docker/Podman/bwrap，**没有实施上述发布或环境安装**。先完成运行环境准备，再启用 Python 分析。

## 回滚及操作语义

- 回滚应用时保留新增表和 `private_ai`；不要仅因回滚代码就删除新会话或提交回执。旧版存在已知 AI 执行/媒体访问问题，不能直接重新开放其 AI 功能；先禁用 AI 并保留代理媒体拒绝规则。
- `migrate_private_ai` 可重复运行，但不会合并两个均已写入的检查点库。迁移必须在停服窗口完成；不要在首次新建私有库之后才尝试迁移旧历史。
- 自动邮件按配置和上海时间小时唯一认领；发送失败或部分成功不自动重发，以免投递结果不明造成重复。管理员现有“测试发送”/命令 `--config-id` 是**明确重新发送全部附件**，应先查看状态；邮件系统不提供跨 SMTP 的绝对 exactly-once 保证。
- 提交回执不是离线队列。结果不明时复用原提交编号核对/重试；文字草稿按账号隔离、保留 24 小时，可恢复或清除，不保存照片/完整区域和物料选择。浏览器禁止存储时仅当前页面内保留提交编号。
- 库存数量沿用现有整数模型。小数/负数/NaN/Infinity 被拒绝，不静默截断；历史账实差异应先核查再单独修账，本次不自动重算。
- 全局最多 3 个 AI 分析、每账号 1 个，当前生产 4 个同步 worker 至少保留 1 个给普通页面。这是容量保护，不是将任务迁出 HTTP 的分布式作业系统；未来扩容需结合独立队列、数据库和实际负载评估。
