# 本次提交范围

最终算法以algorithm/为准，不需要安装训练框架。integration/a_original是参考旧版，不能用它替换algorithm/A_patch之后又期待得到双任务结果。训练尝试、未采用模型、虚拟环境、聊天附件和个人文件不属于运行版本。

本仓库包含全部当前收到并选定用于交付的算法及接入源码，以及A提供的HDMI候选产物。2026-11-03补入C端camera_hdmi_async/async_pipeline原始RC1、灰度RTL及DMA/HDMI BD Tcl、XDC和IP封装。A后续板端兼容补丁及Dynamic Clock第三方HDL仍不在新增包中；依赖详见根README与C_CONTRIBUTION.md。这不是整板从零综合或新增板端验收的承诺。

原PC回归日志与validation.json保留为历史证据；公开版照片改为按源下载，不修改算法权重/阈值/关联策略。运行validate.py后会在本地生成examples/，因此交付报告中的examples/008.png、010.png反例可以重新得到。未将已有反例删除成“全部正确”的展示。

根目录公开清单SHA256SUMS.json记录提交文件哈希（不含其自身和.git）。原有文本保持LF；新增C包文件按.gitattributes中的精确范围关闭换行转换，以保留SHA256SUMS.txt所记录的原始字节。
