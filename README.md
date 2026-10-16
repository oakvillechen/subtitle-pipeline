# 字幕翻译：日语视频 → 中文字幕（Mac 本地流水线）

在 Apple 芯片 Mac 上运行，免费，有图形界面，可断点续跑。

## 功能
- **转写**：mlx-whisper `large-v3-turbo`，按 10 分钟分段并缓存，生成 `视频名.ja.srt`
- **翻译**（保留时间轴，生成 `视频名.zh.srt`，与视频同目录）：
  - **Google Gemini（免费，默认）**：优先 flash-lite（15 RPM / 500 RPD），再回退到 flash 模型；客户端限速，当日额度用完自动跳过
  - **本地 PLaMo**：`mlx-community/plamo-2-translate`（4bit，约 5.4GB，占内存约 6GB），离线、无审查，约 0.6 秒/行
  - **本地 Ollama**：`qwen3:14b`
  - Gemini 全部失败时自动回退：PLaMo → Ollama → 保留日文并标【未翻译】
- **先试 10%**：只处理前约 10% 预览，满意再「继续完成全部」
- 进度条、状态行，停止/关闭后再次开始自动续跑

## 安装
```bash
brew install ffmpeg            # 必需
brew install ollama            # 可选（Ollama 后端）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp keys.env.example keys.env && chmod 600 keys.env   # 填入 Gemini Key（https://aistudio.google.com/apikey）
```
PLaMo 模型首次使用时会自动从 Hugging Face 下载（也可预先下载：
`.venv/bin/python -c "from huggingface_hub import snapshot_download as s; s('mlx-community/plamo-2-translate')"`）。
PLaMo 使用须遵守 PLaMo Community License。

## 使用
- 生成并安装 App：`./build_app.sh` → `/Applications/字幕翻译.app`（日志写入 `app.log`）
- 或双击 `启动字幕工具.command`
- 命令行：`.venv/bin/python pipeline.py 视频.mp4 --backend gemini|plamo|ollama [--step all|transcribe|translate] [--preview]`
