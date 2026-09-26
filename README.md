# Win Control Desk · Windows 总控台

**Windows 优先 · Preview / Alpha · 源码分发**

把常用桌面应用、服务、脚本和文件入口放到一个本机控制台：保存卡片，查看状态和资源，按需启动、正常关闭、唤到前台，或者执行一组事先确认的操作。

项目基于 [pisceslailai/local-ops-win](https://github.com/pisceslailai/local-ops-win)，原始项目为 [laogou717/local-ops](https://github.com/laogou717/local-ops)。保留原作者版权、MIT LICENSE 和第三方许可；不是原项目的官方发行，不承诺同步上游。

后端使用 Python 标准库，前端是原生 HTML/CSS/JavaScript，无前端构建、运行时 pip 依赖或 CDN。源码 ZIP 不是独立 EXE/安装器，Windows 启动脚本和保留的 macOS `.app` 都需要完整源码目录及本机 Python。

## 能做什么

- **启动台**：固定应用/服务/任务卡片，分类标签抽屉、拖拽与键盘排序、正反面操作、自定义命令/回环 HTTP/网页/位置入口。桌面实例按身份识别，浏览器主窗口与 PWA、网盘启动参数分别处理，不靠名字或端口随意认领。
- **应用包与场景**：应用包中的独立项失败后继续；场景先停止再启动，某步失败后不继续切换。取消只取消后续操作，不回滚已经执行的动作，也不持续强制维持应用状态。
- **观察与异常**：进程树资源、监听服务、CPU/内存/显存、磁盘与目录增长、异常详情、忽略/恢复、日志与配置诊断。未知数据不当作零或已停止；不会自行重启或强杀异常应用。
- **文件入口**：文件夹收藏、分组、路径复制；可选 Everything CLI 搜索与 QuickLook 预览。外部工具需另行安装，Everything 服务须运行，CLI 路径在设置中指定；它们不是启动控制台的必需依赖。
- **主题**：极简、Apple、雨境、青瓷、剪纸和 Journal 素材框架；支持浅色、深色和系统外观。主题包与业务功能分离；WebGL/原生窗口行为仍需在目标电脑验收。

详细规则与接口见 [Windows 使用说明](docs/windows-entry.md)。

## 界面预览

以下为当前页面配合隔离演示服务的截图，全部使用虚构卡片/状态，不包含个人配置或真实进程信息，不代表真实应用控制已经验收。

| 启动台 | 服务监控 |
| --- | --- |
| ![启动台演示](docs/screenshots/ops-launchpad.jpg) | ![服务监控演示](docs/screenshots/ops-services.jpg) |

## Windows 安装与启动

需要 **Windows 10/11 x64、Python 3.12 或更高版本**，以及近期版本的 Chrome 或 Edge。本地开发检查的 Python 验证基线为 3.12；更高版本和其他浏览器不自动视为已验证。前端使用 ES Modules、Popover、inert 等现代浏览器能力；仅“支持 ES Modules”不代表覆盖全部功能。

### 获取完整源码

安装 Git 的电脑可运行：

```powershell
git clone https://github.com/qy4747/win-control-desk.git
cd win-control-desk
```

也可以在本仓库 **Code → Download ZIP** 下载源码，解压到固定可写目录，例如 `D:\Apps\win-control-desk`。不要在压缩包内部直接运行，不要只复制 `start.bat` 或 `server.py`。

### 安装 Python，启动控制台

从 [Python 官方 Windows 下载页](https://www.python.org/downloads/windows/) 安装 Python，并安装 Python Launcher 或把 `python` 加入 PATH。先在 PowerShell 验证：

```powershell
py -3.12 --version
# 没有 Python Launcher 时：
python --version
```

双击根目录 **`start.bat`**。启动器优先 Python 3.12，再接受其他不低于 3.12 的已安装 Python；缺少合适运行时会返回明确错误，不写入配置。排错时请从 PowerShell 运行脚本以保留输出：

```powershell
.\start.bat
# 或显式选择运行时：
py -3.12 server.py --no-browser --preferred-port 9603
```

后端只绑定 `127.0.0.1`，在 9600–9609 中选择可用端口；以终端/控制台日志和实际页面显示为准。手动访问 `http://127.0.0.1:实际端口/`。`--no-browser` 只禁止自动打开网页，不改变后端功能。

普通使用不要求安装 Chrome 专用应用窗口工具。仓库中的独立窗口/快捷方式辅助脚本属于可选入口；Chrome 应用窗口模式依赖本机 Chrome，不能用它代替基础安装步骤。

## 第一次使用与操作边界

从“添加”保存一个明确的启动命令，或从运行对象中选择需要关联的应用。未识别出可靠启动命令的观察卡片可以保留，但不能凭空重新启动。

服务卡片右侧按钮用于已验证的窗口/网页入口；停止、状态未知或没有可用入口时置灰。下方最多两个专用按钮，其余在背面。显式移除的按钮不会因重新渲染被自动补回。目录入口默认不依赖应用运行；命令动作可限制为运行中可用。

正常关闭优先走配置的退出动作或已验证窗口的正常关闭；失败会保留身份，不自动升级为强制结束。强制结束需要单独确认，操作前核对进程身份、当前用户、创建时间和所有权。

**关闭网页不等于停止控制台；停止控制台不等于停止受管应用。** 后台监控在网页关闭后仍可运行。设置中心的停止/重启控制的是控制台自身；应用卡片控制的是对应应用。

控制台能以当前用户权限执行保存的命令，只应导入可信配置。不要通过监听地址、反向代理、隧道或端口映射把它暴露给局域网或公网；回环地址不替代 Host、Origin 和控制令牌校验。

## 数据、备份、升级与卸载

Windows 默认配置和图标位于 `%APPDATA%\总控台`，日志位于 `%LOCALAPPDATA%\总控台\Logs`。`CONSOLE_DATA_DIR` / `CONSOLE_LOG_DIR` 可指定独立绝对目录。项目内 `data/` 在符合迁移条件时复制到默认位置，源文件保留。

升级前停止控制台自身，备份完整配置/图标目录和所需日志，再更新完整源码目录；Git 用户先确认自己的工作区没有未提交改动。不要把个人运行目录提交到 Git。配置迁移会保留备份；程序拒绝写入超出其支持范围的 schema。恢复备份时，代码和配置应配套恢复。

卸载时先停止控制台，再由自己决定是否删除源码、配置和日志。需要停止受管应用时单独操作；本项目不会为了卸载而批量结束个人应用。Windows 通知可能创建用户级 `Cddeck 总控台.lnk` 身份快捷方式；不设置系统服务或开机启动，删除入口不会删除应用配置。

可选 `tools/launch_console.py` 入口使用项目内 `data/` 和 `data/logs/`，与 `start.bat` 的默认目录不同；切换入口前确认正在使用哪一份配置，不能把路径变化误当成数据丢失。

当前配置 schema 为 **8**，仅表示数据格式；产品版本以根目录 `VERSION` 为准。

## 平台与维护

本仓库以 Windows 的日常行为作为验收目标，提供 `start.command` 和 `.app` 作为 macOS 兼容入口。Safari、签名/公证和真实 macOS 桌面行为未完成全面验证；Windows 原生窗口、通知、Everything、QuickLook 不承诺跨平台等价。

个人维护，迭代以实际需要为主，不承诺 PR 审阅、合并或固定发布周期。普通问题使用本仓库可用的 Issue 入口；安全问题遵循 [SECURITY.md](SECURITY.md)，不要提交原始配置、令牌、个人路径或未脱敏截图。Discussions 等入口只有实际启用时才适用。

## 开发、验证与源码打包

本仓库不配置 GitHub Actions 自动检查，检查和测试在本地按需运行。开发检查还需要 Node.js；它不参与后端日常运行。Windows 不需要安装 Make：

```powershell
py -3.12 tools/check_project.py
py -3.12 tools/build_release.py --check-only
# 提交到干净工作树后：
py -3.12 tools/check_project.py --release
# 只读扫描当前跟踪文件，以及准备公开的可达历史：
py -3.12 tools/audit_public_tree.py
py -3.12 tools/audit_public_tree.py --history --refs main
# 生成源码 ZIP（不是独立安装包）：
py -3.12 tools/build_release.py
```

macOS 可用 `python3` 或 Makefile 入口。检查覆盖语法、主题包及引用、素材指纹、Python/JavaScript 测试和源码发行范围，保留完整失败输出。模式扫描不代替图像和 Git 元数据审阅。

仅重新生成图片时才需 `requirements-dev.txt` 中的开发依赖；品牌 `.icns` 派生工具还依赖 macOS `iconutil`。不要为了运行项目安装这些开发组件。

安全的页面演示入口：`py -3.12 tools/ui_demo.py --port 9610`，操作说明见 [UI 演示与验收](docs/ui-acceptance.md)。它仅使用内存假数据，不读取个人卡片，不执行真实应用动作。`tests/bridge-control-mode.ps1` 是可选的外部 Bridge 集成检查，必须显式传入可信脚本路径，不属于项目的自动测试或安装依赖。

## AI 助手 Skills

源码自带两份可选 Skill，供支持读取本地文件和执行项目命令的 AI 助手使用；不影响控制台独立运行，也不会自动安装到你的全局环境。

| Skill | 用途 |
| --- | --- |
| [win-control-desk-apps](skills/win-control-desk-apps/SKILL.md) | 发现目标应用、配置卡片的启动命令、位置、按钮和窗口关联；通过本机 API 备份后保存。 |
| [win-control-desk-skins](skills/win-control-desk-skins/SKILL.md) | 依照现有主题包规范制作皮肤、浅深配色、图片和预览，登记素材来源并做针对性检查。 |

**直接使用**：在 AI 助手中打开本项目，让它读取对应的 `SKILL.md` 并执行具体任务，例如：

> 阅读 `skills/win-control-desk-apps/SKILL.md`，把我当前运行的某个应用加入总控台，并配置项目目录入口。

> 阅读 `skills/win-control-desk-skins/SKILL.md`，新增一套深浅色都可用的木质皮肤，保留已有布局和操作方式。

**安装为常用 Skill**：按你使用的 AI 客户端说明，将所需 Skill 的完整目录（含 `references`）复制到它支持的项目级 Skills 目录，再按客户端方式刷新或启用；不要只复制 `SKILL.md`。安装到其他工作区时，在任务中指定本项目的源码根目录。源码 ZIP 同样包含 `skills/`。

应用接入需要已启动的本项目实例，地址和数据目录以实际运行状态为准；配置卡片不会自动试启停你的应用。皮肤预览优先使用内存假数据服务。图片生成能力由所用 AI 环境提供，不是运行项目的必需依赖。

## 分发与许可

项目按源码分发，包含运行代码、主题素材、本地检查工具和 Skills。发布前使用 [发布核对表](RELEASE_CHECKLIST.md) 核对内容、隐私、许可及实际验证结果。

保留 [MIT LICENSE](LICENSE) 原始版权。Lucide、Geist Mono、Liquid Glass 及图像的具体来源和未核实项见 [第三方声明](THIRD_PARTY_NOTICES.md) 与 [素材台账](ASSET_PROVENANCE.md)。Apple 技能用于设计指导，不是官方素材或第三方代码许可证。
