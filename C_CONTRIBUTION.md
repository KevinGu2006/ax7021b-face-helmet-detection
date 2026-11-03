# C 负责的 AX7021B FPGA 与连续显示源码

本目录只整理 C 负责的工作，供合并到现有公开仓库：BGR→Gray RTL、灰度 DMA 与 HDMI 合并 Vivado 设计、C 开发的同步/异步连续检测软件，以及 C 的 RTL/Vivado/Windows Fake 验证摘要。**不包含** B 的人脸/安全帽算法和模型、A 的板端兼容补丁或实机原始日志，也不重复上传现有仓库的 HDMI_CANDIDATE bit/hwh/xsa。

## C 的硬件贡献

| 路径 | 内容 |
| --- | --- |
| `hardware/gray_ip/` | `bgr2gray_axis.v`、SystemVerilog testbench、Q15 灰度接口、随机黄金向量及测试脚本 |
| `hardware/gray_dma/` | AXI DMA Simple Mode 灰度数据通路、IP 封装、Vivado BD Tcl、地址与 PS 配置资料 |
| `hardware/hdmi_gray_dma/` | 保留灰度 DMA 的 HDMI 合并 BD Tcl、HDMI XDC、SiI9134 初始化说明、VDMA/VTC/动态时钟参数 |
| `docs/` | 架构和 Vivado 2025.2 重建步骤 |
| `verification/` | C 的仿真、独立综合及 BD 重建检查摘要 |

AXI DMA 输入 BGRX32、输出 Gray8，RTL 计算 `Y=(3735*B+19235*G+9798*R+16384)>>15`。灰度 DMA 的 TLAST 是整帧最后一像素；HDMI 视频流的 TLAST 是行末，两条流独立。AXI DMA `axi_dma_0` 控制基址 `0x40400000`，显示 VDMA `axi_vdma_0` 为 `0x43000000`。详情见 [硬件架构](docs/HARDWARE_ARCHITECTURE.md)。Haar 和 NCNN/YOLO 由 ARM CPU 执行，本项目没有在 PL 上实现 YOLO 推理。

## C 的连续软件

`runtime/c_continuous_rc1/` 是 C 的原始 RC1：异步最新帧采集、独立检测 Worker、HDMI Worker，附同步回退和 Fake 测试。此目录**不含 A 后来提供的 PYNQ 主线程 `Device.active_device` 兼容修复**。因此它展示 C 的原始实现，不能标成 A 的最终已上板可运行版本。A 的修复后版本与 5 帧、100 帧、5 分钟实机记录由 A 持有；合并仓库时请由 A 决定是否另行公开其补丁。运行与资源所有权见 [连续软件说明](runtime/c_continuous_rc1/README.md)。

## 本包实际检查

- 历史完整 RTL 验证：Vivado 2025.2 xsim 32 帧、2,065,095 像素，黄金误差 0；独立综合 4 LUT、10 FF、3 DSP48E1、0 BRAM。
- 本次可公开向量复测：3 帧、308,255 像素，xsim PASS；独立综合 PASS，同样 4 LUT、10 FF、3 DSP48E1、0 BRAM；没有时序约束。
- 本次 `hardware/gray_dma/rebuild_gray_project.tcl` 在独立新工程成功重建 BD，生成 Wrapper 和 HWH，Validate 通过；没有重新综合/实现。
- HDMI 合并工程此前已完成 Vivado 2025.2 实现及 BD Tcl smoke 重建；本包没有重新实现，也没有证明重新生成 bit 与现有 HDMI_CANDIDATE 逐位一致。
- C 原 RC1 的 Windows Fake 测试原包 25 项通过。本源码精简包没有重复包含 HDMI 二进制，独立运行时其中 2 项哈希/启动测试跳过；其余 23 项可运行。Fake 测试不是 FPGA 实机性能。

## 手工合并到现有仓库

把本目录的 `hardware/`、`runtime/c_continuous_rc1/`、`verification/` 与 `docs/` 新文件合并到最新 main。不要用本 README 覆盖现有根 README；建议在现有 README 的目录/硬件/验证段增加指向本文件的链接，并根据实际合并情况修正旧“缺少 RTL / Vivado Tcl”描述。现有 `algorithm/`、`pl_tools/`、`integration/hdmi_candidate/` 和 `THIRD_PARTY_NOTICES.md` 均保留原样。提交前重新校验 Git diff、相对链接、敏感文件和目标仓库的 SHA256 清单。

Dynamic Clock 的本地第三方 HDL 未放入公开包，原因与精确来源哈希见 [依赖说明](hardware/hdmi_gray_dma/DYNAMIC_CLOCK_SOURCE.md)。因此当前公开树不能独立从零重新生成 HDMI bit；需要从合法来源补齐该 IP、重新 Validate/实施并复核 800×600 时序。
