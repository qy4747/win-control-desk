# 素材来源与当前指纹

只登记能够核实的来源、用途、许可文件和当前 SHA-256；未知的生成日期、模型、上游版本或凭证不补写。路径与对应指纹须在同一行，覆盖运行图片、字体、AppIcon 和主题包图片/预览。自动检查不代替人工审图或权利判断。

状态：`CLEARED` 表示本节来源已确认并保留对应声明；`REVIEW_REQUIRED` 表示仍有明确缺项，检查会提示但不伪装成已核实；`BLOCKED`、`TO_REPLACE` 禁止正式发布。

### Lucide 图标
- 状态：`CLEARED`
- Lucide 0.544.0；随库 `licenses/Lucide-LICENSE.txt` 包含 Lucide/Feather 版权与许可。图标由 `tools/gen_icons.py` 生成到 `static/icons.js`，一致性由项目检查器核对。

### Geist Mono 字体
- 状态：`REVIEW_REQUIRED`
- Vercel Geist Mono；随库 OFL 1.1 原文：`licenses/Geist-OFL-1.1.txt`。原始下载提交与精确版本未记录。
- `static/fonts/GeistMono-Variable.woff2` — SHA-256 `fba8f577f38a2bbcbe818efa6348dd58f36303a10b8737c42fefad275be563ab`

### 品牌图标
- 状态：`REVIEW_REQUIRED`
- 主图登记为 Imagegen 生成，派生为 favicon、触摸图标、品牌标记和 AppIcon；原始生成日期、模型和凭证未确认。
- 派生流程由 `tools/gen_brand_assets.py` 提供。
- `static/assets/apple-touch-icon.png` — SHA-256 `1108214aa511f206409c2daf7a3f7ac318dd4d2554a95476f2f606bfe8b49621`
- `static/assets/brand-mark.png` — SHA-256 `44644d14d7e3cf91808fa2f03e7735f7f4a9ab6c635f29eb98cf7ad4c85eaa0f`
- `static/assets/console-app-icon.png` — SHA-256 `464d5ed1ca52d33c64de4f004df126f280f27f20346620ef0b2e6cb4143ccec3`
- `static/assets/favicon-32.png` — SHA-256 `6c1c34a718d9f26737fc1edc2a1a1fd3838e66826e0a19284e116449f031abbb`
- `static/assets/favicon.ico` — SHA-256 `71b9aa89ea479762f7ed7c54a665c88ef7786089523417119292d446ea12648d`
- `总控台.app/Contents/Resources/AppIcon.icns` — SHA-256 `3ed34bba75ec6a2440d44d9c254ee079ac72b7f2bbc1605a873472131cf56568`

### 主题 Imagegen 图片及派生成品
- 状态：`CLEARED`
- 主题图片来自 Imagegen；Apple 技能用于设计/实现指导，不是图片来源、Apple 官方素材或代码许可。
- Apple 建筑与雨境庭院用作背景；剪纸、青瓷的图片用于纹理、卡片、装饰与主题预览。裁切、透明底处理、缩放和格式转换沿用仓库现有成品。原始个人工作区不随仓库公开；不编造生成日期、模型版本或独占权保证。
- `static/assets/apple-architecture.png` — SHA-256 `dc494d4a12cddda0a6d015af68e720c4ef794bcf0704912835f38b0d994329e4`
- `static/assets/rain-courtyard.webp` — SHA-256 `c441f570fa5966d49cd403ee1d17964509583b3d3d3fc21d2104c88c78869717`
- `static/themes/packs/celadon/assets/bead.png` — SHA-256 `b8a53bbc682d7738174db72ba38bab6fa4b47a3371bda857d88d9bb98f63b541`
- `static/themes/packs/celadon/assets/card.png` — SHA-256 `b86865a3ca44e8d4b6843ef4925d539dd3dc162ae2bcedf78460365120453bc7`
- `static/themes/packs/celadon/assets/glaze.webp` — SHA-256 `912040a7f102644b31a567fa4d222fd0d41673c40385bfd5ac791818515a6ff6`
- `static/themes/packs/celadon/assets/seal.png` — SHA-256 `f2edf96fd5f4d3fa334ae965e6501f211d1940096cf4292812eef6ac5b912a41`
- `static/themes/packs/celadon/assets/strip.png` — SHA-256 `6e725a3203917309b3893c2118b108b6f4ef7ce4b3a6dac5c4166b4d3a6650db`
- `static/themes/packs/celadon/preview.png` — SHA-256 `6df0d403c20d89e7fdd8ea84160daa2b1d173a8cb34259b574d20cb5309e0605`
- `static/themes/packs/papercut/assets/binder.png` — SHA-256 `fea8e975a6f1c6a0c5aa6d1975fc9e04a8e16b0740085317d4c50bdb7c0065b8`
- `static/themes/packs/papercut/assets/card-perforated.png` — SHA-256 `72351015750b6fa358bb52b7e819a3469066795352cabcbae05efbebb47bfa76`
- `static/themes/packs/papercut/assets/card.png` — SHA-256 `d1c4c610f25806e2f17d64c21954f63e5d8a422f44f26b0dd3814686c731d7d3`
- `static/themes/packs/papercut/assets/clip.png` — SHA-256 `0c6c7d891099eb8b1c32219ecf63cfc1ea4593e3b64bf260e1b1de0e912ff264`
- `static/themes/packs/papercut/assets/paper.webp` — SHA-256 `30ff8354a043c7f3033d825cf701e22215553e8372d43d66648072bea89d8127`
- `static/themes/packs/papercut/assets/pin.png` — SHA-256 `86c2aa4afea9f33a9074b4dfe26be6e7f02292fee5bf0b85f02b27fab1be84ce`
- `static/themes/packs/papercut/assets/strip.png` — SHA-256 `cc44016fe7c4a69c5716c907afa813fe005bad7f592885a53d645fca531fd175`
- `static/themes/packs/papercut/preview.png` — SHA-256 `d1c4c610f25806e2f17d64c21954f63e5d8a422f44f26b0dd3814686c731d7d3`

