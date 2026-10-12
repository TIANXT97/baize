# CLAUDE.md —— 工位机器级 SOP

> 本文件为工位 Windows PC 的机器级 SOP，跨工作区、跨项目生效。
> 项目级 AI Agent 工作指南请见 `AGENTS.md`。

---

## 1. 三节点

| 角色 | 节点 |
|---|---|
| **工位**（编辑+push） | 公司 Win11, `DESKTOP-DTE8QPT / dell` |
| **跳板** | 北京阿里云 VPS `101.200.45.220` |
| **干活** | 家里 fnOS NAS `192.168.31.235` @ 用户 `TIANXT` |

---

## 2. SSH → NAS（`ssh nas`）

```
工位 → Torium SOCKS5 (127.0.0.1:10808) → 阿里云 101.200.45.220 → 反向隧道 → NAS 192.168.31.235
```

- 别名：`~/.ssh/config` 里 Host nas
- ProxyCommand 走 `C:\Users\DELL\ssh-tools\socks5-bridge.ps1`
- 私钥：`~/.ssh/id_ed25519`，公钥头 `AAAAC3z...ID1ihU69sk` 已挂 NAS authorized_keys
- 前置条件：工位那条 `ssh -N -L ... root@101.200.45.220` 反弹进程要活着

**验通一条命令**：
```powershell
ssh nas "hostname"   # 期望: TIANXT
```

---

## 3. Git / GitHub API（工位）

- 协议：`git@github.com:TIANXT97/<repo>.git` 原生 SSH
- 身份：`TIANXT97 <770884786@qq.com>`
- 账号：`TIANXT97`
- 2026-10-11 实测带宽：下行 42 Mbps / 上行 18 Mbps（github.com 的 22 端口走 Azure 骨干，对中国友好，不要走代理）

**gh CLI**：
- 位置：`E:\AI工具\gh\bin\gh.exe`（已加入 user PATH，但非全局）
- 已用 OAuth 登录 TIANXT97 账号（token 存 keyring）
- 现有 scope：`admin:public_key`, `delete_repo`, `gist`, `read:org`, `repo`
- **PowerShell 调用**：`& 'E:\AI工具\gh\bin\gh.exe' <cmd>` 或 `$env:Path += ';E:\AI工具\gh\bin'` 后直接 `gh <cmd>`
- **gh 处理 GitHub API 全事**：列 repo、看 PR/issue、建 repo、跑 Actions、删 repo

**红线**：
- 不贴 token 进 `git remote -v` URL（走 gh CLI 的 OAuth 或 ~/.git-credentials）
- 不 `--force` / `reset --hard` main
- 推 GitHub 永远 SSH

**历史教训**：
- 不要再恢复 `ghproxy.net` URL 重写（2026-10-11 已清除）
- NAS 上 yaoyao-cinema 曾经把 PAT 明文嵌 URL —— 已被夭夭转移到 `~/.git-credentials`（600 权限）

---

## 4. 工作流（能工位做的事）

✅ **工位干**：
- 编辑代码（前端 Vue / 后端 Python）
- 静态语法检查 (`pytest --collect-only` / `npm run type-check`)
- `git add / commit / push`

✅ **NAS 干**（一切真实运行）：
- build / 单测 / 容器重启
- db schema 迁移
- 端到端 curl 验证

❌ **工位不干**：
- docker build / run
- 真实单测（mock db 不是真的）
- vue-tsc build（NAS 跑才有意义）

---

## 5. 部署（**按需模式**）

**推完 git 后**：
- **不用当场 build**。夭夭（NAS 那边的 agent）待命，老板随时说"发一下"，夭夭就 `git pull && docker compose build && up -d && health`。
- 出 bug 时夭夭自己评估、写文档推回 GitHub，工位读文档就知道上下文。

**如果你就是 push 的 agent**，话术降级为：
> 我在工位 push 完了。是否要在 NAS 部署？（默认 **否**，等夭夭或老板 cue）

---

## 6. 排查顺序（出问题先看这）

| 症状 | 排法 |
|---|---|
| `ssh nas` 不动 | 1. `Get-Process ssh` 看反弹进程；2. `Test-NetConnection 101.200.45.220 -Port 22`；3. `ssh -v nas` 看 ProxyCommand |
| `ssh nas` 通但没容器 | 1. `ssh nas 'docker ps'`；2. 看 `docker-compose.yml` |
| `git push` 慢 | 看是 SSH 还是 HTTPS，HTTPS 是慢根因 |
| NAS 行为莫名其妙 | `ssh nas 'docker logs <service> --tail=200'`；99% db schema / env / 没真 build |
| 工位改完没效果 | 99% 没 push / push 但没让 NAS 拉取 |

---

## 7. 工位侧常用命令（docker 永远带服务名）

- `docker ps`
- `docker logs <service> --tail=80 --follow`
- `docker compose up -d <service>` ← **带服务名**
- `docker stats <service> --no-stream`

---

## 8. 机器级记忆库（若想加记忆）

发现新机器级配置/教训 → 写到 `E:\AI工具\claude-run\CLAUDE.md`（直接改本文件）或 MEMORY.md。

---

## 9. 代码审查与文档同步铁律（2026-10-12 新增）

### 9.1 工位 Claude 写完代码后，必须做的事

1. **语法检查**：`python -m py_compile` 全量检查修改过的文件
2. **Git diff 审查**：确保改动合理，无次生缺陷
3. **文档同步**：代码改了，文档必须跟上
   - `docs/CHANGELOG.md` — 记录版本变更
   - `docs/whitepaper.md` — 同步核心机制说明
   - `README.md` — 更新特性描述
   - `config.json` — 在注释里补充说明
4. **Issue 引用**：修复代码必须标注 issue 号（如 `// Issue #1`）
5. **版本标记**：新特性必须标注版本号（如 `// v1.5.3-hotfix`）

### 9.2 开 GitHub issue 的流程

1. **工位全代码走查**：逐行读代码，发现边界隐患
2. **写 ISSUES_FOR_YAOYAO.md**：包含问题定位、代码位置、风险等级、建议方案
3. **用 gh CLI 开 issue**：`gh issue create --repo TIANXT97/baize --title "..." --body "..."`
4. **妖妖审评批准**：妖妖在 issue 里回复"【采纳 · 排入下期加固】"或"【维持现状】"
5. **工位动手修**：按妖妖批准的方案改代码 + 文档
6. **开 PR**：`gh pr create --repo TIANXT97/baize --title "..." --body "..." --base main`

### 9.3 跨会话/跨模型协作

如果其他模型/会话要审核工位 Claude 写的代码，必须提供：
- **项目级 AGENTS.md**（如 `baize-memory/AGENTS.md`）— 代码组织、核心机制、代码风格、测试方式、工作流、审核 checklist、常见陷阱
- **机器级 CLAUDE.md**（本文件）— 三节点分工、SSH/Git/部署规范
- **Git log**：`git log --oneline -10` 查看最近提交
- **Git diff**：`git diff main..HEAD` 查看当前分支改动

### 9.4 常见陷阱记录

- **Step-5 的教训**：不要建议分布式架构（Saga/Milvus/Neo4j），单租户自托管场景 SQLite 足够
- **代码与文档同步**：不要只改代码不改文档，会导致文档与代码不一致
- **Repo 已存在**：开新工作区前先 `gh repo view TIANXT97/<repo>` 确认是否已存在，避免重复创建

---

*Last updated: 2026-10-12.*  
*目的：跨工作区、跨项目，启动就有机器 SOP。*
*项目级 AI Agent 工作指南请见 `AGENTS.md`。*
