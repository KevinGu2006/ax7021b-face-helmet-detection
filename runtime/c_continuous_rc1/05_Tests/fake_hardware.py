"""Deterministic-enough wall-clock fake devices for async/sync architecture tests.

These are not FPGA timing models. Delays are real time.sleep calls; reports
include both configured delays and measured wall-clock throughput.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from async_pipeline import DetectionOutput, UnsafeHardwareState


class FakeCameraRig:
    def __init__(self, *, fps=30.0, shape=(60, 80), failures=()):
        self.fps = float(fps)
        self.shape = tuple(shape)
        self.failures = set(failures)
        self.attempts = 0
        self.open_count = 0
        self.release_count = 0
        self.capture_times = {}
        self.read_threads = set()
        self._next_due = None
        self._buffer = np.zeros((*self.shape, 3), dtype=np.uint8)
        self._lock = threading.Lock()

    def open(self):
        with self._lock:
            self.open_count += 1
        return FakeCamera(self)


class FakeCamera:
    def __init__(self, rig: FakeCameraRig):
        self.rig = rig
        self.closed = False

    def read(self):
        if self.closed:
            raise RuntimeError("Camera already closed")
        self.rig.read_threads.add(threading.current_thread().name)
        if self.rig.fps > 0:
            now = time.perf_counter()
            if self.rig._next_due is None:
                self.rig._next_due = now
            remaining = self.rig._next_due - now
            if remaining > 0:
                time.sleep(remaining)
            self.rig._next_due = max(
                self.rig._next_due + 1.0 / self.rig.fps,
                time.perf_counter(),
            )
        with self.rig._lock:
            self.rig.attempts += 1
            n = self.rig.attempts
        if n in self.rig.failures:
            return False, None
        self.rig._buffer.fill(n % 256)
        self.rig.capture_times[n % 256] = time.perf_counter()
        return True, self.rig._buffer

    def release(self):
        if not self.closed:
            self.closed = True
            with self.rig._lock:
                self.rig.release_count += 1


class FakeDetector:
    def __init__(
        self, *, haar_delay=0.0, dma_delay=0.0, slow_frames=None,
        fail_dma_on=None, fail_haar_on=None, unsafe_dma=False,
    ):
        self.haar_delay = float(haar_delay)
        self.dma_delay = float(dma_delay)
        self.slow_frames = dict(slow_frames or {})
        self.fail_dma_on = fail_dma_on
        self.fail_haar_on = fail_haar_on
        self.unsafe_dma = unsafe_dma
        self.processed_ids = []
        self.threads = set()
        self.closed = False
        self.buffers_released = False

    def process(self, packet):
        self.threads.add(threading.current_thread().name)
        self.processed_ids.append(packet.frame_id)
        if packet.frame_id == self.fail_dma_on:
            raise TimeoutError("Fake DMA timeout")
        if self.dma_delay:
            time.sleep(self.dma_delay)
        if packet.frame_id == self.fail_haar_on:
            from async_pipeline import RecoverableDetectionError
            raise RecoverableDetectionError("Fake Haar error")
        delay = self.slow_frames.get(packet.frame_id, self.haar_delay)
        if delay:
            time.sleep(delay)
        h, w = packet.source_shape
        box = (w // 4, h // 4, max(w // 4 + 1, 3 * w // 4),
               max(h // 4 + 1, 3 * h // 4))
        return DetectionOutput(
            boxes=(box,), preprocess_ms=0.1,
            pl_gray_dma_ms=self.dma_delay * 1000,
            dma_wait_ms=self.dma_delay * 1000,
            haar_ms=delay * 1000, draw_ms=0.0,
        )

    def close(self):
        if self.unsafe_dma and self.fail_dma_on in self.processed_ids:
            raise UnsafeHardwareState("Fake DMA still owns DDR")
        self.closed = True
        self.buffers_released = True


class FakeDisplay:
    def __init__(self, rig, *, show_delay=0.0, fail_on=None, unsafe_stop=False):
        self.rig = rig
        self.show_delay = float(show_delay)
        self.fail_on = fail_on
        self.unsafe_stop = unsafe_stop
        self.overlay = object()
        self.buffers = [object(), object(), object()]
        self.closed = False
        self.updates = []
        self.threads = set()

    def show(self, frame):
        self.threads.add(threading.current_thread().name)
        if self.fail_on is not None and len(self.updates) + 1 == self.fail_on:
            raise RuntimeError("Fake HDMI show error")
        if self.show_delay:
            time.sleep(self.show_delay)
        marker = int(frame[0, 0, 0])
        captured_at = self.rig.capture_times.get(marker)
        latency = ((time.perf_counter() - captured_at) * 1000
                   if captured_at is not None else None)
        self.updates.append((marker, latency, time.perf_counter()))

    def snapshot(self):
        return {"vdma": {"error": False, "halted": False}}

    def stop(self):
        if self.unsafe_stop:
            raise UnsafeHardwareState("Fake VDMA still owns DDR")
        self.buffers = []
        self.closed = True


class FakeRenderer:
    def __init__(self):
        self.states = []

    def __call__(self, packet, result, box_state, result_age_ms):
        self.states.append((
            packet.frame_id, result.source_frame_id if result else None,
            box_state, result_age_ms,
        ))
        return packet.image


class FakeCV2:
    INTER_LINEAR = 1

    @staticmethod
    def resize(frame, size, interpolation=None):
        w, h = size
        out = np.empty((h, w, 3), dtype=np.uint8)
        out[:] = frame[0, 0]
        return out
