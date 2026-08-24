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


def _verified_voices() -> str:
    """A private, integrity-checked copy of the voices file for this process.
    Concurrent multi-process reads of one file can return corrupt data on some
    container filesystems (np.load then fails per-voice with CRC errors), so each
    worker copies the zip to its own temp path and verifies it before use."""
    import atexit, shutil, zipfile
    src = str(TTS["voices"])
    for attempt in range(5):
        fd, dst = tempfile.mkstemp(suffix=".bin", prefix=f"kokoro-voices-{os.getpid()}-")
        os.close(fd)
        try:
            shutil.copyfile(src, dst)
            if zipfile.ZipFile(dst).testzip() is None:
                atexit.register(lambda p=dst: Path(p).unlink(missing_ok=True))
                return dst
        except Exception:
            pass
        Path(dst).unlink(missing_ok=True)
        time.sleep(0.4 * (attempt + 1))
    return src  # last resort: the shared file


def engine():
    global _engine
    if _engine is None:
        import kokoro_onnx
        _engine = kokoro_onnx.Kokoro(str(TTS["model"]), _verified_voices())
    return _engine


def _reset_engine():
    global _engine
    _engine = None


def _render_one(args):
    i, text, voice, speed = args
    err = None
    for attempt in range(3):
        try:
            audio, sr = engine().create(text, voice=voice, speed=speed, lang=TTS["lang"])
            assert sr == SR
            return i, _trim(np.asarray(audio, dtype=np.float32)), True
        except Exception as e:
            err = e
            _reset_engine()  # reload from a fresh verified voices copy
            time.sleep(0.3 * (attempt + 1))
    log.warning("tts chunk %d failed after retries (%s): %r", i, err, text[:80])
    return i, np.zeros(int(SR * 0.3), dtype=np.float32), False


