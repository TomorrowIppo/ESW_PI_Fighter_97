"""프레임 합성 (WBS 1.2)

ST7789에는 하드웨어 스프라이트가 없으므로 메모리에서 한 장의 프레임을
배경 -> 캐릭터 -> 이펙트 -> UI 순서로 합성한 뒤 한 번에 전송한다.

    comp = FrameComposer(background_image)
    comp.add("fighters", draw_fighters)     # fn(img, draw, snap)
    comp.add("ui", draw_hud)
    frame = comp.compose(snap)
    display.show(frame)
"""
import time

from PIL import Image, ImageDraw

from .display import W, H

LAYERS = ("background", "fighters", "effects", "ui")


class FrameComposer:
    def __init__(self, background=None, size=(W, H)):
        self.size = size
        self.set_background(background)
        self._layers = {name: [] for name in LAYERS}
        self.compose_ms = 0.0

    def set_background(self, background):
        if background is None:
            background = Image.new("RGB", self.size, (0, 0, 0))
        self.background = background.convert("RGB")

    def add(self, layer, fn):
        """layer 에 그리기 함수 등록. fn(img, draw, snap) 형태."""
        if layer not in self._layers:
            raise ValueError("unknown layer %r (one of %s)" % (layer, ", ".join(LAYERS)))
        self._layers[layer].append(fn)
        return fn

    def compose(self, snap=None):
        t0 = time.perf_counter()
        img = self.background.copy()
        draw = ImageDraw.Draw(img)
        for name in LAYERS:
            for fn in self._layers[name]:
                fn(img, draw, snap)
        self.compose_ms = (time.perf_counter() - t0) * 1000.0
        return img
