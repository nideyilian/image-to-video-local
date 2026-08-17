import { useId, useState, type KeyboardEvent } from "react";
import { ChevronLeft, ChevronRight, LibraryBig, Plus, Trash2, X } from "lucide-react";
import {
  BLEND_MODES,
  DEFAULT_RESOLUTION_PRESETS,
  DEFAULT_WATERMARK_LAYER,
  TRANSITIONS,
  VIDEO_EFFECTS,
  WATERMARK_POSITIONS,
  WATERMARK_SIZE_MODES,
} from "../constants";
import type { LibraryItem, ValidationIssue, VideoConfig, WatermarkLayer } from "../types";
import { Field, PathField } from "./Controls";
import { LibraryPicker } from "./LibraryPicker";

type ConfigKey = keyof VideoConfig;

const INSPECTOR_TABS = [
  { id: "basic", label: "基础" },
  { id: "motion", label: "转场特效" },
  { id: "watermark", label: "水印" },
] as const;

const LAYER_PAGE_SIZE = 1;

export type InspectorTabId = (typeof INSPECTOR_TABS)[number]["id"];
type FeatureMode = "off" | "fixed" | "random";
type BgmMode = "off" | "ordered" | "random";

const FEATURE_MODE_OPTIONS = [
  { value: "off", label: "关闭" },
  { value: "fixed", label: "固定" },
  { value: "random", label: "随机" },
] as const;

const BGM_MODE_OPTIONS = [
  { value: "off", label: "关闭" },
  { value: "ordered", label: "顺序" },
  { value: "random", label: "随机" },
] as const;

const STATUS_OPTIONS = [
  { value: "off", label: "关闭" },
  { value: "on", label: "开启" },
] as const;

