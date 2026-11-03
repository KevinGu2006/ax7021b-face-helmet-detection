# 硬件架构与接口

AX7021B 的 ZYNQ PS 从 USB 摄像头取 BGR 图像，PS 将每像素打包成小端 `B,G,R,0` 的 `uint32`。PL 灰度 IP 计算 `Y=(3735B+19235G+9798R+16384)>>15`，AXI DMA Simple Mode 通过 HP0 在 DDR 与 PL 之间搬运。输入 AXI4-Stream 32 bit，输出 8 bit；DMA 与灰度 IP 使用**整帧末像素 TLAST**，支持背压。33×31 输出为 1,023 字节，S2MM DRE 与 1-byte TKEEP 用于非四字节长度。

HDMI 单独从 DDR 彩色帧缓冲读取：VDMA MM2S → AXI4-Stream to Video Out → 24-bit RGB888、HS/VS/DE/Pixel Clock → SiI9134。视频流 `TUSER` 是帧首、`TLAST` 是行末，不能和灰度 DMA 直接混接。VTC 产生时序；Dynamic Clock 运行时设置 800×600@60 的约 40 MHz 像素时钟。显示采用安全换帧，不能写 VDMA 正在扫描的 DDR 缓冲。

| 实例 | AXI-Lite 基址 | 用途 |
| --- | --- | --- |
| `axi_dma_0` | `0x40400000` | MM2S BGRX32 / S2MM Gray8；双 DRE；length width 26 |
| `hdmi_reset_gpio` | `0x41200000` | SiI9134 复位 |
| `axi_vdma_0` | `0x43000000` | DDR 彩色帧 → 视频流；3 帧缓存 |
| `v_tc_0` | `0x43C00000` | HDMI 视频时序 |
| `axi_dynclk_0` | `0x43C10000` | 可编程像素时钟 |

灰度路径 FCLK0 50 MHz；VDMA memory/stream 路径有独立 100 MHz 时钟，Video Out 内部异步 FIFO 跨到像素时钟。GP0 用于寄存器控制，HP0 访问 DDR。中断未接 PS，当前软件轮询状态。PS IIC0 EMIO 接 SiI9134；板端 Linux 驱动当前使用 `/dev/i2c-0`，具体映射由运行程序检查。

Haar 和 NCNN/YOLO 都在 ARM CPU 上运行。PL 计算限于灰度预处理及视频显示搬运，不含神经网络推理。
