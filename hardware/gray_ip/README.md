# BGRX32 → Gray8 AXI4-Stream IP

This is the actual Verilog RTL, not the Python numerical reference. For each accepted input pixel, `TDATA[7:0]=B`, `[15:8]=G`, `[23:16]=R`, `[31:24]=0`; output is Gray8. The computation is `(3735*B + 19235*G + 9798*R + 16384) >> 15`. Input `TKEEP=4'b1111`, output `TKEEP=1`; `TLAST` denotes the **end of a frame**, not the end of a video line. `TVALID/TREADY` backpressure and reset are implemented in `bgr2gray_axis.v`.

`tb_bgr2gray_axis.sv` is the original testbench. The public `cases.svh` selects two generated random cases (33×31 and 640×480) plus the pixel CSV. The corresponding `.mem` and `.bin` pairs, and their source manifest entries, are in `vectors/`. Run Vivado 2025.2 from this directory with `vivado -mode batch -source verify.tcl`, or use `run_verify.ps1` on Windows. The runner writes fresh logs into this copy of the directory.

The **historical** 2026-10-28 run covered 32 frames and 2,065,095 pixels: 31 image cases (2,065,063 pixels) plus 32 pixel vectors. It passed simulation with zero golden mismatch; standalone synthesis used 4 LUT, 10 FF, 3 DSP48E1, 0 BRAM. Those counts come from the original `coverage.json` and `utilization.rpt`, not from a new run of the smaller public subset. The full original set includes third-party photos and is intentionally not republished here. The existing repository's 26-vector archive is a separate public collection; do not infer that its 26 cases equal the 31-image RTL manifest or the 31-case board acceptance run.

The original synthesis was not timing constrained; this directory is not evidence of an achieved clock rate. See `../../verification/README.md` for the distinction between RTL simulation, implementation, and board testing.

On 2026-11-03 the public subset was actually rerun in Vivado 2025.2: 3 frames, 308,255 pixels, xsim PASS with zero mismatches and standalone synthesis PASS at 4 LUT / 10 FF / 3 DSP48E1 / 0 BRAM. See `../../verification/public_subset_vivado_20261103.json`. This is separate from the original 32-frame result.
