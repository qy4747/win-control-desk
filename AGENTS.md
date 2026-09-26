# 总控台 (Console)

Windows 优先、独立维护的本机控制台，来源与版权见 README/LICENSE。不主动同步上游，不改可见性、重写历史或发 Tag。运行后端仅依赖 Python 3.12+ 标准库（已拆分模块），前端为无构建原生代码。Windows 使用 `start.bat` 或 `py -3.12 server.py`；macOS 兼容入口保留，CI 通过不代替原生桌面验收。

Windows 配置/图标为 `%APPDATA%\总控台`，日志为 `%LOCALAPPDATA%\总控台\Logs`；以下 macOS 路径仅适用于兼容分支。不要读取个人运行数据做截图，使用 `tools/ui_demo.py`。测试先定位失败，保留身份/权限断言；新增样式须覆盖主题包与素材指纹检查。

## 结构

- `server.py` — 后端入口（仅标准库，Python 3.12），协作模块包括 `ops_*`、`service_web.py`、文件工具和 Windows 适配
- `static/index.html` / `static/app.js`（入口）/ `static/js/{core,launchpad,services,overlays,ports,widgets}.js`（原生 ES Modules，无构建）/ `static/icons.js` — 前端（原生，禁框架/CDN/构建）；`core.js` 承载工具/API/浮层/状态/主题注册，`launchpad.js` 卡片+拖拽+诊断+启动台 KPI/分区过滤，`services.js` 表格+监控 KPI 火花线，`overlays.js` 模态+抽屉，`ports.js` 端口归一化纯函数，`widgets.js` 右侧信息栏（实时动态/告警、TOP5、小贴士、快捷操作）与导航轨状态；模块间用 `window.__poll` 共享轮询入口
- 布局 v2：左侧 `.rail` 图标导航轨（启动台/服务监控视图切换 + 日志中心/设置中心弹层入口）+ 顶栏 + 内容/右侧信息栏双栏网格（≤1280px 侧栏下沉到底部、≤900px 导航轨隐藏）；结构样式集中在 `static/base.css` 末尾「布局 v2」段（主题令牌驱动），主题包负责视觉皮肤
- `static/themes/` — 内置 `ops`（极简，保留原外观与默认 id）和 `apple`（建筑壁纸、轻磨砂、液态玻璃）。设置中心提供主题切换，深浅色独立保留。`{id}.css` + `{id}.json`（`id/name/author/desc/colors[]`）注册：`GET /api/state` 返回 `themes/uiTheme`，`POST /api/ui/theme {theme}` 校验后落盘。`static/js/appearance.js` 管理选择器和 Apple 材质生命周期；WebGL 仅用于导航轨、顶栏、场景栏，共最多 3 个上下文，卡片使用 CSS 磨砂。
- 素材主题：`static/themes/elements.css` 共用映射，`packs/<包名>/theme.json` + `theme.css` 自动注册为 `pack-<包名>`；包内放素材、配色和材质样式。`journal` 为占位示例；`papercut` 为真实纸卡/纸条素材包，九宫格仅作用于纸面伪元素，不裁切卡片交互。尺寸规范见 `static/themes/packs/素材包制作说明.md`，实作与生图提示词见 `papercut/实作记录与生图提示词.md`。通过注册表的 `css` 字段加载包样式，原有平铺主题路径继续兼容。
- 主题边界见 `static/themes/README.md`：配色、字体、边框、阴影、状态外观和视觉动效统一进主题目录；`base.css` / `ops.css` / `files.css` 留结构与行为。JS 只提供状态、坐标、进度和采样色，翻面与拖拽视觉参数从主题读取。
- `static/fonts/GeistMono-Variable.woff2` — vendored 数据/代码字体；中文与正文使用系统字体栈；`static/icons/*.svg` — Lucide 图标源文件（vendored）；`tools/gen_icons.py` — 由 svg 重新生成 `icons.js`（勿手改 icons.js）
- `static/assets/` — 品牌素材：`console-app-icon.png` 为 App Icon 主图，`brand-mark.png` 为顶栏标识；`favicon-32.png` / `favicon.ico` / `apple-touch-icon.png` 与 `.app` 内 `AppIcon.icns` 由 `tools/gen_brand_assets.py` 生成
- `~/Library/Application Support/总控台/config.json` — 用户配置；`icons/` 为应用图标。目录/ 文件权限分别为 0700/0600
- `~/Library/Logs/总控台/{appId}.log` — 应用启动日志；`console.log` 为 `.app` 启动日志
- `data/` — 旧版项目内数据，仅在新目标不存在的首次启动中复制迁移；保留不删除
- `start.command` — macOS 双击启动脚本（chmod +x）
- `start.bat` — Windows 双击启动脚本；优先 `py -3.12`，回退符合 3.12+ 的 `py -3` / `python`
- `tools/win_anchor.py` — Windows 受控应用锚点，持有 token，并用进程内 Toolhelp32 快照等待 PPID 后代树退出；仅在原生快照失败时回退 PowerShell CIM；临时批处理位于 `%TEMP%\local-ops-console-anchor`，以产品签名 + 锚点 PID 限定安全清理范围
- `总控台.app` — macOS 无终端窗口启动器（`LSUIElement` 后台应用；内部直接启动 `server.py`，输出写入 `~/Library/Logs/总控台/console.log`）

