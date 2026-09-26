# 参与贡献

项目处于 Preview / Alpha，Windows 是主要验收平台，macOS 保留兼容入口。欢迎范围清晰的改进。

## 开始之前

先搜索已有 Issue 和 Pull Request。较大的功能、配置格式或进程管理策略变更，先开 Issue 说明场景和兼容性影响。安全问题按 [SECURITY.md](SECURITY.md) 私下报告，日志、示例和附件遵循其中的[脱敏规则](SECURITY.md#脱敏规则)。

## 开发环境

- Python 3.12 为检查基线；运行时支持 3.12+，仅依赖标准库。
- Node.js 用于 JavaScript 语法和行为检查，不参与日常运行。
- 前端使用原生 ES Modules，无构建或 CDN。

Windows 启动方式见 [README](README.md)，模块与配置入口见 [开发说明](docs/development.md)。

仅重新生成图片时需要 `requirements-dev.txt` 中的依赖；请在虚拟环境中安装。生成品牌 `.icns` 还需 macOS `iconutil`。

## 修改原则

- 保留请求授权、当前用户和受控进程身份校验；不得仅凭名称或端口结束未知进程。
- 配置格式变更提供逐版迁移及升级检查，保留原子写入、备份与损坏保护。
- 列表按 key 更新，保留键盘操作、焦点和危险操作确认。
- 视觉样式遵循 [主题说明](static/themes/README.md)。
- 修改 `static/icons/*.svg` 后运行 `py -3.12 tools/gen_icons.py` 生成 `static/icons.js`。

## 素材与许可

新增或替换素材时，更新 [素材台账](ASSET_PROVENANCE.md) 的路径、来源、用途、许可与 SHA-256；未知信息如实标注。第三方素材按需补充 [第三方声明](THIRD_PARTY_NOTICES.md) 和许可原文。发行素材不得处于 `BLOCKED` 或 `TO_REPLACE` 状态。

## 检查

按改动范围选择检查，并在 PR 中记录实际结果：

- **纯文档**：核对事实、相对链接、示例和术语一致性。
- **代码**：运行项目检查；Windows 原生行为变化补充对应实机验收。macOS 结果单列。
- **发行范围、许可、素材或打包**：补充发行检查；完整发布步骤见 [发布核对表](RELEASE_CHECKLIST.md)。

```powershell
py -3.12 tools/check_project.py
py -3.12 tools/build_release.py --check-only
# 发行检查需先提交到干净工作树：
py -3.12 tools/check_project.py --release
```

Windows 不需要 Make；macOS 可使用 `python3` 或 `make check` / `make release-check`。仓库未配置 GitHub Actions，以上检查在本地运行。

UI 演示与截图使用 [假数据服务](docs/ui-acceptance.md)。可选的 `tests/bridge-control-mode.ps1` 需显式传入可信 Bridge 脚本路径；后台性能测量入口见 [开发说明](docs/development.md#验证入口)。

## 提交与变更记录

一个 PR 解决一个主题，说明改动、验证结果和必要的兼容性影响。UI 改动附相关截图；使用真实作者身份，保留原作者署名。

用户可感知的功能、安全或兼容性变化写入 [CHANGELOG.md](CHANGELOG.md) 对应版本，使用 Added、Changed、Fixed、Removed 或 Security 分类。纯文档和不影响行为的内部调整无需更新版本说明。

贡献内容按根目录 [LICENSE](LICENSE) 及相应素材许可分发。参与项目须遵守 [行为规范](CODE_OF_CONDUCT.md)。
