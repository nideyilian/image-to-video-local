# -*- coding: utf-8 -*-
"""渲染内核保真比对工具。

用于内核抽取的各个阶段：把改动前的实现与改动后的内核跑同一组参数，
逐帧比对输出的 sha256，确认搬运没有改变任何渲染结果。

用法:
    python tools/render_parity_check.py legacy  _base.json    # 走 src.gui.main_window.ImageToVideoTab
    python tools/render_parity_check.py kernel  _new.json     # 走 src.render.effects
    python tools/render_parity_check.py compare _base.json _new.json

legacy 模式用 object.__new__ 拿到 ImageToVideoTab 实例，
不执行 __init__，因此不会创建任何 Tk 控件。
"""
import sys, os, io, json, random, hashlib, contextlib
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

EFFECTS = sorted({
    "无特效", "缓慢推近", "缓慢拉远", "左右晃动", "上下浮动", "旋转漂移闪动", "旋转呼吸",
    "呼吸变焦扫光", "脉冲放大", "心跳跳动", "心跳摇摆", "圆周漂移", "环形巡航", "涡旋推拉",
    "波浪平移", "滚动快门", "故障抖动", "边缘闪烁", "镜像扫光", "径向拉伸", "径向脉冲旋转",
    "双轴呼吸", "双频摆动", "透视俯仰", "透视呼吸摆动", "水波扭曲", "鱼眼镜头", "呼吸鱼眼旋摆",
    "呼吸模糊", "旋摆模糊脉冲", "镜头呼吸", "镜头抖动呼吸", "漩涡旋转", "螺旋摆动",
    "反向双旋", "变焦摇移", "摇摆推拉", "轻微摇摆", "8字漂移", "左上平移", "右下平移",
    "灵魂出窍", "旋转摆动",
})

CASES = [
    (0.0, 3.0, 100.0, 1.0),
    (1.5, 3.0, 60.0, 1.8),
    (2.9, 3.0, 150.0, 0.5),
]


