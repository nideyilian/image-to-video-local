from pathlib import Path
import sys

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.video_effect_engine import (
    SOUL_OUT_CURVE_FPS,
    SOUL_OUT_MIX_CURVE,
    SOUL_OUT_SCALE_CURVE,
    apply_soul_out,
    fit_cover,
    render_frame,
)


def test_fit_cover_returns_exact_dimensions():
    source = np.full((200, 400, 3), 127, dtype=np.uint8)
    result = fit_cover(source, 108, 192)
    assert result.shape == (192, 108, 3)


def _center_zoom(source: np.ndarray, scale: float) -> np.ndarray:
    height, width = source.shape[:2]
    transform = cv2.getRotationMatrix2D(
        ((width - 1) * 0.5, (height - 1) * 0.5), 0.0, scale,
    )
    return cv2.warpAffine(
        source, transform, (width, height), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def test_soul_out_uses_jianying_default_curves():
    assert SOUL_OUT_CURVE_FPS == 29.85
    assert SOUL_OUT_MIX_CURVE == (
        0.411498, 0.340743, 0.283781, 0.237625,
        0.199993, 0.169133, 0.143688, 0.122599,
        0.037117, 0.028870, 0.022595, 0.017788,
        0.010000, 0.010000, 0.010000, 0.010000,
    )
    assert SOUL_OUT_SCALE_CURVE == (
        1.6268295, 1.7598855, 1.899264, 2.0450655,
        2.1973845, 2.3563155, 2.521950, 2.694381,
        2.8736985, 3.0599925, 3.2533515, 3.453861,
        3.453861, 3.453861, 3.453861, 3.453861,
    )


def test_soul_out_matches_single_center_zoom_mix():
    yy, xx = np.mgrid[:120, :80]
    source = np.stack((xx * 3, yy * 2, (xx + yy) % 256), axis=-1).astype(np.uint8)
    curve_index = 5
    time_sec = (curve_index + 0.1) / SOUL_OUT_CURVE_FPS
    zoomed = _center_zoom(source, SOUL_OUT_SCALE_CURVE[curve_index])
    expected = cv2.addWeighted(
        source, 1.0 - SOUL_OUT_MIX_CURVE[curve_index],
        zoomed, SOUL_OUT_MIX_CURVE[curve_index], 0.0,
    )

    result = apply_soul_out(source, time_sec=time_sec)

    assert result.shape == source.shape
    assert np.array_equal(result, expected)


def test_soul_out_repeats_every_16_curve_frames():
    source = np.arange(48 * 64 * 3, dtype=np.uint8).reshape((48, 64, 3))
    first = apply_soul_out(source, time_sec=0.1 / SOUL_OUT_CURVE_FPS)
    repeated = apply_soul_out(source, time_sec=16.1 / SOUL_OUT_CURVE_FPS)
    assert np.array_equal(first, repeated)


def test_soul_out_does_not_tint_or_bleach_uniform_input():
    source = np.full((120, 80, 3), (20, 120, 240), dtype=np.uint8)
    for curve_index in range(16):
        result = apply_soul_out(source, time_sec=(curve_index + 0.1) / SOUL_OUT_CURVE_FPS)
        assert np.array_equal(result, source)


def test_render_frame_supports_soul_out_protocol_name():
    source = np.full((120, 80, 3), 180, dtype=np.uint8)
    result = render_frame(source, "SOUL_OUT", "STATIC", 5, 30, 30)
    assert result.dtype == np.uint8
    assert result.shape == source.shape
