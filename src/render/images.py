"""图片装载与基础处理（与界面无关的渲染内核）。

从 ``src/gui/main_window.py`` 的 ``ImageToVideoTab`` 抽出，函数体逐字保留。
原先直接写入 Tk 状态变量的部分改为可注入的 ``notify`` 回调，
``turbo_accelerator`` 改为可注入参数。本模块不导入任何 GUI 库。
"""

from __future__ import annotations

import os
import re
import sys

import numpy as np

from ..utils.opencv_silent import import_cv2_silent

cv2 = import_cv2_silent()


def _noop(_message) -> None:
    """默认进度回调：内核被独立使用时静默。"""


def normalize_path(path, notify=None):
    """标准化路径，处理中文和特殊字符"""
    notify = notify or _noop
    if path is None:
        return None
        
    # 确保路径使用正确的路径分隔符
    normalized = os.path.normpath(path)
    
    # 进行简单调试
    notify(f"路径标准化: {path} -> {normalized}")
    
    # 如果是Windows系统，处理中文路径
    if sys.platform == 'win32':
        try:
            # 检查路径是否存在
            if not os.path.exists(normalized):
                notify(f"警告: 路径不存在 - {normalized}")
                return normalized
            
            # 尝试获取短路径名（8.3格式）
            try:
                import win32api
                short_path = win32api.GetShortPathName(normalized)
                notify(f"转换为短路径: {normalized} -> {short_path}")
                return short_path
            except Exception as e:
                notify(f"获取短路径时出错: {str(e)}")
        except Exception as e:
            notify(f"路径存在检测出错: {str(e)}")
    
    return normalized


def get_images_list(input_dir, limit_count=None, selection_mode="随机选择",
                     notify=None, turbo_accelerator=None):
    """获取输入目录中的所有图片文件
    
    Args:
        input_dir: 输入目录路径
        limit_count: 限制图片数量，为None时不限制
        selection_mode: 图片选择方式，"随机选择"或"按名称排序"
    
    Returns:
        list: 图片文件路径列表
    """
    notify = notify or _noop
    # 标准化路径
    input_dir = normalize_path(input_dir, notify)
    
    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp']
    images = []
    
    # 尝试使用Path对象
    try:
        for ext in image_extensions:
            # 同时搜索小写和大写扩展名，避免重复
            lower_files = list(Path(input_dir).glob(f'*{ext}'))
            upper_files = list(Path(input_dir).glob(f'*{ext.upper()}'))
            
            # 去重：只添加不在小写列表中的大写文件
            images.extend(lower_files)
            for upper_file in upper_files:
                if upper_file not in lower_files:
                    images.append(upper_file)
        
        if images:
            image_paths = [str(img) for img in images]
            
            # 根据选择模式处理图片列表
            if selection_mode == "按名称排序":
                # 使用自然排序（数字排序）
                image_paths = sort_images_naturally(image_paths, notify)
                if limit_count and len(image_paths) > limit_count:
                    image_paths = image_paths[:limit_count]
            elif selection_mode == "随机选择" and limit_count and len(image_paths) > limit_count:
                # 随机选择指定数量
                import random
                image_paths = random.sample(image_paths, limit_count)
            
            return image_paths
    except Exception as e:
        notify(f"使用Path获取图片列表时出错: {str(e)}，尝试使用os.walk")
    
    # 备用方法：使用os.walk
    try:
        for root, _, files in os.walk(input_dir):
            for file in files:
                file_path = os.path.join(root, file)
                file_ext = os.path.splitext(file)[1].lower()
                if file_ext in image_extensions:
                    images.append(file_path)
        
        # 根据选择模式处理图片列表
        if selection_mode == "按名称排序":
            # 使用自然排序（数字排序）
            images = sort_images_naturally(images, notify)
            if limit_count and len(images) > limit_count:
                images = images[:limit_count]
        elif selection_mode == "随机选择" and limit_count and len(images) > limit_count:
            # 随机选择指定数量
            import random
            images = random.sample(images, limit_count)
        
        return images
    except Exception as e:
        notify(f"获取图片列表时出错: {str(e)}")
        return []

def natural_sort_key(filename):
    """生成自然排序的键值"""
    import re
    # 提取文件名（去除路径和扩展名）
    basename = os.path.splitext(os.path.basename(filename))[0]
    
    # 将数字和文字分开，数字部分转换为整数
    parts = re.split(r'(\d+)', basename)
    result = []
    
    for part in parts:
        if part.isdigit():
            result.append(int(part))  # 数字部分转整数
        else:
            result.append(part.lower())  # 文字部分转小写
    
    return result

