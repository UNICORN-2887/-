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

    pf = Pathfinder(args.reachable)
    cap = OBSVideoCapture(cam_id=args.camera)
    server = NavigationServer(pf, port=args.port)
    print(f"地图: {args.reachable}")
    print(f"摄像头: OBS #{args.camera}")
    server.start()


def cmd_stitch(args):
    """光流法建图 (交互式 cv2 窗口)."""
    import cv2
    from game_automator.capture import OBSVideoCapture
    from game_automator.stitching import MapStitcher

    cap = OBSVideoCapture(cam_id=args.camera, width=1920, height=1080)
    cap.warmup(10)
    stitcher = MapStitcher(min_movement=args.min_move,
                           canvas_w=args.width, canvas_h=args.height)
    print("A=自动 C=手动 S=保存 R=重置 Q=退出")
    print("T=裁剪框 IJKL=移框 +/-=缩放框")
    print("Shift+WASD=伸缩单边")

    auto_mode = False
    while True:
        frame = cap.read()
        if frame is None:
            continue
        if auto_mode:
            stitcher.add_frame(frame)

        disp = stitcher.canvas if stitcher.canvas is not None else frame
        mh, mw = disp.shape[:2]
        scale = min(900 / mw, 900 / mh, 1.0)
        if scale < 1.0:
            disp = cv2.resize(disp, (int(mw*scale), int(mh*scale)))
        cv2.imshow("stitching", disp)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('a'):
            auto_mode = not auto_mode
        elif key == ord('c'):
            stitcher.add_frame(frame)
        elif key == ord('s'):
            stitcher.save(args.output)
        elif key == ord('r'):
            stitcher.reset()

    cap.release()
    cv2.destroyAllWindows()
    stitcher.save(args.output)
    print(f"已保存: {args.output}")


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
    sp.set_defaults(func=cmd_serve)

    # stitch
    sp = sub.add_parser("stitch", help="光流法建图")
    sp.add_argument("-c", "--camera", type=int, default=1)
    sp.add_argument("-m", "--min-move", type=int, default=25)
    sp.add_argument("--width", type=int, default=None)
    sp.add_argument("--height", type=int, default=None)
    sp.add_argument("-o", "--output", default="map_output.jpg")
    sp.set_defaults(func=cmd_stitch)

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
