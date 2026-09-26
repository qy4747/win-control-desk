# 主题与结构边界

主题由页面的 `#themeCss` 加载，设置中心可切换：

首屏由服务器读取已保存的主题，直接在 HTML 中输出 `data-ui-theme` 和对应的样式路径（包括素材包路径），无需等待 `/api/state`。`js/theme-startup.js` 在样式表之前同步恢复深浅色与水汽偏好；应用初始化优先沿用 HTML 中的主题，避免旧浏览器缓存把首屏切回极简。

- `ops.css` / `ops.json`：极简，默认主题 id 为 `ops`。
- `apple.css` / `apple.json`：Apple，导入极简主题样式后覆盖视觉令牌和材质，复用页面布局与状态。
- `rain.css` / `rain.json` / `rain.js`：雨境，雨夜庭院壁纸、水滴动效和 WebGL 折射，复用各页共用布局。
- `selector.css`：所有主题共用的设置选择器外观。
- `elements.css`：素材主题的共用样式；`packs/<包名>/theme.json` + `theme.css` 自动注册，包内素材独立。
- `packs/journal/`：“手账素材”占位示例；复制文件夹并替换图片与配色即可新增同类主题。完整尺寸与交付规范见 [素材包制作说明](packs/素材包制作说明.md)。

`js/appearance.js` 复用 `core.js` 的注册表、串行主题切换、持久化与失败回滚。导航选中条使用临界阻尼弹簧，改变目标时保留当前位置与速度；按钮按下即时反馈。现有卡片翻面、拖拽、场景长按时机不变。

Apple 的建筑壁纸是本地 `assets/apple-architecture.png`，由 Imagegen 生成现代石材与玻璃建筑背景。导航轨、顶栏和场景栏采样同一壁纸，使用 `vendor/liquid-glass/src/` 的 WebGL2 折射；MIT 许可保留在 vendor 目录，来源核实状态见 [第三方声明](../../THIRD_PARTY_NOTICES.md)。最多 3 个上下文，`maxDpr: 1.5`、`live: false`，静止时不持续绘制；应用列表使用 CSS 轻磨砂。

离开 Apple 时销毁画布和背景节点；深浅色更新现有材质。WebGL 不可用时回退 CSS；减少透明度或提高对比度时销毁 WebGL 并使用实底，减少动态效果时导航直接定位。不能给大批量卡片逐一创建 WebGL 上下文。

设置中心可更换 Apple 壁纸或恢复默认，支持最大 5 MB 的 PNG/JPEG/WebP；上传前浏览器解码验证，后端复用图片签名、体积和同源会话校验。自定义文件原子保存为配置目录下的 `apple-wallpaper`，通过 `GET/POST /api/ui/wallpaper` 读取/上传，`POST /api/ui/wallpaper/reset` 恢复默认。壁纸解码后替换背景并更新现有 WebGL 材质，刷新后仍保留。Apple 页面容器不做透明度入场动画，避免动画期间隔断子元素的背景模糊采样。

雨境使用一个共享 WebGL 画布，预加载视口上下 160px 内的表面，超过 16 个时由渲染器分批绘制，避免滚动时突然切换 CSS 材质。DPR 上限 1.25，按滚动和页面变化更新；选中控件使用局部光圈，卡片悬停以 160ms 过渡改变水膜光影，不改变整页光照。折射采样距离上限 24px、各表面霜化半径上限 3px，避免长日志面板边角过度扭曲。空目标时销毁玻璃层，避免把全屏宿主渲染成玻璃。退出主题销毁画布、监听器和背景节点。减少动态效果时关闭雨滴及水膜位移；减少透明度或提高对比度时使用实底。WebGL 创建失败时保留 CSS 材质。

本地 vendor 的 `src/dom.js` 渲染行为：表面 id 随 DOM 元素保持稳定；固定视口壁纸在卡片滚动时复用纹理，仅更新表面坐标；更新目标列表不再强制重设画布尺寸。滚动事件直接更新目标列表，不额外排一帧；目标更新及尺寸观察器的 `refresh({ backdrop: false })` 不重新采样固定壁纸，避免停下后再补一次背景/光照。宿主尺寸、背景来源或样式变化仍会重绘背景，非固定背景沿用原来的更新方式。雨境背景图的透明度由媒体采样读取 CSS，不重复叠乘。

共享画布按每个目标的祖先滚动区域求交集，完全越界的目标不绘制，部分越界使用 WebGL scissor 裁掉输出，保留原始透镜形状和采样坐标。同一裁剪范围的目标分批绘制，顶栏与导航不套用 `.main` 的裁剪范围。Apple 和雨境壁纸都只读取一次 CSS 透明度。

