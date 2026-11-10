#!/usr/bin/env python3
"""vpipe工作台 — a small local web page in front of the vpipe CLI.

Pick a model (MiniMax H3 video or Qwen Image 2.1 Turbo), a size, a length
and a prompt; this writes a .vpipeline into $VPIPE_WORK/jobs/<id>/, runs
the vpipe binary there and reports progress. Listens on 127.0.0.1 only.

Settings (environment variables, all optional):
  VPIPE_WORK   vpipe's workspace with ./models          (default ~/vpipe-work)
  VPIPE_BIN    the vpipe executable                      (default: found below)
  VPIPE_PORT   port to listen on                         (default 8765)
  FFMPEG / FFPROBE   ffmpeg tools                        (default: found on PATH)
  CODEX_BIN    Codex CLI for the ✨ AI helper            (default: found below)
  VPIPE_ANE    1 = H3 shares work with the Neural Engine (default 1; 0 = GPU only)
  VPIPE_LTX_PLUGIN   the vpipe-ltx-2.5 plugin (.so)      (default: found below)
  VPIPE_LTX_MODEL    LTX-2.5 model under ./models        (default local/LTX-2.5-distilled-8bit)
"""
import base64
import json
import math
import os
import mimetypes
import re
import shutil
import signal
import struct
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

HOST, PORT = "127.0.0.1", int(os.environ.get("VPIPE_PORT") or 8765)
HERE = Path(__file__).resolve().parent
WORK = Path(os.environ.get("VPIPE_WORK") or Path.home() / "vpipe-work").expanduser()
JOBS = WORK / "jobs"
VPIPE_CANDIDATES = [p for p in [
    os.environ.get("VPIPE_BIN"),
    shutil.which("vpipe"),
    str(Path.home() / "vpipe/build/apps/vpipe/vpipe"),
    str(Path.home() / "Documents/Claude/Projects/vpipe/build/apps/vpipe/vpipe"),
    "/Applications/Vpipe Manager.app/Contents/Helpers/vpipe",
] if p]
H3_TEMPLATE = HERE / "templates" / "minimax-h3-text-to-video-turbo.vpipeline"
QWEN_TEMPLATE = HERE / "templates" / "qwen-image-2.1-turbo.vpipeline"
LTX_TEMPLATE = HERE / "templates" / "ltx-2.5-text-to-video.vpipeline"
LTX_MODEL = os.environ.get("VPIPE_LTX_MODEL") or "local/LTX-2.5-distilled-8bit"
LTX_PLUGIN_CANDIDATES = [p for p in [
    os.environ.get("VPIPE_LTX_PLUGIN"),
    str(WORK / "plugins" / "vpipe-ltx-2.5.so"),
    str(Path.home() / "vpipe-ltx-2.5/build/vpipe-ltx-2.5.so"),
    str(Path.home() / "Documents/Claude/Projects/vpipe-ltx-2.5/build/vpipe-ltx-2.5.so"),
] if p]
VIDEO_MODELS = ("h3", "ltx")


