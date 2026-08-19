"""输出文件名组合规则测试：连接符 "-"、序号不补零、不注入无关文案。"""

from datetime import datetime

from src.utils.naming import compose_output_filename

STAMP = datetime(2026, 8, 16, 15, 30, 0)


def test_all_separators_are_dash():
    name = compose_output_filename(
        use_date_prefix=True,
        use_first_image_name=False,
        custom_prefix="video",
        index=1,
        video_format="mp4",
        now=STAMP,
    )
    assert name == "20260816-video-1.mp4"
    assert "_" not in name


def test_sequence_not_zero_padded():
    for index, expected in ((1, "video-1.mp4"), (9, "video-9.mp4"), (10, "video-10.mp4"), (123, "video-123.mp4")):
        name = compose_output_filename(
            use_date_prefix=False,
            use_first_image_name=False,
            custom_prefix="video",
            index=index,
            video_format="mp4",
        )
        assert name == expected, name


def test_empty_prefix_injects_no_default_text():
    # 自定义前缀为空时不应注入 "video" 之类的默认文案
    name = compose_output_filename(
        use_date_prefix=True,
        use_first_image_name=False,
        custom_prefix="",
        index=1,
        video_format="mp4",
        now=STAMP,
    )
    assert name == "20260816-1.mp4"

    bare = compose_output_filename(
        use_date_prefix=False,
        use_first_image_name=False,
        custom_prefix="   ",
        index=1,
        video_format="mov",
    )
    assert bare == "1.mov"


def test_first_image_name_mode():
    # 生产代码在调用前会去掉扩展名（os.path.splitext）
    name = compose_output_filename(
        use_date_prefix=True,
        use_first_image_name=True,
        first_image_name="海边日落",
        custom_prefix="video",
        index=3,
        video_format="mp4",
        now=STAMP,
    )
    assert name == "20260816-海边日落-3.mp4"

    no_date = compose_output_filename(
        use_date_prefix=False,
        use_first_image_name=True,
        first_image_name="海边日落",
        custom_prefix="video",
        index=3,
        video_format="mp4",
    )
    assert no_date == "海边日落-3.mp4"
