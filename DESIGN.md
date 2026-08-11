---
name: "图转视频极速版 - 本地版"
description: "面向本地批量渲染的暖灰仪器化工作台"
colors:
  porcelain: "#f3f1eb"
  porcelain-raised: "#faf9f5"
  chassis-warm-gray: "#e8e5dd"
  data-ink: "#1c2940"
  data-ink-muted: "#6f7782"
  data-ink-faint: "#989b9d"
  structural-line: "#c8c5bd"
  structural-line-strong: "#aaa69d"
  calibration-cobalt: "#254aa5"
  calibration-wash: "#e4eafa"
  calibration-quiet: "#7188ba"
  execution-oxblood: "#7d2935"
  execution-oxblood-deep: "#63202a"
  status-olive: "#667245"
  status-amber: "#9b681f"
  status-danger: "#a13b3b"
typography:
  headline:
    fontFamily: "Georgia, Songti SC, serif"
    fontSize: "17px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "normal"
  title:
    fontFamily: "Segoe UI Variable, Microsoft YaHei UI, Microsoft YaHei, sans-serif"
    fontSize: "13px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "0.02em"
  body:
    fontFamily: "Segoe UI Variable, Microsoft YaHei UI, Microsoft YaHei, sans-serif"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "Segoe UI Variable, Microsoft YaHei UI, Microsoft YaHei, sans-serif"
    fontSize: "9px"
    fontWeight: 750
    lineHeight: 1.2
    letterSpacing: "0.18em"
  mono:
    fontFamily: "Cascadia Mono, Consolas, monospace"
    fontSize: "10px"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "0.08em"
rounded:
  specimen: "2px"
  field: "3px"
  control: "4px"
  toggle: "7px"
  round: "50%"
spacing:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "10px"
  xl: "12px"
  xxl: "14px"
components:
  button-execution:
    backgroundColor: "{colors.execution-oxblood}"
    textColor: "{colors.porcelain-raised}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 10px"
    height: "33px"
  button-execution-hover:
    backgroundColor: "{colors.execution-oxblood-deep}"
    textColor: "{colors.porcelain-raised}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.data-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 10px"
    height: "30px"
  input-field:
    backgroundColor: "{colors.porcelain-raised}"
    textColor: "{colors.data-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.field}"
    padding: "0 7px"
    height: "29px"
  chip-calibration:
    backgroundColor: "{colors.calibration-wash}"
    textColor: "{colors.calibration-cobalt}"
    typography: "{typography.label}"
    rounded: "{rounded.specimen}"
    padding: "2px 6px"
  navigation-selected:
    backgroundColor: "{colors.calibration-wash}"
    textColor: "{colors.data-ink}"
    rounded: "0"
    padding: "11px 12px"
---

# Design System: 图转视频极速版 - 本地版

## Overview

**Creative North Star: "批量指挥台"**

这是一个密集、克制、面向本地生产的渲染工作台。它的世界来自暖灰仪器机箱与瓷白工作面：深蓝数据墨色负责信息，群青校准线负责选择、时间与测量，暗朱红只在真正启动执行的阈值上出现。

界面拒绝松散的后台卡片拼贴。结构由连续边框、窄间距、表格和仪表式标记组织，形成可追踪的生产链；少量衬线标题与等宽数字提供“标本标签”和“设备读数”的对照。复杂能力保持同屏可见，但通过分段检查器、明确状态和稳定列宽控制认知负荷。

**Key Characteristics:**

- 暖灰仪器机箱与瓷白工作面的双层材料关系。
- 深蓝数据墨色、群青校准线与稀缺的暗朱红执行阈值。
- 紧凑、边框驱动、以列表和清单为核心的生产密度。
- 衬线标本标题、无衬线操作文字与等宽读数的三声部排版。
- 阴影仅属于浮层与被抬起的标本，不属于常驻结构面。

## Colors

默认浅色主题是一套低彩度的暖灰纸面系统；深色主题保留相同语义角色，以冷暗机箱和提高亮度的状态色重新映射，而不改变颜色职责。

### Primary

- **校准群青:** 选择态、焦点轮廓、时间轴、进度与测量标记；它表示“当前正在校准或观察”，不表示执行。
- **校准淡洗:** 群青的低强度选中底色，用于当前工作区、运行中任务行和模式标签。

