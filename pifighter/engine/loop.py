"""60Hz 고정 틱 게임 루프 + 렌더 스킵 (WBS 1.1)

판정 로직(tick)은 화면 속도와 관계없이 항상 60Hz로 돌리고,
화면(render)은 남는 시간에 가장 최신 상태만 그린다.
화면 전송이 한 틱보다 오래 걸리면 그 사이의 틱은 화면에 그리지 않고 건너뛴다.

두 가지 방식을 지원한다.

- ``thread`` (기본) : 판정 로직을 별도 스레드에서 마감 시각(deadline)에 맞춰 실행한다.
  화면 전송이 길어져도 틱이 제 시각에 실행된다. 사전 실측(bench/fps_bench.py)에서
  틱 지연 p99 2.6ms 이하로 확인한 구조다.
- ``accum`` : 단일 스레드 고정 시간 누적 방식. 렌더가 끝난 뒤 밀린 틱을 몰아서
  실행하므로 틱 수(60틱/초)는 지켜지지만 틱 사이 간격은 렌더 시간만큼 흔들린다.
  비교·디버그용.

사용 예::

    loop = FixedTickLoop(tick=game.tick, render=renderer.draw, snapshot=game.snapshot)
    loop.run()            # Ctrl+C 또는 loop.stop() 으로 종료
    print(loop.stats.summary())

- ``tick(n)``     : n번째 틱의 판정 로직. 입력 읽기·이동·판정을 여기서 한다.
- ``snapshot()``  : 렌더에 넘길 상태 복사본을 만든다. 틱과 같은 락 안에서 호출되므로
  렌더가 틱 도중의 반쯤 바뀐 상태를 그리는 일이 없다. 가볍게 유지할 것.
- ``render(snap, n)`` : 스냅샷을 그려서 화면으로 보낸다. 락 밖에서 실행된다.
"""
import threading
import time

TICK_HZ = 60


class LoopStats:
    """틱·프레임 통계. 틱 지연(ms)은 마감 시각 대비 실제 실행 시각의 차이."""

    def __init__(self):
        self.reset()

    def reset(self, now=None):
        self.start = time.perf_counter() if now is None else now
        self.end = None
        self.ticks = 0
        self.frames = 0
        self.skipped = 0        # 화면에 그려지지 않고 지나간 틱 수
        self.dropped = 0        # 너무 밀려서 아예 버린 틱 수 (정상이면 0)
        self.late_ms = []       # 틱마다 마감 대비 지연
        self.render_ms = []     # 프레임마다 렌더(합성+전송) 시간

    def elapsed(self):
        end = self.end if self.end is not None else time.perf_counter()
        return max(end - self.start, 1e-9)

    @staticmethod
    def _pct(values, p):
        if not values:
            return 0.0
        s = sorted(values)
        return s[min(len(s) - 1, int(len(s) * p))]

    def summary(self):
        el = self.elapsed()
        return {
            "secs": round(el, 2),
            "ticks": self.ticks,
            "tick_hz": round(self.ticks / el, 2),
            "frames": self.frames,
            "fps": round(self.frames / el, 1),
            "skipped_ticks": self.skipped,
            "dropped_ticks": self.dropped,
            "tick_late_p50_ms": round(self._pct(self.late_ms, 0.50), 2),
            "tick_late_p99_ms": round(self._pct(self.late_ms, 0.99), 2),
            "tick_late_max_ms": round(max(self.late_ms, default=0.0), 2),
            "render_ms_avg": round(sum(self.render_ms) / max(len(self.render_ms), 1), 2),
        }


