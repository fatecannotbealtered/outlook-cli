# 面向 Agent 的 CLI 工具设计规范


本文定义本仓库 CLI 在被 AI Agent 调用时必须遵守的机器契约。目标是让 Agent 能稳定调用、可靠解析、可恢复重试，并避免任何非交互场景下的阻塞或误写。

## 1. 核心铁律

1. stdout 是契约：默认输出单个合法 JSON 文档，禁止混入日志、进度、提示、颜色控制符。
2. stderr 是旁路：进度、警告、调试、错误说明全部写 stderr。
3. 机器优先：默认 `--format json`；`text` 仅供人读；`raw` 仅用于裸字节、日志、diff 等原样透传。
4. 非交互安全：写操作不得等待键盘输入，必须使用 `--dry-run` + `--confirm <token>`。
5. 确定性：相同输入产生相同结构输出；字段名、字段顺序、schema 版本保持稳定。
6. 最小惊扰：查询不改变状态；写操作在缺少有效 confirm token 时必须失败而不是继续执行。
7. 可恢复：错误码、exit code、`retryable` 必须足够稳定，让 Agent 能决定是否重试、回退或请求用户介入。

## 2. 全局参数

| 参数                       | 说明                             |
|--------------------------|--------------------------------|
| `--format json/text/raw` | 输出格式，默认 `json`                 |
| `--json`                 | `--format json` 的兼容别名，不推荐新调用使用 |
| `--fields <a,b,c>`       | 仅返回指定字段，降低 token（查询命令）         |
| `--compact`              | 紧凑 JSON 输出，去除冗余空白（查询命令）        |
| `--dry-run`              | 模拟写操作，返回变更预览与 `confirm_token`  |
| `--confirm <token>`      | 携带 dry-run 返回的 token 真正执行写操作   |
| `--quiet`                | 抑制 stderr 上的进度/提示，不抑制错误        |

`update` 是**单命令，不是带确认门禁的写操作**（见 §14）：裸 `update` 一次调用完成整个自更新。它可按工具增加 `--target-version`、`--channel` 等参数，并保留 `--check`、`--dry-run` 作为**可选只读**标志，但**不接受 `--confirm <token>`**——自更新豁免 §7 写门禁。

格式职责：

- `json`：结构化机器输出，默认格式，也是唯一推荐给 Agent 的格式。
- `text`：人类可读，可以变化，禁止程序解析。
- `raw`：未包装 bytes / log / diff，原样透传，不使用 JSON envelope。

## 3. 统一输出 Envelope

成功与失败使用同形结构。Agent 只需要先判断 `ok`。

