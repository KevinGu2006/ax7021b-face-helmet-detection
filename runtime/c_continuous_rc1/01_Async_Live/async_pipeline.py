"""Small, auditable three-worker latest-frame pipeline; no PYNQ import.

Capture owns the camera. Detection owns gray DMA and FacePipeline. Display owns
Overlay/VDMA. Shared locks protect pointer swaps and short metrics writes only.
"""
from __future__ import annotations

from collections import deque
import csv
from dataclasses import dataclass
import json
import os
from pathlib import Path
import statistics
import threading
import time
from typing import Any, Callable


class RecoverableDetectionError(RuntimeError):
    """A Haar/API error after the DMA transaction has completed safely."""


class UnsafeHardwareState(RuntimeError):
    """A hardware owner cannot prove its DDR buffers are safe to release."""


@dataclass(frozen=True)
class FramePacket:
    frame_id: int
    captured_at: float
    capture_ms: float
    source_shape: tuple[int, int]
    image: Any
    analysis_shape: tuple[int, int] | None = None


@dataclass(frozen=True)
class DetectionOutput:
    boxes: tuple[tuple[int, int, int, int], ...]
    preprocess_ms: float
    pl_gray_dma_ms: float
    dma_wait_ms: float
    haar_ms: float
    draw_ms: float


@dataclass(frozen=True)
class DetectionResult:
    source_frame_id: int
    source_captured_at: float
    completed_at: float
    source_shape: tuple[int, int]
    boxes: tuple[tuple[int, int, int, int], ...]
    analysis_shape: tuple[int, int] | None = None


def classify_result(packet, result, now: float, max_age_ms: float):
    """Return visible result and explicit spatial/temporal provenance state."""
    if result is None or result.source_frame_id > packet.frame_id:
        return None, "none", None, None, None
    age_ms = (now - result.source_captured_at) * 1000
    publish_age_ms = (now - result.completed_at) * 1000
    gap = packet.frame_id - result.source_frame_id
    if result.source_shape != packet.source_shape:
        return None, "shape_mismatch", age_ms, publish_age_ms, gap
    if age_ms > max_age_ms:
        return None, "expired", age_ms, publish_age_ms, gap
    return result, ("matched" if gap == 0 else "delayed"), age_ms, publish_age_ms, gap


class LatestSlot:
    """Capacity one: publishing replaces the pending pointer, never appends."""

    def __init__(self):
        self._condition = threading.Condition()
        self._latest = None

    def publish(self, item) -> None:
        with self._condition:
            self._latest = item
            self._condition.notify_all()

    def get_after(self, last_id: int, timeout: float):
        with self._condition:
            self._condition.wait_for(
                lambda: self._latest is not None and
                self._latest.frame_id > last_id,
                timeout=timeout,
            )
            if self._latest is None or self._latest.frame_id <= last_id:
                return None
            return self._latest

    def peek(self):
        with self._condition:
            return self._latest

    def wake(self):
        with self._condition:
            self._condition.notify_all()

    @property
    def pending_count(self):
        return int(self.peek() is not None)


class ResultSlot:
    def __init__(self):
        self._lock = threading.Lock()
        self._latest = None

    def publish(self, result: DetectionResult) -> None:
        with self._lock:
            self._latest = result

    def peek(self):
        with self._lock:
            return self._latest


METRIC_NAMES = (
    "camera_capture_ms", "camera_frame_prepare_ms",
    "capture_to_display_latency_ms",
    "capture_to_detection_latency_ms", "detection_result_age_ms",
    "result_publish_age_ms", "resize_preprocess_ms", "pl_gray_dma_ms",
    "dma_wait_ms", "haar_detect_ms", "draw_ms", "hdmi_update_ms",
    "hdmi_frame_wait_ms",
)
CSV_FIELDS = (
    "kind", "elapsed_s", "frame_id", "source_frame_id",
    "camera_capture_ms", "camera_frame_prepare_ms",
    "capture_to_display_latency_ms",
    "capture_to_detection_latency_ms", "detection_result_age_ms",
    "result_publish_age_ms", "resize_preprocess_ms", "pl_gray_dma_ms",
    "dma_wait_ms", "haar_detect_ms", "draw_ms", "hdmi_update_ms",
    "hdmi_frame_wait_ms", "frame_gap", "boxes", "box_state", "drop_count",
    "detail",
)


