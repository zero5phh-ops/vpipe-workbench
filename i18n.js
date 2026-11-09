// vpipe工作台 — language switch (中文 / English).
// The page is written in Chinese. In English mode a MutationObserver
// translates every text node, title and placeholder as it appears (static
// HTML, text set by the page's script, server messages), so the main script
// needs no changes. User text (prompts, logs, dialogue) is never touched.
let LANG = "zh";
try { LANG = localStorage.getItem("vpipe-lang") || (navigator.language.startsWith("zh") ? "zh" : "en"); } catch (e) {}

const EN = {
  // header / form
  "在這台 Mac 本機生成 · 可排隊，一次跑一個 · 結果存在 ~/vpipe-work/jobs/": "Generated locally on this Mac · jobs queue up, one runs at a time · results are saved in ~/vpipe-work/jobs/",
  "影片＋聲音": "video + sound", "圖片": "image", "影片": "video",
  "畫面設定": "Picture", "草稿模式": "Draft mode", "大小": "Size", "加速": "Speed-up", "不加速": "None",
  "步數": "Steps", "4 步": "4 steps", "6 步": "6 steps", "8 步": "8 steps", "秒數": "Length", "秒": "s",
  "參考畫面": "Reference", "純文字": "Text only", "首幀／尾幀": "First / last frame", "參考圖": "Reference images",
  "首幀": "First frame", "尾幀": "Last frame", "＋ 首幀": "＋ First frame", "＋ 尾幀": "＋ Last frame",
  "零樣本（FL2VA）": "Zero-shot (FL2VA)", "正式 Ref2VA": "Ref2VA",
  "人物": "People", "場景": "Scene", "物品": "Objects", "最多 5 位": "up to 5", "1 張": "1 image", "最多 5 件": "up to 5",
  "動作影片": "Motion video", "1 段，例如跳舞 Reel": "1 clip, e.g. a dance reel", "＋ 影片": "＋ Video",
  "從第幾秒開始": "Start at (s)", "用原片音樂": "Use the clip's music", "最多 3 張": "up to 3",
  "＋ 加入圖片": "＋ Add images", "從圖庫選": "From library", "人物設定圖模板": "Character sheet template",
  "↩ 還原": "↩ Undo", "✨ AI 優化": "✨ AI enhance",
  "用中文或英文寫想法都可以，再按 ✨ AI 優化。輸入 @ 插入參考圖。": "Write your idea in English or Chinese, then press ✨ AI enhance. Type @ to insert a reference image.",
  "聲音與台詞": "Sound and dialogue", "聲音": "Sound", "背景音樂": "Background music", "字幕": "Subtitles",
  "音樂風格，例如 soft piano, lo-fi": "Music style, e.g. soft piano, lo-fi", "台詞語言": "Dialogue language",
  "中文": "Chinese", "馬來語": "Malay", "Manglish（馬來西亞口音英文）": "Manglish (Malaysian-accented English)",
  "🇲🇾 馬來西亞混搭": "🇲🇾 Malaysian mix", "日本語": "Japanese",
  "一行一句，可寫「誰：台詞」，例如\nthe gym guy: Hi ah moi, keen to train at our gym leh?": "One line each, \"who: line\", e.g.\nthe gym guy: Hi ah moi, keen to train at our gym leh?",
  "⚙ 設定檢查": "⚙ Setup check", "未知的安裝項目": "Unknown install item",
  "已經在安裝別的項目，請等它完成": "Another item is installing; wait for it to finish",
  "正在生成或排隊中，等任務完成後再安裝": "A job is running or queued; install after it finishes",
  "正在安裝模型，裝好後再生成": "A model is installing; generate after it finishes",
  "先安裝 Codex CLI": "Install the Codex CLI first",
  "隨機生成": "Random", "自己輸入號碼": "Enter a number", "號碼": "Number", "例如 2611": "e.g. 2611",
  "開始生成": "Generate", "加入排隊": "Add to queue",
  // right column
  "排隊中": "Queued", "生成中": "Generating", "等第一步完成就會出現預覽": "A preview appears after the first step",
  "階段": "Stage", "進度": "Progress", "已用時間": "Elapsed", "粗估總時間": "Estimated total", "停止": "Stop",
  "參考圖庫": "Reference library", "收起": "Collapse", "展開": "Expand", "從圖庫選擇": "Choose from library", "關閉": "Close",
  "歷史紀錄": "History", "還沒有生成過。": "Nothing generated yet.",
  "完成": "Done", "失敗": "Failed", "已停止": "Stopped", "已取消": "Cancelled", "中斷": "Interrupted",
  "取消": "Cancel", "刪除": "Delete", "存為參考": "Save as reference", "存目前畫面為參考": "Save this frame as reference",
  "先把影片暫停在想要的畫面，再按這裡": "Pause the video on the frame you want, then press this",
  "用於影片": "Use in video", "用於圖片": "Use in image", "改名": "Rename", "存": "Save", "移除": "Remove",
  "名稱，例如 小美、客廳、拿鐵杯": "Name, e.g. Mei, living room, latte cup", "輸入：": "Inputs: ",
  "草稿": "draft", "無聲": "silent", "有配樂": "with music", "首": "First", "尾": "Last",
  // hints and messages
  "只用文字描述生成影片。": "Generate the video from the text alone.",
  "放首幀＝影片從這張圖開始動；放尾幀＝影片結束在這張圖；兩張都放＝從 A 動到 B。圖會依所選大小裁切，建議用跟影片同比例的圖。": "A first frame starts the video from that picture; a last frame ends on it; both = move from A to B. Pictures are cropped to the chosen size, so use the video's aspect ratio.",
  "Pika Flex 固定 6 步": "Pika Flex always runs 6 steps", "Pika Flex（未下載）": "Pika Flex (not downloaded)",
  "Turbo（未下載）": "Turbo (not downloaded)", "Ref2VA 或它的 Pika 加速還沒裝好": "Ref2VA or its Pika speed-up is not installed",
  "讀不到這張圖": "Can't read this image", "影片太大（超過 150MB），先剪短再放": "The video is over 150 MB; trim it first",
  "粗估時間": "Estimate", "實際長度": "Real length", "模式": "Mode", "T2I 文字生圖": "T2I text to image",
  "＋動作影片": "＋ motion video", "：時間約 ×3": ": about ×3 the time",
  "依 M3 MacBook Air 實測起算，跑過幾個任務後會照你這台自動校正，僅供參考": "Starts from M3 MacBook Air timings and calibrates to this Mac after a few jobs; rough only",
  "請放至少一張首幀或尾幀": "Add at least a first or a last frame", "請放至少一張參考圖或一段影片": "Add at least one reference image or a video",
  "動作影片要用「正式 Ref2VA」": "A motion video needs Ref2VA", "已加入排隊": "Added to the queue", "已開始": "Started",
  "確定要停止目前的任務？": "Stop the current job?",
  "⚠ 台詞還有中文字，Manglish 念不出來。改成英文，或按 ✨ AI 優化。": "⚠ The lines still contain Chinese, which Manglish can't speak. Rewrite them in English or press ✨ AI enhance.",
  "（輸入台詞後，這裡會顯示每行判斷成哪種語言）": "(After you type the lines, this shows which language each line was detected as)",
  "改好了。": "Done.", "改寫後的 prompt 和台詞都可以再手動修改。": "You can still edit the rewritten prompt and lines.",
  "改寫後的 prompt 可以再手動修改。": "You can still edit the rewritten prompt.",
  "⚠ 先在 Prompt 寫一點想法": "⚠ Write an idea in the prompt first", "已還原": "Undone",
  "新名稱": "New name", "圖片參考圖最多 3 張": "Up to 3 reference images for an image",
  "影片還沒載入，先播放一下再試": "The video hasn't loaded yet; play it briefly and try again",
  "儲存失敗": "Save failed", "刪除失敗": "Delete failed", "沒有符合的參考圖": "No matching reference",
  "還沒有放參考圖。影片：在「畫面控制」選參考圖或首尾幀；圖片：在「參考圖」加入圖片。": "No reference images yet. Video: choose reference images or first/last frames under Reference; image: add pictures under Reference images.",
  // server
  "準備中（載入模型）": "Preparing (loading models)", "生成中（去噪）": "Generating (denoising)", "解碼畫面": "Decoding frames",
  "未知的模型": "Unknown model", "未知的大小": "Unknown size", "請寫 prompt": "Please write a prompt",
  "秒數要在 1–10 之間": "Length must be 1–10 seconds",
  "H3 的首/尾幀和參考圖不能同時用，請擇一": "H3 can't use first/last frames and reference images together; pick one",
  "參考影片不能和首/尾幀同時用": "A reference video can't be combined with first/last frames",
  "步數只能是 4、6 或 8": "Steps must be 4, 6 or 8",
  "未知的加速方式": "Unknown speed-up", "任務編號不對": "Invalid job id",
  "這個任務正在生成，請先停止": "This job is running; stop it first",
  "這個任務還在排隊，請用排隊區的「取消」": "This job is still queued; use Cancel in the queue",
  "分類只能是人物、場景或物品": "Category must be people, scene or object", "未命名": "Untitled",
  "這筆紀錄沒有圖片可以存": "This job has no image to save", "沒有圖片": "No image",
  "找不到這張參考圖": "Reference image not found",
  "找不到 ChatGPT 的 Codex（要先裝 ChatGPT app 並登入）": "Codex CLI not found (install it, or the ChatGPT app, and sign in)",
  "先在 Prompt 或台詞寫一點想法": "Write an idea in the prompt or the lines first",
  "AI 幫手超過 4 分鐘沒回應，請再試一次": "The AI helper didn't answer within 4 minutes; try again",
  "AI 幫手回的格式看不懂，請再試一次": "The AI helper's answer couldn't be read; try again",
  "Ref2VA 模型還沒裝好，不能用參考影片／Ref2VA": "The Ref2VA model isn't installed, so reference videos / Ref2VA can't be used",
  "Ref2VA 需要 Pika H3 Flex（ref2va）加速，還沒下載": "Ref2VA needs the Pika H3 Flex (ref2va) speed-up, which isn't downloaded",
  "Pika H3 Flex（fl2va）還沒下載，請改用 Turbo 或不加速": "Pika H3 Flex (fl2va) isn't downloaded; use Turbo or None",
  "Turbo LoRA 還沒下載，請改成不加速": "The Turbo LoRA isn't downloaded; choose None",
  "參考影片從開始秒數算起太短了，至少要 2 秒": "The reference video is too short from that start time; it needs at least 2 s",
};
const CAT_EN = { "人物": "people", "場景": "scene", "物品": "object" };
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
const EN_PATTERNS = [
  [/^(\d+) 小時 (\d+) 分$/, "$1 h $2 min"], [/^(\d+) 分 (\d+) 秒$/, "$1 min $2 s"], [/^(\d+(?:\.\d+)?) 秒$/, "$1 s"],
  [/^(\d+) 步$/, "$1 steps"], [/^（(\d+) 格）$/, "($1 frames)"], [/^R2I（(\d+) 張參考圖）$/, "R2I ($1 reference images)"],
  [/^已放 (\d+) 張（最多 9 張），prompt 裡用 person 1、object 2 指定。$/, "$1 added (up to 9). Refer to them as person 1, object 2 in the prompt."],
  [/^參考圖最多 (\d+) 張，目前 (\d+) 張$/, "Up to $1 reference images; you have $2"],
  [/^參考圖最多 (\d+) 張$/, "Up to $1 reference images"],
  [/^（(\d+) 個，全部約 (.+)）$/, (m, n, t) => `(${n}, about ${tr(t)} in all)`],
  [/^約 (.+)$/, (m, t) => "≈ " + tr(t)], [/^用時 (.+)$/, (m, t) => "took " + tr(t)],
  [/^生成中：(.+)$/, (m, t) => "Generating: " + tr(t)],
  [/^AI 改寫中… (\d+) 秒$/, "AI rewriting… $1 s"], [/^完成（(\d+) 秒）$/, "Done ($1 s)"],
  [/^預覽 · 第 (.+) 步（低解析度草稿）$/, "Preview · step $1 (low-res draft)"],
  [/^人物 (\d+)$/, "Person $1"], [/^物品 (\d+)$/, "Object $1"], [/^參考圖 (\d+)$/, "Picture $1"], [/^參(\d+)$/, "Ref $1"],
  [/^H3 影片$/, "H3 video"], [/^Qwen 圖片$/, "Qwen image"],
  [/^(草稿 )?(\d+:\d+)( 小| 大 \(2048\))?　(\d+×\d+)$/, (m, d, r, s, wh) =>
    `${d ? "Draft " : ""}${r}${s === " 小" ? " small" : s ? " large (2048)" : ""}　${wh}`],
  [/^還沒有(人物|場景|物品)參考圖。$/, (m, c) => `No ${CAT_EN[c]} references yet.`],
  [/^從圖庫選(人物|場景|物品)$/, (m, c) => `Choose ${CAT_EN[c]} from library`],
  [/^圖庫裡還沒有(人物|場景|物品)?參考圖。先在歷史紀錄按「存為參考」。$/, (m, c) =>
    `No ${c ? CAT_EN[c] + " " : ""}references in the library yet. Press "Save as reference" in History first.`],
  [/^＋ (人物|場景|物品)$/, (m, c) => "＋ " + cap(CAT_EN[c])],
  [/^已存到「(人物|場景|物品)」：(.*)$/, (m, c, n) => `Saved to ${CAT_EN[c]}: ${n}`],
  [/^(人物|場景|物品)最多 (\d+) 張$/, (m, c, n) => `Up to ${n} ${CAT_EN[c]} images`],
  [/^刪除參考圖「(.*)」？會移到垃圾桶。$/, (m, n) => `Delete reference "${n}"? It moves to the Trash.`],
  [/^刪除這筆紀錄（(.*)）？\n檔案會移到垃圾桶，清空垃圾桶前都還能救回來。$/, (m, id) =>
    `Delete this job (${id})?\nIts files move to the Trash and can be recovered until you empty it.`],
  [/^無法啟動 vpipe：([\s\S]*)$/, "Couldn't start vpipe: $1"], [/^vpipe 結束碼 (.*)$/, "vpipe exit code $1"],
  [/^參考影片讀不到或剪不了：([\s\S]*)$/, "Couldn't read or cut the reference video: $1"],
  [/^AI 幫手失敗：([\s\S]*)$/, "AI helper failed: $1"],
  [/^磁碟空間不夠：需要約 (\d+) GB，目前只剩 (\d+) GB$/, "Not enough disk space: needs about $1 GB, only $2 GB free"],
  [/^找不到 vpipe 執行檔（可用環境變數 VPIPE_BIN 指定）$/, "vpipe not found (set VPIPE_BIN to point at it)"], [/^看不懂的請求：([\s\S]*)$/, "Bad request: $1"],
  [/^伺服器出錯：([\s\S]*)$/, "Server error: $1"], [/^⚠ ([\s\S]+)$/, (m, t) => "⚠ " + tr(t)],
  [/^seed (\d+) · (影片|圖片) · ([\s\S]*)$/, (m, n, k, p) => `seed ${n} · ${k === "影片" ? "video" : "image"} · ${p}`],
];
const HAS_CJK = /[　-鿿＀-￯]/;

