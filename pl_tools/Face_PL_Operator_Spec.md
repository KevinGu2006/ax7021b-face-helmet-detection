# 人脸灰度 PL 算子规范 v1

版本：`bgr_gray_q15_v1`；日期：2026-10-27。以下为 B 提议并已提供黄金数据的联调基线，C 应在交付硬件元数据中确认采用的流配置。未进行 RTL 仿真或开发板验证。

## 1. 实际进入 Haar 的位置

原流程：原始 BGR → 等比例缩放（最长边≤640，不放大，OpenCV INTER_LINEAR）→ BGR2GRAY → equalizeHist → Haar → 坐标映射到原图 → IoU 0.35 去重。

推荐 PL 插入：PS 保存原始 BGR → PS `prepare_bgr_for_pl` → PL 灰度 → PS `detect_faces_gray(gray, original_shape=frame_bgr.shape[:2])` → PS 均衡化、Haar、坐标还原 → 在原始 BGR 绘框。PL v1 不做缩放、均衡化、归一化或帽子识别。

`detect_faces_gray(full_gray)` 也接受原分辨率灰度，内部先缩放灰度再均衡化；大图时与旧流程的“缩放彩色再灰度”可能不同，不能要求检测框完全一致。推荐路径已经缩放后的灰度不要再缩放，不得把 `equalizeHist` 做两次。

## 2. 像素和数值

- 输入：uint8 BGR[H,W,3]，按 y 从上到下、x 从左到右、每像素 B/G/R 顺序。输出：uint8 Gray[H,W]。不涉及 gamma 线性化或视频 limited-range（16–235）转换。
- 连续输入算法表示每行 3W 字节；连续输出每行 W 字节。ROI/非连续 NumPy 视图应先 `np.ascontiguousarray`。DMA 输入采用下文 axis32 表示，每行 4W 字节。
- 固定整数参考：`Y = (3735*B + 19235*G + 9798*R + 16384) >> 15`。
- 正数加半后右移，即四舍五入、半值向上。先乘加，最后一次舍入；不能先逐项截断。不使用 Python `round()` 替代此规则。
- 系数和为 32768；最大带舍入累加值为 8,372,224，23 位无符号累加器足够。采用至少 23 位乘加中间量，避免 uint8 运算溢出。合法输入输出自然位于 0–255；若保留饱和逻辑，其范围也应为 0–255。
- 黑→0，白→255，纯 B/G/R 分别→29/150/76；所有 B=G=R=t 必须输出 t。

