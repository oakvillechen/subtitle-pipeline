#!/usr/bin/env python3
"""日语视频 -> 中文字幕 本地流水线（转写: mlx-whisper；翻译: PLaMo / Ollama，全部本地）"""
import argparse, json, os, re, subprocess, sys, threading, time

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
CHUNK_SEC = 600
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")


class FatalAPIError(RuntimeError):
    pass


def _load_keys():
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys.env")
    if os.path.exists(f):
        for line in open(f, encoding="utf-8"):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)


_load_keys()
BATCH = 30
CONTEXT = 5
FFMPEG = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe" if os.path.exists("/opt/homebrew/bin/ffprobe") else "ffprobe"


class Stopped(Exception):
    pass


def _chk(stop):
    if stop is not None and stop.is_set():
        raise Stopped()


def work_dir(video):
    d = os.path.join(os.path.dirname(os.path.abspath(video)), ".subwork",
                     os.path.splitext(os.path.basename(video))[0])
    os.makedirs(d, exist_ok=True)
    return d


def base_path(video):
    return os.path.splitext(os.path.abspath(video))[0]


def ts(t):
    ms = int(round(max(t, 0) * 1000))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path, entries):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(f"{e['id']}\n{e['time']}\n{e['text'].strip()}\n\n")
    os.replace(tmp, path)


def read_srt(path):
    txt = open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")
    out = []
    for block in re.split(r"\n\s*\n", txt.strip()):
        lines = block.split("\n")
        if len(lines) >= 2 and "-->" in lines[1]:
            out.append({"id": lines[0].strip(), "time": lines[1].strip(),
                        "text": "\n".join(lines[2:]).strip()})
    return out


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---------------- 第一步：转写 ----------------
def duration(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    return float(r.stdout.strip())


def transcribe(video, log=print, stop=None, model=WHISPER_MODEL, prog=None, max_chunks=None, out=None):
    import mlx_whisper
    wd = work_dir(video)
    out = out or base_path(video) + ".ja.srt"
    audio = os.path.join(wd, "audio.wav")
    if not os.path.exists(audio):
        log(f"[转写] 提取音频: {os.path.basename(video)}")
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", video, "-vn", "-ac", "1",
                        "-ar", "16000", audio + ".tmp.wav"], check=True)
        os.replace(audio + ".tmp.wav", audio)
    total = duration(audio)
    n = max(1, int((total + CHUNK_SEC - 1) // CHUNK_SEC))
    log(f"[转写] 时长 {total/60:.1f} 分钟，分成 {n} 段")
    if max_chunks:
        n = min(n, max_chunks)
        log(f"[转写] 试跑模式：只转写前 {n} 段")
    prog = prog or (lambda *a: None)
    prog("转写", 0, n, True)
    segs = []
    for i in range(n):
        _chk(stop)
        cj = os.path.join(wd, f"chunk_{i:03d}.json")
        off = i * CHUNK_SEC
        if os.path.exists(cj):
            log(f"[转写] 第 {i+1}/{n} 段已完成，跳过（缓存）")
            prog("转写", i + 1, n, True)
        else:
            cw = os.path.join(wd, f"chunk_{i:03d}.wav")
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", str(off), "-t", str(CHUNK_SEC),
                            "-i", audio, "-c", "copy", cw], check=True)
            t0 = time.time()
            log(f"[转写] 第 {i+1}/{n} 段转写中…")
            r = mlx_whisper.transcribe(cw, path_or_hf_repo=model, language="ja", task="transcribe",
                                       condition_on_previous_text=False, verbose=None)
            data = [{"start": s["start"], "end": s["end"], "text": s["text"].strip()}
                    for s in r.get("segments", []) if s.get("text", "").strip()]
            save_json(cj, {"offset": off, "segments": data})
            os.remove(cw)
            prog("转写", i + 1, n, False)
            log(f"[转写] 第 {i+1}/{n} 段完成，用时 {time.time()-t0:.0f}s，{len(data)} 句")
        d = json.load(open(cj, encoding="utf-8"))
        for s in d["segments"]:
            segs.append((s["start"] + d["offset"], s["end"] + d["offset"], s["text"]))
    entries = [{"id": str(k + 1), "time": f"{ts(a)} --> {ts(b)}", "text": t}
               for k, (a, b, t) in enumerate(segs)]
    write_srt(out, entries)
    log(f"[转写] 完成 → {out}（{len(entries)} 条）")
    return out


