# Vivado 2025.2 构建说明

目标器件 `xc7z020clg484-2`。所有构建都应使用独立新目录，不覆盖已验证 bit/hwh/xsa。灰度 RTL 可在 `hardware/gray_ip` 中运行 `vivado -mode batch -source verify.tcl`；本公开目录提供 33×31、640×480 随机帧和像素 CSV，历史 32 帧覆盖报告不可误认作精简集的新运行结果。

## 灰度 DMA

`hardware/gray_dma/rebuild_bd.tcl` 为 Vivado 导出的 BD Tcl；`rebuild_gray_project.tcl` 负责在新的空目录中登记自定义 IP、建立工程、生成 Wrapper 并 Validate。调用方式为 `vivado -mode batch -source hardware/gray_dma/rebuild_gray_project.tcl -tclargs <新的空工程绝对路径>`。原项目的运行数据库和 bit 不包含于该精简源码树。具体 DMA 参数及地址参见同目录 README 与 reference。基于此快照新建工程后的综合/实现需要重新执行；原工程的 routed WNS +10.559 ns 不自动继承。

## HDMI + 灰度 DMA

先按 `hardware/hdmi_gray_dma/DYNAMIC_CLOCK_SOURCE.md` 获取与原设计匹配的 `axi_dynclk_v1_0`，置于 `hardware/hdmi_gray_dma/hdmi_reference/axi_dynclk_v1_0`。随后在 Vivado 2025.2 Batch 中调用：

```text
vivado -mode batch -source hardware/hdmi_gray_dma/rebuild_hdmi_project.tcl -tclargs <新的空工程绝对路径>
```

脚本创建 BD、Wrapper、XDC 并 Validate，**不会**自动产生 bit/hwh/xsa。若需候选输出，须另行综合、实现、检查 DRC、WNS/TNS、未约束路径和 XDC I/O 后，才从同一实现导出匹配的 bit/hwh/xsa。原版的 `rebuild_smoke.log` 只证明 BD 重建与 Validate 成功；这份公开快照尚未从零完成新的实现和二进制等价比对。

原始 HDMI 实现报告：route DRC 0 Error / 0 Critical Warning，WNS +4.172 ns，TNS 0；仍有时钟/异步复位方法学警告，应审阅。`hdmi_720p_timing.xdc` 是 74.25 MHz 候选静态约束，而 A 的实机模式为 800×600、40 MHz 动态编程。不要以 720p 约束通过来宣称 720p 板端已验证。
