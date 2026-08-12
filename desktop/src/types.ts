export type WatermarkLayer = {
  enabled: boolean;
  path: string;
  position: string;
  fixed: boolean;
  folder_random_single: boolean;
  size_mode: string;
  scale: number;
  blend_mode: string;
  opacity: number;
};

export type VideoConfig = {
  input_dir: string;
  output_dir: string;
  num_images: number;
  duration: number;
  total_duration: number;
  fps: number;
  video_count: number;
  video_format: string;
  resolution_preset: string;
  resolution_presets: string[];
  keep_aspect_ratio: boolean;
  use_transition: boolean;
  transition_type: string;
  random_transition: boolean;
  enabled_transitions: string[];
  use_video_effect: boolean;
  video_effect_type: string;
  random_video_effect: boolean;
  enabled_video_effects: string[];
  video_effect_intensity: number;
  video_effect_speed: number;
  use_bgm: boolean;
  bgm_dir: string;
  random_bgm: boolean;
  bgm_volume: number;
  loop_bgm: boolean;
  codec: string;
  use_watermark: boolean;
  watermark_type: string;
  watermark_position: string;
  watermark_match_method: string;
  watermark_audio: string;
  watermark_size_mode: string;
  watermark_scale: number;
  use_image_watermark: boolean;
  watermark_layers: WatermarkLayer[];
  watermark_mode: string;
  watermark_path: string;
  watermark_blend_mode: string;
  use_date_prefix: boolean;
  use_first_image_name: boolean;
  custom_prefix: string;
  image_selection_mode: string;
  bitrate: number;
  width?: number;
  height?: number;
  [key: string]: unknown;
};

export type PreviewFrame = {
  source: string;
  previewPath: string;
  previewUrl: string;
  width: number;
  height: number;
};

export type PreviewAsset = PreviewFrame & {
  frames: PreviewFrame[];
};

export type ValidationIssue = {
  field: string;
  section: string;
  message: string;
};

export type Workspace = {
  id: string;
  name: string;
  config: VideoConfig;
  imageCount: number | null;
  preview: PreviewAsset | null;
  validationErrors: string[];
  validationIssues: ValidationIssue[];
  dirty: boolean;
};

export type EngineHealth = {
  protocol: number;
  engine: string;
  pid: number;
  capabilities: string[];
};

export type EngineState = {
  connected: boolean;
  connecting: boolean;
  previewOnly: boolean;
  message: string;
  health: EngineHealth | null;
};

export type SystemSnapshot = {
  cpu_percent: number;
  memory_percent: number;
  memory_available_gb: number;
  process_memory_mb: number;
  disk_free_gb: number;
  ffmpeg_available: boolean;
  ffmpeg_path: string | null;
};

export type JobStatus =
  | "queued"
  | "running"
  | "paused"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed";

export type JobState = {
  job_id: string;
  workspaceId: string;
  workspaceName: string;
  status: JobStatus;
  paused: boolean;
  cancel_requested: boolean;
  progress: number;
  overall: number;
  speed: string | null;
  message: string;
  started_at: number | null;
  finished_at: number | null;
  return_code: number | null;
  outputPath: string;
  configSummary: string;
  demo?: boolean;
};

export type EngineEvent = {
  type: "event";
  event: string;
  payload: Record<string, unknown> & { job_id?: string };
};
