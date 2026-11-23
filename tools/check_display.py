#!/usr/bin/env python3
"""디스플레이 모듈 검증 (WBS 1.2 완료 기준 : 전체 화면 전송 40FPS 이상)

배경 -> 캐릭터 2명 -> 이펙트 -> HUD 순서로 합성한 프레임을 SPI 64MHz, numpy 직접 전송으로
전체 화면 보내며 FPS와 합성/변환/전송 시간을 잰다.

1) 전송만 최대 속도로 반복 (화면 상한 측정)
2) 60Hz 고정 틱 루프(FixedTickLoop) 안에서 실제 게임처럼 실행
마지막에 방향 확인용 화면(좌상단 빨강, 우상단 초록, 좌하단 파랑, 위쪽 글자)을 3초 띄운다.

    python3 tools/check_display.py                 # Pi + 본넷
    python3 tools/check_display.py --headless      # PC : 전송 없이 합성·변환만
    python3 tools/check_display.py --secs 10 --csv bench/results/display_check.csv
"""
import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from pifighter.display import Display, W, H  # noqa: E402
from pifighter.engine import FixedTickLoop  # noqa: E402
from pifighter.render import FrameComposer  # noqa: E402

try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
except Exception:
    FONT = ImageFont.load_default()


def make_background():
    bg = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(bg)
    for y in range(H):
        d.line((0, y, W, y), fill=(40 + y // 3, 20 + y // 6, 80 - y // 4))
    d.rectangle((0, 200, W, H), fill=(60, 50, 40))
    for x in range(0, W, 24):
        d.rectangle((x, 150, x + 16, 200), fill=(30, 30, 50))
    return bg


def make_sprite(color, w=40, h=64):
    s = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(s)
    d.ellipse((12, 0, 28, 16), fill=color)
    d.rectangle((10, 16, 30, 42), fill=color)
    d.rectangle((30, 20, 40, 26), fill=color)
    d.rectangle((10, 42, 18, 64), fill=color)
    d.rectangle((22, 42, 30, 64), fill=color)
    return s


class TestScene:
    """틱마다 캐릭터가 움직이고 HP가 줄어드는 테스트 장면."""

    def __init__(self):
        p1 = make_sprite((240, 200, 60))
        p2 = make_sprite((80, 200, 255)).transpose(Image.FLIP_LEFT_RIGHT)
        self.sprites = (p1, p2)
        self.n = 0
        self.fps_text = "FPS --"
        self.comp = FrameComposer(make_background())
        self.comp.add("fighters", self.draw_fighters)
        self.comp.add("effects", self.draw_effects)
        self.comp.add("ui", self.draw_hud)

    def tick(self, n):
        self.n = n

    def snapshot(self):
        t = self.n
        return {"t": t, "x1": 40 + (t * 3) % 60, "x2": 150 - (t * 2) % 50,
                "hp1": 100 - (t // 3) % 100, "hp2": 100 - (t // 5) % 100}

    def draw_fighters(self, img, _d, s):
        img.paste(self.sprites[0], (s["x1"], 136), self.sprites[0])
        img.paste(self.sprites[1], (s["x2"], 136), self.sprites[1])

    def draw_effects(self, _img, d, s):
        if s["t"] % 20 < 4:   # 타격 이펙트 흉내
            cx = (s["x1"] + s["x2"]) // 2 + 20
            d.ellipse((cx - 10, 150, cx + 10, 170), outline=(255, 255, 255), width=2)

    def draw_hud(self, _img, d, s):
        d.rectangle((6, 8, 104, 18), outline=(255, 255, 255))
        d.rectangle((7, 9, 7 + s["hp1"] * 96 // 100, 17), fill=(255, 220, 0))
        d.rectangle((136, 8, 234, 18), outline=(255, 255, 255))
        d.rectangle((233 - s["hp2"] * 96 // 100, 9, 233, 17), fill=(255, 220, 0))
        d.text((110, 4), str(99 - (s["t"] // 60) % 100).zfill(2), font=FONT, fill=(255, 255, 255))
        d.text((6, 222), self.fps_text, font=FONT, fill=(0, 255, 0))


def orientation_pattern():
    img = Image.new("RGB", (W, H), (20, 20, 20))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 39, 39), fill=(255, 0, 0))        # 좌상단 빨강
    d.rectangle((W - 40, 0, W - 1, 39), fill=(0, 255, 0))  # 우상단 초록
    d.rectangle((0, H - 40, 39, H - 1), fill=(0, 0, 255))  # 좌하단 파랑
    d.text((60, 12), "TOP  1.2 OK", font=FONT, fill=(255, 255, 255))
    return img


def run_max(disp, secs):
    sc = TestScene()
    frames = 0
    comp = conv = send = 0.0
    start = last = time.perf_counter()
    while time.perf_counter() - start < secs:
        sc.tick(frames)
        img = sc.comp.compose(sc.snapshot())
        disp.show(img)
        comp += sc.comp.compose_ms
        conv += disp.convert_ms
        send += disp.send_ms
        frames += 1
        now = time.perf_counter()
        if now - last >= 0.5:
            sc.fps_text = "FPS %.1f max" % (frames / (now - start))
            last = now
    el = time.perf_counter() - start
    return {"stage": "full_max", "fps": round(frames / el, 1),
            "compose_ms": round(comp / frames, 2), "convert_ms": round(conv / frames, 2),
            "send_ms": round(send / frames, 2), "tick_hz": "", "tick_late_p99_ms": ""}


def run_loop(disp, secs):
    sc = TestScene()
    acc = {"comp": 0.0, "conv": 0.0, "send": 0.0, "n": 0, "last": time.perf_counter()}

    def render(snap, _n):
        img = sc.comp.compose(snap)
        disp.show(img)
        acc["comp"] += sc.comp.compose_ms
        acc["conv"] += disp.convert_ms
        acc["send"] += disp.send_ms
        acc["n"] += 1
        now = time.perf_counter()
        if now - acc["last"] >= 0.5:
            sc.fps_text = "FPS %.1f loop" % (loop.stats.frames / loop.stats.elapsed())
            acc["last"] = now

    loop = FixedTickLoop(sc.tick, render, sc.snapshot)
    s = loop.run(duration=secs).summary()
    n = max(acc["n"], 1)
    return {"stage": "full_in_60hz_loop", "fps": s["fps"],
            "compose_ms": round(acc["comp"] / n, 2), "convert_ms": round(acc["conv"] / n, 2),
            "send_ms": round(acc["send"] / n, 2), "tick_hz": s["tick_hz"],
            "tick_late_p99_ms": s["tick_late_p99_ms"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=5.0)
    ap.add_argument("--baud", type=int, default=64, help="SPI MHz")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--csv")
    a = ap.parse_args()

    rows = []
    with Display(baudrate=a.baud * 1_000_000, headless=a.headless) as disp:
        print("SPI %dMHz%s, %.0fs/stage" % (a.baud, " (headless)" if a.headless else "", a.secs))
        for fn in (run_max, run_loop):
            r = fn(disp, a.secs)
            rows.append(r)
            print("  %-18s fps %6.1f  compose %5.2fms  convert %5.2fms  send %6.2fms  tick %s  late99 %s"
                  % (r["stage"], r["fps"], r["compose_ms"], r["convert_ms"], r["send_ms"],
                     r["tick_hz"] or "-", r["tick_late_p99_ms"] if r["tick_late_p99_ms"] != "" else "-"),
                  flush=True)
        disp.show(orientation_pattern())
        time.sleep(0 if a.headless else 3)

    ok = rows[0]["fps"] >= 40 and rows[1]["fps"] >= 40 and abs(rows[1]["tick_hz"] - 60) < 0.5
    print("\n결과 :", "PASS - 전체 화면 전송 40FPS 이상, 로직 60틱/초" if ok else "FAIL")
    if a.csv:
        os.makedirs(os.path.dirname(os.path.abspath(a.csv)), exist_ok=True)
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print("CSV 저장 :", a.csv)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
