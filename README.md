# Codex 科研规则与技能

一套面向科研代码和远程实验的 `AGENTS.md` 与 Codex Skill。它们让调研可续接、实验可对比、文件有清楚的归属，远程任务结束后还能由原聊天接手。

- **减少过度防御和重复验证。** 在实际输入和外部接口处做必要校验，复用已有有效测试，以能回答当前问题的最小用例验收。
- **整理资料、版本和产物。** 用 `PROJECT.md` 维护科研约定，用 `PROJECT_STATE.md` 留下进展和证据入口。调研在同一入口续写，正式运行使用独立输出目录。
- **让长任务回到原聊天。** Slurm 作业或普通 Linux 任务退出后，监控投递事件，由 Codex 核对日志及产物，再按最初的授权处理。启动时可以先记录，验收到进展后再交给后台。

## 规则覆盖什么

| 范围 | 主要约定 |
| --- | --- |
| 项目信息、授权和 Agent 分工 | 项目说明和状态各有入口。正式操作按用户授权执行，主 Agent 保留判断和证据。 |
| 科研语义、实现和验证 | 尊重数据字段、评测和失败处理协议。代码保持直接，测试覆盖实际变动。 |
| 资源和外部网络 | 核对模型、数据、依赖镜像、执行环境和代理，按任务使用资源。 |
| 调研、实验规划和运行 | 复用已有调研。明确数据版本、样本范围和有代表性的设置。实验回答会影响选择的问题。 |
| 长任务、文件和完成 | 复用后台运行机制和监控，把结论与正式结果入口留在项目文档。按复现、恢复和后续需要收尾。 |

完整规则见 [AGENTS.md](codex-rules/AGENTS.md)。

## 按任务选择 Skill

| 想做的事 | Skill |
| --- | --- |
| 建立科研项目说明和状态页 | [init-research-project-docs](codex-rules/skills/init-research-project-docs/SKILL.md) |
| 更新进展、结论与结果入口 | [update-research-project-state](codex-rules/skills/update-research-project-state/SKILL.md) |
| 调研新问题或续查已有方向 | [review-research-topic](codex-rules/skills/review-research-topic/SKILL.md) |
| 判断论文方法和公开资产能否复现 | [review-reproduction-feasibility](codex-rules/skills/review-reproduction-feasibility/SKILL.md) |
| 准备训练、评测、推理或数据生成 | [prepare-research-run](codex-rules/skills/prepare-research-run/SKILL.md) |
| 核对真实运行状态与结果覆盖 | [audit-experiment-status](codex-rules/skills/audit-experiment-status/SKILL.md) |
| 托管远程长任务，终态回到原聊天 | [watch-research-run](codex-rules/skills/watch-research-run/SKILL.md) |
| 让新聊天、另一台机器或合作者接手 | [handoff-research-project](codex-rules/skills/handoff-research-project/SKILL.md) |
| 盘点和精简代码、测试、文档及产物 | [review-cleanup-candidates](codex-rules/skills/review-cleanup-candidates/SKILL.md) |
| 复盘可访问的 Codex 使用记录，提取规则候选 | [codex-usage-review](codex-rules/local-skills/codex-usage-review/SKILL.md)，在本机使用 |

## 安装与试用

1. 选择一个版本标签。按需把规则合并进目标 Codex 环境的 `${CODEX_HOME:-$HOME/.codex}/AGENTS.md`，或仅用于某个项目的 `AGENTS.md`。
2. 按需把完整的 Skill 目录放进目标环境的 `${CODEX_HOME:-$HOME/.codex}/skills/`。长任务托管配合安装 `prepare-research-run` 和 `audit-experiment-status`。本机会话复盘从 `local-skills/` 取用。开启新聊天，使用 Skill 名称或自然语言描述任务。
3. 使用 [调研续接示例](examples/research/README.md) 了解调研产物。监控的客户端接入和短任务验证见下文。

### 长任务接入

| 客户端 | 连接方式 |
| --- | --- |
| Codex 桌面 App | 使用 [官方 SSH 连接](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host)，在目标服务器的原聊天登记。 |
| VS Code Remote-SSH | 在日常 VS Code 中通过可选启动器接入服务器的官方 Codex 后台。Windows 本地窗口可用同名启动器调用扩展随附的 CLI。[安装与复验](integrations/vscode/README.md) |

在目标 Linux 聊天里让 Codex 运行 `watch.py probe`。这是本仓库监控脚本的探测命令。验证通过后，可以把下面这句发给 Codex。

> 用 watch-research-run 托管一条短的验收任务，登记后交给后台，任务退出时在当前聊天检查结果并写回执。

关闭窗口前等登记和交接完成。任务退出后，核对监控状态目录中的 `event.json` 和 `received.json`，再重开原聊天看回复。正式任务使用技能说明中的 launcher 和计划。后台需要可访问或可恢复，远程环境需要能运行模型。

## 版本与许可

Git 标签与 [发布清单](codex-rules/manifest.json) 对应。清单覆盖可同步的规则、Skill 和监控脚本。[MIT License](LICENSE)