function tr(s) {
  if (LANG !== "en" || !s || !HAS_CJK.test(s)) return s;
  const lead = s.match(/^\s*/)[0], tail = s.match(/\s*$/)[0], core = s.trim();
  if (EN[core] !== undefined) return lead + EN[core] + tail;
  for (const [re, to] of EN_PATTERNS) if (re.test(core)) return lead + core.replace(re, to) + tail;
  if (core.includes("·"))   // "H3 · 960×544 · 3 秒 · 草稿" -> part by part
    return lead + core.split("·").map(x => tr(x.trim())).join(" · ").trim() + tail;
  return s;
}

// User text lives in these; never translate it.
const RAW = "textarea, input, pre, .qp, .meta p, #myLines, #stLog, #langSw, #setupCard, script, style";
const ORIG = new WeakMap();   // text node -> { zh, out } so switching back restores the Chinese

function trNode(n) {
  if (n.nodeType === 3) {
    if (n.parentElement && n.parentElement.closest(RAW)) return;
    const rec = ORIG.get(n);
    const zh = rec && rec.out === n.nodeValue ? rec.zh : n.nodeValue;   // changed by the page -> new original
    const out = LANG === "en" ? tr(zh) : zh;
    if (out !== zh || rec) ORIG.set(n, { zh, out });
    if (out !== n.nodeValue) n.nodeValue = out;
  } else if (n.nodeType === 1) {
    if (n.matches("script, style")) return;
    for (const a of ["title", "placeholder"]) {
      if (!n.hasAttribute(a)) continue;
      const cur = n.getAttribute(a), k = "i18n" + a;
      if (n[k] === undefined || n[k].out !== cur) n[k] = { zh: cur };
      const out = LANG === "en" ? tr(n[k].zh) : n[k].zh;
      n[k].out = out;
      if (out !== cur) n.setAttribute(a, out);
    }
    n.childNodes.forEach(trNode);
  }
}

let trBusy = false;
new MutationObserver(ms => {
  if (trBusy) return;
  trBusy = true;
  try {
    for (const m of ms) {
      if (m.type === "childList") m.addedNodes.forEach(trNode);
      else trNode(m.target);
    }
  } finally { trBusy = false; }
}).observe(document.documentElement, { subtree: true, childList: true, characterData: true,
                                       attributes: true, attributeFilter: ["title", "placeholder"] });

for (const fn of ["alert", "confirm", "prompt"]) {
  const real = window[fn].bind(window);
  window[fn] = (msg, ...rest) => real(tr(String(msg == null ? "" : msg)), ...rest);
}

function setLang(l) {
  LANG = l;
  try { localStorage.setItem("vpipe-lang", l); } catch (e) {}
  document.documentElement.lang = l === "en" ? "en" : "zh-Hant";
  trBusy = true;
  try { trNode(document.body); } finally { trBusy = false; }
  document.querySelectorAll("#langSw button").forEach(b => b.classList.toggle("on", b.dataset.l === l));
}
