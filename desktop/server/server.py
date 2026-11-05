# -*- coding: utf-8 -*-
"""
录音转文字工作台（本地离线版）
- 双击「启动录音转文字.bat」即用，浏览器自动打开
- 音频全程不离开本机：模型本地推理（faster-whisper / CPU int8）
- 支持拖入 m4a/mp3/wav/flac/aac/ogg/mp4/amr 等常见音视频
- 产出：带时间轴的分段稿 + 全文，可导出 TXT / DOCX
"""
import io
import json
import os
import re
import sys
import av
import threading
import time
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file, render_template

BASE = Path(__file__).resolve().parent
MODEL_DIR = BASE / "models" / "faster-whisper-small"
OUT_DIR = BASE / "输出"
TMP_DIR = BASE / "_tmp"
OUT_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB

_jobs = {}          # job_id -> {status, progress, segs, text, error, src, lang, duration}
_model = None       # 懒加载的 whisper 模型
_model_lock = threading.Lock()


def _get_model():
    global _model
    with _model_lock:
        if _model is None:
            if not MODEL_DIR.exists() or not any(MODEL_DIR.glob("*.bin")):
                raise RuntimeError("模型缺失：请在产品文件夹运行「下载模型.bat」，或确认 models/faster-whisper-small 完整。")
            from faster_whisper import WhisperModel
            _model = WhisperModel(str(MODEL_DIR), device="cpu", compute_type="int8")
        return _model


def safe_name(name: str) -> str:
    """保留中文与常用字符，去掉路径分隔符等。"""
    name = os.path.basename(name)
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip()
    return cleaned or "audio"


def probe_duration(path: Path) -> float:
    """用 PyAV 探测音频时长（秒）。"""
    try:
        import av
        c = av.open(str(path))
        dur = c.duration
        c.close()
        if dur and dur > 0:
            return dur / 1_000_000.0
    except Exception:
        pass
    return 0.0


def fmt_ts(sec: float) -> str:
    sec = int(sec)
    return "%02d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


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


def run_job(job_id: str, audio_path: Path, lang: str):
    job = _jobs[job_id]
    try:
        model = _get_model()
        job["status"] = "transcribing"
        audio_np = decode_audio16k(audio_path)
        duration = len(audio_np) / 16000.0
        job["duration"] = duration
        kwargs = dict(vad_filter=True, vad_parameters={"min_silence_duration_ms": 500})
        if lang and lang != "auto":
            kwargs["language"] = lang
            if lang == "zh":
                kwargs["initial_prompt"] = "以下是普通话的句子。"  # 偏置输出简体中文
        seg_iter, info = model.transcribe(audio_np, **kwargs)
        segs, texts = [], []
        for seg in seg_iter:
            segs.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
            texts.append(seg.text.strip())
            if info.duration:
                job["progress"] = min(99.0, seg.end / info.duration * 100.0)
        job["segments"] = segs
        job["text"] = "".join(texts) if (lang or "auto") != "en" else " ".join(texts)
        job["progress"] = 100.0
        job["status"] = "done"
    except Exception as e:  # 失败也要给前端明确原因
        job["status"] = "error"
        job["error"] = str(e)
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass


def export_txt(job: dict, stem: str) -> Path:
    out = OUT_DIR / f"{stem}.txt"
    lines = [f"来源文件：{job['src']}", f"转写时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for s in job["segments"]:
        lines.append(f"[{fmt_ts(s['start'])} -> {fmt_ts(s['end'])}] {s['text']}")
    lines += ["", "———— 全文 ————", job["text"]]
    out.write_text("\n".join(lines), encoding="utf-8-sig")
    return out


def export_docx(job: dict, stem: str) -> Path:
    from docx import Document
    from docx.shared import Pt
    doc = Document()
    doc.add_heading("录音转文字稿", level=0)
    p = doc.add_paragraph()
    r = p.add_run(f"来源文件：{job['src']}    转写时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    r.font.size = Pt(10)
    doc.add_heading("分段稿", level=1)
    for s in job["segments"]:
        para = doc.add_paragraph()
        r = para.add_run(f"[{fmt_ts(s['start'])} -> {fmt_ts(s['end'])}] ")
        r.font.size = Pt(9)
        para.add_run(s["text"]).font.size = Pt(12)
    doc.add_heading("全文", level=1)
    para = doc.add_paragraph()
    para.add_run(job["text"]).font.size = Pt(12)
    out = OUT_DIR / f"{stem}.docx"
    doc.save(str(out))
    return out


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/upload")
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "未收到文件"}), 400
    lang = request.form.get("lang", "auto")
    src = safe_name(f.filename)
    tmp = TMP_DIR / f"{uuid.uuid4().hex}_{src}"
    f.save(str(tmp))
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "queued", "progress": 0.0, "segments": [], "text": "",
                     "error": None, "src": src, "lang": lang, "duration": 0.0,
                     "created": time.time()}
    threading.Thread(target=run_job, args=(job_id, tmp, lang), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/api/job/<job_id>")
def api_job(job_id):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(job)


@app.post("/api/export")
def api_export():
    data = request.get_json(force=True)
    job = _jobs.get(data.get("job_id", ""))
    if not job or job["status"] != "done":
        return jsonify({"error": "任务不存在或尚未完成"}), 400
    fmt = data.get("format", "txt")
    stem = f"转写稿_{Path(job['src']).stem}_{time.strftime('%Y%m%d_%H%M%S')}"
    path = export_docx(job, stem) if fmt == "docx" else export_txt(job, stem)
    return jsonify({"filename": path.name})


@app.get("/api/history")
def api_history():
    items = []
    for p in sorted(OUT_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file():
            items.append({"name": p.name, "size": p.stat().st_size,
                          "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
    return jsonify(items)


@app.get("/api/open/<name>")
def api_open(name):
    name = safe_name(name)
    p = OUT_DIR / name
    if not p.is_file():
        return jsonify({"error": "文件不存在"}), 404
    return send_file(str(p), as_attachment=True, download_name=name)


def pick_port(start=8765):
    import socket
    for port in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("8765~8795 端口都被占用")


if __name__ == "__main__":
    port = pick_port()
    url = f"http://127.0.0.1:{port}"
    print(f"录音转文字工作台 已启动：{url}  （本窗口最小化即可，关闭即退出服务）", flush=True)
    if not os.environ.get("ZC_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
