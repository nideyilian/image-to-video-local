"""批量任务编排：选图、转场/特效计划、多个视频的生成循环。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出。
**worker与界面共用这条路径**，避免出现两套实现。
界面侧配置全部通过 ``read_value`` / ``set_value`` 存取；
启动按钮、is_processing 等纯 UI 状态由界面层自行收尾。
本模块不导入任何 GUI 库。
"""

from __future__ import annotations

import os
import random
import time

from ..utils.combination import combination_total, plan_combinations
from ..utils.naming import compose_output_filename
from ..utils.timeline import cycle_images_to_duration, timeline_slot_count
from ..utils.transition_constants import GUI_TRANSITIONS
from ..engine.config import SUBFOLDER_SELECTION_MODE, scan_subfolders
from .codec import get_selected_codec_name, get_strict_ffmpeg_vcodec_for_output
from .compositor import create_video_turbo_enhanced
from .context import (RenderContext, emit_reset_overall_progress, notify, read_value,
                      set_value, should_cancel)
from .controls import maybe_realtime_cleanup
from .images import get_images_list
from .plan import VIDEO_EFFECTS, compute_video_frame_plan


def _wait_pause(ctx) -> None:
    ev = ctx.pause_event
    if ev is not None:
        ev.wait()


def _cleanup(ctx, force: bool = False) -> None:
    last = maybe_realtime_cleanup(
        ctx.turbo_accelerator,
        ctx.transition_engine,
        read_value(ctx, "_last_cache_cleanup", 0.0),
        read_value(ctx, "_cache_cleanup_interval", 2.0),
        force,
        ctx,
    )
    set_value(ctx, "_last_cache_cleanup", last)


def get_enabled_transitions(ctx):
    """获取当前启用的转场效果列表"""
    # 检查是否有override_transitions属性
    if read_value(ctx, "override_transitions") is not None and read_value(ctx, "override_transitions", None):
        return read_value(ctx, "override_transitions", None)
        
    # 否则检查enabled_transitions
    if read_value(ctx, "enabled_transitions") is not None:
        transitions = read_value(ctx, "enabled_transitions", None)
        # 新版结构：list[str]
        if isinstance(transitions, list):
            enabled = [t for t in transitions if t in GUI_TRANSITIONS]
            if enabled:
                return enabled
        # 兼容旧版结构：dict[str, tk.BooleanVar]
        elif isinstance(transitions, dict):
            enabled = []
            for trans, var in transitions.items():
                try:
                    if var.get():
                        enabled.append(trans)
                except Exception:
                    continue
            enabled = [t for t in enabled if t in GUI_TRANSITIONS]
            if enabled:
                return enabled
            
    # 默认返回淡入淡出
    return ["淡入淡出"]

def build_random_transition_plan(ctx, video_count):
    """为多个视频生成随机转场计划，尽量避免连续重复。"""
    count = max(0, int(video_count))
    if count <= 0:
        return []

    enabled_pool = get_enabled_transitions(ctx, )
    pool = [t for t in enabled_pool if t in GUI_TRANSITIONS]
    if not pool:
        pool = ["淡入淡出"]

    # 只有1个效果时只能重复
    if len(pool) == 1:
        return [pool[0]] * count

    plan = []
    last_transition = None
    while len(plan) < count:
        batch = pool.copy()
        random.shuffle(batch)
        # 避免跨批次首尾重复
        if last_transition is not None and batch and batch[0] == last_transition and len(batch) > 1:
            batch[0], batch[1] = batch[1], batch[0]
        for transition in batch:
            if len(plan) >= count:
                break
            if last_transition is not None and transition == last_transition:
                continue
            plan.append(transition)
            last_transition = transition

        # 保险：极端情况下补齐
        if len(plan) < count:
            fallback = next((t for t in pool if t != last_transition), pool[0])
            plan.append(fallback)
            last_transition = fallback

    return plan

def get_enabled_video_effects(ctx):
    """获取当前启用的随机特效池。"""
    if read_value(ctx, "enabled_video_effects") is not None and isinstance(read_value(ctx, "enabled_video_effects", None), list):
        valid = [e for e in read_value(ctx, "enabled_video_effects", None) if e in VIDEO_EFFECTS and e != "无特效"]
        if valid:
            return valid
    return [e for e in VIDEO_EFFECTS if e != "无特效"]


