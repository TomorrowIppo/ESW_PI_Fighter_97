import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PIL import Image  # noqa: E402

from pifighter.display import Display, rgb_to_565  # noqa: E402
from pifighter.render import FrameComposer  # noqa: E402


class FakePanel:
    def __init__(self):
        self.calls = []

    def _block(self, x0, y0, x1, y1, data):
        self.calls.append((x0, y0, x1, y1, data))


def decode(data, w, h):
    return np.frombuffer(data, dtype=">u2").reshape(h, w)


class DisplayTest(unittest.TestCase):
    def setUp(self):
        self.d = Display(headless=True)
        self.panel = FakePanel()
        self.d._disp = self.panel

    def test_rgb565(self):
        px = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]]], dtype=np.uint8)
        self.assertEqual(list(decode(rgb_to_565(px), 4, 1)[0]), [0xF800, 0x07E0, 0x001F, 0xFFFF])

    def test_full_frame_rotated(self):
        img = Image.new("RGB", (240, 240))
        img.putpixel((0, 0), (255, 0, 0))   # 게임 좌상단
        self.d.show(img)
        x0, y0, x1, y1, data = self.panel.calls[-1]
        self.assertEqual((x0, y0, x1, y1), (0, 0, 239, 239))
        self.assertEqual(len(data), 240 * 240 * 2)
        # 180도 회전 -> 패널 우하단
        self.assertEqual(decode(data, 240, 240)[239, 239], 0xF800)

    def test_blit_position_and_clip(self):
        patch = np.zeros((20, 30, 3), dtype=np.uint8)
        self.d.blit(patch, (10, 5))                 # 게임 (10,5)~(39,24)
        self.assertEqual(self.panel.calls[-1][:4], (200, 215, 229, 234))
        self.d.blit(patch, (230, -10))              # 오른쪽·위로 넘침 -> 10x10 만
        x0, y0, x1, y1, data = self.panel.calls[-1]
        self.assertEqual((x1 - x0 + 1, y1 - y0 + 1), (10, 10))
        self.assertEqual(len(data), 10 * 10 * 2)
        n = len(self.panel.calls)
        self.d.blit(patch, (300, 300))              # 완전히 밖 -> 전송 안 함
        self.assertEqual(len(self.panel.calls), n)


class ComposerTest(unittest.TestCase):
    def test_layer_order(self):
        order = []
        c = FrameComposer()
        c.add("ui", lambda i, d, s: order.append("ui"))
        c.add("fighters", lambda i, d, s: order.append("fighters"))
        c.add("effects", lambda i, d, s: order.append("effects"))
        img = c.compose()
        self.assertEqual(order, ["fighters", "effects", "ui"])
        self.assertEqual(img.size, (240, 240))
        with self.assertRaises(ValueError):
            c.add("nope", lambda i, d, s: None)


if __name__ == "__main__":
    unittest.main()
