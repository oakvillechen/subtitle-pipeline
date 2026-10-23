# 字幕翻译：日语视频 → 中文字幕（Mac 本地工具）

在 Apple 芯片 Mac 上完全本地运行的字幕工具：把日语视频转写成日文字幕，再翻译成中文字幕，生成可直接挂载的 `.srt` 文件。全程离线、不上传云端、不产生费用。

## 功能

- **转写**：mlx-whisper `large-v3-turbo` 识别日语语音，按 10 分钟分段并缓存，生成 `视频名.ja.srt`。
- **翻译**：保留原时间轴，生成 `视频名.zh.srt`，与视频放在同一目录。
- 默认后端 **PLaMo**：`mlx-community/plamo-2-translate`（4bit），离线运行，约 0.6 秒/行。
- 备援后端 **Ollama**：`qwen3:14b`。PLaMo 翻译失败的行会自动改走 Ollama；仍失败则保留日文原文并标注。
- **先试 10%**：可只处理前约 10% 生成预览字幕，满意后再继续完成全部，已完成部分不重做。
- **断点续跑**：停止或关闭窗口后，下次开始自动从断点继续。
- **图形界面**：进度条 + 百分比、当前阶段（①转写 ②翻译）、已用时与预计剩余、文件进度；完成后可一键在 Finder 中定位生成的字幕。

## 模型（首次运行自动下载）

| 用途 | 模型 | 存放位置 | 大小约 |
|---|---|---|---|
| 转写 | mlx-community/whisper-large-v3-turbo | `~/.cache/huggingface/hub/` | 1.6 GB |
| 翻译（默认） | mlx-community/plamo-2-translate | `~/.cache/huggingface/hub/` | 5.4 GB |
| 翻译（备援） | qwen3:14b（Ollama） | `~/.ollama/models/` | 9 GB |

## 安装

```bash
brew install ffmpeg # 必需
brew install ollama # 可选，仅备援后端需要
python3 -m venv.venv
.venv/bin/pip install -r requirements.txt
```

PLaMo 模型首次使用时自动从 Hugging Face 下载，也可预先下载：

```bash
.venv/bin/python -c "from huggingface_hub import snapshot_download as s; s('mlx-community/plamo-2-translate')"
ollama pull qwen3:14b # 备援后端
```

## 使用

- **App**：运行 `./build_app.sh`，安装到 `/Applications/字幕翻译.app`，双击打开即可（日志写入 `app.log`）。
- **免安装**：直接双击 `启动字幕工具.command`。
- **命令行**：

```bash
.venv/bin/python pipeline.py 视频.mp4 [--backend plamo|ollama] [--step all|transcribe|translate] [--preview]
```

- 界面演示（模拟进度，不跑流水线）：`.venv/bin/python gui.py --demo`

## 文件说明

| 文件 | 作用 |
|---|---|
| `pipeline.py` | 核心流水线：转写、翻译、断点缓存、命令行入口 |
| `gui.py` | 图形界面 |
| `build_app.sh` | 打包并安装 `/Applications/字幕翻译.app` |
| `assets/make_icon.py` | 生成 App 图标 |
| `启动字幕工具.command` | 双击启动脚本（自动拉起 Ollama 服务） |
| `requirements.txt` | Python 依赖 |

## 备注

- `keys.env` 为本地私有配置，已被 `.gitignore` 排除，永远不会提交到仓库。
- PLaMo 模型遵循 PLaMo Community License（Built with PLaMo）。
