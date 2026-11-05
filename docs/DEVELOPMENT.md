# 开发手册 · 录音转文字工作台

> 面向维护者与二次开发者。所有代码摘录均来自当前仓库真实源码；命令在 Windows（Git Bash / cmd）下可执行。
> 产品形态：**网页版**（浏览器内 Whisper，GitHub Pages / 镜像站直接用）+ **桌面版**（`desktop/` 双击即用，完全离线）。

---

## 1. 项目结构

```
luyin-zhuan-wenzi/
├── README.md                        # 产品说明（含徽章、截图、镜像地址）
├── CHANGELOG.md                     # 版本记录（1.0.0 桌面版 → 1.1.0 网页版+自托管模型）
├── LICENSE                          # MIT
├── .gitignore                       # 排除 desktop/server/models|输出|_tmp、.herenow、截图等
├── .github/workflows/pages.yml      # Pages 部署：以 web/ 为站点根，push main 即发布
├── docs/
│   ├── DEVELOPMENT.md               # 本手册
│   └── screenshots/                 # README 用截图（web-home.png / demo-result.png）
├── desktop/                         # —— 桌面版（拷目录即用）——
│   ├── 启动录音转文字.bat            # 入口：cd server && python server.py，失败时提示排查
│   ├── 下载模型.bat                  # 首次运行：从 hf-mirror 拉 faster-whisper-small（约 460MB）
│   └── server/
│       ├── server.py                # Flask 后端全部逻辑（约 250 行，见 §4.1）
│       ├── static/index.html        # 桌面版前端（由 Flask render_template 渲染）
│       ├── models/faster-whisper-small/   # 模型缓存（gitignore，由 下载模型.bat 生成）
│       ├── 输出/                     # 导出的 TXT/DOCX（gitignore）
│       └── _tmp/                     # 上传音频临时目录，转写完即删（gitignore）
└── web/                             # —— 网页版（纯静态，Pages 根）——
    ├── index.html                   # 单文件前端：UI + transformers.js 转写逻辑 + ?demo=1 自测
    ├── demo/sample-zh.mp3           # 42KB 内置中文样本，?demo=1 自动转写它
    └── models/whisper-base/         # ★ 77MB 自托管 ONNX 模型（随 git 仓库、随站发布）
        ├── config.json              # 模型结构配置（2.2KB）
        ├── generation_config.json   # 生成配置（3.8KB）
        ├── preprocessor_config.json # 特征提取：16k 采样、80 mel（339B）
        ├── quantize_config.json     # q8 量化元信息（2.8KB）
        ├── tokenizer.json           # 词表（2.4MB）
        ├── tokenizer_config.json    # tokenizer 配置（283KB）
        └── onnx/
            ├── encoder_model_quantized.onnx          # 23.2MB
            └── decoder_model_merged_quantized.onnx   # 53.7MB
```

### web/models/whisper-base 的来龙去脉（77MB 自托管模型）

- **为什么有这个目录**：网页版需要把 Whisper 模型下载进浏览器。早期版本 `env.remoteHost` 指向第三方镜像 hf-mirror.com（当时模型约 110MB），**实测其响应头 `Access-Control-Allow-Origin` 锁死为镜像自身域名**——GitHub Pages（或任何其他站点）上的页面跨源 fetch 模型时直接被浏览器 CORS 拦截，加载必然失败。
- **解法**：把 q8 量化后的 ONNX 模型（8 个文件共 79,680,741 字节 ≈ 77MB）直接提交进仓库 `web/models/whisper-base/`，与页面同源发布；transformers.js 的 `remoteHost` 指向自己的站点（见 §4.3）。体积也从 110MB 降到 77MB（fp16 → int8 量化）。
- **代价**：仓库与 Pages 构件变大（仍远低于 Pages 1GB 限制）；换模型要重新提交文件（见 §8.1）。
- 注意：README 功能表里「模型约 110MB，走 hf-mirror 镜像」是 1.1.0 之前的旧文案，以本节与 `web/index.html` 页面内说明（77MB 自托管）为准。

