"""
OCR 识别测试工具
空格=截图, 拖拽框选数字区域, C=测试OCR, Q=退出
"""

import mss, cv2, numpy as np, pytesseract
pytesseract.pytesseract.tesseract_cmd = r"E:\Tools\tesseract\tesseract.exe"

import easyocr
print("EasyOCR...", end=" ", flush=True)
ocr = easyocr.Reader(["en"], gpu=True)
print("OK")

print("空格=截图 | 拖拽框选 | C=OCR | Q=退出")

cv2.namedWindow("截图", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("截图", cv2.WND_PROP_TOPMOST, 1)

frame = None; roi_pts = []

def mouse(event, x, y, flags, param):
    global roi_pts
    if frame is None: return
    h, w = frame.shape[:2]
    sx, sy = w / 1200, h / 800
    if event == cv2.EVENT_LBUTTONDOWN:
        roi_pts = [(int(x * sx), int(y * sy))]
    elif event == cv2.EVENT_LBUTTONUP:
        roi_pts.append((int(x * sx), int(y * sy)))

cv2.setMouseCallback("截图", mouse)

while True:
    if frame is None:
        cv2.imshow("截图", np.zeros((400, 600, 3), dtype=np.uint8))
    else:
        h, w = frame.shape[:2]
        disp = cv2.resize(frame, (1200, 800))
        if len(roi_pts) == 2:
            (x1, y1), (x2, y2) = roi_pts
            cv2.rectangle(disp,
                (int(x1*1200/w), int(y1*800/h)),
                (int(x2*1200/w), int(y2*800/h)), (0, 255, 0), 2)
        cv2.imshow("截图", disp)

    key = cv2.waitKey(30) & 0xFF
    if key == ord("q"): break
    if key == ord(" "):
        sct = mss.MSS()
        img = np.array(sct.grab(sct.monitors[0]))
        frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        roi_pts = []
        print(f"截图: {frame.shape[1]}x{frame.shape[0]}")
    if key == ord("c") and frame is not None and len(roi_pts) == 2:
        (x1, y1), (x2, y2) = roi_pts
        rx, ry = min(x1, x2), min(y1, y2)
        rw, rh = abs(x2 - x1), abs(y2 - y1)
        roi = frame[ry:ry+rh, rx:rx+rw]
        big = cv2.resize(roi, (rw*3, rh*3), interpolation=cv2.INTER_CUBIC)
        print(f"ROI: {rw}x{rh} @({rx},{ry})")
        # PaddleOCR
        try:
            result = ocr.readtext(big, detail=1, allowlist="0123456789")
            if result:
                for bbox, txt, conf in result:
                    print(f"  EasyOCR: [{txt}] c={conf:.2f}")
            else:
                print("  EasyOCR: 未识别")
        except Exception as e:
            print(f"  EasyOCR异常: {e}")
        # Tesseract 对比
        gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
        for th in [100, 130, 150, 180]:
            _, b = cv2.threshold(gray, th, 255, cv2.THRESH_BINARY)
            t = pytesseract.image_to_string(b, config=r"--psm 7 -c tessedit_char_whitelist=0123456789").strip()
            print(f"  Tesseract BIN{th}: [{t}]")
        cv2.imshow("ROI", big)
        roi_pts = []
cv2.destroyAllWindows()