# ---------------- 第二步：翻译 ----------------
SYS = ("你是专业的日译中字幕翻译。把日语字幕翻译成自然、口语化、简洁的简体中文。"
       "要求：逐条翻译，条数和编号必须与输入完全一致，不合并、不拆分、不遗漏；"
       "人名地名保持一致；只输出 JSON 对象，格式为 {\"编号\": \"中文译文\"}，不要任何解释。")


def _chat(backend, messages):
    import requests
    r = requests.post(OLLAMA_URL + "/api/chat", timeout=900,
                      json={"model": OLLAMA_MODEL, "messages": messages, "stream": False,
                            "think": False, "format": "json",
                            "options": {"temperature": 0.3, "num_ctx": 8192}})
    r.raise_for_status()
    return r.json()["message"]["content"]


def _parse(txt):
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0) if m else txt)


_PLAMO = None


def _plamo_gen(text):
    global _PLAMO
    from mlx_lm import load, generate
    from mlx_lm.sample_utils import make_sampler
    if _PLAMO is None:
        print("[翻译] 载入本地 PLaMo 模型…", flush=True)
        _PLAMO = load("mlx-community/plamo-2-translate", tokenizer_config={"trust_remote_code": True},
                      trust_remote_code=True)
    m, tok = _PLAMO
    p = ("<|plamo:op|>dataset\ntranslation\n<|plamo:op|>input lang=Japanese\n" + text +
         "\n<|plamo:op|>output lang=Simplified Chinese\n")
    out = generate(m, tok, prompt=p, sampler=make_sampler(temp=0), max_tokens=60 * (text.count("\n") + 1) + 60)
    return out.split("<|plamo:op|>")[0].strip()


def _plamo_batch(batch, log, group=10):
    res = {}
    for i in range(0, len(batch), group):
        g = batch[i:i + group]
        lines = [e["text"].replace("\n", " ").strip() for e in g]
        try:
            out = [l.strip() for l in _plamo_gen("\n".join(lines)).split("\n") if l.strip()]
        except Exception as ex:
            log(f"[翻译] PLaMo 出错: {ex}"); out = []
        if len(out) == len(g):
            res.update({e["id"]: o for e, o in zip(g, out)}); continue
        for e, l in zip(g, lines):  # 行数对不上，逐行翻
            try:
                o = _plamo_gen(l).replace("\n", " ").strip()
            except Exception:
                o = ""
            res[e["id"]] = o or "【未翻译】" + l
    return res


def _translate_batch(backend, batch, ctx, log):
    if backend == "plamo":
        res = _plamo_batch(batch, log)
        bad = [e for e in batch if res[e["id"]].startswith("【未翻译】")]
        if bad:
            log(f"[翻译] PLaMo 有 {len(bad)} 条失败，改用本地 Ollama")
            try:
                res.update(_translate_batch("ollama", bad, ctx, log))
            except Exception as ex:
                log(f"[翻译] Ollama 也失败: {ex}")
        return res
    payload = {e["id"]: e["text"].replace("\n", " ") for e in batch}
    user = ""
    if ctx:
        user += "【上文（仅供参考，不要翻译）】\n" + "\n".join(e["text"] for e in ctx) + "\n\n"
    user += "【需要翻译的字幕，JSON】\n" + json.dumps(payload, ensure_ascii=False)
    user += f"\n\n请输出包含全部 {len(batch)} 个编号的 JSON。"
    msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": user}]
    for attempt in range(3):
        try:
            res = _parse(_chat(backend, msgs))
            res = {str(k).strip(): str(v).strip() for k, v in res.items()}
            if set(res) == set(payload) and all(res.values()):
                return res
            log(f"[翻译] 编号不匹配（第 {attempt+1} 次），重试")
        except FatalAPIError:
            raise
        except Exception as ex:
            log(f"[翻译] 出错（第 {attempt+1} 次）: {ex}")
            time.sleep(2)
    if len(batch) > 1:  # 拆半重试
        h = len(batch) // 2
        a = _translate_batch(backend, batch[:h], ctx, log)
        return {**a, **_translate_batch(backend, batch[h:], batch[:h][-CONTEXT:], log)}
    log(f"[翻译] 第 {batch[0]['id']} 条无法翻译，保留日文原文")
    return {e["id"]: "【未翻译】" + e["text"].replace("\n", " ") for e in batch}


