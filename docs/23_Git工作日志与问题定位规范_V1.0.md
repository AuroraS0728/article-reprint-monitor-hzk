# Git 工作日志与问题定位规范 V1.0

## 目标

Git 是本项目唯一的代码演化记录。每个可交付增量必须能回答：谁在何时为何修改了什么、影响了哪些文件、通过了哪些真实验证、还遗留哪些风险。提交信息和 GitHub Pull Request 不得出现密码、Token、Cookie、私有 URL、生产配置或个人数据。

## 分支与提交

| 分支 | 用途 | 规则 |
| --- | --- | --- |
| `main` | 已验收、可发布的基线 | 仅接受经审查的合并；不直接开展功能开发。 |
| `develop` | 已通过开发验证的集成分支 | 功能分支完成检查后合并至此。 |
| `feature/<scope>` | 一项可独立审查的功能 | 例如 `feature/phase-05-reports`。 |
| `hotfix/<scope>` | 已发布版本的紧急修复 | 修复后同步回 `develop`。 |

每轮开始前，从 `develop` 创建 `feature/*`；每个功能点或可回滚修复使用独立提交。提交标题采用 `type(scope): summary`，正文必须填写迭代目标、改动、真实验证和未关闭风险。仓库已提供 `.gitmessage` 模板。

常用类型：`feat`、`fix`、`docs`、`test`、`refactor`、`chore`、`security`。

## 开始与结束一轮工作

```powershell
git switch develop
git pull --ff-only origin develop
git switch -c feature/phase-05-reports

# 完成一个可审查的小增量后
git status --short
git add -p
git diff --cached --check
git diff --cached
git commit
```

提交前必须运行与本轮相关的真实检查。Django 变更必须包括 Migration；不允许将未运行的检查写成通过。提交后推送功能分支并创建 Pull Request，PR 模板记录验证和风险。

## 查看工作日志与改动

```powershell
# 项目演化时间线：提交、分支和标签
git log --oneline --decorate --graph --all

# 每次提交改动了哪些文件及增删行数
git log --stat --oneline

# 查看某次提交的完整文件和行级变更
git show <commit-sha>
git show <commit-sha> -- backend/apps/monitoring/services.py

# 当前未提交改动；已暂存改动；两个版本间的行级差异
git diff
git diff --cached
git diff <old-sha> <new-sha>

# 某个分支相对 develop 的文件清单与差异
git diff --name-status develop...HEAD
git diff develop...HEAD
```

建议每次提交前先执行 `git diff --cached`，确认没有误加 `.env`、样本数据、生成物或无关文件。`git status --ignored` 可用于确认敏感文件确实被忽略。

## 使用 git bisect 定位引入问题的提交

仅在已知“最后正常提交”和“首次异常提交”时使用。开始前停止正在修改的工作或先提交/暂存，以避免 checkout 覆盖本地改动。涉及 Migration 时使用测试数据库，不直接对开发业务数据执行回退。

```powershell
# <bad-sha> 为确认异常的版本，<good-sha> 为最后确认正常的版本
git bisect start <bad-sha> <good-sha>

# 在 Git 切换到的每个版本执行同一条可重复验证命令
docker compose exec -T web pytest -q

# 该版本异常：
git bisect bad

# 该版本正常：
git bisect good

# 找到首个问题提交后，恢复原分支
git bisect reset
git show <first-bad-sha>
```

若测试命令可稳定以退出码 `0` 表示正常、非 `0` 表示异常，可自动化：

```powershell
git bisect start <bad-sha> <good-sha>
git bisect run docker compose exec -T web pytest -q
git bisect reset
```

`git bisect` 结果必须记录在修复提交正文和对应 PR 的“Risks / follow-up”中，包含首个异常提交、复现命令和修复验证。

## 发布与回滚

发布前在候选提交上打注释标签，例如 `v1.0.0-rc.1`；仅在完成安全门禁后才创建正式版本标签。发现线上问题时，先用 `git log`、`git show`、`git bisect` 确认引入点；通过新的 `hotfix/*` 提交修复，不以删除 Git 历史或强制推送替代修复。
