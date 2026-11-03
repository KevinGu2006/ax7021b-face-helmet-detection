# C 负责部分的验证

| 层级 | 真实结果 | 限制 |
| --- | --- | --- |
| 灰度 RTL 原始 xsim | 32 帧、2,065,095 像素、黄金误差 0 | 31 图像用例和 32 pixel CSV；完整原始向量含第三方照片，不在公开包 |
| 灰度 RTL 原始独立综合 | 4 LUT、10 FF、3 DSP48E1、0 BRAM | 未加时序约束 |
| 本次公开子集 xsim/综合 | 3 帧、308,255 像素 PASS；同样 4 LUT、10 FF、3 DSP、0 BRAM | 见 `public_subset_vivado_20261103.json`，与历史 32 帧分开 |
| 本次灰度 DMA BD 重建 | Vivado 2025.2 Tcl 生成 BD、Wrapper、HWH 并 Validate PASS | 没有重新跑综合、实施或板端 DMA |
| HDMI 合并工程 | 原实施 DRC 0 Error/Critical，WNS +4.172 ns、TNS 0；旧 smoke 验证 BD Tcl | 未做新 bit 等价重建；Dynamic Clock 源未公开 |
| C 连续软件 Fake | 原 RC1 包 Windows Fake 25 pass；本精简源码独立运行 23 pass / 2 skip | 跳过项依赖已有 HDMI bit/hwh；不是板端结果 |

A 的板端灰度 DMA 31 组、2,065,063 像素零误差，以及 HDMI 与异步程序板端结果属于 A 的联调证据。此 C 包引用该项目背景，但不复制 A 的原始日志或将其写成 C 自行执行的测试。公开仓库既有 `pl_tools/golden_vectors.zip` 的 26 图像用例与 C 原始 RTL 的 31 图像用例不是同一份完整公开集合，不能按数量猜出具体逐例关系。
