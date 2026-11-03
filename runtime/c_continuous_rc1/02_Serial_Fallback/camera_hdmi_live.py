"""Continuous AX7021B camera -> PL gray DMA -> FacePipeline -> HDMI.

The verified A modules own hardware: a_hdmi.Display controls the combined
Overlay/VDMA, and a_gray_dma_fast.ReusableGrayDMA controls the gray DMA.
This application creates each owner once. Importing this module touches no
hardware. The Linux board must be free of the original hdmi_worker process.
"""
from __future__ import annotations

import argparse
from collections import deque
import csv
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import statistics
import sys
import time
from typing import Any, Callable

APP_ROOT = Path(__file__).resolve().parent
DEFAULT_HDMI_ROOT = Path("/home/xilinx/A_hdmi_integration_20261029")
DEFAULT_GRAY_ROOT = Path("/home/xilinx/A_C_gray_hardware_20261028")
DEFAULT_INTEGRATION_ROOT = Path("/home/xilinx/A_C_gray_integration_20261028")
DEFAULT_FACE_ROOT = Path("/home/xilinx/A_B_integration_20261028")
FIELDS = (
    "frame", "elapsed_s", "backend", "camera_capture_ms",
    "resize_preprocess_ms", "pl_gray_dma_ms", "haar_detect_ms",
    "draw_ms", "hdmi_update_ms", "total_frame_ms", "face_count",
    "detection_error", "display_updated",
)
STAGES = FIELDS[3:10]


def ms_since(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    pos = 0.95 * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def current_rss_kb() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


class SingleInstance:
    """Use exactly the worker's controller.lock on Linux; release on exit."""

    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def __enter__(self):
        self.file = self.path.open("a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise RuntimeError(
                "HDMI controller lock is held. Stop hdmi_worker.py or another "
                "live instance before starting this program."
            )
        return self

    def __exit__(self, *_):
        if self.file is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.file.seek(0)
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file, fcntl.LOCK_UN)
            finally:
                self.file.close()
                self.file = None


class Metrics:
    """Stream every row to CSV; keep only a bounded window in memory."""

    def __init__(self, run_dir: Path, backend: str, every: int, window: int):
        run_dir.mkdir(parents=True, exist_ok=False)
        self.run_dir = run_dir
        self.backend = backend
        self.every = every
        self.rows = deque(maxlen=window)
        self.csv_file = (run_dir / "frames.csv").open("w", newline="", encoding="utf-8")
        self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=FIELDS)
        self.csv_writer.writeheader()
        self.events = (run_dir / "events.jsonl").open("w", encoding="utf-8")
        self.started = time.perf_counter()
        self.frames = 0
        self.detected = 0
        self.displayed = 0
        self.camera_failures = 0
        self.camera_reopens = 0
        self.detection_errors = 0
        self.dma_errors = 0
        self.vdma_errors = 0
        self.last_summary: dict[str, Any] = {}

    def event(self, kind: str, detail: Any) -> None:
        self.events.write(json.dumps(
            {"elapsed_s": round(time.perf_counter() - self.started, 3),
             "kind": kind, "detail": detail},
            ensure_ascii=False, default=str,
        ) + "\n")
        self.events.flush()

    def record(self, row: dict[str, Any], detection_ok: bool) -> None:
        self.frames += 1
        self.detected += int(detection_ok)
        self.displayed += int(bool(row["display_updated"]))
        self.rows.append(row)
        self.csv_writer.writerow(row)
        self.csv_file.flush()
        if self.frames % self.every == 0:
            self.save_summary()

    def summary(self) -> dict[str, Any]:
        elapsed = max(time.perf_counter() - self.started, 1e-9)
        stages = {}
        for key in STAGES:
            values = [float(r[key]) for r in self.rows]
            stages[key] = {
                "mean_ms": round(statistics.fmean(values), 3) if values else 0.0,
                "median_ms": round(statistics.median(values), 3) if values else 0.0,
                "p95_ms": round(p95(values), 3),
            }
        return {
            "backend": self.backend,
            "processed_frames": self.frames,
            "successful_detection_frames": self.detected,
            "hdmi_updates": self.displayed,
            "continuous_elapsed_s": round(elapsed, 3),
            "actual_detection_fps": round(self.detected / elapsed, 3),
            "actual_hdmi_update_fps": round(self.displayed / elapsed, 3),
            "stage_window_frames": len(self.rows),
            "stages": stages,
            "camera_read_failures": self.camera_failures,
            "camera_reopens": self.camera_reopens,
            "detection_errors": self.detection_errors,
            "dma_errors": self.dma_errors,
            "vdma_errors": self.vdma_errors,
            "rss_kb": current_rss_kb(),
        }

    def save_summary(self) -> dict[str, Any]:
        data = self.summary()
        tmp = self.run_dir / "summary.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.run_dir / "summary.json")
        self.last_summary = data
        return data

    def close(self) -> dict[str, Any]:
        data = self.save_summary()
        self.csv_file.close()
        self.events.close()
        return data


