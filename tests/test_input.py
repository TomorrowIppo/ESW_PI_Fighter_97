import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from pifighter.input import (A, B, DOWN, LEFT, RIGHT, UP, InputReader,  # noqa: E402
                             ScriptBackend)


def run(frames, debounce=1):
    r = InputReader(ScriptBackend(frames), debounce_ticks=debounce)
    return [r.poll() for _ in frames]


class InputTest(unittest.TestCase):
    def test_press_vs_hold(self):
        st = run([[], [A], [A], [A], []])
        self.assertEqual([s.pressed_any(A) for s in st], [False, True, False, False, False])
        self.assertEqual([s.is_held(A) for s in st], [False, True, True, True, False])
        self.assertEqual([A in s.released for s in st], [False, False, False, False, True])

    def test_one_tick_tap_counts_once(self):
        st = run([[A], [], [A], []])
        self.assertEqual(sum(s.pressed_any(A) for s in st), 2)

    def test_diagonal_and_socd(self):
        st = run([[DOWN, RIGHT], [UP, LEFT], [LEFT, RIGHT], [UP, DOWN, RIGHT], []])
        self.assertEqual([s.numpad() for s in st], [3, 7, 5, 6, 5])
        # 왼쪽을 볼 때는 좌우 반전 : ↓→ 은 '아래-뒤' = 1
        self.assertEqual(st[0].numpad(facing=-1), 1)

    def test_debounce_filters_chatter(self):
        # 1틱짜리 떨림은 debounce=2에서 무시, 2틱 이상 유지되면 반영
        st = run([[B], [], [B], [B], [B], [], [B], []], debounce=2)
        self.assertEqual([s.is_held(B) for s in st],
                         [False, False, False, True, True, True, True, True])
        self.assertEqual(sum(s.pressed_any(B) for s in st), 1)

    def test_simultaneous_buttons(self):
        st = run([[A, B, RIGHT]])
        self.assertTrue(st[0].pressed_any(A) and st[0].pressed_any(B))
        self.assertEqual(st[0].direction, (1, 0))


if __name__ == "__main__":
    unittest.main()
