"""AX7021B async camera/gray/Haar/HDMI entry point.

No board access on import. In async mode the HDMI thread alone constructs
a_hdmi.Display (and its Overlay), the detection thread alone uses the gray
DMA, and the capture thread alone opens/reads the USB camera.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import sys
import time

from async_pipeline import (
    AsyncEngine, DetectionOutput, RecoverableDetectionError, Stats,
    UnsafeHardwareState,
)
from sync_fallback import camera_hdmi_live as sync

ROOT = Path(__file__).resolve().parent
DEFAULT_HDMI_ROOT = Path("/home/xilinx/A_hdmi_integration_20261029")
DEFAULT_GRAY_ROOT = Path("/home/xilinx/A_C_gray_hardware_20261028")
DEFAULT_INTEGRATION_ROOT = Path("/home/xilinx/A_C_gray_integration_20261028")
DEFAULT_FACE_ROOT = Path("/home/xilinx/A_B_integration_20261028")


def map_box_to_hdmi(box, source_shape, out_size=(800, 600)):
    """Map an original-image half-open bbox through the same letterbox geometry."""
    height, width = source_shape
    out_width, out_height = out_size
    if min(height, width, out_width, out_height) < 1:
        raise ValueError("Invalid source or display dimensions")
    scale = min(out_width / width, out_height / height)
    scaled_width = max(1, min(out_width, round(width * scale)))
    scaled_height = max(1, min(out_height, round(height * scale)))
    xoff = (out_width - scaled_width) // 2
    yoff = (out_height - scaled_height) // 2
    x1, y1, x2, y2 = box
    vals = (
        xoff + round(x1 * scaled_width / width),
        yoff + round(y1 * scaled_height / height),
        xoff + round(x2 * scaled_width / width),
        yoff + round(y2 * scaled_height / height),
    )
    ax1, ay1, ax2, ay2 = vals
    ax1 = max(0, min(out_width - 1, ax1))
    ay1 = max(0, min(out_height - 1, ay1))
    ax2 = max(ax1 + 1, min(out_width, ax2))
    ay2 = max(ay1 + 1, min(out_height, ay2))
    return ax1, ay1, ax2, ay2


class BoardDetector:
    """One FacePipeline and one reusable gray DMA, owned by the detector thread."""

    def __init__(self, overlay, backend: str):
        from pipeline_api import FacePipeline
        self.pipeline = FacePipeline(execution_backend="ZYNQ_ARM")
        self.backend = backend
        self.provider = None
        self.closed = False
        self.last_diagnostic = None
        if backend == "pl":
            from a_gray_dma_fast import ReusableGrayDMA
            self.provider = ReusableGrayDMA(overlay, "axi_dma_0", timeout=5)
        elif backend != "cpu":
            raise ValueError("backend must be pl or cpu")

    def process(self, packet) -> DetectionOutput:
        bgr = packet.image
        start = time.perf_counter()
        if self.backend == "pl":
            small = self.pipeline.detector.prepare_bgr_for_pl(bgr)
            prep_ms = (time.perf_counter() - start) * 1000
            started_dma = time.perf_counter()
            gray = self.provider(small)
            dma_ms = (time.perf_counter() - started_dma) * 1000
            diagnostic = self.provider.last_diagnostic or {}
            self.last_diagnostic = diagnostic
            if not diagnostic.get("hardware_tested", False):
                raise RuntimeError("Gray DMA did not confirm a hardware transfer")
            try:
                _annotated, record = self.pipeline.process_frame(
                    bgr, gray, original_shape=bgr.shape[:2],
                    gray_execution_backend="ZYNQ_PL",
                )
            except Exception as exc:
                raise RecoverableDetectionError(str(exc)) from exc
            if (not record.get("external_gray") or
                    record.get("execution_backend", {}).get("gray") != "ZYNQ_PL"):
                raise RuntimeError("PL mode did not use the PL gray image")
        else:
            prep_ms = 0.0
            dma_ms = 0.0
            try:
                _annotated, record = self.pipeline.process_frame(bgr)
            except Exception as exc:
                raise RecoverableDetectionError(str(exc)) from exc
        boxes = tuple(
            tuple(int(v) for v in row["face_bbox"])
            for row in record.get("detections", ())
        )
        timings = record["timings_ms"]
        return DetectionOutput(
            boxes=boxes,
            preprocess_ms=prep_ms,
            pl_gray_dma_ms=dma_ms,
            dma_wait_ms=dma_ms,
            haar_ms=float(timings["face"]),
            draw_ms=float(timings["render"]),
        )

    def close(self):
        if self.provider is not None:
            diagnostic = self.provider.last_diagnostic or {}
            if getattr(self.provider, "_unsafe", False) or (
                self.provider.poisoned and not diagnostic.get("channels_halted", False)
            ):
                raise UnsafeHardwareState(
                    f"Gray DMA halt unconfirmed: {diagnostic}"
                )
            self.provider.close()
        self.closed = True


class PreviewRenderer:
    """Only the display worker calls this; input FramePacket remains immutable."""

    def __init__(self, cv2_module):
        self.cv2 = cv2_module

    def __call__(self, packet, result, box_state, result_age_ms):
        # Display.show copies input into a non-scanning DDR buffer. When no
        # overlay is drawn, the read-only captured frame needs no RAM copy.
        if not (result is not None and result.boxes) and box_state not in (
            "expired", "shape_mismatch"
        ):
            return packet.image
        canvas = packet.image.copy()
        if result is not None and result.boxes:
            for box in result.boxes:
                x1, y1, x2, y2 = map_box_to_hdmi(
                    box, result.analysis_shape or result.source_shape
                )
                self.cv2.rectangle(canvas, (x1, y1), (x2 - 1, y2 - 1),
                                   (0, 220, 0), 2)
            label = (
                f"{box_state.upper()} frame {result.source_frame_id}"
                f" age {result_age_ms:.0f}ms"
            )
            self.cv2.putText(canvas, label, (8, 22),
                             self.cv2.FONT_HERSHEY_SIMPLEX, 0.52,
                             (0, 220, 0), 1, self.cv2.LINE_AA)
        elif box_state in ("expired", "shape_mismatch"):
            self.cv2.putText(canvas, f"{box_state.upper()} boxes hidden",
                             (8, 22), self.cv2.FONT_HERSHEY_SIMPLEX,
                             0.52, (0, 180, 255), 1, self.cv2.LINE_AA)
        return canvas


def prepare_owned_frame(raw, cv2_module):
    """One v1-compatible letterbox with storage independent of VideoCapture."""
    import numpy as np
    prepared = sync.letterbox_bgr(raw, cv2_module, 800, 600)
    if np.shares_memory(prepared, raw):
        prepared = prepared.copy()
    prepared.setflags(write=False)
    return prepared


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("async", "serial"), default="async")
    parser.add_argument("--backend", choices=("pl", "cpu"), default="pl")
    parser.add_argument("--camera", default="0")
    parser.add_argument("--camera-width", type=positive_int, default=640)
    parser.add_argument("--camera-height", type=positive_int, default=480)
    parser.add_argument("--hdmi-root", type=Path, default=DEFAULT_HDMI_ROOT)
    parser.add_argument("--gray-root", type=Path, default=DEFAULT_GRAY_ROOT)
    parser.add_argument("--integration-root", type=Path,
                        default=DEFAULT_INTEGRATION_ROOT)
    parser.add_argument("--face-root", type=Path, default=DEFAULT_FACE_ROOT)
    parser.add_argument("--log-root", type=Path, default=ROOT / "run_logs")
    parser.add_argument("--max-frames", type=int, default=0,
                        help="async: number of captured frames; 0 unlimited")
    parser.add_argument("--max-seconds", type=float, default=0,
                        help="steady-state wall seconds; 0 unlimited")
    parser.add_argument("--result-ttl-ms", type=float, default=1600)
    parser.add_argument("--stats-window", type=positive_int, default=1000)
    parser.add_argument("--stats-every-seconds", type=float, default=5)
    parser.add_argument("--read-fail-before-reopen", type=positive_int, default=3)
    parser.add_argument("--max-camera-reopens", type=int, default=3)
    parser.add_argument("--max-detection-errors", type=positive_int, default=5)
    args = parser.parse_args(argv)
    if any(v < 0 for v in (
        args.max_frames, args.max_seconds, args.max_camera_reopens
    )) or args.result_ttl_ms <= 0 or args.stats_every_seconds <= 0:
        parser.error("limits and reporting interval must be valid")
    return args


def run_serial_fallback(args):
    argv = [
        "--backend", args.backend, "--camera", args.camera,
        "--camera-width", str(args.camera_width),
        "--camera-height", str(args.camera_height),
        "--hdmi-root", str(args.hdmi_root),
        "--gray-root", str(args.gray_root),
        "--integration-root", str(args.integration_root),
        "--face-root", str(args.face_root),
        "--log-root", str(args.log_root / "serial"),
        "--max-frames", str(args.max_frames),
        "--max-seconds", str(args.max_seconds),
        "--read-fail-before-reopen", str(args.read_fail_before_reopen),
        "--max-camera-reopens", str(args.max_camera_reopens),
        "--max-detection-errors", str(args.max_detection_errors),
    ]
    return sync.main(argv)


def quarantine(engine, log):
    """Keep the process, lock and DDR references alive after unsafe shutdown."""
    log.critical("Hardware halt/worker exit is unconfirmed; retaining all owners.")
    log.critical("Do not kill -9 or restart until A manually verifies DMA/VDMA halt.")
    while True:
        living = [n for n, t in engine.threads.items() if t.is_alive()]
        if living:
            log.critical("Workers still active: %s", living)
        else:
            detector = engine.detector
            display = engine.display
            dma_safe = bool(detector is None or detector.closed)
            vdma_safe = bool(display is None or getattr(display, "closed", False))
            if not dma_safe and detector.provider is not None:
                try:
                    status = detector.provider.status()
                    if all(int(v) & 1 for v in status.values()):
                        detector.provider._unsafe = False
                        detector.provider.close()
                        detector.closed = True
                        dma_safe = True
                        log.warning("Gray DMA confirmed halted; buffers released")
                except Exception:
                    log.exception("Gray DMA remains unsafe")
            if not vdma_safe and getattr(display, "vdma", None) is not None:
                try:
                    if int(display.vdma.read(4)) & 1:
                        display.stop()
                        vdma_safe = True
                        log.warning("VDMA confirmed halted; buffers released")
                except Exception:
                    log.exception("VDMA remains unsafe")
            if dma_safe and vdma_safe:
                log.warning("All hardware owners are now halted; exiting quarantine")
                return
        time.sleep(5)


def main(argv=None):
    args = parse_args(argv)
    if args.mode == "serial":
        return run_serial_fallback(args)
    args.log_root.mkdir(parents=True, exist_ok=True)
    run_dir = args.log_root / (
        time.strftime("%Y%m%d_%H%M%S") +
        f"_{os.getpid()}_{time.perf_counter_ns() % 1000000:06d}"
    )
    stats = Stats(run_dir, window=args.stats_window)
    log = logging.getLogger("camera_hdmi_async")
    log.setLevel(logging.INFO)
    for old in log.handlers:
        old.close()
    log.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(threadName)s %(levelname)s %(message)s")
    for handler in (
        logging.StreamHandler(),
        logging.FileHandler(run_dir / "run.log", encoding="utf-8"),
    ):
        handler.setFormatter(formatter)
        log.addHandler(handler)
    engine = None
    exit_code = 0
    lock = sync.SingleInstance(args.hdmi_root / "controller.lock")
    try:
        lock.__enter__()
        sync.verify_hardware_files(args.hdmi_root, ROOT / "hardware_baseline_sha256.json")
        for path in (
            args.hdmi_root, args.gray_root,
            args.integration_root, args.face_root,
        ):
            if not path.is_dir():
                raise FileNotFoundError(f"Missing board module directory: {path}")
            sys.path.insert(0, str(path))
        import cv2
        import a_hdmi
        import pipeline_api
        if args.backend == "pl":
            import a_gray_dma_fast
        names = ["a_hdmi", "pipeline_api"]
        if args.backend == "pl":
            names.append("a_gray_dma_fast")
        provenance = {}
        for name in names:
            source = Path(sys.modules[name].__file__).resolve()
            provenance[name] = {
                "path": str(source),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        stats.record("runtime_modules", detail=json.dumps(provenance))
        renderer = PreviewRenderer(cv2)
        def make_display():
            # Keep a reference even if A's Display.__init__ fails after it
            # allocates scan buffers or starts VDMA.
            display = a_hdmi.Display.__new__(a_hdmi.Display)
            engine.display = display
            try:
                a_hdmi.Display.__init__(display)
            except Exception:
                if getattr(display, "vdma", None) is not None or getattr(display, "buffers", None):
                    try:
                        display.stop()
                    except Exception as stop_error:
                        engine.unsafe_resources.append((
                            "vdma_partial_init", repr(stop_error)
                        ))
                else:
                    display.closed = True
                raise
            return display

        engine = AsyncEngine(
            camera_factory=lambda: sync.camera_open(
                cv2, args.camera, args.camera_width, args.camera_height
            ),
            detector_factory=lambda overlay: BoardDetector(overlay, args.backend),
            display_factory=make_display,
            renderer=renderer, stats=stats, logger=log,
            frame_owner=lambda raw: prepare_owned_frame(raw, cv2),
            max_capture_frames=args.max_frames,
            max_seconds=args.max_seconds,
            max_result_age_ms=args.result_ttl_ms,
            read_fail_before_reopen=args.read_fail_before_reopen,
            max_camera_reopens=args.max_camera_reopens,
            max_detection_errors=args.max_detection_errors,
            report_interval=args.stats_every_seconds,
        )
        def request_stop(_signal_number, _frame):
            log.warning("Stop requested")
            engine.request_stop()
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        result = engine.run()
        (run_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if result["thread_alive"] or result["unsafe_resources"]:
            exit_code = 1
            quarantine(engine, log)
            if not stats.closed:
                stats.close()
        if result["errors"]:
            exit_code = 1
        log.info("Final async summary: %s", json.dumps(result["summary"]))
    except Exception:
        exit_code = 1
        log.exception("Async startup or coordination failed")
        if engine is not None:
            engine.request_stop()
            for thread in engine.threads.values():
                thread.join(timeout=15)
            if any(t.is_alive() for t in engine.threads.values()) or engine.unsafe_resources:
                quarantine(engine, log)
        if not stats.closed:
            stats.close()
    finally:
        if lock.file is not None:
            lock.__exit__(None, None, None)
        for handler in log.handlers:
            handler.close()
        log.handlers.clear()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