成功：

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {},
  "meta": {
    "duration_ms": 0
  }
}
```

失败：

```json
{
  "ok": false,
  "schema_version": "1.0",
  "error": {
    "code": "E_NOT_FOUND",
    "message": "human readable message",
    "details": {},
    "retryable": false
  },
  "meta": {
    "duration_ms": 0
  }
}
```

约定：

- 所有 JSON 响应必须包含 `ok` 与 `schema_version`。
- `data` 始终是命令的业务载荷；不要把业务字段提升到 envelope 顶层。
- `error.code` 使用稳定的语义化枚举，统一以 `E_` 开头。
- `error.message` 给人读，Agent 不应解析。
- `error.details` 放结构化上下文，必须脱敏。
- `error.retryable` 决定 Agent 是否可以自动退避重试。
- `meta.duration_ms` 记录命令执行耗时。`meta` 在每个响应（成功与失败）里都要输出，
  不要标 `omitempty`——`duration_ms: 0` 是合法值，agent 应当总能读到。
- `meta.notices[]`（可选）MAY 携带环境型运营通知——当前即「有可用更新」通知——
  **只从本地缓存读取**，绝不发起网络。每条通知带 `severity`（`info` | `warning`）。
  无内容可报时省略该字段。详见 §14。
- 破坏性 schema 变更必须升级 `schema_version` 主版本。

### 3.1 机器可读契约（`contract.json`）—— 单一真源、强制对齐

§3/§6/§11 的散文有一个机器可读的孪生体：**`contract/contract.json`**，**只**在本模板仓维护，是全体工具共享字段的单一真源。它编码了信封键集、`E_*` ↔ 退出码 ↔ `retryable` 表、自描述必含键、命名规约、分页/批量形状以及 `_untrusted` 键。

- **单源、副本、零漂移。** 工具不手写这些。它把 `contract.json`（与 `.agent` 规范）按 `.agent/SPEC_VERSION` 里的 tag 钉住并 vendor 一份副本，用 `scripts/gen-contract.js` 从中生成各语言模块（`contract_gen.{go,py}`）；一个失败关闭的 CI 守卫（`scripts/check-spec.js`）保证副本与 `template@<pin>` 逐字节一致、且生成模块与 `contract.json` 同步。改契约只发生在模板；工具升 pin 并跑 `scripts/sync-spec.js`。
- **核心冻结；功能扩展，绝不重定义。** `error_codes.core` 在每个工具里完全一致（正是这点让退出码/retryable 行为可移植）。工具独有的错误码放进 `contract-ext.json` 并受校验：ext 码必须是 `E_*`、必须声明 `{exit, retryable}`、不得覆盖 core 码，退出码 `9` 保留给 human-action 码（`E_HUMAN_REQUIRED`、`E_2FA_REQUIRED`）。这就是契约既统一、又支持独有字段的方式。
- **强制力分级。** 信封键、错误码表、`meta` 键、`schema_version` 值 **精确** 匹配。自描述块（`reference` / `context` / `doctor` / `changelog` / `update`）必须含 **必需** 的 canonical 键，但可追加工具特定键——所以独有功能命令绝不被卡,只锁共享面。每个工具有一个运行时一致性测试,把真实命令输出对照 `contract.json`。

## 4. stdout / stderr 规则

- stdout 在 `json` 模式下只能出现一个 JSON 文档，或在明确流式命令中输出 NDJSON。
- stderr 可输出进度、警告、诊断。
- `json` 模式下出错时，失败 envelope 就是 stdout 上那个唯一的 JSON 文档——Agent 永远解析 stdout 并检查 `ok`，不从 stderr 抓取；stderr 可以补充人类可读的错误说明。
- `--quiet` 只能抑制 stderr 上的非错误信息。
- 不允许在 JSON stdout 前后打印 banner、提示语、进度条或颜色码。
- stdout / stderr 一律 **UTF-8 编码，不带 BOM**，换行用 `\n`，确保跨平台（尤其 Windows）Agent 可稳定解析。

## 5. 流式输出（NDJSON）

大输出、日志流、订阅流、批量逐项结果使用 NDJSON。每行必须是独立合法 JSON，便于流式消费、降内存、可中断：

```jsonl
{"ok":true,"schema_version":"1.0","type":"item","data":{}}
{"ok":true,"schema_version":"1.0","type":"item","data":{}}
{"ok":true,"schema_version":"1.0","type":"summary","data":{"count":2}}
```

约定：

- 普通查询默认使用单 JSON envelope。
- 只有命令语义明确是 log / stream / subscribe / 批量流式输出时才使用 NDJSON。
- NDJSON 行必须包含 `ok`、`schema_version`、`type`。
- 结束行建议使用 `type: "summary"`。
- 真正的二进制或纯文本透传走 `--format raw`，不要包成巨型单 JSON。

## 6. Exit Code 语义表

| Code | 含义                 | Agent 行为               |
|------|--------------------|------------------------|
| 0    | 成功                 | 继续                     |
| 1    | 通用错误               | 读取 error envelope 判断   |
| 2    | 参数/用法错误            | 不重试，修正参数               |
| 3    | 资源不存在              | 不重试                    |
| 4    | 权限/认证/配置失败         | 不重试，提示凭证或权限            |
| 5    | 需确认但缺少 token       | 走 dry-run 获取 token 后重试 |
| 6    | 前置条件冲突或 token 失效   | 重新读取状态后重试              |
| 7    | 可重试瞬时错误（网络/限流/服务端） | 退避后重试                  |
| 8    | 超时                 | 退避后重试                  |
| 9    | 需人工介入（见 §16.3，可选） | 转述给用户，待其完成后跑 `resume`  |

错误码与 exit code 必须一致：

- `E_USAGE` / `E_VALIDATION` -> 2
- `E_NOT_FOUND` -> 3
- `E_AUTH` / `E_FORBIDDEN` / `E_CONFIG` -> 4
- `E_CONFIRMATION_REQUIRED` -> 5
- `E_CONFLICT` -> 6
- `E_NETWORK` / `E_RATE_LIMITED` / `E_SERVER` -> 7
- `E_TIMEOUT` -> 8
- `E_INTEGRITY` -> 1（发布完整性失败：签名缺失/无效或 checksum 不符；**非重试**，见 §14）
- `E_IO` -> 1（本地文件系统失败：磁盘满、文件被占用、写入不全；非重试，需修环境；见 §14 update 替换阶段）
- `E_INTERRUPTED` -> 130（被信号/用户取消，SIGINT = 128+2；可重试——分阶段执行不会留下半截状态，见 §14）
- `E_HUMAN_REQUIRED` -> 9（可选，仅启用 §16.3 时）

当错误来自上游 HTTP 调用时，按状态码映射到错误码，让 agent 能从 `error.code` +
`retryable` 区分失败类型——不要把所有 4xx 都塌缩成 `E_NETWORK`：

- `401` -> `E_AUTH`
- `403` -> `E_FORBIDDEN`
- `404` -> `E_NOT_FOUND`
- `408` -> `E_TIMEOUT`（可重试）
- `409` -> `E_CONFLICT`
- `429` -> `E_RATE_LIMITED`（可重试）
- `5xx` -> `E_SERVER`（可重试）
- 连接拒绝 / DNS / 重置 -> `E_NETWORK`（可重试）

优先按上游的错误类型/状态码映射，不要靠匹配人类可读的 message 文本（子串匹配会把仅仅
包含「not found」等字样的消息误判）。把这套映射收敛到**一个**函数里，避免 output
层与 command 层的 status->code->exit 契约漂移。声明了但运行时不可达的错误码应标注为
保留，免得 agent 为不会发生的分支做规划。

## 7. 写操作流程（dry-run -> confirm）

写命令第一步必须支持 `--dry-run`，返回预览与 token：

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "preview": {
      "changes": [
        {
          "action": "delete",
          "resource": "mail",
          "id": "123",
          "before": {},
          "after": null
        }
      ]
    },
    "confirm_token": "ct_9f2a...",
    "expires_at": "2026-06-05T12:00:00Z"
  },
  "meta": {
    "duration_ms": 0
  }
}
```

第二步携带 token 执行：

```bash
tool resource delete --id 123 --confirm ct_9f2a...
```

confirm token 约定：

- token 必须绑定操作内容哈希，包括命令路径、参数、目标资源 ID、调用账号、权限上下文。
- 哈希必须用机器本地密钥做 HMAC（如 `~/.<tool>/confirm.secret`，首次使用时生成，权限 `0600`），使 token 无法通过重算公开哈希凭空铸造——它只能来自同一台机器上一次真实的 `--dry-run`。
- 能获取资源版本时，也应绑定资源版本、etag、changekey 或 updated_at，防止状态漂移。
- token 必须有过期时间，`expires_at` 使用 ISO 8601 UTC。
- token 过期、操作参数变化、目标状态变化时，执行命令返回 `E_CONFLICT`，exit code 6。
- 缺少 token 时返回 `E_CONFIRMATION_REQUIRED`，exit code 5。
- dry-run 不得产生外部副作用，但可以读取状态用于构造 preview。

## 8. 查询、分页与字段选择

查询命令默认支持：

- `--fields <a,b,c>`：只返回指定字段，支持 dotted path 时需在 reference 中声明。
- `--compact`：压缩 JSON 空白。
- `--limit`：限制返回条数。
- `--cursor` 或 `--offset`：分页游标或偏移。

分页返回建议：

```json
{
  "items": [],
  "count": 0,
  "next_cursor": null,
  "has_more": false
}
```

对基于 offset 的上游，回显 `offset` 并返回显式的 `next_offset`（下一页要传的值，
仅在 `has_more` 为 true 时出现），让 agent 确定性翻页，而不必自己从 `offset + count`
推导：

```json
{
  "items": [],
  "count": 0,
  "offset": 0,
  "next_offset": 20,
  "has_more": true
}
```

当列表被静默截断（例如自动翻页上限）时，要输出 `truncated: true`，而不是返回一个看起来
完整、实则被截短的列表。

约定：

- 所有 ID 使用字符串，即使底层是数字。
- 所有时间使用 ISO 8601 UTC。
- 列表顺序必须稳定；默认排序规则应在 reference 中声明。
- 查询命令不得因为缺少可选过滤条件而进入交互询问。

### 8.1 优先服务端过滤，不做客户端假过滤

