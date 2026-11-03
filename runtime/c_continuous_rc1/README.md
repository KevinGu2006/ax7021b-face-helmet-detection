# C 的连续检测 RC1 原始源码

`01_Async_Live/camera_hdmi_async.py` 与 `async_pipeline.py` 实现单进程三 Worker：摄像头采集、PL 灰度 DMA + Haar 检测、HDMI 显示。容量 1 的最新帧缓冲丢弃过时帧；检测框带年龄并会过期；DMA 和 VDMA 各由单一 Worker 拥有。`02_Serial_Fallback/camera_hdmi_live.py` 是同步连续回退版本。`--backend pl` 要求真实 PL 灰度 DMA，不会静默切换 CPU；`--backend cpu` 用于对照。

这些是 C 的原始 RC1 文件，保留以展示软件架构。A 在真实 PYNQ 3.0.1 ARM32 环境中发现首次 `XrtDevice` 探测需在主线程完成，并在 A 自己的兼容包修复了入口。该修复**不在本 C 源码包中**，所以不要把本目录的入口直接作为“已通过 5 分钟实机”的最终运行版本。A 的实机版本应以 A 的兼容包为准，且不能用旧版覆盖板端现有程序。

板端需要 A 已配置的 `a_hdmi.py`、`pynq_vdma_mm2s.py`、`a_gray_dma_fast.py`、`pipeline_api.py`、`face_detection.py` 和匹配的 HDMI_CANDIDATE bit/hwh；程序 CLI 的 `--hdmi-root`、`--gray-root`、`--integration-root`、`--face-root` 指向这些目录。本包不重复复制 A 的模块、B 的检测算法或既有 HDMI 二进制。原单帧回退程序仍位于 A 的联调资料及公开仓库 `integration/`。

Windows Fake 测试命令：`python 05_Tests/run_offline_tests.py`。需要 Python 3.10 和 NumPy。独立源码包的两项 HDMI 二进制测试在未合并前跳过；合并到含匹配 bit/hwh 的完整仓库后重跑。停止程序应使用 Ctrl+C 或 `--max-frames` / `--max-seconds`，不要同时运行第二个抢占 DMA/VDMA 的实例。
