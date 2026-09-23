# 渲染内核从 Tkinter 解耦：拆分方式与实现步骤

> 范围：`src/gui/main_window.py`（Tkinter/CustomTkinter，414KB）中的渲染逻辑抽为界面无关内核，
> 供 Tk 界面、Qt 界面（`src/gui_qt/`）、Tauri 引擎（`src/engine/`）三方共用。
> 结论先行：**不需要从零设计，按已成功的 `TurboTransitionEngine` 模式复制即可，且最大的一块抽取成本接近零。**

---

## 1. 现状诊断

### 1.1 内核以「界面类的成员方法」形式存在

`ImageToVideoTab`（`src/gui/main_window.py:853`）同时承担三个角色：Tk 控件树、渲染配置容器、渲染执行器。
渲染能力全部是它的实例方法，没有可复用的调用边界：

| 分类 | 方法 | 位置 | 行数 |
|---|---|---|---|
| 图片装载 | `get_images_list` / `natural_sort_key` / `sort_images_naturally` | 3310 / 3383 / 3401 | ~120 |
| 图片处理 | `safe_read_image` / `resize_with_aspect_ratio` / `_center_crop` | 3431 / 3480 / 3519 | ~90 |
| 效果渲染 | `apply_single_image_effect` | 3700–4134 | **435** |
| 转场 | `apply_transition` + 5 个转场实现 | 4135–4414 | **280** |
| 编码解析 | `_resolve_cv_fourcc` / `_get_selected_codec_name` / 容器兼容组 等 11 个 | 4415–4523 | ~110 |
| 视频合成 | `create_video` | 4643–4931 | **289** |
| 视频合成（Turbo） | `create_video_turbo_enhanced` + `_turbo_preprocess_image` + `_turbo_write_transition_frames` | 4932–5317 | **386** |
| 音频 | `add_audio_with_ffmpeg` | 5318–5405 | 88 |
| 控制 | `_wait_for_processing_control` | 5702–5716 | 15 |
| FFmpeg 合成 | `create_video_with_ffmpeg` | 7931 | — |

### 1.2 三条消费链路全部绕道 Tk

```text
① Qt 界面   src/gui_qt/main_window.py:2442  QProcess
            → src/gui_qt/tk_bridge_runner.py  root = tk.Tk(); root.withdraw()
            → ImageToVideoTab(holder)          # 实例化整个 Tk 控件树
            → 反射式劫持 tab.update_status / tab.update_progress 抓进度

② Tauri 引擎 src/engine/server.py:163  jobs.start()
            → src/engine/runner.py:158-175  _worker_command()
                打包: --legacy-worker → server.py:573 → tk_bridge_runner
                开发: -m src.gui_qt.tk_bridge_runner
            → 同样落到 tk.Tk()

③ 引擎预览   src/engine/effect_preview.py:338  _LegacyEffectAdapter
            :356  from ..gui.main_window import ImageToVideoTab
            :358  ImageToVideoTab.apply_single_image_effect(self, ...)  # 鸭子类型「假 self」
```

第 ③ 条最典型：引擎为了复用效果函数，把适配器对象冒充成 `ImageToVideoTab` 当 `self` 传进去。
注释自称 "stateless renderer"——说明这个方法本来就是无状态的，只是被绑在了类上。

### 1.3 交付层面的直接代价

`engine_sidecar.spec:7-8` 的 `hiddenimports` 包含 `tkinter` / `tkinter.ttk`，
`PIL.ImageTk` 亦在其中。**一个无界面引擎，打包产物必须捆绑 Tcl/Tk 运行时**，
且每个渲染任务都要付一次 `tk.Tk()` + 隐藏控件树构造的启动开销。

### 1.4 已有资产（工作量比预期小得多）