## 运行

`python3 server.py`（macOS）/ `py -3 server.py`（Windows）→ 绑定 `127.0.0.1`，端口从 **9600** 起尝试，被占则 +1（最多 10 个）。启动后自动打开浏览器。`/favicon.ico` 返回统一品牌图标。

## API 契约（全部 JSON；icon 上传为原始字节）

### `GET /api/state` — 前端唯一轮询接口
```json
{
  "services": [{
    "key": "python3.12:8791", "instanceKey": "54252:8791",
    "pid": 54252, "name": "python3.12", "port": 8791,
    "cwd": "/Users/example/xx项目", "project": "xx项目", "cmd": "python3 app.py",
    "cpu": 0.3, "mem": 1.2, "uptimeSec": 7980,
    "group": "mine", "pinned": false, "hidden": false, "promoted": false,
    "appId": null, "appName": null,
    "origin": {"label": "Codex", "icon": "bot"}
  }],
  "watched": [{"pid": 1, "name": "ffmpeg", "cmd": "...", "cpu": 0.0, "mem": 0.5, "uptimeSec": 60, "keyword": "ffmpeg"}],
  "apps": [{
    "id": "a1b2c3d4", "name": "我的博客", "command": "python3 -m http.server 8080",
    "cwd": "/path", "port": 8080, "emoji": "🚀", "glyph": "rocket", "icon": "/icons/a1b2c3d4.png",
    "kind": "service", "attached": false,
    "running": true, "pid": 1234, "uptimeSec": 120,
    "listening": true, "portOccupied": false, "portOccupiedPid": null,
    "portConflict": false, "portConflictApps": [],
    "lastExit": {"status": "succeeded", "code": 0, "at": 1700000000, "startedAt": 1699999998750, "durationSec": 1.25},
    "health": {"status": "ok", "blocking": false, "issues": []},
    "favicon": "/icons/fav-a1b2c3d4.png",
    "ports": [8080],
    "listening": true, "portOccupied": false, "portOccupiedPid": null,
    "portOwner": null, "portConflict": false, "portConflictApps": []
  }],
  "watchedKeywords": ["ffmpeg"],
  "consolePort": 9600, "consolePid": 123, "consoleCwd": "/path/to/总控台",
  "version": "1.0.0", "schemaVersion": 8,
  "degraded": false, "degradedReasons": []
}
```
- `GET /api/health` — 不运行 `ps/lsof` 的轻量健康检查，返回 `status/version/schemaVersion/degraded/issues/config`
- `group`: `"mine"` | `"background"`；`icon`/`emoji`/`port`/`cwd`/`project`/`appId`/`appName`/`lastExit` 可为 `null`
- `lastExit`：最近一次退出结果。任务状态为 `succeeded`（exit 0）/`canceled`（脚本主动 exit 130）/`failed`（其他自然退出）/`stopped`（总控台中止，code=null）；旧数据可能只有 `code/at`，API 输出时会兼容推导但不改写磁盘。批处理启动时保留上一次完成历史，自然退出或中止后覆盖
- `health`：每次状态读取时只读检查配置，返回 `status: ok|error|unknown`、`blocking` 与 `issues[{kind,severity,title,detail,fix,action}]`。明确缺失的 cwd、脚本或运行时会阻止启动；复杂 Shell 命令无法静态判断时为 unknown，不阻止运行
- `kind`：`"service"`（长期服务，有端口语义）| `"task"`（批处理任务，强制 port=null，主按钮为「运行」）；旧数据缺省视为 `service`。启动台按 kind 分两个区渲染
- `running`：仅表示存在通过本次启动 token、进程组与当前用户三重校验的受控进程；不再以“配置端口有任意监听者”作为运行依据
- `attached`：用户从服务监控明确认领的外部服务身份。此类服务的监听子进程换 PID 后，可按配置端口 + 当前 UID + 真实 cwd 唯一重新关联；普通卡片仍不得仅凭端口自动认领
- 服务行的 `key` 保持 `name:port` 以兼容隐藏/置顶配置；`instanceKey` 使用 `pid:port` 区分同名同端口后来出现的新进程实例，前端发现与 DOM 对账均使用它
- `listening`：受控进程是否正在监听配置端口；`portOccupied`：该端口当前被不属于本卡片的进程占用；多张卡片允许保存同一个常见开发端口，`portConflict/portConflictApps` 仅为旧前端兼容字段并固定返回 `false/[]`；`legacyManaged`：是否通过旧版 PID+端口+UID+cwd 兼容身份识别
- `project`：cwd 最后一段目录名（用于区分同名进程）；`appId`/`appName`：该端口命中启动台应用时的关联信息
- 排除控制台自身进程；只返回当前用户的进程
- **进程溯源**：`origin` 沿 PPID 链（≤12 层）识别启动者——跳过壳/包管理器/运行时包装层与 launchd，优先匹配已知 AI 编程助手（codex/claude/kimi/gemini/aider/opencode 等）、`.app` 包（VS Code/Cursor/iTerm/Warp 等）、tmux/screen 与总控台 run-token 标记（「总控台」）；未识别的中间层先记为候选、有更优答案即覆盖，全部落空才以最近未识别进程命名；`label` 为展示名、`icon` 取 bot/code/terminal/package/rocket/server，仅用于展示，不影响启停判定