---

## 2. 技术栈与运行环境

| 端 | 组件 | 版本/说明 |
|---|---|---|
| 桌面 | Python | 3.10+（开发机实测 3.13.14；`启动录音转文字.bat` 失败提示里写的 3.13 即开发机版本） |
| 桌面 | Flask | 仅用 `Flask/joinify/render_template/send_file`，无额外扩展 |
| 桌面 | faster-whisper | **1.2.1**，CTranslate2 后端，CPU int8 推理 |
| 桌面 | PyAV | **任意新版即可（不要为兼容降级）**——自解码已绕开其与 faster-whisper 的 `metadata_errors` 冲突，见 §9.1 |
| 桌面 | python-docx | DOCX 导出 |
| 网页 | transformers.js | **3.3.1**，固定版本从 jsdelivr 引入：`https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.3.1` |
| 网页 | ONNX Runtime WASM | 由 transformers.js 自动加载（WebAssembly 后端，q8 模型） |
| 网页 | 模型 | whisper-base q8（自托管，见 §1） |
| 部署 | GitHub Pages | Actions 自动构建，站点根 = `web/`（模型随站发布） |
| 部署 | here.now 镜像 | 同一套 `web/` 目录整体发布：https://hazy-crystal-tqp9.here.now/ |

一次性安装（桌面端）：

```bash
pip install flask faster-whisper==1.2.1 python-docx av
```

> PyAV 不锁版本：Python 3.13 只有 PyAV≥15 的 cp313 wheel，旧版装不上——这正是 §4.1 自解码设计存在的原因。

---

## 3. 本地开发

### 3.1 桌面版

```bash
cd desktop/server
python server.py
# 控制台输出：录音转文字工作台 已启动：http://127.0.0.1:8765 （1 秒后自动开浏览器）
```

- 监听 `127.0.0.1`，端口从 **8765 起自动挑选空闲的 30 个之一（8765~8794）**，全占用则报「8765~8795 端口都被占用」（见 `pick_port()`）。
- 不想自动弹浏览器：设环境变量 `ZC_NO_BROWSER=1` 再启动（CI/验收脚本场景常用）。
- 首次运行若提示「模型缺失」，先执行 `desktop/下载模型.bat`（见 §7.3）。

### 3.2 网页版

```bash
cd web
python -m http.server 8000
# 打开 http://127.0.0.1:8000/
```

**必须在站点根 serve**：`http.server` 的工作目录就是站点根，`index.html` 与 `models/` 必须同处一个前缀下。子路径部署（如 Pages 项目页 `/luyin-zhuan-wenzi/`）已由 `SITE_ROOT` 推导兼容（§4.3），但**整站（含 models/）必须一起挪到同一子路径**，只把 `index.html` 放子路径会导致模型 404。

### 3.3 ?demo=1 自测模式

`web/index.html` 末尾内置全自动自测：URL 带 `?demo=1` 时，无需人工选文件，自动执行

**加载模型 → fetch 内置样本 `demo/sample-zh.mp3` → 解码 16k → 转写（language=zh）→ 渲染 → 判定**：

```js
const pass = (out.text || "").includes("第五章") || (out.text || "").includes("网络") || (out.text || "").includes("课本");
document.title = "DEMO " + (pass ? "PASS" : "FAIL") + ": " + (out.text || "").slice(0, 24);
```

- 任何一步失败（模型加载失败/解码异常）都会把 `document.title` 写成 `DEMO FAIL: <原因>`，同时 `#status` 区显示错误。
- 判定方式：肉眼看页面状态行，或无头浏览器读 `document.title`（配合 §6.3 的 shot.py 截图确认）。
- 这是**线上验收的标准动作**：每次发布后都应跑一遍（见 §10）。

---

## 4. 架构与关键实现

### 4.1 桌面转写流水线（desktop/server/server.py）

