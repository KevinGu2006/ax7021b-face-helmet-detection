# 人脸检测 + 安全帽状态联合流程（2026-11-02）

本版默认先检测人脸，再对检出的人脸关联安全帽状态，最终同时显示脸框与helmet/no_helmet/unknown。人脸框来自原Haar检测器，不将安全帽/头部框冒充人脸。保留原640分辨率与参数，安全帽默认使用已做PC一致性验证的NCNN640，未自动降为320/480。

## 推荐调用

```python
from combined_pipeline import CombinedPipeline

# 初始化一次，放在循环外；实际在板端运行才声明ZYNQ_ARM。
pipeline = CombinedPipeline(helmet_profile='ncnn640', execution_backend='ZYNQ_ARM')
annotated_bgr, record = pipeline.run(frame_bgr)
```

输入uint8 H×W×3 BGR。输出图像副本和结构化record：face_count、detections、helmet_detections、unassociated_heads、timings_ms、execution_backend。每条人脸结果包含face_index（仅本帧序号）、face_bbox、helmet_status、helmet_bbox、helmet_score、association_score、reason。坐标为原图[x1,y1,x2,y2)，不包含右下端点。face_index不是身份识别或持续跟踪ID；score/association_score不是经校准的正确概率。

想保留旧A预览的“图像、检测列表”形式：

```python
from algorithm import configure, process_frame
pipeline = configure(helmet_profile='ncnn640', execution_backend='ZYNQ_ARM')
annotated_bgr, detections = process_frame(frame_bgr)
record = pipeline.last_record
```

这一版algorithm入口已经同时做人脸与安全帽。请勿在前面再调用一次旧FacePipeline，否则会重复Haar计算。也不要仍然导入旧B目录的algorithm模块。

## 原有PL灰度接口继续可用

原始彩色图保留给安全帽模型。PL灰度只供Haar：

```python
small_bgr = pipeline.face.prepare_bgr_for_pl(frame_bgr)
gray_from_pl = run_preproc(small_bgr)  # A/C现有、已验证的调用
annotated, record = pipeline.run(frame_bgr, gray_image=gray_from_pl,
    original_shape=frame_bgr.shape[:2], gray_execution_backend='ZYNQ_PL')
```

PL输入准备保持原最长边640，不修改DMA/HDMI/Overlay。frame_bgr和gray必须属于同一帧；尺寸校验无法识别跨帧错配，A需保留帧号。函数不能在灰度分支重新转成伪彩色来做安全帽判断。

## 质量策略与边界

- Haar和安全帽模型均只初始化一次。Haar检出几个人脸，均保留在结果中；没有对应安全帽证据时保留脸框并输出unknown，不能将其默认当未戴帽。
- 每帧安全帽模型最多执行一次，用完整原BGR推理，不逐人裁图重复推理。按空间约束和双向歧义保护建立一对一关联；共享帽框、多人挤在一起、匹配不清楚时unknown。
- 无人脸时默认跳过安全帽模型，输出skipped_no_faces。它表示本流程没有可评价的人脸，不表示无人、所有工人安全或未戴帽人员为0。背对镜头、强遮挡和Haar漏检不在本版可评价范围。
- 有脸但模型检出的其他头部不能关联时保存在unassociated_heads，画灰色未关联头框，不把它们强塞给最近的人脸。
- 保留旧安全帽模型的低分、小目标、触边和类别冲突拒判。关联几何规则是工程初值，不是经过现场验证的佩戴关系模型；没有独立关联标注时不能报告真实关联准确率。
- 原安全帽模型可靠性尚未达到现场验收，本次组合不会自动修复其误判。普通人脸/普通帽/背景仍可能被模型误判为安全帽，不能将绿色框当成可靠防护证明。Haar原来的漏检限制也仍然存在。

## A后台接入

解压到独立目录，如/home/xilinx/B_combined_v5。已有匹配的NCNN环境可直接使用；如尚未安装，可复用本包install_board_ncnn.py和官方wheel（仅ARMv7l、CPython3.10、glibc>=2.31，项目局部安装）。不要升级现有系统OpenCV/PYNQ。board640为OpenCV原始头回退版本，但耗时可能仍很高。

A_patch/基于你提供的后台包，保留相机/线程/历史小图/停止和显示锁，只改算法路径、记录联合结果、更新任务标签。它依赖A已有/home/xilinx/A_compat_RC1，非完整系统镜像。

先通过原按钮正常停止旧后台并等待退出，再在Notebook运行：

```python
import os, importlib.util
os.environ['B_ALGORITHM_DIR'] = '/home/xilinx/B_combined_v5'
os.environ['HELMET_PROFILE'] = 'ncnn640'
os.environ['VISION_EXECUTION_BACKEND'] = 'ZYNQ_ARM'
spec = importlib.util.spec_from_file_location('combined_controls',
    '/home/xilinx/B_combined_v5/A_patch/helmet_controls.py')
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)
controls.start(seconds=60)
```

用controls.status()查看latest_face_count、latest_record；controls.stop()正常停止。仍然把完成的框画在同一历史源图，不能将旧人脸/帽子框叠在当前实时画面。原后台和本版不能同时占用摄像头/HDMI。

## PC测试与CLI

已有依赖参考requirements.txt；NCNN推理另需ncnn==1.0.20261020。推理不用PyTorch，不会发送图像到远端。

```powershell
python tests.py
python infer.py --input example.jpg --output outputs
python infer.py --input pictures --output outputs/batch --profile ncnn640
```

输出标注PNG、同名JSON和summary.json；异常非零退出并保存error.json。目录处理遇错即停止，不把错误伪装为未检出。

examples/是真实图片与结果，validation.json为实测记录。PC耗时不等于板端耗时；本版没有新的AX7021B运行证据，不能把单模型NCNN提速外推成双任务总帧率。详见交付报告。原有模型来源和许可证保留在models/SOURCE_README.md与许可文件中。
