#!/usr/bin/env python3
import os, queue, subprocess, threading, time, tkinter as tk
from tkinter import filedialog, ttk
import pipeline

VIDEO = [("视频/字幕", "*.mp4 *.mkv *.mov *.avi *.m4v *.webm *.ts *.flv *.mp3 *.m4a *.wav *.ja.srt"), ("全部", "*")]


def fmt(sec):
    sec = int(max(sec, 0)); h, r = divmod(sec, 3600); m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class Tracker:
    """进度/ETA 计算（与界面无关，便于测试）。缓存命中的段/批不计入速度。"""
    def __init__(s, mode="all"):
        s.mode = mode; s.t0 = time.time(); s.state = "运行中"
        s.fi = s.nf = 0; s.stage = ""; s.done = s.total = 0
        s.last = time.time(); s.times = []

    def update(s, fi, nf, stage, done, total, cached):
        now = time.time()
        if (fi, stage) != (s.fi, s.stage):
            s.times = []
        if done > 0 and not cached:
            s.times.append(now - s.last)
        s.last = now; s.fi, s.nf, s.stage, s.done, s.total = fi, nf, stage, done, total

    def percent(s):
        f = s.done / s.total if s.total else 0.0
        if s.mode == "transcribe" or s.mode == "translate":
            return 100.0 * f
        return 50.0 * f if s.stage == "转写" else 50.0 + 50.0 * f

    def eta(s):
        if not s.times or s.total <= s.done:
            return None
        avg = sum(s.times) / len(s.times)
        return max(avg * (s.total - s.done) - (time.time() - s.last), 0)

    def text(s):
        parts = [f"● {s.state}"]
        if s.nf > 1: parts.append(f"文件 {s.fi}/{s.nf}")
        if s.stage:
            unit = "段" if s.stage == "转写" else "批"
            parts.append(f"{s.stage} 第 {s.done}/{s.total} {unit}")
        parts.append(f"当前文件 {s.percent():.0f}%")
        parts.append(f"已用 {fmt(time.time() - s.t0)}")
        e = s.eta()
        if s.state == "运行中":
            parts.append(f"本阶段剩余约 {fmt(e)}" if e is not None else "剩余时间：估算中…")
        return "   ".join(parts)


class App:
    def __init__(s, root):
        s.root = root; root.title("日语视频 → 中文字幕（本地）"); root.geometry("820x600")
        s.q = queue.Queue(); s.stop = threading.Event(); s.th = None
        f = ttk.Frame(root, padding=8); f.pack(fill="both", expand=True)
        bar = ttk.Frame(f); bar.pack(fill="x")
        ttk.Button(bar, text="添加视频…", command=s.add).pack(side="left")
        ttk.Button(bar, text="移除选中", command=s.rm).pack(side="left", padx=4)
        ttk.Button(bar, text="清空", command=lambda: s.lb.delete(0, "end")).pack(side="left")
        s.lb = tk.Listbox(f, height=8, selectmode="extended"); s.lb.pack(fill="x", pady=6)
        opt = ttk.Frame(f); opt.pack(fill="x")
        ttk.Label(opt, text="步骤:").pack(side="left")
        s.step = tk.StringVar(value="all")
        for t, v in [("全流程", "all"), ("只转写", "transcribe"), ("只翻译", "translate")]:
            ttk.Radiobutton(opt, text=t, value=v, variable=s.step).pack(side="left")
        ttk.Label(opt, text="   翻译后端:").pack(side="left")
        s.be = tk.StringVar(value="gemini")
        ttk.Radiobutton(opt, text="Google Gemini（免费）", value="gemini", variable=s.be).pack(side="left")
        ttk.Radiobutton(opt, text="本地 Ollama（免费）", value="ollama", variable=s.be).pack(side="left")
        ttk.Radiobutton(opt, text="本地 PLaMo（免费·无审查）", value="plamo", variable=s.be).pack(side="left")
        kf = ttk.Frame(f); kf.pack(fill="x", pady=4)
        ttk.Label(kf, text="Gemini Key（已存，可覆盖）:").pack(side="left")
        s.key = tk.StringVar(value=os.environ.get("GEMINI_API_KEY", ""))
        ttk.Entry(kf, textvariable=s.key, show="*", width=50).pack(side="left")
        cf = ttk.Frame(f); cf.pack(fill="x")
        s.bs = ttk.Button(cf, text="开始", command=s.start); s.bs.pack(side="left")
        s.bp = ttk.Button(cf, text="先试 10%", command=lambda: s.start(preview=True)); s.bp.pack(side="left", padx=4)
        s.bc = ttk.Button(cf, text="继续完成全部", command=s.start); s.bc.pack(side="left")
        s.bt = ttk.Button(cf, text="停止", command=s.do_stop, state="disabled"); s.bt.pack(side="left", padx=4)
        s.bo = ttk.Button(cf, text="打开预览字幕", command=s.open_preview, state="disabled"); s.bo.pack(side="left")
        ttk.Label(cf, text="（停止后再开始会从断点继续）").pack(side="left", padx=4)
        s.pb = ttk.Progressbar(f, maximum=100); s.pb.pack(fill="x", pady=(8, 2))
        s.status = tk.StringVar(value="● 空闲"); ttk.Label(f, textvariable=s.status).pack(anchor="w")
        s.tr = None; s.preview_files = []
        s.log = tk.Text(f, height=20); s.log.pack(fill="both", expand=True, pady=6)
        root.after(200, s.poll)

    def add(s):
        for p in filedialog.askopenfilenames(title="选择视频"):
            if p not in s.lb.get(0, "end"): s.lb.insert("end", p)

    def rm(s):
        for i in reversed(s.lb.curselection()): s.lb.delete(i)

    def say(s, m): s.q.put(m)

    def poll(s):
        while not s.q.empty():
            s.log.insert("end", s.q.get() + "\n"); s.log.see("end")
        if s.tr:
            s.pb["value"] = s.tr.percent(); s.status.set(s.tr.text())
        if s.th and not s.th.is_alive():
            s.th = None
            for b in (s.bs, s.bp, s.bc): b.config(state="normal")
            s.bt.config(state="disabled")
            if s.tr:
                s.tr.state = "已停止" if s.stop.is_set() else "已完成"
                s.status.set(s.tr.text())
            if s.preview_files: s.bo.config(state="normal")
        s.root.after(500, s.poll)

    def prog(s, *a):
        if s.tr: s.tr.update(*a)

    def job(s, files, step, be, preview):
        res = pipeline.run(files, step, be, s.say, s.stop, prog=s.prog, preview=preview) or []
        if preview:
            s.preview_files = [p for p in res if os.path.exists(p)]

    def open_preview(s):
        for p in s.preview_files:
            subprocess.Popen(["open", "-R", p]); subprocess.Popen(["open", "-e", p])

    def start(s, preview=False):
        files = list(s.lb.get(0, "end"))
        if not files: s.say("请先添加视频文件"); return
        if s.key.get().strip(): os.environ["GEMINI_API_KEY"] = s.key.get().strip()
        s.stop.clear(); s.bt.config(state="normal")
        for b in (s.bs, s.bp, s.bc, s.bo): b.config(state="disabled")
        s.tr = Tracker("all" if preview else s.step.get()); s.preview_files = []
        s.th = threading.Thread(target=s.job, daemon=True,
                                args=(files, s.step.get(), s.be.get(), preview))
        s.th.start()

    def do_stop(s):
        s.stop.set(); s.say("正在停止（当前这一段/批完成后停）…")


if __name__ == "__main__":
    r = tk.Tk(); App(r); r.mainloop()
