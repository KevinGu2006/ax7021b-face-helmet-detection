# PS/DDR configuration check — TEST_ONLY

Compared `processing_system7_0` parameters in the original `com2026_test.srcs/sources_1/bd/system/system.bd` with the independent test design's `source_base/system/system.bd`.

- Original PS parameter count: 544; test design: 547.
- Changed existing setting: `PCW_USE_S_AXI_HP0` from `0` to `1`.
- Added HP0 properties: `PCW_S_AXI_HP0_DATA_WIDTH=64`, `PCW_S_AXI_HP0_ID_WIDTH=6`; added `preset=None` metadata.
- All settings with `DDR` or `MIO` in their names compare equal between those two BD files. FCLK_CLK0 is 50 MHz; GP0 and HP0 are enabled in the test design.
- This comparison only shows continuity with the original project. The original project's PS preset has not been validated against A's running AX7021B Linux 6.12.40 / Ubuntu 22.04 / PYNQ 3.0.1 image. No known-good A board XSA/HWH or PS preset was provided for comparison. Board part metadata is not set to an AX7021B board definition.

**Board loading remains blocked** until the board's verified DDR timing, MIO, clock, reset, and boot settings are compared with this project's PS configuration. Also review REQP-1839 reset-path DRC warnings and exercise DMA/reset recovery on a controlled first test. This report is a static Vivado BD comparison and is not a PYNQ Overlay or DDR transfer result.
