# 给仓库维护者的手工合并步骤

此包只含 C 负责部分。先从 GitHub 获取最新 `main` 的独立工作副本，再解压此包到临时目录。把 `hardware/`、`runtime/c_continuous_rc1/`、`verification/`、`docs/` 和 `C_CONTRIBUTION.md` 合并到仓库根目录。**不要用本包替换仓库现有的根 `README.md`、`algorithm/`、`pl_tools/`、`integration/`、模型或 HDMI_CANDIDATE bit/hwh/xsa。**

在现有根 README 的目录段加入一行，例如：`[C 的灰度 RTL、DMA/HDMI 工程与连续软件](C_CONTRIBUTION.md)`；原 README 中“缺少灰度 RTL、Vivado BD/Tcl、异步程序”的旧表述应按新实际文件修订，同时保留联合安全帽算法尚未板端验收、Dynamic Clock 第三方源缺失的限制。

提交前运行：

1. `git status` 和 `git diff --stat`，确认只新增/修改预期文件。
2. `python runtime/c_continuous_rc1/05_Tests/run_offline_tests.py`。需 Python 3.10 与 NumPy；两项二进制测试会在现有仓库的匹配 HDMI 文件路径可发现时运行，否则明确 skip。
3. 校验本包 `SHA256SUMS.txt`，并按合并后的真实内容更新仓库既有 `SHA256SUMS.json`。
4. 检查 README 相对链接、大文件、敏感信息及第三方许可。不要上传 Vivado runs/cache/gen、原厂大工程、A 原始日志或 B 模型副本。
5. 正常提交并推送，不使用 force push。推送后重新打开 GitHub 核对 RTL、Tcl、XDC、C 连续入口及文档确已显示。

Vivado 构建边界：灰度 IP 的公开子集已实际 xsim/综合；灰度 DMA 的新 Tcl 已实测 BD 重建 Validate。HDMI BD Tcl 的动态时钟源码因许可尚未包含，不能把此包描述为可独立生成同一 bit 的完整工程。A 的板端兼容修复属于 A 的交付，本 C 包只保留 C 原始 RC1 软件。
