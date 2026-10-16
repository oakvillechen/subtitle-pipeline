# 字幕翻译：日语视频 → 中文字幕（Mac 本地流水线）

全部在 Apple 芯片 Mac 本机运行：免费、离线、有图形界面，并且可以断点续跑。

## 功能
- **转写**：用 mlx-whisper `large-v3-turbo` 识别日语，按 10 分钟分段并缓存，生成 `视频名.ja.srt`。
- **翻译**：保留时间轴，生成 `视频名.zh.srt`，放在视频同一目录。
  - **本地 PLaMo（默认）**：模型 `mlx-community/plamo-2-translate`（4bit，约 5.4GB），运行时占内存约 6GB；离线、无审查，速度约 0.6 秒/行。
  - **本地 Ollama**：模型 `qwen3:14b`。
  - PLaMo 翻译失败的行会自动改用 Ollama；再失败，就保留日文原文并标上【未翻译】。
- **先试 10%**：先只处理前约 10% 作为预览，满意后点「继续完成全部」。
- **进度界面**：
  - 圆角渐变进度条和大号百分比；全流程模式下显示 ①转写 ②翻译 两个阶段。
  - 信息卡片：状态（运行中 / 已完成 / 已停止）、当前步骤、已用时、剩余约、文件进度。
- **打开所在文件夹**：完成后点这个按钮，会在 Finder 中定位生成的 `.zh.srt`（多个文件就逐个定位）。
- 停止或关闭窗口后，再次开始会自动从断点继续。

## 安装
```bash
brew install ffmpeg            # 必需
brew install ollama            # 可选（Ollama 后端）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
PLaMo 模型首次使用时会自动从 Hugging Face 下载，也可以预先下载：
`.venv/bin/python -c "from huggingface_hub import snapshot_download as s; s('mlx-community/plamo-2-translate')"`
使用 PLaMo 须遵守 PLaMo Community License（Built with PLaMo）。

## 使用
- 生成并安装 App：运行 `./build_app.sh`，会安装到 `/Applications/字幕翻译.app`，日志写入 `app.log`。
- 也可以直接双击 `启动字幕工具.command`。
- 命令行：`.venv/bin/python pipeline.py 视频.mp4 --backend plamo|ollama [--step all|transcribe|translate] [--preview]`
- 界面演示（模拟进度，不跑流水线）：`.venv/bin/python gui.py --demo`