能下推到上游的过滤就不要在客户端对已取到的某一页做后过滤。分页之后再过滤会**静默少算**：看起来全，实则只反映取回的那一页。若上游在某个已知版本新增了该过滤能力，就把 flag 映射到它，并记录最低版本（reference + 兼容性文档），而不是自行模拟；万不得已要本地过滤，必须先取全量再过滤，并在输出里说明。

### 8.2 重子资源独立、结构化、可投影

大小无界的子资源（diff、日志、artifact、完整文件正文）是独立命令，绝不内联进列表。廉价、有界的摘要（数量、路径、stats）放在列表里；重负载只为 agent 选中的那一项按需获取。返回时要**结构化**（如 diff 拆成逐文件条目，而不是一坨不透明文本），让 `--fields` 能把它投影成清单（路径 + 行数）而不传输负载。这样 agent 的 token 成本是它自己的选择，而不是被动挨炸——无需专门的截断协议。

### 8.3 多作用域查询走批量契约扇出

当一次读取跨越多个容器（一个组下的项目、整个实例的项目）时，先把作用域解析成一个具体集合，再以客户端循环扇出（§15，B 类）：一个对外命令、恰好一个作用域选择器、结果聚合且每条都标注其来源容器。扫描失败的容器要在结果里报出（如 `projectErrors[]` / `scope` / `projectsScanned`），绝不静默丢弃，且单个失败不得中断其余。跨容器聚合**有界元数据**是安全的；绝不跨整个集合聚合无界子资源（§8.2）。只有对某个主体才有意义的全实例作用域（某人的全部提交）必须绑定该主体，否则 fail-closed，使无界裸扫不可能发生。

## 9. 幂等性与并发安全

写命令应尽量支持幂等语义：

- 创建类命令建议支持 `--request-id` 或 `--idempotency-key`。上游若支持幂等头（如 GitLab 的
  `Idempotency-Key`），应转发该头，并把 key 绑进 confirm scope，使 token 只对该 key 生效。
- 重试同一个 idempotency key 不应重复创建资源。
- 更新/删除类命令应在 dry-run 中记录目标资源版本。
- confirm 时发现版本变化必须返回 `E_CONFLICT`。
- **confirm token 单次消费。** token 一旦被接受执行写操作，就记录其指纹（如
  `~/.<tool>/confirm-consumed.json`，按过期裁剪），任何重放都以 `E_CONFLICT` 拒绝（「token 已用过，
  请重新 `--dry-run`」）。这给 agent 安全重试语义：确认后超时的写不能盲目重发——重放被拒，重新
  `--dry-run` 会显示当前真实状态。对于无资源版本可绑的上游，这是通用的安全重试机制。要在写执行**之前**
  标记消费（中途崩溃宁可保守拒绝重放，也不冒重复风险）。存储失败要优雅降级，绝不阻塞写。
- 批量写操作应返回逐项结果，不要因为单项失败隐藏其他项状态。

批量写结果建议：

```json
{
  "results": [
    {
      "id": "1",
      "ok": true,
      "action": "deleted"
    },
    {
      "id": "2",
      "ok": false,
      "error": {
        "code": "E_NOT_FOUND"
      }
    }
  ],
  "summary": {
    "ok_count": 1,
    "error_count": 1
  }
}
```

## 10. 敏感信息与审计

- password、token、secret、authorization header、cookie 不得出现在 stdout、stderr、error.details、audit log。
- dry-run preview 必须脱敏敏感字段。
- reference/context/doctor 不得泄露明文凭证。
- context 可以报告凭证是否存在，但只能用布尔值或脱敏摘要。
- audit log 应记录命令路径、脱敏参数、调用账号、时间、exit code、duration。
- `--quiet` 不应关闭审计。

## 11. 自描述命令（reference / context / doctor / changelog）

### reference

声明工具能力、命令、参数、输出 schema、错误码、权限等级，供 Agent 先理解能力。

每个命令的 `output_schema` 必须可被机器使用，不能是占位 stub。用一个字符串 label 指向顶层
`schemas` 目录里的条目：`{ "shape": "object"|"array", "fields": [...], "untrusted_fields": [...] }`，
其中字段清单从命令真实返回的数据（flatten 结构 / `*ToMap` 构造）枚举，`untrusted_fields` 列出
攻击者可控的键。每个命令还应带 `examples`：一条可直接运行的调用（写命令展示 `--dry-run` 再
`--confirm` 这一对，危险命令带 `--dangerous`）。应有一个 guard 测试断言每个叶子命令都解析到非空
schema 且至少有一条 example，使 `reference` 不会悄悄退化回 stub。

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "tool": "tool-name",
    "version": "1.0.0",
    "release_readiness": {
      "level": "beta",
      "fcc_required": true,
      "fcc_status": "verified",
      "mock_upstream_required": true,
      "mock_upstream_status": "verified",
      "live_smoke_required_for_stable": true,
      "live_smoke_status": "missing",
      "reason": "Stable requires recorded live smoke/E2E evidence.",
      "required_evidence": [
        "functional_contract_coverage_100",
        "mock_upstream_contract_tests",
        "recorded_live_smoke_for_stable"
      ]
    },
    "commands": [
      {
        "path": "resource delete",
        "type": "write",
        "description": "Delete a resource",
        "params": [
          {
            "name": "id",
            "type": "string",
            "required": true,
            "multiple": false
          }
        ],
        "output_schema": "deleted_resource",
        "examples": [
          "<tool> resource delete <id> --dry-run --compact",
          "<tool> resource delete <id> --confirm <confirm_token> --compact"
        ]
      }
    ],
    "schemas": {
      "deleted_resource": {
        "shape": "object",
        "fields": ["id", "status"],
        "untrusted_fields": []
      }
    },
    "exit_codes": {}
  },
  "meta": {
    "duration_ms": 0
  }
}
```

`release_readiness` 是机器可读的发布门禁字段。每个 AI 原生 CLI 的
`reference` 都必须包含：

- `level`：`stable`、`beta` 或 `unpublishable`。
- `stable`：FCC 达到 100%；mock upstream / contract tests 覆盖外部行为；
  且该 release candidate 至少有一次可追溯的真实环境 smoke/E2E 记录。
- `beta`：FCC 达到 100%，mock upstream / contract tests 完整，但缺少真实
  smoke/E2E 记录，或项目明确声明暂不具备真实 E2E 条件。
- `unpublishable`：任一公开行为缺少命令级测试，或 mock upstream / contract
  tests 只覆盖 happy path，未覆盖失败、鉴权、分页、空结果、限流等行为。
- `fcc_status`、`mock_upstream_status`、`live_smoke_status` 使用
  `verified`、`missing`、`not_applicable` 或 `unknown`；`stable` 对必需项不得
  使用 `missing` 或 `unknown`。
- `required_evidence[]` 列出 Agent 或发布脚本信任该等级前应检查的证据。

### context

报告当前运行环境、配置、目标、凭证状态。

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "env": "prod",
    "account": "user@example.com",
    "config": {},
    "credentials": {
      "configured": true
    }
  },
  "meta": {
    "duration_ms": 0
  }
}
```

