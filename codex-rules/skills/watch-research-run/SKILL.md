---
name: watch-research-run
description: 在用户要求托管长时间科研任务时，从 Slurm 或由 screen、nohup、setsid、systemd-run 启动的任务取得终态，回到启动任务的 Codex 会话验收结果、诊断故障或在明确授权范围内恢复。适用于预计约一小时以上、需在当前轮结束后继续处理的任务。仅查询已有实验状态时使用 audit-experiment-status。
---

# 托管长时间科研任务

## 启动与登记

1. 使用 `prepare-research-run` 核对本轮授权、正式入口、协议、输入输出和资源。复用项目 `tmp/<任务标识>/PLAN.md`，写明预期结果、验收方法、结果分析和必要路径。用户已授权自动处理时，记下可做的工程修复、恢复方式和重试次数。对于明确授权自动恢复且未指定次数的任务，默认一次。原会话的用户指示决定授权范围。
2. 找到本技能的 `scripts/watch.py`，使用当前会话真实的 `CODEX_THREAD_ID` 和可访问的 **同一个** app-server Unix socket。用实际 CLI 运行 `python3 <脚本> probe --codex <CLI路径> --socket <socket路径> --thread <当前会话UUID>`。只有收到匹配 ID 的 `idle` 或 `active` 才登记自动唤醒。普通 Remote-SSH 扩展可能通过专用 stdio 启动，遇到这种情况报告当前可用的监控和接手方式。在已有可连接后端上开展自动托管，或由用户启用经实际验证的接入方式。
3. 每次尝试使用计划目录下独立的 `watch/<尝试标识>/`。在能脱离当前终端的原有机制中运行脚本。脚本文件、计划与状态目录使用绝对路径，原会话 UUID 在启动时显式传入。任务运行环境、命令与正式输出位置仍按原计划。

需要建立托管会话时，在目标 Linux 主机的个人环境用 `codex app-server --listen unix://<私有短路径>` 提供个人后端，并用有界任务生命周期之外的现有后台机制持有该进程。用户从 `codex --remote unix://<同一路径>` 打开的会话可以经同一个 socket 接受后续事件。服务和 job 所在的账号应具有读取计划、日志和结果所需的权限。VS Code 接入以实际 `probe` 验证为准。

## 监控入口

- **Slurm。** 先完成会话探测，再按授权提交。拿到确切 job ID 后，用原有后台机制运行 `slurm` 子命令。接手已提交作业也使用这一入口。若监控中断且仍缺少终态，可对同一 job 和状态目录重新启动监控。数组或多阶段运行按计划登记所需的具体作业，完成时核对全部预期阶段。必要时用 `--wait-limit` 设置等待终态的上限。
- **screen、nohup、setsid、systemd-run --user。** 保持外层启动方式，将其运行的实际前台命令替换为 `run` 子命令加 `--` 和原 argv。项目 launcher 必须等实际工作结束，并把失败传播为非零退出状态。保留项目原有日志重定向和环境。需要 shell 管道时核对任务的真实退出状态。已经在跑且缺少终态记录的任务，使用已有运行证据审计，证据不足时标记未知。

```bash
python3 "$watch_script" slurm --codex "$codex_bin" --socket "$codex_socket" \
  --thread "$origin_thread" --plan "$plan_file" --state-dir "$attempt_dir" --job-id "$job_id"

python3 "$watch_script" run --codex "$codex_bin" --socket "$codex_socket" \
  --thread "$origin_thread" --plan "$plan_file" --state-dir "$attempt_dir" -- command arg1 arg2
```

在原启动环境中确认 `watch.json` 出现、实际作业存在，并向用户报告作业或进程标识和状态目录。当前轮可以正常结束。脚本在 `event.json` 保存终态，在 `delivery.json` 保存投递记录。`queued` 表示已入队，`received.json` 表示原会话已接手。端点暂时不可用时，事件保留，并在 `--delivery-seconds` 范围内重新连接。已保存事件可用 `deliver --state-dir <目录>` 继续处理投递。遇到 `uncertain` 或 `sending` 时先查实际会话与记录，避免重复触发。包装器若异常消失且缺少终态，依据实际状态审计后再决定如何接续。

## 原会话收到事件

1. 执行通知中的 `ack`，它核对 `CODEX_THREAD_ID` 和该次事件标识。读取登记的计划和终态证据，检查最新用户指示以及真实作业状态。若 `first_ack` 为 `false`，先检查前一轮已做事项，避免重复启动或修改结果。
2. 先用 `audit-experiment-status` 核对实际退出和产物。队列接受通知、进程退出、验收完成分别报告。人工取消、未确认终态或原作业仍活跃时，记录证据与后续判断。
3. **工程故障。** 定位最早能够解释失败的证据。只有用户已授权本次工程恢复、原运行确实结束、且修复保持实验协议和可比性时，由 `prepare-research-run` 复用实际入口做必要验证并按原协议续跑或重跑。以再次启动正式任务计重试次数，在计划中核对次数并预先登记新尝试。重跑使用独立正式输出目录，续跑遵循项目已确认的断点和输出约定。保留旧证据，重试也登记独立监控。超出授权或证据不足时报告现状与选项。
4. **协议或结论可能受影响。** 解释已知原因、拟改动及对可比性的影响，等用户确认后恢复。数据版本、划分、指标、训练参数和失败处理遵循已确认协议。
5. **进程以零退出码结束。** 按计划核对输出、样本覆盖和失败记录。覆盖不足时记录部分完成及缺项，验收通过后报告完成。依据已有结果给出证据支持的结论与下一步。正式重算或新实验按本次授权执行。有实质进展时按项目规则更新 `PROJECT_STATE.md`，本轮结束且投递记录已落盘后，清理已无续接用途的临时计划和监控记录。