| 资产 | 位置 | 状态 |
|---|---|---|
| `TurboTransitionEngine` | `src/core/transition_engine.py:25`（1222 行） | ✅ **已成功解耦**，Tk（1919）与 Qt（395）均直接使用——可行先例 |
| `VideoGenerationService` | `src/services/video_service.py:24` | ⚠️ 已写出但**无人调用**（仅 `services/__init__.py` 导出） |
| `ImageProcessingService` | `src/services/image_service.py:23` | ⚠️ 同上，影子内核 |

**关键量化发现（决定拆分难度）：**

- `apply_single_image_effect`（435 行，最大一块）全文只引用 `self._center_crop` 与递归自身
  → **纯无状态，可零成本提升为模块级函数**
- `apply_transition`（204 行）只引用 `self.transition_engine` → 构造注入一个对象即可
- 暂停/取消已是 `threading.Event`（`main_window.py:912`）+ `bool`（`:915`）
  → **不依赖 Tk 的 `after` 或事件循环，事件机制改造量小**
- `create_video` 引用的 18 个 `self.*` 可完整归类为「配置 / 回调 / 工具 / 水印 / 后处理 / 环境」六类
  （见 §3.1），即接口的全部内容

---

## 2. 目标职责边界

### 渲染内核负责（不 import 任何 `tkinter` / `customtkinter` / `PySide6`）

- 图片扫描、筛选、自然排序、组合规划
- 图片解码与缩放（含中文路径安全的 `np.fromfile` + `cv2.imdecode` 路径）
- 效果渲染、转场渲染
- 帧写入、编码参数解析、容器兼容判定、二次编码、FFmpeg 合成
- 音频混入、水印绘制
- 进度计算、暂停/取消应答
- 对外只暴露「请求进、事件出」

### 界面层负责

- 控件构建、布局、主题、字体
- **把内核产出的 numpy 帧转成自己的显示对象**
  （Tk → `PhotoImage`，Qt → `QPixmap`，Tauri → base64 / 文件）
- 用户输入的校验与收集 → 组装成渲染请求
- 展示内核推送的进度/状态事件
- 暂停/取消的用户动作 → 转成对内核的信号
- 弹窗、目录打开、配置持久化

### 边界判定原则

> 内核永远不知道「画布」存在。它只产出帧（`np.ndarray`）和文件（视频路径）。
> 现有 `_frame_to_photoimage`（`main_window.py:3530`）已经是正确的方向——帧 → 界面，留在界面层。

---

## 3. 接口与数据传递机制

### 3.1 内核入参：`RenderRequest`

把 `create_video` 引用的全部 `self.*` 显式化为一个数据对象：

| 现有来源 | 字段归属 |
|---|---|
| `self.bitrate` / `self.use_video_effect` / `self.video_effect_intensity` / `_speed` / `_type` / `self.loop_bgm` | `RenderRequest` 配置字段 |
| 宽高 / 时长 / fps / 格式 / 编码 / 转场 / 水印层 / BGM 路径 / turbo 开关 | `RenderRequest` 配置字段 |
| `self.ffmpeg_available` / ffmpeg 路径 | `RenderEnvironment`（构造时注入） |
| `self.turbo_accelerator` | `RenderEnvironment`（构造时注入） |
| `self.update_progress` / `reset_progress` / `update_status` | → 改为 `RenderObserver`（§3.2） |
| `self.cancel_requested` / `self._wait_for_processing_control` | → 改为 `RenderObserver`（§3.2） |
| `self.safe_read_image` / `resize_image` / `_resolve_cv_fourcc` / `create_video_with_ffmpeg` / `normalize_path` | 内核内部模块函数，不再是依赖 |
| `self._prepare_image_watermark_layers` / `add_fixed_image_watermarks_to_video` / `apply_image_watermark_layers` | 内核内部（水印子模块） |
| `self._has_postprocess_work` / `_postprocess_video_output` | 内核内部（编码子模块） |

要求：`RenderRequest` 必须能从现有配置 dict **无损双向映射**，字段名与现有 JSON 保持一致
（`PRODUCT.md`：「迁移不得静默改变已有配置含义」）。