### 服务操作
- `POST /api/kill` `{pid, force?}` → `{ok}` / `{ok:false, error}`（force 用 SIGKILL；校验属当前用户）
- `POST /api/services/flag` `{key, flag: "hidden"|"pinned"|"promoted", value: bool}` → `{ok}`（promoted=false 即「移回后台」，前端对 `svc.promoted` 的行显示该按钮）
- `POST /api/watch` `{keyword, action: "add"|"remove"}` → `{ok, keywords}`

### 启动台应用
- `POST /api/apps` `{name, command, cwd?, port?, emoji?, glyph?, kind?, shell?, attachPid?}` → app 对象（`kind` 缺省 `service`；`task` 强制 port=null；Windows `shell` 为 `cmd|powershell`，macOS 为 `bash`；服务监控来源可带 `attachPid`，后端先校验 PID/端口/UID/cwd，再将卡片与运行身份一次写入，失败不创建半成品卡片）
- `POST /api/pick` `{what: "dir"|"script", shell?}` → `{ok, path, command?, cwd?, name?}` / `{ok, canceled:true}`（macOS 用 osascript；Windows 用 PowerShell STA + WinForms 临时置顶 owner。脚本命令按指定 shell 生成，取消不是错误；选择框等待 180 秒，前端请求等待 195 秒）
- `POST /api/project/detect` `{cwd}` → `{ok, cwd, name, files, candidates:[{command,shell,label,source,port,kind,detail}]}`（只读分析项目根目录，不执行项目代码；识别 package.json scripts 与包管理器锁文件、Hexo/Hugo/Jekyll、Django/FastAPI/Flask/Streamlit、Docker Compose、Go、Rust、常用启动脚本及纯静态站点。Hexo 无 scripts 时仍返回 `hexo s` 服务与 `hexo cl` 任务）
- `POST /api/apps/reorder` `{ids: [...]}` → `{ok}`（按 ids 重排 apps 数组；Python sort 稳定，未涉及的 id 相对顺序不变，服务/任务两区可独立拖拽排序互不干扰）
- `PUT /api/apps/{id}`（部分更新同字段，可带 `stopBeforeUpdate:true`）→ app 对象；运行中修改 command/cwd/port/kind/shell 时，缺少该标记返回 `{ok:false, requiresStop:true}`，带标记则安全停止后原子保存
- `DELETE /api/apps/{id}` → `{ok}`（先停止再删，连同图标/日志）
- `POST /api/apps/{id}/start` → `{ok, pid}` / `{ok:false, error, health?}`（已运行则报错；启动前复查配置健康，明确失效返回 422；批处理启动后立即返回，由退出监视线程记录结果，快速成功任务不会被误判成启动失败）
- `POST /api/apps/{id}/stop` → `{ok}` / `{ok:false, error}`
- `POST /api/apps/{id}/restart` → `{ok, pid}` / `{ok:false, error}`（仅重启 token 校验通过的受管进程；等待旧进程退出后再启动，不自动 SIGKILL）
- `POST /api/apps/{id}/diagnose` → `{ok, issues:[{kind,title,detail,fix,action?}], summary}`（本地规则诊断，不调外部 AI：合并运行前健康检查，并覆盖依赖未装/模块缺失、npm 脚本名错误、运行时端口占用、权限不足、pip 包缺失与退出码兜底判读；前端在配置失效或运行失败时显示诊断入口）
- `POST /api/apps/{id}/attach` `{pid}` → `{ok, pid, cwdUpdated?, cwd?}` / `{ok:false, error}`（把已在监听配置端口的当前用户进程**认领**为本卡片受管进程：走 legacy 身份通道 lastPid+端口+UID+真实 cwd 四重校验，cwd 不一致时原子同步为进程实际目录；拒绝 task、无端口、已运行、非当前用户、他卡已认领与未监听该端口的进程。前端在端口诊断弹窗提供「认领为本卡片」）
- `POST /api/apps/{id}/icon`（body 为 png/jpg/webp 原始字节）→ `{ok, icon}`
- `POST /api/apps/{id}/favicon` → `{ok, favicon}` / `{ok:false, error}`（按有效端口抓站点图标：解析首页 `<link rel*icon*>`，兜底 `/favicon.ico`，支持 png/jpg/webp/ico/svg，存入 Application Support 的 `icons/fav-{id}.{ext}` 并写入 `app.favicon`；图标优先级：上传 icon > glyph > favicon > 名称首字，前端在无 icon/glyph 且运行中时自动触发一次）
- `DELETE /api/apps/{id}/icon` → `{ok}`
- `GET /api/apps/{id}/logs?tail=300` → `{text}`

