# 开发说明

安装与使用见 [README](../README.md)，开发环境和检查命令见 [CONTRIBUTING](../CONTRIBUTING.md)。

## 模块入口

| 内容 | 文件 |
| --- | --- |
| HTTP 路由、配置读写、应用生命周期 | [server.py](../server.py) |
| 卡片字段、规则与场景校验 | [ops_model.py](../ops_model.py) |
| 后台采集、异常及场景执行 | [ops_monitor.py](../ops_monitor.py) |
| 扩展 API | [ops_api.py](../ops_api.py) |
| Windows 实例、窗口身份与进程边界 | [ops_entries.py](../ops_entries.py) |
| 服务网页窗口 | [service_web.py](../service_web.py) |
| 文件夹、Everything 与预览 | [file_tools.py](../file_tools.py) |
| Windows 资源与通知 | [win_metrics.py](../win_metrics.py)、[win_notify.py](../win_notify.py) |
| Windows 启动锚点 | [tools/win_anchor.py](../tools/win_anchor.py) |
| 前端入口与功能模块 | [static/app.js](../static/app.js)、[static/js/](../static/js/) |
| 主题注册、结构与视觉边界 | [主题说明](../static/themes/README.md) |

## API

接口参数与返回字段以对应处理函数为准。以下是维护入口，不复制完整状态快照。

| 接口 | 用途与实现入口 |
| --- | --- |
| `GET /api/state`、`GET /api/health` | 页面状态与健康检查；`server.py` 的 `build_state` 及 GET 路由 |
| `/api/apps`、`/api/apps/{id}` | 卡片新增、更新、删除及 start/stop/restart、日志、图标、诊断等子路由；`server.py` |
| `/api/pick`、`/api/project/detect` | 路径选择与项目命令识别；`server.py` |
| `/api/kill`、`/api/services/flag`、`/api/watch` | 进程操作、服务标记与关注；`server.py` |
| `/api/console/stop`、`/api/console/restart`、`/api/ui/theme` | 控制台与主题；`server.py` |
| `/api/ops/*` | 运行实例发现/导入、动作、窗口、规则、场景、事件和告警；`ops_api.py` 的 `get/post` |
| `/api/files/*` | 文件夹、搜索和 QuickLook 预览；`file_tools.py` |

写接口沿用现有请求授权和每应用操作锁。新增不读取 JSON 的 POST 路由也需消费请求体，避免残留字节污染 keep-alive 后续请求。

### 状态与生命周期

- `running` 依据受控进程身份；端口上存在监听者不代表属于该卡片。`listening` 表示受控进程监听，`portOccupied` 表示外部占用。
- 服务行的 `key=name:port` 用于保存标记，`instanceKey=pid:port` 用于前端实例对账。`portConflict/portConflictApps` 是旧前端兼容字段，固定为 `false/[]`。
- 一次性任务的结果：退出 0 为 succeeded，130 为 canceled，其他自然退出为 failed；控制台中止为 stopped。快速成功任务应保留完成结果。
- `inspect_app_health` 仅静态检查；复杂命令为 unknown，不按日志文字或无法解析的表达式判定失败。
- 运行中更新 `command/cwd/port/kind/shell` 需先停止。前端保留编辑草稿；API 的 `stopBeforeUpdate:true` 提供停止后原子更新。
- 正常关闭失败保留管理身份；强制结束单独确认。控制台自身退出后，已启动的独立应用继续运行。
- Windows 的实例匹配、资源统计、动作与强制结束共用独立子卡片边界。窗口绑定与进程归属分别校验，服务网页不纳入服务关闭范围。
- WindowsApps 的版本归一化集中在 `ops_entries.same_window_executable`；实时 PID、创建时间和 EXE 身份仍精确核对。

## 配置

当前 `schemaVersion` 为 **8**；定义见 `server.py` 的 `CURRENT_SCHEMA_VERSION`，完整默认值见 `Config.DEFAULT`、`Config.APP_DEFAULT` 与 `ops_model.APP_FIELDS`。

顶层保存卡片与服务标记、主题、规则/场景、告警忽略与覆盖、文件夹/搜索设置及目录快照。运行身份由后端生成；窗口绑定和实例规则通过专用 API 保存。

迁移入口为 `migrate_config` 与 `CONFIG_MIGRATIONS`，按版本逐步执行。配置加锁后通过临时文件和 `os.replace` 原子写入，`.bak` 保留良好备份。主配置和备份均不可读，或 schema 高于程序支持版本时，保留写入保护。

Windows 默认数据目录见 [README](../README.md#数据升级与卸载)。macOS 配置与图标位于 `~/Library/Application Support/总控台`，日志位于 `~/Library/Logs/总控台`。环境变量可覆盖目录；设置覆盖路径时不自动迁移旧 `data/`。

## 前端与平台

- 页面读取共享状态，列表按稳定 key 更新；采集失败与未知数据单独显示。
- 文件配置在进入页面或变更后读取；Everything 搜索由提交、排序或翻页触发。
- 主题管理配色、字体、材质和视觉动效；布局、滚动、显隐与点击区域留在结构层。
- Windows 使用 CMD/PowerShell，macOS 使用 Bash。命令解析和原生功能按平台处理，修改共享逻辑时保留兼容分支；Windows 是主要实机验收目标。

## 验证入口

常规检查见 [CONTRIBUTING](../CONTRIBUTING.md#检查)，UI 检查见 [演示与验收](ui-acceptance.md)，完整发布见 [发布核对表](../RELEASE_CHECKLIST.md)。

后台性能可用 `py -3.12 tools/measure_idle.py --seconds 1800 --output tmp/idle-acceptance.json` 测量。它使用独立临时配置，记录控制台及辅助进程的 CPU、工作集和采集耗时，并发送一次验收通知。参考目标为平均 CPU ≤1%、工作集 ≤150 MiB；内存趋势和浏览器占用另行记录。
