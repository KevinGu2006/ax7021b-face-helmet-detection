# HDMI＋灰度 DMA 硬件参数与地址映射

来源：本目录 `source_base/system/system.bd`、Vivado 2025.2 自动生成的 `system.hwh`。这些参数属于 HDMI_CANDIDATE 独立工程；板端仍未加载/测试。HWH 中所有 IP 位于 BD 根层级，因此 PYNQ 的完整 IP 路径为 `/axi_dma_0`、`/axi_vdma_0`、`/v_tc_0`、`/axi_dynclk_0`、`/hdmi_reset_gpio`，在 `Overlay.ip_dict` 中通常用不带前导 `/` 的键。A 的 `a_gray_dma.py` 要求传入精确路径，灰度 DMA 保持 `axi_dma_0`。

| IP | HWH 完整路径 | GP0 AXI-Lite 基址 | 64 KiB 地址窗口 | 作用 |
| --- | --- | --- | --- | --- |
| AXI DMA | `/axi_dma_0` | `0x40400000` | `0x40400000–0x4040FFFF` | 原灰度流 MM2S＋S2MM |
| AXI GPIO | `/hdmi_reset_gpio` | `0x41200000` | `0x41200000–0x4120FFFF` | SiI9134 reset_n，channel 1 bit0 |
| AXI VDMA | `/axi_vdma_0` | `0x43000000` | `0x43000000–0x4300FFFF` | DDR 彩色帧 MM2S |
| VTC | `/v_tc_0` | `0x43C00000` | `0x43C00000–0x43C0FFFF` | HDMI 视频时序生成 |
| Dynamic Clock | `/axi_dynclk_0` | `0x43C10000` | `0x43C10000–0x43C1FFFF` | 像素时钟 DRP 控制 |

PS IIC0 控制器本身位于 PS 地址 `0xE0004000`，本候选经 EMIO 接出；它不由 GP0 AXI-Lite 地址窗口分配。Linux 中的总线编号和驱动状态未核实。

## 灰度 DMA（保持 A 实机验证基线）

- AXI DMA v7.1；Simple/Register Direct Mode（`C_INCLUDE_SG=0`），MM2S、S2MM 均开启，Micro DMA 未启用。
- MM2S stream 32 bit、S2MM stream 8 bit；两方向 DRE 开启；length width 26 bit。
- AXI-Lite、memory map、stream 使用 FCLK0 50 MHz。DDR 读/写经 PS S_AXI_HP0 64-bit、DDR 可达段 `0x00000000–0x3FFFFFFF`。原 RTL `bgr2gray_axis_0` 与两个 stream 接口仍直接相连，整帧最后一个像素 TLAST，不接 HDMI 视频流。
- 中断未接 PS；A 现有 PYNQ 代码使用轮询。31 组、2,065,063 像素、误差 0 是 A 在原 gray_dma Overlay 上的实机结果；HDMI 合并后需重新跑。

## HDMI VDMA 与视频链

- AXI VDMA v6.3，`C_INCLUDE_SG=0`，仅 MM2S（S2MM=0），DRE 开启，3 个 frame stores，64-bit AXI memory、24-bit AXI4-Stream Video、line buffer 4096、最大 burst 16。
- VDMA AXI-Lite 50 MHz；memory MM2S 与 stream MM2S 同为 PL Clocking Wizard 输出 100 MHz。PS HP0/原 gray DMA 仍 50 MHz，`axi_hp0_xbar/s02_couplers/auto_cc` 是 Vivado 生成的 100↔50 MHz AXI 时钟转换。
- Video Out v4.0：24-bit RGB888、1 pixel/clock、异步 stream/pixel clock FIFO（`C_HAS_ASYNC_CLK=1`）、master timing mode（`C_VTG_MASTER_SLAVE=1`）；VTC v6.2 关闭 detection，使用 generator。VDMA 的 TUSER 表示帧首，TLAST 表示行末；不与灰度 RTL 的整帧 TLAST 混接。
- FCLK0 50 MHz → `hdmi_ref_clk_wiz` MMCM 100 MHz（`PRIM_SOURCE=No_buffer`）→ `axi_dynclk_0` 参考时钟。Pixel Clock 由 Dynamic Clock 软件配置：原厂 Vitis 默认 800×600@60 为 40 MHz；原厂模式表 720p60 为 74.25 MHz。当前静态 XDC 按 74.25 MHz 签核。
- `rst_ps7_0_50M` 供灰度与 50 MHz 控制域；`rst_hdmi_axis_100M` 由时钟向导 locked 同步释放 Video Out stream/HP0 100 MHz 互连复位；`rst_hdmi_pixel` 由 Dynamic Clock LOCKED_O 同步释放 VTC/Video Out 像素域复位。AXI VDMA `axi_resetn` 保持 50 MHz AXI-Lite 域同步复位，符合 PG020 说明。
- Dynamic Clock、VTC、VDMA 未接 PS IRQ，A 第一轮使用 MMIO 状态轮询。若未来要中断驱动，需重新设计 BD 与软件。

## Warning 判读

BD 的 HP0 AWID/ARID/WID 端口提示 2-bit→6-bit 宽度不一致：三路 master 仲裁最多需 2 位 ID，互连使用低 2 位，PS 高位补 0；当前报告没有 ID 资源不足错误。仍需在 A 的 H4 中让灰度 DMA 与 HDMI VDMA 同时工作，排除动态争用/吞吐问题。

“Unable to find an associated reset port”是 PS GP0/HP0 接口元数据提示；实际 AXI 互连和各 IP reset 已在 BD 中连线。早期时钟缓冲版本的 BRAM 异步控制 Warning 已在最终 No_buffer 版本中消失。最终路由 DRC 为 0 Error、0 Critical Warning、9 Warning、4 Advisory；方法学仍有 TIMING-9（VTC 内部 CDC）、TIMING-18（异步 HDMI reset 输出无 delay）及 TIMING-30（自动生成时钟源选择）Warning。首次板端复位、VDMA status 和画面稳定性仍需检查；静态 DRC 不能替代实机验收。

依据：[AMD AXI VDMA v6.3 PG020](https://docs.amd.com/r/en-US/pg020_axi_vdma/Overview)、[AMD VDMA Clocking](https://docs.amd.com/r/en-US/pg020_axi_vdma/Clocking)、[AMD Video Out v4.0 PG044](https://docs.amd.com/r/en-US/pg044_v_axis_vid_out/Overview)。