def letterbox_bgr(frame, cv2_module, width=800, height=600):
    """Map camera BGR to 800x600 while keeping detection/display coordinates equal."""
    import numpy as np
    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8:
        raise ValueError("Camera must produce uint8 BGR")
    if frame.ndim != 3 or frame.shape[2] != 3 or min(frame.shape[:2]) < 2:
        raise ValueError("Camera must produce nonempty HxWx3 BGR")
    h, w = frame.shape[:2]
    if (w, h) == (width, height):
        return np.ascontiguousarray(frame)
    scale = min(width / w, height / h)
    rw = max(1, min(width, round(w * scale)))
    rh = max(1, min(height, round(h * scale)))
    resized = cv2_module.resize(frame, (rw, rh), interpolation=cv2_module.INTER_LINEAR)
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x = (width - rw) // 2
    y = (height - rh) // 2
    canvas[y:y + rh, x:x + rw] = resized
    return canvas


def camera_open(cv2_module, device: str, width: int, height: int):
    target = int(device) if device.isdigit() else device
    if sys.platform.startswith("linux") and hasattr(cv2_module, "CAP_V4L2"):
        cap = cv2_module.VideoCapture(target, cv2_module.CAP_V4L2)
    else:
        cap = cv2_module.VideoCapture(target)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Camera {device} could not be opened")
    cap.set(cv2_module.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2_module.CAP_PROP_FRAME_HEIGHT, height)
    if hasattr(cv2_module, "CAP_PROP_BUFFERSIZE"):
        cap.set(cv2_module.CAP_PROP_BUFFERSIZE, 1)
    return cap

class CameraOwner:
    """Retain the current capture object across a bounded reopen."""

    def __init__(self, factory: Callable[[], Any]):
        self.factory = factory
        self.cap = factory()

    def read(self):
        return self.cap.read()

    def reopen(self):
        self.cap.release()
        self.cap = self.factory()

    def release(self):
        self.cap.release()


def verify_hardware_files(hdmi_root: Path, baseline: Path) -> dict[str, str]:
    expected = json.loads(baseline.read_text(encoding="utf-8"))
    result = {}
    for name in ("HDMI_CANDIDATE.bit", "HDMI_CANDIDATE.hwh"):
        file = hdmi_root / name
        if not file.is_file():
            raise FileNotFoundError(f"Verified hardware file missing: {file}")
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        if digest != expected[name]["sha256"]:
            raise RuntimeError(f"Hardware SHA256 mismatch: {file}")
        result[name] = digest
    return result


def validate_hardware_owners(display, provider, backend: str) -> None:
    if not hasattr(display, "show") or not hasattr(display, "stop"):
        raise RuntimeError("Display API mismatch")
    overlay = display.overlay
    expected = {"axi_dma_0": 0x40400000, "axi_vdma_0": 0x43000000}
    for name, addr in expected.items():
        item = overlay.ip_dict.get(name)
        if item is None or int(item["phys_addr"]) != addr:
            raise RuntimeError(f"Combined Overlay IP mapping mismatch: {name}")
    if backend == "pl" and provider is None:
        raise RuntimeError("PL mode requires ReusableGrayDMA")


