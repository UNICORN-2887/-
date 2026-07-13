"""
DeadMaze - 截图采集工具
通过 OBS Studio 虚拟摄像头实时获取游戏画面
按 C 键截图（自动编号存储到 pic/ 文件夹）
按 Q 键退出
"""

import os
import sys
import argparse

import cv2


def get_next_index(save_dir: str) -> int:
    """获取下一个截图编号（从已有文件中找最大编号+1）"""
    if not os.path.exists(save_dir):
        return 1

    max_idx = 0
    for f in os.listdir(save_dir):
        if f.endswith(".jpg") and f[:-4].isdigit():
            max_idx = max(max_idx, int(f[:-4]))
    return max_idx + 1


def main():
    parser = argparse.ArgumentParser(description="DeadMaze 截图采集工具")
    parser.add_argument(
        "-c", "--camera", type=int, default=1,
        help="摄像头索引（默认 1 = OBS 虚拟摄像头，0 = 物理摄像头）"
    )
    parser.add_argument(
        "-o", "--output", type=str, default="pic",
        help="截图保存目录（默认 pic/）"
    )
    parser.add_argument(
        "-W", "--width", type=int, default=1920,
        help="摄像头分辨率宽度（默认 1920）"
    )
    parser.add_argument(
        "-H", "--height", type=int, default=1080,
        help="摄像头分辨率高度（默认 1080）"
    )
    args = parser.parse_args()

    # 确保保存目录存在
    save_dir = args.output
    os.makedirs(save_dir, exist_ok=True)

    # 打开 OBS 虚拟摄像头
    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    if not cap.isOpened():
        print(f"[错误] 无法打开摄像头 (索引 {args.camera})")
        print("请确认 OBS 虚拟摄像头已启动，或尝试其他索引: -c 0")
        sys.exit(1)

    # 获取实际分辨率
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[信息] OBS 虚拟摄像头已连接，分辨率: {actual_w}x{actual_h}")
    print(f"[信息] 截图保存目录: {os.path.abspath(save_dir)}/")
    print("[操作] 按 C 键截图 | 按 Q 键退出")

    # 获取起始编号
    next_idx = get_next_index(save_dir)
    screenshot_count = 0

    # 提示文字参数
    FONT = cv2.FONT_HERSHEY_SIMPLEX

    cv2.namedWindow("DeadMaze - 截图采集", cv2.WINDOW_NORMAL)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[警告] 读取画面失败，重试中...")
            continue

        # 叠加提示信息
        display = frame.copy()
        hint = (
            f"[C] 截图 (已存: {screenshot_count}) "
            f"| [Q] 退出 | 下一张: {next_idx:04d}.jpg"
        )
        cv2.putText(display, hint, (10, 30),
                    FONT, 0.8, (0, 255, 0), 2)

        # 显示画面
        cv2.imshow("DeadMaze - 截图采集", display)

        # 等待按键
        key = cv2.waitKey(1) & 0xFF

        if key == ord('c') or key == ord('C'):
            # 截图
            filename = f"{next_idx:04d}.jpg"
            filepath = os.path.join(save_dir, filename)
            cv2.imwrite(filepath, frame)
            print(f"[截图] 已保存: {filepath}")
            next_idx += 1
            screenshot_count += 1

        elif key == ord('q') or key == ord('Q'):
            # 退出
            print(f"[退出] 本次共截图 {screenshot_count} 张，再见！")
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