```
浏览器拖文件 ──POST /api/upload──▶ 存 _tmp/{uuid}_{safe_name}
                                     │ 起后台线程，job 入队（status=queued）
                                     ▼
              run_job(): _get_model() 懒加载 WhisperModel(int8)
                                     │ status=transcribing
                                     ▼
              decode_audio16k(): PyAV 自解码 → 16kHz 单声道 float32 ndarray
                                     ▼
              model.transcribe(audio, vad_filter=True, language?, initial_prompt?)
                                     │ 每段回调更新 progress = seg.end/info.duration
                                     ▼
              status=done（segments+text 落入内存 job）──▶ /api/export 导出 TXT/DOCX
```

要点逐一说明：

1. **job 队列**：`_jobs` 是进程内 dict，`threading.Thread(daemon=True)` 跑转写，前端轮询 `GET /api/job/{id}`。不做持久化——重启即清空（导出的文件在 `输出/` 里留存）。
2. **为何自解码（`decode_audio16k`）**——本项目最关键的一处兼容性设计：

   ```python
   def decode_audio16k(path: Path):
       """用本机 PyAV 解码为 16kHz 单声道 float32。
       不走 faster-whisper 的 decode_audio（新版 PyAV 已移除其使用的 metadata_errors 参数）。"""
       import numpy as np
       container = av.open(str(path), mode="r")
       stream = container.streams.audio[0]
       resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
       chunks = []
       for frame in container.decode(stream):
           for rf in resampler.resample(frame):
               chunks.append(rf.to_ndarray().reshape(-1))
       container.close()
       if not chunks:
           raise RuntimeError("音频解码失败：没有找到有效音轨")
       return np.concatenate(chunks).astype("float32") / 32768.0
   ```

   背景：faster-whisper 1.2.1 自带的 `decode_audio` 内部调用 `av.open(..., metadata_errors="ignore")`，而 **PyAV ≥15 已删除 `metadata_errors` 参数**，传入即 `TypeError`。想在依赖层解决就得降级 PyAV，但 Python 3.13（cp313）根本没有 PyAV 14 及以下的 wheel，**不可降级**。所以直接绕开它：自己用 PyAV 解码 + `AudioResampler` 重采样，产出与 `decode_audio` 等价的 float32 ndarray，直喂 `model.transcribe(audio_np, ...)`（faster-whisper 本来就接受 ndarray 输入）。
3. **转写参数与简体偏置**：

   ```python
   kwargs = dict(vad_filter=True, vad_parameters={"min_silence_duration_ms": 500})
   if lang and lang != "auto":
       kwargs["language"] = lang
       if lang == "zh":
           kwargs["initial_prompt"] = "以下是普通话的句子。"  # 偏置输出简体中文
   ```

   VAD 过滤静音段（500ms 静音切分）；中文时用 initial_prompt 把输出偏置为简体（whisper 默认常出繁体，见 §9.3）。
4. **分段与进度**：逐段消费生成器，`segs.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})`，`job["progress"] = min(99.0, seg.end / info.duration * 100.0)`（封顶 99，完成才置 100）。中文全文用 `"".join`（不加空格），英文用空格连接。
5. **失败语义**：任何异常落入 `status=error, error=str(e)`，前端能显示原因；`finally` 里删除临时音频文件（`unlink(missing_ok=True)`）。
6. **导出**：`export_txt` 以 **`utf-8-sig`** 写（带 BOM，Windows 记事本/Excel 直开不乱码）；`export_docx` 用 python-docx 生成「标题 + 分段稿（时间轴 9pt + 正文 12pt）+ 全文」。

### 4.2 网页转写流水线（web/index.html）

```
用户选文件 ──▶ file.arrayBuffer()
                 │
                 ▼
  decodeTo16kMono():
    AudioContext.decodeAudioData()          ← 浏览器原生解码 mp3/m4a/wav/flac/ogg/mp4…
    多声道混合为单声道（各声道 ÷ 声道数累加）
    OfflineAudioContext(1, len*16000/sr, 16000) 离线重采样到 16kHz
                 │ 返回 Float32Array
                 ▼
  asr(audio, { task:"transcribe", chunk_length_s:30, stride_length_s:5,
               return_timestamps:true, language? })
                 ▼
  out.text + out.chunks[]（c.timestamp[0]/[1] 为秒）→ 渲染分段列表 + 全文 textarea
```

