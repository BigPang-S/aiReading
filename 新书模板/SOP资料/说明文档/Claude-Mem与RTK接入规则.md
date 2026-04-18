# Claude-Mem 与 RTK 接入规则

这份规则只回答两件事：

- Claude-Mem 和 RTK 在小说 SOP 里接哪里
- 它们绝对不能接哪里

## 一、工具定位

### Claude-Mem

Claude-Mem 负责：

- 跨会话记住稳定偏好
- 记住固定命令和排障经验
- 记住反复出现的修订模式
- 记住哪些 workflow 在这个项目里更稳

Claude-Mem 不负责：

- 判定剧情 canon
- 判定人物关系
- 判定时间线
- 判定资源状态
- 判定下一章执行口

一句话：

- Claude-Mem 记“怎么工作”
- 项目文件记“故事现在是什么”

### RTK

RTK 负责：

- 压目录树输出
- 压 grep / find / git / log / test 这类 shell 输出
- 减少终端噪音进入模型上下文

RTK 不负责：

- 压正文
- 压状态卡
- 压任务卡
- 压验收全文

一句话：

- RTK 压“机器输出”
- 不压“小说语料”

## 二、接入后的硬规则

1. 项目 canon 永远以这些文件为准：
   - `当前有效规则卡.md`
   - 当前卷执行状态卡
   - 当前章任务卡
   - `章节验收记录.md`
2. Claude-Mem 记忆和项目文件冲突时，以项目文件为准。
3. RTK 只用于目录、检索、diff、日志、测试输出，不用于正文判断。
4. 每次进入新章前，先读项目卡片，再决定是否参考 Claude-Mem。

## 三、推荐用法

### Claude-Mem

建议让 Claude-Mem 记住的内容：

- 这本书默认走低 token 工作流
- 总目录只在建任务卡时回读
- 状态卡每栏最多 4 条
- 去 AI 味时常见问题和修法
- 哪类章节最容易在验收里翻车

不要让 Claude-Mem 主导的内容：

- “这个人物现在和谁关系更近”
- “这个资源线现在推进到哪”
- “这章到底该承接什么”
- “哪条事实已经落地”

### RTK

推荐命令：

```bash
rtk tree -L 2 .
rtk find -name '*状态卡*'
rtk grep '第43章' 小说框架
rtk git status
rtk git diff README.md 使用手册.md
rtk log some.log
```

不推荐命令场景：

```bash
rtk read 小说正文/源稿/001_章节名.txt
rtk read 小说框架/当前卷执行状态卡.md
rtk read 章节验收记录.md
```

这些场景需要保留原文细节，不能先压缩。

## 四、两类已知风险与处理

### 风险 1：Claude-Mem 混入泛项目记忆

表现：

- 数据库里出现 `songzijian`、`thedotmack` 这类泛项目名
- 新会话被注入了不属于当前小说项目的旧经验

处理原则：

- 把泛项目名写入 `CLAUDE_MEM_EXCLUDED_PROJECTS`
- 小说项目名保留，例如 `女墙之外`
- 如果发现新泛项目名，继续追加到排除列表
- 如果数据库里已经有旧泛项目记录，先备份再定向清理

### 风险 2：RTK telemetry 开启

处理原则：

- 小说工作流默认关闭 RTK telemetry
- 保留本地过滤和 tracking，不上传遥测

## 五、建议配置

小说项目推荐的 Claude-Mem 低 token 配置：

- `CLAUDE_MEM_CONTEXT_OBSERVATIONS=20`
- `CLAUDE_MEM_CONTEXT_SESSION_COUNT=3`
- `CLAUDE_MEM_CONTEXT_SHOW_TERMINAL_OUTPUT=false`
- `CLAUDE_MEM_EXCLUDED_PROJECTS=<你的用户名>,thedotmack`

说明：

- 观察数和会话数太大，会把辅助记忆层重新变成上下文负担。
- 终端输出默认不进 Claude-Mem 上下文，避免把 shell 噪音重新喂回来。

## 六、落地检查

执行：

```bash
python3 scripts/audit_assistant_tooling.py
```

通过标准：

- Claude-Mem 已配置排除泛项目名
- Claude-Mem 处于低 token 注入配置
- RTK telemetry 已关闭