### 总控台自身
- `POST /api/console/restart` → `{ok, pid, helperPid, port}`（先返回响应，再由独立 helper 等待旧进程退出并优先复用原端口；启动台应用不随总控台停止）
- `POST /api/console/stop` → `{ok, pid, port}`（响应发出后关闭总控台 HTTP 服务；启动台中已经运行的独立进程组保持运行）
- `POST /api/ui/theme` `{theme}` → `{ok, theme}` / `{ok:false, error}`（校验主题 id 存在后写入 `config.json` 的 `uiTheme`；主题清单由 `/api/state` 的 `themes` 字段返回）

### 静态
`GET /` → `static/index.html`；`/app.js`、`/js/*`、`/themes/*`、`/assets/*`、`/fonts/*` 等映射 `static/`；`/icons/xxx` → Application Support 的 `icons/xxx`。防路径穿越。

## 后端实现要点

- **执行方式**：应用可保存 `shell`，Windows 为 `cmd|powershell`，macOS 为 `bash`；旧配置 null/缺省保留 Windows CMD / macOS Bash。`shell` 随 `/api/state` 返回，属于运行中修改需先停止的生命周期字段。Windows CMD 写入 UTF-8 临时批处理（单 CRLF、`chcp 65001`、`/v:off`），自动生成路径的 `%` 转为 `%%`；PowerShell 5.1 通过 EncodedCommand 直接运行，保留原生退出码并将异常归为失败。锚点必须显式传递 stdout/stderr，避免 CREATE_NO_WINDOW 下子进程日志丢失。后台任务 stdin 为 DEVNULL，不提供交互终端。
- **Windows 健康检查**：CMD 简单命令按 Windows 双引号解析，保留反斜杠；PowerShell 仅检查明确的脚本路径，其余表达式/cmdlet 返回 unknown，不得按 Bash 或 PATH 错误阻断。项目识别候选包含对应 `shell`；`.ps1` 必须带解释器或使用 PowerShell 的 `&`。

