#!/usr/bin/env python3
"""Generate a visibly synthetic image and an image-only PDF for OCR smoke checks."""
from pathlib import Path
import json
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path("runs/ocr-smoke-20261012")
ROWS = [["项目", "开始日期", "结束日期"],
        ["出访行程", "2026-11-03", "2026-11-07"],
        ["学术访问", "2026-11-04", "2026-11-06"]]


def main():
    ROOT.mkdir(exist_ok=True, parents=True)
    image = Image.new("RGB", (1200, 1500), "white")
    draw = ImageDraw.Draw(image)
    cjk = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
    latin = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
    cn = ImageFont.truetype(cjk, 36)
    en = ImageFont.truetype(latin, 36)
    draw.text((70, 60), "模拟出访材料", font=ImageFont.truetype(cjk, 52), fill="black")
    draw.text((70, 150), "SIMULATED - NOT A REAL DOCUMENT",
              font=ImageFont.truetype(latin, 28), fill="black")
    draw.text((70, 220), "姓名：测试人员甲", font=cn, fill="black")
    label = "护照号码："
    draw.text((70, 290), label, font=cn, fill="black")
    draw.text((70 + draw.textlength(label, font=cn), 290), "P00001234", font=en, fill="black")
    xs, ys = [70, 380, 740, 1130], [420, 520, 620, 720]
    for x in xs:
        draw.line((x, ys[0], x, ys[-1]), fill="black", width=3)
    for y in ys:
        draw.line((xs[0], y, xs[-1], y), fill="black", width=3)
    for i, row in enumerate(ROWS):
        for j, value in enumerate(row):
            font = en if value.isascii() else cn
            draw.text((xs[j] + 18, ys[i] + 27), value, font=font, fill="black")
    draw.text((70, 840), "说明：访问日期与出行日期不同，请分别核对。", font=cn, fill="black")
    image.save(ROOT / "synthetic-table-v2.png")
    pdf = canvas.Canvas(str(ROOT / "synthetic-scan-v2.pdf"), pagesize=(600, 750), invariant=1)
    pdf.drawImage(ImageReader(image), 0, 0, width=600, height=750)
    pdf.save()
    (ROOT / "expected-v2.json").write_text(json.dumps({
        "synthetic": True, "human_reviewed": False,
        "name": "测试人员甲", "passport": "P00001234", "table": ROWS,
    }, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
