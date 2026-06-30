# 安全与性能审计修复 — 部署说明

> **生成日期**: 2026-06-30
> **用途**: 生产服务器 `git pull` 后的上线清单。请生产端运维/AI 按本文档执行。
> **核心原则**: 本文标注「⛔ 必做」的项不做会导致**服务无法启动**或**功能异常**。

---

## 一、本次改动总览

本次提交对灌溉管理系统做了一次系统性的**安全加固 + 性能优化**,共修复 4 个严重漏洞、9 个高危问题、多个中危问题和 3 个性能热点。所有改动已在本地通过 `python manage.py check` 和逐批冒烟测试验证。

| 类别 | 数量 | 影响 |
|---|---|---|
| 严重漏洞 (Critical) | 4 | 认证后门、密钥泄露、Cookie 安全、同步密钥 |
| 高危 (High) | 9 | 文件上传、媒体访问、开放重定向、部署配置等 |
| 中危 (Medium) | 多个 | 弱密码校验、IDOR、速率限制等(部分已顺带修复) |
| 性能优化 | 5 | N+1 查询消除、数据库索引 |

---

## 二、⛔ 上线必做步骤(按顺序执行)

### 步骤 1:确认环境变量(否则服务无法启动)

本次移除了两处**不安全的默认值**。如果环境变量缺失,Django 会**直接拒绝启动**(`SECRET_KEY`)或**功能异常**(`SYNC_API_KEY`)。

```bash
# 检查当前是否已设置
echo "SECRET_KEY = [${SECRET_KEY:-未设置}]"
echo "SYNC_API_KEY = [${SYNC_API_KEY:-未设置}]"
```

#### 1.1 `SECRET_KEY`(必须)

- **变化**: `config/settings.py` 移除了硬编码的默认密钥 `'65=850236hyhtzpqp...'`(该密钥已泄露在 git 历史)。
- **新行为**:
  - 生产环境(`DEBUG=False`)若 `SECRET_KEY` 未设置 → **启动时报 `RuntimeError` 拒绝启动**。
  - 开发环境(`DEBUG=True`)若未设置 → 自动生成临时 key(仅本地用)。
- **操作**:
  ```bash
  # 如果生产之前没显式设过 SECRET_KEY(依赖了旧的硬编码默认值),现在必须生成并设置:
  export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
  # 写入环境变量持久化(根据你的部署方式选择 .env / systemd / gunicorn 配置等)
  ```
- **⚠️ 副作用**: 轮换 `SECRET_KEY` 后,所有用户的 session cookie 失效,**需要重新登录一次**。这是预期且安全的行为。

#### 1.2 `SYNC_API_KEY`(必须)

- **变化**: `core/sync_views.py` 移除了默认值 `'dev-sync-key-change-in-production'`。
- **新行为**: 若未设置,`sync_receive`(Maxicom 数据同步写接口)会对所有请求返回 403,**Maxicom 灌溉数据将停止同步**。
- **操作**:
  ```bash
  # 确认 SYNC_API_KEY 已设置,且与同步 agent 端配置的 key 一致
  echo $SYNC_API_KEY
  ```
  如果之前没设过(依赖了公开的默认值),需生成一个强密钥,并**同步更新同步 agent 端的配置**:
  ```bash
  export SYNC_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  # 同步 agent 端(发送数据的 Maxicom2 sync agent)也要用同一个 key
  ```

### 步骤 2:应用数据库迁移(新增索引)

本次新增了一个 migration,为两个高频查询字段添加索引:

```bash
cd /home/projects/irrigation/internal_server
python manage.py migrate core
```

**此 migration 做了什么**:
- `WorkReport.date` 加 `db_index=True`(工单报表按日期范围过滤的核心字段)
- `MaxicomRuntime` 加 `(site, timestamp)` 复合索引(灌溉 dashboard/PDF/Excel 的核心过滤)

