"""OBS 虚拟摄像头预览 - Q退出"""
import cv2
for cam_id in [0, 1, 2]:
    cap = cv2.VideoCapture(cam_id)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    ret, f = cap.read()
    w = f.shape[1] if ret else 'N/A'
    h = f.shape[0] if ret else 'N/A'
    print(f"摄像头 {cam_id}: {'OK '+str(w)+'x'+str(h) if ret else '无信号'}")
    cap.release()

OBS_CAM = int(input("选OBS的摄像头ID (0/1/2): ") or "1")
cap = cv2.VideoCapture(OBS_CAM)
cv2.namedWindow("OBS画面 - Q退出", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("OBS画面 - Q退出", cv2.WND_PROP_TOPMOST, 1)
while True:
    ret, frame = cap.read()
    if not ret: print("无帧"); break
    cv2.imshow("OBS画面 - Q退出", frame)
    if cv2.waitKey(30) & 0xFF == ord('q'): break
cap.release(); cv2.destroyAllWindows()