def translate(video_or_srt, backend="plamo", log=print, stop=None, prog=None, ja=None, out=None):
    if video_or_srt.endswith(".ja.srt"):
        ja = video_or_srt; b = ja[:-7]
        wd = os.path.join(os.path.dirname(b), ".subwork", os.path.basename(b)); os.makedirs(wd, exist_ok=True)
    else:
        b = base_path(video_or_srt); ja = ja or b + ".ja.srt"; wd = work_dir(video_or_srt)
    if not os.path.exists(ja):
        raise FileNotFoundError(f"找不到日语字幕 {ja}，请先转写")
    entries = read_srt(ja)
    cdir = os.path.join(wd, f"trans_{backend}"); os.makedirs(cdir, exist_ok=True)
    nb = (len(entries) + BATCH - 1) // BATCH
    log(f"[翻译] {len(entries)} 条，{nb} 批，后端 {backend}")
    prog = prog or (lambda *a: None)
    prog("翻译", 0, nb, True)
    zh = {}
    for i in range(nb):
        _chk(stop)
        batch = entries[i * BATCH:(i + 1) * BATCH]
        cf = os.path.join(cdir, f"batch_{i:04d}.json")
        res = json.load(open(cf, encoding="utf-8")) if os.path.exists(cf) else {}
        missing = [e for e in batch if not res.get(e["id"])]
        if not missing:
            log(f"[翻译] 第 {i+1}/{nb} 批已完成，跳过（缓存）")
            prog("翻译", i + 1, nb, True)
        else:
            t0 = time.time()
            if res:  # 试跑时只翻了这批的前一部分，只补译缺的条目
                log(f"[翻译] 第 {i+1}/{nb} 批复用缓存 {len(batch)-len(missing)} 条，补译 {len(missing)} 条")
            first = entries.index(missing[0])
            res.update(_translate_batch(backend, missing, entries[max(0, first-CONTEXT):first], log))
            save_json(cf, res)
            prog("翻译", i + 1, nb, False)
            log(f"[翻译] 第 {i+1}/{nb} 批完成，用时 {time.time()-t0:.0f}s")
        zh.update(res)
    out = out or b + ".zh.srt"
    write_srt(out, [{**e, "text": zh[e["id"]]} for e in entries])
    log(f"[翻译] 完成 → {out}")
    return out


def preview_chunks(video):
    """试跑段数：视频前 10%，向上取整到 10 分钟一段，至少 1 段"""
    import math
    return max(1, math.ceil(duration(video) * 0.1 / CHUNK_SEC))


def run(files, step="all", backend="plamo", log=print, stop=None, prog=None, preview=False):
    """prog(file_i, n_files, stage, done, total, cached)"""
    results = []
    for k, f in enumerate(files, 1):
        log(f"===== ({k}/{len(files)}) {os.path.basename(f)} =====")
        p = (lambda *a, k=k: prog(k, len(files), *a)) if prog else None
        try:
            if preview and not f.endswith(".srt"):
                b = base_path(f); pj, pz = b + ".preview.ja.srt", b + ".preview.zh.srt"
                transcribe(f, log, stop, prog=p, max_chunks=preview_chunks(f), out=pj)
                translate(f, backend, log, stop, prog=p, ja=pj, out=pz)
                log(f"[试跑] 预览字幕已生成：\n  {pj}\n  {pz}\n确认没问题后点「继续完成全部」，已完成的部分不会重做。")
                results.append(pz); continue
            if step in ("all", "transcribe") and not f.endswith(".srt"):
                transcribe(f, log, stop, prog=p)
            if step in ("all", "translate"):
                results.append(translate(f, backend, log, stop, prog=p))
        except Stopped:
            log("已停止。下次再开始会从断点继续。"); return
        except Exception as ex:
            log(f"!! 失败: {ex}")
    log("全部任务结束。")
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="日语视频→中文字幕")
    p.add_argument("files", nargs="+")
    p.add_argument("--step", choices=["all", "transcribe", "translate"], default="all")
    p.add_argument("--backend", choices=["plamo", "ollama"], default="plamo")
    p.add_argument("--preview", action="store_true", help="先试 10%")
    a = p.parse_args()
    run(a.files, a.step, a.backend, preview=a.preview)