function SegmentedControl<T extends string>({ label, value, options, onChange, compact = false }: {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  compact?: boolean;
}) {
  const name = useId();
  return (
    <div className={`segmented-control${compact ? " is-compact" : ""}`} role="radiogroup" aria-label={label}>
      <span className="segmented-label">{label}</span>
      <div>
        {options.map((option) => (
          <label key={option.value}>
            <input type="radio" name={name} value={option.value} checked={value === option.value} onChange={() => onChange(option.value)} />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

const CUSTOM_RESOLUTION_OPTION = "__custom_resolution__";

function ResolutionField({ config, onChange }: {
  config: VideoConfig;
  onChange: <K extends ConfigKey>(key: K, value: VideoConfig[K]) => void;
}) {
  const defaults = DEFAULT_RESOLUTION_PRESETS;
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");

  const presets = config.resolution_presets ?? [];
  const customPresets = Array.from(new Set(presets.filter((value) => !defaults.includes(value))));
  const current = config.resolution_preset;
  const selectValue = adding ? CUSTOM_RESOLUTION_OPTION : current;

  const handleSelectChange = (next: string) => {
    if (next === CUSTOM_RESOLUTION_OPTION) {
      setDraft("");
      setError("");
      setAdding(true);
      return;
    }
    onChange("resolution_preset", next);
  };

  const commitCustom = () => {
    const normalized = draft.trim().toLowerCase().replace(/[×*]/g, "x");
    if (!/^\d{1,5}x\d{1,5}$/.test(normalized)) {
      setError("格式应为 宽x高，例如 1920x1080");
      return;
    }
    const nextPresets = presets.includes(normalized) ? presets : [...presets, normalized];
    onChange("resolution_presets", nextPresets);
    onChange("resolution_preset", normalized);
    setAdding(false);
    setDraft("");
    setError("");
  };

  const cancelCustom = () => {
    setAdding(false);
    setDraft("");
    setError("");
  };

  const showCurrentOnly = current && !defaults.includes(current) && !customPresets.includes(current);

  return (
    <Field label="分辨率" hint={error || undefined}>
      <select value={selectValue} onChange={(event) => handleSelectChange(event.target.value)}>
        {defaults.map((value) => (
          <option key={value} value={value}>{value}</option>
        ))}
        {customPresets.length > 0 && (
          <optgroup label="自定义">
            {customPresets.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </optgroup>
        )}
        {showCurrentOnly && <option value={current}>{current}（当前）</option>}
        <option value={CUSTOM_RESOLUTION_OPTION}>＋ 自定义添加</option>
      </select>
      {adding && (
        <span className="resolution-add">
          <input
            autoFocus
            placeholder="如 1920x1080"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") commitCustom();
              if (event.key === "Escape") cancelCustom();
            }}
          />
          <button type="button" onClick={commitCustom}>添加</button>
          <button type="button" className="quiet" onClick={cancelCustom}>取消</button>
        </span>
      )}
    </Field>
  );
}

function Checkbox({ label, checked, onChange, disabled = false }: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="check-control">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

function Paginator({ page, pageCount, label, onChange }: {
  page: number;
  pageCount: number;
  label: string;
  onChange: (page: number) => void;
}) {
  if (pageCount <= 1) return null;
  return (
    <nav className="inspector-pagination" aria-label={label}>
      <button type="button" className="icon-button" disabled={page === 0} onClick={() => onChange(page - 1)} aria-label="上一页"><ChevronLeft size={15} /></button>
      <span>{page + 1} / {pageCount}</span>
      <button type="button" className="icon-button" disabled={page === pageCount - 1} onClick={() => onChange(page + 1)} aria-label="下一页"><ChevronRight size={15} /></button>
    </nav>
  );
}

export function Inspector({
  config,
  onChange,
  onBrowseDirectory,
  onBrowseFile,
  activeTab,
  onActiveTabChange,
  validationIssues,
  onOpenLibraryTab,
}: {
  config: VideoConfig;
  onChange: <K extends ConfigKey>(key: K, value: VideoConfig[K]) => void;
  onBrowseDirectory: (key: ConfigKey) => void;
  onBrowseFile: (key: ConfigKey, layerIndex?: number) => void;
  activeTab: InspectorTabId;
  onActiveTabChange: (tab: InspectorTabId) => void;
  validationIssues: ValidationIssue[];
  onOpenLibraryTab: (tab: "effect" | "transition") => void;
}) {
  const [bgmPickerOpen, setBgmPickerOpen] = useState(false);
  const [watermarkPickerOpen, setWatermarkPickerOpen] = useState(false);
  const [layerPage, setLayerPage] = useState(0);

  const updateLayer = (index: number, patch: Partial<WatermarkLayer>) => {
    const next = config.watermark_layers.map((layer, layerIndex) => layerIndex === index ? { ...layer, ...patch } : layer);
    onChange("watermark_layers", next);
  };

  const addLayer = () => {
    const index = config.watermark_layers.length;
    onChange("watermark_layers", [...config.watermark_layers, { ...DEFAULT_WATERMARK_LAYER }]);
    setLayerPage(index);
  };
  const removeLayer = (index: number) => onChange("watermark_layers", config.watermark_layers.filter((_, layerIndex) => layerIndex !== index));

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex = index;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % INSPECTOR_TABS.length;
    else if (event.key === "ArrowLeft") nextIndex = (index - 1 + INSPECTOR_TABS.length) % INSPECTOR_TABS.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = INSPECTOR_TABS.length - 1;
    else return;
    event.preventDefault();
    const nextTab = INSPECTOR_TABS[nextIndex];
    onActiveTabChange(nextTab.id);
    window.requestAnimationFrame(() => document.getElementById(`inspector-tab-${nextTab.id}`)?.focus());
  };

  const layerPageCount = Math.max(1, Math.ceil(config.watermark_layers.length / LAYER_PAGE_SIZE));
  const safeLayerPage = Math.min(layerPage, layerPageCount - 1);
  const visibleLayers = config.watermark_layers
    .map((layer, index) => ({ layer, index }))
    .slice(safeLayerPage * LAYER_PAGE_SIZE, (safeLayerPage + 1) * LAYER_PAGE_SIZE);

  const transitionMode: FeatureMode = !config.use_transition ? "off" : config.random_transition ? "random" : "fixed";
  const effectMode: FeatureMode = !config.use_video_effect ? "off" : config.random_video_effect ? "random" : "fixed";
  const bgmMode: BgmMode = !config.use_bgm ? "off" : config.random_bgm ? "random" : "ordered";

  const changeTransitionMode = (mode: FeatureMode) => {
    onChange("use_transition", mode !== "off");
    if (mode !== "off") onChange("random_transition", mode === "random");
  };

  const changeEffectMode = (mode: FeatureMode) => {
    onChange("use_video_effect", mode !== "off");
    if (mode !== "off") onChange("random_video_effect", mode === "random");
  };

  const changeBgmMode = (mode: BgmMode) => {
    onChange("use_bgm", mode !== "off");
    if (mode !== "off") onChange("random_bgm", mode === "random");
  };

  const tabsWithErrors = new Set(validationIssues.map((issue) => issue.section).filter(Boolean));
  return (
    <aside className="inspector" aria-label="参数检查器">
      <div className="panel-heading inspector-heading">
        <div><span className="panel-kicker">输出校准</span><strong>参数检查器</strong></div>
        <span className="schema-tag">配置兼容 v2</span>
      </div>

      <div className="inspector-module-tabs" role="tablist" aria-label="参数模块">
        {INSPECTOR_TABS.map((tab, index) => (
          <button
            key={tab.id}
            id={`inspector-tab-${tab.id}`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`inspector-panel-${tab.id}`}
            tabIndex={activeTab === tab.id ? 0 : -1}
            className={`${activeTab === tab.id ? "is-active" : ""}${tabsWithErrors.has(tab.id) ? " has-error" : ""}`}
            onClick={() => onActiveTabChange(tab.id)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
          >
            {tab.label}
            {tabsWithErrors.has(tab.id) ? <span className="tab-error-dot" aria-label="该分区有未完成的配置" /> : null}
          </button>
        ))}
      </div>

      <div className="inspector-module-body">
        <div id="inspector-panel-basic" className="inspector-module-panel" role="tabpanel" aria-labelledby="inspector-tab-basic" hidden={activeTab !== "basic"}>
          <div className="inspector-paths">
            <PathField label="输入目录" name="input_dir" value={config.input_dir} placeholder="选择图片目录" onChange={(value) => onChange("input_dir", value)} onBrowse={() => onBrowseDirectory("input_dir")} />
            <PathField label="输出目录" name="output_dir" value={config.output_dir} placeholder="选择视频输出目录" onChange={(value) => onChange("output_dir", value)} onBrowse={() => onBrowseDirectory("output_dir")} />
          </div>
          <div className="parameter-grid parameter-grid-basic">
            <Field label="图片数" name="num_images"><input type="number" min={1} max={1000} value={config.num_images} aria-label="每视频图片数" onChange={(event) => onChange("num_images", Number(event.target.value))} /></Field>
            <Field label="单图时长 · 秒" name="duration"><input type="number" min={0.1} max={120} step={0.1} value={config.duration} aria-label="每张图片时长（秒）" onChange={(event) => onChange("duration", Number(event.target.value))} /></Field>
            <Field label="总时长 · 秒" name="total_duration"><input type="number" min={0} max={86400} step={0.1} value={config.total_duration} aria-label="视频总时长（秒，0 表示自动）" title="0 表示按图片数自动计算" onChange={(event) => onChange("total_duration", Number(event.target.value))} /></Field>
            <Field label="视频数" name="video_count"><input type="number" min={1} max={1000000} value={config.video_count} aria-label="视频数量" onChange={(event) => onChange("video_count", Number(event.target.value))} /></Field>
            <Field label="FPS" name="fps"><input type="number" min={1} max={120} value={config.fps} aria-label="帧率" onChange={(event) => onChange("fps", Number(event.target.value))} /></Field>
            <ResolutionField config={config} onChange={onChange} />
            <Field label="格式"><select value={config.video_format} onChange={(event) => onChange("video_format", event.target.value)}><option>mp4</option><option>mov</option><option>avi</option></select></Field>
            <Field label="编码"><select value={config.codec} onChange={(event) => onChange("codec", event.target.value)}><option>H264</option><option>mp4v</option><option>XVID</option><option>MJPG</option></select></Field>
            <Field label="码率 · kbps"><input type="number" min={500} max={100000} step={500} value={config.bitrate} onChange={(event) => onChange("bitrate", Number(event.target.value))} /></Field>
            <Field label="选图方式"><select value={config.image_selection_mode} onChange={(event) => onChange("image_selection_mode", event.target.value)}><option>随机选择</option><option>按名称排序</option></select></Field>
            <Checkbox label="保持画面比例" checked={config.keep_aspect_ratio} onChange={(value) => onChange("keep_aspect_ratio", value)} />
          </div>

          <div className="inspector-section-divider" />
          <div className="basic-mode-row">
            <SegmentedControl label="BGM 模式" value={bgmMode} options={BGM_MODE_OPTIONS} onChange={changeBgmMode} />
            <Checkbox label="循环播放" checked={config.loop_bgm} disabled={!config.use_bgm} onChange={(value) => onChange("loop_bgm", value)} />
          </div>
          <PathField label="音频目录" name="bgm_dir" value={config.bgm_dir} placeholder="选择 BGM 目录" onChange={(value) => onChange("bgm_dir", value)} onBrowse={() => onBrowseDirectory("bgm_dir")} />
          <div className="bgm-files-row" data-field="bgm_files">
            <div className="bgm-files-head">
              <span><small>BGM 素材</small><strong>{(config.bgm_files ?? []).length ? `已选 ${config.bgm_files.length} 首` : "未指定"}</strong></span>
              <span className="bgm-files-actions">
                <button type="button" className="inspector-config-button" onClick={() => setBgmPickerOpen(true)} disabled={!config.use_bgm}><LibraryBig size={14} />从素材库选择</button>
                {(config.bgm_files ?? []).length ? <button type="button" className="quiet-button" onClick={() => onChange("bgm_files", [])} disabled={!config.use_bgm}>清除</button> : null}
              </span>
            </div>
            {(config.bgm_files ?? []).length ? (
              <ul className="bgm-files-chips">
                {(config.bgm_files ?? []).map((path, index) => (
                  <li key={path}>
                    <span title={path}>{path.split(/[\\/]/).pop()}</span>
                    <button type="button" className="icon-button" onClick={() => onChange("bgm_files", (config.bgm_files ?? []).filter((_, itemIndex) => itemIndex !== index))} aria-label={`移除 BGM ${path.split(/[\\/]/).pop()}`}><X size={11} /></button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="bgm-files-hint">未指定时，导出将从「音频目录」按顺序 / 随机选取。</p>
            )}
          </div>
          <div className="parameter-grid">
            <Field label={`音量 ${Math.round(config.bgm_volume * 100)}%`}><input className="range-input" type="range" min={0.1} max={1} step={0.1} disabled={!config.use_bgm} value={config.bgm_volume} onChange={(event) => onChange("bgm_volume", Number(event.target.value))} /></Field>
            <Field label="声音策略"><select disabled={!config.use_bgm} value={config.watermark_audio} onChange={(event) => onChange("watermark_audio", event.target.value)}><option>使用BGM</option><option>使用水印</option><option>两者混合</option><option>静音</option></select></Field>
            <Field label="文件名前缀"><input value={config.custom_prefix} onChange={(event) => onChange("custom_prefix", event.target.value)} /></Field>
          </div>
          <div className="choice-row"><Checkbox label="日期前缀" checked={config.use_date_prefix} onChange={(value) => onChange("use_date_prefix", value)} /><Checkbox label="使用首图名称" checked={config.use_first_image_name} onChange={(value) => onChange("use_first_image_name", value)} /></div>
        </div>

        <div id="inspector-panel-motion" className="inspector-module-panel motion-panel" role="tabpanel" aria-labelledby="inspector-tab-motion" hidden={activeTab !== "motion"}>
          <section className="inspector-static-section">
            <header className="inspector-section-heading"><strong>转场</strong></header>
            <SegmentedControl label="模式" value={transitionMode} options={FEATURE_MODE_OPTIONS} onChange={changeTransitionMode} />
            <div className="parameter-grid parameter-grid-motion">
              <Field label="当前转场" wide><select disabled={transitionMode !== "fixed"} value={config.transition_type} onChange={(event) => onChange("transition_type", event.target.value)}>{TRANSITIONS.map((value) => <option key={value}>{value}</option>)}</select></Field>
            </div>
            <div className="random-pool-row"><span><small>随机转场池</small><strong>已选 {config.enabled_transitions.length} / {TRANSITIONS.length}</strong></span><button type="button" className="inspector-config-button" onClick={() => onOpenLibraryTab("transition")}><LibraryBig size={14} />在素材库配置</button></div>
          </section>

          <section className="inspector-static-section">
            <header className="inspector-section-heading"><strong>特效</strong></header>
            <SegmentedControl label="模式" value={effectMode} options={FEATURE_MODE_OPTIONS} onChange={changeEffectMode} />
            <div className="parameter-grid parameter-grid-motion">
              <Field label="当前特效" wide><select disabled={effectMode !== "fixed"} value={config.video_effect_type} onChange={(event) => onChange("video_effect_type", event.target.value)}><option>无特效</option>{VIDEO_EFFECTS.map((value) => <option key={value}>{value}</option>)}</select></Field>
              <Field label="强度（%）"><input disabled={effectMode === "off"} type="number" min={1} max={9999} step={1} value={config.video_effect_intensity} onChange={(event) => onChange("video_effect_intensity", Number(event.target.value))} /></Field>
              <Field label="速度"><input disabled={effectMode === "off"} type="number" min={0.01} max={9999} step={0.1} value={config.video_effect_speed} onChange={(event) => onChange("video_effect_speed", Number(event.target.value))} /></Field>
            </div>
            <div className="random-pool-row"><span><small>随机特效池</small><strong>已选 {config.enabled_video_effects.length} / {VIDEO_EFFECTS.length}</strong></span><button type="button" className="inspector-config-button" onClick={() => onOpenLibraryTab("effect")}><LibraryBig size={14} />在素材库配置</button></div>
          </section>
        </div>

        <div id="inspector-panel-watermark" className="inspector-module-panel watermark-panel" role="tabpanel" aria-labelledby="inspector-tab-watermark" hidden={activeTab !== "watermark"}>
          <section className="inspector-static-section">
            <header className="inspector-section-heading">
              <strong>视频水印</strong>
              <span className="inspector-section-actions">
                <SegmentedControl compact label="状态" value={config.use_watermark ? "on" : "off"} options={STATUS_OPTIONS} onChange={(value) => onChange("use_watermark", value === "on")} />
                <button type="button" className="inspector-config-button" onClick={() => setWatermarkPickerOpen(true)}><LibraryBig size={14} />从素材库选择</button>
              </span>
            </header>
            <PathField label="水印路径" name="watermark_path" value={config.watermark_path} placeholder="选择视频或目录" onChange={(value) => onChange("watermark_path", value)} onBrowse={() => config.watermark_mode === "文件夹" ? onBrowseDirectory("watermark_path") : onBrowseFile("watermark_path")} />
            <div className="parameter-grid">
              <Field label="路径模式"><select disabled={!config.use_watermark} value={config.watermark_mode} onChange={(event) => onChange("watermark_mode", event.target.value)}><option>单文件</option><option>文件夹</option></select></Field>
              <Field label="匹配"><select disabled={!config.use_watermark} value={config.watermark_match_method} onChange={(event) => onChange("watermark_match_method", event.target.value)}><option>循环</option><option>拉伸</option><option>单次</option></select></Field>
              <Field label="位置"><select disabled={!config.use_watermark} value={config.watermark_position} onChange={(event) => onChange("watermark_position", event.target.value)}>{WATERMARK_POSITIONS.map((value) => <option key={value}>{value}</option>)}</select></Field>
              <Field label="大小模式"><select disabled={!config.use_watermark} value={config.watermark_size_mode} onChange={(event) => onChange("watermark_size_mode", event.target.value)}>{WATERMARK_SIZE_MODES.map((value) => <option key={value}>{value}</option>)}</select></Field>
              <Field label="缩放（%）" name="watermark_scale"><input disabled={!config.use_watermark || config.watermark_size_mode !== "固定比例"} type="number" min={5} max={100} step={5} value={config.watermark_scale} aria-label="视频水印缩放比例（固定比例模式下生效）" onChange={(event) => onChange("watermark_scale", Number(event.target.value))} /></Field>
              <Field label="混合方式"><select disabled={!config.use_watermark} value={config.watermark_blend_mode} onChange={(event) => onChange("watermark_blend_mode", event.target.value)}>{BLEND_MODES.map((value) => <option key={value}>{value}</option>)}</select></Field>
            </div>
          </section>

          <section className="inspector-static-section">
            <header className="inspector-section-heading">
              <strong>图片水印</strong>
              <span className="inspector-section-actions">
                <SegmentedControl compact label="状态" value={config.use_image_watermark ? "on" : "off"} options={STATUS_OPTIONS} onChange={(value) => onChange("use_image_watermark", value === "on")} />
                <button type="button" className="quiet-button" onClick={addLayer}><Plus size={14} />添加图层</button>
              </span>
            </header>
            {visibleLayers.length ? visibleLayers.map(({ layer, index }) => (
              <div className="layer-editor-inline" key={index}>
                <div className="layer-title"><Checkbox label={`图层 ${index + 1}`} checked={layer.enabled} onChange={(value) => updateLayer(index, { enabled: value })} /><button type="button" className="icon-button danger" onClick={() => removeLayer(index)} aria-label={`删除图层 ${index + 1}`}><Trash2 size={14} /></button></div>
                <PathField label="素材" value={layer.path} placeholder="选择图片、视频或目录" onChange={(value) => updateLayer(index, { path: value })} onBrowse={() => onBrowseFile("watermark_layers", index)} />
                <div className="parameter-grid">
                  <Field label="位置"><select value={layer.position} onChange={(event) => updateLayer(index, { position: event.target.value })}>{WATERMARK_POSITIONS.map((value) => <option key={value}>{value}</option>)}</select></Field>
                  <Field label="大小"><select value={layer.size_mode} onChange={(event) => updateLayer(index, { size_mode: event.target.value })}>{WATERMARK_SIZE_MODES.map((value) => <option key={value}>{value}</option>)}</select></Field>
                  <Field label="缩放（%）"><input disabled={layer.size_mode !== "固定比例"} type="number" min={5} max={100} step={5} value={layer.scale} onChange={(event) => updateLayer(index, { scale: Number(event.target.value) })} /></Field>
                  <Field label="透明度"><input type="number" min={0.1} max={1} step={0.1} value={layer.opacity} onChange={(event) => updateLayer(index, { opacity: Number(event.target.value) })} /></Field>
                  <Field label="混合"><select value={layer.blend_mode} onChange={(event) => updateLayer(index, { blend_mode: event.target.value })}>{BLEND_MODES.map((value) => <option key={value}>{value}</option>)}</select></Field>
                </div>
                <div className="choice-row"><Checkbox label="固定图层" checked={layer.fixed} onChange={(value) => updateLayer(index, { fixed: value })} /><Checkbox label="目录随机 1 个" checked={layer.folder_random_single} onChange={(value) => updateLayer(index, { folder_random_single: value })} /></div>
              </div>
            )) : <p className="inline-empty">尚未添加图片水印图层。</p>}
            <Paginator page={safeLayerPage} pageCount={layerPageCount} label="图片水印图层分页" onChange={setLayerPage} />
          </section>
        </div>
      </div>

      <LibraryPicker
        open={bgmPickerOpen}
        onClose={() => setBgmPickerOpen(false)}
        kind="bgm"
        selected={config.bgm_files ?? []}
        onConfirmBgm={(paths) => {
          onChange("bgm_files", paths);
          setBgmPickerOpen(false);
        }}
      />

      <LibraryPicker
        open={watermarkPickerOpen}
        onClose={() => setWatermarkPickerOpen(false)}
        kind="watermark"
        onUseAsVideo={(item: LibraryItem) => {
          onChange("watermark_path", item.path);
          onChange("watermark_mode", "单文件");
          onChange("use_watermark", true);
          setWatermarkPickerOpen(false);
        }}
        onAddWatermarkLayers={(items: LibraryItem[]) => {
          const next = [...config.watermark_layers];
          for (const item of items) {
            if (!next.some((layer) => layer.path === item.path)) {
              next.push({ ...DEFAULT_WATERMARK_LAYER, path: item.path, enabled: true });
            }
          }
          onChange("watermark_layers", next);
          onChange("use_image_watermark", true);
          setWatermarkPickerOpen(false);
        }}
      />
    </aside>
  );
}