- **平台适配层**：macOS 与 Windows 共用全部上层逻辑，平台差异收敛在少量同签名函数里（`IS_WIN` 分支）：扫描（`lsof`/`ps` ↔ `netstat`/PowerShell CIM）、受控进程模型（pgid ↔ PPID 后代树 + `tools/win_anchor.py` 锚点；锚点用 Toolhelp32 原生快照避免常态 PowerShell 轮询）、停止（`killpg` ↔ `taskkill /T[/F]`）、存活判定（`os.kill(pid,0)` ↔ OpenProcess+GetExitCodeProcess）、cwd（lsof ↔ PEB 读取）、文件选择框（osascript ↔ PowerShell WinForms）、实例锁（flock ↔ msvcrt.locking）、数据目录（`~/Library/...` ↔ `%APPDATA%`/`%LOCALAPPDATA%`）。修改平台相关代码时须保证两平台语义等价并在两平台跑测试。
- **端口扫描**：`lsof -iTCP -sTCP:LISTEN -P -n`（Windows：`netstat -ano -p tcp`），按 `(pid, port)` 去重（IPv4/6 重复行）。lsof 的 COMMAND 列会截断，名称以 ps 的 comm 为准。
- **进程详情**：批量 `ps -o pid=,user=,comm=,args=,%cpu=,%mem=,etime= -p <逗号分隔pid>`；只保留 `user == 当前用户`。
- **cwd**：`lsof -a -p <逗号分隔pid> -d cwd -Fn`，解析 `n` 行。
- **etime 解析**：`[[dd-]hh:]mm:ss` → 秒。
- **分组逻辑**（按优先级）：用户 `promoted` → `mine`；进程名含开发关键词（python node ollama docker 等，见 `DEV_KEYWORDS`，只匹配 name 不匹配 args，避免 VS Code `--ms-enable-electron-run-as-node` 这类误伤）→ `mine`（覆盖下方规则，Ollama/Docker 这类在 .app 内的守护进程仍算服务）；可执行路径含 `.app/Contents/`（GUI 应用及其 helper）→ `background`；comm 以系统路径开头（`/usr/libexec/`、`/usr/sbin/`、`/sbin/`、`/System/`、`/usr/lib/`）→ `background`；comm 或 cwd 含 `/Library/Containers/`（沙盒应用）→ `background`；其余默认 `mine`。`hidden` 仅是标记，照常返回。
- **关注进程**：`ps -axo pid=,uid=,comm=,args=,etime=,%cpu=,%mem=`，args 小写包含关键字即命中，只保留当前用户并排除自身及 ps/lsof。
- **应用状态**：每次启动生成随机 `runToken`，常驻外层 shell 在 argv 中持有标记并等待内层命令及其后台作业。新版进程只有同时命中 `lastPgid` / 当前 UID / token 的进程组才算 running；升级前缺少 token 的旧进程，只有配置 `lastPid`、监听端口、当前 UID 与真实 cwd 全部一致时才兼容认领。用户明确从服务监控认领的 `attached` 卡片允许监听子进程换 PID，但必须在配置端口上按当前 UID + 真实 cwd 唯一命中；任一条件不符仍按外部端口占用处理。`ports` 来自受控进程组成员实际监听的端口。
- **应用启停**：多张卡片可保存相同端口（例如多个默认使用 3000 的项目）；启动前只拒绝失效配置和当时真实被占用的端口。重启先做健康预检，失败时不会先停掉仍工作的旧服务。停止时先校验 token，然后只对该受控进程组发 `SIGTERM`，**绝不按端口杀其他监听者**。服务手动 stop 不记录退出历史；任务自然结束记录四态结果，总控台中止记录 `stopped`。批处理不做“长期服务存活探测”，避免把快速成功误判成失败
- **任务取消协议**：一次性任务内部的“用户主动取消”以退出码 **130** 通知总控台；0 表示成功，其余表示失败。不要通过日志文字猜测状态
- **配置健康**：`inspect_app_health` 只解析确定无歧义的简单命令并执行 stat/权限/PATH 检查，不执行命令、不展开变量/通配符。相对脚本按配置 cwd（空值时用户主目录）解析；复杂或动态命令返回 unknown
- **运行中编辑**：编辑面板打开时立即显示“停止服务”。点击只调用 stop，面板保持打开且当前草稿不变；停止成功后用户继续编辑并普通保存。名称/图标仍可在运行中直接保存。`stopBeforeUpdate:true` 保留为 API 客户端的原子停止更新能力，但不是默认前端流程。
- **无终端 PATH**：Finder/`LSUIElement` 启动不会读取 shell 配置；子应用启动环境需显式补入 `~/.local/bin`、Volta/Bun/pnpm、NVM/fnm、Homebrew 与系统 bin 目录，保证 `node`/`npm`/`pnpm` 等可用。启动 API 短暂探测立即退出，并把日志末行作为明确错误返回。
- **日志**：单文件超过 10MB 时 copy-truncate，保留 3 份轮转备份；日志 API 从文件尾部分块读取，不将整个日志读入内存。
- **keep-alive 陷阱**：POST start/stop 前端会带 `{}` body，handler 必须 `discard_body()` 读掉——否则残留字节污染同一 keep-alive 连接的下一个请求（method 解析成 `{}GET` → 501，前端显示断连横幅）。新增不读 body 的 POST 路由时同样处理。
- **运行目录**：默认配置/图标位于 `~/Library/Application Support/总控台`，日志位于 `~/Library/Logs/总控台`；`CONSOLE_DATA_DIR` / `CONSOLE_LOG_DIR` 可显式覆盖，覆盖时对应目录不自动迁移旧 `data/`。
- **配置**：读写加线程锁；写入用临时文件 + `os.replace` 防损坏；`schemaVersion` 逐版显式迁移；`.bak` 保留上一份良好版本。主配置与备份均不可读时进入只读保护，不覆盖原文件。
- **项目识别**：仅读取项目根目录下不超过 2MB 的已知配置/入口文件，不安装依赖、不执行配置、不扫描整个目录；显式 CLI 端口优先于框架默认端口。
- **kill 安全**：只允许结束当前用户的进程。