### 3.2 内核出参：`RenderObserver`（回调协议）

```python
class RenderObserver(Protocol):
    def on_progress(self, percent: int, overall: int, phase: str = "",
                    speed: str | None = None) -> None: ...
    def on_status(self, message: str) -> None: ...
    def should_cancel(self) -> bool: ...
    def wait_if_paused(self) -> bool: ...   # 返回 False 表示应中止
```

这是**唯一**的界面 ↔ 内核通道。四种界面的实现方式：

| 界面 | `RenderObserver` 实现 |
|---|---|
| Tk | 写 `StringVar` / `IntVar`（子进程内安全） |
| Qt | 发信号（`Signal`），由主线程槽更新 |
| Tauri worker | `print(json.dumps(...), flush=True)` 输出 NDJSON |
| 测试 | 记录调用序列的 mock |

`wait_if_paused` 是 `_wait_for_processing_control`（`:5702`）的对称化——把「问界面要不要停」
从内核内部的属性查询，改为显式的接口方法。**这一点是暂停/取消能跨界面复用的关键。**

### 3.3 事件分发

内核自身**不建线程、不建队列**。它只在帧循环的检查点调用 `observer.*`。

- **推模型**（进度、状态）：内核主动调 `on_progress` / `on_status`，单向、无返回
- **拉模型**（暂停、取消）：内核调 `should_cancel()` / `wait_if_paused()` 主动询问
- 现存的「每 0.20s 或状态变化才发一次」节流逻辑（`tk_bridge_runner.py` 的 `patched_update_status`）
  应下沉到 observer 实现里，**不要**留进内核——那是各界面自己的节流策略
- 暂停/取消状态源：现状是 `{paused, cancel}` 控制文件（`runner.py:187` 写、worker 读）。
  这个契约必须保留（§8.4）
- **上下文归属**：渲染必须在后台线程或子进程中执行。现状 Tk 路径在子进程内是安全的；
  若将来某界面在**同进程内**直接调内核，必须保证 `RenderObserver` 的 UI 更新部分线程安全
  （Qt 用 `Signal` 跨线程排队，Tk 需 `root.after` 转主线程）

### 3.4 画布呈现

拆分后预览路径要明确切成两段：

| 段 | 归属 | 现有方法 |
|---|---|---|
| 产出帧 | 内核 | `_build_effect_preview_source_frame`（3547）、`_render_single_effect_preview_frame`（3573）、`apply_transition` 预览分支 |
| 显示帧 | 界面层 | `_frame_to_photoimage`（3530）、`_effect_preview_tick`（3636）、`preview_single_effect_frame`（3667）的 UI 部分 |

**硬约束：预览与导出必须调用同一份效果/转场实现**，否则会出现「预览所见 ≠ 导出所得」。

### 3.5 状态同步

- 内核内部状态（当前第几张、帧计数、耗时、阶段标签）→ 通过 `on_progress` 单向推出，界面不反向写入
- 界面 → 内核只有两个信号：cancel、pause（经 observer）
- **禁止双向共享可变状态。** 现状正是因为界面对象既是状态容器又是渲染器，
  才逼出「反射式劫持方法」这种补丁（`tk_bridge_runner.py` 的 `tab.update_status = patched_...`）

---

## 4. 三种拆分方式对比

| 方式 | 做法 | 工作量 | 收益 | 风险 |
|---|---|---|---|---|
| **A. 新增 `src/render/` 独立包**（推荐） | 内核方法搬入新包，三界面共同消费 | 中（搬运 + 注入） | 彻底：去 tkinter 依赖、三方共用一份、消除假 self | 搬运量大；需逐字保真 |
| B. 填充已有 `src/services/` | 把逻辑塞进 `VideoGenerationService` / `ImageProcessingService` | 小–中 | 复用现有骨架与导出 | 骨架是按「薄封装」设计的（`video_service.py` 仅 271 行），与实际管线形状差距大，硬套会拧巴再返工 |
| C. 仅修 `_LegacyEffectAdapter` | 把假 self 换成直接调用 | 极小 | 消除 `effect_preview` 对 GUI 的 import | **治标**：runner 仍走 Tk，sidecar 仍捆 tkinter |