def make_image() -> np.ndarray:
    """确定性的测试图：渐变 + 高频纹理，避免纯色掩盖差异。"""
    h, w = 360, 640
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[..., 0] = (xx * 255 // max(w - 1, 1)).astype(np.uint8)
    img[..., 1] = (yy * 255 // max(h - 1, 1)).astype(np.uint8)
    img[..., 2] = ((xx + yy) * 255 // max(w + h - 2, 1)).astype(np.uint8)
    img[::7, ::5] = 255
    img[3::11, 4::9] = 0
    return img


def mode_legacy():
    import src.gui.main_window as mw

    obj = object.__new__(mw.ImageToVideoTab)

    def call(img, et, ts, ds, inten, sp):
        return obj.apply_single_image_effect(img, et, ts, ds, inten, sp)

    return call


def mode_kernel():
    from src.render import effects as eff

    def call(img, et, ts, ds, inten, sp):
        return eff.apply_single_image_effect(img, et, ts, ds, inten, sp)

    return call


def digest(arr) -> dict:
    a = np.ascontiguousarray(arr)
    return {
        "shape": list(a.shape),
        "dtype": str(a.dtype),
        "sha256": hashlib.sha256(a.tobytes()).hexdigest(),
        "sum": float(a.sum()),
    }


class _RecordingWriter:
    """只记录写入的帧，不接真实编码器：比对精确，且不依赖 ffmpeg。"""

    def __init__(self):
        self.frames = []

    def write(self, frame):
        self.frames.append(np.ascontiguousarray(frame).copy())

    def isOpened(self):
        return True

    def release(self):
        pass


BASIC_TRANSITIONS = [
    "apply_fade_transition",
    "apply_blinds_transition",
    "apply_slide_transition",
    "apply_dissolve_transition",
    "apply_wipe_transition",
]

TRANSITION_TYPES = ["淡入淡出", "百叶窗", "滑动", "溶解", "擦除", "无转场", "未知转场"]


def run_transitions(mode: str, out_path: str) -> int:
    import src.core.transition_engine as te

    if mode == "legacy":
        import src.gui.main_window as mw

        obj = object.__new__(mw.ImageToVideoTab)

        def basic(name, *args):
            return getattr(obj, name)(*args)

        def compose(a, b, writer, n, tt, engine):
            obj.transition_engine = engine
            return obj.apply_transition(a, b, writer, n, tt)
    else:
        from src.render import transitions as tr

        def basic(name, *args):
            return getattr(tr, name)(*args)

        def compose(a, b, writer, n, tt, engine):
            return tr.apply_transition(a, b, writer, n, tt, engine)

    a = make_image()
    b = np.roll(make_image(), 37, axis=1)
    results, errors = {}, []

    # 1) 五个基础转场：逐帧混合结果
    for name in BASIC_TRANSITIONS:
        for idx, total in [(0, 10), (3, 10), (5, 10), (9, 10), (1, 24)]:
            key = "%s|%d/%d" % (name, idx, total)
            random.seed(7)
            np.random.seed(7)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    out = basic(name, a.copy(), b.copy(), idx, total)
            except Exception as exc:
                errors.append({"key": key, "error": "%s: %s" % (type(exc).__name__, exc)})
                continue
            results[key] = {"none": True} if out is None else digest(out)

    # 2) apply_transition：记录写入的帧序列，覆盖 fallback 与 turbo 两条路径
    engines = [("none", None)]
    try:
        engines.append(("turbo", te.get_turbo_transition_engine()))
    except Exception as exc:
        errors.append({"key": "engine:turbo", "error": "%s: %s" % (type(exc).__name__, exc)})

    for eng_name, engine in engines:
        for tt in TRANSITION_TYPES:
            for n in (4, 9):
                key = "compose|%s|%s|%d" % (eng_name, tt, n)
                writer = _RecordingWriter()
                random.seed(11)
                np.random.seed(11)
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        compose(a.copy(), b.copy(), writer, n, tt, engine)
                except Exception as exc:
                    errors.append({"key": key, "error": "%s: %s" % (type(exc).__name__, exc)})
                    continue
                results[key] = {"frames": [digest(f) for f in writer.frames]}

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"mode": "trans-" + mode, "cases": len(results),
                   "results": results, "errors": errors}, f, ensure_ascii=False, indent=1)
    print("[trans-%s] cases=%d errors=%d -> %s" % (mode, len(results), len(errors), out_path))
    for e in errors[:10]:
        print("  ERR", e["key"], e["error"])
    return 1 if errors else 0


# ---------------- 图片装载 / 排序 / 读图 / 缩放 ----------------

def _images_fixture(tmpdir: str):
    """造含中文名、子目录、非图片文件的素材目录。"""
    from src.utils.opencv_silent import import_cv2_silent

    cv2 = import_cv2_silent()
    d = os.path.join(tmpdir, "素材 目录")
    sub = os.path.join(d, "子目录")
    os.makedirs(sub, exist_ok=True)
    names = ["图1.png", "图10.png", "图2.png", "abc.png", "IMG_0042.jpg", "B-3.png"]
    paths = []
    for idx, n in enumerate(names):
        p = os.path.join(d, n)
        img = np.full((20 + idx * 3, 30 + idx * 4, 3), 10 + idx * 20, dtype=np.uint8)
        ok, buf = cv2.imencode(".png" if n.endswith(".png") else ".jpg", img)
        buf.tofile(p)
        paths.append(p)
    with open(os.path.join(d, "notes.txt"), "w", encoding="utf-8") as f:
        f.write("not an image")
    ok, buf = cv2.imencode(".png", np.full((12, 12, 3), 200, dtype=np.uint8))
    buf.tofile(os.path.join(sub, "深层图.png"))
    return d, paths


class _FakeAccelerator:
    """用于覆盖 safe_read_image 的 turbo 分支。"""

    enabled = True

    def __init__(self):
        self.calls = []

    def optimized_image_read(self, path):
        self.calls.append(str(path))
        return np.full((14, 18, 3), 33, dtype=np.uint8)


def _images_calls(mode: str):
    """统一约定：notify 始终是最后一个位置参数。"""
    if mode == "legacy":
        import src.gui.main_window as mw

        obj = object.__new__(mw.ImageToVideoTab)
        obj.turbo_accelerator = None

        def norm(p, notify):
            obj.update_status = notify
            return obj.normalize_path(p)

        def nkey(f, notify):
            obj.update_status = notify
            return obj.natural_sort_key(f)

        def sortn(ps, notify):
            obj.update_status = notify
            return obj.sort_images_naturally(ps)

        def read(p, acc=None, notify=None):
            obj.update_status = notify
            obj.turbo_accelerator = acc
            return obj.safe_read_image(p)

        def resize(i, w, h, notify):
            obj.update_status = notify
            return obj.resize_with_aspect_ratio(i, w, h)

        def getlist(args, acc=None, notify=None):
            obj.update_status = notify
            obj.turbo_accelerator = acc
            return obj.get_images_list(*args)

        return {"normalize_path": norm, "natural_sort_key": nkey,
                "sort_images_naturally": sortn, "safe_read_image": read,
                "resize_with_aspect_ratio": resize, "get_images_list": getlist}

    from src.render import images as im

    return {
        "normalize_path": lambda p, notify: im.normalize_path(p, notify),
        "natural_sort_key": lambda f, notify: im.natural_sort_key(f),
        "sort_images_naturally": lambda ps, notify: im.sort_images_naturally(ps, notify),
        "safe_read_image": lambda p, acc=None, notify=None: im.safe_read_image(p, notify, acc),
        "resize_with_aspect_ratio": lambda i, w, h, notify: im.resize_with_aspect_ratio(i, w, h),
        "get_images_list": lambda args, acc=None, notify=None: im.get_images_list(
            *args, notify=notify, turbo_accelerator=acc),
    }


def _summ(v):
    if v is None:
        return {"none": True}
    if isinstance(v, np.ndarray):
        return digest(v)
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return str(v)


def run_images(mode: str, out_path: str) -> int:
    import tempfile, shutil

    # 固定目录：legacy 与 kernel 是两次独立进程，路径必须一致才有可比性
    tmp = os.path.join(tempfile.gettempdir(), "render_parity_images")
    shutil.rmtree(tmp, ignore_errors=True)
    results, errors = {}, []
    try:
        d, paths = _images_fixture(tmp)
        c = _images_calls(mode)
        acc = _FakeAccelerator()

        def rec(key, fn, *args):
            msgs = []
            try:
                out = fn(*args, msgs.append)
            except Exception as exc:
                errors.append({"key": key, "error": "%s: %s" % (type(exc).__name__, exc)})
                return
            results[key] = {"out": _summ(out), "msgs": [str(m) for m in msgs]}

        for p in [paths[0], paths[-1], os.path.join(d, "不存在.png"),
                  os.path.join(d, "..", "素材 目录"), None, ""]:
            rec("normalize_path|%s" % p, c["normalize_path"], p)

        for f in ["图1.png", "图10.png", "图2.png", "abc.png",
                  "IMG_0042.jpg", "B-3.png", "无后缀", ""]:
            rec("natural_sort_key|%s" % f, c["natural_sort_key"], f)

        for tag, ps in [("all", paths), ("rev", list(reversed(paths))),
                        ("empty", []), ("one", paths[:1])]:
            rec("sort_images_naturally|%s" % tag, c["sort_images_naturally"], list(ps))

        for i, p in enumerate(list(paths) + [os.path.join(d, "不存在.png"),
                                             os.path.join(d, "notes.txt")]):
            for accv in (None, acc):
                rec("safe_read_image|%d|%s" % (i, "turbo" if accv is not None else "plain"),
                    c["safe_read_image"], p, accv)

        src = np.full((37, 53, 3), 77, dtype=np.uint8)
        for w, h in [(100, 100), (200, 50), (10, 400), (53, 37)]:
            rec("resize|%dx%d" % (w, h), c["resize_with_aspect_ratio"], src, w, h)

        for sel in ["随机选择", "按名称排序", "按子文件夹抽取"]:
            for limit in (None, 3):
                np.random.seed(5)
                random.seed(5)
                rec("get_images_list|%s|%s" % (sel, limit),
                    c["get_images_list"], (d, limit, sel), None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"mode": "images-" + mode, "cases": len(results),
                   "results": results, "errors": errors}, f, ensure_ascii=False, indent=1)
    print("[images-%s] cases=%d errors=%d -> %s" % (mode, len(results), len(errors), out_path))
    for e in errors[:10]:
        print("  ERR", e["key"], e["error"])
    return 1 if errors else 0


# ---------------- 子进程 / 文件 / 元信息 基础工具 ----------------

class _FakeVar:
    def __init__(self, v):
        self._v = v

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


def _norm_text(s: str) -> str:
    """抹掉日志时间戳，使两次运行可比。"""
    import re as _re
    return _re.sub(r"\[\d{2}:\d{2}:\d{2}\]", "[TIME]", str(s))