### doctor

环境与风险体检，每项给出可执行修复建议。

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "checks": [
      {
        "check": "auth",
        "status": "pass",
        "fix": null
      },
      {
        "check": "network",
        "status": "fail",
        "fix": "set HTTP_PROXY or check VPN"
      },
      {
        "check": "release_readiness",
        "status": "warn",
        "fix": "record live smoke/E2E evidence before declaring stable"
      }
    ]
  },
  "meta": {
    "duration_ms": 0
  }
}
```

`doctor` 必须包含 `check: "release_readiness"`，并与 `reference` 报告同一个
发布等级。`stable` 使用 `pass`，有意声明的 `beta` 使用 `warn`，
`unpublishable` 或自称 `stable` 但证据缺失时使用 `fail`。非 `pass` 状态应给出
可执行的 `fix`。

### changelog

报告**版本之间发生了什么变化**，让自更新后的 Agent 能补齐认知，而不是继续用旧套路。这是 `reference`（描述当前能力）在时间维度上的补充。

```bash
tool changelog                    # 全部版本变更
tool changelog --since 1.0.3      # 只返回比 1.0.3 新的版本
```

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "current_version": "1.1.0",
    "since": "1.0.3",
    "entries": [
      {
        "version": "1.1.0",
        "date": "2026-06-07",
        "changes": {
          "added": [
            "..."
          ],
          "changed": [
            "..."
          ],
          "fixed": []
        }
      }
    ]
  },
  "meta": {
    "duration_ms": 0
  }
}
```

约定：

- **单一真相源**：`changelog` 输出从 `CHANGELOG.md` 派生（构建时按 `## [version]` 段落嵌入二进制），不另维护数据。与 release-notes 同源。
- `--since <version>` 只返回严格高于该版本的条目，供「上次见过 X 版本」的 Agent 拉增量。
- 变更分类沿用 Keep a Changelog：`added` / `changed` / `fixed` / `deprecated` / `removed` / `security`。
- 自更新成功后，工具应在结果中提示 Agent 运行 `changelog --since <旧版本>`（见 §14）。

## 12. 命令设计约定

1. 用最短命令完成明确任务，减少组合复杂度。
2. 查询命令默认支持 `--fields` 与 `--compact` 降 token。
3. 写命令必须支持 `--dry-run` 与 `--confirm`。
4. 命名采用 `<noun> <verb>` 或 `<verb> <noun>` 风格，并在全局统一。
5. 不要求 Agent 解析帮助文本；`--help` 给人看，机器能力通过 `reference` 暴露。
6. 所有时间用 ISO 8601 UTC；所有 ID 用字符串。
7. 命令失败时优先返回结构化错误，不输出半截成功 payload。
8. 命令参数应避免二义性；布尔值用 flag，枚举值用有限选项。

## 13. 功能契约覆盖率与发布门禁

功能契约覆盖率（Functional Contract Coverage，FCC）是发布阻断标准：Agent
能依赖的每一个公开行为，都必须有自动化命令级测试覆盖。代码行覆盖率或分支覆盖率是有用的工程指标，但它是辅助指标，不能替代缺失的功能契约测试。

公开功能契约包括以下位置声明的任何行为：

- `README.md` / `README_zh.md`、`SKILL.md` 或 Skill reference 页面；
- `tool reference`、`--help`、`context`、`doctor`、`changelog`、`update` 输出；
- JSON envelope 字段、命令输出 schema、全局参数、错误码、exit code、retryable、stdout/stderr 边界；
- 已记录的配置/环境变量、凭证处理、写操作安全、自更新校验、Skill 同步和 `_untrusted` 安全承诺。

每个公开命令或契约至少覆盖：

- 成功路径；
- 缺失/非法参数；
- 配置缺失、认证缺失或权限失败（适用时）；
- 上游 API 失败、网络失败、限流或超时（适用时）；
- JSON envelope 形状、输出 schema、exit code、stdout/stderr 边界；
- 非交互行为：不提示、不阻塞，写命令使用 `--dry-run` -> `--confirm <token>`；
- 每个影响可观察行为的 bug fix 都必须带回归测试。

`FCC = 100%` 的含义：

- 公开契约中列出的每个命令、参数、输出、错误行为，都映射到至少一个自动化测试，或明确标注为不适用；
- 命令级测试验证 CLI 边界，而不仅仅测试内部 helper；
- 生成代码、版本常量、构建元数据或不可达平台保护分支可以从数字覆盖率中排除，但如果它们是文档化公开行为，就不能从 FCC 中排除；
- 存在已知 FCC 缺口时，不得打发布 tag。
- `fcc_status: "verified"` 必须有机器背书——枚举守卫测试：从 `reference` 实时输出枚举全部叶子命令，逐一断言存在命令级测试调用。状态诚实声明为 `missing` 时守卫跳过；不补测试就把声明翻成 `verified` 会让守卫立刻失败（模板自带该守卫）。

CI 应在每个 PR 上运行单测和命令级测试。数字覆盖率门槛可以按仓库逐步抬升，但发布标准是绝对的：公开功能契约必须被覆盖。

### 发布就绪等级

发布就绪比「测试通过」更严格：

- **Stable**：FCC 达到 100%；mock upstream / contract tests 覆盖成功、
  参数校验、配置/认证/权限失败、上游/网络/限流/超时失败、空结果、分页、输出
  schema、exit code、stdout/stderr 边界；并且该 release candidate 至少有一次
  真实环境 smoke/E2E 记录。
- **Beta**：FCC 达到 100%，mock upstream / contract tests 具备同等行为宽度，
  但缺少真实环境 smoke/E2E 记录，或项目明确声明暂不具备真实 E2E 条件。
- **Unpublishable**：任何公开命令、参数、输出或错误行为缺少命令级测试，或
  mock upstream 测试只覆盖 happy path。