**推荐 A，并分阶段落地。** 理由：B 的两个服务是「设计时想象的内核」，实际渲染管线（turbo 路径、
水印三件套、编码兼容判定）比它复杂得多，填充等于先改造骨架再搬运，两次成本；
C 不解决交付层面的 tkinter 依赖，收益不成正比。

---

## 5. 实现步骤（分阶段，每阶段可独立验证且不破坏现有功能）

### Phase 0 — 抽纯函数（零风险）

1. 新建 `src/render/effects.py`
2. 把 `apply_single_image_effect`（3700–4134）与 `_center_crop`（3519）**逐字**搬入，
   签名去掉 `self`：`apply_single_image_effect(img, effect_type, time_sec, duration_sec, intensity=100.0, speed=1.0)`
3. `src/gui/main_window.py` 中保留薄包装转调，保证 Tk 现有调用点不变
4. `src/engine/effect_preview.py` 的 `_LegacyEffectAdapter`（338–360）
   改为直接调 `src.render.effects`，**删除 `from ..gui.main_window import`**

**验证**：`python -c "import src.engine.effect_preview"` 不再拉起 `customtkinter`；
对同一组 (图片, 效果, 参数) 比对拆分前后输出帧的逐像素哈希一致。

### Phase 1 — 抽转场与合成管线

1. `src/render/transitions.py`：`apply_transition`（4211–4414）+ 5 个转场实现（4135–4210）；
   原 `self.transition_engine` 改为构造注入
2. `src/render/params.py`：`RenderRequest` dataclass + `RenderObserver` Protocol（§3.2）
3. `src/render/compositor.py`：`create_video`（4643–4931）、`create_video_turbo_enhanced`（4932–5220）、
   `_turbo_preprocess_image`（5221）、`_turbo_write_transition_frames`（5257）
   —— `self.*` 按 §3.1 表格替换为 request 字段 / observer 回调 / 模块函数
4. `src/gui/main_window.py` 对应方法变为 3–5 行转发

**验证**：Tk 界面跑通一次完整渲染；对比拆分前后输出文件的时长、帧数、编码、文件大小。

### Phase 2 — 出口与音频

1. `src/render/images.py`：`safe_read_image`（3431）、`resize_with_aspect_ratio`（3480）、
   `get_images_list`（3310）、`natural_sort_key`（3383）、`sort_images_naturally`（3401）
2. `src/render/encoder.py`：编码解析组（4415–4523，11 个方法）、`_reencode_video_to_selected_codec`（4524）、
   `_log_output_probe`（4586）、`create_video_with_ffmpeg`（7931）
3. `src/render/watermark.py`：`_prepare_image_watermark_layers`、`add_fixed_image_watermarks_to_video`、
   `apply_image_watermark_layers`
4. `src/render/audio.py`：`add_audio_with_ffmpeg`（5318–5405）
5. `_has_postprocess_work` / `_postprocess_video_output` 归入 encoder

**验证**：分别跑「无水印/多层图片水印/视频水印」「无 BGM/带 BGM」「H.264/HEVC/容器自动切换」组合矩阵。

### Phase 3 — 换掉渲染 worker（去掉 tkinter 依赖）

1. 新建 `src/render/worker.py`：`main()` 读 `--config` / `--control`，
   构造一个把事件打成 NDJSON 的 `RenderObserver`，调内核
   —— **协议字段与 `tk_bridge_runner.py` 完全一致**（`type/percent/overall/speed/phase/elapsed_sec/done`）