def _process_calls(mode: str):
    if mode == "legacy":
        import src.gui.main_window as mw

        obj = object.__new__(mw.ImageToVideoTab)
        obj.fps = _FakeVar(30.0)

        def logstage(stage, msg, log_file, log_func):
            obj._pipeline_log_file = log_file
            return obj._log_pipeline_stage(stage, msg, log_func)

        def runproc(cmd, retries, log_func):
            return obj._run_process_with_retry(cmd, "TEST", 30, retries, log_func)

        return {
            "even": lambda f, log_func=None: obj._ensure_even_frame(f),
            "replace": lambda s, d, log_func=None: obj._safe_replace_file(s, d),
            "probe": lambda p, log_func=None: obj._probe_video_meta(p),
            "logstage": logstage,
            "runproc": runproc,
        }

    from src.render import process as pr

    return {
        "even": lambda f, log_func=None: pr.ensure_even_frame(f),
        "replace": lambda s, d, log_func=None: pr.safe_replace_file(s, d),
        "probe": lambda p, log_func=None: pr.probe_video_meta(p),
        "logstage": lambda stage, msg, log_file, log_func:
            pr.log_pipeline_stage(stage, msg, log_func, log_file),
        "runproc": lambda cmd, retries, log_func:
            pr.run_process_with_retry(cmd, "TEST", 30, retries, log_func, None),
    }


