"""CLI 入口: game-automator serve | stitch | nav | calibrate.

安装后:
    pip install -e .
    game-automator serve       # 启动导航 API
    game-automator stitch ...  # 光流建图
    game-automator calibrate   # ROI 标定

直接运行:
    python -m game_automator.server serve
"""

import argparse
import sys
import os


def cmd_serve(args):
    """启动 REST 导航服务器."""
    from game_automator.mapping import Pathfinder
    from game_automator.navigation import NavigationServer
    from game_automator.capture import OBSVideoCapture

    pf = Pathfinder(args.reachable, shrink=8)
    map_img = args.map if hasattr(args, 'map') and args.map else None
    server = NavigationServer(pf, port=args.port, map_image=map_img)
    server._reachable_path = args.reachable
    try:
        from game_automator.capture import OBSVideoCapture
        server._cap = OBSVideoCapture(cam_id=args.camera)
        print(f"[OBS] capture ready (camera #{args.camera})")
    except Exception as e:
        print(f"[OBS] capture unavailable: {e}")
    print(f"地图: {args.reachable}")
    if map_img:
        import os
        print(f"前端地图: {map_img} ({os.path.getsize(map_img)} bytes)")
    else:
        print(f"前端地图: (无)")
    print(f"摄像头: OBS #{args.camera}")
    server.start()


