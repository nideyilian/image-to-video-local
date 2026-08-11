export type FocusRegion = {
  x: number;
  y: number;
};

export const CENTER_FOCUS: FocusRegion = { x: 0.5, y: 0.5 };

/**
 * 计算“封面铺满 + 焦点居中”的变换参数。
 * 图片以 coverScale*zoom 比例显示，并平移使焦点 (fx, fy) 对齐舞台中心。
 * 为保证画面不留空白，对平移做了无缝隙约束。
 */
export function computeCoverTransform(
  stageWidth: number,
  stageHeight: number,
  imageWidth: number,
  imageHeight: number,
  fx: number,
  fy: number,
  zoom: number,
): { scale: number; tx: number; ty: number } {
  const scale = Math.max(stageWidth / imageWidth, stageHeight / imageHeight) * zoom;
  const visibleWidth = imageWidth * scale;
  const visibleHeight = imageHeight * scale;
  const rawLeft = (stageWidth - visibleWidth) / 2;
  const rawTop = (stageHeight - visibleHeight) / 2;
  const tx = stageWidth / 2 - (rawLeft + fx * visibleWidth);
  const ty = stageHeight / 2 - (rawTop + fy * visibleHeight);
  // 无缝隙平移约束：图片始终覆盖舞台，多余部分才允许平移
  const panX = (visibleWidth - stageWidth) / 2;
  const panY = (visibleHeight - stageHeight) / 2;
  const clampX = (value: number) => (panX > 0 ? Math.min(panX, Math.max(-panX, value)) : 0);
  const clampY = (value: number) => (panY > 0 ? Math.min(panY, Math.max(-panY, value)) : 0);
  return { scale, tx: clampX(tx), ty: clampY(ty) };
}

/**
 * 轻量级画面主体显著性检测：
 * 将图片缩放到粗网格后，结合边缘梯度（Sobel）、色彩饱和度与中心先验，
 * 取高于平均分值的显著区域做加权质心，得到主体焦点。
 * 任何失败场景（画布被污染、图片加载失败等）都会返回 null，由调用方降级为居中聚焦。
 */
export function findFocusRegion(src: string): Promise<FocusRegion | null> {
  return new Promise<FocusRegion | null>((resolve) => {
    const image = new Image();
    image.onload = () => {
      try {
        const cols = 64;
        const rows = Math.max(1, Math.round((image.naturalHeight / Math.max(1, image.naturalWidth)) * cols));
        const canvas = document.createElement("canvas");
        canvas.width = cols;
        canvas.height = rows;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (!context) {
          resolve(null);
          return;
        }
        context.drawImage(image, 0, 0, cols, rows);
        const pixels = context.getImageData(0, 0, cols, rows).data;

        const luminance = new Float32Array(cols * rows);
        for (let i = 0; i < cols * rows; i++) {
          luminance[i] = 0.299 * pixels[i * 4] + 0.587 * pixels[i * 4 + 1] + 0.114 * pixels[i * 4 + 2];
        }

        const gradient = new Float32Array(cols * rows);
        for (let y = 1; y < rows - 1; y++) {
          for (let x = 1; x < cols - 1; x++) {
            const gx =
              -luminance[(y - 1) * cols + x - 1] + luminance[(y - 1) * cols + x + 1]
              - 2 * luminance[y * cols + x - 1] + 2 * luminance[y * cols + x + 1]
              - luminance[(y + 1) * cols + x - 1] + luminance[(y + 1) * cols + x + 1];
            const gy =
              -luminance[(y - 1) * cols + x - 1] - 2 * luminance[(y - 1) * cols + x] - luminance[(y - 1) * cols + x + 1]
              + luminance[(y + 1) * cols + x - 1] + 2 * luminance[(y + 1) * cols + x] + luminance[(y + 1) * cols + x + 1];
            gradient[y * cols + x] = Math.hypot(gx, gy);
          }
        }

        const weights = new Float32Array(cols * rows);
        let total = 0;
        for (let y = 0; y < rows; y++) {
          for (let x = 0; x < cols; x++) {
            const i = y * cols + x;
            const r = pixels[i * 4] / 255;
            const g = pixels[i * 4 + 1] / 255;
            const b = pixels[i * 4 + 2] / 255;
            const max = Math.max(r, g, b);
            const min = Math.min(r, g, b);
            const saturation = max === 0 ? 0 : (max - min) / max;
            const dx = x / (cols - 1) - 0.5;
            const dy = y / (rows - 1) - 0.5;
            const centerBias = 1 - Math.min(1, Math.hypot(dx, dy) * 1.5);
            weights[i] = gradient[i] + saturation * 130 + centerBias * 46;
            total += weights[i];
          }
        }
        if (total <= 0) {
          resolve(null);
          return;
        }

        const mean = total / (cols * rows);
        let strongTotal = 0;
        let sx = 0;
        let sy = 0;
        for (let y = 0; y < rows; y++) {
          for (let x = 0; x < cols; x++) {
            const i = y * cols + x;
            if (weights[i] > mean) {
              strongTotal += weights[i];
              sx += weights[i] * (x / cols);
              sy += weights[i] * (y / rows);
            }
          }
        }
        if (strongTotal <= 0) {
          resolve(null);
          return;
        }
        resolve({
          x: Math.min(1, Math.max(0, sx / strongTotal)),
          y: Math.min(1, Math.max(0, sy / strongTotal)),
        });
      } catch {
        resolve(null);
      }
    };
    image.onerror = () => resolve(null);
    image.src = src;
  });
}
