# Windows → Mac Codex 聊天记录迁移 SOP

## 1. 目的与范围

本 SOP 用于把 Windows 当前用户下的 Codex 本地聊天记录迁移到 Mac，并保留 Mac 原有聊天。

迁移内容：

- Windows `%USERPROFILE%\.codex\sessions` 中的会话文件。
- `session_index.jsonl` 会话名称索引。
- 完整性清单、SHA-256 校验、Mac 恢复脚本和本 SOP。

默认不迁移：

- `archived_sessions` 中的归档会话。
- `auth.json`、`.credentials.json`、`secrets` 和 OAuth 数据。
- 配置、插件、Skills、日志、缓存、记忆、自动化和浏览器状态。
- 项目代码、工作区文件及聊天中引用但已不存在的本地附件。

## 2. 前置条件

- Windows 源电脑可以访问原 Codex 用户的 `%USERPROFILE%\.codex`。
- Mac 已安装并至少启动过一次 Codex。
- 在两台电脑上都使用日常运行 Codex 的用户，不要使用管理员或 `sudo`。
- 准备 U 盘、可信云盘或局域网工具传输 ZIP。
- 将迁移包视为私密数据，因为聊天正文可能包含敏感信息。

## 3. Windows 源电脑导出

1. 完全退出 Codex；不要只关闭窗口。
2. 打开 Windows PowerShell。
3. 运行 Skill 自带的导出脚本：

   ```powershell
   powershell -ExecutionPolicy Bypass -File "<Skill目录>\scripts\export-codex-chats-for-mac.ps1" -DestinationDirectory "D:\桌面"
   ```

4. 脚本生成：

   - `CodexChats_Windows_to_Mac_时间.zip`
   - 同名 `.sha256.txt` 校验文件。

5. 核对输出的会话数量、ZIP 大小和 SHA-256。若脚本报错，不要继续传输。

无法退出正在使用的 Codex 时，只有在明确接受“当前会话可能缺少最后几条消息”的情况下才能加 `-AllowRunningCodex`。正常 SOP 不推荐此模式。

## 4. 传输并解压到 Mac

1. 把大 ZIP 和 `.sha256.txt` 一起传到 Mac；它们不会自动出现在 Mac 桌面。
2. 双击大 ZIP 完整解压。
3. 打开解压目录，确认同一层至少存在：

   ```text
   native
   SHA256SUMS.txt
   restore-codex-chats-mac.sh
   manifest.json
   ```

4. 如果只有几 KB 的“Mac 补充包”而没有 `native`，说明聊天数据大 ZIP 尚未传到 Mac，不要运行脚本。

## 5. Mac 恢复

1. 在 Mac 上按 `Command + Q` 完全退出 Codex。
2. 打开“终端”。
3. 输入 `bash` 和一个空格，不要先回车。
4. 从 Finder 把 `restore-codex-chats-mac.sh` 拖进终端，系统会填入完整路径。
5. 按回车执行。完整命令类似：

   ```bash
   bash "/Users/用户名/Downloads/CodexChats_Windows_to_Mac_时间/restore-codex-chats-mac.sh"
   ```

6. 不要使用 `sudo`。
7. 出现 `Migration complete` 后启动 Codex，等待首次索引重建。

## 6. 验收

- 恢复输出包含新增会话数、冲突替换数、目标会话总数和备份目录。
- Codex 侧边栏出现迁移的聊天标题。
- 随机打开至少 3 个旧聊天，确认用户消息和 Codex 回复可见。
- Mac 原有聊天仍可打开。
- 保留 ZIP 和迁移前备份，直到确认全部正常。

## 7. 常见故障

### `Permission denied`

脚本存在，但被直接当作可执行程序运行。改用：

```bash
bash "/完整路径/restore-codex-chats-mac.sh"
```

不需要 `chmod`，也不要使用 `sudo`。报错发生时迁移尚未开始。

### 找不到 `native` 或 `SHA256SUMS.txt`

脚本不在大迁移包的解压根目录，或只传了 Mac 补充包。把脚本放到与 `native`、`SHA256SUMS.txt` 同一层，或重新传输并解压大 ZIP。

### 提示 Codex 正在运行

按 `Command + Q` 完全退出 Codex后再执行。不要绕过运行检查。

### 恢复成功但聊天暂未出现

保持 Codex 打开并等待索引重建；仍未出现时，完全退出后重新启动一次。

### 旧项目路径不可用

聊天会话可能记录 `C:\Users\...` 等 Windows 路径。聊天文本仍可查看，但继续旧项目需要单独迁移项目文件，并从 Mac 上的新项目目录创建任务。

## 8. 回退

1. 完全退出 Mac 上的 Codex。
2. 找到恢复输出中的备份目录：

   ```text
   ~/Documents/CodexMigrationBackup_时间
   ```

3. 从该目录恢复原索引和冲突会话。
4. 不要在未核对范围时批量删除 `~/.codex/sessions`。
