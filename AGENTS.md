# 开发约定

Windows 是主要验收平台；macOS 保留兼容入口，平台差异按实际验证结果说明。
运行环境为 Python 3.12+ 标准库和原生 HTML/CSS/JavaScript，无前端构建或 CDN。
本仓库独立维护，不主动同步上游；保留原作者版权和第三方许可。

## 开始工作

- 安装、使用和数据目录：[README](README.md)。
- 模块、API 与配置入口：[开发说明](docs/development.md)。
- 修改原则与检查命令：[参与贡献](CONTRIBUTING.md)。
- 主题结构：[主题说明](static/themes/README.md)；页面预览：[UI 演示](docs/ui-acceptance.md)。

## 关键约束

- 保留回环绑定、Host、控制令牌、当前用户及进程身份校验；不得仅凭名称或端口认领、结束进程。Origin/Fetch-Site 不按来源值拦截，带浏览器来源标记的请求仍须有效控制会话 Cookie。
- 启停、资源统计和窗口操作遵守独立子卡片边界；正常关闭失败不能自动升级为强制结束。
- 配置格式变更要提供逐版迁移和备份恢复检查；保留原子写入及损坏/未来版本配置的写入保护。
- 不直接改写运行中的用户配置。截图与页面演示使用 `tools/ui_demo.py`，提交内容按 [脱敏规则](SECURITY.md#脱敏规则) 处理。
- 主题负责视觉，结构层负责布局和交互；保留键盘操作、可见焦点和减少动态效果支持。
- 图标从 `static/icons/*.svg` 用 `tools/gen_icons.py` 生成，不直接编辑 `static/icons.js`。
- 发布、Tag、仓库可见性及历史重写按用户明确授权执行。

## 验证

按 [CONTRIBUTING.md](CONTRIBUTING.md#检查) 选择与改动相关的检查。纯文档修改核对事实、链接和示例；代码修改运行项目检查，涉及 Windows 原生行为时补充对应实机验收。macOS 的结果单独记录，不要求每次修改都完成双平台验收。