`reference.release_readiness` 和 `doctor.checks[]` 是这道门禁的机器可读出口。
仓库可以选择不发布 `beta` 产物，但没有上述真实证据时不得自称 `stable`。

## 14. 版本与兼容策略

- `schema_version` 表示输出 schema 版本，不等同于工具版本。
- 破坏性 schema 变更升级主版本，例如 `1.x` -> `2.0`。
- 非破坏性新增字段可以保持主版本不变。
- 废弃字段应先保留兼容期，并在 reference 中标记 deprecated。
- 兼容别名可以存在，但不应作为新文档推荐用法。
- Agent 应优先依据 `reference`，而不是 `--help` 或 README。

### 版本协商（工具版本 ↔ Skill 期望）

Skill 是写它那天的能力快照，二进制版本一漂就可能错位：按 v1.1 写的 Skill 碰上 v1.0 二进制，会静默调用不存在的命令。

- 工具必须能报告自身版本：`tool --version` 与 `context.data.version`。
- Skill 在 frontmatter 声明最低兼容版本（见 SKILL-SPEC `requires.min_version`）。
- `doctor` 应有一项检查「当前版本是否满足声明的最低版本」，不满足时给出 `fix`（升级命令），状态 `fail`。

### 自更新与 Skill 同步闭环

带 `self-update` 的工具，更新成功后**必须打通两条更新链**：

1. 二进制或包本身是最新；
2. 内置 Agent Skill 目录也是最新，最终状态等同于运行 `npx skills add <repo> -y -g`。

用户首次安装 Skill 仍使用 `npx skills add ...`；CLI 二进制不能暴露单独的 `install-skill` 命令。但在 update 生命周期中，工具需要负责完整更新：要么同步整个 `skills/<tool>/` 目录，要么在结果中显式返回 `skill_sync_status` 与 `skill_sync_command`，让 Agent 在使用新能力前完成同步。

单命令 update 契约（无叶子子命令、无 confirm token）：

- 裸 `update` 一次调用完成整个更新：解析最新（或 `--target-version`）release、验证完整性、替换二进制/包、再同步 Skill 目录。自更新是单目标、非破坏、自验证的操作，因此**豁免 §7 的 `--dry-run → --confirm <token>` 写门禁**——安全保证来自下面的进程内签名验证，而不是 Agent 对预览的审阅。`update` 没有叶子子命令。
- **按安装方式分派——驱动包管理器执行，而不是只打印命令。**"替换二进制/包"意味着这一次调用要对*每种*安装方式都抵达升级后的终态，而不仅是独立二进制：
  - **独立二进制**（文件归工具自己所有）：下载 → 进程内 Sigstore 验签 → checksum → 原地原子替换；`signature_status: "verified"`。
  - **包管理器管理的安装**（npm / Go / Homebrew——文件归包管理器所有）：工具**不得**原地修改被管理的文件（会让包管理器的元数据失配），也**不得**仅把命令返回给用户去跑。它要**驱动**包管理器——替用户执行安装命令（如 `npm install -g <pkg>@<version>`），再同步 Skill，抵达同样的终态、`status: "updated"`。这条路径的完整性归包管理器自己（registry 完整性/provenance），所以 `signature_status` 为 `not_checked`；新版本在下次调用时生效。安装方式检测必须稳健（别把独立二进制误判为被管理的）；包管理器调用失败时返回错误、`binary_replaced: false` 并附上可手动执行的确切命令。
- `update --check` 是**可选只读**探针：返回当前/目标版本、安装方式、是否有更新、Skill 同步是否可用、checksum/签名材料是否可用。它不改任何东西。
- `update --dry-run` 是同样变更（二进制/包更新、Skill 同步、验证计划）的**可选只读**预览。它**不签发 token**，且绝不是 `update` 的前置必经步骤。
- `update` 幂等：已是最新（或所请求）版本时返回 `ok` + no-op 结果，Agent 可放心反复调用。
- 成功时 `data` 携带 `previous_version`、`current_version`、`signature_verified`、`signature_status`、`skill_sync_status`，以及足够审计的校验元数据。
- 如果二进制/包更新成功但 Skill 同步失败，返回部分成功（`ok: false`、`binary_replaced: true`）并给出 `skill_sync_command`；Agent 在 Skill 同步完成前不得使用新文档能力。

版本通知契约：

- `update --check` 主动检查最新 release，并刷新本地更新通知缓存。
- `doctor` 可以用较短超时主动检查；网络失败本身不得导致 `doctor` 失败。
- `context` 和 `--help` 只读取本地缓存，不得访问远程 registry 或 GitHub。
- 缓存里的通知 MAY 同时挂到**每条命令的 `meta.notices`**，**只从本地缓存读**
  （不联网；代价仅一次本地文件读取）。业务命令只是把缓存通知透出来——绝不主动检查 / 回家。
  缓存无内容可报时省略 `meta.notices`。
- 有可用更新时，通知含 `type: "update_available"`、`severity`、当前/最新版本、安装方式、
  `recommended_command`、已知 release URL、检查时间和机器可读的下一步。它出现在主动检查类命令的
  `data`（`context` / `doctor` / `update --check`），并以只读方式从缓存出现在任意命令的
  `meta.notices`。文本/help 输出可追加一句简短提示。
- **severity 分级**——在检查时由内嵌 CHANGELOG 在「本机版本 → 最新」之间的增量算出，
  并写入缓存，使缓存的 `meta.notices` 自带正确级别：
  - `info`（默认）：例行 patch/minor，增量里无 security 条目。
  - `warning`：自本机版本以来的 changelog 增量含 `security` 条目，**或**最新跨了
    **major** 版本（首位 semver 增大）——即很可能涉及安全或破坏性变更。

release 校验基线：

