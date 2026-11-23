#!/usr/bin/env python3
"""고정 틱 루프 검증 (WBS 1.1 완료 기준 : 화면 FPS와 관계없이 로직 60틱/초 유지)

화면 전송 시간을 흉내 낸 가짜 렌더(0ms, 22ms≈45FPS, 50ms≈20FPS, 100ms≈10FPS, 불규칙)를
걸어 놓고 판정 틱이 60Hz를 유지하는지, 틱 지연이 얼마나 되는지 잰다.
하드웨어 없이도 돌아가므로 Pi와 PC 양쪽에서 실행할 수 있다.

    python3 tools/check_loop.py                 # 기본 : 단계당 5초, thread 방식
    python3 tools/check_loop.py --mode accum    # 단일 스레드 누적 방식과 비교
    python3 tools/check_loop.py --secs 10 --csv results/loop_check.csv
"""
import argparse
import csv
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from pifighter.engine import FixedTickLoop  # noqa: E402


class FakeGame:
    """판정 로직 부하 흉내 : 캐릭터 2명 이동 + 히트박스 8x8 검사 정도."""

    def __init__(self):
        self.x = [40.0, 180.0]
        self.v = [1.5, -1.0]
        self.hits = 0

    def tick(self, n):
        for i in range(2):
            self.x[i] += self.v[i]
            if not 0 <= self.x[i] <= 200:
                self.v[i] = -self.v[i]
        a = n % 60
        self.hits += sum(1 for i in range(8) for j in range(8) if (i * j + a) % 7 == 0)

    def snapshot(self):
        return tuple(self.x)


def busy_render(ms):
    """sleep(=SPI 전송처럼 GIL을 놓는 대기) 80% + 계산 20% 로 렌더 시간을 흉내."""
    def render(_snap, _n):
        t_end = time.perf_counter() + ms / 1000.0 * 0.2
        while time.perf_counter() < t_end:
            pass
        time.sleep(ms / 1000.0 * 0.8)
    return render


def jitter_render(_snap, _n):
    busy_render(random.choice((5, 15, 22, 40, 80)))(_snap, _n)


CASES = [
    ("render_0ms", busy_render(0)),
    ("render_22ms(~45fps)", busy_render(22)),
    ("render_50ms(~20fps)", busy_render(50)),
    ("render_100ms(~10fps)", busy_render(100)),
    ("render_jitter_5-80ms", jitter_render),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=5.0)
    ap.add_argument("--mode", choices=("thread", "accum"), default="thread")
    ap.add_argument("--csv", help="결과를 저장할 CSV 경로")
    a = ap.parse_args()

    print("Python %s | mode=%s | %.0fs/case" % (sys.version.split()[0], a.mode, a.secs))
    rows = []
    for name, render in CASES:
        game = FakeGame()
        loop = FixedTickLoop(tick=game.tick, render=render, snapshot=game.snapshot, mode=a.mode)
        s = loop.run(duration=a.secs).summary()
        s = {"case": name, "mode": a.mode, **s}
        rows.append(s)
        print("  %-22s tick %6.2fHz  fps %5.1f  skip %5d  drop %d  late p50 %5.2f p99 %5.2f max %6.2f ms"
              % (name, s["tick_hz"], s["fps"], s["skipped_ticks"], s["dropped_ticks"],
                 s["tick_late_p50_ms"], s["tick_late_p99_ms"], s["tick_late_max_ms"]), flush=True)

    # 기준 : 60틱/초 유지 + 버린 틱 없음 + 틱 지연 p99가 한 틱(16.7ms) 미만
    bad = [r["case"] for r in rows
           if abs(r["tick_hz"] - 60) >= 0.5 or r["dropped_ticks"] or r["tick_late_p99_ms"] >= 1000 / 60]
    ok = not bad
    print("\n결과 :", "PASS - 모든 경우 로직 60틱/초 유지, 틱 지연 p99 < 16.7ms"
          if ok else "FAIL - " + ", ".join(bad))

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