def run_process_checks(mode: str, out_path: str) -> int:
    import tempfile, shutil, sys as _sys, glob, contextlib as _ctx

    base = os.path.join(tempfile.gettempdir(), "render_parity_process")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    c = _process_calls(mode)
    results, errors = {}, []

    def rec(key, fn, *args):
        msgs, out = [], None
        try:
            with _ctx.redirect_stdout(io.StringIO()) as buf:
                out = fn(*args, msgs.append)
            printed = buf.getvalue()
        except Exception as exc:
            errors.append({"key": key, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        results[key] = {"out": _summ(out),
                        "msgs": [_norm_text(m) for m in msgs],
                        "stdout": _norm_text(printed)}

    # 1) ensure_even_frame
    for h, w in [(10, 20), (11, 21), (1, 1), (3, 4), (7, 10)]:
        rec("even|%dx%d" % (h, w), c["even"], np.full((h, w, 3), 5, dtype=np.uint8))
    rec("even|none", c["even"], None)

    # 2) safe_replace_file
    def _mk(p, content):
        with open(p, "wb") as f:
            f.write(content)

    a, b, cc, dd = [os.path.join(base, n) for n in ("a.bin", "b.bin", "c.bin", "d.bin")]
    _mk(a, b"AAA")
    rec("replace|new_dst", c["replace"], a, b)
    results["replace|new_dst|file"] = {"dst": open(b, "rb").read().decode() if os.path.exists(b) else None,
                                       "src_exists": os.path.exists(a)}
    _mk(cc, b"CCC")
    _mk(dd, b"OLD")
    rec("replace|overwrite_dst", c["replace"], cc, dd)
    results["replace|overwrite_dst|file"] = {"dst": open(dd, "rb").read().decode(),
                                             "src_exists": os.path.exists(cc)}
    rec("replace|missing_src", c["replace"], os.path.join(base, "nope.bin"), os.path.join(base, "x.bin"))

    # 3) run_process_with_retry（避开超时分支：timeout 下限是 10s）
    rec("runproc|ok", c["runproc"], [_sys.executable, "-c", "print('ok')"], 1)
    rec("runproc|fail", c["runproc"], [_sys.executable, "-c", "import sys; sys.exit(3)"], 1)
    rec("runproc|fail_retry2", c["runproc"], [_sys.executable, "-c", "import sys; sys.exit(3)"], 2)
    rec("runproc|missing_exe", c["runproc"], [os.path.join(base, "no_such_exe")], 1)

    # 4) probe_video_meta
    mp4s = sorted(glob.glob(os.path.join(ROOT, "output", "*.mp4")))
    if mp4s:
        rec("probe|real_mp4", c["probe"], mp4s[0])
    rec("probe|missing", c["probe"], os.path.join(base, "nope.mp4"))
    txt = os.path.join(base, "notvideo.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("hello")
    rec("probe|not_video", c["probe"], txt)

    # 5) log_pipeline_stage
    lf = os.path.join(base, "pipeline_%s.log" % mode)
    rec("logstage|with_file", c["logstage"], "STAGE1", "hello world", lf)
    rec("logstage|no_file", c["logstage"], "STAGE2", "fallback", None)
    results["logstage|file_content"] = {
        "body": _norm_text(open(lf, encoding="utf-8").read()) if os.path.exists(lf) else None}

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"mode": "process-" + mode, "cases": len(results),
                   "results": results, "errors": errors}, f, ensure_ascii=False, indent=1)
    print("[process-%s] cases=%d errors=%d -> %s" % (mode, len(results), len(errors), out_path))
    for e in errors[:10]:
        print("  ERR", e["key"], e["error"])
    return 1 if errors else 0


# ---------------- 编码 / 容器解析 ----------------

def _codec_calls(mode: str):
    """返回 (calls, msgs, codec_var)。两侧的界面侧状态完全一致。"""
    cv = _FakeVar("XVID")
    probe_cache = {}
    runtime_probe = {"preferred_cv_codec": "mp4v"}
    fps = _FakeVar(30.0)
    msgs = []

    if mode == "legacy":
        import src.gui.main_window as mw

        obj = object.__new__(mw.ImageToVideoTab)
        obj.codec_var = cv
        obj._codec_probe_cache = probe_cache
        obj._runtime_probe = runtime_probe
        obj.ffmpeg_available = True
        obj.startupinfo = None
        obj.fps = fps
        obj.update_status = msgs.append
        return {
            "ext": lambda p, lf=None: obj._get_output_extension(p),
            "temp": lambda p, s, lf=None: obj._build_temp_output_path(p, s),
            "muxer": lambda p, lf=None: obj._get_ffmpeg_muxer_for_output(p),
            "vcod": lambda p, pc, lf=None: obj._get_container_compatible_vcodecs(p, pc),
            "acod": lambda p, lf=None: obj._get_container_compatible_acodec(p),
            "sel": lambda lf=None: obj._get_selected_codec_name(),
            "ffvc": lambda lf=None: obj._get_ffmpeg_vcodec(),
            "strict": lambda p, lf=None: obj._get_strict_ffmpeg_vcodec_for_output(p),
            "fourcc": lambda lf=None: obj._resolve_cv_fourcc(),
            "pfourcc": lambda lf=None: obj._resolve_processing_fourcc(),
            "h264": lambda lf=None: obj.get_h264_codec(),
            "fallback": lambda lf=None: obj._get_fallback_processing_fourcc(),
            "avail": lambda c, force, lf=None: obj.check_codec_availability(c, force),
            "reenc": lambda s, d, lf=None: obj._reencode_video_to_selected_codec(s, d, lf),
            "probe": lambda p, lf=None: obj._log_output_probe(p, lf),
        }, msgs, cv

    from src.render import codec as cd

    ctx = cd.CodecContext(
        codec_provider=lambda: cv.get(),
        runtime_probe=runtime_probe,
        ffmpeg_available=True,
        startupinfo=None,
        notify=msgs.append,
        fps_provider=lambda: fps.get(),
        probe_cache=probe_cache,
    )
    return {
        "ext": lambda p, lf=None: cd.get_output_extension(p, ctx),
        "temp": lambda p, s, lf=None: cd.build_temp_output_path(p, s, ctx),
        "muxer": lambda p, lf=None: cd.get_ffmpeg_muxer_for_output(p, ctx),
        "vcod": lambda p, pc, lf=None: cd.get_container_compatible_vcodecs(p, pc, ctx),
        "acod": lambda p, lf=None: cd.get_container_compatible_acodec(p, ctx),
        "sel": lambda lf=None: cd.get_selected_codec_name(ctx),
        "ffvc": lambda lf=None: cd.get_ffmpeg_vcodec(ctx),
        "strict": lambda p, lf=None: cd.get_strict_ffmpeg_vcodec_for_output(p, ctx),
        "fourcc": lambda lf=None: cd.resolve_cv_fourcc(ctx),
        "pfourcc": lambda lf=None: cd.resolve_processing_fourcc(ctx),
        "h264": lambda lf=None: cd.get_h264_codec(ctx),
        "fallback": lambda lf=None: cd.get_fallback_processing_fourcc(ctx),
        "avail": lambda c, force, lf=None: cd.check_codec_availability(c, force, ctx),
        "reenc": lambda s, d, lf=None: cd.reencode_video_to_selected_codec(s, d, lf, ctx),
        "probe": lambda p, lf=None: cd.log_output_probe(p, lf, ctx),
    }, msgs, cv


def run_codec(mode: str, out_path: str) -> int:
    import tempfile, shutil, glob, contextlib as _ctx

    base = os.path.join(tempfile.gettempdir(), "render_parity_codec")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    calls, msgs, cv = _codec_calls(mode)
    results, errors = {}, []

    def rec(key, fn, *args):
        del msgs[:]
        try:
            with _ctx.redirect_stdout(io.StringIO()):
                out = fn(*args)
        except Exception as exc:
            errors.append({"key": key, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        results[key] = {"out": _summ(out), "msgs": [_norm_text(m) for m in msgs]}

    # 1) 纯路径/容器解析
    for name in ["a.mp4", "b.MKV", "c.mov", "d.avi", "e.webm", "f.ts", "no_ext", "g.MP4"]:
        p = os.path.join(base, name)
        rec("ext|%s" % name, calls["ext"], p)
        rec("temp|%s" % name, calls["temp"], p, "_tmp")
        rec("muxer|%s" % name, calls["muxer"], p)
        rec("acod|%s" % name, calls["acod"], p)
        rec("strict|%s" % name, calls["strict"], p)
    for name in ["a.mp4", "b.MKV", "d.avi"]:
        p = os.path.join(base, name)
        rec("vcod|%s|none" % name, calls["vcod"], p, None)
        rec("vcod|%s|libx264" % name, calls["vcod"], p, "libx264")

    # 2) 依赖用户选择编码器
    for sel in ["XVID", "H264", "MJPG", "MP4V", "不存在的编码器"]:
        cv.set(sel)
        rec("sel|%s" % sel, calls["sel"])
        rec("ffvc|%s" % sel, calls["ffvc"])
        rec("fourcc|%s" % sel, calls["fourcc"])
        rec("pfourcc|%s" % sel, calls["pfourcc"])
        rec("h264|%s" % sel, calls["h264"])
        rec("fallback|%s" % sel, calls["fallback"])
    cv.set("XVID")

    # 3) 编码器可用性探测（含缓存路径）
    for codec in ["XVID", "avc1", "H264", "NO_SUCH_CODEC"]:
        rec("avail|%s|cached" % codec, calls["avail"], codec, False)
        rec("avail|%s|force" % codec, calls["avail"], codec, True)

    # 4) 真实视频：重编码与输出探测
    mp4s = sorted(glob.glob(os.path.join(ROOT, "output", "*.mp4")))
    if mp4s:
        dst = os.path.join(base, "reencoded.mp4")
        rec("reenc|real", calls["reenc"], mp4s[0], dst, None)
        results["reenc|real|exists"] = {"exists": os.path.exists(dst)}
        rec("probe|real", calls["probe"], mp4s[0], None)
        rec("probe|missing", calls["probe"], os.path.join(base, "nope.mp4"), None)
    txt = os.path.join(base, "x.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("hi")
    rec("probe|not_video", calls["probe"], txt, None)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"mode": "codec-" + mode, "cases": len(results),
                   "results": results, "errors": errors}, f, ensure_ascii=False, indent=1)
    print("[codec-%s] cases=%d errors=%d -> %s" % (mode, len(results), len(errors), out_path))
    for e in errors[:10]:
        print("  ERR", e["key"], e["error"])
    return 1 if errors else 0


# ---------------- 控制原语 / 背景音乐 ----------------

def _audio_calls(mode: str):
    INIT = {"bgm_dir": None, "_bgm_files": None, "use_bgm": True,
            "random_bgm": False, "loop_bgm": True, "watermark_audio": "使用BGM"}
    msgs, events = [], []

    class _Acc:
        enabled = True

        def realtime_cleanup(self, force=False):
            events.append(("acc", bool(force)))

    class _Eng:
        def realtime_cleanup(self, force=False):
            events.append(("eng", bool(force)))

    acc, eng = _Acc(), _Eng()

    if mode == "legacy":
        import src.gui.main_window as mw

        obj = object.__new__(mw.ImageToVideoTab)
        for k, v in INIT.items():
            setattr(obj, k, _FakeVar(v))
        obj.update_status = msgs.append
        obj.turbo_accelerator = acc
        obj.transition_engine = eng
        obj.cancel_requested = False
        obj.pause_event = None
        obj.fps = _FakeVar(30.0)
        obj._last_cache_cleanup = 0.0
        obj._cache_cleanup_interval = 2.0

        setv = lambda name, value: getattr(obj, name).set(value)

        def do_wait(cancel, pause_event):
            obj.cancel_requested = cancel
            obj.pause_event = pause_event
            return obj._wait_for_processing_control(0.01)

        def do_cleanup(base_ts, force):
            obj._last_cache_cleanup = base_ts
            obj._maybe_realtime_cleanup(force)
            return obj._last_cache_cleanup

        return {
            "wait": do_wait, "cleanup": do_cleanup, "setv": setv,
            "getaudio": lambda d: obj.get_audio_files(d),
            "bgmcand": lambda: obj._resolve_bgm_candidates(),
            "bgmsel": lambda: obj._select_bgm_file(),
            "addaudio": lambda v, a, vol: obj.add_audio_with_ffmpeg(v, a, vol),
        }, msgs, events

    from src.render import audio as au
    from src.render import context as cx
    from src.render import controls as ct

    state = dict(INIT)
    ctx = cx.RenderContext(
        read=lambda name, default=None: state.get(name, default),
        ffmpeg_available=True,
        startupinfo=None,
        notify=msgs.append,
        fps_provider=lambda: 30.0,
        cancel_provider=lambda: False,
        pause_event=None,
        turbo_accelerator=acc,
        transition_engine=eng,
    )
    setv = lambda name, value: state.__setitem__(name, value)

    def do_wait(cancel, pause_event):
        ctx.cancel_provider = (lambda: cancel)
        ctx.pause_event = pause_event
        return ct.wait_for_processing_control(0.01, ctx)

    def do_cleanup(base_ts, force):
        return ct.maybe_realtime_cleanup(acc, eng, base_ts, 2.0, force, ctx)

    return {
        "wait": do_wait, "cleanup": do_cleanup, "setv": setv,
        "getaudio": lambda d: au.get_audio_files(d, ctx),
        "bgmcand": lambda: au.resolve_bgm_candidates(ctx),
        "bgmsel": lambda: au.select_bgm_file(ctx),
        "addaudio": lambda v, a, vol: au.add_audio_with_ffmpeg(v, a, vol, ctx),
    }, msgs, events


def run_audio(mode: str, out_path: str) -> int:
    import tempfile, shutil, glob, threading, time, contextlib as _ctx

    base = os.path.join(tempfile.gettempdir(), "render_parity_audio")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    calls, msgs, events = _audio_calls(mode)
    results, errors = {}, []

    for n in ["a.mp3", "b.WAV", "c.m4a", "d.ogg", "e.flac", "f.aac",
              "g.txt", "h.mp4", "i.mp3.bak"]:
        with open(os.path.join(base, n), "wb") as f:
            f.write(b"x")
    os.makedirs(os.path.join(base, "sub"), exist_ok=True)

    def rec(key, fn, *args):
        del msgs[:]
        try:
            with _ctx.redirect_stdout(io.StringIO()):
                out = fn(*args)
        except Exception as exc:
            errors.append({"key": key, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        results[key] = {"out": _summ(out), "msgs": [_norm_text(m) for m in msgs]}

    # 1) 音频目录扫描
    rec("getaudio|dir", calls["getaudio"], base)
    rec("getaudio|missing", calls["getaudio"], os.path.join(base, "nope"))

    # 2) BGM 候选
    calls["setv"]("_bgm_files", None)
    calls["setv"]("bgm_dir", base)
    rec("bgmcand|dir", calls["bgmcand"])
    calls["setv"]("_bgm_files", [os.path.join(base, "a.mp3"), os.path.join(base, "nope.mp3")])
    rec("bgmcand|explicit", calls["bgmcand"])
    calls["setv"]("_bgm_files", None)
    calls["setv"]("bgm_dir", os.path.join(base, "nope"))
    rec("bgmcand|empty", calls["bgmcand"])
    calls["setv"]("bgm_dir", base)

    # 3) BGM 选择
    for use in (True, False):
        for strat in ("使用BGM", "两者混合", "仅水印音频"):
            for rnd in (False, True):
                calls["setv"]("use_bgm", use)
                calls["setv"]("watermark_audio", strat)
                calls["setv"]("random_bgm", rnd)
                random.seed(9)
                rec("bgmsel|%s|%s|%s" % (use, strat, rnd), calls["bgmsel"])
    calls["setv"]("use_bgm", True)
    calls["setv"]("watermark_audio", "使用BGM")
    calls["setv"]("random_bgm", False)

    # 4) 暂停 / 取消应答
    def ev(set_now):
        e = threading.Event()
        if set_now:
            e.set()
        return e

    rec("wait|cancel", calls["wait"], True, ev(True))
    rec("wait|nopause", calls["wait"], False, None)
    rec("wait|already_set", calls["wait"], False, ev(True))

    e2 = threading.Event()
    t = threading.Thread(target=lambda: (time.sleep(0.1), e2.set()), daemon=True)
    t.start()
    del msgs[:]
    out = calls["wait"](False, e2)
    t.join(timeout=3)
    results["wait|paused_then_resume"] = {"out": _summ(out), "msgs": []}

    # 5) 实时内存清理
    now = time.time()
    for key, base_ts, force in [("cleanup|fresh", now, False),
                                ("cleanup|stale", now - 100.0, False),
                                ("cleanup|force", now, True)]:
        del events[:]
        after = calls["cleanup"](base_ts, force)
        results[key] = {"cleaned": bool(after != base_ts), "events": list(events)}

    # 6) 真实混音
    mp4s = sorted(glob.glob(os.path.join(ROOT, "output", "*.mp4")))
    mp3s = sorted(glob.glob(os.path.join(ROOT, "output", "*.mp3")))
    if mp4s and mp3s:
        vid = os.path.join(base, "with_bgm.mp4")
        shutil.copy2(mp4s[0], vid)
        before = os.path.getsize(vid)
        rec("addaudio|real", calls["addaudio"], vid, mp3s[0], 0.5)
        results["addaudio|real|file"] = {
            "exists": os.path.exists(vid),
            "changed": os.path.getsize(vid) != before if os.path.exists(vid) else False,
        }
        rec("addaudio|no_such_video", calls["addaudio"], os.path.join(base, "nope.mp4"), mp3s[0], 0.5)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"mode": "audio-" + mode, "cases": len(results),
                   "results": results, "errors": errors}, f, ensure_ascii=False, indent=1)
    print("[audio-%s] cases=%d errors=%d -> %s" % (mode, len(results), len(errors), out_path))
    for e in errors[:10]:
        print("  ERR", e["key"], e["error"])
    return 1 if errors else 0


# ---------------- 水印 / 单图合成 ----------------

WATERMARK_W2K = {
    "_calc_overlay_geometry": "calc_overlay_geometry",
    "_select_video_watermark_file": "select_video_watermark_file",
    "_get_video_watermark_blend_mode": "get_video_watermark_blend_mode",
    "_get_video_watermark_alpha": "get_video_watermark_alpha",
    "_get_ffmpeg_blend_mode": "get_ffmpeg_blend_mode",
    "_collect_fixed_layer_specs_for_ffmpeg": "collect_fixed_layer_specs_for_ffmpeg",
    "_safe_read_image_with_alpha": "safe_read_image_with_alpha",
    "_normalize_watermark_layers": "normalize_watermark_layers",
    "_get_image_files_in_dir": "get_image_files_in_dir",
    "_prepare_image_watermark_layers": "prepare_image_watermark_layers",
    "_apply_image_watermark_layer": "apply_image_watermark_layer",
    "apply_blend_mode": "apply_blend_mode",
    "apply_image_watermark_layers": "apply_image_watermark_layers",
    "add_fixed_image_watermarks_to_video": "add_fixed_image_watermarks_to_video",
    "verify_watermark_file": "verify_watermark_file",
    "get_watermark_files": "get_watermark_files",
    "resize_image_hq": "resize_image_hq",
    "blend_image_with_video_frame_hq": "blend_image_with_video_frame_hq",
    "blend_image_with_video_frame": "blend_image_with_video_frame",
}

WM_INIT = {
    "use_watermark": False,
    "watermark_type": "视频",
    "watermark_path": "",
    "watermark_mode": "单文件",
    "watermark_blend_mode": "正常",
    "watermark_layers": [],
    "_current_video_index": 0,
    "bitrate": 8000,
    "_pipeline_log_file": None,
}
# Tk 变量形式的字段（其余为普通属性）
WM_VARS = {"use_watermark", "watermark_type", "watermark_path",
           "watermark_mode", "watermark_blend_mode", "bitrate"}


def _watermark_calls(mode: str):
    msgs = []

    if mode == "legacy":
        import src.gui.main_window as mw

        obj = object.__new__(mw.ImageToVideoTab)
        for k, v in WM_INIT.items():
            setattr(obj, k, _FakeVar(v) if k in WM_VARS else v)
        obj.update_status = msgs.append
        obj.startupinfo = None
        obj.ffmpeg_available = True
        obj.fps = _FakeVar(30.0)

        def setv(name, value):
            cur = getattr(obj, name, None)
            if isinstance(cur, _FakeVar):
                cur.set(value)
            else:
                setattr(obj, name, value)

        def call(tk_name, *args):
            return getattr(obj, tk_name)(*args)

        return call, setv, msgs

    from src.render import context as cx
    from src.render import watermark as wm

    state = dict(WM_INIT)
    ctx = cx.RenderContext(
        read=lambda name, default=None: state.get(name, default),
        ffmpeg_available=True,
        startupinfo=None,
        notify=msgs.append,
        fps_provider=lambda: 30.0,
        cancel_provider=lambda: False,
    )
    setv = lambda name, value: state.__setitem__(name, value)

    def call(tk_name, *args):
        return getattr(wm, WATERMARK_W2K[tk_name])(ctx, *args)

    return call, setv, msgs


def run_watermark(mode: str, out_path: str) -> int:
    import tempfile, shutil, glob, contextlib as _ctx
    from src.utils.opencv_silent import import_cv2_silent

    cv2 = import_cv2_silent()
    base = os.path.join(tempfile.gettempdir(), "render_parity_watermark")
    shutil.rmtree(base, ignore_errors=True)
    imgdir = os.path.join(base, "图层素材")
    os.makedirs(imgdir, exist_ok=True)

    def save_png(path, w, h, alpha=False):
        if alpha:
            arr = np.zeros((h, w, 4), dtype=np.uint8)
            arr[..., 3] = 255
            arr[..., 0] = 200
        else:
            arr = np.full((h, w, 3), 120, dtype=np.uint8)
        ok, buf = cv2.imencode(".png", arr)
        buf.tofile(path)

    wm1 = os.path.join(imgdir, "水印1.png")
    wm2 = os.path.join(imgdir, "水印2.png")
    wm_alpha = os.path.join(imgdir, "带透明.png")
    save_png(wm1, 80, 40)
    save_png(wm2, 120, 60)
    save_png(wm_alpha, 60, 30, alpha=True)
    with open(os.path.join(base, "note.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    for n in ["w1.mp4", "w2.MOV", "w3.avi", "w4.mkv", "w5.txt"]:
        with open(os.path.join(base, n), "wb") as f:
            f.write(b"v")

    call, setv, msgs = _watermark_calls(mode)
    results, errors = {}, []

    def rec(key, *args):
        del msgs[:]
        try:
            with _ctx.redirect_stdout(io.StringIO()):
                out = args[0](*args[1:])
        except Exception as exc:
            errors.append({"key": key, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        results[key] = {"out": _summ(out), "msgs": [_norm_text(m) for m in msgs]}

    # 1) 叠加几何
    for sm in ["自适应覆盖", "完全覆盖", "固定比例", "未知模式"]:
        for pos in ["左上", "右上", "左下", "中心", "右下"]:
            rec("geom|%s|%s" % (sm, pos), call, "_calc_overlay_geometry",
                1920, 1080, 400, 200, sm, 25.0, pos)

    # 2) 混合模式映射
    for bm in ["正常", "滤色", "叠加", "正片叠底", "变亮", "变暗", "相加", "未知"]:
        rec("alpha|%s" % bm, call, "_get_video_watermark_alpha", bm)
        rec("ffblend|%s" % bm, call, "_get_ffmpeg_blend_mode", bm)
    rec("vbmode|default", call, "_get_video_watermark_blend_mode")
    setv("watermark_blend_mode", "滤色")
    rec("vbmode|set", call, "_get_video_watermark_blend_mode")
    setv("watermark_blend_mode", "正常")

    # 3) 水印文件枚举
    rec("wmfiles|dir", call, "get_watermark_files", base)
    rec("wmfiles|missing", call, "get_watermark_files", os.path.join(base, "nope"))

    # 4) 水印有效性
    rec("verify|off", call, "verify_watermark_file")
    setv("use_watermark", True)
    rec("verify|bad_path", call, "verify_watermark_file")
    setv("watermark_path", os.path.join(base, "note.txt"))
    rec("verify|not_video", call, "verify_watermark_file")
    mp4s = sorted(glob.glob(os.path.join(ROOT, "output", "*.mp4")))
    if mp4s:
        setv("watermark_path", mp4s[0])
        rec("verify|real", call, "verify_watermark_file")

    # 5) 图层规范化 / 目录扫描
    rec("imgs|dir", call, "_get_image_files_in_dir", imgdir)
    setv("watermark_layers", "not-a-list")
    rec("norm|bad", call, "_normalize_watermark_layers")
    layers = [
        {"enabled": True, "type": "图片", "path": wm1, "position": "右下",
         "size_mode": "固定比例", "scale": 20.0, "blend_mode": "正常", "opacity": 0.5,
         "fixed": True},
        {"enabled": True, "type": "图片", "path": imgdir, "position": "左上",
         "size_mode": "自适应覆盖", "scale": 30.0, "blend_mode": "滤色", "opacity": 0.8,
         "fixed": True, "folder_random_single": False},
        {"enabled": False, "type": "图片", "path": wm2, "fixed": True},
        {"enabled": True, "type": "视频", "path": wm2, "fixed": True},
    ]
    setv("watermark_layers", layers)
    rec("norm|layers", call, "_normalize_watermark_layers")
    rec("prepare", call, "_prepare_image_watermark_layers")
    rec("collect", call, "_collect_fixed_layer_specs_for_ffmpeg")

    # 6) 透明通道读取
    rec("alpha|rgb", call, "_safe_read_image_with_alpha", wm1)
    rec("alpha|rgba", call, "_safe_read_image_with_alpha", wm_alpha)
    rec("alpha|missing", call, "_safe_read_image_with_alpha", os.path.join(base, "nope.png"))

    # 7) 混合模式合成
    bg = np.full((120, 200, 3), 60, dtype=np.uint8)
    fg = np.full((40, 60, 3), 220, dtype=np.uint8)
    for m in ["正常", "滤色", "叠加", "正片叠底", "变亮", "变暗", "相加", "未知"]:
        rec("blend|%s" % m, call, "apply_blend_mode", bg, fg, m, 0.6)

    # 8) 单图层/多图层水印
    layer1 = {"enabled": True, "type": "图片", "path": wm1, "position": "右下",
              "size_mode": "固定比例", "scale": 20.0, "blend_mode": "正常", "opacity": 0.5}
    rec("layer|one", call, "_apply_image_watermark_layer", bg, layer1, 0)
    rec("layers|all", call, "apply_image_watermark_layers", bg, [layer1], 0)
    rec("layers|empty", call, "apply_image_watermark_layers", bg, [], 0)

    # 9) 高质量缩放 / 视频帧混合
    src = np.full((90, 160, 3), 100, dtype=np.uint8)
    for tw, th in [(320, 180), (480, 270), (200, 400)]:
        rec("hq|%dx%d" % (tw, th), call, "resize_image_hq", src, tw, th, "适应", True)
    frame = np.full((90, 160, 3), 200, dtype=np.uint8)
    rec("blendframe|hq", call, "blend_image_with_video_frame_hq", src, frame, "右下")
    rec("blendframe|plain", call, "blend_image_with_video_frame", src, frame, "右下")

    # 10) 视频水印文件选择
    setv("watermark_type", "视频")
    setv("watermark_path", mp4s[0] if mp4s else wm1)
    setv("watermark_mode", "单文件")
    rec("select|single", call, "_select_video_watermark_file", None)
    setv("watermark_mode", "文件夹")
    rec("select|folder", call, "_select_video_watermark_file", None)
    setv("_current_video_index", 1)
    rec("select|folder_idx1", call, "_select_video_watermark_file", None)
    setv("use_watermark", False)
    rec("select|off", call, "_select_video_watermark_file", None)
    setv("use_watermark", True)
    setv("watermark_path", "")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"mode": "watermark-" + mode, "cases": len(results),
                   "results": results, "errors": errors}, f, ensure_ascii=False, indent=1)
    print("[watermark-%s] cases=%d errors=%d -> %s" % (mode, len(results), len(errors), out_path))
    for e in errors[:12]:
        print("  ERR", e["key"], e["error"])
    return 1 if errors else 0


# ---------------- 端到端：真实渲染一路走到底 ----------------

PIPE_W2K = {
    "create_video": "create_video",
    "create_video_turbo_enhanced": "create_video_turbo_enhanced",
    "create_video_with_ffmpeg": "create_video_with_ffmpeg",
    "_has_postprocess_work": "has_postprocess_work",
    "_postprocess_video_output": "postprocess_video_output",
    "_run_unified_postprocess_ffmpeg": "run_unified_postprocess_ffmpeg",
    "_run_fixed_layers_ffmpeg_only": "run_fixed_layers_ffmpeg_only",
}
PIPE_MODULE = {
    "create_video": "compositor", "create_video_turbo_enhanced": "compositor",
    "create_video_with_ffmpeg": "encoder", "_has_postprocess_work": "encoder",
    "_postprocess_video_output": "postprocess", "_run_unified_postprocess_ffmpeg": "postprocess",
    "_run_fixed_layers_ffmpeg_only": "postprocess",
}


def _pipeline_calls(mode: str):
    import glob

    imgs = sorted(glob.glob(os.path.join(ROOT, "output", "*.png")))[:3]
    msgs = []

    if mode == "legacy":
        import src.gui.main_window as mw

        obj = object.__new__(mw.ImageToVideoTab)
        obj.update_status = msgs.append
        obj.update_progress = lambda v: None
        obj.reset_progress = lambda *a, **k: None
        obj.reset_overall_progress = lambda *a, **k: None
        obj._set_absolute_progress = lambda *a, **k: None
        obj._maybe_realtime_cleanup = lambda *a, **k: None
        obj.codec_var = _FakeVar("XVID")
        for n, v in [("bitrate", 4000), ("use_video_effect", False),
                     ("video_effect_type", "无特效"), ("video_effect_intensity", 100.0),
                     ("video_effect_speed", 1.0), ("fps", 10),
                     ("loop_bgm", True), ("use_bgm", False), ("random_bgm", False),
                     ("bgm_dir", ""), ("watermark_audio", "使用BGM"),
                     ("use_watermark", False), ("watermark_type", "视频"),
                     ("watermark_path", ""), ("watermark_mode", "单文件"),
                     ("watermark_blend_mode", "正常"), ("watermark_size_mode", "自适应覆盖"),
                     ("watermark_scale", 20.0)]:
            setattr(obj, n, _FakeVar(v))
        obj.turbo_accelerator = None
        obj.transition_engine = None
        obj.ffmpeg_available = True
        obj.startupinfo = None
        obj._codec_probe_cache = {}
        obj._runtime_probe = {}
        obj.cancel_requested = False
        obj.pause_event = None
        obj.watermark_layers = []
        obj._current_video_index = 0
        obj._bgm_files = None
        obj._last_cache_cleanup = 0.0
        obj._cache_cleanup_interval = 2.0
        obj._pipeline_log_file = None
        obj._progress_phase_label = "渲染中"
        obj._progress_render_weight = 1.0

        def call(name, *args):
            return getattr(obj, name)(*args)

        return call, imgs, msgs

    import src.render.compositor as cp
    import src.render.encoder as en
    import src.render.postprocess as pp
    from src.render import context as cx

    state = {
        "bitrate": 4000, "use_video_effect": False, "video_effect_type": "无特效",
        "video_effect_intensity": 100.0, "video_effect_speed": 1.0,
        "loop_bgm": True, "use_bgm": False, "random_bgm": False, "bgm_dir": "",
        "watermark_audio": "使用BGM", "use_watermark": False, "watermark_type": "视频",
        "watermark_path": "", "watermark_mode": "单文件",
        "watermark_blend_mode": "正常", "watermark_size_mode": "自适应覆盖",
        "watermark_scale": 20.0, "watermark_layers": [], "_current_video_index": 0,
        "_bgm_files": None, "_pipeline_log_file": None,
        "_progress_phase_label": "渲染中", "_progress_render_weight": 1.0,
    }
    ctx = cx.RenderContext(
        read=lambda name, default=None: state.get(name, default),
        set_value=lambda name, value: state.__setitem__(name, value),
        codec_provider=lambda: "XVID",
        runtime_probe={},
        probe_cache={},
        ffmpeg_available=True,
        startupinfo=None,
        notify=msgs.append,
        progress=lambda v: None,
        reset_progress=lambda *a, **k: None,
        reset_overall_progress=lambda *a, **k: None,
        set_absolute_progress=lambda *a, **k: None,
        cancel_provider=lambda: False,
        pause_event=None,
        fps_provider=lambda: 10.0,
    )
    mods = {"compositor": cp, "encoder": en, "postprocess": pp}

    def call(name, *args):
        return getattr(mods[PIPE_MODULE[name]], PIPE_W2K[name])(ctx, *args)

    return call, imgs, msgs


def run_pipeline(mode: str, out_path: str) -> int:
    import tempfile, shutil, contextlib as _ctx

    base = os.path.join(tempfile.gettempdir(), "render_parity_pipeline")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    call, imgs, msgs = _pipeline_calls(mode)
    results, errors = {}, []

    # 自造素材，避免依赖 output/ 的内容
    from src.utils.opencv_silent import import_cv2_silent

    _cv2 = import_cv2_silent()
    imgdir = os.path.join(base, "输入图")
    os.makedirs(imgdir, exist_ok=True)
    imgs = []
    for i, (w, h) in enumerate([(320, 180), (320, 180), (400, 300)]):
        p = os.path.join(imgdir, "图%d.png" % (i + 1))
        ok, buf = _cv2.imencode(".png", np.full((h, w, 3), 40 + i * 60, dtype=np.uint8))
        buf.tofile(p)
        imgs.append(p)

    def run_case(key, fn, *args, keep_msgs=True):
        del msgs[:]
        try:
            with _ctx.redirect_stdout(io.StringIO()):
                out = fn(*args)
        except Exception as exc:
            errors.append({"key": key, "error": "%s: %s" % (type(exc).__name__, exc)})
            return None
        results[key] = {"out": _summ(out)}
        if keep_msgs:
            results[key]["msgs"] = [_norm_text(m) for m in msgs][:12]
        return out

    # 1) 纯判定
    run_case("has_postproc|empty", lambda: call("_has_postprocess_work", []))
    run_case("has_postproc|layers", lambda: call("_has_postprocess_work", [
        {"enabled": True, "type": "图片", "path": imgs[0], "fixed": True}]))

    # 2) create_video -> create_video_with_ffmpeg（真实渲染）
    out1 = os.path.join(base, "out1.mp4")
    got = run_case("create_video", lambda: call("create_video", imgs, out1, 1.0, 10, 320, 180))
    if got is not None:
        results["create_video|file"] = {
            "exists": os.path.exists(out1),
            "size_gt": os.path.getsize(out1) > 1000 if os.path.exists(out1) else False,
        }
        from src.render.process import probe_video_meta
        meta = probe_video_meta(out1)
        results["create_video|meta"] = meta

    # 3) 空图层后处理（应直接返回）；其日志含耗时数字，故只比对返回值
    run_case("postproc|empty", lambda: call("_postprocess_video_output", out1, [], "右下"),
             keep_msgs=False)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"mode": "pipeline-" + mode, "cases": len(results),
                   "results": results, "errors": errors}, f, ensure_ascii=False, indent=1)
    print("[pipeline-%s] cases=%d errors=%d -> %s" % (mode, len(results), len(errors), out_path))
    for e in errors[:6]:
        print("  ERR", e["key"], e["error"])
    return 1 if errors else 0


def run(mode: str, out_path: str) -> int:
    call = mode_legacy() if mode == "legacy" else mode_kernel()
    base = make_image()
    results, errors = {}, []
    for et in EFFECTS:
        for ts, ds, inten, sp in CASES:
            key = "%s|%.2f|%.2f|%.1f|%.2f" % (et, ts, ds, inten, sp)
            random.seed(42)
            np.random.seed(42)
            try:
                out = call(base.copy(), et, ts, ds, inten, sp)
            except Exception as exc:
                errors.append({"key": key, "error": "%s: %s" % (type(exc).__name__, exc)})
                continue
            if out is None:
                results[key] = {"none": True}
                continue
            arr = np.ascontiguousarray(out)
            results[key] = {
                "shape": list(arr.shape),
                "dtype": str(arr.dtype),
                "sha256": hashlib.sha256(arr.tobytes()).hexdigest(),
                "sum": float(arr.sum()),
            }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "cases": len(results), "results": results, "errors": errors},
                  f, ensure_ascii=False, indent=1)
    print("[%s] cases=%d errors=%d -> %s" % (mode, len(results), len(errors), out_path))
    for e in errors[:10]:
        print("  ERR", e["key"], e["error"])
    return 1 if errors else 0