### Secondary

- **执行暗朱红:** 仅用于启动当前渲染或批量导出的高承诺操作。
- **执行深朱红:** 暗朱红操作的悬停反馈，保持沉着而非发光。

### Tertiary

- **完成橄榄:** 引擎就绪、完成与有效状态。
- **等待琥珀:** 忙碌、暂停和未保存状态。
- **故障红:** 验证失败、任务失败、错误与危险取消反馈。

### Neutral

- **瓷白工作面:** 主工作区与常驻面板的基础表面。
- **抬升瓷白:** 顶部指挥条、输入框、表格底面与浮层内容面。
- **暖灰机箱:** 页面底盘、胶片条和结构分区的后退层。
- **深蓝数据墨色:** 主文本、实心播放控件和品牌印记。
- **次级数据墨色:** 说明、时间码与次要状态。
- **微弱数据墨色:** 占位、弱提示和最低层级标签。
- **结构线 / 强结构线:** 分隔、字段轮廓与主要区域边界；深度首先由这两级线条建立。

**The Calibration Before Execution Rule.** 群青负责选择与校准；暗朱红只负责用户跨过执行阈值的动作，两者不可互换。

**The Semantic Status Rule.** 状态色必须同时配合图标、文字或进度结构，不能独自承担含义。

## Typography

**Display Font:** Georgia（中文回退 Songti SC）
**Body Font:** Segoe UI Variable（中文回退 Microsoft YaHei UI / Microsoft YaHei）
**Label/Mono Font:** Cascadia Mono（回退 Consolas）

**Character:** 排版像一台本地生产设备：无衬线文字紧凑直接，衬线只为品牌、空状态和标本标题提供少量编辑感；等宽字体专门承载序号、时间与数值读数。

### Hierarchy

- **Headline:** 粗衬线、小尺度标题，用于空状态或样片标识，不能扩张成营销式大标题。
- **Title:** 半粗无衬线，用于面板标题、项目名和工作区名称。
- **Body:** 小号无衬线，用于说明、控制文案和本地生产提示；长说明保持舒展行距。
- **Label:** 高字重、宽字距的小号标签，用于面板眉题、字段分组和表头；可使用大写变换以强化设备标记感。
- **Mono:** 等宽数字用于序号、时间码、帧率、进度和计数，保持制表数字对齐。

**The Three-Voice Rule.** 衬线负责标本语气，无衬线负责操作，等宽字体负责读数；不要让任一声部替代另外两者。

## Layout

桌面主壳体是四段纵向结构：固定指挥条、可选验证带、三列生产区和全宽渲染清单。标准三列为窄工作区轨道、弹性预览区与固定检查器；主生产区在当前实现中以 216px / minmax(430px, 1fr) / 340px 组织。渲染清单横跨底部并保留最小高度，使任务监督不会被参数编辑挤出视野。

空间节奏以 4–14px 的紧凑步进为主，面板标题约 52px，字段和按钮约 29–33px。密度来自稳定的行高、连续分隔线和有限的内边距，不依靠把内容缩成不可读的微型文字。

1240px 以下收紧侧栏和检查器；980px 以下保留至少 760px 的桌面画布，把检查器变为右侧覆盖层，并隐藏次要引擎读数。响应式变化保持工作区、预览和任务清单的操作连续性，而不是把生产流程改造成纵向卡片流。

## Elevation & Depth

系统默认平坦，常驻区域靠暖灰层级、结构线与内嵌描边区分深度。阴影只用于右侧覆盖检查器、提示浮层和预览中的抬升标本；默认浮层阴影为柔和宽扩散，深色主题提高不透明度。预览舞台是刻意下沉的深色设备腔体，不代表全局深色卡片样式。

### Shadow Vocabulary

- **浮层环境影:** `0 12px 36px rgba(37, 43, 51, 0.11)`；仅用于提示和覆盖式检查器等离开结构面的内容。
- **暗色浮层环境影:** `0 16px 42px rgba(0, 0, 0, 0.28)`；深色主题中的同语义替代。
- **标本抬升影:** `0 10px 24px rgba(0, 0, 0, 0.22)`；仅用于深色预览腔体中的单窗口样片。

