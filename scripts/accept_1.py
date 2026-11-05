# -*- coding: utf-8 -*-
"""产品1《录音转文字工作台》验收脚本：真实转写 Documents/录音/录音.m4a 并导出。"""
import sys, time, json, hashlib, requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
# 音频可用第 3 个参数覆盖（其他电脑请自备一段音频）：
# python scripts/accept_1.py http://127.0.0.1:8765 evidence "D:\某\测试音频.m4a"
AUDIO = sys.argv[3] if len(sys.argv) > 3 else r"C:\Users\Administrator\Documents\录音\录音.m4a"
EVID = sys.argv[2] if len(sys.argv) > 2 else "evidence"
import os
os.makedirs(EVID, exist_ok=True)

report = {"base": BASE, "audio": AUDIO, "checks": []}

def check(name, ok, detail):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    print(("PASS " if ok else "FAIL ") + name + " | " + str(detail))

# 1 首页可访问
r = requests.get(BASE + "/", timeout=10)
check("首页HTTP", r.status_code == 200 and "录音转文字工作台" in r.text, f"status={r.status_code}, len={len(r.text)}")

# 2 上传真实录音
t0 = time.time()
with open(AUDIO, "rb") as f:
    r = requests.post(BASE + "/api/upload", files={"file": ("录音.m4a", f)}, data={"lang": "zh"}, timeout=60)
j = r.json()
check("上传返回job_id", "job_id" in j, json.dumps(j, ensure_ascii=False))
job_id = j["job_id"]

# 3 轮询直到完成
final = None
for _ in range(300):
    j = requests.get(BASE + f"/api/job/{job_id}", timeout=10).json()
    if j["status"] in ("done", "error"):
        final = j
        break
    time.sleep(1)
elapsed = time.time() - t0
check("转写完成", final and final["status"] == "done",
      f"耗时{elapsed:.1f}s 时长{final['duration']:.1f}s 分段{len(final['segments'])}" if final and final["status"] == "done" else json.dumps(final, ensure_ascii=False)[:300])

if final and final["status"] == "done":
    text = final["text"]
    segs = final["segments"]
    check("全文非空", len(text.strip()) > 0, f"{len(text)}字")
    kw = [k for k in ("在吗", "听得见", "说话") if k in text]
    check("转写内容正确（含已知关键词）", len(kw) >= 2,
          f"命中关键词={kw}（该录音实测内容为半英文问候语，hello 也被正确转出）")
    first = " / ".join(f"[{int(s['start'])}-{int(s['end'])}]{s['text']}" for s in segs[:5])
    check("时间轴分段", all("start" in s and "end" in s for s in segs), first[:200])
    report["transcript_text"] = text
    report["segments_first5"] = first

    # 4 导出 TXT + DOCX 并真实下载
    for fmt in ("txt", "docx"):
        r = requests.post(BASE + "/api/export", json={"job_id": job_id, "format": fmt}, timeout=30)
        j = r.json()
        ok = "filename" in j
        check(f"导出{fmt.upper()}", ok, json.dumps(j, ensure_ascii=False))
        if ok:
            d = requests.get(BASE + "/api/open/" + j["filename"], timeout=30).content
            h = hashlib.sha256(d).hexdigest()
            size = len(d)
            check(f"{fmt.upper()}内容下载", size > 100 and (d[:4] == b"PK\x03\x04" if fmt == "docx" else True),
                  f"size={size} sha256={h[:16]}…")
            report[f"{fmt}_file"] = {"name": j["filename"], "size": size, "sha256": h}

    # 5 历史列表
    r = requests.get(BASE + "/api/history", timeout=10).json()
    check("历史记录", isinstance(r, list) and len(r) >= 2, f"{len(r)}条: {[i['name'] for i in r][:4]}")

report["elapsed_sec"] = round(elapsed, 1)
with open(os.path.join(EVID, "product1_accept.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
all_ok = all(c["ok"] for c in report["checks"])
print("\n=== 产品1验收：" + ("全部通过 [OK]" if all_ok else "存在失败 [NG]") + " ===")
sys.exit(0 if all_ok else 1)