def sort_images_naturally(image_paths, notify=None):
    """使用自然排序对图片进行排序
    
    Args:
        image_paths: 图片路径列表
        
    Returns:
        list: 排序后的图片路径列表
    """
    notify = notify or _noop
    try:
        # 使用自然排序键进行排序
        sorted_paths = sorted(image_paths, key=natural_sort_key)
        
        # 输出排序信息用于调试
        if len(sorted_paths) > 0:
            first_few = [os.path.basename(path) for path in sorted_paths[:5]]
            last_few = [os.path.basename(path) for path in sorted_paths[-5:]] if len(sorted_paths) > 5 else []
            
            if last_few and len(sorted_paths) > 5:
                notify(f"按名称排序完成: 前5个 {first_few}...后5个 {last_few}")
            else:
                notify(f"按名称排序完成: {first_few}")
        
        return sorted_paths
        
    except Exception as e:
        notify(f"自然排序出错: {str(e)}，使用默认排序")
        # 出错时降级为默认排序
        return sorted(image_paths)

def safe_read_image(img_path, notify=None, turbo_accelerator=None):
    """安全读取图片，处理中文路径问题（支持 Turbo 加速）"""
    notify = notify or _noop
    # 尝试使用 Turbo 加速器
    if turbo_accelerator and turbo_accelerator.enabled:
        try:
            return turbo_accelerator.optimized_image_read(img_path)
        except Exception as e:
            notify(f"Turbo 读取失败，使用标准方法: {str(e)}")
    
    # 标准读取方法
    try:
        # 首先尝试使用numpy从文件加载，这种方法可以更好地处理中文路径
        try:
            # 确保路径编码正确
            encoded_path = img_path
            if isinstance(img_path, str):
                if os.path.exists(img_path):
                    # 使用numpy读取，避开OpenCV的路径编码问题
                    img_array = np.fromfile(img_path, dtype=np.uint8)
                    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if img is not None:
                        return img
                else:
                    # 尝试不同的编码方式
                    for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
                        try:
                            # 尝试转换路径编码
                            decoded_path = img_path.encode('latin1').decode(encoding)
                            if os.path.exists(decoded_path):
                                img_array = np.fromfile(decoded_path, dtype=np.uint8)
                                img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                                if img is not None:
                                    return img
                        except Exception:
                            pass
        except Exception as e:
            notify(f"使用numpy方法读取图片出错: {str(e)}，尝试直接读取")
        
        # 如果numpy方法失败，尝试直接读取
        img = cv2.imread(img_path)
        if img is not None:
            return img
        
        notify(f"警告：无法读取图片 {img_path}")
        return None
    except Exception as e:
        notify(f"读取图片出错: {str(e)}")
        return None

def resize_with_aspect_ratio(img, target_width, target_height):
    """等比缩放图片，保持原始比例，不足的部分添加黑边"""
    if img is None:
        return None
        
    # 获取原始图片尺寸
    h, w = img.shape[:2]
    
    # 计算宽高比
    img_ratio = w / h
    target_ratio = target_width / target_height
    
    # 创建一个黑色背景图像（目标尺寸）
    result = np.zeros((target_height, target_width, 3), dtype=np.uint8)
    
    # 计算缩放后的尺寸和位置
    if img_ratio > target_ratio:
        # 图片比目标更宽，以宽度为准缩放
        new_w = target_width
        new_h = int(target_width / img_ratio)
        # 计算垂直居中的起始位置
        y_offset = (target_height - new_h) // 2
        x_offset = 0
    else:
        # 图片比目标更高，以高度为准缩放
        new_h = target_height
        new_w = int(target_height * img_ratio)
        # 计算水平居中的起始位置
        x_offset = (target_width - new_w) // 2
        y_offset = 0
    
    # 对原图进行缩放
    resized_img = cv2.resize(img, (new_w, new_h))
    
    # 将缩放后的图片放入黑色背景中
    result[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized_img
    
    return result


def resize_image(img, target_w, target_h, mode="适应", keep_aspect=True):
    """通用图片缩放方法，支持适应、拉伸、填充"""
    if img is None:
        return None
    h, w = img.shape[:2]
    if mode == "适应":
        return resize_with_aspect_ratio(img, target_w, target_h)
    elif mode == "拉伸":
        return cv2.resize(img, (target_w, target_h))
    elif mode == "填充":
        # 等比缩放后裁剪
        scale = max(target_w / w, target_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(img, (new_w, new_h))
        x0 = (new_w - target_w) // 2
        y0 = (new_h - target_h) // 2
        return resized[y0:y0+target_h, x0:x0+target_w]
    else:
        # 默认等比适应
        return resize_with_aspect_ratio(img, target_w, target_h)

# --- 底层工具：实现已抽到渲染内核 src.render.process ---