- `chunk_length_s:30 / stride_length_s:5` 是长音频滑窗：30 秒窗口、5 秒重叠，避免长音频截断与边界丢字。
- `return_timestamps:true` 才有 `chunks`（无它只有 `out.text`）。
- 解码细节坑：`decodeAudioData` 会 **detach** 传入的 ArrayBuffer，所以代码里先 `arrayBuffer.slice(0)` 复制一份再解（`?demo=1` 还要用同一个 buf 构造 File）。二开碰到 "buffer already detached" 就是这里。
- 导出 TXT 用 Blob + `URL.createObjectURL` 前端下载，文件名 `转写稿_YYYYMMDDTHHMMSS.txt`（时间戳中 `-:T` 被替换掉）。

### 4.3 SITE_ROOT 子路径推导与模型自托管

`web/index.html` 顶部（模型地址的全部秘密都在这三行）：

```js
import { pipeline, env } from "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.3.1";
// 兼容子路径部署（GitHub Pages 项目页 /luyin-zhuan-wenzi/）：从 pathname 推导站点根
const SITE_ROOT = location.pathname.replace(/\/[^/]*$/, "");
env.remoteHost = location.origin + SITE_ROOT;
env.remotePathTemplate = "{model}/";
env.allowLocalModels = false;
env.allowRemoteModels = true;
```

推导规则：剥掉 pathname 最后一段（`index.html` 或末尾斜杠后的空串），得到站点根：

| 页面 URL | SITE_ROOT | 模型实际地址 |
|---|---|---|
| `https://…github.io/luyin-zhuan-wenzi/` | `/luyin-zhuan-wenzi` | `…/luyin-zhuan-wenzi/models/whisper-base/` |
| `https://hazy-crystal-tqp9.here.now/` | `""`（根域名） | `/models/whisper-base/` |
| `http://127.0.0.1:8000/index.html` | `""` | `/models/whisper-base/` |

之后 `pipeline("automatic-speech-recognition", "models/whisper-base", { dtype: "q8", progress_callback })` 拼出同源地址下载模型。**同源**是关键：§1 讲过第三方镜像 CORS 锁死自身域名的实测教训，自托管后 fetch 不再跨源，国内（Pages 直连/镜像站）都能用。`progress_callback` 把每个文件的 `loaded/total` 写进进度条，首次约 77MB，之后走浏览器缓存秒开。

---

## 5. 数据契约

### 5.1 桌面版 HTTP API（全部仅监听 127.0.0.1）

| 端点 | 方法 | 入参 | 出参/行为 |
|---|---|---|---|
| `/` | GET | — | 渲染 `static/index.html` |
| `/api/upload` | POST | multipart：`file`（音频）、form：`lang=auto\|zh\|en` | `{"job_id": "12位hex"}`；文件存 `_tmp/{uuid}_{safe_name}`，2GB 上限 |
| `/api/job/{id}` | GET | — | 整个 job JSON（见状态机），不存在返回 404 |
| `/api/export` | POST | `{"job_id", "format":"txt"\|"docx"}` | `{"filename": "转写稿_….txt\|docx"}`；job 必须 done |
| `/api/history` | GET | — | `[{"name","size","mtime"}]`，`输出/` 按修改时间倒序 |
| `/api/open/{name}` | GET | — | 附件下载 `输出/` 内文件；`safe_name` 清洗 + `contained()` 容器校验，越界/不存在 404 |

**job 状态机**：`queued → transcribing → done | error`（终态只有 done/error）。job JSON 字段：

