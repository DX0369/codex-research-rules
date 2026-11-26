# VS Code Remote-SSH 接入 Codex 长任务

启动器让 Codex 扩展的 JSON 行通信接到远端官方 Codex 后台的私有 Unix socket。监控通过同一个后台将事件投给原聊天。桌面 App 的 [官方 SSH 入口](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host) 可直接使用其远端后台。

## 安装

1. 远端扩展进程的 `PATH` 应能找到支持 `queue --resume`、`app-server daemon start` 的 Codex CLI，以及 [Websocat](https://github.com/vi/websocat/releases/tag/v1.14.2)。由常驻后台读取当前 `CODEX_HOME` 下的配置，默认是 `$HOME/.codex`。
2. 在远端仓库根目录执行：

   ```sh
   mkdir -p "$HOME/.local/bin"
   install -m 755 integrations/vscode/codex-vscode "$HOME/.local/bin/codex-vscode"
   command -v codex codex-vscode websocat
   ```

3. 在用于 Remote-SSH 的 VS Code 客户端用户设置中写入以下内容，然后重开远端窗口。扩展把它注册为应用级开发设置。需要同时保留常规 VS Code 入口时，用独立的 `--user-data-dir` 启动远程窗口。

   ```json
   {
     "chatgpt.cliExecutable": "codex-vscode"
   }
   ```

## 探测与复验

让要接收通知的聊天执行：

```sh
watch_script="${CODEX_HOME:-$HOME/.codex}/skills/watch-research-run/scripts/watch.py"
python3 "$watch_script" probe
```

从结果核对当前聊天 ID 和目标后台。看到 `idle` 或 `active` 后，再做一次短任务的登记、交接和终态回执检查。VS Code 扩展升级或入口变更后，复用这个验收。

本版在 Linux 上用 Codex CLI `0.169.0-alpha.11.1` 和 Websocat `1.14.2` 验证了启动器的 JSON 行通信、断开后投递、原聊天的回执与回复。实际扩展启动参数和面板显示以现场验收为准。

需要撤销时，从该客户端用户设置还原 `chatgpt.cliExecutable`，重开窗口。在监控任务已结束或已另行接续后，可以移除远端启动器文件。
