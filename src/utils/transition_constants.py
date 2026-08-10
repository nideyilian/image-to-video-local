#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
转场效果常量统一定义
统一管理所有转场效果的命名和映射
"""

from enum import Enum
from typing import List, Dict

class TransitionEffect(Enum):
    """转场效果类型枚举（统一定义）"""
    FADE = "淡入淡出"
    SLIDE_LEFT = "左右滑动"
    SLIDE_UP = "上下滑动"
    CROSSFADE = "交叉溶解"
    ZOOM = "缩放过渡"
    CIRCLE_EXPAND = "圆形扩展"
    PIXELATE = "像素化"
    ROTATE = "旋转变换"
    BLINDS = "百叶窗"
    CHECKERBOARD = "棋盘格"
    WAVE = "波浪"
    COLOR_MIX = "颜色混合"
    BLOCK = "方块过渡"
    WIPE_LEFT = "左侧擦除"
    WIPE_RIGHT = "右侧擦除"
    # 新增有冲击力的转场效果
    ZOOM_IN_IMPACT = "放大冲击"
    ZOOM_OUT_EXPLODE = "缩小爆炸"
    ROTATE_ZOOM = "旋转放大"
    ELASTIC_ZOOM = "弹性缩放"
    FLIP_3D = "3D翻转"
    PUSH_IN = "推入效果"
    DIAGONAL_WIPE = "对角擦除"
    DOOR_OPEN = "门式打开"
    FLASH_TRANSITION = "闪光过渡"
    SHATTER = "碎片飞散"
    # 新增：高级转场效果（10个）
    GLOW_SPREAD = "光晕扩散"
    RADIAL_SWEEP = "径向旋切"
    VORTEX_DISTORT = "漩涡扭曲"
    DIAMOND_REVEAL = "菱形开幕"
    FOCUS_BLUR = "镜头虚焦"
    CURTAIN_VERTICAL = "纵向拉幕"
    CURTAIN_HORIZONTAL = "横向拉幕"
    LIQUID_BLEND = "液态融合"
    LIGHT_STREAK = "流光擦拭"
    CLOCK_WIPE = "时钟扫描"


# 所有可用的转场效果列表（按中文名称）
ALL_TRANSITIONS = [effect.value for effect in TransitionEffect]

# GUI中显示的转场效果（可以是全部或精选）
GUI_TRANSITIONS = [
    "淡入淡出",
    "左右滑动", 
    "上下滑动",
    "交叉溶解",
    "缩放过渡",
    "圆形扩展",
    "百叶窗",
    "棋盘格",
    "像素化",
    "旋转变换",
    "波浪",
    "颜色混合",
    "方块过渡",
    # 新增冲击力转场
    "放大冲击",
    "缩小爆炸",
    "旋转放大",
    "弹性缩放",
    "3D翻转",
    "推入效果",
    "对角擦除",
    "门式打开",
    "闪光过渡",
    "碎片飞散",
    # 新增高级转场
    "光晕扩散",
    "径向旋切",
    "漩涡扭曲",
    "菱形开幕",
    "镜头虚焦",
    "纵向拉幕",
    "横向拉幕",
    "液态融合",
    "流光擦拭",
    "时钟扫描",
]

# 默认启用的转场效果（用于随机选择）
DEFAULT_ENABLED_TRANSITIONS = [
    "淡入淡出",
    "左右滑动",
    "交叉溶解",
    "缩放过渡",
    "圆形扩展",
    "百叶窗",
]

# 转场效果的描述
TRANSITION_DESCRIPTIONS = {
    "淡入淡出": "图片渐变过渡，最平滑自然",
    "左右滑动": "图片从右向左滑入",
    "上下滑动": "图片从上向下滑入",
    "交叉溶解": "随机像素交叉溶解",
    "缩放过渡": "图片缩放切换",
    "圆形扩展": "从中心圆形扩展显示",
    "百叶窗": "百叶窗式展开",
    "棋盘格": "棋盘格式过渡",
    "像素化": "像素化后清晰化",
    "旋转变换": "旋转切换效果",
    "波浪": "波浪形过渡",
    "颜色混合": "颜色空间混合",
    "方块过渡": "方块扩散效果",
    # 新增冲击力转场描述
    "放大冲击": "快速从中心放大，强烈冲击感",
    "缩小爆炸": "缩小并爆炸成碎片",
    "旋转放大": "旋转同时放大，动感十足",
    "弹性缩放": "有回弹效果的缩放，富有弹性",
    "3D翻转": "立体翻转效果，空间感强",
    "推入效果": "新图推开旧图",
    "对角擦除": "对角线快速扫过",
    "门式打开": "像开门一样从中间展开",
    "闪光过渡": "强光闪烁过渡，炫目",
    "碎片飞散": "图片碎裂飞散，震撼",
    # 新增高级转场描述
    "光晕扩散": "中心光晕逐步扩散切换",
    "径向旋切": "扇形旋转切入下一帧",
    "漩涡扭曲": "漩涡扭曲后平滑过渡",
    "菱形开幕": "菱形区域由小到大展开",
    "镜头虚焦": "先虚焦再清晰聚焦到下一帧",
    "纵向拉幕": "左右幕布向外拉开",
    "横向拉幕": "上下幕布向外拉开",
    "液态融合": "液态粘连感混合切换",
    "流光擦拭": "高亮光带扫过揭示下一帧",
    "时钟扫描": "按时钟方向扇区逐步替换",
}

def get_transition_name(value: str) -> str:
    """获取转场效果的标准名称"""
    # 直接返回，因为现在都使用中文名称作为标准
    return value

def is_valid_transition(name: str) -> bool:
    """检查是否是有效的转场效果名称"""
    return name in ALL_TRANSITIONS