```json
{"status": "done", "progress": 100.0,
 "segments": [{"start": 0.0, "end": 3.2, "text": "…"}],
 "text": "全文…", "error": null,
 "src": "录音.m4a", "lang": "zh", "duration": 62.5, "created": 1730000000.0}
```

- `progress`：queued 阶段 0；transcribing 阶段 = 最新分段 `seg.end / info.duration * 100`（封顶 99）；done 时 100。
- `segments`/`text` 仅在 done 后非空；`duration` 单位秒（= 解码后样本数 / 16000）。
- `_jobs` 常驻内存不淘汰（量小无妨）；进程重启全部丢失。

### 5.2 输出文件命名

- 桌面版：`输出/转写稿_{原文件名不含扩展名}_{YYYYMMDD_HHMMSS}.txt|.docx`（`time.strftime('%Y%m%d_%H%M%S')` 本地时区）。
- 网页版：浏览器下载 `转写稿_{YYYYMMDDTHHMMSS}.txt`（不含来源文件名，二开可补）。
- TXT 结构：`来源文件 / 转写时间 头两行 + [HH:MM:SS -> HH:MM:SS] 分段 + ———— 全文 ————`；编码 `utf-8-sig`。

### 5.3 网页版无持久化

- 转写结果只存在于页面内存（`lastResult` 变量），刷新即失；唯一落盘动作是用户点「导出 TXT」的浏览器下载。
- 模型缓存由 **transformers.js 自动管理**：文件按 URL 存进浏览器 **Cache API**，同源同路径下次秒开；过期/清理策略归浏览器（见 §9.6），代码侧无显式缓存逻辑。

---

## 6. 测试与验收

### 6.1 真实音频验收脚本 scripts/accept_1.py（workspace 内，不入仓库）

位于 `C:\Users\Administrator\.zcode\workspace\1793891459329-48ff391c-aa53-4698-a8eb-ac6dd7bfb2a2\scripts\accept_1.py`。
前置：桌面版已启动、真实录音存在于 `C:\Users\Administrator\Documents\录音\录音.m4a`。

```bash
# 先启动桌面版（另一窗口）
python scripts/accept_1.py http://127.0.0.1:8765 evidence
```

脚本依次校验并输出 PASS/FAIL：首页 200 → 上传真实 m4a 拿 `job_id` → 轮询 ≤300s 至终态 → 全文非空且命中已知关键词 ≥2 个（`在吗/听得见/说话`，该录音实测还正确转出了英文 hello）→ 分段含 start/end → 导出并真实下载 TXT/DOCX（DOCX 校验 `PK\x03\x04` 魔数 + sha256）→ 历史列表 ≥2 条。结果落 `evidence/product1_accept.json`，任一失败退出码 1。

### 6.2 网页版 ?demo=1 自测

见 §3.3。本地跑法：

```bash
cd web && python -m http.server 8000
# 浏览器打开 http://127.0.0.1:8000/index.html?demo=1 ，等状态行出现「DEMO 完成」
```

### 6.3 无头截图驱动 scripts/shot.py（workspace 内，不入仓库）

无头 Edge + CDP，支持注入 JS 制造界面状态（改 `--out`/`--url` 即可复用）：

```bash
cd C:\Users\Administrator\.zcode\workspace\1793891459329-48ff391c-aa53-4698-a8eb-ac6dd7bfb2a2
# 网页首页
python scripts/shot.py --url "http://127.0.0.1:8000/index.html" --out evidence/web-home.png
# demo 全链路截图：模型加载+转写耗时较长，--wait 必须给足（毫秒）
python scripts/shot.py --url "http://127.0.0.1:8000/index.html?demo=1" --out evidence/demo-result.png --wait 120000 --wait2 3000
# 线上 Pages 版同理，把 --url 换成 https://openclawzhangchong.github.io/luyin-zhuan-wenzi/?demo=1
```