def _percentiles(values):
    if not values:
        return {"mean": None, "median": None, "p95": None}
    ordered = sorted(values)
    pos = 0.95 * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return {
        "mean": round(statistics.fmean(ordered), 3),
        "median": round(statistics.median(ordered), 3),
        "p95": round(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo), 3),
    }


def _rss_kb():
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]
            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            get_current = ctypes.windll.kernel32.GetCurrentProcess
            get_current.restype = wintypes.HANDLE
            get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
            get_memory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            get_memory.restype = wintypes.BOOL
            if get_memory(
                get_current(), ctypes.byref(counters), counters.cb
            ):
                return int(counters.WorkingSetSize // 1024)
        except (AttributeError, OSError):
            pass
    return None


class Stats:
    """Bounded in-memory samples and a streamed event CSV."""

    def __init__(self, output_dir: Path, *, window=1000, flush_every=32):
        output_dir.mkdir(parents=True, exist_ok=False)
        self.output_dir = output_dir
        self._lock = threading.Lock()
        self._windows = {name: deque(maxlen=window) for name in METRIC_NAMES}
        self._resource_windows = {
            "cpu_percent_one_core": deque(maxlen=window),
            "rss_kb": deque(maxlen=window),
        }
        self._counts = {
            "camera_frames": 0, "detection_frames": 0, "hdmi_content_updates": 0,
            "detection_drop_count": 0, "preview_drop_count": 0,
            "camera_read_failures": 0, "camera_reconnect_count": 0,
            "worker_exception_count": 0, "dma_errors": 0, "vdma_errors": 0,
            "recoverable_detection_errors": 0, "stale_box_hidden_count": 0,
            "shape_mismatch_hidden_count": 0,
        }
        self._csv_file = (output_dir / "events.csv").open(
            "w", encoding="utf-8", newline=""
        )
        self._writer = csv.DictWriter(self._csv_file, fieldnames=CSV_FIELDS)
        self._writer.writeheader()
        self._flush_every = flush_every
        self._rows_written = 0
        self.started = None
        self.cpu_started = None
        self._last_resource_wall = None
        self._last_resource_cpu = None
        self.closed = False

    def start(self):
        self.started = time.perf_counter()
        self.cpu_started = time.process_time()
        self._last_resource_wall = self.started
        self._last_resource_cpu = self.cpu_started

    def count(self, name: str, amount: int = 1):
        with self._lock:
            self._counts[name] += amount

    def record(self, kind: str, **fields):
        now = time.perf_counter()
        row = {"kind": kind, "elapsed_s": round(now - self.started, 6)
               if self.started is not None else None}
        row.update(fields)
        with self._lock:
            for name in METRIC_NAMES:
                value = row.get(name)
                if value is not None:
                    self._windows[name].append(float(value))
            if kind == "capture":
                self._counts["camera_frames"] += 1
            elif kind == "detection":
                self._counts["detection_frames"] += 1
            elif kind == "display":
                self._counts["hdmi_content_updates"] += 1
            self._writer.writerow({key: row.get(key) for key in CSV_FIELDS})
            self._rows_written += 1
            if self._rows_written % self._flush_every == 0:
                self._csv_file.flush()

    def snapshot(self):
        now = time.perf_counter()
        cpu_now = time.process_time()
        rss = _rss_kb()
        with self._lock:
            counts = dict(self._counts)
            samples = {k: list(v) for k, v in self._windows.items()}
            rows_written = self._rows_written
            if self._last_resource_wall is not None:
                delta_wall = now - self._last_resource_wall
                if delta_wall > 0:
                    self._resource_windows["cpu_percent_one_core"].append(
                        100 * (cpu_now - self._last_resource_cpu) / delta_wall
                    )
                if rss is not None:
                    self._resource_windows["rss_kb"].append(rss)
                self._last_resource_wall = now
                self._last_resource_cpu = cpu_now
            resource_samples = {k: list(v) for k, v in self._resource_windows.items()}
        elapsed = max(now - self.started, 1e-9) if self.started is not None else 0
        cpu_elapsed = cpu_now - self.cpu_started if self.cpu_started is not None else 0
        return {
            "wall_elapsed_s": round(elapsed, 3),
            **counts,
            "camera_capture_fps": round(counts["camera_frames"] / elapsed, 3) if elapsed else 0,
            "detection_fps": round(counts["detection_frames"] / elapsed, 3) if elapsed else 0,
            "hdmi_content_update_fps": round(counts["hdmi_content_updates"] / elapsed, 3) if elapsed else 0,
            "cpu_percent_one_core": round(100 * cpu_elapsed / elapsed, 2) if elapsed else 0,
            "rss_kb": rss,
            "resource_stats": {k: _percentiles(v) for k, v in resource_samples.items()},
            "metric_window": max((len(v) for v in samples.values()), default=0),
            "metrics_ms": {k: _percentiles(v) for k, v in samples.items()},
            "events_written": rows_written,
            "timing_notes": {
                "dma_wait_ms": "Upper bound: entire ReusableGrayDMA call; includes pack, flush, transfer and wait",
                "hdmi_frame_wait_ms": "Upper bound: entire verified Display.show call; includes copy, flush, park and wait",
                "detection_result_age_ms": "Age of source capture at HDMI update, not age since publication",
            },
        }

    def save(self):
        data = self.snapshot()
        path = self.output_dir / "summary.json"
        tmp = self.output_dir / "summary.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        with self._lock:
            self._csv_file.flush()
        return data

    def close(self):
        if self.closed:
            return self.snapshot()
        data = self.save()
        with self._lock:
            self._csv_file.close()
            self.closed = True
        return data


class AsyncEngine:
    """Coordinates three owners without holding shared locks during hardware calls."""

    def __init__(
        self,
        *,
        camera_factory: Callable[[], Any],
        detector_factory: Callable[[Any], Any],
        display_factory: Callable[[], Any],
        renderer: Callable[[FramePacket, DetectionResult | None, str, float | None], Any],
        stats: Stats,
        logger,
        frame_owner: Callable[[Any], Any] | None = None,
        max_capture_frames: int = 0,
        max_seconds: float = 0,
        max_result_age_ms: float = 1600,
        read_fail_before_reopen: int = 3,
        max_camera_reopens: int = 3,
        max_detection_errors: int = 5,
        join_timeout: float = 15,
        report_interval: float = 5,
    ):
        self.camera_factory = camera_factory
        self.detector_factory = detector_factory
        self.display_factory = display_factory
        self.renderer = renderer
        self.stats = stats
        self.log = logger
        self.frame_owner = frame_owner or self._copy_owned
        self.max_capture_frames = max_capture_frames
        self.max_seconds = max_seconds
        self.max_result_age_ms = max_result_age_ms
        self.read_fail_before_reopen = read_fail_before_reopen
        self.max_camera_reopens = max_camera_reopens
        self.max_detection_errors = max_detection_errors
        self.join_timeout = join_timeout
        self.report_interval = report_interval
        self.frames = LatestSlot()
        self.results = ResultSlot()
        self.stop_event = threading.Event()
        self.capture_done = threading.Event()
        self.detector_done = threading.Event()
        self.display_done = threading.Event()
        self.capture_ready = threading.Event()
        self.detector_ready = threading.Event()
        self.display_ready = threading.Event()
        self.display = None
        self.detector = None
        self.camera = None
        self.errors = []
        self.unsafe_resources = []
        self.threads = {}

    @staticmethod
    def _copy_owned(image):
        owned = image.copy()
        if hasattr(owned, "setflags"):
            owned.setflags(write=False)
        return owned

    def request_stop(self):
        self.stop_event.set()
        self.frames.wake()

    def _fail(self, worker, error):
        self.errors.append((worker, repr(error)))
        self.stats.count("worker_exception_count")
        self.stats.record("worker_error", detail=f"{worker}: {error!r}")
        self.log.exception("%s worker failed", worker)
        self.request_stop()

    def _capture(self):
        camera = None
        consecutive = 0
        next_id = 1
        try:
            camera = self.camera_factory()
            self.camera = camera
            self.capture_ready.set()
            while not self.stop_event.is_set():
                if self.max_capture_frames and next_id > self.max_capture_frames:
                    break
                if self.max_seconds and time.perf_counter() - self.stats.started >= self.max_seconds:
                    break
                start = time.perf_counter()
                try:
                    okay, raw = camera.read()
                except Exception as exc:
                    okay, raw = False, None
                    self.stats.record("camera_read_exception", detail=repr(exc))
                if not okay or raw is None:
                    consecutive += 1
                    self.stats.count("camera_read_failures")
                    self.stats.record("camera_read_failure", detail=consecutive)
                    if consecutive >= self.read_fail_before_reopen:
                        if self.stats.snapshot()["camera_reconnect_count"] >= self.max_camera_reopens:
                            raise RuntimeError("Camera reconnect attempts exhausted")
                        camera.release()
                        camera = self.camera_factory()
                        self.camera = camera
                        self.stats.count("camera_reconnect_count")
                        self.stats.record("camera_reconnected")
                        consecutive = 0
                    else:
                        self.stop_event.wait(0.1)
                    continue
                consecutive = 0
                captured = time.perf_counter()
                source_shape = tuple(raw.shape[:2])
                owned = self.frame_owner(raw)
                ready = time.perf_counter()
                packet = FramePacket(
                    next_id, captured, (captured - start) * 1000,
                    source_shape, owned, tuple(owned.shape[:2]),
                )
                self.frames.publish(packet)
                self.stats.record("capture", frame_id=next_id,
                                  camera_capture_ms=packet.capture_ms,
                                  camera_frame_prepare_ms=(ready - captured) * 1000)
                next_id += 1
        except Exception as exc:
            self._fail("capture", exc)
        finally:
            self.capture_ready.set()
            if camera is not None:
                try:
                    camera.release()
                except Exception as exc:
                    self._fail("capture_release", exc)
            self.capture_done.set()
            self.frames.wake()

    def _detect(self):
        detector = None
        last_id = 0
        consecutive_errors = 0
        diagnostic_logged = False
        try:
            detector = self.detector_factory(self.display.overlay)
            self.detector = detector
            self.detector_ready.set()
            while not self.stop_event.is_set():
                packet = self.frames.get_after(last_id, 0.1)
                if packet is None:
                    if self.capture_done.is_set():
                        break
                    continue
                skipped = max(0, packet.frame_id - last_id - 1)
                if skipped:
                    self.stats.count("detection_drop_count", skipped)
                    self.stats.record("detection_drop", frame_id=packet.frame_id,
                                      drop_count=skipped)
                last_id = packet.frame_id
                try:
                    output = detector.process(packet)
                except RecoverableDetectionError as exc:
                    consecutive_errors += 1
                    self.stats.count("recoverable_detection_errors")
                    self.stats.record("detection_error", frame_id=packet.frame_id,
                                      detail=repr(exc))
                    if consecutive_errors >= self.max_detection_errors:
                        raise RuntimeError("Repeated Haar detection errors") from exc
                    continue
                consecutive_errors = 0
                complete = time.perf_counter()
                result = DetectionResult(
                    packet.frame_id, packet.captured_at, complete,
                    packet.source_shape, tuple(output.boxes),
                    packet.analysis_shape,
                )
                self.results.publish(result)
                diagnostic = getattr(detector, "last_diagnostic", None)
                if diagnostic and not diagnostic_logged:
                    self.stats.record("first_pl_dma_diagnostic", frame_id=packet.frame_id,
                                      detail=json.dumps(diagnostic, default=str))
                    diagnostic_logged = True
                self.stats.record(
                    "detection", frame_id=packet.frame_id,
                    source_frame_id=packet.frame_id,
                    capture_to_detection_latency_ms=(complete - packet.captured_at) * 1000,
                    resize_preprocess_ms=output.preprocess_ms,
                    pl_gray_dma_ms=output.pl_gray_dma_ms,
                    dma_wait_ms=output.dma_wait_ms,
                    haar_detect_ms=output.haar_ms,
                    draw_ms=output.draw_ms,
                    boxes=len(result.boxes),
                )
        except Exception as exc:
            if "DMA" in repr(exc) or isinstance(exc, TimeoutError):
                self.stats.count("dma_errors")
            if detector is not None and getattr(detector, "provider", None) is not None:
                self.stats.record(
                    "dma_failure_diagnostic",
                    detail=json.dumps(detector.provider.last_diagnostic, default=str),
                )
            self._fail("detection", exc)
        finally:
            self.detector_ready.set()
            if detector is not None:
                try:
                    detector.close()
                except UnsafeHardwareState as exc:
                    self.unsafe_resources.append(("dma", repr(exc)))
                    self.stats.record("unsafe_dma", detail=repr(exc))
                except Exception as exc:
                    self.unsafe_resources.append(("dma_close", repr(exc)))
                    self.stats.record("unsafe_dma", detail=repr(exc))
            self.detector_done.set()

    def _display(self):
        display = None
        last_id = 0
        try:
            display = self.display_factory()
            self.display = display
            self.display_ready.set()
            while not self.stop_event.is_set():
                packet = self.frames.get_after(last_id, 0.1)
                if packet is None:
                    if self.capture_done.is_set():
                        break
                    continue
                skipped = max(0, packet.frame_id - last_id - 1)
                if skipped:
                    self.stats.count("preview_drop_count", skipped)
                    self.stats.record("preview_drop", frame_id=packet.frame_id,
                                      drop_count=skipped)
                last_id = packet.frame_id
                result = self.results.peek()
                now = time.perf_counter()
                visible, box_state, result_age_ms, publish_age_ms, gap = classify_result(
                    packet, result, now, self.max_result_age_ms
                )
                if box_state == "expired":
                    self.stats.count("stale_box_hidden_count")
                elif box_state == "shape_mismatch":
                    self.stats.count("shape_mismatch_hidden_count")
                rendered = self.renderer(packet, visible, box_state, result_age_ms)
                started_show = time.perf_counter()
                try:
                    display.show(rendered)
                    completed = time.perf_counter()
                    if hasattr(display, "snapshot"):
                        state = display.snapshot()
                        if state.get("vdma", {}).get("error") or state.get("vdma", {}).get("halted"):
                            raise RuntimeError(f"VDMA status after show: {state['vdma']}")
                except Exception:
                    self.stats.count("vdma_errors")
                    raise
                show_ms = (completed - started_show) * 1000
                self.stats.record(
                    "display", frame_id=packet.frame_id,
                    source_frame_id=result.source_frame_id if result else None,
                    capture_to_display_latency_ms=(completed - packet.captured_at) * 1000,
                    detection_result_age_ms=result_age_ms,
                    result_publish_age_ms=publish_age_ms,
                    hdmi_update_ms=show_ms,
                    hdmi_frame_wait_ms=show_ms,
                    frame_gap=gap,
                    boxes=len(visible.boxes) if visible else 0,
                    box_state=box_state,
                )
        except Exception as exc:
            self._fail("display", exc)
        finally:
            self.display_ready.set()
            if display is not None:
                try:
                    display.stop()
                except Exception as exc:
                    self.unsafe_resources.append(("vdma", repr(exc)))
                    self.stats.record("unsafe_vdma", detail=repr(exc))
            self.display_done.set()

    def _start_thread(self, name, target):
        thread = threading.Thread(target=target, name=name, daemon=False)
        self.threads[name] = thread
        thread.start()

    def run(self):
        self._start_thread("hdmi-display", self._display)
        if not self.display_ready.wait(20) or self.display is None or self.stop_event.is_set():
            self.request_stop()
            return self._finish()
        self._start_thread("face-detection", self._detect)
        if not self.detector_ready.wait(20) or self.detector is None or self.stop_event.is_set():
            self.request_stop()
            return self._finish()
        self.stats.start()
        self._start_thread("camera-capture", self._capture)
        if not self.capture_ready.wait(10) or self.camera is None:
            self.request_stop()
        next_report = time.perf_counter() + self.report_interval
        while True:
            if self.stop_event.is_set():
                break
            if self.capture_done.is_set() and self.detector_done.is_set() and self.display_done.is_set():
                break
            now = time.perf_counter()
            if now >= next_report:
                state = self.stats.save()
                self.log.info(
                    "capture_fps=%.2f detect_fps=%.2f hdmi_fps=%.2f "
                    "det_drop=%d preview_drop=%d rss_kb=%s",
                    state["camera_capture_fps"], state["detection_fps"],
                    state["hdmi_content_update_fps"],
                    state["detection_drop_count"], state["preview_drop_count"],
                    state["rss_kb"],
                )
                next_report = now + self.report_interval
            self.stop_event.wait(0.05)
        return self._finish()

    def _finish(self):
        if self.stop_event.is_set():
            self.frames.wake()
        for name in ("camera-capture", "face-detection", "hdmi-display"):
            thread = self.threads.get(name)
            if thread is not None:
                thread.join(timeout=self.join_timeout)
        alive = [name for name, thread in self.threads.items() if thread.is_alive()]
        if alive:
            self.unsafe_resources.append(("threads_still_active", alive))
            return {"thread_alive": alive, "unsafe_resources": list(self.unsafe_resources),
                    "errors": list(self.errors), "summary": self.stats.snapshot()}
        summary = self.stats.close()
        return {"thread_alive": [], "unsafe_resources": list(self.unsafe_resources),
                "errors": list(self.errors), "summary": summary}
