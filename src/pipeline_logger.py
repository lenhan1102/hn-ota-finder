"""
pipeline_logger.py — Module logging tập trung cho toàn bộ pipeline NDC Leads Finder.

Mục đích:
  - Ghi log ra file với timestamp + job_id để debug khi pipeline bị treo ở Bước 4
  - Hỗ trợ watchdog phát hiện site nào treo, bước mấy, bao nhiêu giây
  - Log mức WARNING/ERROR được in rõ hơn để dễ thấy trong PM2

Cách dùng:
    from pipeline_logger import get_logger
    log = get_logger(job_id="abc123", log_dir="/app/logs")
    log.step_start(4, "Thẩm định website")
    log.site_start(1, 50, "vntravel.com")
    log.site_done(1, 50, "vntravel.com", elapsed=3.2, result="LOADED")
    log.site_hang(1, 50, "vntravel.com", elapsed=30.0)  # watchdog phát hiện treo
"""

import logging
import os
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


# Cấu hình mặc định
DEFAULT_LOG_DIR = Path(os.getenv("PIPELINE_LOG_DIR", "/app/logs"))
MAX_LOG_SIZE_MB = 20
BACKUP_COUNT = 5  # giữ 5 file log cũ xoay vòng


# Custom formatter: thêm màu khi chạy trực tiếp (không PM2)
_COLOR = {
    "DEBUG":    "\033[36m",   # cyan
    "INFO":     "\033[32m",   # green
    "WARNING":  "\033[33m",   # yellow
    "ERROR":    "\033[31m",   # red
    "CRITICAL": "\033[35m",   # magenta
    "RESET":    "\033[0m",
}


class _ColorFormatter(logging.Formatter):
    def format(self, record):
        color = _COLOR.get(record.levelname, "")
        reset = _COLOR["RESET"]
        record.levelname = f"{color}{record.levelname:<8}{reset}"
        return super().format(record)


class _PlainFormatter(logging.Formatter):
    pass


class PipelineLogger:
    """Logger chuyên dụng cho pipeline NDC Leads Finder."""

    def __init__(self, logger: logging.Logger, job_id: str = "", log_file: str = ""):
        self._logger = logger
        self.job_id = job_id
        self.log_file = log_file
        self._step = 0
        self._step_name = ""
        self._step_start = time.time()

    def debug(self, msg, *a, **kw):    self._logger.debug(self._fmt(msg), *a, **kw)
    def info(self, msg, *a, **kw):     self._logger.info(self._fmt(msg), *a, **kw)
    def warning(self, msg, *a, **kw):  self._logger.warning(self._fmt(msg), *a, **kw)
    def error(self, msg, *a, **kw):    self._logger.error(self._fmt(msg), *a, **kw)
    def critical(self, msg, *a, **kw): self._logger.critical(self._fmt(msg), *a, **kw)

    def _fmt(self, msg):
        prefix = f"[job={self.job_id}]" if self.job_id else ""
        step_tag = f"[B{self._step}/{self._step_name}]" if self._step else ""
        return f"{prefix}{step_tag} {msg}"

    def step_start(self, step: int, name: str):
        """Gọi khi bắt đầu một bước pipeline (1-5)."""
        self._step = step
        self._step_name = name
        self._step_start = time.time()
        self.info(f">> BAT DAU BUOC {step}: {name}")

    def step_done(self, step: int, name: str):
        """Gọi khi một bước pipeline kết thúc thành công."""
        elapsed = time.time() - self._step_start
        self.info(f"OK XONG BUOC {step}: {name} ({elapsed:.1f}s)")

    def step_error(self, step: int, name: str, exc: Exception):
        """Gọi khi một bước pipeline bị lỗi."""
        elapsed = time.time() - self._step_start
        self.error(f"FAIL BUOC {step}: {name} ({elapsed:.1f}s) -- {type(exc).__name__}: {exc}")

    def site_start(self, idx: int, total: int, domain: str):
        """Gọi ngay trước khi bắt đầu kiểm tra một website."""
        self.info(f"  START [{idx}/{total}] {domain}")

    def site_done(self, idx: int, total: int, domain: str, elapsed: float, result: str):
        """Gọi sau khi kiểm tra xong một website."""
        self.info(f"  DONE  [{idx}/{total}] {domain} | {result} ({elapsed:.1f}s)")

    def site_hang(self, idx: int, total: int, domain: str, elapsed: float):
        """Gọi khi watchdog phát hiện một site bị treo quá lâu."""
        self.warning(
            f"  WATCHDOG [{idx}/{total}] Site '{domain}' chua phan hoi sau {elapsed:.0f}s -- force-kill context!"
        )

    def site_skip(self, idx: int, total: int, domain: str, reason: str):
        """Gọi khi bỏ qua site (DNS lỗi...)."""
        self.info(f"  SKIP  [{idx}/{total}] {domain} | {reason}")

    def heartbeat(self, idx: int, total: int, elapsed_total: float):
        """Gọi định kỳ để xác nhận tiến trình còn sống."""
        self.info(f"  HEARTBEAT Buoc4: da xu ly {idx}/{total} site (tong {elapsed_total:.0f}s)")


# Cache logger theo key
_loggers: dict = {}


def get_logger(
    job_id: str = "",
    log_dir=None,
    level: str = "INFO",
) -> PipelineLogger:
    """
    Trả về PipelineLogger cho job_id.
    Lần đầu gọi sẽ tạo handler file + console.
    Các lần sau trả về instance đã cache.

    Args:
        job_id:  ID job (hoặc '' cho log chung)
        log_dir: Thư mục lưu log. Mặc định: $PIPELINE_LOG_DIR hoặc /app/logs
        level:   DEBUG / INFO / WARNING / ERROR
    """
    cache_key = f"{job_id}:{log_dir}:{level}"
    if cache_key in _loggers:
        return _loggers[cache_key]

    if log_dir is None:
        log_dir = DEFAULT_LOG_DIR
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    if job_id:
        log_filename = log_dir / f"pipeline_{job_id}.log"
    else:
        ts = datetime.now().strftime("%Y%m%d")
        log_filename = log_dir / f"pipeline_{ts}.log"

    logger_name = f"pipeline.{job_id or 'global'}"
    py_logger = logging.getLogger(logger_name)
    py_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    py_logger.propagate = False

    if not py_logger.handlers:
        fmt_str = "%(asctime)s %(levelname)-8s %(message)s"
        date_fmt = "%Y-%m-%d %H:%M:%S"

        # Handler 1: File rotating
        fh = RotatingFileHandler(
            log_filename,
            maxBytes=MAX_LOG_SIZE_MB * 1024 * 1024,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(_PlainFormatter(fmt_str, datefmt=date_fmt))
        fh.setLevel(logging.DEBUG)
        py_logger.addHandler(fh)

        # Handler 2: Console (màu nếu TTY)
        sh = logging.StreamHandler(sys.stdout)
        if sys.stdout.isatty():
            sh.setFormatter(_ColorFormatter(fmt_str, datefmt=date_fmt))
        else:
            sh.setFormatter(_PlainFormatter(fmt_str, datefmt=date_fmt))
        sh.setLevel(getattr(logging, level.upper(), logging.INFO))
        py_logger.addHandler(sh)

    pl = PipelineLogger(py_logger, job_id=job_id, log_file=str(log_filename))
    _loggers[cache_key] = pl

    py_logger.info(f"[pipeline_logger] Log file: {log_filename} (job_id={job_id!r}, level={level})")
    return pl