流程：导航 → 等 `--wait` → 注入 `--pre`（可选 `--reload`+`--pre2`）→ 注入 `--act` → 等 `--wait2` → 截图。判定 demo 结果：截图里 `#status` 含「DEMO 完成」即通过；要程序化读 `document.title`（`DEMO PASS/FAIL`）可另用任意 CDP 客户端 `Runtime.evaluate` 一行取值。

---

## 7. 构建与部署

### 7.1 GitHub Pages（正式站）

`.github/workflows/pages.yml`：push 到 `main`（或手动 workflow_dispatch）→ `actions/upload-pages-artifact` 直接打包 **`web/` 目录为站点根** → `deploy-pages` 发布。**没有任何构建步骤**，`web/models/whisper-base/` 的 77MB 模型随构件一起上线。

```bash
git add web/ && git commit -m "feat: …" && git push   # 等 Actions 变绿
# 验证：https://openclawzhangchong.github.io/luyin-zhuan-wenzi/?demo=1 → DEMO PASS
```

### 7.2 here.now 镜像站（备用入口）

镜像与 Pages 共用同一份 `web/` 目录，**模型文件一起发布**（同源策略下镜像站同样能加载自托管模型）。用 workspace 内的 here.now 发布脚本：

```bash
cd C:\Users\Administrator\.zcode\workspace\1793891459329-48ff391c-aa53-4698-a8eb-ac6dd7bfb2a2
bash hn_publish.sh gh/luyin-zhuan-wenzi/web --slug hazy-crystal-tqp9 --overwrite
# 参数以 bash hn_publish.sh 无参输出的 usage 为准；发布后验证 https://hazy-crystal-tqp9.here.now/?demo=1
```

### 7.3 桌面版分发

**拷贝 `desktop/` 整个目录到目标机器即完成安装**（Python 3.10+ 已装的前提下）。`models/输出/_tmp` 均被 gitignore，所以仓库/拷贝包里不带模型；首次双击 `启动录音转文字.bat` 若提示模型缺失，双击 `下载模型.bat`：

```bat
python -c "import os;os.environ['HF_ENDPOINT']='https://hf-mirror.com';from huggingface_hub import snapshot_download;snapshot_download(repo_id='Systran/faster-whisper-small',local_dir='models/faster-whisper-small',allow_patterns=['*.bin','*.json','*.txt'])"
```

走国内镜像 hf-mirror 下载 `Systran/faster-whisper-small`（约 460MB，一次即可；断点续传，中断重跑不从头来）。

---

## 8. 二次开发指南

### 8.1 更换更大模型（small / medium）

**桌面版**（faster-whisper 原版权重，Systran 仓库）：

1. `desktop/下载模型.bat` 里改 `repo_id`：`Systran/faster-whisper-base` / `Systran/faster-whisper-medium` / `Systran/faster-whisper-large-v3`；
2. `server.py` 顶部同步改 `MODEL_DIR = BASE / "models" / "faster-whisper-small"`；
3. 重跑 下载模型.bat → 启动 → accept_1.py 回归。

**网页版**（transformers.js 需要 ONNX 量化版，取 Xenova 转换仓库的 q8 文件）：

1. 下载 `https://hf-mirror.com/Xenova/whisper-small/resolve/main/` 下的：`config.json`、`preprocessor_config.json`、`tokenizer.json`、`tokenizer_config.json`、`generation_config.json`、`quantize_config.json`、`onnx/encoder_model_quantized.onnx`、`onnx/decoder_model_merged_quantized.onnx`（直接浏览器/脚本下载到本地与 CORS 无关，CORS 只约束网页运行时的跨源 fetch）；
2. 放入新目录 `web/models/whisper-small/`（**新建目录而不是覆盖**——浏览器 Cache API 按 URL 缓存，覆盖同名文件会命中旧缓存）；
3. `index.html` 里 `pipeline("automatic-speech-recognition", "models/whisper-small", { dtype: "q8", … })` 改模型 id，其余零改动（SITE_ROOT 自动适配）；
4. 同步更新页面里「约 77MB」的文案，push 后用 ?demo=1 验证。

**权衡表**（数值为约数）：

