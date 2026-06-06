# outlook-cli

[![CI](https://github.com/fatecannotbealtered/outlook-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/fatecannotbealtered/outlook-cli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![npm version](https://img.shields.io/npm/v/@fatecannotbealtered-/outlook-cli.svg)](https://www.npmjs.com/package/@fatecannotbealtered-/outlook-cli)

[English](README.md) | 中文

Outlook Exchange 命令行工具，面向人类和 AI Agent。

从终端管理邮件、日历、文件夹、规则和联系人。专为自动化设计，支持扁平 JSON 输出、权限控制和发送安全机制。

[特性](#特性) · [安装](#安装) · [命令总览](#命令总览) · [安全设计](#安全设计) · [项目结构](#项目结构) · [贡献](#贡献)

## 免责声明

本项目仅供**个人学习、研究和日常生产力**使用，不提供 SLA 或商业支持。如在工作中使用，请遵守组织相关规定。软件按"原样"提供，不作任何明示或暗示的保证。

## 特性

- **50 个原子命令**：邮件、日历、文件夹、规则、工具、配置
- **双模式输出**：`--json` 机器可读，默认人类友好
- **权限系统**：read-only（默认）→ write → full
- **发送安全**：send/reply/forward 必须加 `--preview` 或 `--send`
- **只软删除**：所有删除进回收站，无永久删除
- **审计日志**：JSONL 格式，按月轮转
- **单文件二进制**：PyInstaller 打包，无需 Python 运行时
- **npm 分发**：`npm install -g @fatecannotbealtered-/outlook-cli`
- **内置更新**：通过 dry-run/confirm 安全检查和更新 CLI

## 安装

将下面整段复制发给您的 Agent（或自行执行）：

```bash
# 请帮我安装 outlook-cli，并记住以后操作 Outlook/Exchange 都使用 outlook-cli（查询时加 --json）。
# 安装 CLI
npm install -g @fatecannotbealtered-/outlook-cli

# 安装 CLI Skill（必需）— 复制到你支持的 skills 目录下
npx skills add fatecannotbealtered/outlook-cli -y -g

# 配置并验证
outlook-cli setup login
outlook-cli setup doctor --json

# 检查 CLI 更新
outlook-cli update --check
```

### 手动安装（开发用）

```bash
git clone https://github.com/fatecannotbealtered/outlook-cli.git
cd outlook-cli
pip install -e .
```

## 快速开始

```bash
outlook-cli mail list --json
outlook-cli cal list --days 7 --json
outlook-cli tools contacts --query "张三" --json
```

## 命令总览

### `setup` — 配置管理

| 命令 | 说明 |
|------|------|
| `setup login` | 交互式配置凭据 |
| `setup status` | 查看配置状态 |
| `setup doctor` | 测试 Exchange 连接 |

### `update` — 自更新

| 命令 | 说明 |
|------|------|
| `update --check` | 检查最新可用 CLI 版本 |
| `update --dry-run` | 预览将执行的包管理器更新命令 |
| `update --confirm <token>` | 执行已确认的更新命令 |

### `mail` — 邮件操作（24 个命令）

| 命令 | 权限 | 说明 |
|------|------|------|
| `mail list` | read-only | 列出邮件 |
| `mail search` | read-only | 搜索邮件 |
| `mail read` | read-only | 阅读邮件全文 |
| `mail stats` | read-only | 邮件统计 |
| `mail thread` | read-only | 会话视图 |
| `mail attachment-summary` | read-only | 附件概览 |
| `mail export` | read-only | 导出为 .eml |
| `mail download-attachment` | read-only | 下载附件 |
| `mail move` | write | 移动邮件 |
| `mail mark` | write | 标记已读/未读 |
| `mail flag` | write | 旗标/完成 |
| `mail categorize` | write | 分类标签 |
| `mail restore` | write | 从回收站恢复 |
| `mail batch` | write | 批量操作 |
| `mail delete` | write | 软删除（进回收站） |
| `mail send` | full | 发送邮件（需 `--preview`/`--send`） |
| `mail reply` | full | 回复发件人 |
| `mail reply-all` | full | 回复全部 |
| `mail forward` | full | 转发邮件 |
| `mail drafts` | read-only | 列出草稿 |
| `mail draft-read` | read-only | 阅读草稿内容 |
| `mail draft-edit` | write | 编辑草稿 |
| `mail draft-send` | full | 发送草稿 |
| `mail draft-delete` | write | 删除草稿 |

### `cal` — 日历（4 个命令）

| 命令 | 权限 | 说明 |
|------|------|------|
| `cal list` | read-only | 列出日程 |
| `cal create` | write | 创建日程 |
| `cal update` | write | 修改日程 |
| `cal delete` | write | 删除日程 |

### `folders` — 文件夹管理（6 个命令）

| 命令 | 权限 | 说明 |
|------|------|------|
| `folders list` | read-only | 列出文件夹 |
| `folders create` | write | 创建文件夹 |
| `folders rename` | write | 重命名 |
| `folders move` | write | 移动文件夹 |
| `folders empty` | write | 清空文件夹 |
| `folders delete` | write | 删除文件夹 |

### `rules` — 收件箱规则（5 个命令）

| 命令 | 权限 | 说明 |
|------|------|------|
| `rules list` | read-only | 列出规则 |
| `rules create` | write | 创建规则 |
| `rules update` | write | 修改规则 |
| `rules delete` | write | 删除规则 |
| `rules toggle` | write | 启用/禁用规则 |

### `tools` — 工具（8 个命令）

| 命令 | 权限 | 说明 |
|------|------|------|
| `tools contacts` | read-only | 搜索通讯录 |
| `tools free-busy` | read-only | 查询空闲/忙碌 |
| `tools rooms` | read-only | 列出会议室 |
| `tools rooms-free-busy` | read-only | 查询会议室空闲 |
| `tools oof get` | read-only | 查看自动回复设置 |
| `tools oof set` | write | 开启自动回复 |
| `tools oof disable` | write | 关闭自动回复 |
| `tools respond` | write | 响应会议邀请 |

## 全局标志

| 标志 | 说明 |
|------|------|
| `--json` | JSON 输出（机器可读） |
| `--quiet` | 抑制非错误输出 |
| `--dry-run` | 预览写操作 |
| `--account EMAIL` | 共享邮箱地址（委托访问） |
| `--version` | 显示版本 |

## 权限系统

默认权限为 `read-only`。要启用写/发送操作，编辑 `~/.outlook-cli/config.json`：

```json
{
  "email": "user@company.com",
  "password": "...",
  "permissions": {
    "mode": "full"
  }
}
```

**AI Agent 无法通过程序修改此文件** — CLI 不提供修改权限的命令，只能由人类手动编辑配置文件。

## 发送安全

发送类命令（`send`、`reply`、`reply-all`、`forward`、`draft-send`）必须显式添加安全标志：

```bash
# 预览（不发送）
outlook-cli mail send --to "a@b.com" --subject "测试" --body "你好" --preview

# 确认发送
outlook-cli mail send --to "a@b.com" --subject "测试" --body "你好" --send

# 不加标志：报错
outlook-cli mail send --to "a@b.com" --subject "测试" --body "你好"
# 错误：发送类命令需要 --preview 或 --send
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `OUTLOOK_EMAIL` | 覆盖邮箱 |
| `OUTLOOK_PASSWORD` | 覆盖密码 |
| `OUTLOOK_SERVER` | 覆盖 Exchange 服务器 |
| `OUTLOOK_TIMEZONE` | 覆盖时区 |
| `OUTLOOK_PERMISSIONS` | 覆盖权限模式 |
| `OUTLOOK_SHARED_MAILBOX` | 共享邮箱地址（委托访问） |
| `OUTLOOK_NO_AUDIT` | 设为 `1` 禁用审计日志 |
| `OUTLOOK_AUDIT_RETENTION_MONTHS` | 审计日志保留月数（默认 3） |
| `NO_COLOR` | 禁用 ANSI 颜色 |

## 错误码

| 代码 | 退出码 | 含义 |
|------|--------|------|
| `CONFIG_ERROR` | 3 | 未配置 |
| `AUTH_REQUIRED` | 3 | 凭据错误 |
| `FORBIDDEN` | 5 | 权限不足 |
| `NOT_FOUND` | 4 | 资源未找到 |
| `VALIDATION_ERROR` | 2 | 参数错误 |
| `SERVER_ERROR` | 7 | 服务器错误 |
| `NETWORK_ERROR` | 7 | 连接失败 |

## JSON 输出

所有命令支持 `--json` 输出机器可读格式，默认**扁平、省 token**（适合 AI Agent）：

```bash
# 扁平 JSON — 字段精简，token 成本低
outlook-cli mail list --limit 5 --json
outlook-cli mail search --sender "boss@company.com" --json

# 管道友好（抑制非 JSON 输出）
outlook-cli mail list --json --quiet

# 预览写操作，不实际执行
outlook-cli mail delete --id "abc123" --dry-run --json
```

错误响应包含机器可读的错误码和可操作的提示：

```json
{
  "error": "邮件未找到: abc123",
  "errorCode": "NOT_FOUND",
  "hint": "确认资源 ID 是否正确（来自 list/search 结果）"
}
```

设置 `NO_COLOR=1` 禁用彩色输出（适用于 CI/CD）。

## 配置文件

凭据存储在 `~/.outlook-cli/config.json`（权限 0600）：

```json
{
  "email": "user@company.com",
  "password": "密码或应用密码",
  "server": "",
  "timezone": "Asia/Shanghai",
  "shared_mailbox": "",
  "permissions": {
    "mode": "read-only"
  }
}
```

| 字段 | 说明 |
|------|------|
| `email` | Exchange 邮箱地址 |
| `password` | 密码或应用密码（开启 2FA 时） |
| `server` | Exchange 服务器地址（空 = 自动发现） |
| `timezone` | 日历操作时区（默认 `Asia/Shanghai`） |
| `shared_mailbox` | 共享邮箱地址，委托访问（可选） |
| `permissions.mode` | 权限等级：`read-only` / `write` / `full` |

## 常见问题

| 问题 | 解决方案 |
|------|---------|
| 未找到配置 | 运行 `outlook-cli setup login` 或设置 `OUTLOOK_EMAIL` 和 `OUTLOOK_PASSWORD` 环境变量 |
| 认证失败 | 检查凭据；开启 2FA 时使用应用密码 |
| 权限不足 | 检查 `~/.outlook-cli/config.json` 中的 `permissions.mode` |
| 资源未找到 | 从 `list`/`search` 结果中确认 ID |
| 自动发现失败 | 设置 `OUTLOOK_SERVER` 环境变量或配置文件中的 `server` 字段 |
| 连接超时 | 检查网络和 Exchange 服务器可用性 |
| 发送被拒绝 | 在发送命令中添加 `--preview` 或 `--send` 标志 |

## 安全设计

> **⚠️ 警告：AI Agent 操作邮箱的风险**
>
> 为 AI Agent 开启 `write` 或 `full` 权限，意味着将**真实世界的后果**交给程序决策，这与其他 CLI 工具有本质区别：
>
> - **邮件不可撤回** — 一旦发出，无法召回。误配置或产生幻觉的 Agent 可能向错误收件人发送邮件、泄露机密信息，或造成声誉损失。
> - **删除影响线上数据** — 虽然删除进回收站，但批量操作生产邮箱可能在恢复前已干扰正常工作流。
> - **规则和自动回复影响所有来信** — 一条错误规则或自动回复可能在数天内静默误路由或自动回复邮件，直到有人发现。
>
> **建议：**
> - 保持默认 `read-only` 权限，除非确实需要写入/发送能力
> - 对 AI Agent：默认使用 `read-only`，仅在特定可信工作流中提升到 `write`
> - **永远不要为无人值守的 AI Agent 授予 `full` 权限** — 发送邮件前必须有人类审核
> - 使用 `--preview` 预览 Agent 的意图，确认后再 `--send`
> - 使用 `--dry-run` 测试写操作，不实际执行
> - 定期检查 `~/.outlook-cli/audit/` 日志，发现异常操作
>
> 权限系统的存在是为了保护你。修改权限是一个刻意的、仅限人类的操作 — 请像对待共享邮箱密码一样谨慎。

**三级权限系统：**

| 等级 | 范围 | 示例命令 |
|------|------|---------|
| `read-only`（默认） | 只读操作 | list, search, read, contacts, free-busy, oof get |
| `write` | + 数据修改 | move, delete, mark, cal create, folders CRUD, rules CRUD |
| `full` | + 发送/回复/转发 | send, reply, reply-all, forward, draft-send |

**运行机制：**
- 权限存储在 `~/.outlook-cli/config.json`（`permissions.mode` 字段）
- **CLI 不提供修改权限的命令** — 只能由人类手动编辑配置文件
- AI Agent 无法通过程序提升权限
- 环境变量 `OUTLOOK_PERMISSIONS` 可覆盖（适用于 CI）

**发送安全（不可逆操作）：**
- 发送类命令必须显式加 `--preview` 或 `--send` 标志
- 不加标志：命令**被拒绝**，返回错误
- `--preview`：输出预览内容，**不发送**
- `--send`：真正发送邮件

**只软删除：**
- 所有 `delete` 命令将邮件移至回收站（不提供永久删除）
- 可通过 `mail restore` 恢复

**凭据安全：**
- 凭据存储在 `~/.outlook-cli/config.json`，权限 `0600`（仅用户可读）
- 配置目录权限 `0700`
- `setup login` 输入密码时隐藏显示
- 敏感参数（`--password`、`--token`）从审计日志中剥离
- 凭据不会被记录或传输给第三方

**审计日志：**
- 每次写命令自动记录到 `~/.outlook-cli/audit/`（JSONL 格式）
- 按月轮转，可配置保留期（默认 3 个月）
- 设置 `OUTLOOK_NO_AUDIT=1` 可禁用

> 漏洞报告请见 [SECURITY.md](SECURITY.md)。

## 审计日志

每次写命令（send、delete、move、create、update 等）自动记录到 `~/.outlook-cli/audit/`（JSONL 格式），每月一个文件。

```bash
# 查看本月审计日志
cat ~/.outlook-cli/audit/audit-2026-05.jsonl

# 每条记录格式：
# {"ts":"2026-05-03T14:22:01+08:00","cmd":"mail delete","args":["mail","delete","--id","abc123"],"exit":0,"ms":450}
```

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `OUTLOOK_NO_AUDIT` | （未设置） | 设为 `1` 禁用审计日志 |
| `OUTLOOK_AUDIT_RETENTION_MONTHS` | `3` | 自动删除 N 个月前的日志（`0` = 永久保留） |

清理在每次写命令时懒执行，无需后台进程或 cron。

## 系统要求

- Exchange Server 2016/2019 或 Microsoft 365（启用 EWS）
- npm 安装：Node.js 16+，无需 Python
- 开发模式：Python 3.10+，exchangelib, click, cryptography

## 项目结构

```
outlook-cli/
├── outlook_cli/                  # Python 包
│   ├── __init__.py               # 版本号
│   ├── main.py                   # Click 入口、全局标志、权限检查
│   ├── config.py                 # 配置管理（~/.outlook-cli/config.json）
│   ├── crypto.py                 # AES-256-GCM 凭据加密（机器绑定）
│   ├── exchange.py               # Exchange EWS 连接与工具函数
│   ├── output.py                 # 双模式输出（JSON / 人类友好）
│   ├── audit.py                  # 写操作审计日志（JSONL）
│   └── commands/
│       ├── setup.py              # login, status, doctor
│       ├── mail.py               # 24 个邮件命令
│       ├── cal.py                # 4 个日历命令
│       ├── folders.py            # 6 个文件夹命令
│       ├── rules.py              # 5 个收件箱规则命令
│       └── tools.py              # 8 个工具命令
├── tests/                        # 单元测试（config, output, audit, crypto, permissions, e2e, integration）
├── scripts/
│   ├── install.js                # npm postinstall（下载二进制）
│   └── run.js                    # npm bin 包装器
├── skills/outlook-cli/
│   └── SKILL.md                  # AI Agent 技能定义
├── .github/workflows/
│   ├── ci.yml                    # 测试矩阵（Python 3.10/3.11/3.12）
│   └── release.yml               # tag 触发构建 + npm 发布
├── build.py                      # PyInstaller 构建脚本
├── setup.py                      # pip 安装（开发用）
├── requirements.txt              # Python 依赖
├── package.json                  # npm 分发
└── .gitignore
```

## 贡献

欢迎贡献！见 [CONTRIBUTING.md](CONTRIBUTING.md)。发布记录：[CHANGELOG.md](CHANGELOG.md)。

## 许可证

MIT © Sean Guo