### Journal SVG 素材框架
- 状态：`CLEARED`
- 仓库内以 SVG 几何图形、渐变和纹理定义实现的素材框架/预览，随项目代码维护，不引用外部图片 URL。适用项目 MIT 声明。
- `static/themes/packs/journal/assets/background.svg` — SHA-256 `ea9ab473317809fc2c26e5551fc7c84a0c383e3fd78e405c69910dc21db00462`
- `static/themes/packs/journal/assets/card.svg` — SHA-256 `f36bd1afe83084b69ef834b74ede6776394e0597adad25fe554f9005a91064d0`
- `static/themes/packs/journal/assets/chrome.svg` — SHA-256 `87af04b9c5eb6a5b29dd1b7b72c4c3ae771952d6d178d8ace6ec0c51a44619af`
- `static/themes/packs/journal/assets/control.svg` — SHA-256 `2d3ae73a31f9c90733d853f9263575b6e562d8e06a5dd6b0448c0eaef42e5b22`
- `static/themes/packs/journal/assets/corner.svg` — SHA-256 `c842302317e4eba7ecb69d58314cdd8257c24934ec287b2c624f6943bfabfe4d`
- `static/themes/packs/journal/assets/decor-a.svg` — SHA-256 `aa9de6075cb1ad779e9123fbe9b267cf259576819b3bb738acab0a7669d6fa7b`
- `static/themes/packs/journal/assets/decor-b.svg` — SHA-256 `3610a09f78df6db1fa5a1be897390d57b4f147628f151b4be934c96e1bcf75f2`
- `static/themes/packs/journal/assets/decor-c.svg` — SHA-256 `e857c9ab52c2fe52fa673a462ef565fb5e4830cb3c9a641d0983d10de002cfb5`
- `static/themes/packs/journal/assets/frame.svg` — SHA-256 `97f2393fe7670f0cb340020ca6d26f41d70dbc8b0b46721fd1efaf7eab691884`
- `static/themes/packs/journal/assets/label-frame.svg` — SHA-256 `2305cbac66a39026025490a48ce87ea84041e2b6dd2022ae8e273dbdb9909bd6`
- `static/themes/packs/journal/assets/panel.svg` — SHA-256 `8c1f9437b4eb436a10be5409f73fa6e1828cc86680053d74f36f6e031e946fc6`
- `static/themes/packs/journal/preview.svg` — SHA-256 `ed7246950ed1e3af4339683f503a5a1ec8c1e4d9c9bafd85b8c47d78bcec0715`

### README 界面截图
- 状态：`CLEARED`
- 来源：本仓库页面在 Edge 中的实际截图，1440 × 960，使用 `tools/ui_demo.py` 的虚构演示数据；不读取个人配置，保留底部演示标识。Apple 与雨境加载随库默认壁纸。
- 用途：README 主题对比与服务监控预览。界面代码适用项目 MIT 声明，截图中的字体、图标及主题素材沿用本台账与第三方声明中的对应来源和许可。
- `docs/screenshots/apple-launchpad.jpg` — SHA-256 `398474ae8502bdcbfb76f44552e8fb339e780a3bdff165bb4b6eaefaa175dd6e`
- `docs/screenshots/celadon-launchpad.jpg` — SHA-256 `776b760f89775ff6c04c1fcf55abfd5f0d2def6176af7e6e2e71a8920602e57e`
- `docs/screenshots/journal-launchpad.jpg` — SHA-256 `e4ce66113c563bba6a5dcf3ee468582a5e298548c46dd815b3a6bd6f73a900f5`
- `docs/screenshots/ops-launchpad.jpg` — SHA-256 `d8ce0631c5c7bc85f312890f90151946b5131825a3cd0f6ad1227e6ddeca586d`
- `docs/screenshots/ops-services.jpg` — SHA-256 `4e95b7d038362bc2898bbe1c30dea80026d66d95b60d7b3c814989e47acea33c`
- `docs/screenshots/papercut-launchpad.jpg` — SHA-256 `0b2b01b7c96e402fb622249d87ca4cbf94c078e6751c51525b7d2e38844c9f99`
- `docs/screenshots/rain-launchpad.jpg` — SHA-256 `f230713247920690665e9cc1ad825df931777a1b0c2f8e88f9bc0b28e0b68555`