## 配置 schema

Windows 卡片独立管理：已登记子应用是启动者进程树的管理边界，检测、资源统计、脚本上下文和强制关闭共用该边界。关联前也按已保存身份识别子应用；不能只取消重叠检查而仍对父卡片整树关闭。Python/Node 服务以解析后的绝对脚本入口和有效参数匹配，cwd 用于解析相对入口，不要求绝对入口的启动目录一致。

WindowsApps 更新：窗口型实例规则、窗口重找、后台驻留及进程树边界预筛选统一使用 `ops_entries.same_window_executable`。只忽略当前 ProgramFiles/WindowsApps 包目录的四段版本号，保留包名、架构、资源标识、发布者和相对 EXE；实时 PID/创建时间/EXE 身份校验仍精确匹配。不要把这一规则扩展为任意版本目录或服务参数的模糊匹配。

服务卡片端口按钮和悬浮图标统一走 `/api/ops/window` 的 focus：服务停止时禁用，有端口的服务只复用网页窗口，不唤起原先关联的终端；无端口服务仍可唤起关联窗口。`service_web.py` 只在点击时识别网页：优先现有绑定和 RelaunchCommand；Chrome 应用窗口不一定有 RelaunchCommand，因此串行打开并记录新窗口的 HWND/进程身份/窗口属性绑定。安装的网页应用保留独立 AppUserModelID；普通 Chrome 应用 ID 不含端口，不能作为跨服务唯一身份。不将浏览器纳入服务关闭范围；普通浏览器标签页不做跨标签精确定位。

```json
{
  "schemaVersion": 1,
  "apps": [{"id": "8位hex", "name": "", "command": "", "cwd": null, "shell": null, "port": null, "emoji": null, "icon": null, "favicon": null, "kind": "service", "lastPid": null, "lastPgid": null, "runToken": null, "attached": false, "lastExit": null, "createdAt": 0}],
  "hidden": ["name:port"], "pinned": ["name:port"], "promoted": ["name:port"],
  "watchedKeywords": [],
  "uiTheme": "ops"
}
```