def run_loop(
    camera,
    display,
    provider,
    pipeline,
    cv2_module,
    metrics: Metrics,
    *,
    backend: str,
    stop_requested: Callable[[], bool],
    max_frames: int,
    max_seconds: float,
    read_fail_before_reopen: int,
    max_camera_reopens: int,
    max_detection_errors: int,
    log: logging.Logger,
) -> Any:
    """Serial loop; caller owns initialization, lock and safe cleanup."""
    if backend not in ("pl", "cpu"):
        raise ValueError("backend must be pl or cpu")
    if backend == "pl" and provider is None:
        raise ValueError("PL mode requires provider")
    consecutive_camera_failures = 0
    consecutive_detection_errors = 0
    started = metrics.started
    while not stop_requested():
        if max_frames and metrics.frames >= max_frames:
            break
        if max_seconds and time.perf_counter() - started >= max_seconds:
            break
        frame_start = time.perf_counter()
        try:
            ok, frame = camera.read()
        except Exception as exc:
            ok, frame = False, None
            metrics.event("camera_read_exception", repr(exc))
        capture_ms = ms_since(frame_start)
        if not ok or frame is None:
            metrics.camera_failures += 1
            consecutive_camera_failures += 1
            metrics.event("camera_read_failure", {"consecutive": consecutive_camera_failures})
            log.warning("Camera read failed (%d consecutive)", consecutive_camera_failures)
            if consecutive_camera_failures >= read_fail_before_reopen:
                if metrics.camera_reopens >= max_camera_reopens:
                    raise RuntimeError("Camera recovery attempts exhausted")
                camera.reopen()
                metrics.camera_reopens += 1
                consecutive_camera_failures = 0
                metrics.event("camera_reopened", metrics.camera_reopens)
            else:
                time.sleep(0.1)
            continue
        consecutive_camera_failures = 0

        t = time.perf_counter()
        prepared = letterbox_bgr(frame, cv2_module)
        small = pipeline.detector.prepare_bgr_for_pl(prepared) if backend == "pl" else None
        preprocess_ms = ms_since(t)

        gray_ms = 0.0
        if backend == "pl":
            t = time.perf_counter()
            try:
                gray = provider(small)
                diagnostic = getattr(provider, "last_diagnostic", None) or {}
                if diagnostic.get("reused_buffers") is False:
                    raise RuntimeError("Gray DMA DDR buffers were reallocated during live loop")
            except Exception as exc:
                metrics.dma_errors += 1
                metrics.event("dma_error", {
                    "exception": repr(exc),
                    "status": getattr(provider, "last_diagnostic", None),
                })
                raise
            gray_ms = ms_since(t)

        detection_ok = True
        detection_error = ""
        t = time.perf_counter()
        try:
            if backend == "pl":
                annotated, record = pipeline.process_frame(
                    prepared, gray, original_shape=prepared.shape[:2],
                    gray_execution_backend="ZYNQ_PL",
                )
            else:
                annotated, record = pipeline.process_frame(prepared)
            face_ms = float(record["timings_ms"]["face"])
            draw_ms = float(record["timings_ms"]["render"])
            face_count = int(record["face_count"])
            consecutive_detection_errors = 0
        except Exception as exc:
            detection_ok = False
            detection_error = repr(exc)
            face_ms = ms_since(t)
            annotated = prepared
            draw_ms = 0.0
            face_count = 0
            consecutive_detection_errors += 1
            metrics.detection_errors += 1
            metrics.event("detection_error", detection_error)
            log.exception("Face detection failed; displaying the current camera frame")
        if detection_ok and backend == "pl" and (
            not record.get("external_gray") or
            record.get("execution_backend", {}).get("gray") != "ZYNQ_PL"
        ):
            raise RuntimeError("FacePipeline did not use the PL gray image")
        t = time.perf_counter()
        try:
            display.show(annotated)
            snapshot = display.snapshot()
            if snapshot["vdma"]["error"] or snapshot["vdma"]["halted"]:
                raise RuntimeError(f"VDMA state after update: {snapshot['vdma']}")
        except Exception as exc:
            metrics.vdma_errors += 1
            metrics.event("vdma_error", repr(exc))
            raise
        hdmi_ms = ms_since(t)
        row = {
            "frame": metrics.frames + 1,
            "elapsed_s": round(time.perf_counter() - metrics.started, 6),
            "backend": backend,
            "camera_capture_ms": round(capture_ms, 3),
            "resize_preprocess_ms": round(preprocess_ms, 3),
            "pl_gray_dma_ms": round(gray_ms, 3),
            "haar_detect_ms": round(face_ms, 3),
            "draw_ms": round(draw_ms, 3),
            "hdmi_update_ms": round(hdmi_ms, 3),
            "total_frame_ms": round(ms_since(frame_start), 3),
            "face_count": face_count,
            "detection_error": detection_error,
            "display_updated": 1,
        }
        metrics.record(row, detection_ok)
        if metrics.frames % metrics.every == 0:
            summary = metrics.last_summary
            log.info(
                "frames=%d elapsed=%.1fs detect_fps=%.2f hdmi_fps=%.2f "
                "haar_p95=%.1fms dma_p95=%.1fms hdmi_p95=%.1fms "
                "camera_fail=%d dma_err=%d vdma_err=%d rss_kb=%s",
                metrics.frames, summary["continuous_elapsed_s"],
                summary["actual_detection_fps"], summary["actual_hdmi_update_fps"],
                summary["stages"]["haar_detect_ms"]["p95_ms"],
                summary["stages"]["pl_gray_dma_ms"]["p95_ms"],
                summary["stages"]["hdmi_update_ms"]["p95_ms"],
                metrics.camera_failures, metrics.dma_errors, metrics.vdma_errors,
                summary["rss_kb"],
            )
        if consecutive_detection_errors >= max_detection_errors:
            raise RuntimeError("Repeated face detection failures; preserving last HDMI frame")
    return None


