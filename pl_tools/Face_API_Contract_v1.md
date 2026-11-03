# 独立人脸 API v1

日期：2026-10-27。当前实测平台为 Windows PC；不依赖安全帽模型、PyTorch、TensorFlow 或 PYNQ。参考依赖为 Python 3.12.7 / NumPy 1.26.4 / OpenCV 4.10.0。固定 requirements 面向 Python 3.9–3.12；未验证旧板端 Python 3.4.2。

## 直接调用

```python
from face_detection import FaceDetector, detect_faces, detect_faces_gray

detector = FaceDetector()  # 初始化一次，重复调用；并发时每个工作线程单独实例
face_bboxes = detector.detect_faces(frame_bgr)
face_bboxes = detector.detect_faces_gray(gray_image)  # 完整原尺寸灰度

# 对齐旧流程的推荐 PL 路径
small_bgr = detector.prepare_bgr_for_pl(frame_bgr)
gray_from_pl = run_preproc(small_bgr)  # A/C 提供真实 DMA 调用
face_bboxes = detector.detect_faces_gray(gray_from_pl, original_shape=frame_bgr.shape[:2])
```

BGR 接口只接受 uint8 H×W×3；灰度接口只接受 uint8 H×W，不接受三通道灰度、float 或空数组。人脸输入 H/W 至少为2。RGB 输入先显式 `cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)`；灰度不能通过复制三通道再转灰度的方式接入。

框为原始图像像素 `[x1,y1,x2,y2)`，整数、右下不包含。直接函数返回框列表；`[]` 表示未检出人脸，不能解释为没有人或佩戴合规。异常会抛出，不转为空框。

提供 `original_shape` 时，其含义是原图 `(H,W)`，灰度必须恰好等于 `prepare_bgr_for_pl` 的预期输出尺寸；PS 不会再次缩放。没有此参数时，灰度视为原尺寸图像并按最长边缩放。原始 BGR 和灰度必须来自同一帧、方向一致；仅形状检查无法发现跨帧错配，A 应维护帧号。

## 预处理及参数

BGR 默认路径：最长边缩到640（不放大；宽高用 Python round；INTER_LINEAR）→ cvtColor(BGR2GRAY) → equalizeHist → frontal Haar → 映射 → 去重。可选侧脸及水平翻转。`detect_faces_gray` 从灰度缩放/均衡化进入后续相同阶段，不做 BGR2GRAY。

默认 scaleFactor=1.1、minNeighbors=5、min_face=24；实际检测器的 minSize 为 `max(12, round(min_face/max(sx,sy)))`，默认24并不等于24像素人脸必然检出。Haar 的基础窗口、视角、图像质量和缩放都会影响可检尺寸。可通过构造参数配置 `max_detection_side`、`scale_factor`、`min_neighbors` 和 `use_profile`。

人脸模块 `face_detection.py` 不导入安全帽分类器；`face_geometry.py` 提供共用几何逻辑。检测 XML 默认从 `models/` 或 `cv2.data.haarcascades` 加载，缺失或无效即报错。交付内附 OpenCV 原始 XML 和许可文本；人脸 Haar 分数未标定，结构化输出 `score=null`，不伪造置信度。

## 调度与绘图

```python
from pipeline_api import FacePipeline
pipe = FacePipeline()  # face_only 默认，不加载帽子模型
annotated_bgr, record = pipe.process_frame(frame_bgr)

# 已缩放 BGR 的 PL 灰度，与原始彩色图分别传递
annotated_bgr, record = pipe.process_frame(
    frame_bgr, gray_image=gray_from_pl, original_shape=frame_bgr.shape[:2],
    gray_execution_backend="ZYNQ_PL")  # 只在实机证据成立时如此标注
```

record 包含 `schema_version`、`mode`、`face_detected`、`face_count`、`face_backend`、`detections`、`processing_ms`、`timings_ms`、`execution_backend`、`external_gray`。每条检测有 `face_bbox`、`face_detected=true`、`face_backend`、`score=null`。face时间覆盖该入口内的人脸预处理、检测及坐标处理，不包括上游外部灰度运算/搬运；`pl_integration_example` 另记录准备、回调和完整端到端耗时。

安全帽可选：`FacePipeline(mode="face_then_helmet", helmet_mode="svm", model_path=...)`；真实模型未交付时会报错。显式 `helmet_mode="heuristic"` 仅作颜色演示，出现警告，不能当成真实识别精度。`classify_helmet(frame_bgr, face_bboxes)` 是 pipeline 实例方法；`render_results` 独立导出。保留的 `algorithm.process_frame` 仍返回旧版标注图和安全帽结果，不更改其默认行为或分类数学逻辑。

后端标记默认 PC。PS 端可构造 `FacePipeline(execution_backend="ZYNQ_ARM")`；标记属于调用者声明，不是平台自动认证。外部灰度默认 `EXTERNAL_UNVERIFIED`。CPU 参考回调必须标为 PC。只测 PC 回调不构成板端或 PL 运行证据。

## 单图与批量 CLI

```powershell
python infer_face_cli.py --input test_images/lena.jpg --output outputs/lena
python infer_face_cli.py --input test_images --output outputs/batch
python infer_face_cli.py --input test_images/lena.jpg --gray golden_vectors/photo_lena/expected_gray.png --output outputs/gray
# 对已预缩放图像生成的 PL 输出，加 --gray-resized。
```

保存每张标注 PNG、同名 JSON 和 summary.json。目录递归处理，结果带序号避免同名覆盖。`--gray` 只允许单图；读取时保留文件原通道和位深，不悄悄转灰度。正常（含无脸）退出0；输入、模型或推理异常退出1，写 error.json。参数用法错误由 argparse 退出2。损坏文件不能记成“无脸”；批量遇错即停止，既有结果保留。

输出含人脸框和耗时，属于检测/定位，不包含身份识别。照片来源及使用条件见 sources/provenance 文件；公开测试图片不是工地数据或安全帽标签。
