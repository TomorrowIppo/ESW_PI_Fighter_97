#!/usr/bin/env python3
"""입력 모듈 검증 (WBS 1.3 완료 기준 : 매 틱 입력 반영, 씹힘 없음)

60Hz 고정 틱 루프에서 매 틱 입력을 읽고, 화면에 지금 누른 버튼·방향과
버튼별 누른 횟수를 띄운다. 콘솔에는 누름/뗌 이벤트를 틱 번호와 함께 찍는다.

    python3 tools/check_input.py               # 60초 동안 (CENTER 3초 길게 누르면 종료)
    python3 tools/check_input.py --secs 30 --debounce 2

확인 방법 : A를 정해진 횟수(예 20번) 빠르게 연타한 뒤 화면 카운트가 같은지 본다.
종료하면 버튼별 누른 횟수, 가장 짧게 눌린 길이(틱), poll 시간을 요약한다.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PIL import ImageFont  # noqa: E402

from pifighter.display import Display  # noqa: E402
from pifighter.engine import FixedTickLoop  # noqa: E402
from pifighter.input import (A, B, BUTTONS, CENTER, DOWN, LEFT, RIGHT, UP,  # noqa: E402
                             InputReader)
from pifighter.render import FrameComposer  # noqa: E402

try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    BIG = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
except Exception:
    FONT = BIG = ImageFont.load_default()

ON, OFF, EDGE = (255, 220, 0), (60, 60, 70), (200, 200, 200)
ARROW = {1: "DL", 2: "D", 3: "DR", 4: "L", 5: "N", 6: "R", 7: "UL", 8: "U", 9: "UR"}


class InputCheck:
    def __init__(self, reader):
        self.reader = reader
        self.counts = {b: 0 for b in BUTTONS}
        self.down_at = {}
        self.min_len = {b: None for b in BUTTONS}
        self.poll_ms = []
        self.center_hold = 0
        self.quit = False
        self.st = reader.state

    def tick(self, n):
        t0 = time.perf_counter()
        st = self.reader.poll()
        self.poll_ms.append((time.perf_counter() - t0) * 1000.0)
        for b in st.pressed:
            self.counts[b] += 1
            self.down_at[b] = n
        for b in st.released:
            ln = n - self.down_at.pop(b, n)
            if self.min_len[b] is None or ln < self.min_len[b]:
                self.min_len[b] = ln
        if st.pressed or st.released:
            print("tick %6d  +%-18s -%-18s held=%s dir=%s" % (
                n, ",".join(sorted(st.pressed)), ",".join(sorted(st.released)),
                ",".join(sorted(st.held)) or "-", ARROW[st.numpad()]), flush=True)
        self.center_hold = self.center_hold + 1 if st.is_held(CENTER) else 0
        if self.center_hold >= 180:
            self.quit = True
        self.st = st

    def snapshot(self):
        return (self.st, dict(self.counts))

    def draw(self, _img, d, snap):
        st, counts = snap
        cx, cy, r = 70, 110, 18
        boxes = {UP: (cx, cy - 2 * r), DOWN: (cx, cy + 2 * r), LEFT: (cx - 2 * r, cy),
                 RIGHT: (cx + 2 * r, cy), CENTER: (cx, cy)}
        for b, (x, y) in boxes.items():
            d.rectangle((x - r + 2, y - r + 2, x + r - 2, y + r - 2),
                        fill=ON if st.is_held(b) else OFF, outline=EDGE)
        for b, (x, y) in ((A, (165, 95)), (B, (205, 125))):
            d.ellipse((x - r, y - r, x + r, y + r), fill=ON if st.is_held(b) else OFF, outline=EDGE)
            d.text((x - 5, y - 8), b, font=FONT, fill=(0, 0, 0))
        d.text((8, 6), "INPUT TEST  tick %d" % st.tick, font=FONT, fill=(255, 255, 255))
        d.text((150, 160), ARROW[st.numpad()], font=BIG, fill=(0, 255, 160))
        y = 180
        line = "  ".join("%s%d" % (b[0] if b != CENTER else "C", counts[b])
                         for b in (UP, DOWN, LEFT, RIGHT, CENTER))
        d.text((8, y), line, font=FONT, fill=(255, 255, 255))
        d.text((8, y + 20), "A %d   B %d" % (counts[A], counts[B]), font=FONT, fill=(255, 255, 255))
        d.text((8, 222), "hold CENTER 3s to quit", font=FONT, fill=(150, 150, 150))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=60.0)
    ap.add_argument("--debounce", type=int, default=1)
    a = ap.parse_args()

    reader = InputReader(debounce_ticks=a.debounce)
    chk = InputCheck(reader)
    comp = FrameComposer()
    comp.add("ui", chk.draw)
    print("입력 확인 시작 (%.0f초, debounce=%d). CENTER 3초 누르면 종료." % (a.secs, a.debounce),
          flush=True)
    with Display() as disp:
        loop = None

        def tick(n):
            chk.tick(n)
            if chk.quit:
                loop.stop()

        loop = FixedTickLoop(tick, lambda s, n: disp.show(comp.compose(s)), chk.snapshot)
        s = loop.run(duration=a.secs).summary()
    reader.close()

    pm = sorted(chk.poll_ms) or [0]
    print("\n===== 요약 =====")
    print("로직 %.2f틱/초, 화면 %.1fFPS, 틱 지연 p99 %.2fms" % (s["tick_hz"], s["fps"], s["tick_late_p99_ms"]))
    print("poll 시간 평균 %.3fms, 최대 %.3fms" % (sum(pm) / len(pm), pm[-1]))
    for b in BUTTONS:
        print("  %-6s 누른 횟수 %3d   가장 짧게 누른 길이 %s틱" % (
            b, chk.counts[b], "-" if chk.min_len[b] is None else chk.min_len[b]))


if __name__ == "__main__":
    main()