**注意事项**:
- SQLite 上执行是瞬间完成,但建议在**低峰期**做(建索引时会有短暂锁表)。
- migration 文件:`core/migrations/0067_alter_workreport_date_and_more.py`
- 可以用 `python manage.py showmigrations core` 确认 `0067` 已应用。

### 步骤 3:确认隧道指向 127.0.0.1(若适用)

本次把 `healthcheck.sh` 里 gunicorn 的监听地址从 `0.0.0.0:8000` 改成了 `127.0.0.1:8000`(安全加固,避免应用直接暴露在所有网卡上)。

```bash
# 检查隧道(cloudflared / frpc)连接的是哪个地址
grep -i "8000\|addr\|local_port" /opt/frp/frpc.toml
```

- **如果隧道指向 `127.0.0.1:8000` 或 `localhost:8000`** → ✅ 无需改动,直接生效。
- **如果隧道指向内网 IP(如 `10.x.x.x`)或 `0.0.0.0`** → ❌ 需要把隧道配置改为指向 `127.0.0.1:8000`,否则隧道连不上应用。

> `healthcheck.sh` 里的健康检查 `curl http://localhost:8000/` 本身不受影响。

---

## 三、完整的重启流程(典型)

```bash
# 1. 拉取代码
cd /home/projects/irrigation
git pull

# 2. 确认环境变量(按步骤 1)
echo $SECRET_KEY && echo $SYNC_API_KEY

# 3. 应用迁移(按步骤 2)
cd internal_server
python manage.py migrate core

# 4. 确认隧道地址(按步骤 3),然后重启服务
bash ../healthcheck.sh   # 或你惯用的 gunicorn 重启方式
```

---

## 四、各项改动的详细说明(供排查)

### 安全修复

| ID | 文件 | 改动 | 破坏性 |
|---|---|---|---|
| C1 | `core/authentication.py` | 移除数字 token 认证后门(原 `Token 1` 可冒充超管) | 移除了「按 user id 认证」的能力;超管需用真实 `ManagerProfile.api_token` |
| C2 | `config/settings.py` | 移除硬编码 SECRET_KEY,生产强制环境变量 | ⛔ 见步骤 1.1 |
| C3 | `config/settings.py` | 生产环境 Cookie 改回 `Secure=True` + SameSite/HttpOnly | 仅影响 HTTPS,正常 |
| C4 | `core/sync_views.py` | sync key 改用 `hmac.compare_digest`,移除不安全默认值 | ⛔ 见步骤 1.2 |
| H1 | `core/upload_security.py`(新增)+ 5 处上传点 | 文件上传加扩展名白名单 + 50MB 上限 + Pillow 内容校验 | 会拒绝 `.html`/`.svg`/改名文件(预期);合法图片/视频不受影响 |
| H2 | `config/urls.py` | `/media/` 加 `login_required` | 匿名无法访问媒体;网页端(session)正常 |
| H3 | `core/views.py` | 登录 `next` 参数加 host 校验,防开放重定向 | 正常 |
| H4 | `core/ai_views.py` | AI `thread_id` 正则校验,防路径穿越 | 非法 thread_id 被拒(预期) |
| H5 | `core/views.py` | `remarks_list` 加 `@login_required` | 匿名无法访问(预期) |
| H6 | `core/sync_views.py` | sync 状态接口加认证 | 见下方「同步接口」说明 |
| H7 | `config/settings.py` | 生产环境加 `SECURE_SSL_REDIRECT=True` | HTTP 请求会重定向到 HTTPS |
| H8 | `healthcheck.sh` | gunicorn 绑定 `127.0.0.1`、超时 600s→120s | 见步骤 3 |
| H9 | `config/settings.py` | ALLOWED_HOSTS 移除 `.trycloudflare.com` 通配和裸 IP | 如需临时域名,用环境变量覆盖 |
| - | `config/settings.py` | CSRF_TRUSTED_ORIGINS 移除裸 IP 的 http 条目 | 正常 |

#### 同步接口的认证策略(重要)