数值来源为 [OpenCV 4.10.0 常量](https://github.com/opencv/opencv/blob/4.10.0/modules/imgproc/src/color.simd_helpers.hpp) 与 [uint8 灰度实现](https://github.com/opencv/opencv/blob/4.10.0/modules/imgproc/src/color_rgb.simd.hpp)。OpenCV 当前算法使用 `cv2.cvtColor(..., cv2.COLOR_BGR2GRAY)`，以其作为软件比较基准。不同 OpenCV 构建或加速后端可能有 1 LSB 差异，因此固定整数公式是 RTL 的精确验收基准。

验收分两层：PL 对固定 Q15 黄金值必须逐像素误差 **0**；Q15 对目标 OpenCV BGR2GRAY 允许绝对误差 **≤1**（本机已生成向量实际为 0）。若 C 选择其他近似系数，要另设版本并重新验证，不把“允许 1”解释为可以任意偏置输出。1 LSB 像素误差不保证均衡化后的图像或 Haar 检测框仍完全相同，必须补测整链。

## 3. 推荐流配置：AXI DMA，整帧一个 packet

| 信号/约定 | 输入 | 输出 |
| --- | --- | --- |
| TDATA | 32 位，每拍一个像素；[7:0]=B，[15:8]=G，[23:16]=R，[31:24]=0 | 8 位，每拍一个 Y |
| TKEEP | `4'b1111`，高字节为有效的填充字节 | `1'b1` |
| TLAST | 只在整帧最后一个像素为 1 | 对应最后一个输出像素为 1 |
| TUSER | 不使用或固定为 0 | 不使用或固定为 0 |
| 行序 | 无填充、无空行、共 W×H 像素 | 无填充、共 W×H 像素 |
| 传输长度 | MM2S：4×W×H 字节 | S2MM：W×H 字节 |

`input_axis32.bin` 是每个字 0x00RRGGBB 的小端表示，内存字节为 B,G,R,0。`input_bgr24.bin` 是 B,G,R 三字节的数值参考表示，**不能直接当作此 32 位流的 DMA 缓冲区**。`.mem` 每行一个字，输入 8 位十六进制字符、输出 2 位字符，适合 `$readmemh`。

这是 AXI DMA 整帧 packet 配置；**AXI4-Stream Video/VDMA 的 TLAST 通常表示行末，TUSER 表示帧首，是另一种配置**。若接入原厂视频通路，必须由 C 提供适配层或另发视频流契约，不能直接混接两套 TLAST 语义。若 C 改为输入24位或输出32位，也必须更新打包、TKEEP、DMA长度和黄金文件说明。

只有 `TVALID && TREADY` 时消耗/产生一个像素。背压时输出 TDATA/TLAST/TKEEP 应保持稳定；不应丢像素或把 stall 周期计为像素。仿真需覆盖随机背压、连续帧、奇数尺寸、复位后第一帧和极值。复位中断帧由 PS 放弃，清理 DMA 后从完整帧重启；不要接着解释残余字节。

v1 建议支持 1≤W≤640、1≤H≤640，以覆盖最长边640的横图和竖图；首次可先跑320×240或640×480。黄金集中有1×1、单行、单列、奇数宽度。真实人脸接口要求H/W≥2。向量中的原尺寸大照片用于算子离线测试，实际检测工作尺寸见 `pl_demo_inputs`。C若仅实现固定VGA尺寸，须说明限制，不能将竖图直接送入；A/B需另行采用固定画布或修改 detector 参数并核对坐标。DMA最大传输长度、地址对齐、DRE、缓存和时钟由A/C实际设计确认。

[PYNQ DMA 文档](https://pynq.readthedocs.io/en/latest/pynq_libraries/dma.html) 指出示例 DMA 默认最大事务长度为14位、约16KB，并要求流末正确产生 TLAST。640×480 的输入为1,228,800字节，发送长度字段至少需要21位；输出为307,200字节，至少19位。先检查实际 IP 配置，避免直接以整帧长度调用默认 DMA。

## 4. A/C 的调用责任

`pl_integration_example.py` 的 `process_with_gray_provider` 已接好“PL 回调返回灰度→PS Haar”的软件路径，原始 BGR 不丢弃。`run_preproc(small_bgr)` 由 A/C 实现，必须在 DMA 完成后返回同尺寸连续 uint8 二维数组。

A/C 需从实际 `.bit/.hwh` 确认 DMA 实例、位宽、时钟/复位、最大长度、是否 scatter-gather、缓存一致性和恢复方式。先启动接收端再发送，正确 flush/invalidate，并配置超时/恢复；这里不假定某个 overlay 或 DMA 寄存器地址。不得仅修改后端标记就把 CPU 回调称为 PL。

## 5. 仿真与逐像素比较

```powershell
python face_preproc_reference.py --output golden_vectors --images test_images
python compare_pl_gray.py --case golden_vectors/random_33x31 --actual pl_gray.bin --output pl_compare.json
```

`pl_gray.bin` 必须是恰好 H×W 字节的原始灰度，无 BMP/PNG 文件头、无尾部 padding。比较脚本对形状/字节数量报错，对数值不一致返回非零退出码；也可以直接 `compare_gray(expected, actual, tolerance=0)`。

目前的自比较日志只验证比较工具，不是 C 的 RTL/PL 通过证据。实际比对时附 RTL/IP 版本、帧尺寸、源向量哈希、运行设备、输入输出字节数、错误像素数、最大误差，以及 CPU、DMA/拷贝、PL 内核、总链路分别计时。