def _render_all(segs, voice, speed, progress_every):
    jobs = [(i, s["text"], voice, speed) for i, s in enumerate(segs)]
    out = [None] * len(jobs)
    failed = 0
    started = time.time()
    def consume(it):
        nonlocal failed
        n = 0
        for i, audio, ok in it:
            out[i] = audio; n += 1
            failed += 0 if ok else 1
            if progress_every and n % progress_every == 0:
                log.info("  tts %d/%d chunks (%.0fs elapsed, %d workers)", n, len(jobs), time.time() - started, WORKERS)
    if WORKERS <= 1 or len(jobs) < 8:
        consume(map(_render_one, jobs))
    else:
        with ProcessPoolExecutor(max_workers=WORKERS) as pool:
            consume(pool.map(_render_one, jobs, chunksize=4))
    # an isolated flaky chunk degrades to a short silence; wholesale failure must
    # abort loudly rather than publish a silently truncated episode
    if failed > max(1, len(jobs) // 50):
        raise RuntimeError(f"TTS failed on {failed}/{len(jobs)} chunks — aborting episode")
    return out


def synthesize(segs: list[dict], mp3_path: Path, *, voice: str | None = None, speed: float | None = None,
               slate: str | None = None, progress_every: int = 25) -> dict:
    """Render segments to mp3. When MUSIC is enabled and `slate` is given, the file
    opens with a produced cold open (music bed alone, then the slate line in the
    announcer voice over the ducked bed) and closes with a pad under the spoken outro.

    Returns {"duration": s, "cues": [(start, end, text)], "marks": [(start, kind, text)],
    "bytes": n}. Marks flag the slate, the title, headings, and the outro — the
    chapter sources."""
    voice = voice or TTS["voice"]
    speed = speed or TTS["speed"]
    music = bool(MUSIC.get("enabled")) and bool(slate)
    parts: list[np.ndarray] = []
    cues: list[tuple[float, float, str]] = []
    marks: list[tuple[float, str, str]] = []
    t = 0.0
    slate_end = 0.0
    if music:
        _, slate_audio, slate_ok = _render_one((0, slate, MUSIC["slate_voice"], speed))
        if not slate_ok:
            raise RuntimeError("TTS failed on the slate line — aborting episode")
        pre = float(MUSIC["pre"])
        parts.append(np.zeros(int(SR * pre), dtype=np.float32)); t += pre
        dur = len(slate_audio) / SR
        cues.append((t, t + dur, slate)); marks.append((t, "slate", slate))
        parts.append(slate_audio); t += dur
        slate_end = t
        parts.append(np.zeros(int(SR * float(MUSIC["gap"])), dtype=np.float32)); t += float(MUSIC["gap"])
    parts.append(np.zeros(int(SR * 0.5), dtype=np.float32)); t += 0.5
    rendered = _render_all(segs, voice, speed, progress_every)
    outro_start = outro_end = None
    for i, s in enumerate(segs):
        audio = rendered[i]
        dur = len(audio) / SR
        cues.append((t, t + dur, s["text"]))
        if s.get("kind") in ("title", "heading", "outro"):
            marks.append((t, s["kind"], s["text"]))
        if s.get("kind") == "outro":
            outro_start = t if outro_start is None else outro_start
            outro_end = t + dur
        parts.append(audio); t += dur
        gap = np.zeros(int(SR * s["pause"]), dtype=np.float32)
        parts.append(gap); t += s["pause"]
    tail = float(MUSIC["tail"]) + 0.3 if music else 1.0
    parts.append(np.zeros(int(SR * tail), dtype=np.float32)); t += tail
    pcm = np.concatenate(parts)
    peak = float(np.max(np.abs(pcm))) if len(pcm) else 1.0
    if peak > 0:
        pcm = pcm * min(1.0, 0.95 / peak)
    if music:
        # order matters: loudness-normalize the speech alone (the beds must not be
        # measured or squashed by loudnorm), then mix the beds, then plain-encode.
        from .music import intro_bed, outro_pad, mix_beds   # parent process only — never in TTS workers
        out_sr = int(TTS["mp3_rate"])
        pcm = _loudnorm(pcm, SR, out_sr)
        bed = intro_bed(out_sr, duck_at=float(MUSIC["pre"]), fade_from=slate_end + 0.5,
                        duration=slate_end + float(MUSIC["gap"]) + 3.2)
        outro = o_at = None
        if outro_start is not None:
            o_at = max(0.0, outro_start - 0.9)
            outro = outro_pad(out_sr, fade_from=(outro_end - o_at) + 0.3, duration=t - o_at)
        pcm = mix_beds(pcm, out_sr, intro=bed, outro=outro, outro_at=o_at or 0.0, limit=MUSIC["limit"])
        encode_mp3(pcm, out_sr, mp3_path)
    else:
        encode_mp3(pcm, SR, mp3_path, filters=LOUDNORM)
    duration = mp3_duration(mp3_path) or t
    return {"duration": duration, "cues": cues, "marks": marks, "bytes": mp3_path.stat().st_size}


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


def tag_mp3(mp3_path: Path, *, title: str, artist: str, album: str, date: str, comment: str, art_jpeg: bytes | None,
            track: int | None, chapters: list[tuple[float, str]] | None = None, duration: float | None = None):
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, COMM, APIC, TRCK, TCON, CHAP, CTOC, CTOCFlags, ID3NoHeaderError
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
    if chapters:
        ids = []
        for i, (start, ch_title) in enumerate(chapters):
            end = chapters[i + 1][0] if i + 1 < len(chapters) else (duration or start)
            ids.append(f"ch{i}")
            tags.add(CHAP(element_id=f"ch{i}", start_time=int(start * 1000), end_time=int(end * 1000),
                          sub_frames=[TIT2(encoding=3, text=ch_title)]))
        tags.add(CTOC(element_id="toc", flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
                      child_element_ids=ids, sub_frames=[TIT2(encoding=3, text="Chapters")]))
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
