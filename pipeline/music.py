"""Deterministic intro music bed: a warm ambient Fmaj9 synth pad under a sparse
pluck motif, ducked when the voice enters and faded out by ~9.5 s.

Everything here is pure numpy with fixed constants — calling intro_bed() twice
always yields bit-identical audio. Bed generation runs in the parent process
only (synthesize() / the `intro` backfill); TTS workers never import-execute it.
"""
from __future__ import annotations
import numpy as np
from .config import MUSIC

# ---- timeline (seconds) -----------------------------------------------------
DURATION = 9.5                    # total bed length
ATTACK = 1.5                      # slow pad fade-in
SOLO = float(MUSIC.get("solo", 2.5))   # full level until here (voice enters)
DUCK_END = SOLO + 0.8             # ducked to DUCK_LEVEL by here (~3.3 s)
DUCK_LEVEL = 0.25                 # bed level under the voice
FADE_START = 7.0                  # cosine fade FADE_START → DURATION

# ---- level ------------------------------------------------------------------
# Speech leaves ffmpeg loudnorm with true peaks at -1.5 dBTP (~0.84 linear).
# Solo-section bed peak 0.70 (~ -3.1 dBFS) is clearly audible but soft; ducked
# it peaks ~0.175 (~ -15 dBFS), i.e. ~13.5 dB under speech peaks.
SOLO_PEAK = 0.70

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

# ---- motif: 5 soft plucks on Fmaj9 chord tones ------------------------------
MOTIF = [                         # (onset s, freq Hz, relative amplitude)
    (0.55, 440.000, 1.00),        # A4
    (1.30, 523.251, 0.85),        # C5
    (2.00, 391.995, 0.80),        # G4
    (2.75, 329.628, 0.70),        # E4
    (3.50, 440.000, 0.55),        # A4
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


def _duck_fade(t: np.ndarray) -> np.ndarray:
    env = np.ones_like(t)
    m = (t >= SOLO) & (t < DUCK_END)                      # smooth duck as voice enters
    x = (t[m] - SOLO) / (DUCK_END - SOLO)
    env[m] = DUCK_LEVEL + (1.0 - DUCK_LEVEL) * (0.5 + 0.5 * np.cos(np.pi * x))
    env[(t >= DUCK_END)] = DUCK_LEVEL
    m = (t >= FADE_START) & (t < DURATION)                # cosine fade to silence
    x = (t[m] - FADE_START) / (DURATION - FADE_START)
    env[m] *= 0.5 + 0.5 * np.cos(np.pi * x)
    env[t >= DURATION] = 0.0
    return env


def intro_bed(sr: int = 24000) -> np.ndarray:
    """The full ~9.5 s intro bed as mono float32, deterministic for a given sr."""
    n = int(round(DURATION * sr))
    t = np.arange(n, dtype=np.float64) / sr
    bed = _lowpass(_pad(t) + _plucks(t), sr) * _duck_fade(t)
    peak = float(np.max(np.abs(bed)))
    if peak > 0:
        bed *= SOLO_PEAK / peak                            # peak lands in the solo section
    return bed.astype(np.float32)


def mix_intro(speech: np.ndarray, sr: int, *, limit: float | None = None) -> np.ndarray:
    """Mix the bed (from t=0) into speech PCM that already starts with the solo
    lead-in silence. Scales the whole mix down if its peak would exceed `limit`
    so the encoded file can never clip."""
    limit = float(MUSIC.get("limit", 0.89)) if limit is None else float(limit)
    bed = intro_bed(sr)
    n = max(len(speech), len(bed))
    out = np.zeros(n, dtype=np.float32)
    out[: len(speech)] += np.asarray(speech, dtype=np.float32)
    out[: len(bed)] += bed
    peak = float(np.max(np.abs(out))) if n else 0.0
    if peak > limit:
        out *= limit / peak
    return out


def add_intro(speech: np.ndarray, sr: int) -> np.ndarray:
    """Prepend SOLO seconds of silence to speech, then mix the bed (backfill path)."""
    lead = np.zeros(int(round(SOLO * sr)), dtype=np.float32)
    return mix_intro(np.concatenate([lead, np.asarray(speech, dtype=np.float32)]), sr)