- `/api/sync/receive`(机器间**写入**)→ 需要 `X-Sync-Key` 头(同步 agent 必须带)
- `/api/sync/status`、`/api/sync/agent-status`(网页 dashboard **读取**)→ 改为 `@login_required`(登录即可)
  - 这样设计是因为网页 dashboard(`static/js/dashboard.js` 的同步在线指示)会调用 `agent-status`,它走 session cookie,无法带 sync key。

### 性能优化

| 优化点 | 文件 | 效果(实测) |
|---|---|---|
| `maxicom_dashboard_api` 站点层级 | `core/views.py` | 用 annotate+prefetch,查询数从 ~123 降至 20(站点部分 111→2,常数) |
| `announcement_unacked_api` 用户循环 | `core/views.py` | select_related 预取 profile,查询数从 52 降至 1 |
| `ZoneSerializer` 列表 | `core/api.py` | Prefetch 待审批需求,查询数从 ~40 降至 2 |
| `WorkReport.date` 索引 | `core/models.py` + migration | 按日期过滤的查询(报表/dashboard/导出)大幅加速 |
| `MaxicomRuntime (site,timestamp)` 复合索引 | `core/models.py` + migration | 灌溉 dashboard/PDF/Excel 加速 |

### 顺带修复的潜在 bug

- `core/views.py` 的 `_user_display_name`:反向 OneToOne 关系在 profile 不存在时抛 `RelatedObjectDoesNotExist`(不是 AttributeError),原 `getattr(user, attr, None)` 的默认值不生效,会导致异常。已加 try/except 保护。

---

## 五、上线后验证清单

拉取并重启后,建议快速验证以下功能正常:

```bash
# 1. 服务正常启动
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/login/  # 应为 200

# 2. 登录后访问关键页面(用浏览器或带 session 的请求)
#    - 首页 dashboard(/)
#    - 数据报表(/stats/)
#    - 工单列表(/work-reports/)
#    - 灌溉监控(/irrigation/)
#    - 待确认备注(/remarks/)

# 3. 确认同步状态指示正常(dashboard 上的「同步代理」灯)
#    - 调用 GET /api/sync/agent-status(登录态)应返回 200

# 4. 确认 Maxicom 数据仍在同步
#    - 等几分钟,看 /api/sync/status 的 counts 是否增长
```

---

## 六、回滚说明

如果上线后出现严重问题需要回滚:

```bash
git revert <本次提交的commit hash>   # 或 git reset 到上个版本
# 回滚 migration(可选,索引回滚安全):
python manage.py migrate core 0066
# 重启服务
```

> ⚠️ 回滚后,如果之前轮换了 `SECRET_KEY`,保留新值即可(不影响回滚)。

---

## 七、本次提交涉及的文件清单

```
新增:
  internal_server/core/upload_security.py          # 文件上传校验工具
  internal_server/core/migrations/0067_*.py        # 索引 migration
  SECURITY_AUDIT_FIXES.md                           # 本文档

修改:
  internal_server/config/settings.py               # SECRET_KEY/Cookie/SSL/HOSTS/CSRF
  internal_server/config/urls.py                   # media 加 login_required
  internal_server/core/authentication.py           # 移除 token 后门
  internal_server/core/sync_views.py               # sync key + 状态接口认证
  internal_server/core/views.py                    # N+1修复/重定向校验/上传校验/remarks登录
  internal_server/core/api.py                      # ZoneSerializer N+1修复 + 上传校验
  internal_server/core/ai_views.py                 # thread_id 正则校验
  internal_server/core/workorder_tree_views.py     # 上传校验
  internal_server/core/models.py                   # 数据库索引
  healthcheck.sh                                   # gunicorn 加固
```

---

**如有疑问,核心就三件事**:设置 `SECRET_KEY` 和 `SYNC_API_KEY` 环境变量、跑 `python manage.py migrate core`、确认隧道指向 `127.0.0.1`。其余都是自动生效的代码级安全加固。
