"""Build the GoldenRecord pitch video from video/script.yaml and the captured frames.

  1. Narration per segment with a neural voice (edge-tts), plus word timings for captions
  2. One clip per visual: slow eased zoom towards its focus point; a LIVE RUN badge on harness footage
  3. Concatenate, mux narration, burn captions -> video/out/GoldenRecord-Pitch-Video.mp4

Run: python video/build.py   (needs ffmpeg on PATH or FFMPEG env var)
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

import edge_tts
import yaml
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
FRAMES, WORK = OUT / "frames", OUT / "work"
FPS, W, H = 30, 1920, 1080
TAIL = 0.7  # pause after each segment's narration (seconds)
FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("FFPROBE") or shutil.which("ffprobe") or "ffprobe"
TEAM = [("Vinod Atmakur", "Product owner & quality architect"), ("Anand Topu", "AI Engineer"),
        ("Yogesh Godwade", "AI Engineer"), ("Koushik Das", "AI Engineer"),
        ("Ravi Chander Kanikala", "AI Engineer"), ("Dilip Divakaran", "AI Engineer")]


def run(cmd: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd[:6])} ...\n{result.stderr[-2000:]}")


def duration(path: Path) -> float:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    return float(out.stdout.strip())


# ---------------------------------------------------------------- cards and badge
CARD_CSS = """body{margin:0;width:1920px;height:1080px;font-family:'Segoe UI',sans-serif;}
.dark{background:#0F1B2D;color:#F6F4EE}.e{font-weight:700;letter-spacing:4px;text-transform:uppercase;color:#E8B84A;font-size:24px}"""


def render_cards() -> None:
    title = (f"<html><head><style>{CARD_CSS}</style></head><body class='dark'><div style='padding:128px;height:824px;"
             "display:flex;flex-direction:column;justify-content:space-between'>"
             "<div class='e'>Hackathon · Track 02 · GenAI Data Harmonization &amp; Quality Guardrails</div>"
             "<div><div style='font-size:160px;font-weight:700;letter-spacing:-4px;line-height:1'>Golden"
             "<span style='color:#E8B84A'>Record</span></div><div style='font-size:46px;color:#C9D2DE;margin-top:36px;"
             "max-width:1300px'>Fabric tells you your data is bad. GoldenRecord fixes it: safely, by root cause, "
             "with an audit trail.</div></div><div style='font-size:28px;color:#9AA7B8;margin-bottom:150px'>Team GoldenRecord · "
             "built on Microsoft Fabric</div></div></body></html>")
    cards = "".join(
        f"<div style='background:{'#0F1B2D' if i == 0 else '#FDFCF9'};border:1px solid #D9D4C7;border-radius:18px;"
        f"padding:34px 38px'><div style='font-size:36px;font-weight:700;color:{'#F6F4EE' if i == 0 else '#0F1B2D'}'>"
        f"{n}</div><div style='font-size:26px;font-weight:600;margin-top:10px;color:{'#E8B84A' if i == 0 else '#8A5F00'}'>"
        f"{r}</div></div>" for i, (n, r) in enumerate(TEAM))
    team = (f"<html><head><style>{CARD_CSS}</style></head><body style='background:#F6F4EE;color:#0F1B2D'>"
            "<div style='padding:120px 128px'><div class='e' style='color:#8A5F00'>The team</div>"
            "<div style='font-size:80px;font-weight:700;margin:14px 0 56px'>Team GoldenRecord</div>"
            f"<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:28px'>{cards}</div></div></body></html>")
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, doc in (("card_title.png", title), ("card_team.png", team)):
            page = b.new_page(viewport={"width": W, "height": H})
            page.set_content(doc)
            page.screenshot(path=str(FRAMES / name))
            page.close()
        b.close()


def mask_placeholder(src: Path, dst: Path) -> None:
    """Paint over the '[What we have seen ...]' placeholder line on the Why-us slide."""
    img = Image.open(src).convert("RGB")
    bg = img.getpixel((40, 640))
    ImageDraw.Draw(img).rectangle([90, 600, 1830, 690], fill=bg)
    img.save(dst)


def render_badge() -> Path:
    path = WORK / "badge_live.png"
    font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 26)
    text = "LIVE RUN  ·  local dev harness  ·  same code as the Fabric notebooks"
    w = int(font.getlength(text)) + 70
    img = Image.new("RGBA", (w, 54), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, 53], radius=27, fill=(15, 27, 45, 225))
    d.ellipse([20, 19, 36, 35], fill=(232, 76, 61, 255))
    d.text((48, 11), text, font=font, fill=(246, 244, 238, 255))
    img.save(path)
    return path


# ---------------------------------------------------------------- narration and captions
async def tts(text: str, voice: str, rate: str, mp3: Path, attempts: int = 5) -> list[tuple[float, float, str]]:
    """The speech service occasionally returns no audio; retry with backoff."""
    for attempt in range(1, attempts + 1):
        try:
            return await _tts_once(text, voice, rate, mp3)
        except edge_tts.exceptions.NoAudioReceived:
            if attempt == attempts:
                raise
            await asyncio.sleep(2 * attempt)


async def _tts_once(text: str, voice: str, rate: str, mp3: Path) -> list[tuple[float, float, str]]:
    words = []
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append((start, start + chunk["duration"] / 1e7, chunk["text"]))
    return words


def _norm(token: str) -> str:
    return re.sub(r"[^0-9a-z]", "", token.lower())


def restore_punctuation(words, text: str):
    """Word timings come without punctuation; take each word's spelling from the script instead."""
    tokens, j, out = text.split(), 0, []
    for s, e, w in words:
        for k in range(j, min(j + 4, len(tokens))):
            if _norm(tokens[k]) == _norm(w) or (_norm(w) and _norm(tokens[k]).startswith(_norm(w))):
                out.append((s, e, tokens[k]))
                j = k + 1
                break
        else:
            out.append((s, e, w))
    return out


