# 卡片计划与关闭方式

本文对应源码根目录的 `tools/manage_apps.py`。接口变化时核对工具的 `prepare()`、参数帮助及后端验证函数，不通过直写配置绕过验证。

## 最小计划

由助手填写 JSON，用户无需手写。以下路径、PID 和创建时间都是示例，必须替换为本次发现的值；没有当前运行实例时省略 `pid/created`：

```json
{
  "apps": [{
    "name": "示例服务",
    "pid": 1234,
    "created": "本次发现的创建时间字符串",
    "kind": "service",
    "shell": "cmd",
    "command": "python server.py",
    "cwd": "D:\\Apps\\ExampleService",
    "port": 8080,
    "category": "开发工具",
    "locations": [
      {"id": "project", "name": "项目目录", "path": "D:\\Apps\\ExampleService"},
      {"id": "config", "name": "配置文件", "path": "D:\\Apps\\ExampleService\\config.json", "mode": "editor"}
    ],
    "front": ["custom:project", "custom:config"]
  }]
}
```

- 更新用已有 `name` 或明确 `appId`；同名多张必须给 `appId`。只改位置和按钮时省略实例与生命周期字段，保留原配置。
- `kind` 明确区分 `desktop`（应用）、`service`（服务）和 `task`（一次性脚本）；`shell` 只选择解释器。端口必须来自目标服务，不把 GUI 的内部监听默认当成网页入口。
- `locations` 生成 `type=location` 动作，绝对路径须存在；`mode` 为 `explorer/terminal/editor`，默认 `when=always`。编辑器留空时用记事本；目录用编辑器打开时须指定支持目录的实际 `.exe`。
- `actions` 按 ID 合并，未涉及项保留。命令、回环 HTTP、URL 和脚本动作使用原生类型，不伪装为位置入口。依赖运行的动作设 `when=running`；离线维护和位置入口按实际需求设 `always`。
- `front` 只安排下方最多两个软件专用动作。上方打开/关闭和服务 Web／应用前台入口由工具生成。服务不要重复添加 Web 按钮；省略 `front` 时，新卡片生成布局，已有卡片保留布局。
- 需要精确布局时使用现有 `cardButtons`，其 `when` 控制按钮显隐，不等同于动作 `when` 的运行条件。显式布局是完整布局，不自动补回已移除项。
- `window` 使用发现返回的一整条窗口对象；`null` 明确解除绑定。隐藏窗口、工具窗口、最小化和后台驻留要按现有身份规则区分，窗口不可见不等于进程退出。
- `followInstance: true/false` 通过后端启停后续实例识别。PID 和创建时间用于本次操作锁定；长期匹配规则由后端生成，不能手填或放宽参数匹配。

## 关闭方式

配置启动时同时确认关闭方式；“配置已保存”不能当作“已验证退出”。

| 目标行为 | 选择 |
| --- | --- |
| 有已核实的原生退出命令或 API | 优先使用原生退出，保留应用自身收尾流程。 |
| 文档编辑器等可能有未保存内容 | 保留正常关闭与保存提示；用户取消保存后不升级为强杀。 |
| 关窗口仅隐藏或缩到托盘 | 不声称窗口关闭就是退出；查该应用的原生退出方式。 |
| 用户明确选择结束已验证实例 | 可配置 `tools/stop_app_processes.py`；这是进程终止，会中断未完成任务。 |
| 退出方式未知 | 说明未确认，不猜 `--quit` 或擅自试关。 |

脚本动作使用 `type=script`，`path` 是已存在的 `.py` 或 `.ps1` 绝对路径，可包含 `id/name/when/timeoutSec`。将动作 ID 写入 `stopAction` 才会替换固定关闭按钮的行为，启动仍用 `command`。需要其他 Python 环境时填写已核实的 `python` 绝对路径。

脚本从环境变量 `CDDECK_APP_CONTEXT` 读取执行时的 `appId/name/cwd/port/processes`，进程项包含 `{pid, created}`。不固化 PID，不按名称/端口结束。复用项目自带终止脚本时，将源码根目录拼接 `tools/stop_app_processes.py` 得到实际路径，不复制维护者机器上的路径。

PowerShell 控制脚本成功显式返回 `exit 0`，失败返回非零；不能把最后一个无关探测命令的退出码当作控制结果。系统服务和外部隧道不是普通应用子进程，只在用户明确指定时使用对应控制器，不从示例中套用端口、服务名或强杀名单。

## 图标和实例边界

- 桌面卡片缺少自定义图片时可用现有 EXE 图标提取；服务优先项目 Logo 或已验证站点 favicon，不默认使用解释器图标。有现成素材就复用，不为接入卡片额外生图。
- 普通浏览器、独立 profile、PWA 和服务网页各有身份，不能全局忽略参数。Python/Node 同目录下不同脚本或配置参数也不能混认。
- 父子程序已有独立卡片时保留管理边界，不重复创建互相覆盖的关闭入口。确需改关联宿主时按当前 API 支持范围处理，不为通过导入而解除重叠保护。
