# Microsoft 365 Workflow 邮件发送

用户管理 → 邮件报表 → 邮件发送设置，选择 SMTP 或 Microsoft 365 Workflow。原 SMTP 配置保留，默认仍为 SMTP。定时发送、手动测试发送和 AI 报表发送共用同一发送服务。

Workflow 使用「When an HTTP request is received」→「Send an email (V2)」。HTTP 请求为 POST JSON，仅包含三个字符串：`t`（收件人，多个以分号分隔）、`s`（主题）、`b`（HTML 正文）。在邮件动作中分别映射 To / Subject / Body；无需配置附件。触发链接必须允许服务器凭链接调用；租户 OAuth 限制的触发器需要额外认证，当前不自动获取租户令牌。

报表继续生成完整 Excel，Workflow 正文逐个列出下载链接。文件存放于媒体目录之外的 private_email_reports；下载需要随机令牌，数据库只保存令牌摘要，7 天后失效。定时邮件任务清理过期文件。报表收件人无需应用账号，可凭邮件里的有效链接下载。

HTTP 2xx 记录为 accepted（已提交 Workflow），不表示邮箱已经投递。失败不自动改走 SMTP，也不自动重试，避免重复邮件。触发 URL 作为秘密保存，不在设置读取接口或网络异常详情中返回。

管理员需在发送设置中粘贴自己的 Workflow 链接。下载站点默认使用当前生产域名，可设置其他 HTTPS 站点。按先前要求不进行浏览器验收或实际邮件发送。

Microsoft references:
- https://learn.microsoft.com/en-us/power-automate/oauth-authentication
- https://learn.microsoft.com/en-us/connectors/office365/


## 可复用发送配置

邮件报表页维护命名配置列表，可保存多套 SMTP、Workflow，并为每条报表独立选择。默认配置仅用于新建报表和 AI 临时发送，不自动替换已有报表的绑定。保存与列表更新均在页内完成。

迁移自动将原 SMTP 和已有 Workflow 分别保留为命名配置，按原来选中的发送方式绑定所有既有报表。SMTP 若原先来自服务器环境，继续沿用环境配置。密码、Workflow 链接仍是只写字段，留空保留；引用中的配置与默认配置受到删除保护。

定时发送与手动测试使用报表绑定的配置；某套配置未完善不会阻止其他报表发送。按用户此前要求，不进行额外测试、界面验收或实际试发。
