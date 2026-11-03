# DMA and address map (from final gray_dma.hwh)

- IP full path: `/axi_dma_0`; top-level PYNQ key: `axi_dma_0`.
- AXI-Lite control: PS M_AXI_GP0 -> axi_ctrl_xbar -> DMA S_AXI_LITE, `0x40400000`–`0x4040FFFF`.
- MM2S memory read: DMA M_AXI_MM2S -> axi_hp0_xbar -> PS S_AXI_HP0, mapped `0x00000000`–`0x3FFFFFFF`.
- S2MM memory write: DMA M_AXI_S2MM -> axi_hp0_xbar -> PS S_AXI_HP0, mapped `0x00000000`–`0x3FFFFFFF`.
- Simple Mode: `C_INCLUDE_SG=0`, `C_MICRO_DMA=0`; both channels enabled. Memory-mapped width: 32 bits on both channels. Stream width: MM2S 32 bits, S2MM 8 bits. Both DREs enabled. Length width: 26 bits.
- Stream path: MM2S -> `bgr2gray_axis_0/s_axis` -> `bgr2gray_axis_0/m_axis` -> S2MM. Frame TLAST is preserved. Gray output TKEEP is always 1.
- Clock: PS FCLK_CLK0, 50 MHz, drives DMA, both interconnects, gray IP, HP0. Reset: `rst_ps7_0_50M/peripheral_aresetn` drives active-low AXI and gray resets.
- DMA interrupts are not connected to PS. Use status polling. Software must allocate physically reachable DDR buffers and handle cache synchronization.

These are static hardware design properties. No board DMA transfer has been verified.