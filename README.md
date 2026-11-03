# AX7021B 人脸检测与安全帽佩戴判断

FPGA大赛作品代码提交版，整理日期2026-11-03。默认流程：**Haar人脸检测 → NCNN640安全帽模型 → 同帧一对一关联 → 标注人脸及佩戴状态**。

本仓库提供当前可用算法、权重、AX7021B接入补丁、灰度转换参考和已有HDMI候选产物。算法可以在PC独立运行；C端灰度RTL、DMA/HDMI BD Tcl和原始连续软件已补入；整板运行仍依赖A端PYNQ兼容入口及部分外部组件，具体缺项见下文。

## 获取与快速运行

点击GitHub的 **Code → Download ZIP** 下载，或使用git clone本仓库地址。模型已经随代码提供，无需训练。

```bash
cd algorithm
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python infer.py --input /path/to/image.jpg --output outputs
```

推荐PC环境为Python3.10/3.11，依赖版本见algorithm/requirements.txt。运行输出标注PNG、JSON以及summary.json。首次创建模型后循环复用，不要每张图启动新解释器。完全在本地CPU执行，不上传摄像头图像。

输入为uint8 BGR图像；输出每个人脸的face_bbox、helmet_bbox、helmet_status及分阶段耗时。三态为helmet、no_helmet、unknown。只做检测，不做身份识别。

## 目录

|目录|内容|
|---|---|
|[algorithm/](algorithm/README.md)|最终联合流程、CLI、模型、ARM wheel、测试和A接入补丁|
|[pl_tools/](pl_tools/Face_PL_Operator_Spec.md)|BGR/灰度数值参考、测试向量和逐像素比较工具|
|[integration/a_original/](integration/a_original/)|A提供的原后台源码，作为参考；联合版本用algorithm/A_patch|
|[integration/board_adaptation/](integration/board_adaptation/)|A提供的原始头导出工具与板端适配记录|
|[integration/hdmi_candidate/](integration/hdmi_candidate/)|A提供的HDMI候选bit/hwh/xsa和PS控制源码|
|[hardware/](C_CONTRIBUTION.md)|C端灰度RTL/仿真、DMA与HDMI合并BD Tcl、XDC和IP封装|
|[runtime/c_continuous_rc1/](runtime/c_continuous_rc1/README.md)|C原始异步/同步连续软件与离线Fake测试，非A最终兼容版本|
|[verification/](verification/README.md)|C提供的历史验证摘要，以及本次合并的独立检查记录|
|[docs/](docs/BUILD_VIVADO.md)|Vivado重建步骤、硬件架构、性能诊断与提交范围|

灰度仿真向量已打包为pl_tools/golden_vectors.zip，包含26组图像和32个像素向量；解压后用于RTL比较，也可运行face_preproc_reference.py重新生成。

## 测试

```bash
cd algorithm
python fetch_test_inputs.py
python tests.py
python validate.py
python board_benchmark.py --image /path/to/image.jpg --repeats 5
```

照片从明确记录的上游地址下载并验证SHA256，不在公开仓库中重复发布。下载需要网络；数据集ZIP可能较大。也可用自己的图片运行CLI。公开照片及数据集权利仍归原权利人，下载前请核对来源条款。

已有记录：12项测试通过；32张图片的人脸框与原版一致；21张有脸图片的安全帽模型结果与单独运行一致。PC有脸图片的完整算法耗时中位数约284ms（不含相机、DMA、HDMI或初始化），**不是AX7021B帧率**。详细说明见[交付报告](algorithm/交付报告.md)。

## AX7021B / PYNQ接入

使用algorithm/作为板端B_combined_v5目录，先正常停止旧后台，按[接入说明](algorithm/README.md)使用A_patch。ARMv7l/CPython3.10/glibc≥2.31可使用项目自带官方NCNN wheel局部安装；不要直接用PC requirements覆盖板端系统环境。OpenCV raw-head的board640后端可回退，但可能仍很慢。

PL灰度可通过run(frame_bgr, gray_image=..., original_shape=...)传入；原彩色图保留用于安全帽网络。当前A_patch走CPU路径，没有伪称已调用PL。

## C端源码补充与复现边界

本次新增[贡献索引](C_CONTRIBUTION.md)、[硬件架构](docs/HARDWARE_ARCHITECTURE.md)与[Vivado 2025.2构建说明](docs/BUILD_VIVADO.md)。灰度RTL和DMA BD Tcl现已提供；灰度输入BGRX32、输出Gray8，帧末TLAST，与HDMI行末TLAST分开。以下命令只在本地做Fake验证，不访问相机或FPGA：

```bash
python runtime/c_continuous_rc1/05_Tests/run_offline_tests.py
```

**运行版本要区分**：runtime/c_continuous_rc1是C的原始RC1，补齐了camera_hdmi_async/async_pipeline源码，但不含A后来的主线程Device.active_device兼容修复；不能直接把该目录冒充/home/xilinx/A_compat_RC1的最终板端入口。不要覆盖板端正在使用的A兼容版本。其余a_gray_dma_fast、pipeline_api等依赖及路径见[连续软件说明](runtime/c_continuous_rc1/README.md)。

**硬件构建仍有依赖**：HDMI BD Tcl、XDC和灰度IP已补齐；Dynamic Clock第三方HDL仍需按[来源与哈希说明](hardware/hdmi_gray_dma/DYNAMIC_CLOCK_SOURCE.md)合法取得。公开树尚不能独立从零生成同一HDMI bit，新增Tcl重建也不等于已重新综合、实施或逐位验证现有候选产物。本次合并没有运行Vivado或开发板，包内历史结果与本次检查分别记录。

本次合并检查：25项离线Fake测试全部通过；308,255个参考像素复算差异为0（不是RTL仿真或板端测量）。记录见[合并检查](verification/c_merge_checks_20261103.json)与[Fake测试日志](verification/c_merge_offline_tests.log)。

原C包文件保持原始字节，SHA256SUMS.txt验证该贡献包的内容；根SHA256SUMS.json记录合并后的仓库全部提交文件，两者用途不同。
## 质量边界

联合接口及结果一致性已经验证，现场识别可靠性尚未验收。原安全帽模型仍会把部分普通人脸误报为戴帽；Haar也会漏检小脸、侧脸、遮挡和背面。无脸时跳过安全帽模型，不表示现场无人或所有人安全。无法关联或证据不足时输出unknown。本项目不能作为已经通过验收的安全防护系统。

保留640输入，不通过默认降低分辨率换取演示速度。模型常驻，每帧最多一次安全帽推理；多脸不会重复执行整网。进一步现场改进需要独立采集并标注实际摄像头的数据。

## 来源与许可

模型基于[keremberke/yolov8n-hard-hat-detection](https://huggingface.co/keremberke/yolov8n-hard-hat-detection)，不是本项目从零训练的新网络。原模型说明、NCNN、Ultralytics和OpenCV许可文件均保留。各组件按各自许可使用；请阅读[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。项目资料未统一授权为MIT，第三方权重、照片和厂商IP也不因此改变授权。