雨境显式保留停止按钮的警示色、异常卡片边框、当前场景底线和待切换场景虚线；剪纸也保留未选中当前场景的底线，避免材质规则覆盖状态提示。

雨境设置同样提供「更换壁纸／恢复默认壁纸」，复用壁纸接口并传 `?theme=rain`，独立保存为 `rain-wallpaper`；省略主题仍操作 Apple 壁纸。更换后先解码，再同时更新背景和折射采样。默认开启轻微「背景水汽」，可关闭，选择保存在当前浏览器的 `console-rain-mist`。水汽仅影响背景和玻璃采样，不模糊文字与按钮。卡片的非对称水膜外沿采用 CSS 绘制，内部折射仍使用共享 WebGL 表面。

雨境壁纸为 `assets/rain-courtyard.webp`（1672 × 941，约 587 KiB），由用户认可的雨景原型通过 imagegen 去除 UI 后生成，再转换为 WebP。素材提示词：

> Edit the provided reference into a CLEAN PHOTOGRAPHIC BACKGROUND ASSET for a desktop app. Remove EVERY piece of interface: all cards, glass panels, capsules, buttons, navigation, icons, app logos, text, branding, numbers, and typography. Also remove writing/signage from the wall, mug and stone. Reconstruct the architectural rainy courtyard underneath them coherently. Preserve the original blue hour rainy modern city courtyard composition and photographic realism, rain on the foreground window, trees, wet reflective stone pavement, soft warm windows and distant buildings. Keep the dark architectural mullion near the left, a subtle cafe table and plain black mug lower left, low stone wall and warm lantern lower right. The central majority should be rain-soaked scenery with visually calm midtones, no dominating foreground object. Wide 16:9 composition target 2560x1440 or maximum available landscape. Beautiful natural rain droplet highlights and restrained warm reflected light. No UI or glass interface objects anywhere, no text or watermark. This is the original rainy scene rebuilt behind the removed UI, not a new unrelated scene.

## 放在主题内

- 颜色、背景、字体、字号、字重、行高、字距。
- 边框、圆角、阴影、焦点环和图标着色。
- 运行、告警、选中、禁用、悬浮等状态的外观；状态本身仍由 JS 设置。
- 动效关键帧、过渡、视觉时长和缓动。JS 驱动的翻面和拖拽从主题变量读取这些参数。
- 图标光晕的配色公式。JS 只提供图标采样色 `--icon-color` 和应用标识派生的 `--icon-hue`。

文件末尾按原来的 `base.css → ops.css → files.css` 顺序收纳各组件视觉规则，保留原选择器、媒体条件和覆盖顺序。仅仅使用了 `var(--accent)` 的颜色声明也属于视觉规则，应放在主题内。

## 留在结构与行为层

`static/base.css`、`static/ops.css`、`static/files.css` 保留网格、尺寸、间距、定位、滚动、响应式布局、文本截断、显隐和点击区域。它们在主题后加载；若要改变信息布局或卡片尺寸，需要同时修改对应结构文件，不能只在主题里用相同优先级覆盖。

JS 保留应用开关、前台、选择和翻面时机，以及实时坐标、百分比、成员数量等数据。运行时写入的进度宽度、拖拽位移、浮层避让位置属于这些数据，不移成固定样式。

可访问性是例外：隐藏但可读的文本裁剪、触屏按钮可见性和系统强制颜色模式的焦点保护保留在 `base.css`。

## 动效约定

- `--card-flip-*-ms`、`--reorder-duration-ms`、`--drop-duration-ms` 是毫秒数值，不带单位。翻面等待动画完成；拖拽清理时机跟随主题时长。
- 长按关闭仍为按下 200ms 后开始蓄力、1000ms 时执行。主题中的 `.8s` 蓄力动画对应中间的 800ms；换皮可改颜色和形状，不能只修改动画时长而让它与操作判定脱节。
- `prefers-reduced-motion` 的降级和可见焦点不能删除。
- 应用图标图片、SVG 路径属于内容素材，不是主题配色。

## 验证

主题行为检查：`node --test tests/js/appearance.test.mjs tests/js/theme-boundary.test.mjs tests/js/card-flip.test.mjs tests/js/views.test.mjs`。注册表、预览、资源引用和素材指纹使用 `python tools/check_project.py --skip-tests` 检查。

浏览器使用 `tools/ui_demo.py` 的假数据，检查主题回切、刷新持久化、深浅色、各页导航、卡片与浮层、窄屏、焦点、无 WebGL 回退及减少透明度/动态效果。Apple 页面最多 3 个画布，退出主题后应释放。实际结果与未验证项按测试环境记录。
