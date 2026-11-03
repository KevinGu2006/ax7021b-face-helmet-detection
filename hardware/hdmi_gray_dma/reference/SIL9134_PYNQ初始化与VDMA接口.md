# AX7021B / SiI9134 的 PYNQ 初始化依据与接口

状态：HDMI_CANDIDATE 静态设计资料；没有在 A 的 Linux 或显示器上执行。单一控制者原则：若内核 DRM/VDMA 已绑定相同 IP，Python 不得再写其 MMIO。不得执行原厂裸机 `ps7_init`，不得改启动镜像/设备树。

## 原厂资料实读结果

来源为本机 `https://github.com/alinxalinx/AX7021B_2023.1 （course_s1_fpga/09_vdma_hdmi_out/Vitis/auto_create_vitis/src/vdma_hdmi）`：`main.c`、`i2c/PS_i2c.c`、`dynclk/dynclk.c/.h`、`display_ctrl/display_ctrl.c`、`display_ctrl/vga_modes.h`。这些文件是 ALINX Vivado 2023.1 裸机例程；此处只提取调用顺序和数值，不将其二进制程序用于 Linux。原厂仓库没有发现顶层 LICENSE 文件；引用时保留原路径和文件头。

`main.c` 实际调用 `DisplayInitialize` 后直接 `DisplayStart`。`DisplayInitialize` 默认 `VMODE_800x600`，所以原厂示例默认运行 **800×600@60、40 MHz**。其模式表另包含 **1280×720@60、74.25 MHz**；模式表存在不等于这份示例默认已用 720p 实测。建议 A 第一次 H1/H2 从 800×600 开始，然后验证 720p。

## 本候选硬件映射

| IP | 基地址 | 时钟/作用 |
| --- | --- | --- |
| `axi_dma_0` | `0x40400000` | 原灰度 DMA，50 MHz，MM2S 32-bit / S2MM 8-bit，HP0 |
| `hdmi_reset_gpio` | `0x41200000` | AXI GPIO channel 1 bit0 → SiI9134 reset_n，低有效 |
| `axi_vdma_0` | `0x43000000` | MM2S-only，3 frame stores，24-bit video stream，64-bit DDR read |
| `v_tc_0` | `0x43C00000` | 视频时序发生器，pixel clock 域 |
| `axi_dynclk_0` | `0x43C10000` | 可编程像素时钟；参考时钟 100 MHz |

PS FCLK0 保持原已验证的 50 MHz；PL Clocking Wizard 从它产生 100 MHz，供 Dynamic Clock 参考和 VDMA 存储器/视频数据通路。HP0 及 AXI-Lite 仍为 50 MHz，HP0 互连插入 AXI 时钟转换。Video Out 视频流侧 100 MHz、像素侧 40 或 74.25 MHz，由 IP 的异步 FIFO 跨域。VTC 与 Video Out 都用同一像素时钟，VTC 生成 timing，Video Out 配为 master timing mode（`C_VTG_MASTER_SLAVE=1`，原厂值）。新建的像素复位由 Dynamic Clock `LOCKED_O` 控制。灰度流的整帧 TLAST 与 VDMA 的行末 TLAST/帧首 TUSER 不连通。

## SiI9134 复位和 I²C

原厂 `main.c`：GPIO 输出设置为低，等待 **50 ms**，再置高；随后以 **100 kHz** I²C 写入：7-bit 地址 `0x39` 的寄存器 `0x08 = 0x35`；7-bit 地址 `0x3D` 的寄存器 `0x2F = 0x00`。源码使用 8-bit 形式 `0x72 >> 1` 和 `0x7A >> 1`，不要把 `0x72/0x7A` 作为 Linux `i2c-dev` 的 7-bit 地址。每笔需检查 ACK，失败时停止 H1 并保存总线号/错误码。GPIO channel 1 `DATA=base+0x00`、`TRI=base+0x04`；先写 TRI bit0=0 表示输出，再写 DATA bit0=0/1。首次板端执行由 A 人工确认。

本设计把 PS IIC0 经 EMIO 引至 SCL B22、SDA A22。A 的标准联调包没有提供当前 Linux 的 IIC0 设备树、`/dev/i2c-*` 总线映射或 SiI9134 驱动证据。A 先只读核查 `/dev/i2c*`、`i2cdetect -l`（仅列总线）、`/proc/device-tree`、`dmesg`，确定哪个总线是 PS IIC0（控制器物理基址 `0xE0004000`）及是否已经被驱动占用。随后再决定由 Linux `i2c-dev` 写两笔寄存器，或由已存在的单一驱动管理。不能仅因 HWH 导出 IIC0 EMIO 就假定当前运行 Linux 已启用该控制器。

## Dynamic Clock 与 VTC