def cmd_stitch(args):
    """光流法建图 — 严格匹配 DeadMaze map_stitcher.py 双窗口+裁剪框方案."""
    import cv2, json, os, time, ctypes
    from game_automator.capture import OBSVideoCapture
    from game_automator.stitching import MapStitcher, CropRegion

    # ── 摄像头选择 ──
    cams = OBSVideoCapture.list_cameras()
    if not cams:
        print("[错误] 未检测到摄像头")
        return
    print("\n可用摄像头:")
    for i, (idx, name) in enumerate(cams):
        marker = " [OBS]" if "obs" in name.lower() else ""
        print(f"  {idx}: {name}{marker}")
    obs_id = OBSVideoCapture.find_obs()
    default = obs_id if obs_id is not None else cams[0][0]
    print(f"\n默认选择: {default} (回车确认, 或输入编号): ", end="")
    choice = input().strip()
    cam_id = int(choice) if choice else default

    cap = OBSVideoCapture(cam_id=cam_id, width=1920, height=1080)
    cap.warmup(10)
    frame = cap.read()
    if frame is None:
        print("[错误] 无法读取摄像头")
        return
    fh, fw = frame.shape[:2]
    print(f"[信息] 摄像头 {cam_id}: {fw}x{fh}")

    # ── 裁剪框配置 ──
    CONFIG_FILE = "map_stitcher_crop.json"
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                crop = CropRegion.from_dict(json.load(f))
            print(f"[配置] 已加载裁剪框: {crop}")
        except Exception:
            crop = CropRegion(int(fw * 200 / 1280), int(fh * 80 / 720), fw - int(fw * 200 / 1280), fh - int(fh * 80 / 720))
    else:
        crop = CropRegion(int(fw * 200 / 1280), int(fh * 80 / 720), fw - int(fw * 200 / 1280), fh - int(fh * 80 / 720))
    print(f"[信息] 裁剪区: {crop}")

    stitcher = MapStitcher(min_movement=args.min_move,
                           canvas_w=args.width, canvas_h=args.height)
    show_crop = True
    stitcher.status = "就绪 | C拼接 | A自动 | S保存 | Q退出"

    print("=" * 60)
    print("  A     - 切换自动拼接")
    print("  C     - 手动拼接当前帧")
    print("  T     - 切换裁剪框显示")
    print("  IJKL  - 微调裁剪框位置")
    print("  +/-   - 缩放裁剪框 (四边同时)")
    print("  Shift+WASD - 收缩单边 (上/下/左/右)")
    print("  S     - 保存地图 + 裁剪配置")
    print("  R     - 重置地图")
    print("  Q     - 退出")
    print("=" * 60)

    cv2.namedWindow("DeadMaze - 地图拼接", cv2.WINDOW_NORMAL)
    cv2.namedWindow("拼接地图", cv2.WINDOW_NORMAL)
    auto_timer = time.time()
    auto_interval = 0.3
    FONT = cv2.FONT_HERSHEY_SIMPLEX

    while True:
        frame = cap.read()
        if frame is None:
            time.sleep(0.01)
            continue

        # 画面窗口 (带裁剪框叠加)
        if show_crop:
            display = crop.draw_on(frame)
        else:
            display = frame.copy()
        cv2.putText(display, stitcher.status, (10, 25), FONT, 0.45, (0, 255, 0), 1)
        cv2.putText(display, f"已拼: {stitcher.frame_count} 帧", (10, 45), FONT, 0.4, (255, 255, 0), 1)
        cv2.putText(display, f"自动: {'ON' if stitcher.auto_mode else 'OFF'}", (10, 65),
                    FONT, 0.4, (0, 255, 0) if stitcher.auto_mode else (0, 0, 255), 1)
        cv2.imshow("DeadMaze - 地图拼接", display)

        # 拼接地图窗口
        if stitcher.canvas is not None:
            md = stitcher.canvas.copy()
            mh, mw = md.shape[:2]
            scale = min(900 / mw, 900 / mh, 1.0)
            if scale < 1.0:
                md = cv2.resize(md, (int(mw * scale), int(mh * scale)))
            cv2.imshow("拼接地图", md)

        key = cv2.waitKey(1) & 0xFF
        _shift = ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000 != 0

        # Shift+WASD 伸缩单边
        if _shift and key in (ord('w'), ord('W')):
            crop.y += 10; crop.h = max(100, crop.h - 10)
            stitcher.status = f"裁剪框收缩上边: {crop}"
        elif _shift and key in (ord('s'), ord('S')):
            crop.h = max(100, crop.h - 10)
            stitcher.status = f"裁剪框收缩下边: {crop}"
        elif _shift and key in (ord('a'), ord('A')):
            crop.x += 10; crop.w = max(100, crop.w - 10)
            stitcher.status = f"裁剪框收缩左边: {crop}"
        elif _shift and key in (ord('d'), ord('D')):
            crop.w = max(100, crop.w - 10)
            stitcher.status = f"裁剪框收缩右边: {crop}"

        # 手动拼接
        elif key == ord('c') or key == ord('C'):
            cropped = crop.apply(frame)
            canvas, dx, dy, conf = stitcher.add_frame(cropped)
            if canvas is not None:
                stitcher.status = f"拼接 #{stitcher.frame_count} | Δ({dx:.0f},{dy:.0f}) c={conf:.2f}"

        # 自动拼接
        elif key == ord('a') or key == ord('A'):
            stitcher.auto_mode = not stitcher.auto_mode
            stitcher.status = f"自动: {'ON' if stitcher.auto_mode else 'OFF'}"

        # 显示切换
        elif key == ord('t') or key == ord('T'):
            show_crop = not show_crop
            stitcher.status = f"裁剪框: {'显示' if show_crop else '隐藏'}"

        # 微调裁剪框
        elif key == ord('i') or key == ord('I'):
            crop.y = max(0, crop.y - 5); stitcher.status = f"裁剪框上移: {crop}"
        elif key == ord('k') or key == ord('K'):
            crop.y += 5; stitcher.status = f"裁剪框下移: {crop}"
        elif key == ord('j') or key == ord('J'):
            crop.x = max(0, crop.x - 5); stitcher.status = f"裁剪框左移: {crop}"
        elif key == ord('l') or key == ord('L'):
            crop.x += 5; stitcher.status = f"裁剪框右移: {crop}"

        # 缩放裁剪框
        elif key == ord('+') or key == ord('='):
            crop.x = max(0, crop.x - 10); crop.y = max(0, crop.y - 10)
            crop.w += 20; crop.h += 20
            stitcher.status = f"裁剪框放大: {crop}"
        elif key == ord('-') or key == ord('_'):
            crop.x += 10; crop.y += 10
            crop.w = max(100, crop.w - 20); crop.h = max(100, crop.h - 20)
            stitcher.status = f"裁剪框缩小: {crop}"

        # 保存
        elif key == ord('s') or key == ord('S'):
            stitcher.save(args.output)
            with open(CONFIG_FILE, 'w') as f:
                json.dump(crop.to_dict(), f, indent=2)
            print(f"[保存] {args.output} + {CONFIG_FILE}")

        # 重置
        elif key == ord('r') or key == ord('R'):
            stitcher.reset()

        elif key == ord('q') or key == ord('Q'):
            with open(CONFIG_FILE, 'w') as f:
                json.dump(crop.to_dict(), f, indent=2)
            break

        # 自动拼接
        if stitcher.auto_mode and time.time() - auto_timer > auto_interval:
            cropped = crop.apply(frame)
            canvas, dx, dy, conf = stitcher.add_frame(cropped)
            if canvas is not None and stitcher.frame_count > 0:
                stitcher.status = f"自动 #{stitcher.frame_count} | Δ({dx:.0f},{dy:.0f}) c={conf:.2f}"
            auto_timer = time.time()

    cap.release()
    cv2.destroyAllWindows()
    print(f"退出。共拼接 {stitcher.frame_count} 帧。")


