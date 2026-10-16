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
        s.last = time.time(); s.times = []; s.t_end = None

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
        if s.stage == "转写": return 50.0 * f
        if s.stage == "翻译": return 50.0 + 50.0 * f
        return 0.0

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
        parts.append(f"{'总用时' if s.t_end else '已用'} {fmt((s.t_end or time.time()) - s.t0)}")
        e = s.eta()
        if s.state == "运行中":
            parts.append(f"本阶段剩余约 {fmt(e)}" if e is not None else "剩余时间：估算中…")
        return "   ".join(parts)


BG, CARD, FG, SUB = "#f4f5f9", "#ffffff", "#1d1d1f", "#86868b"
C1, C2 = (236, 72, 153), (59, 130, 246)  # 粉 → 蓝（与图标一致）
FONT = "PingFang SC"
PILL = {"运行中": "#34c759", "已完成": "#0a84ff", "已停止": "#8e8e93", "空闲": "#c7c7cc"}


def _mix(t):
    return "#%02x%02x%02x" % tuple(int(a + (b - a) * t) for a, b in zip(C1, C2))


class Bar(tk.Canvas):
    """圆角渐变进度条，带平滑动画"""
    def __init__(s, master, h=16, **kw):
        super().__init__(master, height=h, bg=CARD, highlightthickness=0, **kw)
        s.h, s.val, s.target = h, 0.0, 0.0
        s.bind("<Configure>", lambda e: s.draw()); s.tick()

    def set(s, v): s.target = max(0.0, min(100.0, v))

    def tick(s):
        d = s.target - s.val
        if abs(d) > 0.05:
            s.val += d * 0.18; s.draw()
        elif d:
            s.val = s.target; s.draw()
        s.after(30, s.tick)

    def draw(s):
        s.delete("all"); w, h = s.winfo_width(), s.h; r = h / 2
        if w < h: return
        s.create_line(r, r, w - r, r, width=h, capstyle="round", fill="#e5e5ea")
        fw = (w - h) * s.val / 100
        if s.val <= 0: return
        s.create_oval(0, 0, h, h, fill=_mix(0), outline="")
        n = max(int(fw), 1)
        for i in range(0, n, 2):
            s.create_line(r + i, 0, r + i, h, width=2, fill=_mix(i / max(w - h, 1)))
        s.create_oval(fw, 0, fw + h, h, fill=_mix(fw / max(w - h, 1)), outline="")