原厂 `dynclk.h` 的寄存器偏移：CTRL `0x00`，STATUS `0x04`，CLK_L `0x08`，FB_L `0x0C`，FB_H_CLK_H `0x10`，DIV `0x14`，LOCK_L `0x18`，FLTR_LOCK_H `0x1C`。`dynclk.c` 的 `ClkFindParams` 固定假设 100 MHz 输入；本设计在 PL 内保证该参考频率。移植时用同版 `ClkFindParams → ClkFindReg → ClkWriteReg → ClkStop → ClkStart` 的算法及顺序，给每个状态轮询加超时，并检查 `STATUS[0]` 运行和 `LOCKED_O`/VTC 状态。不要把这些 DRP 寄存器当普通 MMCM 固定分频寄存器直接写一个频率值。

原厂 VTC 配置顺序：计算 porch/sync/active/polarity，`XVtc_RegUpdateEnable`，`XVtc_SetGeneratorTiming`，全部 `SourceSelect` 选 generator 寄存器，再 `XVtc_EnableGenerator`。VTC 必须使用 Dynamic Clock 的 pixel clock；Video Out 与 VTC 采用 master timing mode，不连接 Video Out `vtg_ce`，与原厂 Tcl 一致。

| 模式 | Active | H front/sync/back | H total | V front/sync/back | V total | 极性 | Pixel clock |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 原厂示例默认 | 800×600 | 40/128/88 | 1056 | 1/4/23 | 628 | H+ V+ | 40 MHz |
| 原厂模式表 | 1280×720 | 110/40/220 | 1650 | 5/5/20 | 750 | H+ V+ | 74.25 MHz |

以上数值由 `vga_modes.h` 的 `hps/hpe/hmax/vps/vpe/vmax` 转换，所有模式均为逐行扫描。当前硬件静态时序分析按 720p 74.25 MHz 进行；A 首次从 800×600 运行后再验证 720p。

## PYNQ VDMA MM2S

用 `pynq.allocate()` 分配 3 个物理连续帧缓冲；可先给 3 个起始地址都写同一张静态彩条图，之后再实现多缓冲切换。每个像素在 DDR 中是 **B、G、R** 三字节；原厂 `main.c` 的绘图代码明确依次写 `wBlue, wGreen, wRed`。Video Out 的流宽 24 bit，输出 RGB888 并行信号。A 必须用红/绿/蓝分区测试实际屏幕颜色次序。

依据 AMD PG020，MM2S 以 `CR(0x00)` 写 `RS=1, Circular_Park=1`，然后写 START_ADDRESS1..3 `0x5C/0x60/0x64`、STRIDE `0x58`、HSIZE `0x54`，最后写 VSIZE `0x50` 提交。SR `0x04` 的 bit0 为 Halted；错误位含 bit4/5/6/7 和 bit14。800×600 紧凑帧 `HSIZE=STRIDE=2400`、`VSIZE=600`、1,440,000 字节；720p 紧凑帧 `HSIZE=STRIDE=3840`、`VSIZE=720`、2,764,800 字节。两个 stride 都是 8 字节对齐。缓冲物理地址必须落入 HP0 DDR 可达的 `0x00000000..0x3FFFFFFF`，且帧尾未越界；启动前 flush cache，运行期间保留 buffer 对象，不能释放或重用。`pynq_vdma_mm2s.py` 提供纯 Python 计划校验、寄存器状态读取和启动顺序；导入不会触碰硬件。

原厂代码采用 `XAxiVdma_StartParking` 固定当前帧；本候选的 3 帧配置允许后续按帧边界切换，但 A 在确认 `PARK_PTR_REG` 和当前帧指针语义后再写多缓冲切换逻辑。单帧原地更新可能撕裂，H5 应测量并解决。

## A 需要先给出的只读证据

- `uname -a`、`ls -l /dev/i2c* /dev/dri/* /dev/fb* 2>&1`、`i2cdetect -l`、`lsmod` 相关模块、`dmesg` HDMI/I2C/VDMA/VTC 片段。
- PS IIC0 的设备树 status、是否绑定 Linux 驱动，I²C bus number 与 `0xE0004000` 的对应关系；SiI9134 是否已有驱动独占。
- 若有 DRM/framebuffer，确认是否控制同一 VDMA/VTC/Dynamic Clock；若有，停止 Python MMIO 路线并先协调单一控制者。
- A 人工加载候选 Overlay 后，保存 50 MHz FCLK0、Dynamic Clock STATUS、GPIO、VTC 和 VDMA 状态寄存器快照及显示器 OSD。此步骤不由本交付自动执行。

依据：[AMD AXI VDMA PG020 编程顺序](https://docs.amd.com/r/en-US/pg020_axi_vdma/Programming-Sequence)、[AMD PG020 时钟模式](https://docs.amd.com/r/en-US/pg020_axi_vdma/Clocking)、[AMD AXI4-Stream to Video Out PG044](https://docs.amd.com/r/en-US/pg044_v_axis_vid_out/Overview)。
