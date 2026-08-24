"""Kokoro-ONNX synthesis → MP3 (+ per-chunk timings for a WebVTT transcript)."""
from __future__ import annotations
import subprocess, tempfile, time, io, os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import soundfile as sf
from .config import TTS, MUSIC
from .util import log

import logging
logging.getLogger("phonemizer").setLevel(logging.ERROR)
SR = 24000
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
_engine = None
WORKERS = int(os.environ.get("TTS_WORKERS") or max(1, min(4, (os.cpu_count() or 2) // 2)))


def engine():
    global _engine
    if _engine is None:
        import kokoro_onnx
        _engine = kokoro_onnx.Kokoro(str(TTS["model"]), str(TTS["voices"]))
    return _engine


def _render_one(args):
    i, text, voice, speed = args
    try:
        audio, sr = engine().create(text, voice=voice, speed=speed, lang=TTS["lang"])
        assert sr == SR
        return i, _trim(np.asarray(audio, dtype=np.float32))
    except Exception as e:  # a single bad chunk must not kill the episode
        log.warning("tts chunk %d failed (%s): %r", i, e, text[:80])
        return i, np.zeros(int(SR * 0.3), dtype=np.float32)


def _render_all(segs, voice, speed, progress_every):
    jobs = [(i, s["text"], voice, speed) for i, s in enumerate(segs)]
    out = [None] * len(jobs)
    started = time.time()
    def consume(it):
        n = 0
        for i, audio in it:
            out[i] = audio; n += 1
            if progress_every and n % progress_every == 0:
                log.info("  tts %d/%d chunks (%.0fs elapsed, %d workers)", n, len(jobs), time.time() - started, WORKERS)
    if WORKERS <= 1 or len(jobs) < 8:
        consume(map(_render_one, jobs))
    else:
        with ProcessPoolExecutor(max_workers=WORKERS) as pool:
            consume(pool.map(_render_one, jobs, chunksize=4))
    return out


def synthesize(segs: list[dict], mp3_path: Path, *, voice: str | None = None, speed: float | None = None,
               progress_every: int = 25) -> dict:
    """Render segments to mp3. Returns {"duration": s, "cues": [(start, end, text)], "bytes": n}."""
    voice = voice or TTS["voice"]
    speed = speed or TTS["speed"]
    intro = bool(MUSIC.get("enabled"))
    solo = float(MUSIC["solo"]) if intro else 0.0
    parts: list[np.ndarray] = []
    cues: list[tuple[float, float, str]] = []
    t = 0.0
    if solo:  # music-only lead-in; every cue below is naturally offset by `solo`
        parts.append(np.zeros(int(SR * solo), dtype=np.float32)); t += solo
    lead = np.zeros(int(SR * 0.5), dtype=np.float32)
    parts.append(lead); t += 0.5
    rendered = _render_all(segs, voice, speed, progress_every)
    for i, s in enumerate(segs):
        audio = rendered[i]
        dur = len(audio) / SR
        cues.append((t, t + dur, s["text"]))
        parts.append(audio); t += dur
        gap = np.zeros(int(SR * s["pause"]), dtype=np.float32)
        parts.append(gap); t += s["pause"]
    parts.append(np.zeros(int(SR * 1.0), dtype=np.float32)); t += 1.0
    pcm = np.concatenate(parts)
    peak = float(np.max(np.abs(pcm))) if len(pcm) else 1.0
    if peak > 0:
        pcm = pcm * min(1.0, 0.95 / peak)
    if intro:
        # order matters: loudness-normalize the speech alone (the bed must not be
        # measured or squashed by loudnorm), then mix the bed, then plain-encode.
        from .music import mix_intro   # parent process only — never in TTS workers
        out_sr = int(TTS["mp3_rate"])
        pcm = _loudnorm(pcm, SR, out_sr)
        pcm = mix_intro(pcm, out_sr, limit=MUSIC["limit"])
        encode_mp3(pcm, out_sr, mp3_path)
    else:
        encode_mp3(pcm, SR, mp3_path, filters=LOUDNORM)
    duration = mp3_duration(mp3_path) or t
    return {"duration": duration, "cues": cues, "bytes": mp3_path.stat().st_size}


def _loudnorm(pcm: np.ndarray, sr: int, out_sr: int) -> np.ndarray:
    """Loudness-normalize float PCM through ffmpeg loudnorm (the same target the
    encode step used before intro music existed); returns float32 mono @ out_sr."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, pcm, sr, subtype="FLOAT")
        wav = tmp.name
    try:
        out = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", wav, "-af", LOUDNORM, "-f", "f32le",
                              "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(out_sr), "-"],
                             check=True, capture_output=True).stdout
    finally:
        Path(wav).unlink(missing_ok=True)
    return np.frombuffer(out, dtype=np.float32).copy()


def encode_mp3(pcm: np.ndarray, sr: int, mp3_path: Path, *, filters: str | None = None):
    """Encode float PCM to MP3 with the pipeline's canonical codec settings."""
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, pcm, sr, subtype="FLOAT")
        wav = tmp.name
    try:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-ac", "1", "-ar", str(TTS["mp3_rate"])]
        if filters:
            cmd += ["-af", filters]
        cmd += ["-codec:a", "libmp3lame", "-b:a", TTS["mp3_bitrate"], "-write_xing", "1", str(mp3_path)]
        subprocess.run(cmd, check=True)
    finally:
        Path(wav).unlink(missing_ok=True)


def decode_mp3(mp3_path: Path, sr: int) -> np.ndarray:
    """Decode an MP3 to mono float32 PCM at `sr` via ffmpeg."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3_path), "-f", "f32le", "-acodec", "pcm_f32le",
                          "-ac", "1", "-ar", str(sr), "-"], check=True, capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def _trim(a: np.ndarray, thresh: float = 0.004, keep: float = 0.06) -> np.ndarray:
    """Trim leading/trailing silence Kokoro adds, keeping a short tail."""
    idx = np.where(np.abs(a) > thresh)[0]
    if len(idx) == 0:
        return a
    s = max(0, idx[0] - int(SR * keep)); e = min(len(a), idx[-1] + int(SR * keep))
    return a[s:e]


def mp3_duration(p: Path) -> float | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                             capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except Exception:
        return None


def tag_mp3(mp3_path: Path, *, title: str, artist: str, album: str, date: str, comment: str, art_jpeg: bytes | None, track: int | None):
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, COMM, APIC, TRCK, TCON, ID3NoHeaderError
    try:
        tags = ID3(str(mp3_path))
    except ID3NoHeaderError:
        tags = ID3()
    tags.delete(str(mp3_path))
    tags = ID3()
    tags.add(TIT2(encoding=3, text=title)); tags.add(TPE1(encoding=3, text=artist)); tags.add(TALB(encoding=3, text=album))
    tags.add(TDRC(encoding=3, text=date[:10])); tags.add(TCON(encoding=3, text="Podcast"))
    tags.add(COMM(encoding=3, lang="eng", desc="", text=comment))
    if track:
        tags.add(TRCK(encoding=3, text=str(track)))
    if art_jpeg:
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=art_jpeg))
    tags.save(str(mp3_path), v2_version=3)


def _vtt_ts(x: float) -> str:
    h, rem = divmod(x, 3600); m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def write_vtt(cues: list[tuple[float, float, str]], path: Path):
    ts = _vtt_ts
    lines = ["WEBVTT", ""]
    for i, (a, b, text) in enumerate(cues, 1):
        lines += [str(i), f"{ts(a)} --> {ts(b)}", text, ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def shift_vtt(path: Path, offset: float):
    """Shift every cue timestamp in a WebVTT file by +offset seconds, in place."""
    import re

    def bump(m: "re.Match[str]") -> str:
        h, mnt, s = m.group(0).split(":")
        return _vtt_ts(int(h) * 3600 + int(mnt) * 60 + float(s) + offset)

    pat = re.compile(r"\d{2,}:\d{2}:\d{2}\.\d{3}")
    out = []
    for line in path.read_text().splitlines():
        out.append(pat.sub(bump, line) if "-->" in line else line)
    path.write_text("\n".join(out) + "\n")