- **强制签名验证，无跳过路径**：二进制自更新路径必须在进程内验证 `checksums.txt` 的 Sigstore 签名，再用它校验归档 SHA256。签名 bundle 缺失、签名验不过、checksum 不符，一律**失败关闭**，不存在"验不了就放行"的降级。整条链对外返回 `E_INTEGRITY`（exit 1，非重试）——伪造或损坏的发布不该被当成可重试的瞬时错误。
- **验证器内置、不依赖用户环境**：验证在工具二进制内完成（Go 用 `sigstore-go`，Python 冻结二进制内用 `sigstore`），**不外挂 cosign**，不依赖机器上预装任何东西。TUF 信任根从库内嵌的 `root.json` 引导（不是 TOFU 现拉现信）。
- **新版 bundle 格式**：签名侧用 `cosign sign-blob --new-bundle-format` 产出 Sigstore protobuf bundle（`checksums.txt.sigstore.json`），与进程内验证器对齐；旧版 cosign bundle 格式不被接受。
- **身份绑定**：验证端把证书 SAN 绑定到本仓库的 tagged release workflow（`…/release.yml@refs/tags/v*`，锚定 `^…$`）并校验 GitHub OIDC issuer。已知目标 tag 时可绑精确身份，强于正则。
- **跨语言统一**：Go 二进制与 Python 冻结二进制走同一套自更新契约——都是"下载归档 → 进程内验签 → checksum → 替换二进制"，包管理器不参与完整性。
- update 结果携带 `signature_status`（成功即 `verified`；异常一律走 error envelope 中止）与 `signature_verified`（仅当进程内 Sigstore 验证真实执行且成功时为 true）。不能把 checksum 校验伪装成签名校验。

- `update` 成功后，结果 `data` 中返回 `previous_version` 与 `current_version`。
- 同时在结果中提示：`run "changelog --since <previous_version>" to see what changed`。
- Agent 约定：自更新后、继续干活前，先读 `changelog --since <旧版本>`（见 SKILL-SPEC 配方）。

失败与中断契约：

单命令 `update` 按阶段执行——发现 → 下载 → 验签 → 验 checksum → 替换二进制 → 同步 Skill——只有一个原子提交点。让每条失败 message 都诚实的不变式：

- 替换二进制**之前**的一切只动临时目录；这里任何失败或中断都让已装二进制纹丝不动、完全可用（`current_version` 不变、`binary_replaced: false`）。
- 替换本身是原子的。Windows 上正在运行的可执行文件可被 rename 但不可覆写，因此把验好的 `<bin>.new` 落位的方式是：把在用的二进制 rename 到一旁 `<bin>.old`，再把 `<bin>.new` rename 到真实路径——**新二进制当场就位、`binary_replaced: true`，下次调用即运行新版（无需重启）**。被挤掉的 `<bin>.old` 在旧进程仍运行时删不掉，故留在原地、由下次 `update` 清理（并从头重验任何 staged 产物，遗留绝不被信任）。非 Windows 上则把验好的二进制同盘 rename 落位。替换中途崩溃只会留下旧的或新的二进制，绝无半截。
- Skill 同步在替换**之后**执行，且可独立重放。

因此工具永远能确定、也**必须始终报告**它失败后的状态。每个 update 失败信封在 `error.details`（部分成功时在 `data`）携带：`stage`（`discover|download|verify_signature|verify_checksum|replace|skill_sync`）、`current_version`、`binary_replaced`、`skill_sync_status`。

按 **Agent 的下一步动作**分类失败，而不是按原始成因：

| 阶段 | 失败 | code / exit | retryable | 失败后状态 | message 必须说 |
|------|------|-------------|-----------|------------|----------------|
| discover / download | 网络 / 超时 / 限流 | `E_NETWORK` / `E_TIMEOUT` / `E_RATE_LIMITED` → 7,8 | true | 旧版本，无改动 | "瞬时——重跑 `update`，它幂等" |
| verify_signature / verify_checksum | 签名缺失/无效、身份不符、checksum 不符 | `E_INTEGRITY` → 1 | **false** | 旧版本，已拒装 | "完整性失败——不要重试，停下报人" |
| replace | 权限 / 磁盘满 / 文件被占 | `E_FORBIDDEN` / `E_CONFIG` / `E_IO` → 4,1 | false（需修） | 旧版本（原子未提交） | 给出具体修法，再重跑 |
| skill_sync（替换后） | npx 缺失 / 网络 | 部分成功（`ok:false`、`binary_replaced:true`） | true | 二进制新、Skill 旧 | "二进制已到 vX；运行 `<skill_sync_command>`，再 `changelog --since <prev>`" |
| 任意 | 用户/信号中断（SIGINT） | `E_INTERRUPTED` → 130 | true | 见上述阶段不变式 | 实际发生了什么 + 安全的下一步 |

中断（Ctrl-C / SIGTERM）：

- 捕获信号，把当前阶段回退到干净状态，并在退出前**仍向 stdout 吐出终态 JSON 信封**——被中断的 Agent 必须拿到可解析的终态，而不是一个被杀的裸进程。
- 中断时一律清理临时目录；半截下载绝不可被后续运行信任（永远重新下载 + 重新验签）。
- message 取决于被中断的阶段：替换前 → "已取消，无改动，仍在 `<current>`"；原子替换中 → 据实报旧或新；替换后 Skill 同步中 → 部分成功 + `skill_sync_command`。

message 永不可破的三条铁律：

1. 绝不谎报版本：每个终态信封都说明工具现在实际运行的版本。
2. 绝不让 Agent 重试完整性失败：`E_INTEGRITY` 是 `retryable: false`，且措辞上与任何网络失败明确区分——伪造的 release 不是可循环重试的瞬时抖动。
3. 绝不把部分当成功：二进制已换但 Skill 未同步是部分成功 + `skill_sync_command`，不是 `ok: true`。

## 15. 批量操作（Batch operations）

很多写操作的现实工作流需要一次对**一批**对象执行（关一批 issue、群发给一批 openid、对一批实例跑同一条 SQL）。批量命令对 Agent 仍是**一条**命令、**一个** envelope、**一个** confirm token、**一份**聚合结果——绝不是要 Agent 自己驱动的循环。下面的契约无论该批量由上游原生 bulk 端点服务（A 类）还是客户端循环实现（B 类）都完全一致；Agent 不应、也不需要分辨是哪一类。

### 15.1 复数入参

- 批量目标用复数参数：`--ids`、`--symbols`、`--instances`、`--openids` 等。
- 每个复数参数同时接受 **comma-separated**（`--ids 1,2,3`）与 **repeatable**（`--ids 1 --ids 2 --ids 3`）两种写法；二者等价，可混用。
- 单值优雅退化：`--ids 1` 是合法的「批量一个」，与批量多个同形 envelope。已存在单数参数（`--symbol`）的，保留为复数的兼容别名并在 reference 标 deprecated，不维护两条分叉代码路径。
- 执行前对目标去重，并在结果 `items[]` 中保持输入顺序，使 Agent 能确定性地把结果对回输入。
- 空目标列表是用法错误（`E_VALIDATION`，exit 2），不是静默 no-op。

### 15.2 批量的 dry-run 汇总

