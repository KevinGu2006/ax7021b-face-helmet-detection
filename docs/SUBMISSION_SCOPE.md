# 本次提交范围

最终算法以algorithm/为准，不需要安装训练框架。integration/a_original是参考旧版，不能用它替换algorithm/A_patch之后又期待得到双任务结果。训练尝试、未采用模型、虚拟环境、聊天附件和个人文件不属于运行版本。

本仓库包含全部当前收到并选定用于交付的算法及接入源码，以及A提供的HDMI候选产物。没有收到的camera_hdmi_async/async_pipeline、Vivado完整工程和灰度RTL不能凭空补齐；依赖详见根README。这不是整板从零综合的承诺。

原PC回归日志与validation.json保留为历史证据；公开版照片改为按源下载，不修改算法权重/阈值/关联策略。运行validate.py后会在本地生成examples/，因此交付报告中的examples/008.png、010.png反例可以重新得到。未将已有反例删除成“全部正确”的展示。

根目录公开清单SHA256SUMS.json记录本次文件哈希（不含其自身和.git）。不同操作系统检出时注意Git换行转换；仓库设置.gitattributes固定文本LF。