## 前端要求

### 文件夹与 Everything（schema 7）

- `file_tools.py` 承载 `/api/files/*`：GET `config`；POST `folders/save`、`folders/remove`、`folders/reorder`、`settings`、`search`、`open`。配置新增 `folders[{id,name,path,group}]` 和 `fileSearch{esPath}`，不混入应用记录。
- `static/js/folders.js` 与 `file-search.js` 配合 `static/files.css` 提供两个独立页面。配置仅进入页面和变更后读取；ES 搜索只在提交、排序、翻页时执行，禁止放进状态轮询。Ctrl+K 不增加文件入口。
- ES 1.1.0.37 的 `-search` 使用三重引号转义，不能直接把整条查询交给标准 Windows 参数转义；选项先构造为数组，再专门序列化最后的搜索参数，`shell=False`。标准输出使用 Windows 代码页，必须读取独立临时 UTF-8 JSON 导出，查询结束自动清理。
- 每页 100 条，使用 `-n offset+101`、`-viewport-offset offset`、`-viewport-count 101`；进程限时 8 秒，并发 2 个，上限 1000 页。结果通过 attributes 的目录位识别类型，不能逐项 stat 或递归扫描。配置迁移、输入边界、编码／分页与请求乱序测试见 `test_file_tools.py` 和 `tests/js/file-search.test.mjs`。
- QuickLook 试用接入：POST `preview {action:show|switch|close,path?}` 向当前用户已运行的 QuickLook 命名管道发送 UTF-8 消息；不启动第二套预览器、不执行待预览文件、不修改 QuickLook 配置。连接和写入有限时。列表鼠标/方向键选择、空格预览、Esc 关闭；请求串行且只保留最新待发项，搜索/翻页/离开页面时退出联动。方向键仅在当前页结果内移动。

### 原有页面

- 中文 UI，单页两视图（侧边导航：启动台 / 服务监控），每 2s 轮询 `/api/state`
- 添加服务时选择工作区文件夹后自动调用项目识别并展示候选命令；用户点选候选后再填入命令/端口。原有“选择脚本”与手动填写入口必须保留
- 编辑运行中服务时，表单内立即显示“停止服务”；停止操作不得关闭编辑面板或清除已经填写的内容，停止后恢复普通“保存”
- 批处理运行中显示实时耗时和「中止」入口；结束后明确显示成功/取消/失败/中止、距今时间与耗时。失败时突出日志入口；首次加载已有历史不重复提醒
- 停止状态下配置健康有阻断问题时，卡片显示第一项原因、禁用运行/启动并开放「配置与运行诊断」；运行中的停止/中止入口不得被健康问题禁用
- 服务监控只在当前页面会话连续轮询期间提醒新出现的、未管理的 mine 端口；首次加载、断线/后台/降级/重启恢复时静默建立基线。发现栏提供「加入启动台」「忽略并隐藏」「暂时关闭」
- 从服务监控或新端口发现点击「加入启动台」时，项目识别完成前不得保存；创建请求必须携带 `attachPid`，由后端原子完成卡片创建与来源 PID 认领，失败时不留下“已创建但未认领”的半成品卡片；成功后卡片直接显示运行中
- DOM 按 key 原地更新，禁整列表重绘闪烁；fetch 失败显示断连横幅
- 深浅色跟随系统 + 手动切换（localStorage `console-theme`）；**极简 / Apple / 素材包主题**（`ops.css` 保留原外观；`apple.css` 导入原主题并覆盖材质令牌，使用本地建筑壁纸与 vendored WebGL 玻璃；`#themeCss` 整包加载，切换失败回滚）；字体 = macOS 系统字体栈 + Geist Mono（数据/代码）；顶栏品牌图标 = `static/assets/brand-mark.png`；UI 零 emoji
- 动效：卡片入场 stagger（`--d`）、hover 浮起、模态/抽屉缓动、按键下压回弹、`prefers-reduced-motion` 降级
- 危险操作（结束进程/删除应用）必须确认
