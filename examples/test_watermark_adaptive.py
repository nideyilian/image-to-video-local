#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
测试视频水印自适应大小功能
"""

import sys
import os
import cv2
import numpy as np

# 添加src目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(current_dir)
sys.path.insert(0, project_dir)

def create_test_video(output_path, width, height, duration=3, fps=30, color=(100, 150, 200), text="Main Video"):
    """创建测试视频"""
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    total_frames = int(duration * fps)
    
    for i in range(total_frames):
        # 创建渐变背景
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        for y in range(height):
            ratio = y / height
            frame[y, :] = [
                int(color[0] * (1 - ratio * 0.5)),
                int(color[1] * (1 - ratio * 0.5)),
                int(color[2] * (1 - ratio * 0.5))
            ]
        
        # 添加文本
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 2
        thickness = 3
        
        (text_width, text_height), _ = cv2.getTextSize(text, font, font_scale, thickness)
        x = (width - text_width) // 2
        y = (height + text_height) // 2
        
        cv2.putText(frame, text, (x, y), font, font_scale, (255, 255, 255), thickness)
        
        # 添加帧数
        frame_text = f"Frame: {i+1}/{total_frames}"
        cv2.putText(frame, frame_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        
        out.write(frame)
    
    out.release()
    print(f"[OK] 创建测试视频: {output_path} ({width}x{height})")

def test_watermark_modes():
    """测试不同的水印模式"""
    print("=" * 70)
    print("视频水印自适应大小功能测试")
    print("=" * 70)
    
    # 创建测试目录
    test_dir = os.path.join(project_dir, "test_watermark_output")
    os.makedirs(test_dir, exist_ok=True)
    
    # 测试场景
    test_cases = [
        {
            "name": "横向视频 + 横向水印",
            "main": {"width": 1920, "height": 1080, "color": (100, 150, 200), "text": "Main 16:9"},
            "watermark": {"width": 1280, "height": 720, "color": (200, 100, 100), "text": "WM 16:9"}
        },
        {
            "name": "横向视频 + 竖向水印",
            "main": {"width": 1920, "height": 1080, "color": (100, 150, 200), "text": "Main 16:9"},
            "watermark": {"width": 720, "height": 1280, "color": (200, 100, 100), "text": "WM 9:16"}
        },
        {
            "name": "竖向视频 + 横向水印",
            "main": {"width": 720, "height": 1280, "color": (100, 200, 150), "text": "Main 9:16"},
            "watermark": {"width": 1280, "height": 720, "color": (200, 100, 100), "text": "WM 16:9"}
        },
        {
            "name": "方形视频 + 横向水印",
            "main": {"width": 1080, "height": 1080, "color": (150, 150, 200), "text": "Main 1:1"},
            "watermark": {"width": 1920, "height": 1080, "color": (200, 100, 100), "text": "WM 16:9"}
        }
    ]
    
    print(f"\n总共 {len(test_cases)} 个测试场景\n")
    
    for idx, case in enumerate(test_cases, 1):
        print(f"\n[{idx}/{len(test_cases)}] 测试场景: {case['name']}")
        print("-" * 70)
        
        # 创建主视频
        main_video_path = os.path.join(test_dir, f"test_main_{idx}.mp4")
        create_test_video(
            main_video_path,
            case['main']['width'],
            case['main']['height'],
            duration=2,
            color=case['main']['color'],
            text=case['main']['text']
        )
        
        # 创建水印视频
        watermark_video_path = os.path.join(test_dir, f"test_watermark_{idx}.mp4")
        create_test_video(
            watermark_video_path,
            case['watermark']['width'],
            case['watermark']['height'],
            duration=2,
            color=case['watermark']['color'],
            text=case['watermark']['text']
        )
        
        # 计算比例信息
        main_ratio = case['main']['width'] / case['main']['height']
        wm_ratio = case['watermark']['width'] / case['watermark']['height']
        
        print(f"  主视频: {case['main']['width']}x{case['main']['height']} (比例: {main_ratio:.2f})")
        print(f"  水印: {case['watermark']['width']}x{case['watermark']['height']} (比例: {wm_ratio:.2f})")
        
        # 模拟不同的大小模式
        modes = [
            ("固定比例", 20),
            ("自适应覆盖", None),
            ("完全覆盖", None)
        ]
        
        for mode_name, scale in modes:
            print(f"\n  测试模式: {mode_name}", end="")
            if scale:
                print(f" (缩放: {scale}%)")
            else:
                print()
            
            # 计算预期的水印大小
            if mode_name == "自适应覆盖":
                if wm_ratio > main_ratio:
                    # 水印更宽，按高度适配
                    expected_h = case['main']['height']
                    expected_w = int(expected_h * wm_ratio)
                else:
                    # 水印更高，按宽度适配
                    expected_w = case['main']['width']
                    expected_h = int(expected_w / wm_ratio)
                print(f"    预期水印大小: {expected_w}x{expected_h}")
                print(f"    保持原始比例: {wm_ratio:.2f}")
                if expected_w > case['main']['width'] or expected_h > case['main']['height']:
                    print(f"    [注意] 水印会超出主视频边界，将自动裁剪")
            
            elif mode_name == "完全覆盖":
                expected_w = case['main']['width']
                expected_h = case['main']['height']
                print(f"    预期水印大小: {expected_w}x{expected_h}")
                print(f"    [注意] 不保持原始比例，会拉伸")
            
            else:  # 固定比例
                watermark_size = int(case['main']['width'] * (scale / 100.0))
                expected_w = watermark_size
                expected_h = int(watermark_size / wm_ratio)
                print(f"    预期水印大小: {expected_w}x{expected_h}")
                print(f"    保持原始比例: {wm_ratio:.2f}")
    
    print("\n" + "=" * 70)
    print("测试场景创建完成！")
    print("=" * 70)
    print(f"\n测试文件保存在: {test_dir}")
    print("\n使用说明：")
    print("1. 启动主程序: python main.py")
    print("2. 选择测试视频作为主视频")
    print("3. 选择对应的水印视频")
    print("4. 在'大小模式'中选择不同模式测试")
    print("5. 观察水印的自适应效果")
    
    print("\n推荐测试组合：")
    print("  - 固定比例模式: 适合小水印logo")
    print("  - 自适应覆盖: 适合全屏水印，保持比例")
    print("  - 完全覆盖: 适合需要完全覆盖的场景（会拉伸）")

if __name__ == "__main__":
    try:
        test_watermark_modes()
    except Exception as e:
        print(f"\n[ERROR] 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()