def hold_unsafe(provider, display, log: logging.Logger) -> None:
    """Never let Linux reclaim DDR while a DMA/VDMA might still own it."""
    log.critical("Hardware halt is unconfirmed. Buffers and controller lock remain live.")
    log.critical("Do not kill -9 this process. Inspect DMA/VDMA state and recover hardware manually.")
    while True:
        try:
            diagnostic = getattr(provider, "last_diagnostic", None) or {}
            provider_unsafe = bool(provider is not None and (
                getattr(provider, "_unsafe", False) or
                (getattr(provider, "poisoned", False) and
                 not diagnostic.get("channels_halted", False))
            ))
            if provider_unsafe:
                state = provider.status()
                if all(int(v) & 1 for v in state.values()):
                    provider._unsafe = False
                    provider.close()
                    provider_unsafe = False
                    log.warning("Gray DMA channels halted; its buffers are now released")
            display_unsafe = bool(display is not None and
                                  getattr(display, "buffers", None) and
                                  not getattr(display, "closed", False))
            if display_unsafe and getattr(display, "vdma", None) is not None:
                if int(display.vdma.read(4)) & 1:
                    display.stop()
                    display_unsafe = False
                    log.warning("VDMA halted; display buffers are now released")
            if not provider_unsafe and not display_unsafe:
                return
        except Exception:
            log.exception("Still waiting for confirmed hardware halt")
        try:
            time.sleep(2)
        except KeyboardInterrupt:
            log.critical("Ignoring Ctrl+C until hardware halt is confirmed")


def positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return n


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=("pl", "cpu"), default="pl")
    p.add_argument("--camera", default="0", help="V4L2 index or /dev/videoN")
    p.add_argument("--camera-width", type=positive_int, default=640)
    p.add_argument("--camera-height", type=positive_int, default=480)
    p.add_argument("--hdmi-root", type=Path, default=DEFAULT_HDMI_ROOT)
    p.add_argument("--gray-root", type=Path, default=DEFAULT_GRAY_ROOT)
    p.add_argument("--integration-root", type=Path, default=DEFAULT_INTEGRATION_ROOT)
    p.add_argument("--face-root", type=Path, default=DEFAULT_FACE_ROOT)
    p.add_argument("--log-root", type=Path, default=APP_ROOT / "run_logs")
    p.add_argument("--stats-every", type=positive_int, default=10)
    p.add_argument("--stats-window", type=positive_int, default=100)
    p.add_argument("--max-frames", type=int, default=0, help="0 means unlimited")
    p.add_argument("--max-seconds", type=float, default=0.0, help="0 means unlimited")
    p.add_argument("--read-fail-before-reopen", type=positive_int, default=3)
    p.add_argument("--max-camera-reopens", type=int, default=3)
    p.add_argument("--max-detection-errors", type=positive_int, default=5)
    args = p.parse_args(argv)
    if args.max_frames < 0 or args.max_seconds < 0 or args.max_camera_reopens < 0:
        p.error("limits must be nonnegative")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    args.log_root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = args.log_root / f"{stamp}_{os.getpid()}"
    metrics = Metrics(run_dir, args.backend, args.stats_every, args.stats_window)
    log = logging.getLogger("camera_hdmi_live")
    log.setLevel(logging.INFO)
    for old_handler in log.handlers:
        old_handler.close()
    log.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.StreamHandler(),
                    logging.FileHandler(run_dir / "run.log", encoding="utf-8")):
        handler.setFormatter(formatter)
        log.addHandler(handler)
    log.info("run_dir=%s backend=%s", run_dir, args.backend)
    stopped = False

    def request_stop(_signum, _frame):
        nonlocal stopped
        stopped = True
        log.info("Stop requested; finishing current frame")

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    camera = display = provider = None
    exit_code = 0
    unsafe = False
    lock = SingleInstance(args.hdmi_root / "controller.lock")
    try:
        lock.__enter__()
        hashes = verify_hardware_files(
            args.hdmi_root, APP_ROOT / "hardware_baseline_sha256.json"
        )
        metrics.event("hardware_sha256", hashes)
        for path in (args.hdmi_root, args.gray_root,
                     args.integration_root, args.face_root):
            if not path.is_dir():
                raise FileNotFoundError(f"Board dependency directory missing: {path}")
            sys.path.insert(0, str(path))
        import cv2
        import numpy as np
        import a_hdmi
        from pipeline_api import FacePipeline
        if args.backend == "pl":
            from a_gray_dma_fast import ReusableGrayDMA
        module_names = ["a_hdmi", "pipeline_api"]
        if args.backend == "pl":
            module_names += ["a_gray_dma_fast", "a_gray_dma"]
        modules = {}
        for name in module_names:
            source = Path(sys.modules[name].__file__).resolve()
            modules[name] = {
                "path": str(source),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        metrics.event("runtime_module_sha256", modules)
        log.info("Runtime module provenance: %s", json.dumps(modules))
        camera_factory = lambda: camera_open(
            cv2, args.camera, args.camera_width, args.camera_height
        )
        camera = CameraOwner(camera_factory)
        log.info("Camera opened once; requested %dx%d",
                 args.camera_width, args.camera_height)
        display = a_hdmi.Display.__new__(a_hdmi.Display)
        a_hdmi.Display.__init__(display)
        log.info("Combined Overlay and HDMI VDMA initialized once")
        pipeline = FacePipeline(execution_backend="ZYNQ_ARM")
        if args.backend == "pl":
            provider = ReusableGrayDMA(display.overlay, "axi_dma_0", timeout=5)
            dw, dh = pipeline.detector.detection_size(600, 800)
            provider(np.zeros((dh, dw, 3), dtype=np.uint8))
            if provider.poisoned:
                raise RuntimeError("PL gray DMA warmup failed")
            log.info("PL gray DMA warmup complete; persistent DDR pair=%dx%d",
                     dw, dh)
        validate_hardware_owners(display, provider, args.backend)
        metrics.started = time.perf_counter()
        metrics.event("steady_state_started", {"mode": args.backend})
        log.info("Steady-state timing starts now; press Ctrl+C to stop")
        run_loop(
            camera, display, provider, pipeline, cv2, metrics,
            backend=args.backend, stop_requested=lambda: stopped,
            max_frames=args.max_frames, max_seconds=args.max_seconds,
            read_fail_before_reopen=args.read_fail_before_reopen,
            max_camera_reopens=args.max_camera_reopens,
            max_detection_errors=args.max_detection_errors, log=log,
        )
    except Exception:
        exit_code = 1
        log.exception("Live processing stopped due to error")
        metrics.event("fatal_error", "see run.log")
    finally:
        if camera is not None:
            try:
                camera.release()
            except Exception:
                log.exception("Camera release failed")
        if provider is not None:
            diagnostic = getattr(provider, "last_diagnostic", None) or {}
            if getattr(provider, "_unsafe", False) or (
                provider.poisoned and not diagnostic.get("channels_halted", False)
            ):
                unsafe = True
                log.critical("Gray DMA halt unconfirmed: %s", diagnostic)
            else:
                try:
                    provider.close()
                except Exception:
                    unsafe = True
                    log.exception("Could not safely release gray DMA buffers")
        if display is not None:
            try:
                if getattr(display, "buffers", None):
                    display.stop()
            except Exception:
                unsafe = True
                log.exception("Could not confirm VDMA halt; keeping display buffers")
        try:
            result = metrics.close()
            log.info("summary=%s", json.dumps(result, ensure_ascii=False))
        except Exception:
            exit_code = 1
            log.exception("Could not finalize performance log")
        if unsafe:
            hold_unsafe(provider, display, log)
        if lock.file is not None:
            lock.__exit__(None, None, None)
        for handler in log.handlers:
            handler.close()
        log.handlers.clear()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