批量的 `--dry-run` 在任何写之前返回**将对 N 个对象做什么**，并给出一个覆盖整批的 `confirm_token`：

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "preview": {
      "action": "close",
      "total": 3,
      "targets": ["1042", "1043", "1044"],
      "changes": [
        { "action": "close", "resource": "issue", "id": "1042" },
        { "action": "close", "resource": "issue", "id": "1043" },
        { "action": "close", "resource": "issue", "id": "1044" }
      ]
    },
    "confirm_token": "ct_9f2a...",
    "expires_at": "2026-06-15T12:00:00Z"
  },
  "meta": { "duration_ms": 0 }
}
```

- preview 必须说明操作与完整目标集合，让人或 Agent 在确认前审计影响范围（blast radius）。
- token 绑定**整个已解析的目标集合**（外加命令路径、参数、账号、权限上下文，见 §7），增减任一目标即令其失效并返回 `E_CONFLICT`。

### 15.3 单个 confirm token 覆盖整批，且单次消费

- 批量 dry-run 给出的单个 `--confirm <token>` 授权整批；Agent 不逐项确认。
- token **单次消费**，与 §9 完全一致：写执行前记录指纹并标记已消费，任何重放以 `E_CONFLICT` 拒绝（「token 已用过，请重新 `--dry-run`」）。这沿用各仓现有的 confirm 单次消费基础设施——批量不新增任何 token 机制。
- 批量部分失败后，token 仍保持已消费；Agent 重新 `--dry-run`（此时只解析到仍待处理的目标），而不是重放旧 token。

### 15.4 危险批量：`--dangerous` 两步闸门

不可逆或高影响范围的批量——批量 `delete`、MR `merge`、群发 / 广播——在 dry-run → confirm **之上**再加一道闸门：

- 命令必须带 `--dangerous` 调用；不带时即使持有有效 confirm token，命令也以 `E_CONFIRMATION_REQUIRED`（exit 5）失败。
- 这是两步人意闸门：`--dangerous` 声明意图，confirm token 授权具体已解析的那一批。两者缺一不可，任何一个单独都不执行。
- reference 把这些命令标 `dangerous: true`，其 `examples[]` 展示 `--dangerous` 形式。
- 工具可在危险批量上叠加更严格的本地策略（如逐项 confirm、默认 `--continue-on-error false`、夜间仅 dry-run）；此类覆盖必须在 reference 声明，不得暗藏。

### 15.5 逐项聚合结果，不整体回滚

批量结果按项聚合。部分失败**不**回滚已成功的项：

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "items": [
      { "target": "1042", "ok": true },
      { "target": "1043", "ok": true },
      {
        "target": "1044",
        "ok": false,
        "error": { "code": "E_NOT_FOUND", "retryable": false }
      }
    ],
    "summary": { "total": 3, "succeeded": 2, "failed": 1 }
  },
  "meta": { "duration_ms": 0 }
}
```

- 每个 `items[]` 项带 `target`（输入标识——`id`、`symbol`、`instance`……；用自然键，不用数组下标）、`ok`，失败时带 `error`，其 `{ code, retryable }` 分类与顶层 envelope（§6）一致。
- `summary` 始终报告 `{ total, succeeded, failed }`，计数必须与 item 实际数量相等。
- 只要批量执行并产出结果，顶层 `ok` 即为 `true`，即便存在逐项失败；逐项状态在 `items[]` 里。顶层 `ok: false` 仅保留给整批根本无法执行的情况（参数错、鉴权、无目标）。不要因为单项失败而隐藏其他项状态（与 §9 一致）。
- `--continue-on-error` 控制首个失败后是否继续；**默认 `true`**（尽力而为，跑完整批）。设 `--continue-on-error false` 在首个失败处停止——已应用的项保持已应用（不回滚），`summary` 只反映已尝试的项，未尝试的剩余项要报告出来（如 `skipped`），让 Agent 可续跑。危险批量可把默认翻成 `false`，需在 reference 声明。

### 15.6 上游有上限：客户端自动分批

当原生 bulk 端点有单次调用上限时，命令把批量切成多块顺序提交，对 Agent 仍呈现为一条命令：

- 已知上限：Jira `/issue/bulk`、agile `backlog/issue` 与 `sprint/{id}/issue` ≤ 50；微信 openid 批量 ≤ 100，群发 openid 列表按上游上限。命令必须按上限分批，不得把超限批量直接透传让上游 400。
- 分批在契约里不可见：跨所有块仍是一个 envelope、一个 `confirm_token`、一份聚合 `items[]`/`summary`。
- 块级失败映射回受影响的 `items[]`；单块失败不令整条命令失败（受 `--continue-on-error` 约束）。
- 把分批大小收敛到每个工具的一个共享 helper 里，避免共用同一端点的命令间上限漂移。

### 15.7 A/B 两类，对外契约一致

- **A 类**用上游原生 bulk 端点（真服务端批量，上游可能原子）。
- **B 类**因无原生 bulk，客户端对单目标调用做循环。
- 对外契约对两类完全一致：复数入参、dry-run 汇总、单 confirm token、危险闸门、聚合 `items[]`/`summary`、`--continue-on-error`。Agent 无法也无需分辨 A 与 B。
- 原子性**不**是对外契约的一部分。B 类（或被分批的、有上限的 A 类）批量不得宣称上游原子；上游确实非原子或顺序不稳定时，在 output schema / reference 里如实说明，而不是暗示事务语义。

### 15.8 批量命令的自描述

每个批量命令带真实的 `output_schema` 与可运行 `examples[]`（见 §11）：

- schema 声明 `items[]` 形状（`target`、`ok`、`error{code,retryable}`）与 `summary{total,succeeded,failed}` 形状，攻击者可控的键列入 `untrusted_fields`（`_untrusted`）。
- `examples[]` 展示复数入参的 dry-run 再 confirm 这一对；危险批量带 `--dangerous`。
- 这些必须通过 reference 守卫（每个叶子命令非空 schema + 至少一条 example），并像其他公开行为一样计入 FCC（§13）。

## 16. 可选模式（按需启用）

以下三种模式**不是人人必做**：工具用得上就照这里实现，用不上就忽略，零负担。它们让规范随工具复杂度伸缩——简单工具保持轻，复杂工具不必重新发明轮子。每条都标了「何时适用」。

### 16.1 凭证生命周期（令牌会过期时）

**何时适用**：凭证不是静态的，而是会过期 / 需刷新的——OAuth access_token（微信公众号约 2h）、cookie / session（小红书）、临时 STS 凭证等。静态用户名密码的工具跳过本节。

