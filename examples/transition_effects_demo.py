#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
转场效果演示脚本
展示所有可用的转场效果，包括新增的冲击力转场
"""

import sys
import os
import cv2
import numpy as np

# 添加src目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(current_dir)
src_dir = os.path.join(project_dir, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from core.transition_engine import TurboTransitionEngine
from utils.transition_constants import GUI_TRANSITIONS, TRANSITION_DESCRIPTIONS

def create_demo_image(color, size=(720, 1280, 3), text="", subtitle=""):
    """创建演示图片"""
    img = np.zeros(size, dtype=np.uint8)
    
    # 渐变背景
    for i in range(size[0]):
        ratio = i / size[0]
        img[i, :] = [
            int(color[0] * (1 - ratio * 0.3)),
            int(color[1] * (1 - ratio * 0.3)),
            int(color[2] * (1 - ratio * 0.3))
        ]
    
    # 添加主标题
    if text:
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 2.5
        thickness = 4
        
        (text_width, text_height), _ = cv2.getTextSize(text, font, font_scale, thickness)
        x = (size[1] - text_width) // 2
        y = (size[0] - text_height) // 2 - 50
        
        # 文字阴影
        cv2.putText(img, text, (x+3, y+3), font, font_scale, (0, 0, 0), thickness)
        # 文字本体
        cv2.putText(img, text, (x, y), font, font_scale, (255, 255, 255), thickness)
    
    # 添加副标题
    if subtitle:
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.2
        thickness = 2
        
        (text_width, text_height), _ = cv2.getTextSize(subtitle, font, font_scale, thickness)
        x = (size[1] - text_width) // 2
        y = (size[0] + text_height) // 2 + 50
        
        cv2.putText(img, subtitle, (x+2, y+2), font, font_scale, (0, 0, 0), thickness)
        cv2.putText(img, subtitle, (x, y), font, font_scale, (200, 200, 200), thickness)
    
    return img

def demo_single_transition(engine, transition_name, img1, img2, num_frames=30, save_video=False):
    """演示单个转场效果"""
    print(f"\n正在演示: {transition_name}")
    
    try:
        # 生成转场帧
        frames = engine.generate_transition_frames(img1, img2, transition_name, num_frames)
        
        if not frames:
            print(f"  [FAIL] 未能生成转场帧")
            return False
        
        print(f"  [OK] 生成 {len(frames)} 帧")
        
        # 显示转场效果
        for i, frame in enumerate(frames):
            # 添加转场名称标签
            label_img = frame.copy()
            cv2.putText(label_img, transition_name, (20, 50), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
            cv2.putText(label_img, f"Frame: {i+1}/{len(frames)}", (20, 100), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
            
            cv2.imshow('Transition Demo', label_img)
            
            # 按ESC退出，按空格暂停，按其他键继续
            key = cv2.waitKey(33)  # 30fps
            if key == 27:  # ESC
                return False
            elif key == 32:  # Space
                cv2.waitKey(0)
        
        # 显示结束画面
        cv2.imshow('Transition Demo', img2)
        cv2.waitKey(500)
        
        return True
        
    except Exception as e:
        print(f"  [FAIL] 错误: {str(e)}")
        return False

def main():
    """主函数"""
    print("=" * 70)
    print("图片转视频工具 - 转场效果演示")
    print("=" * 70)
    
    # 创建演示图片
    print("\n正在创建演示图片...")
    img1 = create_demo_image((50, 50, 200), text="Image 1", subtitle="Press SPACE to pause, ESC to skip")
    img2 = create_demo_image((200, 50, 50), text="Image 2", subtitle="Transition Effects Demo")
    img3 = create_demo_image((50, 200, 50), text="Image 3", subtitle="Enjoy the show!")
    
    print("[OK] 演示图片创建完成")
    
    # 初始化转场引擎
    print("\n正在初始化转场引擎...")
    engine = TurboTransitionEngine()
    print("[OK] 转场引擎初始化完成")
    
    # 获取所有转场效果
    all_transitions = GUI_TRANSITIONS
    
    print(f"\n总共有 {len(all_transitions)} 种转场效果")
    print("\n转场效果列表：")
    
    # 区分原有和新增的转场
    new_transitions = [
        "放大冲击", "缩小爆炸", "旋转放大", "弹性缩放", "3D翻转",
        "推入效果", "对角擦除", "门式打开", "闪光过渡", "碎片飞散"
    ]
    
    for i, name in enumerate(all_transitions, 1):
        marker = "[NEW]" if name in new_transitions else "     "
        desc = TRANSITION_DESCRIPTIONS.get(name, "")
        print(f"  {i:2d}. {marker} {name:12s} - {desc}")
    
    print("\n" + "=" * 70)
    print("演示控制：")
    print("  - 空格键：暂停/继续")
    print("  - ESC键：跳过当前转场")
    print("  - 关闭窗口：退出演示")
    print("=" * 70)
    
    input("\n按回车键开始演示...")
    
    # 演示所有转场效果
    success_count = 0
    
    for i, transition_name in enumerate(all_transitions, 1):
        print(f"\n[{i}/{len(all_transitions)}] ", end="")
        
        # 在三张图片之间轮换
        if i % 3 == 1:
            img_from, img_to = img1, img2
        elif i % 3 == 2:
            img_from, img_to = img2, img3
        else:
            img_from, img_to = img3, img1
        
        # 演示转场
        success = demo_single_transition(engine, transition_name, img_from, img_to, num_frames=25)
        
        if success:
            success_count += 1
        else:
            print("  [INFO] 用户跳过或发生错误")
            break
    
    # 清理
    cv2.destroyAllWindows()
    
    # 显示统计信息
    print("\n" + "=" * 70)
    print("演示统计")
    print("=" * 70)
    print(f"演示完成: {success_count}/{len(all_transitions)}")
    
    stats = engine.get_performance_stats()
    print(f"\n性能统计：")
    print(f"  生成转场数量: {stats['transitions_generated']}")
    print(f"  总处理时间: {stats['total_time']:.2f}秒")
    print(f"  平均生成时间: {stats['average_time']:.3f}秒/转场")
    print(f"  缓存命中率: {stats['cache_hit_rate']}")
    
    print("\n" + "=" * 70)
    print("演示结束，感谢观看！")
    print("=" * 70)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[INFO] 用户中断演示")
        cv2.destroyAllWindows()
    except Exception as e:
        print(f"\n[ERROR] 演示过程中发生错误: {str(e)}")
        cv2.destroyAllWindows()
        raise