def _tool(env, name):
    for p in (os.environ.get(env), shutil.which(name), f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if p and Path(p).exists():
            return p
    return name   # fails with a clear "No such file" if really missing


FFMPEG, FFPROBE = _tool("FFMPEG", "ffmpeg"), _tool("FFPROBE", "ffprobe")


def to_trash(path, name):
    """Move a file or folder to the user's Trash (works across volumes)."""
    trash = Path.home() / ".Trash"
    dst, n = trash / name, 2
    while dst.exists():
        dst = trash / f"{name}-{n}"
        n += 1
    shutil.move(str(path), str(dst))

# Sizes offered on the page. H3 wants multiples of 32, Qwen multiples of 16.
SIZES = {
    "h3": {
        "16:9": (960, 544), "16:9 小": (832, 480),
        "9:16": (544, 960), "9:16 小": (480, 832),
        "1:1": (704, 704),
        "草稿 16:9": (608, 352), "草稿 9:16": (352, 608),
    },
    # LTX-2.5: multiples of 32 too (its VAE compresses space by 32)
    "ltx": {
        "16:9": (960, 544), "16:9 小": (832, 480),
        "9:16": (544, 960), "9:16 小": (480, 832),
        "1:1": (704, 704),
        "草稿 16:9": (640, 352), "草稿 9:16": (352, 640),
    },
    "qwen": {
        "1:1": (1024, 1024), "16:9": (1344, 768), "9:16": (768, 1344),
        "4:3": (1184, 896), "1:1 大 (2048)": (2048, 2048),
    },
}

# Baseline measured on an M3 MacBook Air 24 GB (2026-11-05); calibration() refits
# it from this Mac's own finished jobs. Rough estimates only.
H3_REF = (29070 + 320, 18090.0)     # tokens, seconds (8 s 960x544, 6 steps)
QWEN_REF = (4175, 232.0)            # tokens, seconds (1024^2, 8 steps, warm)
# 832x480, 121 frames, first frame, 8-bit model on the internal SSD (2026-11-10)
LTX_REF = (6240, 1027.0)
REFS = {"h3": H3_REF, "qwen": QWEN_REF, "ltx": LTX_REF}

lock = threading.Lock()
current = {"proc": None, "job": None, "running": False}
queue = []  # [(job, pipeline_path)] waiting their turn; one vpipe at a time


def vpipe_bin():
    for p in VPIPE_CANDIDATES:
        if Path(p).exists():
            return str(p)
    raise RuntimeError("找不到 vpipe 執行檔（可用環境變數 VPIPE_BIN 指定）")


def ltx_plugin():
    for p in LTX_PLUGIN_CANDIDATES:
        if Path(p).exists():
            return str(p)
    return None


def ltx_frames(seconds):
    """Frames LTX-2.5 renders: 8k+1 (its VAE chunks time by 8), rounded up, at 24 fps."""
    want = max(9, round(seconds * 24))
    return 8 * math.ceil((want - 1) / 8) + 1


def h3_frames(seconds):
    """Frames H3 actually renders: 17k+5, rounded up, at 24 fps."""
    want = max(5, round(seconds * 24))
    k = math.ceil((want - 5) / 17)
    return 17 * k + 5


def _step_factor(steps):
    return 0.1 + 0.9 * (steps or 6) / 6


def calibration(model):
    """Fit time = c * tokens^p from this Mac's finished jobs (plus the seed run).

    H3 times are normalised to 6 steps first. Returns (c, p). With only one
    distinct point the exponent stays at the prior and only c moves.
    """
    pts = [REFS[model]]
    for j in list_jobs():
        if j.get("model") == model and j.get("state") == "done" and j.get("elapsed_s") and j.get("tokens"):
            t = j["elapsed_s"]
            if model == "h3":
                t /= _step_factor(j.get("steps"))
            pts.append((j["tokens"], t))
    p = 1.25
    xs = [math.log(x) for x, _ in pts]
    ys = [math.log(y) for _, y in pts]
    if len(set(round(x, 3) for x in xs)) >= 2:
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        var = sum((x - mx) ** 2 for x in xs)
        if var > 1e-6:
            p = min(2.0, max(1.0, sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var))
    c = math.exp(sum(y - p * x for x, y in zip(xs, ys)) / len(xs))
    return c, p


def estimate(model, w, h, seconds, steps=6):
    if model == "ltx":
        frames = ltx_frames(seconds)
        tokens = ((frames - 1) // 8 + 1) * (h // 32) * (w // 32)
        c, p = calibration("ltx")
        return {"frames": frames, "real_seconds": round(frames / 24, 2),
                "tokens": tokens, "eta_s": int(c * tokens ** p)}
    if model == "h3":
        frames = h3_frames(seconds)
        k = (frames - 5) // 17
        latents = 2 + 5 * k
        tokens = latents * (h // 32) * (w // 32) + int(seconds * 40)
        c, p = calibration("h3")
        # fitted at 6 steps; denoise is ~90% of a run and scales with steps
        secs = c * tokens ** p * _step_factor(steps)
        return {"frames": frames, "real_seconds": round(frames / 24, 2),
                "tokens": tokens, "eta_s": int(secs)}
    tokens = (w // 16) * (h // 16) + 79
    c, p = calibration("qwen")
    secs = c * tokens ** p
    return {"tokens": tokens, "eta_s": int(secs)}


def _gray_columns(path):
    """Width, height and 8-bit grey pixels of an image, via ffmpeg (no PIL here)."""
    pr = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                        capture_output=True, text=True)
    w, h = map(int, pr.stdout.strip().split(",")[:2])
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path),
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    return w, h, raw


def _divider_runs(n, line_stats):
    """Runs of near-white, flat lines (a sheet's panel gutters), away from the edges."""
    hits = [i for i in range(n) if n * 0.1 < i < n * 0.9
            and line_stats[i][0] > 235 and line_stats[i][1] < 8]
    runs = []
    for i in hits:
        if runs and i - runs[-1][1] <= 2:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    return [r for r in runs if r[1] - r[0] < n * 0.05]   # a gutter is thin


def _stats(vals):
    m = sum(vals) / len(vals)
    return m, (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5


def _seam_runs(w, h, raw, vertical):
    """Panels butted together with no white gutter: a straight line where the
    picture jumps across almost its whole height (or width). A normal photo
    peaks around 0.6 of its height; a panel seam is above 0.8."""
    n, m = (w, h) if vertical else (h, w)
    samples = range(0, m, max(1, m // 256))
    def px(i, j):   # i along the cut axis, j along the line
        return raw[j * w + i] if vertical else raw[i * w + j]
    score = [0.0] * n
    for i in range(int(n * 0.1), int(n * 0.9)):
        score[i] = sum(1 for j in samples if abs(px(i + 1, j) - px(i - 1, j)) > 6) / len(samples)
    hits = [i for i in range(n) if score[i] >= 0.8]
    runs = []
    for i in hits:
        if runs and i - runs[-1][1] <= 3:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    # panels of a sheet are similar in size: every piece 20-60% of the side
    edges = [0] + [r for run in runs for r in (run[0], run[1] + 1)] + [n]
    pieces = [edges[k + 1] - edges[k] for k in range(0, len(edges), 2)]
    if not runs or len(runs) > 3 or any(not (0.2 * n <= p <= 0.6 * n) for p in pieces):
        return []
    return runs


def split_sheet(rel):
    """A character / reference sheet (panels split by white gutters) -> one file per panel.

    Fed whole, Qwen Image treats the sheet as the picture to edit and copies
    its panels and white wall into the result. Each panel on its own is just
    another photo of the same person. Returns [rel] when no gutter is found."""
    src = WORK / rel
    try:
        w, h, raw = _gray_columns(src)
    except Exception:
        return [rel]
    if len(raw) < w * h:
        return [rel]
    step = max(1, h // 256)
    cols = [_stats(raw[x:w * h:w * step]) for x in range(w)]
    xs = _divider_runs(w, cols) or _seam_runs(w, h, raw, True)
    stepx = max(1, w // 256)
    rows = [_stats(raw[y * w:(y + 1) * w:stepx]) for y in range(h)]
    ys = _divider_runs(h, rows) or _seam_runs(w, h, raw, False)
    if not xs and not ys:
        return [rel]
    def cuts(n, runs):
        edges, a = [], 0
        for r0, r1 in runs:
            edges.append((a, r0))
            a = r1 + 1
        edges.append((a, n))
        return [(a, b) for a, b in edges if b - a >= n * 0.15]
    panels = [(x0, y0, x1 - x0, y1 - y0) for y0, y1 in cuts(h, ys) for x0, x1 in cuts(w, xs)]
    if len(panels) < 2:
        return [rel]
    out = []
    stem = rel.rsplit(".", 1)[0]
    for k, (x, y, pw, ph) in enumerate(panels, 1):
        prel = f"{stem}-p{k}.png"
        r = subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(src),
                            "-vf", f"crop={pw}:{ph}:{x}:{y}", str(WORK / prel)], capture_output=True)
        if r.returncode != 0:
            return [rel]
        out.append(prel)
    return out


def _ref_size(rel):
    """The size a reference is encoded at: its own shape, at most ~1 MP, never
    upscaled, both sides multiples of 32 -- Qwen 2.1's vision encoder reads
    32-pixel patches, and vae-encode and the conditioner must see the same size."""
    try:
        pr = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(WORK / rel)],
                            capture_output=True, text=True)
        w, h = map(int, pr.stdout.strip().split(",")[:2])
    except Exception:
        return 1024, 1024
    s = min(1.0, (1048576 / (w * h)) ** 0.5)
    return max(256, int(w * s) // 32 * 32), max(256, int(h * s) // 32 * 32)


QWEN_MAX_REFS = 6   # panels cost prefix tokens (KV-cached); 3 panels ran 7m55s
QWEN_SINGLE_PHOTO = ("生成一張單一的寫實照片：只有一個畫面，不要拼貼、不要分格、不要並排，"
                     "也不要沿用參考圖的白牆背景；場景、動作和鏡頭照上面的描述。")


def expand_qwen_refs(refs, prompt):
    """Split sheets into panels (within Qwen's reference limit) and renumber
    the prompt's Picture N so it still points at the same person."""
    groups = [split_sheet(r) for r in refs]
    if sum(len(g) for g in groups) > 4:
        # several sheets: drop the back views, keep the full-body front (the
        # whole outfit, skirt and shoes included) and the close-up (the face).
        # Keeping only the close-up let the model invent the lower half.
        groups = [[g[0], g[-1]] if len(g) > 2 else g for g in groups]
    if sum(len(g) for g in groups) > QWEN_MAX_REFS:
        groups = [g[:1] for g in groups]   # the full-body front only
    while sum(len(g) for g in groups) > QWEN_MAX_REFS:   # plain photos past the cap
        groups.pop()
    first, n, notes = {}, 1, []
    for i, g in enumerate(groups, 1):
        first[i] = n
        if len(g) > 1:
            names = "、".join(f"Picture {n + k}" for k in range(len(g)))
            notes.append(f"{names} 是同一個人（同一張設定圖的不同角度），臉、髮型和整套服裝（上衣、下身、鞋子）都照這幾張；"
                         f"她在畫面裡只出現一次，不是雙胞胎。({names} show ONE person; she appears only once.)")
        n += len(g)
    if any(len(g) > 1 for g in groups):
        prompt = re.sub(r"(?i)(<?)Picture\s*(\d+)(>?)",
                        lambda m: f"{m.group(1)}Picture {first.get(int(m.group(2)), int(m.group(2)))}{m.group(3)}",
                        prompt)
    text = prompt.rstrip() + "\n" + "\n".join(notes + [QWEN_SINGLE_PHOTO])
    return [p for g in groups for p in g], text


def build_qwen_ref(job_id, refs, w, h, prompt, seed):
    """Qwen Image 2.1 Turbo with 1–3 reference images (R2I / edit)."""
    rw, rh = w, h
    if max(w, h) > 1024:  # references never need more than ~1 MP
        s = 1024 / max(w, h)
        rw, rh = int(w * s) // 16 * 16, int(h * s) // 16 * 16
    out = f"jobs/{job_id}/output.png"
    refs, prompt = expand_qwen_refs(refs, prompt)
    st = [{"id": "model-select", "type": "model-select", "iports": [],
           "config": {"hf_dir": "Qwen/Qwen-Image-2.1-Turbo"}}]
    for i, r in enumerate(refs, 1):
        st.append({"id": f"load-{i}", "type": "load-image", "iports": [],
                   "config": {"url": [r]}})
        st.append({"id": f"resample-{i}", "type": "image-resample",
                   "iports": [{"src": f"load-{i}", "oport": 0}],
                   # keep the reference's own shape (~1 MP); cropping it to the
                   # output aspect cut character sheets into strips that the
                   # model then copied into the result
                   "config": dict(zip(("width", "height"), _ref_size(r)),
                                  fit="crop", algorithm="lanczos")})
    e = {"src": "", "oport": 0}
    st += [
        {"id": "references", "type": "tensor-list", "config": {},
         "iports": [{"src": f"resample-{i}", "oport": 0} for i in range(1, len(refs) + 1)]},
        {"id": "text-prompt", "type": "text-prompt", "iports": [], "config": {"text": prompt}},
        {"id": "qwen-image-21-model-config", "type": "qwen-image-21-model-config",
         "iports": [], "config": {}},
        {"id": "vae-encode", "type": "vae-encode", "config": {},
         "iports": [e, {"src": "model-select", "oport": 0}, {"src": "references", "oport": 0}]},
        {"id": "diffusion-conditioner", "type": "diffusion-conditioner", "config": {},
         "iports": [{"src": "text-prompt", "oport": 0}, e, {"src": "model-select", "oport": 0},
                    e, e, {"src": "qwen-image-21-model-config", "oport": 0},
                    {"src": "references", "oport": 0}]},
        {"id": "generate-image", "type": "generate-image",
         "config": {"width": w, "height": h, "seed": seed},
         "iports": [{"src": "diffusion-conditioner", "oport": 0}, e,
                    {"src": "model-select", "oport": 0}, e, e, e, e,
                    {"src": "qwen-image-21-model-config", "oport": 0},
                    {"src": "vae-encode", "oport": 1}]},
        {"id": "vae-decode", "type": "vae-decode", "config": {},
         "iports": [{"src": "generate-image", "oport": 0}, {"src": "model-select", "oport": 0}]},
        {"id": "save-image", "type": "save-image", "iports": [{"src": "vae-decode", "oport": 0}],
         "config": {"path": out, "format": "png", "compression": 6}},
    ]
    return {"id": f"simple-{job_id}", "stages": st, "subpipelines": []}, out


def build_h3_conditioned(job_id, w, h, seconds, prompt, seed, first=None, last=None, refs=None):
    """H3 with a first and/or last keyframe, or with reference images.

    Keyframes go through vae-encode into generate-video's iport5 (first)
    and iport6 (last). Reference images use the "Ref2VA-like" mode on the
    FL2VA weights: a video-ref-encoder replaces the diffusion-conditioner
    and feeds iport0/7/8. The two modes are mutually exclusive in H3.
    """
    d = load_h3_template()
    frames = h3_frames(seconds)
    out = f"jobs/{job_id}/output.mp4"
    stages = {s["id"]: s for s in d["stages"]}
    gv = stages["generate-video"]
    gv["config"].update(width=w, height=h, frames=frames, seed=seed)
    stages["save-video"]["config"]["output_url"] = out
    e = {"src": "", "oport": 0}
    while len(gv["iports"]) < 10:
        gv["iports"].append(dict(e))
    extra = []
    if refs:
        stages["minimax-h3-model-config"]["config"]["condition_audio_timestep"] = 1.0
        d["stages"] = [s for s in d["stages"] if s["id"] not in ("text-prompt", "diffusion-conditioner")]
        extra.append({"id": "text-prompt", "type": "text-prompt", "iports": [], "config": {"text": prompt}})
        extra.append({"id": "video-ref-encoder", "type": "video-ref-encoder",
                      "iports": [{"src": "text-prompt", "oport": 0}, {"src": "model-select", "oport": 0}],
                      "config": {"references": refs, "frames": frames, "unload_when_idle": "auto"}})
        gv["iports"][0] = {"src": "video-ref-encoder", "oport": 0}
        gv["iports"][7] = {"src": "video-ref-encoder", "oport": 1}
        gv["iports"][8] = {"src": "video-ref-encoder", "oport": 2}
    else:
        stages["text-prompt"]["config"]["text"] = prompt
        for name, path, port in (("first", first, 5), ("last", last, 6)):
            if not path:
                continue
            extra += [
                {"id": f"load-{name}", "type": "load-image", "iports": [], "config": {"url": [path]}},
                {"id": f"{name}-frame", "type": "image-resample", "iports": [{"src": f"load-{name}", "oport": 0}],
                 "config": {"width": w, "height": h, "fit": "crop", "algorithm": "lanczos"}},
                {"id": f"vae-encode-{name}", "type": "vae-encode",
                 "iports": [{"src": f"{name}-frame", "oport": 0}, {"src": "model-select", "oport": 0}],
                 "config": {"unload_when_idle": "always"}},
            ]
            gv["iports"][port] = {"src": f"vae-encode-{name}", "oport": 0}
    # declare after model-select so every stage's inputs are already defined
    i = next(n for n, s in enumerate(d["stages"]) if s["id"] == "model-select") + 1
    d["stages"] = d["stages"][:i] + extra + d["stages"][i:]
    d["id"] = f"simple-{job_id}"
    return d, out


def add_preview(pipe, model, job_id):
    """Wire the live preview: a tiny autoencoder decodes each step's estimate.

    Qwen: generate-image oport2 ([3,H,W] u8) -> save-image, one PNG per step.
    H3:   generate-video oport2 ([F,3,H,W] u8) -> save-tensor (last step wins);
          the server turns that into a looping mp4 with ffmpeg on request.
    """
    cfg_id = "minimax-h3-model-config" if model == "h3" else "qwen-image-21-model-config"
    gen_id = "generate-video" if model == "h3" else "generate-image"
    for s in pipe["stages"]:
        if s["id"] == cfg_id:
            s.setdefault("config", {}).update(
                preview_vae="madebyollin/taeh3" if model == "h3" else "madebyollin/taeqi2_1",
                preview_every=1, preview_max_edge=384 if model == "h3" else 512)
    if model == "h3":
        sink = {"id": "preview-sink", "type": "save-tensor",
                "iports": [{"src": gen_id, "oport": 2}],
                "config": {"path": f"jobs/{job_id}/preview.vpt"}}
    else:
        sink = {"id": "preview-sink", "type": "save-image",
                "iports": [{"src": gen_id, "oport": 2}],
                "config": {"path": f"jobs/{job_id}/preview-%02d.png", "format": "png", "compression": 1}}
    pipe["stages"].append(sink)


_preview_cache = {}


def video_preview(job_id):
    """Convert jobs/<id>/preview.vpt (u8 [F,3,H,W], planar RGB) to preview.mp4."""
    vpt = JOBS / job_id / "preview.vpt"
    mp4 = JOBS / job_id / "preview.mp4"
    if not vpt.exists():
        return None
    st = vpt.stat()
    key = (st.st_mtime_ns, st.st_size)
    if _preview_cache.get(job_id) == key and mp4.exists():
        return _preview_cache[job_id + ":step"]
    raw = vpt.read_bytes()
    if raw[:8] != b"VPTENSOR":
        return None
    dtype, rank = struct.unpack_from("<II", raw, 12)
    count = struct.unpack_from("<Q", raw, 24)[0]
    dims = struct.unpack_from(f"<{rank}q", raw, 32)
    off = 32 + 8 * rank
    if rank != 4 or dims[1] != 3 or len(raw) < off + count:
        return None
    f, _, h, w = dims
    payload = raw[off:off + count]
    side = {}
    try:
        side = json.loads(raw[off + count:].decode() or "{}")
    except ValueError:
        pass
    plane = h * w
    gbrp = bytearray()
    for i in range(f):  # ffmpeg's planar order is G, B, R
        base = i * 3 * plane
        r, g, b = (payload[base + k * plane: base + (k + 1) * plane] for k in range(3))
        gbrp += g + b + r
    fps = side.get("fps") or 24
    tmp = mp4.with_suffix(".tmp.mp4")
    res = subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gbrp",
         "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)],
        input=bytes(gbrp), capture_output=True)
    if res.returncode != 0:
        return None
    tmp.replace(mp4)
    step = side.get("step")
    _preview_cache[job_id] = key
    _preview_cache[job_id + ":step"] = step
    return step


def preview_info(job):
    jid = job["id"]
    if job["model"] == "h3":
        step = video_preview(jid)
        if (JOBS / jid / "preview.mp4").exists():
            m = int((JOBS / jid / "preview.mp4").stat().st_mtime)
            return {"kind": "video", "url": f"/files/jobs/{jid}/preview.mp4?v={m}", "step": step}
        return None
    pngs = sorted((JOBS / jid).glob("preview-*.png"))
    if not pngs:
        return None
    last = pngs[-1]
    return {"kind": "image", "url": f"/files/jobs/{jid}/{last.name}?v={int(last.stat().st_mtime)}",
            "step": len(pngs)}


H3_MODEL = os.environ.get("VPIPE_H3_MODEL") or "local/MiniMax-H3-FL2VA-8bit"
REF2VA_MODEL = os.environ.get("VPIPE_REF2VA_MODEL") or "local/MiniMax-H3-Ref2VA-4bit"
ACCELS = ("turbo", "pika", "none")


def load_h3_template():
    d = json.loads(H3_TEMPLATE.read_text())
    for st_ in d["stages"]:
        if st_["type"] == "model-select":
            st_["config"]["hf_dir"] = H3_MODEL
    return d


def model_avail():
    """Which optional H3 weights are on disk (the page greys out the rest and
    the server refuses a job that needs a missing one)."""
    m = WORK / "models"
    pika = m / "Pika-Labs"
    return {
        "h3": (m / H3_MODEL).is_dir(),
        "qwen": (m / "Qwen" / "Qwen-Image-2.1-Turbo").is_dir(),
        "ltx": (m / LTX_MODEL / "diffusion_models").is_dir() and ltx_plugin() is not None,
        # the folder appears as soon as quantizing starts; the DiT config is written last
        "ref2va": (m / REF2VA_MODEL / "diffusion_models" / "config.json").exists(),
        "turbo": (m / "larryvrh").is_dir(),
        "ref2va_turbo": (m / "lightx2v").is_dir(),
        "pika_fl2va": pika.is_dir() and any(pika.glob("**/fl2va*")),
        "pika_ref2va": pika.is_dir() and any(pika.glob("**/ref2va*")),
    }


def check_weights(accel, engine):
    a = model_avail()
    if engine == "ref2va":
        if not a["ref2va"]:
            raise ValueError("Ref2VA 模型還沒裝好，不能用參考影片／Ref2VA")
        if not a["pika_ref2va"]:
            raise ValueError("Ref2VA 需要 Pika H3 Flex（ref2va）加速，還沒下載")
    elif accel == "pika" and not a["pika_fl2va"]:
        raise ValueError("Pika H3 Flex（fl2va）還沒下載，請改用 Turbo 或不加速")
    elif accel == "turbo" and not a["turbo"]:
        raise ValueError("Turbo LoRA 還沒下載，請改成不加速")
# model registry keys of each speed-up, per H3 partition
ACCEL_LORA = {
    ("turbo", "fl2va"): "larryvrh/MiniMax-H3-Turbo-Lora-v4-600-ema",
    ("pika", "fl2va"): "Pika-Labs/Pika-H3-Flex-fl2va",
    ("pika", "ref2va"): "Pika-Labs/Pika-H3-Flex-ref2va",
}


ANE_ON = os.environ.get("VPIPE_ANE", "1") != "0"


def apply_ane(pipe):
    """Let the Apple Neural Engine take a share of every H3 block (ane_ffn +
    ane_qkv) and of the video decoder's feed-forward. Measured on an M3 Air
    24 GB, 832x480 5 s: 72m37s GPU-only -> 43m27s (1.67x), PSNR 36 dB, no
    visible loss. ane_int8 is left off: on an M3 it was no faster. vpipe
    falls back to the GPU by itself where the plan cannot grant the module."""
    if not ANE_ON:
        return
    for s in pipe["stages"]:
        cfg = s.setdefault("config", {})
        if s["type"] == "generate-video":
            cfg.update(ane_ffn=True, ane_qkv=True)
        elif s["type"] == "vae-decode":
            cfg["ane_ffn"] = True


def apply_accel(pipe, accel, engine, steps):
    """Set the H3 partition and speed-up adapter; returns the steps really run.

    - Turbo on FL2VA: larryvrh v4, the chosen 4/6/8 steps.
    - Turbo on Ref2VA: lightx2v's Ref2VA adapter, 8 steps, video_shift 6.0.
    - Pika H3 Flex: its manifest fixes 6 steps on its own grid (re-noise
      sampler), no condition_timestep; keyframes are also shown to the
      conditioner; references at a 1024 short edge (480p tier).
    - none: base model, the chosen steps (needs 16+ to look clean).
    """
    st = {s["id"]: s for s in pipe["stages"]}
    if accel == "turbo" and engine == "ref2va":
        accel = "pika"   # lightx2v's Ref2VA Turbo was removed 2026-11-05; Pika is the Ref2VA speed-up
    if engine == "ref2va":
        st["model-select"]["config"]["hf_dir"] = REF2VA_MODEL
    mc = st["minimax-h3-model-config"]["config"]
    mc.pop("lora", None)
    mc.pop("lora_scale", None)
    if accel != "none":
        mc["lora"] = ACCEL_LORA[(accel, engine)]
        mc["lora_scale"] = 1.0
    if engine == "ref2va" and "video-ref-encoder" in st:
        # Ref2VA defaults to a 2048 short edge -- the 768p tier. Below 768p the
        # release uses 1024; at 2048 two references cost 8192 rows, more than a
        # draft clip itself (measured: ~9 min per 10% of the denoise on M3).
        gw = st["generate-video"]["config"]
        tier_768 = min(gw.get("width", 0), gw.get("height", 0)) >= 768
        st["video-ref-encoder"]["config"]["reference_image_short_edge"] = 2048 if tier_768 else 1024
    if accel == "pika":
        mc.pop("condition_timestep", None)
        steps = 6
        if "video-ref-encoder" in st:
            st["video-ref-encoder"]["config"]["reference_image_short_edge"] = 1024
        dc = st.get("diffusion-conditioner")
        if dc is not None and "first-frame" in st:
            while len(dc["iports"]) < 4:
                dc["iports"].append({"src": "", "oport": 0})
            dc["iports"][3] = {"src": "first-frame", "oport": 0}
    st["generate-video"]["config"]["steps"] = steps
    return steps


def _image_ext(raw):
    """'.png' / '.jpg' / '.webp' from the bytes themselves, or a refusal: vpipe
    carries on WITHOUT a picture it cannot read, so a bad upload must stop here."""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if raw[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("這不是可用的圖片（只收 PNG、JPG、WebP）")


def save_image(job_id, name, data_url):
    raw = base64.b64decode(data_url.partition(",")[2])
    rel = f"jobs/{job_id}/{name}{_image_ext(raw)}"
    (WORK / rel).write_bytes(raw)
    return rel


def save_refs(job_id, images):
    """Write uploaded data-URL images into the job dir; return relative paths."""
    paths = []
    for i, data_url in enumerate(images[:9], 1):   # H3 reads at most 9 pictures
        raw = base64.b64decode(data_url.partition(",")[2])
        rel = f"jobs/{job_id}/ref{i}{_image_ext(raw)}"
        (WORK / rel).write_bytes(raw)
        paths.append(rel)
    return paths


def save_ref_video(job_id, data_url, start, w, h, frames, keep_audio):
    """A motion reference clip for Ref2VA: cut to the generated length, cropped
    to the output's own size at 24 fps, so it costs about as many rows as the
    clip being made (reference_video_short_edge 0 keeps it at that size)."""
    head, _, b64 = data_url.partition(",")
    ext = ".mov" if "quicktime" in head else ".webm" if "webm" in head else ".mp4"
    src = WORK / f"jobs/{job_id}/refvideo-src{ext}"
    src.write_bytes(base64.b64decode(b64))
    rel = f"jobs/{job_id}/refvideo.mp4"
    cmd = [FFMPEG, "-v", "error", "-y", "-ss", f"{max(0.0, start):.2f}", "-i", str(src),
           "-frames:v", str(frames), "-t", f"{frames / 24 + 0.05:.2f}",
           "-vf", f"fps=24,scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16"]
    cmd += ["-c:a", "aac", "-ar", "48000"] if keep_audio else ["-an"]
    r = subprocess.run(cmd + [str(WORK / rel)], capture_output=True, text=True)
    if r.returncode != 0 or not (WORK / rel).exists():
        raise ValueError("參考影片讀不到或剪不了：" + (r.stderr or "").strip()[-200:])
    got = subprocess.run([FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(WORK / rel)],
                         capture_output=True, text=True).stdout.strip()
    if got.isdigit() and int(got) < 48:
        raise ValueError("參考影片從開始秒數算起太短了，至少要 2 秒")
    return rel


def build_ltx(job_id, w, h, seconds, prompt, seed, first=None, audio=True):
    """LTX-2.5 text-to-video, or image-to-video when a first frame is given
    (the vpipe-ltx-2.5 plugin's graphs, merged). 8 steps are the checkpoint's."""
    d = json.loads(LTX_TEMPLATE.read_text())
    out = f"jobs/{job_id}/output.mp4"
    mdir = f"./models/{LTX_MODEL}"
    for s in d["stages"]:
        c = s.setdefault("config", {})
        if s["id"] == "model-select":
            c["hf_dir"] = mdir
        elif s["id"] == "text-prompt":
            c["text"] = prompt
        elif s["id"] == "gen":
            c.update(width=w, height=h, frames=ltx_frames(seconds), seed=seed)
        elif s["id"] == "save":
            c.update(output_url=out, enable_audio=bool(audio))
    if first:
        d["stages"][1:1] = [
            {"id": "load-image", "type": "load-image", "iports": [], "config": {"url": "./" + first}},
            {"id": "vae-encode", "type": "vae-encode", "iports": [{"src": "load-image", "oport": 0}],
             "config": {"hf_dir": mdir, "target_width": w, "target_height": h, "unload_when_idle": "always"}}]
        for s in d["stages"]:
            if s["id"] == "gen":
                s["iports"][5] = {"src": "vae-encode", "oport": 0}   # ref_latent0: the clip starts AT it
            elif s["id"] == "ltx-config":
                s["config"]["ref_strength"] = 1.0
    d["id"] = f"simple-{job_id}"
    return d, out


def build_pipeline(job_id, model, w, h, seconds, prompt, seed):
    if model == "h3":
        d = load_h3_template()
        frames = h3_frames(seconds)
        out = f"jobs/{job_id}/output.mp4"
        for s in d["stages"]:
            c = s.setdefault("config", {})
            if s["id"] == "text-prompt":
                c["text"] = prompt
            elif s["id"] == "generate-video":
                c.update(width=w, height=h, frames=frames, seed=seed)
            elif s["id"] == "save-video":
                c["output_url"] = out
    else:
        d = json.loads(QWEN_TEMPLATE.read_text())
        out = f"jobs/{job_id}/output.png"
        for s in d["stages"]:
            c = s.setdefault("config", {})
            if s["id"] == "text-prompt":
                c["text"] = prompt
            elif s["id"] == "generate-image":
                c.update(width=w, height=h, seed=seed)
            elif s["id"] == "save-image":
                c["path"] = out
    d["id"] = f"simple-{job_id}"
    return d, out


PROG_RE = re.compile(r"\[PROGRESS\] (\d+)% of '([^']+)'")


def read_status(job):
    """Fill progress fields from the job's log."""
    log = JOBS / job["id"] / "run.log"
    stage, pct, tail = "準備中（載入模型）", 0, []
    if log.exists():
        lines = log.read_text(errors="replace").splitlines()
        tail = lines[-6:]
        for line in reversed(lines):
            m = PROG_RE.search(line)
            if m and not m.group(2).startswith("download"):
                pct, stage = int(m.group(1)), m.group(2)
                break
        names = {"denoise": "生成中（去噪）", "vae decode": "解碼畫面"}
        stage = names.get(stage, stage)
    job = dict(job)
    job.update(stage=stage, percent=pct, log_tail=tail)
    if job["state"] == "running":
        job["elapsed_s"] = int(time.time() - job["started"])
    return job


def save_job(job):
    (JOBS / job["id"] / "job.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=2))


def run_job(job, pipeline_path):
    try:
        _run_one(job, pipeline_path)
    finally:
        with lock:
            current["proc"] = None
            current["running"] = False
        kick()


def kick():
    """Start the next queued job if nothing is running."""
    with lock:
        if current["running"] or not queue:
            return
        job, path = queue.pop(0)
        job["state"] = "running"
        job["started"] = time.time()
        save_job(job)
        current["job"] = job
        current["running"] = True
    threading.Thread(target=run_job, args=(job, path), daemon=True).start()


def _run_one(job, pipeline_path):
    try:
        with open(JOBS / job["id"] / "run.log", "w") as log:
            cmd = [vpipe_bin(), "--launch", str(pipeline_path)]
            if job.get("model") == "ltx":
                plug = ltx_plugin()
                if not plug:
                    raise RuntimeError("找不到 vpipe-ltx-2.5 外掛（可用 VPIPE_LTX_PLUGIN 指定）")
                cmd[1:1] = ["--plugin", plug]
            proc = subprocess.Popen(
                cmd,
                cwd=WORK, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True)
            with lock:
                current["proc"] = proc
                job["pid"] = proc.pid       # so a restarted server can clean it up
                stop_now = job.get("state") == "stopped"   # Stop pressed before Popen returned
                save_job(job)
            if stop_now:
                _terminate(proc)
            rc = proc.wait()
    except Exception as e:   # vpipe missing, can't write the log, ...
        with lock:
            job.update(state="failed", error=f"無法啟動 vpipe：{e}", finished=time.time())
            save_job(job)
        return
    with lock:
        job["finished"] = time.time()
        job["elapsed_s"] = int(job["finished"] - job["started"])
        job.pop("pid", None)
        out = WORK / job["output"]
        if rc == 0 and out.exists():
            job["state"] = "done"      # finished before a late Stop landed
        elif job.get("state") == "stopped":
            pass
        else:
            job["state"] = "failed"
            job["error"] = f"vpipe 結束碼 {rc}"
        save_job(job)


def start_job(body):
    if setup_task["proc"] is not None:
        raise ValueError("正在安裝模型，裝好後再生成")
    model = body.get("model")
    if model not in SIZES:
        raise ValueError("未知的模型")
    size_key = body.get("size")
    if size_key not in SIZES[model]:
        raise ValueError("未知的大小")
    w, h = SIZES[model][size_key]
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("請寫 prompt")
    seconds = float(body.get("seconds") or 3) if model in VIDEO_MODELS else 0
    if model in VIDEO_MODELS and not (1 <= seconds <= 10):
        raise ValueError("秒數要在 1–10 之間")
    seed = body.get("seed")
    seed = int(seed) if seed not in (None, "") else int(time.time()) % 100000   # 0 is a real seed
    with lock:   # only to reserve the folder; the slow work below runs unlocked
        job_id = time.strftime("%Y%m%d-%H%M%S")
        n = 2
        while (JOBS / job_id).exists():
            job_id = time.strftime("%Y%m%d-%H%M%S") + f"-{n}"
            n += 1
        (JOBS / job_id).mkdir(parents=True, exist_ok=True)
    try:
        job, pipe_path = _prepare_job(job_id, body, model, size_key, w, h, prompt, seconds, seed)
    except BaseException:
        shutil.rmtree(JOBS / job_id, ignore_errors=True)   # no half-made job folders
        raise
    with lock:
        save_job(job)
        queue.append((job, pipe_path))
    kick()
    return job


def _prepare_job(job_id, body, model, size_key, w, h, prompt, seconds, seed):
    """Save the uploads and write the pipeline for one job (no lock held)."""
    images = body.get("images") or []
    first = last = None
    if model == "ltx":
        if images or body.get("last") or body.get("video"):
            raise ValueError("LTX 目前只支援純文字或首幀（不支援尾幀、參考圖、參考影片）")
        if not model_avail()["ltx"]:
            raise ValueError("LTX-2.5 模型或外掛還沒裝好")
    if model in VIDEO_MODELS and body.get("first"):
        first = save_image(job_id, "first", body["first"])
    if model == "h3" and body.get("last"):
        last = save_image(job_id, "last", body["last"])
    if (first or last) and images:
        raise ValueError("H3 的首/尾幀和參考圖不能同時用，請擇一")
    refs = save_refs(job_id, images) if images else []
    ref_video = None
    if model == "h3" and body.get("video"):
        if first or last:
            raise ValueError("參考影片不能和首/尾幀同時用")
        ref_video = save_ref_video(job_id, body["video"], float(body.get("video_start") or 0), w, h,
                                   h3_frames(seconds), bool(body.get("video_audio")))
        refs = refs + [ref_video]
        body["engine"] = "ref2va"   # clips are a trained input only on the Ref2VA partition
    if model == "ltx":
        pipe, out = build_ltx(job_id, w, h, seconds, prompt, seed, first,
                              body.get("audio", True) is not False)
    elif model == "qwen" and refs:
        pipe, out = build_qwen_ref(job_id, refs, w, h, prompt, seed)
    elif model == "h3" and (refs or first or last):
        pipe, out = build_h3_conditioned(job_id, w, h, seconds, prompt, seed, first, last, refs)
    else:
        pipe, out = build_pipeline(job_id, model, w, h, seconds, prompt, seed)
    steps, turbo, accel, engine = 8, True, "turbo", "fl2va"
    if model == "h3":
        steps = int(body.get("steps") or 6)
        if steps not in (4, 6, 8):
            raise ValueError("步數只能是 4、6 或 8")
        accel = body.get("accel") or ("turbo" if body.get("turbo", True) is not False else "none")
        if accel not in ACCELS:
            raise ValueError("未知的加速方式")
        engine = "ref2va" if (refs and body.get("engine") == "ref2va") else "fl2va"
        check_weights("pika" if engine == "ref2va" else accel, engine)
        steps = apply_accel(pipe, accel, engine, steps)
        apply_ane(pipe)
        if ref_video:
            for st_ in pipe["stages"]:
                if st_["id"] == "video-ref-encoder":
                    st_["config"]["reference_video_short_edge"] = 0
        turbo = accel != "none"
    if body.get("preview", True) and model != "ltx":   # no live preview for LTX yet
        add_preview(pipe, model, job_id)
    audio = model in VIDEO_MODELS and body.get("audio", True) is not False
    if model == "h3" and not audio:
        for s in pipe["stages"]:
            if s["id"] == "save-video":
                s["config"]["enable_audio"] = False
    pipe_path = JOBS / job_id / "pipeline.vpipeline"
    pipe_path.write_text(json.dumps(pipe, ensure_ascii=False, indent=2))
    job = {"id": job_id, "model": model, "size": size_key,
           "width": w, "height": h, "seconds": seconds, "seed": seed,
           "prompt": prompt, "output": out, "state": "queued",
           "queued_at": time.time(), "draft": bool(body.get("draft")), "refs": refs, "first": first, "last": last,
           "audio": audio, "bgm": bool(body.get("bgm")),
           "steps": steps, "turbo": turbo if model != "ltx" else None, "accel": accel if model == "h3" else None,
           "ane": ANE_ON if model == "h3" else None,
           "engine": engine if model == "h3" and refs else None,
           "ref_video": ref_video,
           **estimate(model, w, h, seconds, steps)}
    if model == "h3" and refs:  # 768-short-edge references, re-read every step
        job["tokens"] += (len(refs) - (1 if ref_video else 0)) * 900
        if ref_video:   # a clip at the output's size costs about the output's own rows
            job["tokens"] += (2 + 5 * ((h3_frames(seconds) - 5) // 17)) * (h // 32) * (w // 32)
        c, p = calibration("h3")
        job["eta_s"] = int(c * job["tokens"] ** p * _step_factor(steps))
    if model == "qwen" and refs:  # each reference adds its own tokens to the prefix
        n_refs = sum(1 for st_ in pipe["stages"] if st_["id"].startswith("load-"))  # sheets split into panels
        job["tokens"] += n_refs * 2400   # each reference / panel ~0.6–1 MP of prefix
        # the reference prefix is KV-cached, so it costs little per step:
        # measured 271 s with one 1024² reference vs 232 s without
        # measured 11-07: 3 sheet panels 7m55s vs ~3m50s with no reference
        job["eta_s"] = int(job["eta_s"] * (1 + 0.35 * n_refs))
    return job, pipe_path


def cancel_job(job_id):
    """Remove a job that is still waiting in the queue."""
    with lock:
        for i, (job, _) in enumerate(queue):
            if job["id"] == job_id:
                queue.pop(i)
                job["state"] = "cancelled"
                save_job(job)
                return True
    return False


def delete_job(job_id):
    """Move a finished job's folder to the macOS Trash (recoverable until emptied)."""
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}(-[0-9]+)?", job_id or ""):
        raise ValueError("任務編號不對")
    with lock:
        if current["running"] and current["job"] and current["job"]["id"] == job_id:
            raise ValueError("這個任務正在生成，請先停止")
        if any(j["id"] == job_id for j, _ in queue):
            raise ValueError("這個任務還在排隊，請用排隊區的「取消」")
    src = JOBS / job_id
    if not src.is_dir():
        return False
    to_trash(src, f"vpipe-job-{job_id}")
    return True


LIB = WORK / "library"
LIB_CATS = ("person", "scene", "object")


def _lib_index():
    f = LIB / "library.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except ValueError:
            pass
    return []


def _lib_save(items):
    LIB.mkdir(parents=True, exist_ok=True)
    tmp = LIB / "library.json.tmp"
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    tmp.replace(LIB / "library.json")


def library_add(body):
    """Save a picture into the reference library under person / scene / object.

    The picture comes from a finished job's image output ({job_id}) or as a
    data URL ({image}, e.g. a frame grabbed from a video in the browser).
    """
    cat = body.get("category")
    if cat not in LIB_CATS:
        raise ValueError("分類只能是人物、場景或物品")
    name = (body.get("name") or "").strip()[:40] or "未命名"
    item_id = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}-{os.urandom(2).hex()}"
    (LIB / cat).mkdir(parents=True, exist_ok=True)
    if body.get("job_id"):
        jid = body["job_id"]
        if not re.fullmatch(r"[0-9]{8}-[0-9]{6}(-[0-9]+)?", jid):
            raise ValueError("任務編號不對")
        src = JOBS / jid / "output.png"
        if not src.exists():
            raise ValueError("這筆紀錄沒有圖片可以存")
        rel = f"library/{cat}/{item_id}.png"
        (WORK / rel).write_bytes(src.read_bytes())
    elif body.get("image"):
        head, _, b64 = body["image"].partition(",")
        ext = ".png" if "png" in head else ".jpg"
        rel = f"library/{cat}/{item_id}{ext}"
        (WORK / rel).write_bytes(base64.b64decode(b64))
    else:
        raise ValueError("沒有圖片")
    with lock:
        items = _lib_index()
        item = {"id": item_id, "category": cat, "name": name, "file": rel,
                "from_job": body.get("job_id") or body.get("from_job"), "created": time.time()}
        items.append(item)
        _lib_save(items)
    return item


def library_update(body, action):
    iid = body.get("id", "")
    with lock:
        items = _lib_index()
        hit = next((x for x in items if x["id"] == iid), None)
        if hit is None:
            raise ValueError("找不到這張參考圖")
        if action == "rename":
            hit["name"] = (body.get("name") or "").strip()[:40] or hit["name"]
        elif action == "move":
            cat = body.get("category")
            if cat not in LIB_CATS:
                raise ValueError("分類只能是人物、場景或物品")
            old = WORK / hit["file"]
            new_rel = f"library/{cat}/{old.name}"
            (LIB / cat).mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(WORK / new_rel))
            hit["file"], hit["category"] = new_rel, cat
        elif action == "delete":
            f = WORK / hit["file"]
            if f.exists():
                to_trash(f, f"vpipe-ref-{hit['category']}-{f.name}")
            items = [x for x in items if x["id"] != iid]
        _lib_save(items)
    return {"ok": True}


def queue_summary():
    with lock:
        return [{"id": j["id"], "model": j["model"], "width": j["width"], "height": j["height"],
                 "real_seconds": j.get("real_seconds"), "steps": j.get("steps"),
                 "eta_s": j.get("eta_s"), "prompt": j["prompt"][:80], "draft": j.get("draft")}
                for j, _ in queue]


def _terminate(proc, grace=10):
    """SIGTERM vpipe's process group, then SIGKILL if it is still there.

    vpipe only notices SIGTERM between stages (loading weights, VAE decode and
    teardown can take minutes), so a polite stop alone could leave it running."""
    def kill(sig):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
    kill(signal.SIGTERM)

    def later():
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            kill(signal.SIGKILL)
    threading.Thread(target=later, daemon=True).start()


def stop_job():
    with lock:
        proc, job = current["proc"], current["job"]
        if not current["running"] or job is None:
            return False
        job["state"] = "stopped"
        save_job(job)
        if proc is not None and proc.poll() is None:
            _terminate(proc)
        return True   # with no proc yet, _run_one sees "stopped" and kills it at once


def list_jobs(limit=30):
    out = []
    if JOBS.exists():
        for d in sorted(JOBS.iterdir(), reverse=True):
            f = d / "job.json"
            if f.exists():
                try:
                    out.append(json.loads(f.read_text()))
                except ValueError:
                    pass
    return out if limit is None else out[:limit]


# ---- ✨ AI helper: rewrite a rough idea into H3's dialect ---------------------
# Uses the Codex CLI (signed in with a ChatGPT account): $CODEX_BIN, `codex` on
# PATH, or the copy inside the ChatGPT app. Read-only sandbox, nothing is saved
# between calls.
import tempfile
CODEX = Path(next((p for p in (os.environ.get("CODEX_BIN"), shutil.which("codex"),
                               "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex")
                   if p and Path(p).exists()), "/nonexistent/codex"))
ASSIST_RULES = """You turn a rough video idea (often written in Chinese) into a prompt for MiniMax H3,
a local text/reference-to-video model that renders picture and sound together.
Return JSON matching the schema. Rules learned from many test renders:

PROMPT (field "prompt") - English only, no Chinese characters at all:
1. One plain paragraph of what is visible: place, light, who is in frame, what they wear, where they stand.
   People from reference pictures are named exactly with the role names given (e.g. "the person", "person 2");
   describe their outfit and hair from the pictures in a few words so they stay consistent.
   Every other person in the story has no picture: give them a short, concrete, original description
   (age 20+, build, hair, clothes) and a plain name like "the gym guy".
2. Camera framing comes right after the place, because without it H3 picks a wide shot and faces turn to mush.
   Vertical 9:16: "medium close-up two-shot, both people framed from the waist up, faces large and clearly visible".
   Keep at most two people clearly in frame; background people stay soft and out of focus.
   Say the camera is steady (or one slow simple move).
   Think about where people face and put the camera on THAT side so faces are seen: people queuing or ordering
   face the counter, so the camera stands behind the counter at the staff's position looking out at them; people
   watching a stage or screen face it, so the camera is near it. Say it plainly ("seen from behind the counter,
   both customers face the counter and the camera"). The other person in a conversation speaks over the
   shoulder or turns their head halfway, so both faces stay visible.
3. Then "Timeline:" with beats like "[0s-1.5s] ...", covering the whole length, describing who acts,
   who turns to whom, facial expression, small gestures, and who is speaking in each beat
   (e.g. "the gym guy speaks, smiling confidently; the person listens"). Stage directions from the draft
   (pauses, hesitation, looks) go into the beats.
4. Positive wording only: describe what is there, never "no / not / without". Static props stay still - say so.
5. Do NOT write the dialogue text inside the prompt and do not mention subtitles; the page adds the lines.
6. Around 700-1400 characters. Keep it tasteful; all people are adults.

DIALOGUE (field "dialogue"): one item per spoken line, in order.
- speaker: the same name used in the prompt ("the gym guy", "the person").
- lang: "English", "Malay" or "Chinese" - the language actually spoken.
- text: what is said, 4-12 words, natural speech. No speaker name, no brackets, no stage directions in it.
- If the user chose a Malaysian accent style, translate Chinese lines into casual Malaysian English
  (keep particles like lah / leh / lor / meh / ah, and words like "ah moi", "boss", "can or not") unless
  the user's mix option asks to keep some lines in Chinese or Malay.
- Keep the meaning and the joke of the user's lines.
- If the user typed no dialogue but the story has people talking (a chat, a pick-up line, an argument, a greeting),
  write the lines yourself: short, natural, in the chosen language style, fitting the characters and the joke.
  Leave dialogue empty only when the story is clearly silent (or sound is off).

SECONDS (field "seconds"): YOU choose it; the user's current setting is only a hint. Integer 2-10 =
time to speak all lines at a relaxed pace (about 2.5 words per second, plus any pause in the draft)
+ about 1 second for reactions so the last word is not cut. Never shorter than that, even if the user set less;
never much longer, because every extra second is far slower to render on this laptop.

NOTES (field "notes_zh"): 2-4 short sentences in Traditional Chinese for the user: what you changed and why,
and anything they should check (e.g. a second person has no reference picture so his face is invented).
"""
IMAGE_ASSIST_RULES = """You turn a rough picture idea (often written in Chinese) into a prompt for
Qwen Image 2.1 Turbo, a photo model that runs on the user's laptop. Reply with JSON only.

PROMPT (field "prompt"), written in English:
1. One single photograph. Say so near the start ("A single realistic photo, one frame"). If a reference
   picture is a character / lookbook sheet with several panels, the result is ONE shot of that person in
   the new scene, never a sheet, collage, split screen or side-by-side panels, and not on the sheet's
   plain studio wall.
2. People with a reference picture: call them by the picture label exactly as the user does
   ("the woman from Picture 1"), and keep the labels' numbers unchanged. Describe their face-defining
   look, hair and their WHOLE outfit from head to toe as the picture shows it - top, bottom (skirt /
   shorts / trousers, with length and material), legwear and shoes, plus signature accessories - unless
   the user asks for a new outfit. Leaving the lower half out makes the model invent one (a leather mini
   skirt turned into trousers). People without a picture get a short, concrete, original description
   (age 20+).
3. Then the place, specific and real (landmark, street, time of day, weather), what they are doing,
   pose, expression and what they hold. Keep every detail the user asked for.
4. Camera: framing (close-up / waist-up / full-body), angle, lens feel, depth of field, where the light
   comes from. Faces large enough to read; a landmark in the background stays recognisable.
5. Extra people (a crowd, passers-by, people following): at most two or three, clearly separated from
   the main people with open space between them, smaller and softly out of focus further back, never
   overlapping or touching the main people. Dress them in light or mid tones that differ from the main
   people's clothes, so dark clothes and dark hair do not merge into one black mass. Give the main
   people a clean, lighter background behind them.
6. Style: realistic photography, natural skin, sharp focus, plus the mood the idea implies.
7. Describe what is there in positive words. Around 600-1100 characters. Tasteful; all people are adults.
8. Fit the frame the user picked (square / vertical / horizontal) in the composition. Full-body framing
   needs enough room for heads and shoes; two people side by side fit a square only at full-body width.

NOTES (field "notes_zh"): 1-3 short sentences in Traditional Chinese for the user: what you added and
anything to check.
"""
IMAGE_ASSIST_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["prompt", "notes_zh"],
    "properties": {"prompt": {"type": "string"}, "notes_zh": {"type": "string"}},
}

ASSIST_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["prompt", "dialogue", "seconds", "notes_zh"],
    "properties": {
        "prompt": {"type": "string"},
        "dialogue": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["speaker", "lang", "text"],
            "properties": {"speaker": {"type": "string"},
                           "lang": {"type": "string", "enum": ["English", "Malay", "Chinese", "Japanese"]},
                           "text": {"type": "string"}}}},
        "seconds": {"type": "integer"},
        "notes_zh": {"type": "string"},
    },
}
LANG_STYLE = {
    "Chinese": "Mandarin Chinese", "English": "English", "Malay": "Malaysian Malay",
    "Manglish": "English with a strong local Malaysian accent (translate Chinese lines into casual Malaysian English)",
    "MYmix": "a Malaysian mix: each line keeps the language it was written in (Chinese stays Malaysian Mandarin, Malay stays Malay, English stays Malaysian-accented English)",
    "Japanese": "Japanese",
}


