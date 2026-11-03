"""Candidate AX7021B HDMI VDMA MM2S control helper.

This module does not load an Overlay, change PS clocks, program VTC/Dynamic Clock,
initialize the SiI9134, or access hardware on import. A must first confirm that
Linux has not bound another owner to the VDMA/video subsystem.
Reference: AMD AXI VDMA v6.3 PG020, Programming Sequence and MM2S registers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

VDMA_BASE = 0x43000000
MM2S_CR = 0x00
MM2S_SR = 0x04
MM2S_VSIZE = 0x50
MM2S_HSIZE = 0x54
MM2S_STRIDE = 0x58
MM2S_START = (0x5C, 0x60, 0x64)
# PG020: DMAIntErr, DMASlvErr, DMADecErr, SOFEarlyErr, Err_Irq.
MM2S_ERROR_MASK = 0x40F0
HP0_DDR_LIMIT = 0x40000000


@dataclass(frozen=True)
class FramePlan:
    width: int
    height: int
    stride: int
    addresses: tuple[int, int, int]

    @property
    def hsize(self) -> int:
        return self.width * 3

    @property
    def required_bytes(self) -> int:
        return self.stride * self.height


def plan_rgb888(width: int, height: int, stride: int, addresses: Sequence[int]) -> FramePlan:
    """Validate a 3-byte/pixel B,G,R buffer plan for the 3-store VDMA."""
    if not (1 <= width <= 4096 and 1 <= height <= 4096):
        raise ValueError("invalid width/height")
    if stride < width * 3 or stride >= (1 << 16):
        raise ValueError("stride must cover every pixel and fit VDMA register")
    if stride % 8:
        raise ValueError("use an 8-byte aligned stride for the 64-bit DDR interface")
    if len(addresses) != 3:
        raise ValueError("this candidate VDMA has 3 frame stores; supply 3 addresses")
    result = []
    for addr in addresses:
        a = int(addr)
        if a <= 0 or a % 8 or a + stride * height > HP0_DDR_LIMIT:
            raise ValueError(f"frame address 0x{a:x} is unaligned or outside HP0 DDR")
        result.append(a)
    return FramePlan(width, height, stride, tuple(result))


def status(mmio) -> dict[str, int | bool]:
    """Read current MM2S registers without changing hardware."""
    sr = int(mmio.read(MM2S_SR))
    return {
        "control": int(mmio.read(MM2S_CR)),
        "status": sr,
        "halted": bool(sr & 1),
        "error": bool(sr & MM2S_ERROR_MASK),
        "vsize": int(mmio.read(MM2S_VSIZE)),
        "hsize": int(mmio.read(MM2S_HSIZE)),
        "stride": int(mmio.read(MM2S_STRIDE)) & 0xFFFF,
    }


def start_static(mmio, plan: FramePlan) -> dict[str, int | bool]:
    """Start circular MM2S after caller flushes each DDR frame and starts timing.

    MMIO must be the PYNQ MMIO object for axi_vdma_0 at 0x43000000. All
    allocated buffers must remain alive for the entire VDMA run. Writing VSIZE
    last commits the transfer; call this only after Dynamic Clock, VTC, SiI9134
    and the video output path are ready. Never call while a Linux DRM driver owns it.
    """
    before = status(mmio)
    if before["error"]:
        raise RuntimeError(f"VDMA already has an error: 0x{before['status']:08x}")
    if not before["halted"]:
        raise RuntimeError("VDMA is already running; stop it before reconfiguration")
    mmio.write(MM2S_CR, 0x3)  # RS=1, Circular_Park=1; interrupt/frame count disabled
    for off, addr in zip(MM2S_START, plan.addresses):
        mmio.write(off, addr)
    mmio.write(MM2S_STRIDE, plan.stride)
    mmio.write(MM2S_HSIZE, plan.hsize)
    mmio.write(MM2S_VSIZE, plan.height)  # Commit last, as required by PG020.
    after = status(mmio)
    if after["error"]:
        raise RuntimeError(f"VDMA MM2S failed: 0x{after['status']:08x}")
    return after


def stop(mmio) -> dict[str, int | bool]:
    """Request a graceful stop; caller should poll `status()['halted']`."""
    mmio.write(MM2S_CR, 0)
    return status(mmio)