2. `src/engine/runner.py:158-175` 的 `_worker_command()` 改为 `-m src.render.worker`
3. `src/engine/server.py:573` 的 `_run_legacy_worker()` 改指 `src.render.worker`
4. `engine_sidecar.spec:7-8` 删除 `tkinter` / `tkinter.ttk`；评估 `PIL.ImageTk` 是否仍需要

**验证**：起 sidecar → `render` → 观察进度事件流；确认产物内不含 `tcl/tk` 目录，sidecar 体积下降。

### Phase 4 — Tk 界面降级为消费者

1. 删除 `src/gui/main_window.py` 中的内核方法（此时应只剩转发或被删）
2. 让 Tk 界面改为「组装 `RenderRequest` + 实现 `RenderObserver`」
3. `src/gui_qt/tk_bridge_runner.py` 可退役（Qt 直接走 `src.render.worker`）

**验证**：Tk 界面与 Qt 界面分别渲染同一配置，输出文件应完全一致。

---

## 6. 可复用模式：照抄已成功的先例

`src/core/transition_engine.py` 已经演示了正确做法，Phase 1 直接复刻：

- 模块级类 `TurboTransitionEngine`，不 import 任何 GUI
- 单例获取 `get_turbo_transition_engine()`（:1222）+ 显式清理 `cleanup_...()`（:1230）
- 两侧界面各自 `from ... import get_turbo_transition_engine`（Tk :37、Qt :63）

差异点：`TurboTransitionEngine` 只抽了转场，且仍靠单例持有带缓存的加速器。
`src/render/` 应改为**显式注入**（`RenderEnvironment`），避免又出现一个跨界面的隐藏全局态。

---

## 7. 兼容性关注点

1. **配置 JSON 是兼容边界**（`PRODUCT.md` 明示）。`RenderRequest` 必须能从现有 config dict 无损映射，
   字段名不得改动，否则老配置文件含义被静默改变。
2. **打包规格**：两个 spec 的 `datas = [("config","config"), ("src","src")]` 会把整个 `src` 打进产物，
   新增 `src/render/` 需确认被正确收集；同时删除 `hiddenimports` 中的 tkinter 要确认没有隐式依赖。
3. **命令行契约**：`--legacy-worker` / `--config` / `--control` 是打包产物的对外参数，
   Phase 3 换实现时要保持参数不变，否则旧版 GUI 调新引擎会静默失败。
4. **控制文件协议**：`{"paused": bool, "cancel": bool}`（`runner.py:189` 写、worker 读）不可变，
   否则 Qt 与 Tauri 的暂停/取消会静默失效。
5. **NDJSON 事件字段名**已被 Qt 与 Tauri 前端消费，Phase 3 必须逐字段保持。
6. **双轨并存**：旧版 exe 仍在发布线（`releases/`），Tk 与 Qt 界面需保持可运行直到新界面功能对等。

---

## 8. 性能关注点

1. **去掉 Tk 的启动开销**：现状每个渲染任务要付 `tk.Tk()` + 隐藏控件树（`create_widgets`，:1972）
   的构造成本。Phase 3 后每个任务的启动延迟应明显下降——这是可量化的收益，建议前后各测一次任务启动到首帧的时间。
2. **不要再造全局单例**：`turbo_accelerator`（`src/optimization/turbo_accelerator.py`）是带缓存的单例，
   跨任务复用需显式释放（对照 `optimize_memory`，:2892）。
3. **避免首帧付出 GUI 导入成本**：现状 `_LegacyEffectAdapter` 每帧执行 `from ..gui.main_window import`
   （模块缓存使其廉价，但首帧要付 `customtkinter` 导入）。Phase 0 即消除。
4. **中文路径解码路径不能退化**：`safe_read_image` 用 `np.fromfile` + `cv2.imdecode`（:3431），
   搬运时**不要**顺手换成 `cv2.imread`，后者在非 ASCII 路径下会失败。
