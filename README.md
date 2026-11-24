# Codex 科研规则与技能

这里保存个人科研工程规则及技能的发布源码。Git 标签与发布清单中的版本对应。

- [全局科研规则](codex-rules/AGENTS.md)
- [共享科研技能](codex-rules/skills/)
- [本机复盘技能](codex-rules/local-skills/)
- [发布清单](codex-rules/manifest.json)

## 取用和发布

首个标签 `v2026-11-24.2` 对应已验收的 `2026-11-24.2` 发布版本。可以从所选标签导出 `codex-rules/`。

```bash
git archive --format=zip --output=codex-rules-v2026-11-24.2.zip v2026-11-24.2 codex-rules/
```

将导出的规则目录作为现有服务器迁移工具的 `tools/codex-rules/` 发布输入。先通过菜单 12 预览并校验，再同步与复核。需要更新离线迁移包时，使用菜单 10 导出。`local-skills/` 中的技能由发布工具安装到本机。

修改规则或技能后，核对实际文件并更新发布清单中的版本和 SHA-256。提交经验证的版本并打标签，新会话使用已同步的版本。