| 模型 | 网页 q8 体积 | 推荐场景 | 中文准确率 | 转写速度（CPU） |
|---|---|---|---|---|
| whisper-base（现用） | ~77MB | 短录音、开箱即用 | 一般，短句可用 | 1x |
| whisper-small | ~250MB | 网页可接受的上限 | 明显更好 | 2~3x 慢 |
| whisper-medium | ~770MB | 仅桌面版 | 更好 | 5~8x 慢，网页不建议 |
| large-v3 | ~3GB | 仅桌面版 | 最好 | 10x+ 慢，需强机 |

桌面版对应 faster-whisper 权重：base ~140MB / small ~460MB / medium ~1.5GB。

### 8.2 增加 SRT 字幕导出

分段数据两端都有秒级时间轴，SRT 只是换个序列化格式。

桌面版（server.py）：加一个时间格式化与导出函数，并在 `/api/export` 分发：

```python
def fmt_srt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000); m, ms = divmod(ms, 60_000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def export_srt(job: dict, stem: str) -> Path:
    out = OUT_DIR / f"{stem}.srt"
    lines = []
    for i, s in enumerate(job["segments"], 1):
        lines += [str(i), f"{fmt_srt_ts(s['start'])} --> {fmt_srt_ts(s['end'])}", s["text"], ""]
    out.write_text("\n".join(lines), encoding="utf-8-sig")
    return out
# api_export 里：path = {"docx": export_docx, "srt": export_srt}.get(fmt, export_txt)(job, stem)
```

网页版（index.html）：复用 `ts()` 加毫秒变体，在 `#expT` 旁加一个按钮，用 `lastResult.chunks` 拼同样的 `序号 / --> / 文本` 三行组，Blob 下载。注意两端前端表单/按钮都要同步加选项。

### 8.3 麦克风录音直转

两端入口改造，核心是 MediaRecorder 产出的 Blob 走既有解码路径：

```js
const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
const rec = new MediaRecorder(stream);
const chunks = []; rec.ondataavailable = e => chunks.push(e.data);
rec.onstop = async () => {
  stream.getTracks().forEach(t => t.stop());
  const blob = new Blob(chunks, { type: "audio/webm" });        // Chrome/Edge 默认 webm/opus
  const audio = await decodeTo16kMono(await blob.arrayBuffer());
  const out = await asr(audio, { task: "transcribe", chunk_length_s: 30, stride_length_s: 5, return_timestamps: true, language: "zh" });
  // 渲染同现有 render()
};
rec.start();
```

- 网页版：加「开始/停止录音」按钮，stop 后走上面流程即可，`decodeAudioData` 能解 webm/opus，`decodeTo16kMono` 零改动（注意它内部 `arrayBuffer.slice(0)` 防 detach 的细节，传 Blob 的 arrayBuffer 时同样适用）。
- 桌面版：在 `static/index.html` 里用同段代码录音，然后把 Blob 装进 File 直接走现有 `POST /api/upload`（文件名给 `录音.webm` 即可，PyAV 能解 webm/opus，服务端零改动）。
- 实时逐句上屏属进阶需求（transformers.js Streamer / faster-whisper 流式），建议另立任务，不在本改造内。

### 8.4 说话人分离 / 摘要

Whisper **只转写不区分说话人**，也没有摘要能力，需要外挂：

- **说话人分离**：接 pyannote.audio（需要 HuggingFace token 授权模型、依赖较重）或轻量方案 resemblyzer 提取 embedding 聚类。落点在**桌面版**：对 `decode_audio16k` 产出的同一路 16k 音频跑 diarization，得到 `[(speaker, start, end)]` 区间，与 `job["segments"]` 按时间重叠合并成 `[时间轴][说话人] 文本`。网页版 WASM 环境跑不动 pyannote，不建议。
- **摘要**：把 `job["text"]` 喂给本地 LLM（Ollama 等）或云端 API。**隐私边界**：音频不出本机是本产品的核心承诺——若接云端 LLM，只能发送**转写文本**（且需用户显式确认），绝不发送音频或未经同意的原文；仓库内不得出现任何 API key。

