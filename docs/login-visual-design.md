# 登录页主视觉

最终实现使用真实业务截图与 CSS 卡片，只有蓝色色带背景由 imagegen 内置工具生成；模型由工具管理，未指定模型版本。

原始素材：`frontend/public/images/login/blue-ribbon-v3.png` 为独立背景，`opportunities.png`、`tasks.png`、`work.png`、`reports.png` 为真实采样原图。保留原图供 README 展示与重新编码；登录页实际加载 `optimized/` 下带内容指纹的 WebP。下文历史图片、测试数据库与预览留在本地，不是运行依赖。

## 加载优化

运行前端 `npm run login-artwork:build` 可从五张原图重新生成素材及 `app/login-artwork.json`。卡片使用无损 WebP，解码后的 RGBA 像素与原图一致；丝带使用质量 90 的 WebP，保留原始尺寸。总体积由 2,383,348 字节降至 862,840 字节，减少约 64%。更换素材后需要重新运行脚本并提交新素材与清单。

页面 HTML 预加载丝带和首张卡片，仅在视口宽度至少 861px 时启用；其余卡片随登录界面加载。生产环境为 `optimized/` 配置一年 immutable 缓存，内容变化会生成新 URL。开发服务器仍使用开发缓存策略。布局、卡片比例、阴影与鼠标微动参数保持不变。

## 最终位置与交互

丝带左移 17cqw；卡片整体旋转 -10°，等比缩放 0.88。鼠标移动通过 requestAnimationFrame 合并更新，当前卡片轻移、其余层弱跟随；位移使用 900ms、阴影使用 1000ms 过渡。离开、取消指针或窗口失焦时归位，卸载清理监听器和待执行帧。触屏、窄屏及减少动态效果设置禁用动效。登录接口、错误处理、CSRF 与首次改密流程不变。

## V4 视觉比例修正

移除 V3 的 rotateX/rotateY，改为单一平面旋转 -10° 与等比缩放 0.88。浏览器检查最终矩阵：X/Y 缩放均为 0.8800001，坐标轴点积为 0，确认无非等比拉伸或剪切。保留原始截图比例、蓝色色带与层间阴影。预览：`outputs/login-desktop-v4.png`。

## V3 几何修正（历史版本）

截图与外框共用父级的单一正交投影，四层保持平行。截图按原始 1600:1050 比例展示，无独立变换、无内容重绘、无面板内裁切。边框、厚度和柔和投影由 CSS 绘制。背景独立通过内置 imagegen 生成；不再让模型生成界面与外框。

已检查桌面截图、原图比例和手机隐藏状态，构建与登录组件 ESLint 通过。最终预览：`outputs/login-desktop-v3.png`。

背景生成提示词：

Edit this image to produce ONLY its sculptural BLUE RIBBON BACKGROUND on white. Remove ALL four UI panels, frames, interface content, text, numbers, their cast shadows. Reconstruct the beautiful continuous cobalt blue ridged ribbon that was behind them. Preserve original portrait 4:5 framing, luminous white studio background, ribbon curving from top center-right down along left of center to bottom, luxurious satin blue material, parallel ridges, ice blue highlights, deep blue folds and physical thickness. Keep center-right mostly white for later compositing actual interface panels. Leftmost edge pure white. This is a clean background plate for deterministic HTML compositing. No rectangles, cards, screens, frames, text, logos, UI or objects other than the flowing blue sculptural ribbon. Highest quality.

## V2 真实页面采样

独立测试数据库 `.run/login_visual_sample.db`，后端端口 8796、前端端口 5186，单独会话 cookie。使用虚构的 6 人团队、4 个项目与商机、12 个任务、工作记录、交付物和周报；未读取或修改正式业务数据。

真实浏览器采样位于 `outputs/login-samples/`：`opportunities.png`、`tasks.png`、`work.png`、`reports.png`。V2 基于这些截图通过内置 imagegen 重新生成，保留实际信息架构并增强光影。生成图的小字仍存在重绘误差，不是逐像素截图合成。

### V2 提示词