**The Flat Chassis Rule.** 常驻面板、字段分组和表格不使用卡片投影；边框和材料层级先行。

## Shapes

形体以直角和极小圆角为主：样片标签和胶片格使用轻微收口，字段和分组稍柔，标准按钮保持克制的小圆角。圆形只属于品牌印记、播放按钮、状态点和拨动开关旋钮。主面板不做悬浮大圆角卡片，预览校准角采用明确的直线折角。

**The Instrument Edge Rule.** 小圆角服务于触控反馈和防止视觉毛刺；结构分区仍由直线边界和对齐关系建立。

## Components

组件整体“精密而克制”：默认安静，选择态清楚，执行态稀缺且不可误认。

### Buttons

- **Shape:** 标准操作使用克制的小圆角；图标按钮是 28px 方形，播放按钮与品牌印记是圆形。
- **Primary:** 执行按钮使用暗朱红实心面、浅色文字和紧凑水平内边距；批量导出保持至少 132px 宽，以形成明确阈值。
- **Hover / Focus:** 执行按钮悬停转为深朱红；所有按钮使用 2px 群青可见焦点和 2px 外偏移。
- **Secondary / Ghost:** 安静按钮默认透明，仅在悬停时出现暖灰底面和结构线；图标按钮始终保留细边框。

### Chips

- **Style:** 校准淡洗底色、群青文字、细群青混合边框和极小圆角。
- **State:** 用于 schema、数量和模式读数，不作为装饰性标签云。

### Cards / Containers

- **Corner Style:** 常驻容器保持直角；字段内的图层编辑器使用轻微圆角。
- **Background:** 瓷白为工作面，抬升瓷白为输入和表格，暖灰机箱为后退层。
- **Shadow Strategy:** 遵守 Flat Chassis Rule；只有覆盖层和预览标本获得阴影。
- **Border:** 单像素结构线连续建立区域关系，关键分区使用强结构线。
- **Internal Padding:** 紧凑步进，标题、字段和清单行保持稳定对齐。

### Inputs / Fields

- **Style:** 抬升瓷白底、单像素结构线、轻微圆角和 29px 高度；标签置于字段上方。
- **Focus:** 统一的群青外轮廓，不用模糊霓虹光晕。
- **Error / Disabled:** 禁用态降低不透明度并保留原有结构；错误在字段之外同时给出故障色与文字说明。

### Navigation

- **Style:** 工作区导航是全宽紧凑列表；默认透明，悬停仅有极淡群青，选中态使用校准淡洗、上下边框和左侧 3px 群青校准线。序号使用等宽字体，名称与状态分层呈现。

### Compact Inspector

检查器以基础参数三列校准网格开场；转场、特效、BGM、视频水印、图片水印共享五标签页，命名输出继续使用原生折叠分段。标签页以群青底线表达当前模块，所有字段保持原有顺序和键盘可达，结构之间共享分隔线，不拆成彼此悬浮的卡片。

### Render Manifest

渲染清单是生产状态的高密度表格：固定表头、稳定列宽、等宽进度和行内操作共同保证扫描效率。运行中行只获得低强度校准淡洗；完成、暂停与失败必须继续显示文字和图标。

## Do's and Don'ts

### Do:

- **Do** 用连续边框、稳定列宽和材料层级组织密集生产信息。
- **Do** 把群青留给选择、焦点、测量、时间和进度，把暗朱红留给真正执行。
- **Do** 为状态同时提供图标、文字或数值证据，确保非颜色识别。
- **Do** 在序号、时间码、帧率和进度中使用等宽制表数字。
- **Do** 保持键盘可见焦点，并尊重减少动态效果偏好。

### Don't:

- **Don't** 把工作流拆成一组互不相干、带大圆角和常驻阴影的后台卡片。
- **Don't** 用暗朱红装饰普通导航、标签或低承诺操作。
- **Don't** 用群青暗示危险或最终执行，也不要用状态色单独传达任务含义。
- **Don't** 在常驻结构面添加发光、玻璃拟态或环境投影。
- **Don't** 用营销式巨型标题或宽松留白稀释本地生产工作台的密度。
