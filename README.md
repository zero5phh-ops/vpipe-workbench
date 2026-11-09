# vpipe工作台

A small local web page for running **MiniMax H3** (video with sound) and **Qwen Image 2.1 Turbo** (images) on a Mac, through the [vpipe](https://github.com/tgo-app-dev/vpipe) command-line engine. Everything runs on your own machine: no cloud, no credits.

一個在 Mac 本機跑 AI 影片和圖片的小網頁。它把 vpipe 的指令包成表單：選模型、大小、秒數，寫 prompt，按「開始生成」就好。

> The interface comes in **English and Traditional Chinese**; switch with the 中文 / EN button in the top-right corner.
> 介面有繁體中文和英文，右上角切換。

## 功能 Features

- **⚙ Setup check / 設定檢查**: on first launch the page checks this Mac for vpipe, ffmpeg, Qwen Image, MiniMax H3, the Turbo LoRA, the preview decoders and the Codex CLI, and shows how to get whatever is missing:
  - a link to the vpipe download page
  - a copy button for the `brew` commands
  - one-click **Install** buttons for the models, with progress and disk-space checks
  - a **Login** button that signs Codex in with your ChatGPT account

  Reopen it any time with **⚙ 設定檢查**.

- **H3 影片**：文字生影片、首／尾幀、參考圖（人物／場景／物品）、參考影片（動作），可開關聲音和背景音樂，可加台詞（含馬來西亞口音英文）。
- **Qwen 圖片**：文字生圖、參考圖生圖。人物設定圖（三格：正面／背面／特寫）會自動拆成單張再送進模型，避免成品變成拼貼。
- **✨ AI 優化**：把一句中文想法改寫成詳細的 prompt（需要 Codex CLI，用 ChatGPT 帳號登入）。
- 排隊、停止、即時預覽、從實際跑過的任務自動校正預估時間、參考圖庫（@ 插入）。
- 只聽 `127.0.0.1`，並拒絕其他網站送來的請求。

## 需要 Requirements

- Apple Silicon Mac. 24 GB of memory is comfortable; H3 is slow on smaller machines (an 8-second 960×544 clip took about 5 hours on an M3 MacBook Air).
- [vpipe](https://github.com/tgo-app-dev/vpipe), built from source or from the Vpipe Manager app.
- Python 3.9 or newer (standard library only, no `pip install`).
- `ffmpeg` / `ffprobe` (`brew install ffmpeg`).
- Model weights, downloaded with vpipe into its workspace (`~/vpipe-work/models` by default). See vpipe's own docs:
  - Qwen Image 2.1 Turbo: `Qwen/Qwen-Image-2.1-Turbo`
  - MiniMax H3, quantized locally to `local/MiniMax-H3-FL2VA-8bit`. A different id can be set with `VPIPE_H3_MODEL`.
  - Optional extras: the Turbo LoRA (`larryvrh/MiniMax-H3-Turbo-Lora`), Pika H3 Flex, H3 Ref2VA (`local/MiniMax-H3-Ref2VA-4bit`), and the `madebyollin/taeqi2_1` preview decoder. The page greys out anything that isn't installed.
- Optional: the [Codex CLI](https://github.com/openai/codex), for the ✨ AI 優化 button.

## 使用 Usage

```bash
git clone https://github.com/zero5phh-ops/vpipe-workbench.git
cd vpipe-workbench
./start.sh
```

`start.sh` starts the server, if it isn't already running, and opens http://127.0.0.1:8765. The first time, the **⚙ Setup check** panel opens and lists what's missing. Install vpipe from its download page, then let the page download the models for you; the install pipelines are in `templates/prepare-*.vpipeline`. The H3 install downloads about 115 GB, needs about 185 GB free while it runs, ends at 66 GB, and takes hours.

Settings, all optional environment variables:

| Variable | Meaning | Default |
|---|---|---|
| `VPIPE_WORK` | vpipe workspace (with `./models`); jobs go to `jobs/` | `~/vpipe-work` |
| `VPIPE_BIN` | vpipe executable | `vpipe` on PATH, then common build locations |
| `VPIPE_PORT` | port | `8765` |
| `VPIPE_H3_MODEL` / `VPIPE_REF2VA_MODEL` | H3 model ids | `local/MiniMax-H3-FL2VA-8bit` / `local/MiniMax-H3-Ref2VA-4bit` |
| `FFMPEG` / `FFPROBE` | ffmpeg tools | found on PATH |
| `CODEX_BIN` | Codex CLI | `codex` on PATH, or the copy inside the ChatGPT app |

Each job is saved in `$VPIPE_WORK/jobs/<id>/`: the `.vpipeline`, the log, previews and the output. Deleting a job moves its folder to the Trash.

## 授權 License

This page's own code is MIT-licensed (see `LICENSE`). It doesn't contain or redistribute any model weights or vpipe code. It only runs the vpipe program you install yourself.

**The models have their own licenses, and they apply to you when you download and use them.** Read them before you rely on the output, especially for commercial work:

- **vpipe**: Apache License 2.0.
- **MiniMax H3**, and LoRAs built on it such as Pika H3 Flex: *MiniMax H3 Community License Agreement*. Among other terms, it **excludes the EU, the UK, South Korea and the United States** from its territory, and it has an Acceptable Use Policy.
- **Qwen Image 2.1 Turbo**: Qwen's own model license (tagged `qwen-research` on Hugging Face). Check whether it allows your use case.
- **taeqi2_1** (preview decoder): MIT.
- The Turbo LoRAs: see their Hugging Face pages.

Generated people should be adults. Don't use the tools to imitate real people without their consent.
