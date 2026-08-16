import { Loader2, Music } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { engine } from "../engine";

// BGM 封面：按路径缓存提取结果，避免每次渲染都重复调用引擎
const bgmCoverCache = new Map<string, string | null>();

export function BgmCover({ path, size = "normal", overlay }: {
  path: string;
  size?: "small" | "normal";
  overlay?: ReactNode;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const cached = bgmCoverCache.get(path);
    if (cached !== undefined) {
      if (cached) setUrl(cached);
      else setFailed(true);
      return;
    }
    void engine.call<{ cover_path: string | null }>("library_audio_cover", { path }, 30_000)
      .then((result) => {
        if (cancelled) return;
        const coverUrl = result.cover_path ? engine.toAssetUrl(result.cover_path) : null;
        bgmCoverCache.set(path, coverUrl);
        if (coverUrl) setUrl(coverUrl);
        else setFailed(true);
      })
      .catch(() => {
        if (!cancelled) {
          bgmCoverCache.set(path, null);
          setFailed(true);
        }
      });
    return () => { cancelled = true; };
  }, [path]);

  return (
    <span className={`library-bgm-cover${size === "small" ? " is-small" : ""}`}>
      {url ? <img src={url} alt="" loading="lazy" /> : (
        <span className="library-bgm-cover-placeholder">
          {failed ? <Music size={16} /> : <Loader2 className="is-spinning" size={16} />}
        </span>
      )}
      {overlay}
    </span>
  );
}