def assist(body):
    if not CODEX.exists():
        raise ValueError("找不到 ChatGPT 的 Codex（要先裝 ChatGPT app 並登入）")
    idea = (body.get("prompt") or "").strip()
    dlg = (body.get("dialogue") or "").strip()
    if not idea and not dlg:
        raise ValueError("先在 Prompt 或台詞寫一點想法")
    roles = body.get("roles") or []
    with tempfile.TemporaryDirectory(prefix="vpipe-assist-") as tmp:
        tmp = Path(tmp)
        imgs = []
        for i, d in enumerate((body.get("images") or [])[:6]):
            if not isinstance(d, str) or "," not in d:
                continue
            f = tmp / f"picture{i + 1}.jpg"
            f.write_bytes(base64.b64decode(d.split(",", 1)[1]))
            imgs.append(str(f))
        image_mode = body.get("mode") == "image"
        (tmp / "schema.json").write_text(json.dumps(IMAGE_ASSIST_SCHEMA if image_mode else ASSIST_SCHEMA))
        if image_mode:
            lines = [IMAGE_ASSIST_RULES, "", "USER'S DRAFT", f"Idea: {idea}",
                     f"Frame: {body.get('size') or '1:1'}",
                     (f"Reference pictures attached, in order: Picture 1 to Picture {len(imgs)}."
                      if imgs else "No reference pictures: describe every person in words.")]
        else:
            lines = [ASSIST_RULES, "", "USER'S DRAFT", f"Idea / scene: {idea or '(none)'}",
                     f"Dialogue lines as typed (speaker: line):\n{dlg or '(none)'}",
                     f"Spoken language style chosen: {LANG_STYLE.get(body.get('lang'), body.get('lang') or 'Chinese')}",
                     f"Frame: {body.get('size') or '9:16'} ({'vertical' if '9:16' in str(body.get('size')) else 'as given'})",
                     f"Length they set: {body.get('seconds')} s",
                     f"Sound: {'OFF (silent video, no dialogue)' if body.get('audio') is False else 'background music too' if body.get('bgm') else 'ambient sound and dialogue only'}"]
            if roles:
                lines.append("Reference pictures attached, in order: " +
                             "; ".join(f"Picture {i + 1} = {r}" for i, r in enumerate(roles)))
            else:
                lines.append("No reference pictures: describe every person in words.")
        if body.get("ui_lang") == "en":
            lines.append("The user reads English: write notes_zh in English, not Chinese.")
        cmd = [str(CODEX), "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
               "-C", str(tmp), "-c", 'model_reasoning_effort="low"',
               "--output-schema", str(tmp / "schema.json"), "-o", str(tmp / "out.json")]
        for f in imgs:
            cmd += ["-i", f]
        cmd += ["--", "\n".join(lines)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=240, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise ValueError("AI 幫手超過 4 分鐘沒回應，請再試一次")
        out = tmp / "out.json"
        if not out.exists():
            tail = (r.stderr or r.stdout or "").strip()[-300:]
            raise ValueError("AI 幫手失敗：" + (tail or f"exit {r.returncode}"))
        txt = out.read_text()
        m = re.search(r"\{[\s\S]*\}", txt)
        try:
            ans = json.loads(m.group(0) if m else txt)
        except Exception:
            raise ValueError("AI 幫手回的格式看不懂，請再試一次")
    if not image_mode:
        ans["seconds"] = max(1, min(10, int(ans.get("seconds") or 3)))
    return ans


# ---- First-run setup: what is installed, and one-click model downloads -------
VPIPE_RELEASES = "https://github.com/tgo-app-dev/vpipe/releases/latest"
SETUP_MODELS = {
    # id: (install pipeline, peak disk GB, final GB, required-for)
    "qwen":     ("prepare-qwen-image-2.1-turbo.vpipeline", 34, 33, "Qwen 圖片"),
    "h3":       ("prepare-minimax-h3-8bit.vpipeline", 185, 66, "H3 影片"),
    "turbo":    ("prepare-minimax-h3-turbo-lora.vpipeline", 2, 1, "H3 Turbo 加速"),
    "previews": ("prepare-previews.vpipeline", 1, 0.1, "生成中的預覽"),
}
setup_task = {"id": None, "proc": None, "started": None, "error": None, "done": []}


def _codex_logged_in():
    if not CODEX.exists():
        return False
    try:
        r = subprocess.run([str(CODEX), "login", "status"], capture_output=True, text=True,
                           timeout=15, stdin=subprocess.DEVNULL)
        return r.returncode == 0 and "logged in" in (r.stdout + r.stderr).lower()
    except Exception:
        return False


def setup_status():
    a = model_avail()
    try:
        vbin = vpipe_bin()
    except RuntimeError:
        vbin = None
    st = shutil.disk_usage(WORK if WORK.exists() else Path.home())
    with lock:
        t = dict(setup_task)
    t.pop("proc", None)
    if t["id"]:
        t["percent"], t["stage"] = _setup_progress(t["id"])
    previews = (WORK / "models" / "madebyollin" / "taeqi2_1").is_dir() and \
               (WORK / "models" / "madebyollin" / "taehv").is_dir()
    items = [
        {"id": "vpipe", "ok": bool(vbin), "path": vbin, "required": True, "action": "link",
         "url": VPIPE_RELEASES},
        {"id": "ffmpeg", "ok": Path(FFMPEG).exists() and Path(FFPROBE).exists(), "path": FFMPEG,
         "required": True, "action": "command", "command": "brew install ffmpeg"},
        {"id": "qwen", "ok": a["qwen"], "required": False, "action": "install",
         "need_gb": SETUP_MODELS["qwen"][1], "final_gb": SETUP_MODELS["qwen"][2]},
        {"id": "h3", "ok": a["h3"], "required": False, "action": "install",
         "need_gb": SETUP_MODELS["h3"][1], "final_gb": SETUP_MODELS["h3"][2]},
        {"id": "turbo", "ok": a["turbo"], "required": False, "action": "install",
         "need_gb": SETUP_MODELS["turbo"][1], "final_gb": SETUP_MODELS["turbo"][2]},
        {"id": "previews", "ok": previews, "required": False, "action": "install",
         "need_gb": SETUP_MODELS["previews"][1], "final_gb": SETUP_MODELS["previews"][2]},
        {"id": "codex", "ok": CODEX.exists(), "path": str(CODEX) if CODEX.exists() else None,
         "required": False, "action": "command", "command": "brew install --cask codex",
         "alt_command": "npm install -g @openai/codex"},
        {"id": "codex_login", "ok": _codex_logged_in(), "required": False, "action": "login",
         "blocked": not CODEX.exists()},
    ]
    ready = items[0]["ok"] and items[1]["ok"] and (a["qwen"] or a["h3"])
    return {"items": items, "ready": ready, "work": str(WORK), "free_gb": round(st.free / 1e9),
            "task": t}


def _setup_log(sid):
    return WORK / "setup" / f"{sid}.log"


def _setup_progress(sid):
    try:
        tail = _setup_log(sid).read_text(errors="replace").splitlines()[-40:]
    except OSError:
        return 0, ""
    pct, stage = 0, ""
    for line in tail:
        m = re.search(r"\[PROGRESS\]\s+(\d+)% of '([^']+)'", line)
        if m:
            pct, stage = int(m.group(1)), m.group(2)
    return pct, stage


def setup_install(sid):
    if sid not in SETUP_MODELS:
        raise ValueError("未知的安裝項目")
    pipe, need_gb, _, _ = SETUP_MODELS[sid]
    try:
        vbin = vpipe_bin()
    except RuntimeError as e:
        raise ValueError(str(e))
    WORK.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(WORK).free / 1e9
    if free < need_gb:
        raise ValueError(f"磁碟空間不夠：需要約 {need_gb} GB，目前只剩 {free:.0f} GB")
    with lock:
        if setup_task["proc"] is not None:
            raise ValueError("已經在安裝別的項目，請等它完成")
        if current["running"] or queue:
            raise ValueError("正在生成或排隊中，等任務完成後再安裝")
        (WORK / "setup").mkdir(exist_ok=True)
        log = open(_setup_log(sid), "w")
        proc = subprocess.Popen([vbin, "--launch", str(HERE / "templates" / pipe)], cwd=WORK,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        setup_task.update(id=sid, proc=proc, started=time.time(), error=None)

    def wait():
        rc = proc.wait()
        log.close()
        with lock:
            setup_task["proc"] = None
            if rc == 0 and setup_task.get("id") == sid:
                setup_task["done"] = setup_task["done"] + [sid]
                setup_task["id"] = None
            elif setup_task.get("id") == sid:
                setup_task["error"] = "stopped" if setup_task.get("stopping") else f"vpipe 結束碼 {rc}"
            setup_task.pop("stopping", None)
    threading.Thread(target=wait, daemon=True).start()
    return {"started": sid}


def setup_stop():
    with lock:
        proc = setup_task["proc"]
        if proc is None:
            return False
        setup_task["stopping"] = True
    _terminate(proc)
    return True


def setup_codex_login():
    """Run `codex login`: it opens the browser for the ChatGPT sign-in and
    finishes by itself; the page polls setup_status for the result."""
    if not CODEX.exists():
        raise ValueError("先安裝 Codex CLI")
    subprocess.Popen([str(CODEX), "login"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return {"started": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path, ctype):
        """Serve a file, honouring a single byte Range (Safari will not play
        a <video> without it); streamed in chunks, never read whole."""
        size = path.stat().st_size
        start, end = 0, size - 1
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if m and size and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:   # the last N bytes
                start = max(0, size - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def _host_ok(self):
        """Only this machine's own page may talk to the server: a wrong Host
        means DNS rebinding, a foreign Origin means another website."""
        host = (self.headers.get("Host") or "").lower()
        if host not in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"):
            return False
        origin = self.headers.get("Origin")
        return origin in (None, f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}")

    def do_GET(self):
        if not self._host_ok():
            return self.send_error(403)
        try:
            return self._get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _get(self):
        p = unquote(self.path.split("?")[0])
        if p in ("/", "/index.html"):
            return self._file(HERE / "index.html", "text/html; charset=utf-8")
        if p.startswith("/assets/") and "/" not in p[len("/assets/"):] and ".." not in p:
            f = HERE / "assets" / p[len("/assets/"):]
            if f.is_file():
                return self._file(f, mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        if p == "/i18n.js":
            return self._file(HERE / "i18n.js", "text/javascript; charset=utf-8")
        if p == "/api/setup":
            return self._json(setup_status())
        if p == "/api/config":
            sizes = {m: {k: list(v) for k, v in s.items()} for m, s in SIZES.items()}
            avail = model_avail()
            return self._json({"sizes": sizes, "avail": avail})
        if p == "/api/estimate":
            q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
            m = q.get("model", "h3")
            s = q.get("size", "")
            if m in SIZES and s in SIZES[m]:
                w, h = SIZES[m][s]
                try:
                    secs, steps = float(q.get("seconds", 3)), int(q.get("steps", 6))
                except ValueError:
                    return self._json({"error": "bad"}, 400)
                return self._json(estimate(m, w, h, secs, steps))
            return self._json({"error": "bad"}, 400)
        if p == "/api/status":
            with lock:
                job = current["job"]
                busy = current["running"]
            st = read_status(job) if job and busy else None
            if st and busy:
                try:
                    st["preview"] = preview_info(job)
                except Exception:  # a half-written preview file; next poll gets it
                    st["preview"] = None
            return self._json({"busy": busy, "job": st, "queue": queue_summary()})
        if p == "/api/jobs":
            return self._json(list_jobs())
        if p == "/api/library":
            return self._json(_lib_index())
        if p.startswith("/files/jobs/") or p.startswith("/files/library/"):
            rel = p[len("/files/"):]
            f = (WORK / rel).resolve()
            ok_roots = (JOBS.resolve(), LIB.resolve())
            if any(r in f.parents for r in ok_roots) and f.is_file():
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                return self._file(f, ctype)
        self.send_error(404)

    def do_POST(self):
        # a JSON content type cannot be sent cross-site without a CORS
        # preflight, which this server never answers
        if not self._host_ok() or not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send_error(403)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("要傳 JSON 物件")
        except ValueError as e:
            return self._json({"error": f"看不懂的請求：{e}"}, 400)
        try:
            if self.path == "/api/run":
                return self._json(start_job(body))
            if self.path == "/api/assist":
                return self._json(assist(body))
            if self.path == "/api/stop":
                return self._json({"stopped": stop_job()})
            if self.path == "/api/library/add":
                return self._json(library_add(body))
            if self.path in ("/api/library/rename", "/api/library/move", "/api/library/delete"):
                return self._json(library_update(body, self.path.rsplit("/", 1)[1]))
            if self.path == "/api/delete":
                return self._json({"deleted": delete_job(body.get("id", ""))})
            if self.path == "/api/setup/install":
                return self._json(setup_install(body.get("id", "")))
            if self.path == "/api/setup/stop":
                return self._json({"stopped": setup_stop()})
            if self.path == "/api/setup/codex-login":
                return self._json(setup_codex_login())
            if self.path == "/api/cancel":
                return self._json({"cancelled": cancel_job(body.get("id", ""))})
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as e:   # never leave the page without an answer
            return self._json({"error": f"伺服器出錯：{type(e).__name__}: {e}"}, 500)
        self.send_error(404)


if __name__ == "__main__":
    JOBS.mkdir(parents=True, exist_ok=True)
    # jobs left "queued"/"running" by a previous server process never finished
    for j in list_jobs(limit=None):
        if j.get("state") in ("queued", "running"):
            pid = j.pop("pid", None)
            ps = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True,
                                text=True).stdout if pid else ""
            if "vpipe" in ps:   # vpipe runs in its own session, so it outlived the old server
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            j["state"] = "interrupted"
            save_job(j)
    print(f"vpipe工作台: http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
