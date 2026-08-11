import { useState, type KeyboardEvent } from "react";
import { Plus, Trash2 } from "lucide-react";
import {
  BLEND_MODES,
  DEFAULT_WATERMARK_LAYER,
  RESOLUTIONS,
  TRANSITIONS,
  VIDEO_EFFECTS,
  WATERMARK_POSITIONS,
  WATERMARK_SIZE_MODES,
} from "../constants";
import type { VideoConfig, WatermarkLayer } from "../types";
import { Field, InspectorSection, PathField, PoolEditor, Toggle } from "./Controls";

type ConfigKey = keyof VideoConfig;

const INSPECTOR_TABS = [
  { id: "transition", label: "转场" },
  { id: "effect", label: "特效" },
  { id: "bgm", label: "BGM" },
  { id: "video-watermark", label: "视频水印" },
  { id: "image-watermark", label: "图片水印" },
] as const;

type InspectorTabId = (typeof INSPECTOR_TABS)[number]["id"];

export function Inspector({
  config,
  onChange,
  onBrowseDirectory,
  onBrowseFile,
}: {
  config: VideoConfig;
  onChange: <K extends ConfigKey>(key: K, value: VideoConfig[K]) => void;
  onBrowseDirectory: (key: ConfigKey) => void;
  onBrowseFile: (key: ConfigKey, layerIndex?: number) => void;
}) {
  const [activeTab, setActiveTab] = useState<InspectorTabId>("transition");

  const updateLayer = (index: number, patch: Partial<WatermarkLayer>) => {
    const next = config.watermark_layers.map((layer, layerIndex) => layerIndex === index ? { ...layer, ...patch } : layer);
    onChange("watermark_layers", next);
  };

  const addLayer = () => onChange("watermark_layers", [...config.watermark_layers, { ...DEFAULT_WATERMARK_LAYER }]);
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
    setActiveTab(nextTab.id);
    window.requestAnimationFrame(() => document.getElementById(`inspector-tab-${nextTab.id}`)?.focus());
  };

  return (
    <aside className="inspector" aria-label="参数检查器">
      <div className="panel-heading inspector-heading">
        <div>
          <span className="panel-kicker">输出校准</span>
          <strong>参数检查器</strong>
        </div>
        <span className="schema-tag">配置兼容 v2</span>
      </div>

      <div className="inspector-scroll">
        <InspectorSection title="基础参数" summary={`${config.resolution_preset} · ${config.fps} fps`} defaultOpen>
          <div className="field-grid field-grid-three">
            <PathField label="输入目录" value={config.input_dir} placeholder="选择图片目录" onChange={(value) => onChange("input_dir", value)} onBrowse={() => onBrowseDirectory("input_dir")} />
            <PathField label="输出目录" value={config.output_dir} placeholder="选择视频输出目录" onChange={(value) => onChange("output_dir", value)} onBrowse={() => onBrowseDirectory("output_dir")} />
            <Field label="图片数"><input type="number" min={1} max={1000} value={config.num_images} aria-label="每视频图片数" onChange={(event) => onChange("num_images", Number(event.target.value))} /></Field>
            <Field label="单图时长 · 秒"><input type="number" min={0.1} max={120} step={0.1} value={config.duration} aria-label="每张图片时长（秒）" onChange={(event) => onChange("duration", Number(event.target.value))} /></Field>
            <Field label="总时长 · 秒"><input type="number" min={0} max={86400} step={0.1} value={config.total_duration} aria-label="视频总时长（秒，0 表示自动）" title="0 表示按图片数自动计算" onChange={(event) => onChange("total_duration", Number(event.target.value))} /></Field>
            <Field label="视频数"><input type="number" min={1} max={1000000} value={config.video_count} aria-label="视频数量" onChange={(event) => onChange("video_count", Number(event.target.value))} /></Field>
            <Field label="FPS"><input type="number" min={1} max={120} value={config.fps} aria-label="帧率" onChange={(event) => onChange("fps", Number(event.target.value))} /></Field>
            <Field label="分辨率"><input list="resolution-options" value={config.resolution_preset} onChange={(event) => onChange("resolution_preset", event.target.value)} /><datalist id="resolution-options">{[...new Set([...RESOLUTIONS, ...config.resolution_presets])].map((value) => <option key={value} value={value} />)}</datalist></Field>
            <Field label="格式"><select value={config.video_format} onChange={(event) => onChange("video_format", event.target.value)}><option>mp4</option><option>mov</option><option>avi</option></select></Field>
            <Field label="编码"><select value={config.codec} onChange={(event) => onChange("codec", event.target.value)}><option>H264</option><option>mp4v</option><option>XVID</option><option>MJPG</option></select></Field>
            <Field label="码率 · kbps"><input type="number" min={500} max={100000} step={500} value={config.bitrate} onChange={(event) => onChange("bitrate", Number(event.target.value))} /></Field>
            <Field label="选图方式"><select value={config.image_selection_mode} onChange={(event) => onChange("image_selection_mode", event.target.value)}><option>随机选择</option><option>按名称排序</option></select></Field>
            <Toggle label="保持画面比例" checked={config.keep_aspect_ratio} onChange={(value) => onChange("keep_aspect_ratio", value)} />
          </div>
        </InspectorSection>

        <section className="inspector-tabs" aria-label="效果与媒体设置">
          <div className="inspector-tab-list" role="tablist" aria-label="效果与媒体">
            {INSPECTOR_TABS.map((tab, index) => (
              <button
                key={tab.id}
                id={`inspector-tab-${tab.id}`}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                aria-controls={`inspector-panel-${tab.id}`}
                tabIndex={activeTab === tab.id ? 0 : -1}
                className={activeTab === tab.id ? "is-active" : undefined}
                onClick={() => setActiveTab(tab.id)}
                onKeyDown={(event) => handleTabKeyDown(event, index)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div id="inspector-panel-transition" className="inspector-tab-panel" role="tabpanel" aria-labelledby="inspector-tab-transition" hidden={activeTab !== "transition"}>
            <div className="toggle-row">
              <Toggle label="启用转场" checked={config.use_transition} onChange={(value) => onChange("use_transition", value)} />
              <Toggle label="随机转场" checked={config.random_transition} disabled={!config.use_transition} onChange={(value) => onChange("random_transition", value)} />
            </div>
            <Field label="当前转场" wide>
              <select disabled={!config.use_transition} value={config.transition_type} onChange={(event) => onChange("transition_type", event.target.value)}>
                {TRANSITIONS.map((value) => <option key={value}>{value}</option>)}
              </select>
            </Field>
            <PoolEditor label="随机转场池" values={TRANSITIONS} selected={config.enabled_transitions} onChange={(value) => onChange("enabled_transitions", value)} />
          </div>

          <div id="inspector-panel-effect" className="inspector-tab-panel" role="tabpanel" aria-labelledby="inspector-tab-effect" hidden={activeTab !== "effect"}>
            <div className="toggle-row">
              <Toggle label="启用特效" checked={config.use_video_effect} onChange={(value) => onChange("use_video_effect", value)} />
              <Toggle label="随机特效" checked={config.random_video_effect} disabled={!config.use_video_effect} onChange={(value) => onChange("random_video_effect", value)} />
            </div>
            <Field label="当前特效" wide>
              <select disabled={!config.use_video_effect} value={config.video_effect_type} onChange={(event) => onChange("video_effect_type", event.target.value)}>
                <option>无特效</option>{VIDEO_EFFECTS.map((value) => <option key={value}>{value}</option>)}
              </select>
            </Field>
            <div className="field-grid">
              <Field label="强度（%）"><input disabled={!config.use_video_effect} type="number" min={1} max={9999} step={1} value={config.video_effect_intensity} onChange={(event) => onChange("video_effect_intensity", Number(event.target.value))} /></Field>
              <Field label="速度"><input disabled={!config.use_video_effect} type="number" min={0.01} max={9999} step={0.1} value={config.video_effect_speed} onChange={(event) => onChange("video_effect_speed", Number(event.target.value))} /></Field>
            </div>
            <PoolEditor label="随机特效池" values={VIDEO_EFFECTS} selected={config.enabled_video_effects} onChange={(value) => onChange("enabled_video_effects", value)} />
          </div>

          <div id="inspector-panel-bgm" className="inspector-tab-panel" role="tabpanel" aria-labelledby="inspector-tab-bgm" hidden={activeTab !== "bgm"}>
            <div className="toggle-row">
              <Toggle label="启用 BGM" checked={config.use_bgm} onChange={(value) => onChange("use_bgm", value)} />
              <Toggle label="随机" checked={config.random_bgm} disabled={!config.use_bgm} onChange={(value) => onChange("random_bgm", value)} />
              <Toggle label="循环" checked={config.loop_bgm} disabled={!config.use_bgm} onChange={(value) => onChange("loop_bgm", value)} />
            </div>
            <PathField label="音频目录" value={config.bgm_dir} placeholder="选择 BGM 目录" onChange={(value) => onChange("bgm_dir", value)} onBrowse={() => onBrowseDirectory("bgm_dir")} />
            <Field label={`音量 ${Math.round(config.bgm_volume * 100)}%`} wide><input className="range-input" type="range" min={0.1} max={1} step={0.1} disabled={!config.use_bgm} value={config.bgm_volume} onChange={(event) => onChange("bgm_volume", Number(event.target.value))} /></Field>
            <Field label="声音策略" wide><select disabled={!config.use_bgm} value={config.watermark_audio} onChange={(event) => onChange("watermark_audio", event.target.value)}><option>使用BGM</option><option>使用水印</option><option>两者混合</option><option>静音</option></select></Field>
          </div>

          <div id="inspector-panel-video-watermark" className="inspector-tab-panel" role="tabpanel" aria-labelledby="inspector-tab-video-watermark" hidden={activeTab !== "video-watermark"}>
            <Toggle label="启用视频水印" checked={config.use_watermark} onChange={(value) => onChange("use_watermark", value)} />
            <div className="field-grid">
              <Field label="路径模式"><select disabled={!config.use_watermark} value={config.watermark_mode} onChange={(event) => onChange("watermark_mode", event.target.value)}><option>单文件</option><option>文件夹</option></select></Field>
              <Field label="匹配"><select disabled={!config.use_watermark} value={config.watermark_match_method} onChange={(event) => onChange("watermark_match_method", event.target.value)}><option>循环</option><option>拉伸</option><option>单次</option></select></Field>
            </div>
            <PathField label="水印路径" value={config.watermark_path} placeholder="选择视频或目录" onChange={(value) => onChange("watermark_path", value)} onBrowse={() => config.watermark_mode === "文件夹" ? onBrowseDirectory("watermark_path") : onBrowseFile("watermark_path")} />
            <div className="field-grid">
              <Field label="大小模式"><select disabled={!config.use_watermark} value={config.watermark_size_mode} onChange={(event) => onChange("watermark_size_mode", event.target.value)}>{WATERMARK_SIZE_MODES.map((value) => <option key={value}>{value}</option>)}</select></Field>
              <Field label="混合方式"><select disabled={!config.use_watermark} value={config.watermark_blend_mode} onChange={(event) => onChange("watermark_blend_mode", event.target.value)}>{BLEND_MODES.map((value) => <option key={value}>{value}</option>)}</select></Field>
            </div>
            <div className="field-grid">
              <Field label="位置"><select disabled={!config.use_watermark} value={config.watermark_position} onChange={(event) => onChange("watermark_position", event.target.value)}>{WATERMARK_POSITIONS.map((value) => <option key={value}>{value}</option>)}</select></Field>
              <Field label="缩放（%）"><input disabled={!config.use_watermark || config.watermark_size_mode !== "固定比例"} type="number" min={5} max={100} step={5} value={config.watermark_scale} aria-label="视频水印缩放比例（固定比例模式下生效）" onChange={(event) => onChange("watermark_scale", Number(event.target.value))} /></Field>
            </div>
          </div>

          <div id="inspector-panel-image-watermark" className="inspector-tab-panel" role="tabpanel" aria-labelledby="inspector-tab-image-watermark" hidden={activeTab !== "image-watermark"}>
            <div className="layer-heading">
              <Toggle label="启用图片水印" checked={config.use_image_watermark} onChange={(value) => onChange("use_image_watermark", value)} />
              <button type="button" className="quiet-button" onClick={addLayer}><Plus size={14} />添加图层</button>
            </div>
            {config.watermark_layers.length ? (
              <div className="layer-list">
                {config.watermark_layers.map((layer, index) => (
                  <div className="layer-editor" key={`${index}-${layer.path}`}>
                    <div className="layer-title">
                      <Toggle label={`图层 ${index + 1}`} checked={layer.enabled} onChange={(value) => updateLayer(index, { enabled: value })} />
                      <button type="button" className="icon-button" onClick={() => removeLayer(index)} aria-label={`删除图层 ${index + 1}`}><Trash2 size={14} /></button>
                    </div>
                    <PathField label="素材" value={layer.path} placeholder="选择图片、视频或目录" onChange={(value) => updateLayer(index, { path: value })} onBrowse={() => onBrowseFile("watermark_layers", index)} />
                    <div className="field-grid">
                      <Field label="位置"><select value={layer.position} onChange={(event) => updateLayer(index, { position: event.target.value })}>{WATERMARK_POSITIONS.map((value) => <option key={value}>{value}</option>)}</select></Field>
                      <Field label="大小"><select value={layer.size_mode} onChange={(event) => updateLayer(index, { size_mode: event.target.value })}>{WATERMARK_SIZE_MODES.map((value) => <option key={value}>{value}</option>)}</select></Field>
                      <Field label="缩放（%）"><input type="number" min={5} max={100} step={5} value={layer.scale} onChange={(event) => updateLayer(index, { scale: Number(event.target.value) })} /></Field>
                      <Field label="透明度"><input type="number" min={0.1} max={1} step={0.1} value={layer.opacity} onChange={(event) => updateLayer(index, { opacity: Number(event.target.value) })} /></Field>
                      <Field label="混合"><select value={layer.blend_mode} onChange={(event) => updateLayer(index, { blend_mode: event.target.value })}>{BLEND_MODES.map((value) => <option key={value}>{value}</option>)}</select></Field>
                    </div>
                    <div className="toggle-row"><Toggle label="固定图层" checked={layer.fixed} onChange={(value) => updateLayer(index, { fixed: value })} /><Toggle label="目录随机 1 个" checked={layer.folder_random_single} onChange={(value) => updateLayer(index, { folder_random_single: value })} /></div>
                  </div>
                ))}
              </div>
            ) : <p className="inline-empty">尚未添加图片水印图层。</p>}
          </div>
        </section>

        <InspectorSection title="命名与输出" summary={config.custom_prefix || "video"}>
          <Field label="文件名前缀" wide><input value={config.custom_prefix} onChange={(event) => onChange("custom_prefix", event.target.value)} /></Field>
          <div className="toggle-row"><Toggle label="日期前缀" checked={config.use_date_prefix} onChange={(value) => onChange("use_date_prefix", value)} /><Toggle label="使用首图名称" checked={config.use_first_image_name} onChange={(value) => onChange("use_first_image_name", value)} /></div>
        </InspectorSection>
      </div>
    </aside>
  );
}