5. **帧循环里别反复构造对象**：原实现靠 `self.属性` 读取配置是零成本；
   改为 `RenderRequest` 后，务必在循环外构造一次、循环内复用，不要每帧重建。
6. **回调不能变成瓶颈**：`on_progress` 在 turbo 路径的调用点密集（见 §9.7），
   节流策略放在 observer 实现侧（现成参考：`tk_bridge_runner.py` 的 0.20s / 1.0s 阈值）。

---

## 9. 边界情况

1. **效果函数逐字保真**：`apply_single_image_effect` 435 行内含大量 `if effect_type ==` 分支与参数钳制，
   搬运时禁止「顺手重构」。建议先建帧比对回归，再动手。
2. **预览与导出一致性**（最高风险项）：拆开后 `preview_single_effect_frame`（:3667）与 `create_video`（:4643）
   必须调用同一个内核函数。现在两者天然一致只因长在同一个类里——这是拆分最易引入的回归。
3. **水印三件套是共享中间态**：`_prepare_image_watermark_layers` 同时被预览与合成使用，
   归属要明确（建议放内核，因其依赖 ffmpeg 与帧数据），否则两层各持一份会漂移。
4. **后处理条件分支**：`_has_postprocess_work` + `_postprocess_video_output` 决定是否二次编码，
   漏接会产出编码不符的文件（而且不一定报错）。
5. **暂停检查点一个都不能少**：`_wait_for_processing_control` 在 turbo 路径被调用 6 次
   （5012 / 5120 / 5143 / 5162 / 5284 / 5301 / 5312），拆出去时全部保留，
   少一个就会出现「暂停后仍在写帧」。
6. **取消时的产物清理**：`cancel_requested`（:5179）在过渡帧写入中途被检查，
   此时已有临时文件（`_build_temp_output_path`，:4472）与半成品输出，
   内核要保证中止路径不留下损坏文件。
7. **`_wait_for_processing_control` 的调用密度与性能的权衡**：它默认 `sleep_sec=0.03`，
   在帧循环里高频调用，拆分后如果 observer 的 `wait_if_paused` 实现变慢（例如跨进程查询），
   会直接拖慢渲染速度。
8. **frozen 模式复用 `sys.executable`**：`runner.py` 依赖「同一个 exe 既能当 GUI 又能当 worker」，
   Phase 3 换 worker 模块时要保持这个契约（改内部模块名，不改进程模型）。
9. **单例缓存的内存释放**：`TurboTransitionEngine` 与 `turbo_accelerator` 在长批量任务间复用，
   需要保留 `cleanup_*` 路径，否则大批量渲染会内存增长。

---

## 10. 回归验证清单

拆分每个阶段后至少覆盖：

- [ ] 同配置下拆分前后输出文件：时长、帧数、编码、码率、文件大小一致
- [ ] 效果与转场的帧级比对（同一组参数输出逐像素哈希一致）
- [ ] 预览路径 vs 导出路径对同一配置的视觉结果一致
- [ ] 暂停/继续/取消三动作在渲染中途生效，且响应延迟无明显退化
- [ ] 多层图片水印 + 视频水印 + BGM 组合矩阵
- [ ] 中文路径与非 ASCII 文件名输入输出
- [ ] 异常路径：ffmpeg 缺失、图片损坏、磁盘满、目标文件被占用
- [ ] 打包产物：sidecar 可独立启动、`render` 方法可用、产物内无 tcl/tk

---

## 11. 实施进度（2026-09-21 更新）

**P0–P4 全部完成。** `main_window.py` 8350 → 3917 行；`src/render/` 9526 行 / 15 个模块。

