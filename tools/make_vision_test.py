"""
生成一张用于验证「读图能力」的测试图。

用法:
    .python\\python.exe tools\\make_vision_test.py

图中有若干**只能靠看图才能读出的信息**:
色块顺序、圆形位置、一个四位数字、一句随机短语。
这样就能确认读图链路是真的通了,而不是靠文件名或上下文猜的。
"""

import os
import random

from PIL import Image, ImageDraw, ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))
_WS = os.path.dirname(_HERE)
OUT = os.path.join(_WS, '.tmp', 'vision_test.png')

# 每次随机,避免"背答案"
COLORS = [('红', (220, 40, 40)), ('绿', (40, 170, 70)), ('蓝', (40, 90, 220))]
PHRASES = [
    '紫色雨伞挂在第三个门后',
    '窗台上的玻璃杯映出七点晨光',
    '铁轨尽头的信号灯刚刚转绿',
]


def pick_font(size):
    for name in ('msyh.ttc', 'simhei.ttf', 'simsun.ttc', 'arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    random.shuffle(COLORS)
    number = random.randint(1000, 9999)
    phrase = random.choice(PHRASES)

    W, H = 720, 420
    img = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    # 三个色块(顺序随机)
    for i, (_label, rgb) in enumerate(COLORS):
        x = 40 + i * 210
        d.rectangle([x, 40, x + 180, 160], fill=rgb, outline=(0, 0, 0), width=3)

    # 一个黄色圆
    d.ellipse([520, 40, 680, 200], fill=(250, 210, 40), outline=(0, 0, 0), width=3)

    # 一个四位数字
    d.text((40, 200), str(number), fill=(0, 0, 0), font=pick_font(90))

    # 一句中文短语
    d.text((40, 320), phrase, fill=(90, 30, 140), font=pick_font(38))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT)

    # 把答案写到另一个文件,便于人工比对(读图时不应读取本文件)
    ans = os.path.join(os.path.dirname(OUT), 'vision_test_answer.txt')
    with open(ans, 'w', encoding='utf-8') as fh:
        fh.write('色块顺序(左→右): %s\n' % ' '.join(c[0] for c in COLORS))
        fh.write('数字: %d\n' % number)
        fh.write('短语: %s\n' % phrase)

    print('图片: %s' % OUT)
    print('答案: %s' % ans)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
