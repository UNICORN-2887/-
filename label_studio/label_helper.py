"""
DeadMaze - 标注辅助工具
1. 将截图复制到 Label Studio 可访问的目录
2. 把 Label Studio 导出的 JSON 标注转换为 YOLO 格式
"""

import os
import sys
import json
import shutil
import argparse

# ============================================================
# YOLO 类别映射（必须与 labeling_config.xml 保持一致）
# ============================================================
CLASS_MAP = {
    "Bike": 0,
    "Psign": 1,
    "Campfire": 2,
    "Sleepbag": 3,
    "TreeShadow1": 4,
    "DeadTree1": 5,
}


# ============================================================
# 功能1: 准备图片 → 复制到统一目录
# ============================================================
def prepare_images(source_dir, dest_dir):
    """将截图复制到 Label Studio 导入目录"""
    os.makedirs(dest_dir, exist_ok=True)
    copied = 0

    for f in sorted(os.listdir(source_dir)):
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            src = os.path.join(source_dir, f)
            dst = os.path.join(dest_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                copied += 1

    print(f"已复制 {copied} 张图片到 {os.path.abspath(dest_dir)}/")
    print(f"在 Label Studio 中导入时选择此目录即可。")


# ============================================================
# 功能2: Label Studio JSON → YOLO 格式
# ============================================================
def convert_to_yolo(json_file, output_dir, image_dir=None):
    """
    将 Label Studio 导出的 JSON 转换为 YOLO 格式
    - 每张图片生成一个 .txt 文件（同名）
    - 每行: class_id x_center y_center width height（归一化0~1）
    """
    os.makedirs(output_dir, exist_ok=True)

    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    converted = 0
    skipped = 0

    for item in data:
        # Label Studio 导出格式可能因版本而异，兼容两种
        if 'data' not in item:
            continue

        # 获取图片文件名
        img_path = item['data'].get('image', '')
        img_name = os.path.basename(img_path).replace('\\', '/').split('/')[-1]
        if not img_name:
            # 尝试另一个字段
            img_name = item.get('file_upload', 'unknown.jpg')

        base_name = os.path.splitext(img_name)[0]
        txt_path = os.path.join(output_dir, f"{base_name}.txt")

        # 获取图片尺寸
        annotations = item.get('annotations', [])
        if not annotations:
            skipped += 1
            continue

        # 优先从标注中获取图片尺寸
        img_w, img_h = None, None

        for ann in annotations:
            result = ann.get('result', [])

            # 有些版本 result 直接在 ann 上
            if not result and 'value' in ann:
                result = [ann]

            for r in result:
                val = r.get('value', {})

                # 获取原始尺寸
                orig_w = val.get('original_width', 0)
                orig_h = val.get('original_height', 0)
                if orig_w and orig_h:
                    img_w, img_h = orig_w, orig_h

                # 获取标注框
                label = val.get('rectanglelabels', None)
                if label is None:
                    # 尝试 r['type'] == 'rectanglelabels'
                    t = r.get('type', '')
                    if t == 'rectanglelabels':
                        label = val.get('rectanglelabels', [])
                    else:
                        continue

                if isinstance(label, list) and len(label) > 0:
                    label = label[0]

                if label not in CLASS_MAP:
                    continue

                # 坐标（可能是百分比或像素）
                x = val.get('x', 0)
                y = val.get('y', 0)
                w = val.get('width', 0)
                h = val.get('height', 0)

                # 转换像素坐标为归一化坐标
                if img_w and img_h:
                    if x > 1 or y > 1:  # 像素坐标
                        x_center = (x + w / 2) / img_w
                        y_center = (y + h / 2) / img_h
                        width = w / img_w
                        height = h / img_h
                    else:  # 已归一化
                        x_center = x + w / 2
                        y_center = y + h / 2
                        width = w
                        height = h
                else:
                    # 无尺寸信息，假设归一化
                    x_center = x + w / 2
                    y_center = y + h / 2
                    width = w
                    height = h

                class_id = CLASS_MAP[label]
                line = f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"
                # 追加写入
                with open(txt_path, 'a', encoding='utf-8') as tf:
                    tf.write(line + '\n')

                converted += 1

    print(f"转换完成: {converted} 个标注框 → {output_dir}/")
    print(f"跳过 {skipped} 张无标注的图片")

    # 生成 data.yaml
    yaml_path = os.path.join(os.path.dirname(output_dir), 'data.yaml')
    with open(yaml_path, 'w', encoding='utf-8') as f:
        f.write(f"# DeadMaze 标志物检测\n")
        f.write(f"path: {os.path.abspath(os.path.dirname(output_dir))}\n")
        f.write(f"train: {os.path.abspath(output_dir)}/images\n")
        f.write(f"val: {os.path.abspath(output_dir)}/images\n")
        f.write(f"\nnc: {len(CLASS_MAP)}\n")
        f.write(f"names: {list(CLASS_MAP.keys())}\n")
    print(f"data.yaml 已生成: {yaml_path}")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DeadMaze 标注辅助工具")
    sub = parser.add_subparsers(dest='cmd', required=True)

    # prepare
    p_prep = sub.add_parser('prepare', help='复制截图到统一目录')
    p_prep.add_argument('source', help='截图目录 (如 pic/)')
    p_prep.add_argument('-d', '--dest', default='label_studio/images',
                        help='目标目录')

    # convert
    p_conv = sub.add_parser('convert', help='Label Studio JSON → YOLO')
    p_conv.add_argument('json_file', help='Label Studio 导出的 JSON 文件')
    p_conv.add_argument('-o', '--output', default='label_studio/yolo_labels',
                        help='YOLO 标注输出目录')

    args = parser.parse_args()

    if args.cmd == 'prepare':
        prepare_images(args.source, args.dest)
    elif args.cmd == 'convert':
        convert_to_yolo(args.json_file, args.output)