class App:
    def __init__(s, root):
        s.root = root; root.title("字幕翻译 · 日语 → 中文"); root.geometry("880x720"); root.configure(bg=BG)
        s.q = queue.Queue(); s.stop = threading.Event(); s.th = None
        st = ttk.Style()
        try: st.theme_use("aqua")
        except tk.TclError: pass
        for n in ("TFrame", "TLabel", "TRadiobutton"): st.configure(n, background=BG, font=(FONT, 13))
        st.configure("Card.TFrame", background=CARD)
        f = ttk.Frame(root, padding=(20, 16)); f.pack(fill="both", expand=True)
        tk.Label(f, text="字幕翻译", font=(FONT, 22, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(f, text="日语视频 → 简体中文字幕 · 全部本地运行", font=(FONT, 12), bg=BG, fg=SUB).pack(anchor="w", pady=(0, 10))
        bar = ttk.Frame(f); bar.pack(fill="x")
        ttk.Button(bar, text="添加视频…", command=s.add).pack(side="left")
        ttk.Button(bar, text="移除选中", command=s.rm).pack(side="left", padx=6)
        ttk.Button(bar, text="清空", command=lambda: s.lb.delete(0, "end")).pack(side="left")
        s.lb = tk.Listbox(f, height=5, selectmode="extended", font=(FONT, 12), relief="flat", bd=0,
                          highlightthickness=1, highlightbackground="#e5e5ea", bg=CARD, fg=FG)
        s.lb.pack(fill="x", pady=8)
        opt = ttk.Frame(f); opt.pack(fill="x")
        ttk.Label(opt, text="步骤", foreground=SUB).pack(side="left", padx=(0, 6))
        s.step = tk.StringVar(value="all")
        for t, v in [("全流程", "all"), ("只转写", "transcribe"), ("只翻译", "translate")]:
            ttk.Radiobutton(opt, text=t, value=v, variable=s.step).pack(side="left")
        ttk.Label(opt, text="翻译引擎", foreground=SUB).pack(side="left", padx=(24, 6))
        s.be = tk.StringVar(value="plamo")
        ttk.Radiobutton(opt, text="本地 PLaMo（免费·无审查）", value="plamo", variable=s.be).pack(side="left")
        ttk.Radiobutton(opt, text="本地 Ollama", value="ollama", variable=s.be).pack(side="left")
        cf = ttk.Frame(f); cf.pack(fill="x", pady=(12, 0))
        s.bs = ttk.Button(cf, text="开始", command=s.start); s.bs.pack(side="left")
        s.bp = ttk.Button(cf, text="先试 10%", command=lambda: s.start(preview=True)); s.bp.pack(side="left", padx=6)
        s.bc = ttk.Button(cf, text="继续完成全部", command=s.start); s.bc.pack(side="left")
        s.bt = ttk.Button(cf, text="停止", command=s.do_stop, state="disabled"); s.bt.pack(side="left", padx=6)
        s.bo = ttk.Button(cf, text="打开预览字幕", command=s.open_preview, state="disabled"); s.bo.pack(side="left")
        s.bf = ttk.Button(cf, text="打开所在文件夹", command=s.reveal, state="disabled"); s.bf.pack(side="left", padx=6)
        tk.Label(f, text="停止后再开始会从断点继续", font=(FONT, 11), bg=BG, fg=SUB).pack(anchor="w", pady=(4, 0))
        # —— 进度卡片 ——
        card = tk.Frame(f, bg=CARD, highlightthickness=1, highlightbackground="#e5e5ea")
        card.pack(fill="x", pady=14); inner = tk.Frame(card, bg=CARD); inner.pack(fill="x", padx=18, pady=14)
        top = tk.Frame(inner, bg=CARD); top.pack(fill="x")
        s.pct = tk.Label(top, text="0%", font=(FONT, 34, "bold"), bg=CARD, fg=FG); s.pct.pack(side="left")
        s.stg = tk.Frame(top, bg=CARD); s.stg.pack(side="right")
        s.stage_lbl = {}
        for k, t in (("转写", "① 转写"), ("翻译", "② 翻译")):
            l = tk.Label(s.stg, text=t, font=(FONT, 12, "bold"), bg="#f2f2f7", fg=SUB, padx=12, pady=4)
            l.pack(side="left", padx=4); s.stage_lbl[k] = l
        s.pb = Bar(inner); s.pb.pack(fill="x", pady=(8, 14))
        grid = tk.Frame(inner, bg=CARD); grid.pack(fill="x")
        s.info = {}
        for i, k in enumerate(("状态", "当前步骤", "已用时", "剩余约", "文件")):
            c = tk.Frame(grid, bg="#f7f7fa", padx=12, pady=8); c.grid(row=0, column=i, sticky="nsew", padx=4)
            grid.columnconfigure(i, weight=1)
            tk.Label(c, text=k, font=(FONT, 11), bg="#f7f7fa", fg=SUB).pack(anchor="w")
            v = tk.Label(c, text="—", font=(FONT, 14, "bold"), bg="#f7f7fa", fg=FG); v.pack(anchor="w"); s.info[k] = v
        s.tr = None; s.preview_files = []; s.outputs = []; s.files = []; s.is_preview = False
        s.log = tk.Text(f, height=7, font=("Menlo", 11), relief="flat", bd=0, bg=CARD, fg="#3a3a3c",
                        highlightthickness=1, highlightbackground="#e5e5ea", padx=8, pady=6)
        s.log.pack(fill="both", expand=True)
        s.render(); root.after(200, s.poll)

    def render(s):
        tr = s.tr; state = tr.state if tr else "空闲"
        pill = s.info["状态"]; pill.config(text=f"● {state}", fg=PILL.get(state, FG))
        if not tr:
            return
        if tr.t_end and state == "已完成":
            s.pb.set(10 if s.is_preview else 100)
            s.pct.config(text="10% 预览完成" if s.is_preview else "100%")
        elif not tr.t_end:
            v = tr.percent(); s.pb.set(v); s.pct.config(text=f"{v:.0f}%")
        unit = "段" if tr.stage == "转写" else "批"
        s.info["当前步骤"].config(text=f"{tr.stage} 第 {tr.done}/{tr.total} {unit}" if tr.stage else "准备中…")
        s.info["已用时"].config(text=fmt((tr.t_end or time.time()) - tr.t0))
        e = tr.eta()
        s.info["剩余约"].config(text="—" if tr.t_end else (fmt(e) if e is not None else "估算中…"))
        s.info["文件"].config(text=f"{tr.fi or 1}/{tr.nf or len(s.files) or 1}")
        show = tr.mode == "all"
        for k, l in s.stage_lbl.items():
            if not show:
                l.pack_forget(); continue
            if not l.winfo_ismapped(): l.pack(side="left", padx=4)
            on = tr.stage == k and not tr.t_end
            done = (k == "转写" and tr.stage == "翻译") or (tr.t_end and state == "已完成")
            l.config(bg=_mix(0 if k == "转写" else 1) if on else ("#e8f0fe" if done else "#f2f2f7"),
                     fg="white" if on else ("#0a84ff" if done else SUB))

    def add(s):
        for p in filedialog.askopenfilenames(title="选择视频"):
            if p not in s.lb.get(0, "end"): s.lb.insert("end", p)

    def rm(s):
        for i in reversed(s.lb.curselection()): s.lb.delete(i)

    def say(s, m): s.q.put(m)

    def poll(s):
        while not s.q.empty():
            s.log.insert("end", s.q.get() + "\n"); s.log.see("end")
        if s.th and not s.th.is_alive():
            s.th = None
            for b in (s.bs, s.bp, s.bc): b.config(state="normal")
            s.bt.config(state="disabled")
            if s.tr:
                s.tr.state = "已停止" if s.stop.is_set() else "已完成"
                s.tr.t_end = time.time()
            if s.preview_files: s.bo.config(state="normal")
            if s._existing_outputs(): s.bf.config(state="normal")
        s.render()
        s.root.after(500, s.poll)

    def prog(s, *a):
        if s.tr: s.tr.update(*a)

    def job(s, files, step, be, preview):
        res = pipeline.run(files, step, be, s.say, s.stop, prog=s.prog, preview=preview) or []
        s.outputs = [p for p in res if p and os.path.exists(p)]
        if preview:
            s.preview_files = list(s.outputs)

    def _existing_outputs(s):
        out = list(s.outputs)
        if not out:  # 只转写 / 被停止：找已有的 .zh.srt 或 .ja.srt
            for f in s.files:
                b = pipeline.base_path(f)
                for ext in (".zh.srt", ".ja.srt"):
                    if os.path.exists(b + ext): out.append(b + ext); break
        return out

    def reveal(s):
        for p in s._existing_outputs():
            subprocess.Popen(["open", "-R", p])

    def open_preview(s):
        for p in s.preview_files:
            subprocess.Popen(["open", "-R", p]); subprocess.Popen(["open", "-e", p])

    def start(s, preview=False):
        files = list(s.lb.get(0, "end"))
        if not files: s.say("请先添加视频文件"); return
        s.stop.clear(); s.bt.config(state="normal")
        for b in (s.bs, s.bp, s.bc, s.bo, s.bf): b.config(state="disabled")
        s.tr = Tracker("all" if preview else s.step.get()); s.preview_files = []; s.outputs = []
        s.files = files; s.is_preview = preview
        s.th = threading.Thread(target=s.job, daemon=True,
                                args=(files, s.step.get(), s.be.get(), preview))
        s.th.start()

    def do_stop(s):
        s.stop.set(); s.say("正在停止（当前这一段/批完成后停）…")


def demo(r, app, shot=None):
    """--demo：不跑流水线，模拟进度用于截图/预览界面"""
    app.lb.insert("end", "/Users/me/Movies/示例视频_1080p.mp4")
    app.files = ["/Users/me/Movies/示例视频_1080p.mp4"]
    app.tr = Tracker("all"); app.tr.t0 -= 754
    for i in range(1, 6): app.tr.update(1, 1, "转写", i, 5, False)
    app.tr.times = []; app.tr.update(1, 1, "翻译", 0, 48, False)
    for i in range(1, 26): app.tr.last -= 9; app.tr.update(1, 1, "翻译", i, 48, False)
    for m in ("===== (1/1) 示例视频_1080p.mp4 =====", "[转写] 5 段全部完成", "[翻译] 1426 条，48 批，后端 plamo",
              "[翻译] 第 24/48 批完成，用时 18s", "[翻译] 第 25/48 批完成，用时 17s"):
        app.say(m)
    if shot:
        def cap():
            r.update(); x, y, w, h = r.winfo_rootx(), r.winfo_rooty(), r.winfo_width(), r.winfo_height()
            subprocess.run(["screencapture", "-x", "-o", f"-R{x},{y - 28},{w},{h + 28}", shot]); r.destroy()
        r.after(2500, cap)


if __name__ == "__main__":
    import sys
    r = tk.Tk(); a = App(r)
    if "--demo" in sys.argv:
        i = sys.argv.index("--demo"); demo(r, a, sys.argv[i + 1] if len(sys.argv) > i + 1 else None)
    r.mainloop()