class FixedTickLoop:
    def __init__(self, tick, render, snapshot=None, hz=TICK_HZ, mode="thread",
                 max_lag_ticks=30):
        if mode not in ("thread", "accum"):
            raise ValueError("mode must be 'thread' or 'accum'")
        self.tick_fn = tick
        self.render_fn = render
        self.snapshot_fn = snapshot or (lambda: None)
        self.dt = 1.0 / hz
        self.mode = mode
        # 이보다 더 밀리면(예: 디버거로 멈춤) 따라잡기를 포기하고 시각을 다시 맞춘다.
        self.max_lag = max_lag_ticks * self.dt
        self.stats = LoopStats()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._running = False
        self._tick_no = 0           # 다음에 실행할 틱 번호
        self._latest = None         # (틱 번호, 스냅샷)
        self._error = None

    # ---------------------------------------------------------------- 공통
    def stop(self):
        with self._cond:
            self._running = False
            self._cond.notify_all()

    @property
    def running(self):
        return self._running

    def _do_tick(self, deadline, now):
        """락을 잡은 상태에서 호출. 틱 하나 실행 + 스냅샷 갱신."""
        self.stats.late_ms.append((now - deadline) * 1000.0)
        n = self._tick_no
        self.tick_fn(n)
        self._tick_no = n + 1
        self.stats.ticks += 1
        self._latest = (n, self.snapshot_fn())

    def _do_render(self, item, last_rendered):
        n, snap = item
        if last_rendered is not None and n - last_rendered > 1:
            self.stats.skipped += n - last_rendered - 1
        t0 = time.perf_counter()
        self.render_fn(snap, n)
        self.stats.render_ms.append((time.perf_counter() - t0) * 1000.0)
        self.stats.frames += 1
        return n

    def run(self, duration=None):
        """루프 실행. duration(초)이 주어지면 마감 시각이 그 안에 드는 틱까지 실행하고 끝낸다."""
        self._running = True
        self._tick_no = 0
        self._latest = None
        self._error = None
        self.stats.reset()
        stop_at = None if duration is None else self.stats.start + duration
        try:
            if self.mode == "thread":
                self._run_thread(stop_at)
            else:
                self._run_accum(stop_at)
        finally:
            self._running = False
            if self.stats.end is None:
                self.stats.end = time.perf_counter()
        if self._error:
            raise self._error
        return self.stats

    # ---------------------------------------------------- thread 방식
    def _logic_thread(self, start, stop_at):
        deadline = start
        try:
            while self._running:
                now = time.perf_counter()
                if deadline > now:
                    time.sleep(deadline - now)
                    now = time.perf_counter()
                if stop_at is not None and deadline >= stop_at:
                    self.stats.end = now
                    break
                if now - deadline > self.max_lag:
                    missed = int((now - deadline) / self.dt)
                    self.stats.dropped += missed
                    deadline += missed * self.dt
                with self._cond:
                    self._do_tick(deadline, now)
                    self._cond.notify()
                deadline += self.dt
        except BaseException as e:  # 로직 쪽 예외는 메인 스레드에서 다시 던진다
            self._error = e
        finally:
            self.stop()

    def _run_thread(self, stop_at):
        th = threading.Thread(target=self._logic_thread,
                              args=(self.stats.start, stop_at),
                              name="logic-60hz", daemon=True)
        th.start()
        last = None
        try:
            while self._running:
                with self._cond:
                    # 새 틱이 나올 때까지 대기 -> 같은 상태를 두 번 그리지 않음
                    while self._running and (self._latest is None or
                                             self._latest[0] == last):
                        self._cond.wait(timeout=0.1)
                    if not self._running:
                        break
                    item = self._latest
                last = self._do_render(item, last)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
            th.join(timeout=1.0)

    # ----------------------------------------------------- accum 방식
    def _run_accum(self, stop_at):
        start = self.stats.start
        last = None
        try:
            while self._running:
                now = time.perf_counter()
                due = start + self._tick_no * self.dt   # 다음 틱의 마감 시각
                if stop_at is not None and due >= stop_at:
                    self.stats.end = now
                    break
                if now - due > self.max_lag:
                    missed = int((now - due) / self.dt)
                    self.stats.dropped += missed
                    start += missed * self.dt           # 기준 시각을 당겨 재동기화
                    due += missed * self.dt
                if now < due:
                    if self._latest is not None and self._latest[0] != last:
                        last = self._do_render(self._latest, last)
                    else:
                        time.sleep(due - now)
                    continue
                with self._lock:
                    self._do_tick(due, now)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