- `context.data.credentials` 除「配没配」外，应报告**有效性与过期信息**（脱敏）：

  ```json
  {
    "credentials": {
      "configured": true,
      "valid": true,
      "expires_at": "2026-06-07T12:00:00Z",
      "refreshable": true
    }
  }
  ```

- 令牌过期且不可自动刷新时，操作返回 `E_AUTH`（exit 4），`details` 指明需重新认证。
- 可自动刷新的工具应**透明刷新**，不让 Agent 操心；刷新失败再降级为 `E_AUTH`。
- `doctor` 增一项 `check: "credentials"`，对临近过期给 `warn` + 续期 `fix`。
- 刷新令牌、secret 一律脱敏，绝不出现在 stdout / stderr / details。

### 16.2 异步任务生命周期（长任务：提交 -> 轮询 -> 取结果）

**何时适用**：操作不能同步返回结果——SQL 异步执行 / 审批（Archery）、批量群发、采集 / 爬取任务、大导出。同步即得结果的命令跳过本节。

- 提交命令立即返回 `job_id` 与状态，不阻塞：

  ```json
  {
    "ok": true,
    "schema_version": "1.0",
    "data": {
      "job_id": "job_abc123",
      "status": "pending",
      "poll": "tool job status --id job_abc123",
      "result": "tool job result --id job_abc123"
    },
    "meta": { "duration_ms": 12 }
  }
  ```

- 状态查询返回稳定枚举：`pending` / `running` / `succeeded` / `failed` / `cancelled`，并带进度（如 `progress`、`eta_seconds`）。
- 结果与状态分开取：`succeeded` 后用 `result` 命令拉数据（大结果走 NDJSON / `--format raw`）。
- `failed` 的结果用标准 error envelope，`retryable` 指明能否重试整个任务。
- 写类长任务的提交仍走 `dry-run → confirm`；confirm 后才落 `job_id`。

### 16.3 人工介入检查点（需要人来扫码 / 验证码 / 审批时）

**何时适用**：流程中途必须由人完成某步——扫码登录 / 验证码（小红书）、审批人放行（Archery）、二次确认等。全自动工具跳过本节。

- 卡在人工步骤时，**不阻塞、不瞎试**，返回专用信号让 Agent 把球踢给用户：

  ```json
  {
    "ok": false,
    "schema_version": "1.0",
    "error": {
      "code": "E_HUMAN_REQUIRED",
      "message": "Scan the QR code to continue",
      "details": { "action": "scan_qr", "resume": "tool login resume --id sess_1", "qr_path": "/tmp/qr.png" },
      "retryable": false
    },
    "meta": { "duration_ms": 30 }
  }
  ```

- `E_HUMAN_REQUIRED` 用 exit code `9`（在既有 0–8 之外新增；不复用 `4`，以区分「凭证错」与「等人动作」）。
- `details.action` 用稳定枚举说明需要人做什么，`details.resume` 给出人工完成后的续跑命令。
- Agent 约定：收到 `E_HUMAN_REQUIRED` → 向用户转述 `message` 与所需动作 → 等用户完成 → 跑 `resume`，不自动重试。

## 17. 设计检查清单

> 标 `（可选）` 的仅当对应可选模式启用时才需勾。

- [ ] 默认 `--format json`
- [ ] stdout 仅含合法 JSON / NDJSON，无污染
- [ ] 日志与进度全部走 stderr
- [ ] 成功/失败同形 envelope，含 `ok` 与 `schema_version`
- [ ] `error` 含语义化 `code`、`details`、`retryable`
- [ ] exit code 分层且与 `retryable` 一致
- [ ] 写命令具备 dry-run / confirm-token 闭环
- [ ] confirm token 绑定操作参数、账号、权限上下文和资源版本
- [ ] 提供 `reference` / `context` / `doctor`
- [ ] 提供 `changelog [--since]`，与 CHANGELOG/release-notes 同源
- [ ] 工具可报告自身版本（`--version` 与 `context.version`）
- [ ] `reference` 报告 `release_readiness`，`doctor` 检查它
- [ ] （含 self-update 时）`update` 是单命令（无叶子子命令、无 confirm token）；`--check` / `--dry-run` 为可选只读
- [ ] （含 self-update 时）release 完整性被校验，签名状态显式返回
- [ ] （含 self-update 时）整个 Skill 目录同步纳入 update 结果
- [ ] （含 self-update 时）更新后回传 previous/current 版本并提示读 changelog
- [ ] （含 self-update 时）每个 update 失败/中断信封携带 `stage` + `current_version` + `binary_replaced` + `skill_sync_status`；`E_INTEGRITY` 非重试；二进制已换但 Skill 未同步是部分成功而非 `ok`
- [ ] （含 self-update 时）捕获 SIGINT/SIGTERM，不留半截状态，且仍吐出终态 JSON 信封
- [ ] 查询命令支持 `fields` / `compact`
- [ ] 列表命令支持分页或明确说明无需分页
- [ ] 批量命令用复数入参（`--ids`/`--symbols`/…），comma-separated 或 repeatable，单值退化
- [ ] 批量 dry-run 汇总完整目标集；单个 confirm token 覆盖整批且单次消费
- [ ] 危险批量（delete / merge / 群发）需 `--dangerous` 两步闸门
- [ ] 批量结果聚合 `items[].{target,ok,error{code,retryable}}` + `summary{total,succeeded,failed}`，不整体回滚，`--continue-on-error` 默认 true
- [ ] 有上限的原生 bulk 由客户端自动分批、对外单条命令；A/B 两类对外契约一致；批量命令带真实 `output_schema` + `examples`
- [ ] README / Skill / reference / help / context / doctor / changelog / update 中声明的公开行为达到 100% 功能契约覆盖率
- [ ] Stable release 有真实环境 smoke/E2E 记录；否则工具声明为 `beta`
- [ ] 所有时间为 ISO 8601 UTC
- [ ] 所有 ID 为字符串
- [ ] 敏感信息全链路脱敏
- [ ] schema 变更有版本与兼容策略
- [ ] stdout/stderr 为 UTF-8 无 BOM
- [ ] （可选·令牌过期）`context`/`doctor` 报告凭证有效性与过期，刷新失败降级 `E_AUTH`
- [ ] （可选·长任务）提交返回 `job_id` + 状态枚举，状态/结果分离
- [ ] （可选·需人工）卡人工步骤返回 `E_HUMAN_REQUIRED`（exit 9）+ `resume`，不自动重试
