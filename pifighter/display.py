"""디스플레이 출력 모듈 (WBS 1.2)

Adafruit 1.3" TFT Bonnet (ST7789, 240x240) 초기화와 화면 전송을 담당한다.

- SPI 64MHz (Pi 5에서는 64MHz와 80MHz 결과가 같았다)
- 기본 ``disp.image()`` 대신 numpy로 RGB565 바이트를 만들어 ``_block`` 으로 바로 전송
- 본넷은 180도 돌려 쓰므로, PIL 회전 대신 numpy 슬라이스(뒤집기)로 처리
- ``blit()`` 으로 사각형 영역만 보낼 수 있다 (부분 갱신 WBS 1.5에서 사용)

하드웨어가 없는 PC에서는 ``Display(headless=True)`` 로 변환까지만 수행한다.
"""
import time

import numpy as np

W = H = 240

# 본넷 핀 (Adafruit 예제 / bench/fps_bench.py 와 동일)
PIN_CS = "CE0"
PIN_DC = "D25"
PIN_BACKLIGHT = "D26"
SPI_HZ = 64_000_000


def rgb_to_565(rgb):
    """(h, w, 3) uint8 배열 -> ST7789에 그대로 보낼 big-endian RGB565 바이트."""
    a = rgb.astype(np.uint16)
    v = ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)
    return v.astype(">u2").tobytes()


def _as_rgb_array(frame):
    """PIL Image 또는 numpy 배열을 (h, w, 3) uint8 배열로."""
    if isinstance(frame, np.ndarray):
        return frame[..., :3]
    if frame.mode != "RGB":
        frame = frame.convert("RGB")
    return np.asarray(frame)


class Display:
    """ST7789 출력. 좌표는 모두 게임 화면 기준(좌상단 0,0)."""

    def __init__(self, baudrate=SPI_HZ, rotate180=True, headless=False, backlight=True):
        self.size = (W, H)
        self.rotate180 = rotate180
        self.headless = headless
        self.baudrate = baudrate
        self.convert_ms = 0.0   # 마지막 전송의 RGB565 변환 시간
        self.send_ms = 0.0      # 마지막 전송의 SPI 전송 시간
        self._pins = []
        self._disp = None
        if not headless:
            self._open(backlight)

    def _open(self, backlight):
        import board
        import digitalio
        from adafruit_rgb_display import st7789

        cs = digitalio.DigitalInOut(getattr(board, PIN_CS))
        dc = digitalio.DigitalInOut(getattr(board, PIN_DC))
        self._pins += [cs, dc]
        # 드라이버 rotation은 image()에만 적용되고 _block은 패널 좌표를 쓰므로 회전은 blit()에서 직접 처리한다.
        self._disp = st7789.ST7789(board.SPI(), height=H, y_offset=80, rotation=180,
                                   cs=cs, dc=dc, rst=None, baudrate=self.baudrate)
        bl = digitalio.DigitalInOut(getattr(board, PIN_BACKLIGHT))
        bl.switch_to_output()
        bl.value = bool(backlight)
        self._pins.append(bl)

    # ------------------------------------------------------------------
    def show(self, frame):
        """전체 화면 전송. frame : 240x240 PIL Image 또는 (240, 240, 3) 배열."""
        self.blit(frame, (0, 0))

    def blit(self, frame, pos=(0, 0)):
        """frame 을 화면 (x, y) 위치에 전송. 화면 밖으로 나가는 부분은 잘라낸다."""
        rgb = _as_rgb_array(frame)
        x, y = pos
        h, w = rgb.shape[:2]
        # 화면 경계로 자르기
        cx0, cy0 = max(0, -x), max(0, -y)
        cx1, cy1 = min(w, W - x), min(h, H - y)
        if cx1 <= cx0 or cy1 <= cy0:
            return
        rgb = rgb[cy0:cy1, cx0:cx1]
        x, y = x + cx0, y + cy0
        h, w = rgb.shape[:2]

        t0 = time.perf_counter()
        if self.rotate180:
            rgb = rgb[::-1, ::-1]
            px, py = W - x - w, H - y - h
        else:
            px, py = x, y
        data = rgb_to_565(rgb)
        t1 = time.perf_counter()
        if self._disp is not None:
            self._disp._block(px, py, px + w - 1, py + h - 1, data)
        t2 = time.perf_counter()
        self.convert_ms = (t1 - t0) * 1000.0
        self.send_ms = (t2 - t1) * 1000.0

    def fill(self, color=(0, 0, 0)):
        self.show(np.full((H, W, 3), color, dtype=np.uint8))

    def close(self, clear=True):
        if self._disp is not None and clear:
            try:
                self.fill((0, 0, 0))
            except Exception:
                pass
        for p in self._pins:
            try:
                p.deinit()
            except Exception:
                pass
        self._pins = []
        self._disp = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
