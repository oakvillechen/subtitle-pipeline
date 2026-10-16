# 纯 Python 生成 1024px 图标 PNG（圆角渐变底 + 白色字幕条）
import zlib, struct, sys
N = 1024
def px(x, y):
    r = 180; cx = min(max(x, r), N - r); cy = min(max(y, r), N - r)
    if (x - cx) ** 2 + (y - cy) ** 2 > r * r: return (0, 0, 0, 0)
    t = y / N
    c = (int(220 - 120 * t), int(40 + 30 * t), int(80 + 140 * t), 255)
    if 300 < x < 724 and 300 < y < 560 and ((x - 512) ** 2 / 212 ** 2 + (y - 430) ** 2 / 130 ** 2) < 1: c = (255, 255, 255, 255)  # 对话气泡
    for y0, x0, x1 in ((700, 220, 804), (790, 300, 724)):
        if y0 < y < y0 + 50 and x0 < x < x1: c = (255, 255, 255, 235)
    return c
raw = b"".join(b"\0" + b"".join(bytes(px(x, y)) for x in range(N)) for y in range(N))
ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
open(sys.argv[1], "wb").write(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw, 9)) + ch(b"IEND", b""))
