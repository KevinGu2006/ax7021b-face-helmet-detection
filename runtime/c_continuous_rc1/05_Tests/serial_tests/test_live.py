"""Windows mocks only: no board, PYNQ, USB camera or Vivado interaction."""
import json
import logging
import signal
import types
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2] / "02_Serial_Fallback"
sys.path.insert(0, str(ROOT))
import camera_hdmi_live as live


class FakeCV2:
    INTER_LINEAR = 1

    @staticmethod
    def resize(frame, shape, interpolation=None):
        width, height = shape
        yy = np.minimum((np.arange(height) * frame.shape[0] / height).astype(int),
                        frame.shape[0] - 1)
        xx = np.minimum((np.arange(width) * frame.shape[1] / width).astype(int),
                        frame.shape[1] - 1)
        return frame[yy[:, None], xx[None, :], :]


class FakeCamera:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.releases = 0

    def read(self):
        return next(self.frames)

    def release(self):
        self.releases += 1


class FakeDetector:
    def detection_size(self, height, width):
        return 640, 480

    def prepare_bgr_for_pl(self, frame):
        assert frame.shape == (600, 800, 3)
        return np.zeros((480, 640, 3), dtype=np.uint8)


class FakePipeline:
    def __init__(self, failure_on=None):
        self.detector = FakeDetector()
        self.calls = 0
        self.failure_on = failure_on

    def process_frame(self, frame, gray=None, original_shape=None,
                      gray_execution_backend="EXTERNAL_UNVERIFIED"):
        self.calls += 1
        if self.calls == self.failure_on:
            raise RuntimeError("mock Haar failure")
        external = gray is not None
        if external:
            assert gray.shape == (480, 640)
            assert original_shape == (600, 800)
        return frame.copy(), {
            "face_count": 1,
            "timings_ms": {"face": 2.0, "render": 0.2},
            "external_gray": external,
            "execution_backend": {
                "gray": gray_execution_backend if external else "ZYNQ_ARM"
            },
        }


class FakeProvider:
    def __init__(self, fail=False):
        self.calls = 0
        self.last_diagnostic = {}
        self.fail = fail

    def __call__(self, frame):
        self.calls += 1
        if self.fail:
            raise TimeoutError("mock DMA timeout")
        self.last_diagnostic = {"reused_buffers": True}
        return np.zeros(frame.shape[:2], dtype=np.uint8)