def compare(a_path: str, b_path: str) -> int:
    with open(a_path, encoding="utf-8") as f:
        a = json.load(f)
    with open(b_path, encoding="utf-8") as f:
        b = json.load(f)
    ra, rb = a["results"], b["results"]
    print("A(%s) cases=%d   B(%s) cases=%d" % (a["mode"], len(ra), b["mode"], len(rb)))
    miss = sorted(set(ra) ^ set(rb))
    diff = sorted(k for k in ra if k in rb and ra[k] != rb[k])
    print("key set diff: %d   frame mismatch: %d" % (len(miss), len(diff)))
    for k in miss[:10]:
        print("  MISSING", k)
    for k in diff[:10]:
        print("  DIFF", k, "\n    A=", ra[k], "\n    B=", rb[k])
    if not miss and not diff:
        print("RESULT: IDENTICAL")
        return 0
    print("RESULT: MISMATCH")
    return 1


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd in ("legacy", "kernel"):
        return run(cmd, sys.argv[2])
    if cmd in ("trans-legacy", "trans-kernel"):
        return run_transitions(cmd.split("-", 1)[1], sys.argv[2])
    if cmd in ("images-legacy", "images-kernel"):
        return run_images(cmd.split("-", 1)[1], sys.argv[2])
    if cmd in ("process-legacy", "process-kernel"):
        return run_process_checks(cmd.split("-", 1)[1], sys.argv[2])
    if cmd in ("codec-legacy", "codec-kernel"):
        return run_codec(cmd.split("-", 1)[1], sys.argv[2])
    if cmd in ("audio-legacy", "audio-kernel"):
        return run_audio(cmd.split("-", 1)[1], sys.argv[2])
    if cmd in ("watermark-legacy", "watermark-kernel"):
        return run_watermark(cmd.split("-", 1)[1], sys.argv[2])
    if cmd in ("pipeline-legacy", "pipeline-kernel"):
        return run_pipeline(cmd.split("-", 1)[1], sys.argv[2])
    if cmd == "compare":
        return compare(sys.argv[2], sys.argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
