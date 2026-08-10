#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试MOV水印文件夹模式功能

测试场景：
1. 创建多个测试图片和MOV水印
2. 使用文件夹模式生成多个视频
3. 验证每个视频使用了不同的水印
"""

import os
import sys
import cv2
import numpy as np
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def create_test_images(output_dir, count=6):
    """创建测试图片"""
    os.makedirs(output_dir, exist_ok=True)
    
    colors = [
        (255, 100, 100),  # 红色系
        (100, 255, 100),  # 绿色系
        (100, 100, 255),  # 蓝色系
        (255, 255, 100),  # 黄色系
        (255, 100, 255),  # 紫色系
        (100, 255, 255),  # 青色系
    ]
    
    for i in range(count):
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        color = colors[i % len(colors)]
        img[:] = color
        
        # 添加文字标识
        text = f"Image {i+1}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        text_size = cv2.getTextSize(text, font, 3, 5)[0]
        text_x = (img.shape[1] - text_size[0]) // 2
        text_y = (img.shape[0] + text_size[1]) // 2
        cv2.putText(img, text, (text_x, text_y), font, 3, (255, 255, 255), 5)
        
        output_path = os.path.join(output_dir, f"image_{i+1:02d}.jpg")
        cv2.imwrite(output_path, img)
        print(f"创建测试图片: {output_path}")

def create_test_mov_watermarks(output_dir, count=3):
    """创建测试MOV水印视频"""
    os.makedirs(output_dir, exist_ok=True)
    
    watermark_styles = [
        {"color": (255, 0, 0), "label": "RED"},
        {"color": (0, 255, 0), "label": "GREEN"},
        {"color": (0, 0, 255), "label": "BLUE"},
    ]
    
    for i in range(count):
        style = watermark_styles[i % len(watermark_styles)]
        output_path = os.path.join(output_dir, f"watermark_{i+1:02d}.mp4")
        
        # 创建一个简单的MOV水印视频 (5帧, 30fps)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, 30.0, (320, 180))
        
        for frame_idx in range(5):
            # 创建带透明背景的效果（实际上MP4不支持alpha通道，这里用黑色背景）
            frame = np.zeros((180, 320, 3), dtype=np.uint8)
            
            # 绘制彩色圆圈
            center = (160, 90)
            radius = 40 + int(10 * np.sin(frame_idx * np.pi / 5))
            cv2.circle(frame, center, radius, style["color"], -1)
            
            # 添加标签
            font = cv2.FONT_HERSHEY_SIMPLEX
            cv2.putText(frame, style["label"], (120, 95), font, 0.8, (255, 255, 255), 2)
            
            out.write(frame)
        
        out.release()
        print(f"创建测试MOV水印: {output_path}")

def main():
    """主测试函数"""
    print("=" * 60)
    print("测试MOV水印文件夹模式")
    print("=" * 60)
    
    # 创建测试目录
    test_dir = Path("test_watermark_folder")
    test_dir.mkdir(exist_ok=True)
    
    images_dir = test_dir / "images"
    watermarks_dir = test_dir / "watermarks"
    output_dir = test_dir / "output"
    
    # 清理旧文件
    for d in [images_dir, watermarks_dir, output_dir]:
        if d.exists():
            for f in d.glob("*"):
                f.unlink()
    
    # 创建测试数据
    print("\n步骤 1: 创建测试图片和水印")
    print("-" * 60)
    create_test_images(str(images_dir), count=6)
    create_test_mov_watermarks(str(watermarks_dir), count=3)
    
    print("\n步骤 2: 验证文件创建")
    print("-" * 60)
    images = sorted(images_dir.glob("*.jpg"))
    watermarks = sorted(watermarks_dir.glob("*.mp4"))
    
    print(f"创建了 {len(images)} 张测试图片:")
    for img in images:
        print(f"  - {img.name}")
    
    print(f"\n创建了 {len(watermarks)} 个测试水印:")
    for wm in watermarks:
        print(f"  - {wm.name}")
    
    print("\n步骤 3: 使用说明")
    print("-" * 60)
    print("测试准备完成！请按以下步骤进行测试：")
    print("")
    print("1. 运行主程序: python main.py")
    print("")
    print("2. 在主界面配置以下参数：")
    print(f"   - 输入目录: {images_dir.absolute()}")
    print(f"   - 输出目录: {output_dir.absolute()}")
    print("   - 每个视频图片数: 2")
    print("   - 视频数量: 3")
    print("   - 图片持续时间: 2秒")
    print("")
    print("3. 配置水印参数：")
    print("   - 启用水印: 勾选")
    print("   - 水印类型: 视频")
    print("   - 水印模式: 文件夹")
    print(f"   - 水印路径: {watermarks_dir.absolute()}")
    print("   - 水印位置: 右下")
    print("   - 混合模式: 滤色 (如果水印有黑色背景)")
    print("")
    print("4. 点击开始处理")
    print("")
    print("5. 验证结果：")
    print("   - 应该生成3个视频")
    print("   - 第1个视频使用 watermark_01.mp4 (红色)")
    print("   - 第2个视频使用 watermark_02.mp4 (绿色)")
    print("   - 第3个视频使用 watermark_03.mp4 (蓝色)")
    print("")
    print("6. 测试单文件模式：")
    print("   - 将水印模式改为 '单文件'")
    print(f"   - 选择单个水印文件，如: {watermarks_dir / 'watermark_01.mp4'}")
    print("   - 生成视频，验证所有视频都使用同一个水印")
    print("")
    print("=" * 60)
    print("测试文件已准备好！")
    print("=" * 60)

if __name__ == "__main__":
    main()

