"""요청 단위 request_id를 모든 로그 줄에 자동으로 붙인다.

미들웨어가 요청마다 set_request_id()를 호출하면, 같은 요청 안에서 남는 로그(app.chat, app.llm,
app.guardian, app.db 포함)는 메시지에 직접 쓰지 않아도 끝에 request_id=...가 붙는다.
contextvar라 동기 엔드포인트가 도는 스레드풀로도 값이 전달된다. 요청 밖(시작 시, 크론)은 "-".
"""
import contextvars
import logging
import time
import uuid

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
# 응답을 보낸 뒤에 할 일(가디언 즉시 분석 등). 요청마다 새 dict — 스레드풀로 넘어가도 같은 dict를 가리킨다
_pending: contextvars.ContextVar[dict | None] = contextvars.ContextVar("pending", default=None)
# 요청 마감 시각(time.monotonic 기준). 미들웨어가 요청마다 건다 — 바깥 호출은 남은 시간만큼만 기다린다
_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar("deadline", default=None)
LOG_FORMAT = "%(levelname)s %(message)s request_id=%(request_id)s"


def new_request_id() -> str:
    return uuid.uuid4().hex[:8]


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    return _request_id.get()


def start_deadline(seconds: float) -> None:
    _deadline.set(time.monotonic() + seconds)


def clear_deadline() -> None:
    """응답을 보낸 뒤의 일(가디언 분석 등)은 사용자가 기다리지 않으므로 요청 마감에 묶지 않는다."""
    _deadline.set(None)


def remaining(limit: float) -> float:
    """limit과 요청의 남은 시간 중 짧은 쪽 (요청 밖이면 limit). 0보다 작을 수 있다."""
    deadline = _deadline.get()
    return limit if deadline is None else min(limit, deadline - time.monotonic())


def start_pending() -> dict:
    value: dict = {}
    _pending.set(value)
    return value


def pending() -> dict | None:
    return _pending.get()


def install() -> None:
    """모든 LogRecord에 request_id 속성을 넣는다. 핸들러·로거 구성과 무관하게 동작한다 (중복 설치 안전)."""
    factory = logging.getLogRecordFactory()
    if getattr(factory, "_with_request_id", False):
        return

    def record_factory(*args, **kwargs):
        record = factory(*args, **kwargs)
        record.request_id = _request_id.get()
        return record

    record_factory._with_request_id = True
    logging.setLogRecordFactory(record_factory)