def run_batch(ctx):
    """处理视频生成 - 主要处理逻辑"""
    try:
        # 获取参数
        input_dir = read_value(ctx, "input_dir", "").strip()
        output_dir = read_value(ctx, "output_dir", "").strip()
        num_images = read_value(ctx, "num_images", 1)
        video_count = read_value(ctx, "video_count", 1)
        selection_mode = read_value(ctx, "image_selection_mode", "随机选择")  # 获取图片选择方式

        try:
            timeline_slot_count(read_value(ctx, "duration", 3.0), read_value(ctx, "total_duration", 0))
        except ValueError as exc:
            notify(ctx, str(exc))
            return False
        
        # 参数验证
        if not input_dir:
            notify(ctx, "请选择输入目录")
            return False
        
        if not os.path.exists(input_dir):
            notify(ctx, "输入目录不存在")
            return False
        
        if not output_dir:
            notify(ctx, "请选择输出目录")
            return False

        # 严格编码器-容器兼容性校验（主渲染与后处理统一）
        _vfmt = str(read_value(ctx, "video_format", "mp4"))
        probe_output = os.path.join(output_dir, "probe." + _vfmt.lstrip("."))
        strict_codec = get_strict_ffmpeg_vcodec_for_output(probe_output, ctx)
        if not strict_codec:
            notify(ctx,
                f"编码器/容器不兼容：编码器={get_selected_codec_name(ctx)}，格式={_vfmt}，请调整后重试"
            )
            return False
        
        # 创建输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 获取图片列表
        notify(ctx, f"正在获取图片列表（模式：{selection_mode}）...")
        subfolder_groups: list[tuple[str, list[str]]] = []
        if selection_mode == SUBFOLDER_SELECTION_MODE:
            # 「按子文件夹抽取」：每个直接子文件夹出一张，按子文件夹名顺序组成一轮。
            subfolder_groups, skipped_subfolders = scan_subfolders(input_dir)
            if skipped_subfolders:
                notify(ctx, 
                    f"以下子文件夹没有可用图片，已跳过：{'、'.join(skipped_subfolders)}"
                )
            all_images = [image for _name, images in subfolder_groups for image in images]
        else:
            all_images = get_images_list(input_dir, limit_count=None, selection_mode=selection_mode,
                            notify=ctx.notify, turbo_accelerator=ctx.turbo_accelerator)
        
        if not all_images:
            if selection_mode == SUBFOLDER_SELECTION_MODE:
                notify(ctx, "输入目录里没有包含图片的子文件夹，请放入形如 1、2、3 的子文件夹")
            else:
                notify(ctx, "目录中没有找到图片文件")
            return False
        
        # 检查图片数量
        if selection_mode == SUBFOLDER_SELECTION_MODE:
            # 一轮 = 每个子文件夹一张，数量由子文件夹个数决定，与「图片数」无关。
            combination_pool = combination_total([len(images) for _name, images in subfolder_groups])
            notify(ctx, 
                f"{len(subfolder_groups)} 个子文件夹共可组成 {combination_pool} 种组合，将生成 {video_count} 个视频"
            )
            if len(subfolder_groups) < 2:
                notify(ctx, 
                    f"提示：只找到 1 个子文件夹（{subfolder_groups[0][0]}），一轮只有 1 张图，循环后是静止画面"
                )
            if video_count > combination_pool:
                notify(ctx, 
                    f"组合数量不足：只有 {combination_pool} 种组合，需要 {video_count} 个视频；"
                    f"超出部分会复用组合，且各组合出现次数最多相差 1 次"
                )
        elif selection_mode == "按名称排序":
            min_required = video_count * num_images
            if len(all_images) < min_required:
                notify(ctx, f"图片数量不足，共有{len(all_images)}张，生成{video_count}个视频需要{min_required}张（每个{num_images}张）")
                return False
        else:
            if len(all_images) < num_images:
                notify(ctx, f"图片数量不足，只有{len(all_images)}张，需要{num_images}张")
                return False
            # 随机选择模式下，要求每个视频首图不重复。
            if len(all_images) < video_count:
                notify(ctx, 
                    f"图片数量不足以保证首图不重复：共有{len(all_images)}张，计划生成{video_count}个视频"
                )
                return False
        
        notify(ctx, f"找到{len(all_images)}张图片，将生成{video_count}个视频")
        
        # 生成多个视频
        successful_videos = 0
        overall_start_ts = time.time()
        set_value(ctx, "_task_start_ts", overall_start_ts)
        emit_reset_overall_progress(ctx, video_count)
        _cleanup(ctx, force=True)
        used_first_images = set()
        # 组合计划一次性生成：跨视频统一去重，保证每个组合最多出现一次，
        # 只有当视频数超过组合总数时才重复，且重复被摊平。
        video_combinations: list[list[str]] = []
        if selection_mode == SUBFOLDER_SELECTION_MODE:
            video_combinations = plan_combinations(
                [images for _name, images in subfolder_groups],
                video_count,
            )
        transition_plan = []
        if read_value(ctx, "use_transition", True) and read_value(ctx, "random_transition", False):
            transition_plan = build_random_transition_plan(ctx, video_count)
            if transition_plan:
                notify(ctx, f"[RANDOM] 已生成转场计划: {' | '.join(transition_plan)}")
        for video_index in range(video_count):
            if should_cancel(ctx):
                notify(ctx, "已取消处理")
                return False
            _wait_pause(ctx)
            set_value(ctx, "current_video_index", video_index)
            _cleanup(ctx, )
            notify(ctx, f"正在生成第{video_index + 1}个视频...")
            
            # 根据选择模式获取图片
            if selection_mode == SUBFOLDER_SELECTION_MODE:
                selected_images = list(video_combinations[video_index])
                picked_names = " / ".join(
                    f"{name}:{os.path.basename(image)}"
                    for (name, _images), image in zip(subfolder_groups, selected_images)
                )
                notify(ctx, f"第{video_index + 1}个视频按子文件夹顺序抽取: {picked_names}")
            elif selection_mode == "按名称排序":
                start_index = video_index * num_images
                selected_images = []
                for i in range(num_images):
                    if should_cancel(ctx):
                        notify(ctx, "已取消处理")
                        return False
                    _wait_pause(ctx)
                    img_index = start_index + i
                    if img_index < len(all_images):
                        selected_images.append(all_images[img_index])
                
                notify(ctx, f"第{video_index + 1}个视频使用图片 {start_index+1}-{start_index+len(selected_images)}: {[os.path.basename(img) for img in selected_images]}")
            else:
                import random
                # 先随机首图（未使用过），再补齐剩余图片，确保“首图不重复”。
                first_candidates = [img for img in all_images if img not in used_first_images]
                if not first_candidates:
                    notify(ctx, "随机首图池已耗尽，无法继续保证首图不重复")
                    return False
                first_image = random.choice(first_candidates)
                used_first_images.add(first_image)

                target_count = min(num_images, len(all_images))
                remain_need = max(0, target_count - 1)
                remain_pool = [img for img in all_images if img != first_image]
                remain_images = random.sample(remain_pool, min(remain_need, len(remain_pool)))
                selected_images = [first_image] + remain_images
                notify(ctx, f"第{video_index + 1}个视频随机选择图片: {[os.path.basename(img) for img in selected_images]}")

            source_image_count = len(selected_images)
            selected_images = cycle_images_to_duration(
                selected_images,
                read_value(ctx, "duration", 3.0),
                read_value(ctx, "total_duration", 0),
            )
            if len(selected_images) != source_image_count:
                notify(ctx, 
                    f"第{video_index + 1}个视频按总时长循环为 {len(selected_images)} 个图片片段"
                )
            
            if read_value(ctx, "progress_info_var") is not None:
                set_value(ctx, "progress_info_var", f"视频进度: {video_index + 1}/{video_count}")
            
            # 生成输出文件名：连接符统一为 "-"、末尾序号不补零、
            # 前缀为空不注入默认文案（见 src/utils/naming.py）
            from ..utils.naming import compose_output_filename

            first_image_name = ""
            if selected_images:
                first_image_name = os.path.splitext(os.path.basename(selected_images[0]))[0]
            output_filename = compose_output_filename(
                use_date_prefix=read_value(ctx, "use_date_prefix", False),
                use_first_image_name=read_value(ctx, "use_first_image_name", False),
                first_image_name=first_image_name,
                custom_prefix=read_value(ctx, "custom_prefix", ""),
                index=video_index + 1,
                video_format=read_value(ctx, "video_format", "mp4"),
            )
            
            output_path = os.path.join(output_dir, output_filename)
            
            # 调用创建视频方法 - 修复转场效果和Turbo加速
            # 检查转场效果是否启用
            transition_frames = 15 if read_value(ctx, "use_transition", True) else 0
            
            # 处理随机转场
            if read_value(ctx, "use_transition", True):
                if read_value(ctx, "random_transition", False):
                    transition_type = (
                        transition_plan[video_index]
                        if video_index < len(transition_plan)
                        else "淡入淡出"
                    )
                    notify(ctx, f"[RANDOM] 第{video_index + 1}个视频随机转场: {transition_type}")
                else:
                    transition_type = read_value(ctx, "transition_type", "淡入淡出")
            else:
                transition_type = "无转场"

            # 处理随机特效（按视频随机一次）
            video_effect_type_for_video = read_value(ctx, "video_effect_type", "无特效")
            random_effect_enabled = (
                read_value(ctx, "use_video_effect", False)
                and read_value(ctx, "random_video_effect", False)
                and int(video_count) >= 1
            )
            if random_effect_enabled:
                enabled_effects = get_enabled_video_effects(ctx, )
                if enabled_effects:
                    video_effect_type_for_video = random.choice(enabled_effects)
                    notify(ctx, f"[RANDOM] 第{video_index + 1}个视频随机特效: {video_effect_type_for_video}")
            
            notify(ctx, 
                f"第{video_index + 1}个视频 - 转场: {transition_type}, 特效: {video_effect_type_for_video}, 帧数: {transition_frames}"
            )
            
            # 设置当前视频索引，供视频水印文件夹模式使用
            set_value(ctx, "_current_video_index", video_index)
            per_video_start_ts = time.time()
            
            success = create_video_turbo_enhanced(ctx, 
                selected_images,
                output_path,
                read_value(ctx, "duration", 3.0),
                read_value(ctx, "fps", 30),
                read_value(ctx, "width", 1920),
                read_value(ctx, "height", 1080),
                bool(read_value(ctx, "watermark_layers", [])),
                None,
                read_value(ctx, "watermark_position", "右下"),
                "适应",  # resize_mode
                read_value(ctx, "keep_aspect_ratio", True),
                transition_frames,  # 使用动态计算的转场帧数
                transition_type,    # 使用动态计算的转场类型
                0.5,  # watermark_opacity
                20,  # watermark_size
                video_effect_type_for_video
            )
            
            if success:
                successful_videos += 1
                per_video_elapsed = max(0.0, time.time() - per_video_start_ts)
                notify(ctx, f"成功生成第{video_index + 1}个视频: {output_filename}，耗时 {per_video_elapsed:.1f} 秒")
            else:
                per_video_elapsed = max(0.0, time.time() - per_video_start_ts)
                notify(ctx, f"生成第{video_index + 1}个视频失败，耗时 {per_video_elapsed:.1f} 秒")
            _cleanup(ctx, )
        
        # 显示最终结果
        if read_value(ctx, "overall_progress_var") is not None:
            set_value(ctx, "overall_progress_var", 100)
        if read_value(ctx, "overall_progress_info_var") is not None:
            set_value(ctx, "overall_progress_info_var", "总进度: 100%")
        if successful_videos > 0:
            overall_elapsed = max(0.0, time.time() - overall_start_ts)
            notify(ctx, f"处理完成！成功生成{successful_videos}个视频（共{video_count}个），总耗时 {overall_elapsed:.1f} 秒")
            if not read_value(ctx, "batch_mode", False) and not read_value(ctx, "_completion_notified", False):
                set_value(ctx, "_completion_notified", True)
                if read_value(ctx, "detail_info_var") is not None:
                    set_value(ctx, "detail_info_var", f"状态: 处理完成（共{successful_videos}个，耗时 {overall_elapsed:.1f} 秒）")
            if read_value(ctx, "batch_mode", False) and read_value(ctx, "parent_update_status") is not None:
                _pus = read_value(ctx, "parent_update_status")
                if _pus is not None:
                    _pus(f"标签页处理完成：成功生成{successful_videos}个视频", True)
                set_value(ctx, "batch_mode", False)
            
            return True
        else:
            notify(ctx, "所有视频生成都失败！")
            return False
            
    except Exception as e:
        import traceback
        error_msg = f"处理视频时出错: {str(e)}\n{traceback.format_exc()}"
        notify(ctx, error_msg)
        print(error_msg)
        return False
    finally:
        set_value(ctx, "is_processing", False)
        if read_value(ctx, "start_button") is not None:
            pass