def cmd_reachable(args):
    """可达区标定 — 严格匹配 DeadMaze reachability_map.py."""
    import cv2
    from game_automator.mapping import ReachabilityEditor

    editor = ReachabilityEditor()
    editor.load_map(args.map)
    out = args.output or f"{editor.base}_reachable.png"

    # 断点续标
    if os.path.exists(out):
        saved = cv2.imread(out, cv2.IMREAD_GRAYSCALE)
        if saved is not None and saved.shape == (editor.h, editor.w):
            editor.binary = saved
            pct = np.sum(saved == 255) / saved.size * 100
            print(f"[加载] 已有标注 {out} (可行走={pct:.1f}%)")
        else:
            editor.init_boundary()
    else:
        editor.init_boundary()

    print("\n=== 二值可达图 ===")
    print("左键=涂白 | 右键=涂黑 | P=描边 | D=门标记 | IJKL=平移 | +/-=缩放")
    print("1-4=画笔 | C=HSV | T=视图 | F=切换填充颜色 | S=保存 | Q=保存+退出\n")

    cv2.namedWindow("二值可达图", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("二值可达图", cv2.WND_PROP_TOPMOST, 1)
    cv2.setMouseCallback("二值可达图", editor.on_mouse)

    while True:
        cv2.imshow("二值可达图", editor.render_overlay())
        key = cv2.waitKey(30) & 0xFF

        if key == ord('q') or key == ord('Q'):
            editor.save(out)
            print("[退出] 进度已自动保存")
            break

        elif key in (ord('p'), ord('P'), ord('m'), ord('M')):
            editor.door_mode = False
            editor.poly_mode = not editor.poly_mode
            editor.poly_points = []
            print(f"[模式] {'描边' if editor.poly_mode else '涂刷'}")
        elif key in (ord('d'), ord('D')):
            editor.poly_mode = False
            editor.door_mode = not editor.door_mode
            print(f"[模式] {'门标记' if editor.door_mode else '涂刷'}")

        elif editor.poly_mode and key == 27:  # Esc
            editor.cancel_poly(); print("[描边] 已取消")
        elif editor.poly_mode and key == 13:  # Enter
            editor.fill_poly(editor.poly_color)
        elif editor.poly_mode and key in (ord('f'), ord('F')):
            editor.poly_color = 0 if editor.poly_color == 255 else 255

        elif key == ord('t') or key == ord('T'):
            editor.show_mode = (editor.show_mode + 1) % 3
        elif key == ord('c') or key == ord('C'):
            editor.hsv_guess()

        elif ord('1') <= key <= ord('4'):
            if editor.door_mode:
                editor._set_door_dir(key - ord('1'))
            else:
                editor.set_brush([4, 12, 30, 80][key - ord('1')])

        elif key == ord('s') or key == ord('S'):
            editor.save(out)
        elif key == ord('r') or key == ord('R'):
            editor.init_boundary()

        elif key in (ord('+'), ord('=')):
            editor.scale = min(3.0, editor.scale * 1.15)
        elif key in (ord('-'), ord('_')):
            editor.scale = max(0.03, editor.scale / 1.15)

        elif key == ord('i'): editor.offset_y += 30
        elif key == ord('k'): editor.offset_y -= 30
        elif key == ord('j'): editor.offset_x += 30
        elif key == ord('l'): editor.offset_x -= 30

    cv2.destroyAllWindows()
    print("退出.")

def cmd_calibrate(args):
    """启动 ROI 标定网页."""
    from game_automator.capture import OBSVideoCapture
    from game_automator.calibration import CalibrationServer

    cap = OBSVideoCapture(cam_id=args.camera)
    cap.warmup(5)

    calib = CalibrationServer(cap, roi_file=args.output)
    if args.rois:
        calib.load_from_file(args.rois)
    calib.start(port=args.port)


def main():
    p = argparse.ArgumentParser(prog="game-automator",
        description="通用游戏自动化框架")
    sub = p.add_subparsers(dest="command")

    # serve
    sp = sub.add_parser("serve", help="启动导航 REST API")
    sp.add_argument("reachable", help="可达图路径")
    sp.add_argument("-c", "--camera", type=int, default=1)
    sp.add_argument("-p", "--port", type=int, default=5001)
    sp.add_argument("--map", type=str, default=None, help="地图图片(前端显示用)")
    sp.set_defaults(func=cmd_serve)

    # stitch
    sp = sub.add_parser("stitch", help="光流法建图")
    sp.add_argument("-c", "--camera", type=int, default=1)
    sp.add_argument("-m", "--min-move", type=int, default=25)
    sp.add_argument("--width", type=int, default=None)
    sp.add_argument("--height", type=int, default=None)
    sp.add_argument("-o", "--output", default="map_output.jpg")
    sp.set_defaults(func=cmd_stitch)

    # reachable
    sp = sub.add_parser("reachable", help="可达区标定 (交互式cv2窗口)")
    sp.add_argument("map", nargs="?", default="map_output.jpg", help="大地图路径")
    sp.add_argument("-o", "--output", default=None, help="输出可达图路径")
    sp.set_defaults(func=cmd_reachable)

    # calibrate
    sp = sub.add_parser("calibrate", help="ROI标定")
    sp.add_argument("-c", "--camera", type=int, default=1)
    sp.add_argument("-o", "--output", default="roi_calibration.json")
    sp.add_argument("-r", "--rois", default=None, help="已有ROI文件")
    sp.add_argument("-p", "--port", type=int, default=5050)
    sp.set_defaults(func=cmd_calibrate)

    args = p.parse_args()
    if args.command is None:
        p.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
