# 来源与许可

- 安全帽模型：keremberke/yolov8n-hard-hat-detection，模型卡：https://huggingface.co/keremberke/yolov8n-hard-hat-detection 。模型卡副本位于algorithm/models/SOURCE_README.md。转换为NCNN和原始头ONNX不改变权重来源。
- Ultralytics相关代码/工具：保留algorithm/ULTRALYTICS_LICENSE.txt；不能据此将项目依赖重新授权为MIT。
- NCNN及随附ARM wheel：algorithm/NCNN_LICENSE.txt；wheel来源与SHA256见algorithm/wheels/source.json。
- OpenCV/Haar：pl_tools/opencv_LICENSE.txt；XML内也保留上游许可。
- OpenCV测试照片：仅提供固定修订版URL和哈希，由使用者显式下载；照片版权不因OpenCV仓库许可证自动转移。参考pl_tools/opencv_extra_RIGHTS.txt。
- 安全帽测试图来自keremberke/hard-hat-detection固定修订测试集，来源、原始文件名、标签和数据集许可记录见algorithm/test_inputs/dataset_manifest.json。数据集来源记录标注CC BY 4.0，使用前仍应核对上游条款。
- A端HDMI参考C代码、生成硬件产物可能依赖AMD/Xilinx或板卡厂商组件，原文件头保留；不意味着可按本项目名义转授权厂商IP。

本次整理不替作者统一授予新的开源许可证。自有代码和第三方组件应分别按适用授权使用；公开可下载不等于第三方内容无版权限制。
