#!/usr/bin/env python3
"""
PI FIGHTER '97 - TFT Bonnet FPS 벤치마크
Raspberry Pi 5 + Adafruit 1.3" Color TFT Bonnet (ST7789 240x240)

격투게임 1장면(배경 + 캐릭터 2명 + 체력바/타이머 HUD)을 매 프레임 그리면서
최적화 단계별로 FPS를 측정한다. 동시에 60Hz 고정 틱 로직 스레드를 돌려서
화면이 느려져도 판정 틱이 일정하게 유지되는지도 같이 잰다.

실행:  python3 fps_bench.py            (전체 단계, 단계당 5초)
       python3 fps_bench.py --secs 3   (단계당 3초)
결과:  화면 출력 + results.json / results.csv / frame_*.png 저장
"""
import argparse, json, csv, os, sys, threading, time

import board, digitalio
from PIL import Image, ImageDraw, ImageFont
from adafruit_rgb_display import st7789

try:
    import numpy as np
except ImportError:
    np = None

W = H = 240
OUT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- 디스플레이
_backlight = None


def make_display(baud):
    global _backlight
    cs = digitalio.DigitalInOut(board.CE0)
    dc = digitalio.DigitalInOut(board.D25)
    spi = board.SPI()
    disp = st7789.ST7789(spi, height=240, y_offset=80, rotation=180,
                         cs=cs, dc=dc, rst=None, baudrate=baud)
    if _backlight is None:
        _backlight = digitalio.DigitalInOut(board.D26)
        _backlight.switch_to_output()
        _backlight.value = True
    return disp, cs, dc


def release(cs, dc):
    for p in (cs, dc):
        try:
            p.deinit()
        except Exception:
            pass


# ---------------------------------------------------------------- 장면 리소스
def make_sprite(color, w=40, h=64):
    """임시 격투 캐릭터 스프라이트 (투명 배경 RGBA)."""
    s = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(s)
    d.ellipse((12, 0, 28, 16), fill=color)            # 머리
    d.rectangle((10, 16, 30, 42), fill=color)          # 몸
    d.rectangle((30, 20, 40, 26), fill=color)          # 팔(펀치)
    d.rectangle((10, 42, 18, 64), fill=color)          # 다리
    d.rectangle((22, 42, 30, 64), fill=color)
    return s


