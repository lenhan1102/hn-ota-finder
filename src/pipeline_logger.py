"""
pipeline_logger.py — Module logging cho pipeline NDC Leads Finder.

Chiến lược lưu log:
  - KHÔNG ghi ra file (tránh đầy disk server)
  - Ghi ra stdout/stderr (PM2 capture, tự rotate)
  - In-memory ring buffer (max 500 entries) chỉ lưu WARNING + ERROR
  - Expose qua hidden API endpoint /api/_dbg/pipeline-errors (chỉ dev biết)
"""

import logging
import os
import sys
import time
from collections import deque
from datetime import datetime

# Guarantee singleton across 'pipeline_logger' and 'src.pipeline_logger'
if __name__ in sys.modules:
    sys.modules.setdefault("pipeline_logger", sys.modules[__name__])
    sys.modules.setdefault("src.pipeline_logger", sys.modules[__name__])

# ─── Ring Buffer toàn cục — chỉ lưu WARNING + ERROR ─────────────────────────
_MAX_ENTRIES = int(os.getenv("PIPELINE_LOG_MAX_ENTRIES", "500"))
_error_ring: deque = deque(maxlen=_MAX_ENTRIES)


def get_error_log() -> list:
    """Trả về danh sách log lỗi hiện có trong ring buffer (mới nhất ở cuối)."""
    return list(_error_ring)


def clear_error_log():
    """Xóa toàn bộ ring buffer (dùng khi restart test)."""
    _error_ring.clear()


# ─── Custom Handler: ghi WARNING+ vào ring buffer ────────────────────────────
class _RingBufferHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)

    def emit(self, record: logging.LogRecord):
        try:
            raw_msg = str(getattr(record, "msg", ""))
            job_id = getattr(record, "job_id", "")
            if not job_id and raw_msg:
                import re
                m = re.search(r"\[job=([^\]]+)\]", raw_msg)
                if m:
                    job_id = m.group(1)

            step = getattr(record, "step", 0)
            step_name = getattr(record, "step_name", "")
            if (not step or not step_name) and raw_msg:
                import re
                m = re.search(r"\[B(\d+)/([^\]]+)\]", raw_msg)
                if m:
                    step = int(m.group(1))
                    step_name = m.group(2)

            _error_ring.append({
                "ts": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "msg": self.format(record),
                "job_id": job_id,
                "step": step,
                "step_name": step_name,
            })
        except Exception:
            pass


# ─── PipelineLogger wrapper ───────────────────────────────────────────────────
class PipelineLogger:
    """Logger chuyên dụng cho pipeline NDC Leads Finder."""

    def __init__(self, logger: logging.Logger, job_id: str = ""):
        self._logger = logger
        self.job_id = job_id
        self.log_file = ""   # Không dùng file — giữ attribute để tương thích
        self._step = 0
        self._step_name = ""
        self._step_start = time.time()

    def _extra(self, kw):
        kw_copy = dict(kw)
        extra = kw_copy.setdefault("extra", {})
        extra.setdefault("job_id", self.job_id)
        extra.setdefault("step", self._step)
        extra.setdefault("step_name", self._step_name)
        return kw_copy

    def debug(self, msg, *a, **kw):    self._logger.debug(self._fmt(msg), *a, **self._extra(kw))
    def info(self, msg, *a, **kw):     self._logger.info(self._fmt(msg), *a, **self._extra(kw))
    def warning(self, msg, *a, **kw):  self._logger.warning(self._fmt(msg), *a, **self._extra(kw))
    def error(self, msg, *a, **kw):    self._logger.error(self._fmt(msg), *a, **self._extra(kw))
    def critical(self, msg, *a, **kw): self._logger.critical(self._fmt(msg), *a, **self._extra(kw))

    def _fmt(self, msg):
        prefix = f"[job={self.job_id}]" if self.job_id else ""
        step_tag = f"[B{self._step}/{self._step_name}]" if self._step else ""
        return f"{prefix}{step_tag} {msg}"

    def step_start(self, step: int, name: str):
        self._step = step
        self._step_name = name
        self._step_start = time.time()
        self.info(f">> BAT DAU BUOC {step}: {name}")

    def step_done(self, step: int, name: str):
        elapsed = time.time() - self._step_start
        self.info(f"OK XONG BUOC {step}: {name} ({elapsed:.1f}s)")

    def step_error(self, step: int, name: str, exc: Exception):
        elapsed = time.time() - self._step_start
        self.error(f"FAIL BUOC {step}: {name} ({elapsed:.1f}s) -- {type(exc).__name__}: {exc}")

    def site_start(self, idx: int, total: int, domain: str):
        self.info(f"  START [{idx}/{total}] {domain}")

    def site_done(self, idx: int, total: int, domain: str, elapsed: float, result: str):
        # Chỉ log DEAD vào WARNING để FE xem được
        if "DEAD" in result or "WATCHDOG" in result:
            self.warning(f"  DEAD [{idx}/{total}] {domain} | {result} ({elapsed:.1f}s)")
        else:
            self.info(f"  DONE [{idx}/{total}] {domain} | {result} ({elapsed:.1f}s)")

    def site_hang(self, idx: int, total: int, domain: str, elapsed: float):
        self.warning(
            f"  WATCHDOG [{idx}/{total}] Site '{domain}' treo {elapsed:.0f}s -- force-kill!"
        )

    def site_skip(self, idx: int, total: int, domain: str, reason: str):
        self.info(f"  SKIP [{idx}/{total}] {domain} | {reason}")

    def heartbeat(self, idx: int, total: int, elapsed_total: float):
        self.info(f"  HEARTBEAT B4: {idx}/{total} site ({elapsed_total:.0f}s)")


# ─── Factory / Cache ──────────────────────────────────────────────────────────
_loggers: dict = {}


def get_logger(
    job_id: str = "",
    log_dir=None,    # Bỏ qua — không còn dùng file
    level: str = "INFO",
) -> PipelineLogger:
    """
    Trả về PipelineLogger cho job_id.
    Log được ghi ra stdout (PM2 capture) và ring buffer (WARNING+ only).
    """
    cache_key = f"{job_id}:{level}"
    if cache_key in _loggers:
        return _loggers[cache_key]

    logger_name = f"pipeline.{job_id or 'global'}"
    py_logger = logging.getLogger(logger_name)
    py_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    py_logger.propagate = False

    if not py_logger.handlers:
        fmt_str = "%(asctime)s %(levelname)-8s %(message)s"
        date_fmt = "%Y-%m-%d %H:%M:%S"
        plain_fmt = logging.Formatter(fmt_str, datefmt=date_fmt)

        # Handler 1: stdout (PM2 tự rotate, không tốn disk thêm)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(plain_fmt)
        sh.setLevel(getattr(logging, level.upper(), logging.INFO))
        py_logger.addHandler(sh)

        # Handler 2: Ring buffer (chỉ WARNING+)
        rb = _RingBufferHandler()
        rb.setFormatter(plain_fmt)
        py_logger.addHandler(rb)

    pl = PipelineLogger(py_logger, job_id=job_id)
    _loggers[cache_key] = pl
    return pl