def caption_cues(words, offset: float, text: str, max_chars: int = 46) -> list[tuple[float, float, str]]:
    """Group word timings into short caption lines; break at sentence ends."""
    words = restore_punctuation(words, text)
    cues, line, start = [], [], None
    for i, (s, e, w) in enumerate(words):
        if start is None:
            start = s
        line.append(w)
        joined = " ".join(line)
        nxt = words[i + 1][2] if i + 1 < len(words) else ""
        sentence_end = w[-1:] in ".?!:"
        if len(joined) >= max_chars - 8 or sentence_end or i == len(words) - 1 or len(joined + " " + nxt) > max_chars:
            cues.append((offset + start, offset + e + 0.15, joined))
            line, start = [], None
    return cues


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


# ---------------------------------------------------------------- video clips
def clip(src: Path, dur: float, zoom: float, focus, live: bool, badge: Path, out: Path) -> None:
    n = max(1, int(round(dur * FPS)))
    fx, fy = focus or (W / 2, H / 2)
    e = f"(on/{n})*(on/{n})*(3-2*(on/{n}))"  # smoothstep ease
    z = f"1+({zoom}-1)*{e}"
    cx, cy = f"({W / 2}+({fx}-{W / 2})*{e})*2", f"({H / 2}+({fy}-{H / 2})*{e})*2"
    zp = (f"scale={W * 2}:{H * 2},zoompan=z='{z}':x='max(0,min(iw-iw/zoom,{cx}-iw/zoom/2))'"
          f":y='max(0,min(ih-ih/zoom,{cy}-ih/zoom/2))':d={n}:s={W}x{H}:fps={FPS},"
          f"fade=t=in:st=0:d=0.35,fade=t=out:st={max(0, dur - 0.35):.2f}:d=0.35")
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", str(src)]
    if live:
        cmd += ["-i", str(badge), "-filter_complex", f"[0:v]{zp}[v];[v][1:v]overlay=W-w-36:30,format=yuv420p[o]",
                "-map", "[o]"]
    else:
        cmd += ["-vf", f"{zp},format=yuv420p"]
    cmd += ["-frames:v", str(n), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-r", str(FPS), str(out)]
    run(cmd)


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    spec = yaml.safe_load((ROOT / "script.yaml").read_text(encoding="utf-8"))
    render_cards()
    badge = render_badge()
    mask_placeholder(FRAMES / "slide_11.png", FRAMES / "card_edge.png")
    swaps = {"slide_01.png": "card_title.png", "slide_16.png": "card_team.png",
             "slide_11.png": "card_edge.png"}  # avoid deck placeholders

    clips, audios, cues, t = [], [], [], 0.0
    for seg in spec["segments"]:
        text = " ".join(seg["text"].split())
        mp3 = WORK / f"{seg['id']}.mp3"
        words = asyncio.run(tts(text, spec["voice"], spec.get("rate", "+0%"), mp3))
        seg_dur = duration(mp3) + TAIL
        cues += caption_cues(words, t, text)
        audios.append((mp3, seg_dur))
        total_w = sum(v["weight"] for v in seg["visuals"])
        for i, v in enumerate(seg["visuals"]):
            d = seg_dur * v["weight"] / total_w
            out = WORK / f"{seg['id']}_{i}.mp4"
            clip(FRAMES / swaps.get(v["file"], v["file"]), d, v.get("zoom", 1.0), v.get("focus"),
                 v.get("live", False), badge, out)
            clips.append(out)
        print(f"{seg['id']:18} {seg_dur:6.1f}s  ({t / 60:4.1f} min)")
        t += seg_dur

    (WORK / "clips.txt").write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
    run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "clips.txt", "-c", "copy",
         "video.mp4"], cwd=WORK)
    # Narration: each segment padded to its slot, then joined.
    parts = []
    for i, (mp3, seg_dur) in enumerate(audios):
        part = WORK / f"a{i:02d}.wav"
        run([FFMPEG, "-y", "-loglevel", "error", "-i", str(mp3), "-af", f"apad,atrim=0:{seg_dur:.3f}",
             "-ar", "48000", "-ac", "2", str(part)])
        parts.append(part)
    (WORK / "audio.txt").write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "audio.txt", "-c", "copy",
         "audio.wav"], cwd=WORK)
    cues = [(st, min(en, cues[i + 1][0] - 0.02) if i + 1 < len(cues) else en, tx)  # no overlapping lines
            for i, (st, en, tx) in enumerate(cues)]
    (WORK / "captions.srt").write_text("".join(
        f"{i}\n{srt_time(s)} --> {srt_time(e)}\n{txt}\n\n" for i, (s, e, txt) in enumerate(cues, 1)), encoding="utf-8")
    shutil.copy(WORK / "captions.srt", OUT / "GoldenRecord-Pitch-Video.srt")
    style = ("FontName=Segoe UI Semibold,FontSize=17,PrimaryColour=&H00FFFFFF,BackColour=&H99000000,"
             "BorderStyle=3,Outline=6,Shadow=0,MarginV=28")
    run([FFMPEG, "-y", "-loglevel", "error", "-i", "video.mp4", "-i", "audio.wav",
         "-vf", f"subtitles=captions.srt:force_style='{style}'", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(OUT / "GoldenRecord-Pitch-Video.mp4")],
        cwd=WORK)
    print(f"done: {OUT / 'GoldenRecord-Pitch-Video.mp4'}  ({t / 60:.1f} min)")


if __name__ == "__main__":
    main()