---

## 9. 常见坑

1. **PyAV `metadata_errors`**：faster-whisper 1.2.1 的 `decode_audio` 调 `av.open(..., metadata_errors="ignore")`，PyAV ≥15 删除了该参数直接 `TypeError`；cp313 无旧版 wheel 不可降级。**已用 `decode_audio16k` 自解码根治（§4.1），不要再引入对 faster-whisper.decode_audio 的调用**；升级 faster-whisper 时先确认其上游已适配新 PyAV。
2. **GBK bat**：两个 .bat 是 **ANSI/GBK 编码 + CRLF**（cmd 按 OEM 码页 936 读取），用编辑器保存成 UTF-8 会让中文标题/提示全部乱码甚至解析异常。改 bat 时保持 GBK 编码；跨平台脚本一律别写成 bat。
3. **简繁输出**：whisper 中文经常输出繁体。桌面版已用 `initial_prompt="以下是普通话的句子。"` 偏置简体；**网页版未做**（transformers.js 的 ASR pipeline 不暴露等价 prompt 参数）——若要改，可行的路线是接 opencc-js 对 `out.text`/`chunks` 做繁→简后处理。
4. **长音频内存**：网页版把整条音频读进内存：`decodeAudioData` 先产生原始采样率多声道缓冲，再生成 16k 单声道 Float32Array（64KB/秒，30 分钟 ≈ 115MB），加上转写中间张量，浏览器内存压力可观——页面已标注**建议单文件 ≤30 分钟**，更长录音引导用户用桌面版。桌面版同为整段 ndarray（同量级）+ 2GB 上传上限，30 分钟无压力。
5. **hf-mirror 限流 429**：`下载模型.bat` 走 hf-mirror 大文件偶见 429；huggingface_hub 内置 HTTP 退避重试，且 `snapshot_download` 支持断点续传——**重跑 bat 即可**，已下载分片不重复。
6. **浏览器 Cache API 模型缓存过期**：transformers.js 按 URL 把模型文件缓存在 Cache API，浏览器在磁盘压力下可能清理（表现为再次全量下载 77MB）；更隐蔽的是**同名覆盖模型文件会命中旧缓存**——换模型请换目录名（§8.1）。强制刷新：DevTools → Application → Cache Storage 删除对应条目。
7. **（附）上传安全不可回退**：`safe_name()`（拦 `..`/路径分隔符/Windows 保留设备名）与 `contained()`（commonpath 容器校验）是 1.0.1 安全加固的成果，新增任何「按名字读文件」的端点必须复用同一套校验。

---

## 10. 维护与发布清单

改 `web/` 后的标准发布流：

- [ ] 本地 `cd web && python -m http.server 8000` + `?demo=1` 先过一遍
- [ ] `git add … && git commit && git push origin main`（不 push 模型外的大文件；`models/输出/_tmp` 已在 .gitignore）
- [ ] GitHub → Actions 确认 **Deploy static site to Pages** 变绿
- [ ] 打开线上 `https://openclawzhangchong.github.io/luyin-zhuan-wenzi/?demo=1` 验证 `DEMO PASS`（必要时硬刷新绕旧缓存）
- [ ] 重发 here.now 镜像（§7.2，带模型一起）并同样 `?demo=1` 验证
- [ ] 涉及模型/体积/端点变化：更新 `web/index.html` 页面文案、README、CHANGELOG.md（ Keep a Changelog 风格）
- [ ] 改桌面版：本地起服务跑 `scripts/accept_1.py`（§6.1）全绿再提交
- [ ] 提交信息用 `feat:/fix:/docs:/ci:` 前缀；不动 LICENSE/徽章，除非有意变更

---

*最后核对：2026-11-06，基于 commit `a9dff77`（fix: GitHub Pages 子路径下模型自托管地址丢失前缀）。*
