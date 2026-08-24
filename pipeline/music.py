"""Deterministic music beds: a warm ambient Fmaj9 synth pad (plus a sparse pluck
motif on the intro) that sits under the cold open and the spoken outro.

Everything here is pure numpy with fixed constants — the same arguments always
yield bit-identical audio. Bed generation runs in the parent process only
(synthesize()); TTS workers never import-execute it.
"""
from __future__ import annotations
import numpy as np
from .config import MUSIC

ATTACK = 1.2                      # slow pad fade-in
DUCK_LEVEL = 0.27                 # bed level under the voice

# ---- level ------------------------------------------------------------------
# Speech leaves ffmpeg loudnorm with true peaks at -1.5 dBTP (~0.84 linear).
# Solo-section bed peak 0.70 (~ -3.1 dBFS) is clearly audible but soft; ducked
# it peaks ~0.19 (~ -14.4 dBFS), i.e. ~13 dB under speech peaks.
SOLO_PEAK = 0.70
OUTRO_PEAK = 0.30                 # outro pad is accompaniment only, never solo-loud

# ---- pad: Fmaj9 voicing (F2 sub + F3 A3 C4 E4 G4) --------------------------
PAD_NOTES = [                     # (freq Hz, relative amplitude)
    (87.307, 0.90),               # F2 sub
    (174.614, 0.55),              # F3
    (220.000, 0.40),              # A3
    (261.626, 0.36),              # C4
    (329.628, 0.30),              # E4
    (391.995, 0.26),              # G4
]
DETUNE = 0.0022                   # ±0.22 % pairwise detune → slow chorus beating
PARTIAL_ROLLOFF = (1.00, 0.30, 0.10)   # harmonics 1..3

# ---- motif: soft plucks on Fmaj9 chord tones (intro only) -------------------
MOTIF = [                         # (onset s, freq Hz, relative amplitude)
    (0.45, 440.000, 1.00),        # A4
    (1.15, 523.251, 0.85),        # C5
    (1.90, 391.995, 0.75),        # G4
    (2.70, 329.628, 0.65),        # E4
    (3.50, 440.000, 0.50),        # A4
]
PLUCK_TAU = 0.6                   # exponential decay time constant
PLUCK_H2 = 0.18                   # faint 2nd harmonic

LOWPASS_HZ = 2000.0               # gentle zero-phase lowpass so the bed sits back


def _pad(t: np.ndarray) -> np.ndarray:
    out = np.zeros_like(t)
    for ni, (f, amp) in enumerate(PAD_NOTES):
        for h, roll in enumerate(PARTIAL_ROLLOFF, start=1):
            if roll <= 0:
                continue
            # deterministic per-component phases avoid an all-cosine onset spike
            ph = 0.37 * h + 1.13 * ni
            for sgn in (-1.0, 1.0):
                fr = f * h * (1.0 + sgn * DETUNE)
                out += (amp * roll * 0.5) * np.sin(2 * np.pi * fr * t + ph + 0.5 * sgn)
    env = np.ones_like(t)
    a = t < ATTACK
    env[a] = 0.5 - 0.5 * np.cos(np.pi * t[a] / ATTACK)   # raised-cosine attack
    return out * env


def _plucks(t: np.ndarray) -> np.ndarray:
    out = np.zeros_like(t)
    for t0, f, amp in MOTIF:
        m = t >= t0
        tt = t[m] - t0
        env = np.expm1(-tt / 0.008) * -1.0 * np.exp(-tt / PLUCK_TAU)  # 8 ms attack, ~0.6 s decay
        tone = np.sin(2 * np.pi * f * tt) + PLUCK_H2 * np.sin(2 * np.pi * 2 * f * tt)
        out[m] += 0.32 * amp * env * tone
    return out


def _lowpass(x: np.ndarray, sr: int, fc: float = LOWPASS_HZ) -> np.ndarray:
    """Zero-phase FFT lowpass with a 2nd-order-Butterworth magnitude curve."""
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), d=1.0 / sr)
    spec *= 1.0 / np.sqrt(1.0 + (freqs / fc) ** 4)
    return np.fft.irfft(spec, n=len(x))


def _cos_step(t: np.ndarray, t0: float, t1: float, from_v: float, to_v: float, env: np.ndarray):
    """In-place raised-cosine ramp of env from from_v to to_v over [t0, t1]."""
    m = (t >= t0) & (t < t1)
    x = (t[m] - t0) / max(t1 - t0, 1e-6)
    env[m] = from_v + (to_v - from_v) * (0.5 - 0.5 * np.cos(np.pi * x))
    env[t >= t1] = to_v


def intro_bed(sr: int, *, duck_at: float, fade_from: float, duration: float) -> np.ndarray:
    """Intro bed as mono float32: full level until `duck_at` (the slate voice
    entry), ducked under the voice, cosine-faded to silence over
    [fade_from, duration]. Deterministic for given arguments."""
    n = int(round(duration * sr))
    t = np.arange(n, dtype=np.float64) / sr
    env = np.ones_like(t)
    _cos_step(t, duck_at - 0.25, duck_at + 0.55, 1.0, DUCK_LEVEL, env)
    fade = np.ones_like(t)
    _cos_step(t, fade_from, duration, 1.0, 0.0, fade)
    bed = _lowpass(_pad(t) + _plucks(t), sr) * env * fade
    peak = float(np.max(np.abs(bed)))
    if peak > 0:
        bed *= SOLO_PEAK / peak                            # peak lands in the solo section
    return bed.astype(np.float32)


def outro_pad(sr: int, *, fade_from: float, duration: float) -> np.ndarray:
    """Pad-only tail under the spoken outro: fades in over ATTACK, holds low
    beneath the voice, then cosine-fades to silence over [fade_from, duration]."""
    n = int(round(duration * sr))
    t = np.arange(n, dtype=np.float64) / sr
    fade = np.ones_like(t)
    _cos_step(t, fade_from, duration, 1.0, 0.0, fade)
    pad = _lowpass(_pad(t), sr) * fade
    peak = float(np.max(np.abs(pad)))
    if peak > 0:
        pad *= OUTRO_PEAK / peak
    return pad.astype(np.float32)


def mix_beds(speech: np.ndarray, sr: int, *, intro: np.ndarray | None,
             outro: np.ndarray | None = None, outro_at: float = 0.0,
             limit: float | None = None) -> np.ndarray:
    """Mix the intro bed (from t=0) and the outro pad (from `outro_at` seconds)
    into speech PCM. Scales the whole mix down iff its peak would exceed `limit`
    so the encoded file can never clip."""
    limit = float(MUSIC.get("limit", 0.89)) if limit is None else float(limit)
    n = len(speech)
    if outro is not None:
        n = max(n, int(round(outro_at * sr)) + len(outro))
    if intro is not None:
        n = max(n, len(intro))
    out = np.zeros(n, dtype=np.float32)
    out[: len(speech)] += np.asarray(speech, dtype=np.float32)
    if intro is not None:
        out[: len(intro)] += intro
    if outro is not None:
        o = int(round(outro_at * sr))
        out[o: o + len(outro)] += outro
    peak = float(np.max(np.abs(out))) if n else 0.0
    if peak > limit:
        out *= limit / peak
    return out
