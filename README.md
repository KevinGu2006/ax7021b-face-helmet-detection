# AX7021B 人脸检测与安全帽佩戴判断

FPGA大赛作品代码提交版，整理日期2026-11-03。默认流程：**Haar人脸检测 → NCNN640安全帽模型 → 同帧一对一关联 → 标注人脸及佩戴状态**。

本仓库提供当前可用算法、权重、AX7021B接入补丁、灰度转换参考和已有HDMI候选产物。算法可以在PC独立运行；整板运行还依赖A端已有PYNQ环境和外部异步相机工程，具体缺项见下文。

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
|[docs/](docs/)|性能诊断、质量回归、提交范围说明|

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

**整板复现缺项**：A_patch仍依赖原/home/xilinx/A_compat_RC1/01_Async_Live中的camera_hdmi_async、async_pipeline及相应板端配置；它们不在本次收到的源文件内。HDMI候选资料没有完整Vivado BD/Tcl/约束/HDL源码；本仓库保留现有二进制产物，不保证能从零重新综合。灰度IP的RTL及DMA最终工程也未提供，不能以Python数值参考代替实际RTL。不要把本仓库描述为已完成从零重建的完整Vivado工程。

## 质量边界

联合接口及结果一致性已经验证，现场识别可靠性尚未验收。原安全帽模型仍会把部分普通人脸误报为戴帽；Haar也会漏检小脸、侧脸、遮挡和背面。无脸时跳过安全帽模型，不表示现场无人或所有人安全。无法关联或证据不足时输出unknown。本项目不能作为已经通过验收的安全防护系统。

保留640输入，不通过默认降低分辨率换取演示速度。模型常驻，每帧最多一次安全帽推理；多脸不会重复执行整网。进一步现场改进需要独立采集并标注实际摄像头的数据。

## 来源与许可

模型基于[keremberke/yolov8n-hard-hat-detection](https://huggingface.co/keremberke/yolov8n-hard-hat-detection)，不是本项目从零训练的新网络。原模型说明、NCNN、Ultralytics和OpenCV许可文件均保留。各组件按各自许可使用；请阅读[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。项目资料未统一授权为MIT，第三方权重、照片和厂商IP也不因此改变授权。
