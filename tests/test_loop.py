import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from pifighter.engine import FixedTickLoop  # noqa: E402


class Counter:
    def __init__(self):
        self.n = []
        self.rendered = []

    def tick(self, n):
        self.n.append(n)

    def snapshot(self):
        return len(self.n)


class FixedTickLoopTest(unittest.TestCase):
    def _run(self, mode, render_ms, secs=1.0):
        c = Counter()

        def render(snap, n):
            c.rendered.append((snap, n))
            time.sleep(render_ms / 1000.0)

        loop = FixedTickLoop(c.tick, render, c.snapshot, mode=mode)
        stats = loop.run(duration=secs)
        return c, stats

    def check(self, mode, render_ms):
        c, s = self._run(mode, render_ms)
        # 1초에 60틱 (경계 오차 1틱 허용)
        self.assertAlmostEqual(s.ticks, 60, delta=1)
        # 틱 번호는 빠짐없이 순서대로
        self.assertEqual(c.n, list(range(len(c.n))))
        self.assertEqual(s.dropped, 0)
        # 같은 틱을 두 번 그리지 않고, 스냅샷은 그 틱 직후의 상태
        ns = [n for _, n in c.rendered]
        self.assertEqual(ns, sorted(set(ns)))
        for snap, n in c.rendered:
            self.assertEqual(snap, n + 1)
        # 첫 프레임 이후 : 그린 프레임 수 + 건너뛴 틱 수 = 지나간 틱 수
        if ns:
            self.assertEqual(s.frames + s.skipped, ns[-1] - ns[0] + 1)
        return s

    def test_thread_fast_render(self):
        s = self.check("thread", 0)
        self.assertLessEqual(s.frames, 61)     # 새 틱이 없으면 그리지 않음 -> 60FPS 상한

    def test_thread_slow_render(self):
        s = self.check("thread", 50)           # 화면 ~20FPS
        self.assertGreater(s.skipped, 0)
        self.assertLess(s.frames, 25)

    def test_accum_slow_render(self):
        s = self.check("accum", 50)
        self.assertGreater(s.skipped, 0)

    def test_tick_error_propagates(self):
        def bad(n):
            if n == 3:
                raise RuntimeError("boom")
        loop = FixedTickLoop(bad, lambda s, n: None)
        with self.assertRaises(RuntimeError):
            loop.run(duration=1.0)


if __name__ == "__main__":
    unittest.main()