def make_background():
    bg = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(bg)
    for y in range(H):                                   # 노을 그라데이션
        d.line((0, y, W, y), fill=(40 + y // 3, 20 + y // 6, 80 - y // 4))
    d.rectangle((0, 200, W, H), fill=(60, 50, 40))       # 바닥
    for x in range(0, W, 24):
        d.rectangle((x, 150, x + 16, 200), fill=(30, 30, 50))  # 연구실 책상 실루엣
    return bg


try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
except Exception:
    FONT = ImageFont.load_default()


class Scene:
    """두 캐릭터가 좌우로 움직이며 체력/타이머가 바뀌는 대전 장면."""
    def __init__(self):
        self.bg = make_background()
        p1 = make_sprite((240, 200, 60))
        p2 = make_sprite((80, 200, 255))
        self.spr = [p1, p2.transpose(Image.FLIP_LEFT_RIGHT)]
        self.f = 0

    def positions(self):
        t = self.f
        x1 = 40 + (t * 3) % 60
        x2 = 150 - (t * 2) % 50
        return [(x1, 136), (x2, 136)]

    def hud(self, d, fps_text):
        hp1 = 100 - (self.f // 3) % 100
        hp2 = 100 - (self.f // 5) % 100
        d.rectangle((6, 8, 104, 18), outline=(255, 255, 255))
        d.rectangle((7, 9, 7 + hp1 * 96 // 100, 17), fill=(255, 220, 0))
        d.rectangle((136, 8, 234, 18), outline=(255, 255, 255))
        d.rectangle((233 - hp2 * 96 // 100, 9, 233, 17), fill=(255, 220, 0))
        d.text((110, 4), str(99 - (self.f // 30) % 100).zfill(2), font=FONT, fill=(255, 255, 255))
        d.text((6, 222), fps_text, font=FONT, fill=(0, 255, 0))

    def render_full(self, fps_text):
        img = self.bg.copy()
        for s, pos in zip(self.spr, self.positions()):
            img.paste(s, pos, s)
        self.hud(ImageDraw.Draw(img), fps_text)
        self.f += 1
        return img


# ---------------------------------------------------------------- 60Hz 로직 틱
class LogicTicker(threading.Thread):
    """60Hz 고정 틱. 실제 게임에선 여기서 입력/판정/카운터를 처리한다."""
    def __init__(self, hz=60):
        super().__init__(daemon=True)
        self.dt = 1.0 / hz
        self.ticks = 0
        self.late = []          # 각 틱의 지연(ms)
        self.running = True

    def run(self):
        nxt = time.perf_counter()
        while self.running:
            nxt += self.dt
            # --- 가짜 판정 작업 (히트박스 겹침 검사 정도의 부하) ---
            a = (self.ticks * 3) % 60
            _ = [(i, j) for i in range(8) for j in range(8) if (i * j + a) % 7 == 0]
            self.ticks += 1
            now = time.perf_counter()
            if nxt > now:
                time.sleep(nxt - now)
            self.late.append(max(0.0, (time.perf_counter() - nxt) * 1000))


# ---------------------------------------------------------------- 전송 방법
def to_rgb565_np(img):
    a = np.asarray(img, dtype=np.uint16)
    v = ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)
    return v.astype(">u2").tobytes()


def send_raw(disp, img, x=0, y=0):
    """numpy로 RGB565 변환 후 드라이버의 블록 전송을 직접 호출.
    rotation=180이므로 이미지와 좌표를 직접 뒤집어 보낸다."""
    w, h = img.size
    img = img.rotate(180)
    x0, y0 = W - x - w, H - y - h
    disp._block(x0, y0, x0 + w - 1, y0 + h - 1, to_rgb565_np(img))


# ---------------------------------------------------------------- 단계 실행
def run_stage(name, disp, mode, secs, snapshot, cap=0):
    scene = Scene()
    ticker = LogicTicker()
    ticker.start()
    frames, t_comp, t_send = 0, 0.0, 0.0
    fps_text = "FPS --"
    prev_rects = []
    sender_err = None

    # 스레드 전송용
    q_lock = threading.Condition()
    pending = [None]
    stop = [False]
    sent_th = [0]

    def sender():
        nonlocal t_send, sender_err
        while True:
            with q_lock:
                while pending[0] is None and not stop[0]:
                    q_lock.wait()
                if stop[0] and pending[0] is None:
                    return
                img = pending[0]
                pending[0] = None
            t = time.perf_counter()
            try:
                send_raw(disp, img)
            except Exception as e:
                sender_err = e
                return
            t_send += time.perf_counter() - t
            sent_th[0] += 1

    th = None
    if mode == "thread":
        th = threading.Thread(target=sender, daemon=True)
        th.start()

    start = time.perf_counter()
    last = start
    sent = 0
    while time.perf_counter() - start < secs:
        t0 = time.perf_counter()
        pos = scene.positions()          # 이번 프레임에 그려질 캐릭터 위치
        img = scene.render_full(fps_text)
        t1 = time.perf_counter()
        t_comp += t1 - t0

        if mode == "pil":
            disp.image(img)
            sent += 1
        elif mode == "numpy":
            send_raw(disp, img)
            sent += 1
        elif mode == "dirty":
            # 첫 프레임은 전체, 이후엔 HUD 띠 2개 + 캐릭터가 지나간 가로 띠만 전송
            cur = [(max(0, x - 4), y, min(W, x + 44), y + 64) for x, y in pos]
            if frames == 0:
                send_raw(disp, img)
            else:
                rs = cur + prev_rects
                band = (min(r[0] for r in rs), 136, max(r[2] for r in rs), 200)
                for (x0, y0, x1, y1) in [(0, 0, W, 24), (0, 216, W, 240), band]:
                    send_raw(disp, img.crop((x0, y0, x1, y1)), x0, y0)
            prev_rects = cur
            sent += 1
        elif mode == "thread":
            if sender_err:
                raise sender_err
            with q_lock:
                pending[0] = img     # 밀리면 최신 프레임으로 덮어씀(렌더 스킵)
                q_lock.notify()
        t2 = time.perf_counter()
        if mode != "thread":
            t_send += t2 - t1
        frames += 1
        if mode == "thread":
            sent = sent_th[0]
        if cap:
            # 화면을 cap FPS로 제한 (판정 틱과 같은 속도로 한 장씩)
            nxt_frame = start + frames / cap
            dt = nxt_frame - time.perf_counter()
            if dt > 0:
                time.sleep(dt)
        if t2 - last >= 0.5:
            fps_text = "FPS %.1f %s" % (sent / (t2 - start), name)
            last = t2
        if snapshot and frames == 30:
            img.save(os.path.join(OUT, "frame_%s.png" % name))

    if th:
        with q_lock:
            stop[0] = True
            q_lock.notify()
        th.join(timeout=2)
        sent = sent_th[0]
    elapsed = time.perf_counter() - start
    ticker.running = False
    ticker.join(timeout=1)
    late = sorted(ticker.late) or [0]
    res = {
        "stage": name,
        "display_fps": round(sent / elapsed, 1),
        "compose_ms": round(t_comp / max(frames, 1) * 1000, 1),
        "send_ms": round(t_send / max(sent, 1) * 1000, 1),
        "logic_hz": round(ticker.ticks / elapsed, 1),
        "tick_late_p50_ms": round(late[len(late) // 2], 2),
        "tick_late_p99_ms": round(late[int(len(late) * 0.99) - 1], 2),
    }
    print("  -> %s" % res, flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=5)
    ap.add_argument("--bauds", default="24,40,64,80", help="MHz 목록")
    ap.add_argument("--only", default="", help="dirty 처럼 특정 단계만 (예: --only dirty)")
    ap.add_argument("--cap", type=float, default=0, help="화면 FPS 상한 (예: 60)")
    a = ap.parse_args()

    print("Python", sys.version.split()[0], "| numpy", np.__version__ if np else "없음")
    if np is None:
        print("!! numpy가 없어 numpy/dirty/thread 단계는 건너뜁니다 (pip install numpy)")

    bauds = [int(b) for b in a.bauds.split(",")]
    results = []

    # 1~2단계: 기본 방식(Pillow + disp.image)으로 SPI 클럭별 측정
    for mhz in ([] if a.only else bauds):
        name = "1_pil_%dMHz" % mhz
        print("[%s]" % name, flush=True)
        try:
            disp, cs, dc = make_display(mhz * 1_000_000)
            results.append(run_stage(name, disp, "pil", a.secs, snapshot=(mhz == bauds[0])))
            release(cs, dc)
        except Exception as e:
            print("  !! 실패:", e)
            results.append({"stage": name, "error": str(e)})

    if np is not None:
        best = max(bauds)
        for mode in ([a.only] if a.only else ("numpy", "dirty", "thread")):
            name = "%s_%s_%dMHz" % ({"numpy": "3", "dirty": "4", "thread": "5"}[mode], mode, best)
            if a.cap:
                name += "_cap%d" % a.cap
            print("[%s]" % name, flush=True)
            try:
                disp, cs, dc = make_display(best * 1_000_000)
                results.append(run_stage(name, disp, mode, a.secs, snapshot=True, cap=a.cap))
                release(cs, dc)
            except Exception as e:
                print("  !! 실패:", e)
                results.append({"stage": name, "error": str(e)})

    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    keys = ["stage", "display_fps", "compose_ms", "send_ms", "logic_hz",
            "tick_late_p50_ms", "tick_late_p99_ms", "error"]
    with open(os.path.join(OUT, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in results:
            w.writerow(r)

    print("\n===== 결과 요약 =====")
    print("%-20s %8s %10s %8s %8s %8s" % ("stage", "FPS", "compose", "send", "logicHz", "late99"))
    for r in results:
        if "error" in r:
            print("%-20s ERROR %s" % (r["stage"], r["error"]))
        else:
            print("%-20s %8.1f %8.1fms %6.1fms %8.1f %6.2fms" % (
                r["stage"], r["display_fps"], r["compose_ms"], r["send_ms"],
                r["logic_hz"], r["tick_late_p99_ms"]))
    print("\n저장:", os.path.join(OUT, "results.json"))


if __name__ == "__main__":
    main()
