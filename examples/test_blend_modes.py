#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
测试水印混合模式功能
演示不同混合模式的效果，特别是滤色模式对黑色背景mov的处理
"""

import sys
import os
import cv2
import numpy as np

# 添加src目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(current_dir)
sys.path.insert(0, project_dir)

def create_test_background(width=1920, height=1080):
    """创建测试背景图像"""
    # 创建彩色渐变背景
    img = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        ratio = y / height
        img[y, :] = [
            int(100 * (1 - ratio * 0.5)),
            int(150 * (1 - ratio * 0.5)),
            int(200 * (1 - ratio * 0.5))
        ]
    
    # 添加文本
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, "Background Video", (width//2 - 200, height//2), 
               font, 2, (255, 255, 255), 3)
    
    return img

def create_test_watermark_black_bg(width=640, height=360):
    """创建黑色背景的测试水印（模拟mov文件）"""
    # 黑色背景
    img = np.zeros((height, width, 3), dtype=np.uint8)
    
    # 添加彩色图形
    center_x, center_y = width // 2, height // 2
    
    # 红色圆形
    cv2.circle(img, (center_x - 100, center_y), 50, (0, 0, 255), -1)
    
    # 绿色矩形
    cv2.rectangle(img, (center_x - 50, center_y - 50), 
                 (center_x + 50, center_y + 50), (0, 255, 0), -1)
    
    # 蓝色三角形
    pts = np.array([[center_x + 100, center_y - 50],
                    [center_x + 150, center_y + 50],
                    [center_x + 50, center_y + 50]], np.int32)
    cv2.fillPoly(img, [pts], (255, 0, 0))
    
    # 白色文字
    cv2.putText(img, "MOV Watermark", (width//2 - 120, height - 30), 
               cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    
    return img

def apply_blend_mode(background, foreground, mode="正常", alpha=0.5):
    """
    应用不同的混合模式
    """
    try:
        # 确保图像类型一致
        bg = background.astype(np.float32) / 255.0
        fg = foreground.astype(np.float32) / 255.0
        
        if mode == "正常":
            result = bg * (1 - alpha) + fg * alpha
            
        elif mode == "滤色":
            # 滤色模式 - 适合黑色背景
            result = 1 - (1 - bg) * (1 - fg)
            result = bg * (1 - alpha) + result * alpha
            
        elif mode == "叠加":
            mask = bg < 0.5
            result = np.where(mask, 2 * bg * fg, 1 - 2 * (1 - bg) * (1 - fg))
            result = bg * (1 - alpha) + result * alpha
            
        elif mode == "正片叠底":
            result = bg * fg
            result = bg * (1 - alpha) + result * alpha
            
        elif mode == "变亮":
            result = np.maximum(bg, fg)
            result = bg * (1 - alpha) + result * alpha
            
        elif mode == "变暗":
            result = np.minimum(bg, fg)
            result = bg * (1 - alpha) + result * alpha
            
        elif mode == "相加":
            result = bg + fg
            result = np.clip(result, 0, 1)
            result = bg * (1 - alpha) + result * alpha
            
        else:
            result = bg * (1 - alpha) + fg * alpha
        
        # 转换回uint8
        result = np.clip(result * 255, 0, 255).astype(np.uint8)
        return result
        
    except Exception as e:
        print(f"混合模式应用失败: {str(e)}")
        return background

def test_blend_modes():
    """测试所有混合模式"""
    print("=" * 70)
    print("水印混合模式测试")
    print("=" * 70)
    
    # 创建测试图像
    print("\n创建测试图像...")
    background = create_test_background(1920, 1080)
    watermark = create_test_watermark_black_bg(640, 360)
    
    print(f"背景大小: {background.shape}")
    print(f"水印大小: {watermark.shape}")
    
    # 混合模式列表
    blend_modes = [
        "正常",
        "滤色",      # 重点：黑色背景mov推荐
        "叠加",
        "正片叠底",
        "变亮",
        "变暗",
        "相加"
    ]
    
    print(f"\n总共 {len(blend_modes)} 种混合模式\n")
    
    # 水印位置（右下角）
    wm_h, wm_w = watermark.shape[:2]
    bg_h, bg_w = background.shape[:2]
    x_pos = bg_w - wm_w - 50
    y_pos = bg_h - wm_h - 50
    
    # 创建输出目录
    output_dir = os.path.join(project_dir, "test_blend_output")
    os.makedirs(output_dir, exist_ok=True)
    
    # 保存原始图像
    cv2.imwrite(os.path.join(output_dir, "00_background.png"), background)
    cv2.imwrite(os.path.join(output_dir, "00_watermark_black_bg.png"), watermark)
    print(f"[OK] 保存原始图像")
    
    # 测试每种混合模式
    for idx, mode in enumerate(blend_modes, 1):
        print(f"\n[{idx}/{len(blend_modes)}] 测试混合模式: {mode}")
        
        # 创建结果图像
        result = background.copy()
        
        # 提取ROI
        roi = result[y_pos:y_pos+wm_h, x_pos:x_pos+wm_w]
        
        # 应用混合模式
        blended = apply_blend_mode(roi, watermark, mode=mode, alpha=0.5)
        
        # 放回结果
        result[y_pos:y_pos+wm_h, x_pos:x_pos+wm_w] = blended
        
        # 添加模式名称标签
        cv2.putText(result, f"Blend Mode: {mode}", (50, 80), 
                   cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
        
        # 保存结果
        output_path = os.path.join(output_dir, f"{idx:02d}_{mode}.png")
        cv2.imwrite(output_path, result)
        print(f"  [OK] 保存: {output_path}")
        
        # 显示结果
        display_img = cv2.resize(result, (960, 540))
        cv2.imshow(f"Blend Mode Test - {mode}", display_img)
        
        # 按任意键继续，ESC退出
        key = cv2.waitKey(0)
        if key == 27:  # ESC
            break
        
        cv2.destroyAllWindows()
    
    cv2.destroyAllWindows()
    
    # 打印总结
    print("\n" + "=" * 70)
    print("测试完成！")
    print("=" * 70)
    print(f"\n结果保存在: {output_dir}")
    
    print("\n混合模式说明：")
    print("  1. 正常 - 标准Alpha混合，黑色背景会显示")
    print("  2. 滤色 [推荐] - 黑色变透明，适合黑色背景mov")
    print("  3. 叠加 - 根据背景亮度混合")
    print("  4. 正片叠底 - 变暗效果")
    print("  5. 变亮 - 保留较亮像素")
    print("  6. 变暗 - 保留较暗像素")
    print("  7. 相加 - 线性减淡，更亮")
    
    print("\n推荐使用：")
    print("  - 黑色背景mov -> 滤色模式")
    print("  - 普通水印 -> 正常模式")
    print("  - 艺术效果 -> 叠加/变亮模式")

def demo_screen_mode():
    """演示滤色模式的效果"""
    print("\n" + "=" * 70)
    print("滤色模式详细演示")
    print("=" * 70)
    
    # 创建背景
    bg = create_test_background(1920, 1080)
    wm = create_test_watermark_black_bg(640, 360)
    
    wm_h, wm_w = wm.shape[:2]
    bg_h, bg_w = bg.shape[:2]
    x_pos = bg_w - wm_w - 50
    y_pos = bg_h - wm_h - 50
    
    # 对比：正常模式 vs 滤色模式
    result_normal = bg.copy()
    result_screen = bg.copy()
    
    roi_normal = result_normal[y_pos:y_pos+wm_h, x_pos:x_pos+wm_w]
    roi_screen = result_screen[y_pos:y_pos+wm_h, x_pos:x_pos+wm_w]
    
    blended_normal = apply_blend_mode(roi_normal, wm, mode="正常", alpha=0.5)
    blended_screen = apply_blend_mode(roi_screen, wm, mode="滤色", alpha=0.5)
    
    result_normal[y_pos:y_pos+wm_h, x_pos:x_pos+wm_w] = blended_normal
    result_screen[y_pos:y_pos+wm_h, x_pos:x_pos+wm_w] = blended_screen
    
    # 添加标签
    cv2.putText(result_normal, "Normal Mode (Black BG Visible)", (50, 80), 
               cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
    cv2.putText(result_screen, "Screen Mode (Black BG Transparent)", (50, 80), 
               cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
    
    # 并排显示
    combined = np.hstack([
        cv2.resize(result_normal, (960, 540)),
        cv2.resize(result_screen, (960, 540))
    ])
    
    cv2.imshow("Comparison: Normal vs Screen Mode", combined)
    print("\n对比显示：")
    print("  左侧：正常模式 - 黑色背景可见")
    print("  右侧：滤色模式 - 黑色背景透明")
    print("\n按任意键关闭...")
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    try:
        # 运行完整测试
        test_blend_modes()
        
        # 运行滤色模式演示
        demo_screen_mode()
        
    except KeyboardInterrupt:
        print("\n\n[INFO] 用户中断测试")
        cv2.destroyAllWindows()
    except Exception as e:
        print(f"\n[ERROR] 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        cv2.destroyAllWindows()