| 模块 | 行数 | 内容 |
|---|---|---|
| `effects.py` | 461 | 43 种单图动态效果 |
| `transitions.py` | 306 | 转场合成 + 5 个基础转场 |
| `images.py` | 294 | 路径 / 扫描 / 排序 / 读图 / 缩放 |
| `process.py` | 205 | 子进程守护 / 文件替换 / 视频元信息 |
| `codec.py` | 325 | 编码器与容器解析（CodecContext） |
| `context.py` | 79 | RenderContext：界面侧唯一出入口 |
| `controls.py` | 46 | 暂停取消应答 / 内存清理 |
| `audio.py` | 150 | BGM 候选与混入 |
| `watermark.py` | 1450 | 图片水印 / 视频水印 / 单图合成 |
| `encoder.py` / `compositor.py` | 1043 | FFmpeg 合成 / 帧序与视频合成 |
| `postprocess.py` | 565 | 后处理编排 |
| `plan.py` / `job.py` / `worker.py` | 678 | 共享常量 / 批量编排 / 无界面入口 |

## 11b. P3 / P4 落地要点

**P3 无界面 worker**：`src/render/worker.py` 的 NDJSON 协议与旧 `tk_bridge_runner` 完全一致，
因此 `engine/runner.py`、`engine/server.py`（`--legacy-worker`）、`main_qt.py`（`--qt-bridge-worker`）、
`gui_qt/main_window.py` 的 QProcess 四个调用点只改指向，不改协议。
`engine_sidecar.spec` 已删除 `tkinter` / `tkinter.ttk` / `PIL.ImageTk`。

**P4 界面降级**：`process_videos` 与转场/特效计划抽到 `job.py`，
**worker 与界面共用同一条编排路径**——这是避免"两套实现漂移"的关键。
界面只保留上下文组装与按钮收尾。

**验证**：8 个保真 scope 全 IDENTICAL + worker 端到端真渲染（生成 2 个 mp4，零 Tk 依赖）。
工具的 8 个 scope：effects / trans / images / process / codec / audio / watermark / pipeline。
另加 `tools/check_undefined_names.py`：扫"搬运漏掉的 import"（静态语法检查发现不了）。

**剩余可选清理**：`src/gui_qt/tk_bridge_runner.py` 已无调用点，可删除；
`src/render/__init__.py` 可补导出。

---

## 12. 待确认决策点（原）

**验证**：`tools/render_parity_check.py` 共 8 个 scope，全部 IDENTICAL
（effects 129 例 / trans 53 / images 44 / process 21 / codec 89 / audio 24 /
watermark 72 / pipeline 端到端真实渲染）。

**与 §4 方案的偏差**：
1. **进度显示不搬**——`update_progress` / `_set_absolute_progress` / `reset_progress` /
   `reset_overall_progress` 是界面职责（写 Tk 变量），内核只通过 ctx 回调上报。
2. **P1/P2 顺序互换**，且 `resize_image` 归入 `images.py`（encoder 与 compositor 都要用）。
3. **边界调整**：原方案的 §3.1/§3.2 中的 `RenderRequest` / `RenderObserver` 落地为
   `RenderContext`（读 `read_value` / 写 `set_value` / 上报 `notify`·`progress`·`emit_*`），
   没有单独的数据类——因为调用点是逐字搬运，参数化签名比构造请求对象更贴近原行为。

**剩余**：P3（`render/worker.py` 替换 Tk 桥接器、spec 去掉 tkinter）、P4（Tk 降级为消费者）。

---

## 12. 待确认决策点（原）

**内核代码放哪里？**

- **选项 1（推荐）**：新增 `src/render/` 独立包，与 `core/` / `utils/` / `services/` 平级。
  边界干净，语义明确（这是渲染内核，不是通用服务）。
- **选项 2**：填充已有的 `src/services/`。复用现有骨架与导出，但需先把
  `VideoGenerationService` / `ImageProcessingService` 改造成符合实际管线（turbo、水印、编码兼容）的形状，
  等于先返工再搬运。

其余细节（模块内文件划分、命名、Phase 顺序）可在执行中按实际情况调整，不需要逐项确认。
