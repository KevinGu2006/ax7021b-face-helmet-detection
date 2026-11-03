"""Offline worker and resource tests; no real camera, PYNQ or FPGA."""
from __future__ import annotations

import logging
from pathlib import Path
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from async_pipeline import (
    AsyncEngine, DetectionResult, FramePacket, LatestSlot, Stats,
    classify_result,
)
from camera_hdmi_async import PreviewRenderer, map_box_to_hdmi, prepare_owned_frame
from fake_hardware import (
    FakeCameraRig, FakeCV2, FakeDetector, FakeDisplay, FakeRenderer,
)
from sync_fallback import camera_hdmi_live as sync


class AsyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.log = logging.getLogger("fake_async_test")
        self.log.addHandler(logging.NullHandler())
        self.counter = 0

    def tearDown(self):
        self.tmp.cleanup()

    def run_fake(self, *, rig=None, detector=None, display=None, renderer=None,
                 max_frames=0, max_seconds=0, ttl=1600, read_fail_before_reopen=3,
                 max_reopens=3, window=100, join_timeout=2):
        self.counter += 1
        rig = rig or FakeCameraRig(fps=30, shape=(24, 32))
        detector = detector or FakeDetector()
        display = display or FakeDisplay(rig)
        renderer = renderer or FakeRenderer()
        stats = Stats(self.path / f"run_{self.counter}", window=window)
        engine = AsyncEngine(
            camera_factory=rig.open,
            detector_factory=lambda _overlay: detector,
            display_factory=lambda: display,
            renderer=renderer,
            stats=stats, logger=self.log,
            max_capture_frames=max_frames,
            max_seconds=max_seconds, max_result_age_ms=ttl,
            read_fail_before_reopen=read_fail_before_reopen,
            max_camera_reopens=max_reopens,
            join_timeout=join_timeout, report_interval=100,
        )
        result = engine.run()
        return engine, result, rig, detector, display, renderer

    def test_a_slow_detection_does_not_gate_preview(self):
        rig = FakeCameraRig(fps=40, shape=(24, 32))
        det = FakeDetector(haar_delay=0.15, dma_delay=0.01)
        engine, result, *_ = self.run_fake(
            rig=rig, detector=det, max_seconds=0.55
        )
        summary = result["summary"]
        self.assertEqual(result["thread_alive"], [])
        self.assertGreater(summary["hdmi_content_updates"],
                           3 * summary["detection_frames"])
        self.assertGreater(summary["detection_drop_count"], 0)
        self.assertLess(
            summary["metrics_ms"]["capture_to_display_latency_ms"]["p95"],
            summary["metrics_ms"]["capture_to_detection_latency_ms"]["median"],
        )
        self.assertEqual(engine.frames.pending_count, 1)

    def test_b_long_detection_keeps_latest_frame_only(self):
        rig = FakeCameraRig(fps=60, shape=(24, 32))
        det = FakeDetector(haar_delay=0.01, slow_frames={1: 0.4})
        engine, result, *_ = self.run_fake(
            rig=rig, detector=det, max_seconds=0.7
        )
        summary = result["summary"]
        self.assertGreater(summary["hdmi_content_updates"], 20)
        self.assertGreater(summary["detection_drop_count"], 15)
        self.assertEqual(engine.frames.pending_count, 1)

    def test_c_camera_disconnect_reconnect_is_bounded(self):
        rig = FakeCameraRig(fps=80, shape=(24, 32), failures=(2, 3, 4))
        _, result, rig, _, _, _ = self.run_fake(
            rig=rig, max_frames=40, read_fail_before_reopen=3, max_reopens=1
        )
        summary = result["summary"]
        self.assertEqual(result["errors"], [])
        self.assertEqual(summary["camera_read_failures"], 3)
        self.assertEqual(summary["camera_reconnect_count"], 1)
        self.assertEqual(rig.open_count, 2)
        self.assertEqual(rig.release_count, 2)

    def test_c_reconnect_limit_stops(self):
        rig = FakeCameraRig(fps=100, failures=range(1, 20))
        _, result, *_ = self.run_fake(
            rig=rig, max_frames=5, read_fail_before_reopen=2, max_reopens=1
        )
        self.assertTrue(result["errors"])
        self.assertEqual(result["thread_alive"], [])
        self.assertEqual(result["summary"]["camera_reconnect_count"], 1)

    def test_d_dma_timeout_retains_buffer_owner(self):
        rig = FakeCameraRig(fps=5, shape=(24, 32))
        det = FakeDetector(fail_dma_on=1, unsafe_dma=True)
        engine, result, _, detector, display, _ = self.run_fake(
            rig=rig, detector=det, max_frames=10
        )
        self.assertTrue(result["errors"])
        self.assertEqual(result["thread_alive"], [])
        self.assertTrue(result["unsafe_resources"])
        self.assertFalse(detector.buffers_released)
        self.assertTrue(display.closed)
        self.assertGreaterEqual(result["summary"]["dma_errors"], 1)
        self.assertIs(engine.detector, det)

    def test_e_hdmi_error_stops_all_workers_without_deadlock(self):
        rig = FakeCameraRig(fps=50, shape=(24, 32))
        display = FakeDisplay(rig, fail_on=2)
        _, result, _, detector, display, _ = self.run_fake(
            rig=rig, display=display, max_frames=100
        )
        self.assertTrue(result["errors"])
        self.assertEqual(result["thread_alive"], [])
        self.assertTrue(display.closed)
        self.assertTrue(detector.closed)
        self.assertGreaterEqual(result["summary"]["vdma_errors"], 1)

    def test_e_unsafe_vdma_stop_retains_scan_buffers(self):
        rig = FakeCameraRig(fps=100, shape=(24, 32))
        display = FakeDisplay(rig, fail_on=2, unsafe_stop=True)
        engine, result, _, _, display, _ = self.run_fake(
            rig=rig, display=display, max_frames=50
        )
        self.assertTrue(result["unsafe_resources"])
        self.assertFalse(display.closed)
        self.assertEqual(len(display.buffers), 3)
        self.assertIs(engine.display, display)

    def test_f_thousands_of_frames_bound_queue_and_metrics_memory(self):
        rig = FakeCameraRig(fps=0, shape=(8, 8))
        tracemalloc.start()
        before, _ = tracemalloc.get_traced_memory()
        engine, result, *_ = self.run_fake(
            rig=rig, max_frames=3000, window=50
        )
        after, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        summary = result["summary"]
        self.assertEqual(summary["camera_frames"], 3000)
        self.assertEqual(engine.frames.pending_count, 1)
        self.assertTrue(all(len(window) <= 50
                            for window in engine.stats._windows.values()))
        self.assertTrue(all(len(window) <= 50
                            for window in engine.stats._resource_windows.values()))
        self.assertEqual(result["thread_alive"], [])
        self.assertLess(after - before, 3_000_000)
        print(f"STRESS_MEMORY before={before} after={after} peak={peak} delta={after - before}")
        self.memory_observation = {"before": before, "after": after, "peak": peak}

    def test_g_repeated_runs_leave_no_threads_or_lock_owner(self):
        path = self.path / "controller.lock"
        for _ in range(3):
            with sync.SingleInstance(path):
                rig = FakeCameraRig(fps=0, shape=(8, 8))
                engine, result, _, detector, display, _ = self.run_fake(
                    rig=rig, max_frames=30
                )
                self.assertEqual(result["thread_alive"], [])
                self.assertFalse(any(thread.is_alive()
                                     for thread in engine.threads.values()))
                self.assertTrue(detector.closed)
                self.assertTrue(display.closed)
        with sync.SingleInstance(path):
            pass

    def test_h_result_age_shape_gap_and_letterbox_mapping(self):
        now = 100.0
        frame = FramePacket(50, now - 0.02, 1.0, (720, 1280), None)
        result = DetectionResult(
            40, now - 0.3, now - 0.05, (720, 1280),
            ((0, 0, 1280, 720),),
        )
        visible, state, age, _, gap = classify_result(frame, result, now, 500)
        self.assertIs(visible, result)
        self.assertEqual((state, gap), ("delayed", 10))
        self.assertAlmostEqual(age, 300)
        self.assertEqual(
            map_box_to_hdmi((0, 0, 1280, 720), (720, 1280)),
            (0, 75, 800, 525),
        )
        self.assertEqual(
            map_box_to_hdmi((0, 0, 640, 480), (480, 640)),
            (0, 0, 800, 600),
        )
        self.assertEqual(classify_result(frame, result, now, 100)[1], "expired")
        changed = FramePacket(50, now, 1.0, (480, 640), None)
        self.assertEqual(
            classify_result(changed, result, now, 500)[1], "shape_mismatch"
        )
        exact = DetectionResult(50, now - 0.01, now, (720, 1280), ())
        self.assertEqual(classify_result(frame, exact, now, 500)[1], "matched")

    def test_h_frame_ownership_copy_survives_camera_reuse(self):
        rig = FakeCameraRig(fps=100, shape=(8, 8))
        class ReadingDetector(FakeDetector):
            def process(self, packet):
                marker = int(packet.image[0, 0, 0])
                self.assert_readonly = not packet.image.flags.writeable
                time.sleep(0.08)
                self.stable = marker == int(packet.image[0, 0, 0])
                return super().process(packet)
        detector = ReadingDetector()
        _, result, rig, detector, display, _ = self.run_fake(
            rig=rig, detector=detector, max_frames=20
        )
        self.assertEqual(result["thread_alive"], [])
        self.assertTrue(detector.assert_readonly)
        self.assertTrue(detector.stable)
        self.assertEqual(rig.read_threads, {"camera-capture"})
        self.assertEqual(detector.threads, {"face-detection"})
        self.assertEqual(display.threads, {"hdmi-display"})

    def test_h_board_preprocessing_matches_v1_and_owns_800x600_frame(self):
        raw = np.ones((480, 640, 3), dtype=np.uint8)
        prepared = prepare_owned_frame(raw, FakeCV2)
        self.assertEqual(prepared.shape, (600, 800, 3))
        self.assertFalse(np.shares_memory(raw, prepared))
        self.assertFalse(prepared.flags.writeable)
        original = sync.letterbox_bgr(raw, FakeCV2)
        self.assertTrue(np.array_equal(prepared, original))
        exact = np.ones((600, 800, 3), dtype=np.uint8)
        exact_prepared = prepare_owned_frame(exact, FakeCV2)
        self.assertFalse(np.shares_memory(exact, exact_prepared))

    def test_h_unannotated_preview_reuses_readonly_owned_frame(self):
        image = np.zeros((600, 800, 3), dtype=np.uint8)
        image.setflags(write=False)
        packet = FramePacket(1, 1.0, 0.0, (480, 640), image, (600, 800))
        self.assertIs(PreviewRenderer(FakeCV2)(packet, None, "none", None), image)


if __name__ == "__main__":
    unittest.main(verbosity=2)
