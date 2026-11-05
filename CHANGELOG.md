# 更新日志

## [1.1.0] - 2026-11-06
### 新增
- 网页版浏览器内转写（transformers.js + whisper-base 量化模型随站自托管 77MB）
- ?demo=1 自动演示全链路
### 优化
- 模型自托管替代第三方镜像（原镜像 CORS 锁死来源域名不可用）；体积 110MB→77MB

## [1.0.1] - 2026-11-06
### 修复
- [安全] 文件名清洗加固 + 导出下载容器校验
- 兼容 PyAV≥15（自解码 16kHz float32 直喂模型，不再依赖 faster-whisper 的 decode_audio）

## [1.0.0] - 2026-11-05
### 新增
- 桌面版（Flask + faster-whisper small）：拖入音频→带时间轴转写→导出 TXT/DOCX，完全离线