class FakeDisplay:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def show(self, frame):
        assert frame.shape == (600, 800, 3)
        if self.fail:
            raise RuntimeError("mock VDMA failure")
        self.calls += 1

    def snapshot(self):
        return {"vdma": {"error": False, "halted": False}}


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.metrics = live.Metrics(
            Path(self.tmp.name) / "run", "pl", every=25, window=20
        )
        self.log = logging.getLogger("mock_live_test")
        self.log.addHandler(logging.NullHandler())
        self.frame = np.full((600, 800, 3), 40, dtype=np.uint8)

    def tearDown(self):
        if not self.metrics.csv_file.closed:
            self.metrics.close()
        self.tmp.cleanup()

    def run_fake(self, camera, display, provider, pipeline, count, backend="pl",
                 read_fail_before_reopen=3, max_camera_reopens=2):
        return live.run_loop(
            camera, display, provider, pipeline, FakeCV2, self.metrics,
            backend=backend, stop_requested=lambda: False, max_frames=count,
            max_seconds=0, read_fail_before_reopen=read_fail_before_reopen,
            max_camera_reopens=max_camera_reopens, max_detection_errors=5,
            log=self.log,
        )

    def test_100_frames_no_per_frame_reinitialization(self):
        camera = FakeCamera([(True, self.frame)] * 100)
        display, provider, pipeline = FakeDisplay(), FakeProvider(), FakePipeline()
        self.run_fake(camera, display, provider, pipeline, 100)
        summary = self.metrics.close()
        self.assertEqual((provider.calls, pipeline.calls, display.calls),
                         (100, 100, 100))
        self.assertEqual(summary["processed_frames"], 100)
        self.assertEqual(summary["hdmi_updates"], 100)
        self.assertEqual(summary["successful_detection_frames"], 100)
        self.assertEqual(summary["stage_window_frames"], 20)
        self.assertEqual(len((self.metrics.run_dir / "frames.csv").read_text().splitlines()), 101)
        self.assertGreater(summary["actual_detection_fps"], 0)
        self.assertGreater(summary["actual_hdmi_update_fps"], 0)
        self.assertFalse(list(self.metrics.run_dir.glob("*.png")))

    def test_camera_bounded_reopen_and_detection_failure_keeps_display(self):
        first = FakeCamera([(False, None), (False, None)])
        second = FakeCamera([(True, self.frame)] * 3)
        cameras = iter([first, second])
        owner = live.CameraOwner(lambda: next(cameras))
        display, provider, pipeline = FakeDisplay(), FakeProvider(), FakePipeline(failure_on=2)
        self.run_fake(owner, display, provider, pipeline, 3,
                      read_fail_before_reopen=2)
        summary = self.metrics.close()
        self.assertEqual(summary["camera_read_failures"], 2)
        self.assertEqual(summary["camera_reopens"], 1)
        self.assertEqual(summary["detection_errors"], 1)
        self.assertEqual(summary["hdmi_updates"], 3)
        self.assertEqual(summary["successful_detection_frames"], 2)
        self.assertEqual(first.releases, 1)
        owner.release()
        self.assertEqual(second.releases, 1)

    def test_dma_failure_stops_without_display_fallback(self):
        camera = FakeCamera([(True, self.frame)])
        display, provider = FakeDisplay(), FakeProvider(fail=True)
        with self.assertRaises(TimeoutError):
            self.run_fake(camera, display, provider, FakePipeline(), 1)
        self.assertEqual(self.metrics.dma_errors, 1)
        self.assertEqual(display.calls, 0)
        self.assertEqual(self.metrics.frames, 0)

    def test_vdma_failure_stops(self):
        camera = FakeCamera([(True, self.frame)])
        display = FakeDisplay(fail=True)
        with self.assertRaisesRegex(RuntimeError, "VDMA"):
            self.run_fake(camera, display, FakeProvider(), FakePipeline(), 1)
        self.assertEqual(self.metrics.vdma_errors, 1)
        self.assertEqual(self.metrics.frames, 0)

    def test_cpu_mode_has_no_pl_gray_call(self):
        self.metrics.backend = "cpu"
        camera = FakeCamera([(True, self.frame)] * 2)
        self.run_fake(camera, FakeDisplay(), None, FakePipeline(), 2, backend="cpu")
        summary = self.metrics.close()
        self.assertEqual(summary["processed_frames"], 2)
        self.assertEqual(summary["stages"]["pl_gray_dma_ms"]["mean_ms"], 0)

    def test_letterbox_keeps_aspect_and_coordinates(self):
        wide = np.full((720, 1280, 3), 27, dtype=np.uint8)
        canvas = live.letterbox_bgr(wide, FakeCV2)
        self.assertEqual(canvas.shape, (600, 800, 3))
        self.assertEqual(int(canvas[0].max()), 0)
        self.assertEqual(int(canvas[75, 0, 0]), 27)
        self.assertEqual(int(canvas[-1].max()), 0)

    def test_hardware_hashes_match_packaged_verified_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline = json.loads((ROOT / "hardware_baseline_sha256.json").read_text(encoding="utf-8"))
            for name in ("HDMI_CANDIDATE.bit", "HDMI_CANDIDATE.hwh"):
                candidates = list((ROOT.parents[2] / "integration" / "hdmi_candidate").rglob(name))
                if not candidates:
                    self.skipTest("Existing repository HDMI artifact not present in C source-only tree")
                source = candidates[0]
                (root / name).write_bytes(source.read_bytes())
            hashes = live.verify_hardware_files(root, ROOT / "hardware_baseline_sha256.json")
            self.assertEqual(len(hashes), 2)

    def test_camera_recovery_limit_stops(self):
        camera = FakeCamera([(False, None), (False, None)])
        with self.assertRaisesRegex(RuntimeError, "recovery attempts exhausted"):
            self.run_fake(camera, FakeDisplay(), FakeProvider(), FakePipeline(), 1,
                          read_fail_before_reopen=2, max_camera_reopens=0)
        self.assertEqual(self.metrics.camera_failures, 2)
        self.assertEqual(self.metrics.camera_reopens, 0)

    def test_pl_backend_mismatch_is_fatal(self):
        class WrongBackend(FakePipeline):
            def process_frame(self, *args, **kwargs):
                annotated, record = super().process_frame(*args, **kwargs)
                record["execution_backend"]["gray"] = "ZYNQ_ARM"
                return annotated, record
        display = FakeDisplay()
        with self.assertRaisesRegex(RuntimeError, "did not use the PL gray image"):
            self.run_fake(FakeCamera([(True, self.frame)]), display,
                          FakeProvider(), WrongBackend(), 1)
        self.assertEqual(display.calls, 0)

    def test_unsafe_buffers_release_only_after_confirmed_halt(self):
        class Provider:
            _unsafe = True
            poisoned = True
            last_diagnostic = {"channels_halted": False}
            closed = False
            def status(self):
                return {"mm2s": 1, "s2mm": 1}
            def close(self):
                self.closed = True
        class Vdma:
            def read(self, offset):
                return 1
        class Display:
            buffers = [object()]
            closed = False
            vdma = Vdma()
            def stop(self):
                self.closed = True
                self.buffers = []
        provider, display = Provider(), Display()
        live.hold_unsafe(provider, display, self.log)
        self.assertTrue(provider.closed)
        self.assertTrue(display.closed)

    def test_main_initializes_and_releases_each_owner_once(self):
        baseline = json.loads((ROOT / "hardware_baseline_sha256.json").read_text(encoding="utf-8"))
        board = Path(self.tmp.name) / "board"
        board.mkdir()
        for name in ("HDMI_CANDIDATE.bit", "HDMI_CANDIDATE.hwh"):
            candidates = list((ROOT.parents[2] / "integration" / "hdmi_candidate").rglob(name))
            if not candidates:
                self.skipTest("Existing repository HDMI artifact not present in C source-only tree")
            source = candidates[0]
            (board / name).write_bytes(source.read_bytes())
        class Capture:
            creations = 0
            releases = 0
            def __init__(self, *args):
                Capture.creations += 1
            def isOpened(self):
                return True
            def set(self, *args):
                return True
            def read(self):
                return True, self_frame
            def release(self):
                Capture.releases += 1
        class Display(FakeDisplay):
            creations = 0
            stops = 0
            def __init__(self):
                super().__init__()
                Display.creations += 1
                self.overlay = types.SimpleNamespace(ip_dict={
                    "axi_dma_0": {"phys_addr": 0x40400000},
                    "axi_vdma_0": {"phys_addr": 0x43000000},
                })
                self.buffers = [object()]
                self.closed = False
            def stop(self):
                Display.stops += 1
                self.buffers = []
                self.closed = True
        class Provider(FakeProvider):
            creations = 0
            closes = 0
            def __init__(self, *args, **kwargs):
                super().__init__()
                Provider.creations += 1
                self.poisoned = False
                self._unsafe = False
            def close(self):
                Provider.closes += 1
        class Pipeline(FakePipeline):
            creations = 0
            def __init__(self, execution_backend=None):
                super().__init__()
                Pipeline.creations += 1
        self_frame = self.frame
        cv2mod = types.ModuleType("cv2")
        cv2mod.__file__ = __file__
        cv2mod.VideoCapture = Capture
        cv2mod.CAP_PROP_FRAME_WIDTH = 3
        cv2mod.CAP_PROP_FRAME_HEIGHT = 4
        cv2mod.CAP_PROP_BUFFERSIZE = 38
        cv2mod.INTER_LINEAR = 1
        hdmi = types.ModuleType("a_hdmi")
        hdmi.__file__ = __file__
        hdmi.Display = Display
        gray = types.ModuleType("a_gray_dma_fast")
        gray.__file__ = __file__
        gray.ReusableGrayDMA = Provider
        base = types.ModuleType("a_gray_dma")
        base.__file__ = __file__
        pipe = types.ModuleType("pipeline_api")
        pipe.__file__ = __file__
        pipe.FacePipeline = Pipeline
        old_int = signal.getsignal(signal.SIGINT)
        old_term = signal.getsignal(signal.SIGTERM)
        old_path = list(sys.path)
        try:
            with patch.dict(sys.modules, {
                "cv2": cv2mod, "a_hdmi": hdmi, "a_gray_dma_fast": gray,
                "a_gray_dma": base, "pipeline_api": pipe,
            }):
                result = live.main([
                    "--backend", "pl", "--max-frames", "3",
                    "--stats-every", "3", "--log-root", str(Path(self.tmp.name) / "live_logs"),
                    "--hdmi-root", str(board), "--gray-root", str(board),
                    "--integration-root", str(board), "--face-root", str(board),
                ])
        finally:
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)
            sys.path[:] = old_path
        self.assertEqual(result, 0)
        self.assertEqual((Capture.creations, Capture.releases), (1, 1))
        self.assertEqual((Display.creations, Display.stops), (1, 1))
        self.assertEqual((Provider.creations, Provider.closes), (1, 1))
        self.assertEqual(Provider.creations, 1)
        self.assertEqual(Pipeline.creations, 1)
        run = next((Path(self.tmp.name) / "live_logs").iterdir())
        summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["processed_frames"], 3)
        self.assertEqual(summary["hdmi_updates"], 3)
        self.assertFalse(list(run.glob("*.png")))

    def test_single_instance_lock(self):
        path = Path(self.tmp.name) / "controller.lock"
        with live.SingleInstance(path):
            with self.assertRaises(RuntimeError):
                with live.SingleInstance(path):
                    pass
        with live.SingleInstance(path):
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)

