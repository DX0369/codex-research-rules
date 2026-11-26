# VS Code Remote-SSH 接入 Codex 长任务

VS Code Remote-SSH 在服务器上运行 Codex 扩展。Linux 启动器把扩展的 JSON 行通信接到官方 Codex 后台的私有 Unix socket，监控通过同一个后台将事件投给原聊天。Windows 本地窗口使用同名启动器调用扩展随附的官方 CLI。后台由远端启动器按需启动，关闭桌面 App 后仍可使用这条 VS Code 接入路径。桌面 App 自己的接入见 [官方 SSH 说明](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host)。

## 服务器准备

1. 远端扩展进程的 `PATH` 应能找到支持 `queue --resume`、`app-server daemon start` 的 Codex CLI，以及 [Websocat](https://github.com/vi/websocat/releases/tag/v1.14.2)。由常驻后台读取当前 `CODEX_HOME` 下的配置，默认是 `$HOME/.codex`。
2. 在每台要接入的 Linux 服务器的仓库根目录执行下面的命令。确保 VS Code 远端扩展进程启动时，个人 `$HOME/.local/bin` 已在它的 `PATH` 中。

   ```sh
   mkdir -p "$HOME/.local/bin"
   install -m 755 integrations/vscode/codex-vscode "$HOME/.local/bin/codex-vscode"
   command -v codex codex-vscode websocat
   ```

## Windows 客户端准备

如果准备在日常 VS Code 中同时使用 Windows 本地窗口和 Linux 远端窗口，在本机仓库根目录用 PowerShell 编译同名启动器。示例使用 Windows x64 的 .NET Framework 编译器。

```powershell
$bin = Join-Path $env:USERPROFILE '.local\bin'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
New-Item -ItemType Directory -Force -Path $bin | Out-Null
& $csc /nologo /target:exe "/out:$bin\codex-vscode.exe" 'integrations\vscode\windows-launcher.cs'
```

把该 `$bin` 目录加入 Windows 用户的 `Path`，然后重新启动 VS Code 使环境变量生效。在你原先使用的本机**用户设置**中合并以下配置，再重开目标 Remote-SSH 窗口。

```json
{
  "chatgpt.cliExecutable": "codex-vscode"
}
```

这是扩展的应用级开发设置。同一份用户数据目录下的本地窗口和所有远端窗口都会读取它。使用 Codex 的远端窗口需要在运行扩展的一侧能找到同名启动器。只想在部分连接中启用时，可以继续用独立的 `--user-data-dir` 管理该设置。

## 探测与复验

在重开的窗口里打开要接收通知的原聊天，让它执行以下命令。

```sh
watch_script="${CODEX_HOME:-$HOME/.codex}/skills/watch-research-run/scripts/watch.py"
python3 "$watch_script" probe
```

从结果核对当前聊天 ID 和目标后台。看到 `idle` 或 `active` 后，再做一次短任务的登记、交接和终态回执检查。看到 `notLoaded` 时，先确认窗口已走启动器，并在重载后的面板打开原聊天。只重载窗口时，旧聊天可能还没有载入。VS Code 扩展升级或入口变更后，复用这个验收。

已经以 `--record-only` 登记的任务会继续保存终态。它的 `watch.json` 中没有投递地址，重连和重载不会给旧登记补上地址。要为正在运行的任务补通知，沿用原计划和原终态记录单独接续，避免重启实验或重复投递。

Linux 启动器已验证 JSON 行通信、关闭 VS Code 窗口后的投递和重开后查看同一聊天的回复。Windows 启动器已用实际随附 CLI `0.171.0-alpha.13.2` 验证 JSON 行初始化、创建和读取测试聊天、断开后进程退出。每个实际面板仍以本节的探测和回执为准。

需要撤销时，从客户端用户设置还原 `chatgpt.cliExecutable`，重开窗口。在监控任务已结束或已另行接续后，可以移除启动器文件。
