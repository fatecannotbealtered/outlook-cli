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

`update` 命令可以按工具增加 `--target-version` 或 `--channel` 等参数，但必须保留统一生命周期参数：`--check`、`--dry-run`、`--confirm <token>`。

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
- `meta.duration_ms` 记录命令执行耗时。
- 破坏性 schema 变更必须升级 `schema_version` 主版本。

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
| 9    | 需人工介入（见 §15.3，可选） | 转述给用户，待其完成后跑 `resume`  |

错误码与 exit code 必须一致：

- `E_USAGE` / `E_VALIDATION` -> 2
- `E_NOT_FOUND` -> 3
- `E_AUTH` / `E_FORBIDDEN` / `E_CONFIG` -> 4
- `E_CONFIRMATION_REQUIRED` -> 5
- `E_CONFLICT` -> 6
- `E_NETWORK` / `E_RATE_LIMITED` / `E_SERVER` -> 7
- `E_TIMEOUT` -> 8
- `E_HUMAN_REQUIRED` -> 9（可选，仅启用 §15.3 时）

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

约定：

- 所有 ID 使用字符串，即使底层是数字。
- 所有时间使用 ISO 8601 UTC。
- 列表顺序必须稳定；默认排序规则应在 reference 中声明。
- 查询命令不得因为缺少可选过滤条件而进入交互询问。

## 9. 幂等性与并发安全

写命令应尽量支持幂等语义：

- 创建类命令建议支持 `--request-id` 或 `--idempotency-key`。
- 重试同一个 idempotency key 不应重复创建资源。
- 更新/删除类命令应在 dry-run 中记录目标资源版本。
- confirm 时发现版本变化必须返回 `E_CONFLICT`。
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
        "output_schema": {}
      }
    ],
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

update 必须遵守的契约：

- `update --check` 只读。返回当前/目标版本、安装方式、是否有二进制/包更新、Skill 同步是否需要或可用、checksum/签名材料是否可用。
- `update --dry-run` 返回完整变更预览：二进制/包更新、Skill 目录同步、checksum/签名校验，以及 `confirm_token`。
- `update --confirm <token>` 执行更新。替换本地文件或运行包管理器前，必须先完成 release 完整性校验。
- 更新成功后，返回 `previous_version`、`current_version`、`skill_sync_status`，以及足够审计的校验元数据。
- 如果二进制/包更新成功但 Skill 同步失败，必须返回非成功或部分成功状态，并给出 `skill_sync_command`；Agent 在 Skill 同步完成前不得使用新文档能力。

版本通知契约：

- `update --check` 主动检查最新 release，并刷新本地更新通知缓存。
- `doctor` 可以用较短超时主动检查；网络失败本身不得导致 `doctor` 失败。
- `context` 和 `--help` 只读取本地缓存，不得访问远程 registry 或 GitHub。
- 有可用更新时，JSON 命令数据中包含 `notices[]`，字段包括
  `type: "update_available"`、当前/最新版本、安装方式、
  `recommended_command`、已知 release URL、检查时间和机器可读的下一步。文本/help 输出可追加一句简短提示。

release 校验基线：

- 按 `checksums.txt` 校验归档/包；checksum 不匹配、缺失 checksum 文件、或缺少当前归档条目，都必须失败关闭。
- 已签名 release 应由 tagged GitHub Actions release workflow 使用 Sigstore/Cosign keyless 模式签署 `checksums.txt`。验证端应绑定到预期仓库 workflow 身份和 GitHub OIDC issuer。
- update 结果携带 `signature_status`（一个短字符串说明发布完整性在哪里被验证：如 `verified`、`not_checked`、`handled_by_npm_installer`、`manual_release_verification_required`）与 `signature_verified`（仅当本地 Sigstore 验证真实执行且成功时为 true）。不能把 checksum 校验伪装成签名校验。

- `update --confirm <token>` 成功后，结果 `data` 中返回 `previous_version` 与 `current_version`。
- 同时在结果中提示：`run "changelog --since <previous_version>" to see what changed`。
- Agent 约定：自更新后、继续干活前，先读 `changelog --since <旧版本>`（见 SKILL-SPEC 配方）。

## 15. 可选模式（按需启用）

以下三种模式**不是人人必做**：工具用得上就照这里实现，用不上就忽略，零负担。它们让规范随工具复杂度伸缩——简单工具保持轻，复杂工具不必重新发明轮子。每条都标了「何时适用」。

### 15.1 凭证生命周期（令牌会过期时）

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

### 15.2 异步任务生命周期（长任务：提交 -> 轮询 -> 取结果）

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

### 15.3 人工介入检查点（需要人来扫码 / 验证码 / 审批时）

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

## 16. 设计检查清单

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
- [ ] （含 self-update 时）实现 `update --check` / `--dry-run` / `--confirm`
- [ ] （含 self-update 时）release 完整性被校验，签名状态显式返回
- [ ] （含 self-update 时）整个 Skill 目录同步纳入 update 结果
- [ ] （含 self-update 时）更新后回传 previous/current 版本并提示读 changelog
- [ ] 查询命令支持 `fields` / `compact`
- [ ] 列表命令支持分页或明确说明无需分页
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
