"""입력 모듈 (WBS 1.3)

본넷의 5방향 조이스틱(상하좌우·가운데)과 A/B 버튼을 매 틱 한 번씩 읽는다.

- "누른 순간"(pressed) / "누르고 있는 상태"(held) / "뗀 순간"(released) 구분
  : 공격은 pressed 로 한 번만, 이동·가드는 held 로 누르는 동안 계속
- 두 방향이 동시에 눌리면 대각선으로 해석, 좌+우 / 상+하 동시 입력은 중립 처리
- 틱 단위로 읽고, ``debounce_ticks`` 틱 연속 같은 값일 때만 상태를 바꿔 떨림(채터링)을 거른다
- 방향은 숫자패드 표기(1~9, 5=중립)로도 준다 -> 커맨드 입력 버퍼(WBS 2.5)에서 사용

    7 8 9      ↖ ↑ ↗
    4 5 6  =   ← · →
    1 2 3      ↙ ↓ ↘

    inp = InputReader()          # Pi : 본넷 GPIO
    def tick(n):
        st = inp.poll()
        if st.pressed_any("A"): ...
        dx, dy = st.direction    # dx -1/0/1 (왼/오), dy -1/0/1 (아래/위)
"""
UP, DOWN, LEFT, RIGHT, CENTER, A, B = "UP", "DOWN", "LEFT", "RIGHT", "CENTER", "A", "B"
BUTTONS = (UP, DOWN, LEFT, RIGHT, CENTER, A, B)

# 본넷 핀 (Adafruit 1.3" TFT Bonnet, 화면 rotation=180 기준 방향)
BONNET_PINS = {
    UP: "D17", DOWN: "D22", LEFT: "D27", RIGHT: "D23",
    CENTER: "D4", A: "D5", B: "D6",
}

_NUMPAD = {(-1, -1): 1, (0, -1): 2, (1, -1): 3,
           (-1, 0): 4, (0, 0): 5, (1, 0): 6,
           (-1, 1): 7, (0, 1): 8, (1, 1): 9}


class InputState:
    """한 틱의 입력 상태 (읽기 전용으로 쓸 것)."""

    __slots__ = ("tick", "held", "pressed", "released")

    def __init__(self, tick, held, pressed, released):
        self.tick = tick
        self.held = held            # frozenset : 지금 누르고 있는 버튼
        self.pressed = pressed      # frozenset : 이번 틱에 새로 눌린 버튼
        self.released = released    # frozenset : 이번 틱에 떨어진 버튼

    def is_held(self, b):
        return b in self.held

    def pressed_any(self, *bs):
        return any(b in self.pressed for b in bs)

    @property
    def direction(self):
        """(dx, dy). 반대 방향이 같이 눌리면 그 축은 0."""
        h = self.held
        dx = (RIGHT in h) - (LEFT in h)
        dy = (UP in h) - (DOWN in h)
        return dx, dy

    def numpad(self, facing=1):
        """숫자패드 방향. facing=-1(왼쪽을 봄)이면 좌우를 뒤집어 '앞=6'으로 맞춘다."""
        dx, dy = self.direction
        return _NUMPAD[(dx * facing, dy)]

    def __repr__(self):
        return "InputState(t=%d held=%s pressed=%s dir=%d)" % (
            self.tick, sorted(self.held), sorted(self.pressed), self.numpad())


class GpioBackend:
    """본넷 GPIO 읽기 (Blinka digitalio, 풀업 -> 누르면 False)."""

    def __init__(self, pins=None):
        import board
        import digitalio

        self._ios = []
        for name, pin in (pins or BONNET_PINS).items():
            io = digitalio.DigitalInOut(getattr(board, pin))
            io.direction = digitalio.Direction.INPUT
            io.pull = digitalio.Pull.UP
            self._ios.append((name, io))

    def read(self):
        return frozenset(name for name, io in self._ios if not io.value)

    def close(self):
        for _, io in self._ios:
            try:
                io.deinit()
            except Exception:
                pass
        self._ios = []


class ScriptBackend:
    """테스트·리플레이용 : 틱마다 눌린 버튼 집합을 차례로 돌려준다."""

    def __init__(self, frames):
        self._frames = [frozenset(f) for f in frames]
        self._i = 0

    def read(self):
        f = self._frames[self._i] if self._i < len(self._frames) else frozenset()
        self._i += 1
        return f

    def close(self):
        pass


class InputReader:
    def __init__(self, backend=None, debounce_ticks=1):
        """debounce_ticks : 이 틱 수만큼 연속으로 같은 값이어야 상태를 바꾼다.
        1이면 틱 샘플링(16.7ms 간격) 자체가 필터 역할을 하고 지연이 없다.
        2 이상이면 떨림에 더 강하지만 (n-1)틱만큼 늦게 반영된다."""
        self.backend = backend if backend is not None else GpioBackend()
        self.debounce = max(1, int(debounce_ticks))
        self._stable = frozenset()                  # 확정된 상태
        self._count = {b: 0 for b in BUTTONS}       # 확정 상태와 다른 값이 연속된 틱 수
        self._tick = -1
        self.state = InputState(-1, frozenset(), frozenset(), frozenset())

    def poll(self):
        """매 틱 한 번 호출. 이번 틱의 InputState 를 돌려준다."""
        raw = self.backend.read()
        self._tick += 1
        stable = set(self._stable)
        for b in BUTTONS:
            if (b in raw) != (b in self._stable):
                self._count[b] += 1
                if self._count[b] >= self.debounce:
                    stable.symmetric_difference_update((b,))
                    self._count[b] = 0
            else:
                self._count[b] = 0
        stable = frozenset(stable)
        self.state = InputState(self._tick, stable,
                                stable - self._stable, self._stable - stable)
        self._stable = stable
        return self.state

    def close(self):
        self.backend.close()