Use case: compositing. Edit reference image 1, a portrait login hero. Keep its high-end sculptural cobalt blue ridged ribbon, luminous white studio background, four cascading floating panels, polished beveled edges, substantial physical thickness, blue reflected edge lighting, soft deep ambient occlusion and beautiful layered shadows. CRITICAL correction: the panel CONTENT must be the actual supplied application screenshots 2,3,4,5, not invented generic CRM layouts. Map screenshot 2 onto the entire FRONT panel as a perspective surface texture. Map screenshot 3 onto the second panel; screenshot 4 onto the third; screenshot 5 onto the back panel. Use all screenshots with fidelity to their exact navigation, proportions, labels, grouping, color and information architecture. Preserve the wide rectangular screenshot aspect ratio, allow right-side panels to extend beyond the artwork edge instead of reflowing or redesigning their layouts. Front panel MUST show actual header “解决方案部门作战台”, tabs “商机追踪 工作管理 周期总览”, actual main title “商机进展状态，一屏看清”, FOUR metric tiles “在跟商机 4”, “本周阶段推进 4”, “新增交付物 4”, “待协调 1”; below it actual horizontal LIST rows with colored connected stage dots, and narrow right “商机阶段分布” sidebar. Retain left navigation with numbered 作战台 项目 部门工作 任务 工作记录 周报. ABSOLUTELY NO revenue, currency, conversion-rate donuts, CRM contacts navigation, or invented sales tiles. Second panel screenshot 3 is the real task page with a three-column grid of generous task cards, status badges and fine blue action links. Third screenshot 4 is real work management, team member submission cards, 4/5 submission ring, deliverable tiles, right AI summary box. Fourth screenshot 5 is actual text report page, not invented charts. Preserve the supplied Chinese text as closely as possible, never replace real layout with concept dashboard. All visual enhancement must happen in lighting, perspective, panel edges, substrate material and the blue ribbon around those exact screen contents. Panels feel like real printed UI surfaces on satin porcelain thin boards; crisp text surface with realistic shadows beneath, never a flat screenshot collage. Maintain portrait 4:5 artwork and white left edge for seamless login integration. No login form, no captions or watermark. Highest-quality output.

参考：用户提供的 GitBook 登录页，以及项目 `outputs/v040-fixed-browser.png`。界面内容为艺术化示例，不代表真实业务数据或精确功能说明。

设计：白底，四层实体质感界面，蓝色立体色带，柔和投影、边缘高光与环境遮蔽。左侧仅账号密码登录。窄屏隐藏装饰，保留原有身份验证与首次改密流程。

## 生成提示词

Use case: stylized-concept. Create a production-quality right-side login hero illustration, portrait 4:5 composition at highest quality. References: image 1 GitBook login composition, image 2 our Chinese collaboration workspace UI. Generate ONLY artwork, no login form, no footer, no GitBook or Mobbin branding. Reinterpret the right-hand layered UI as an expensive photorealistic 3D product editorial render: four large floating porcelain-white UI panels in parallel dramatic isometric perspective, cascading diagonally with generous air between layers. Thin but tangible bevelled edges, satin ceramic/aluminum substrates, extremely realistic broad softbox lighting from upper left, beautiful contact occlusion, soft layered cast shadows, subtle cool reflected light along undersides; substantial and sculptural, NEVER flat screenshot collage. Behind the stack, a huge sweeping cobalt-blue ribbon with several finely extruded parallel ridges curves from top to bottom. Ribbon uses #1677ff mids, deep ultramarine folds, ice-blue specular highlights, luxurious molded satin material, not neon tubes. Seamless nearly white background, left edge pure white with breathing space to blend into website; panels extend partially beyond right edge; entire main stack visible enough to understand. UI aesthetics from second reference: dark navy headings, blue selected tabs, fine separators, small status chips, refined compact white cards. Foreground panel title exactly “商机追踪” with readable short Chinese labels “需求确认”, “方案交流”, “POC验证” and an elegant progress dashboard; second panel “任务协作” with connected task cards; third “周度工作” with progress and avatar dots; rear panel “团队周报” with report blocks. Use fictional content only, minimal small text, no gibberish paragraphs, no empty/loading states. Restrained blue, white, silver, slight teal. Preserve professional enterprise product identity but elevate composition and dimensional materials dramatically. No extra floating icons, no glass bubbles, no devices, no dark background, no promotional headline.
