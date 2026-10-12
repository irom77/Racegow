"""Optional music bed for the exported clip.

  synth_track — generates an upbeat electronic loop (kick, clap, hats, bass, arpeggio) with numpy, so
                `--music auto` needs no bundled audio files and no licence check. A random seed picks
                tempo, key, chord progression and patterns; the same seed gives the same track.
  mix_music   — one ffmpeg pass: music looped/trimmed to the clip, faded in/out, levelled to sit under the motor audio,
                video stream copied untouched."""
import random
import re
import subprocess
import wave
from pathlib import Path
import numpy as np
from .media import ffmpeg_exe

SR = 44100
PROGRESSIONS = [(0, 8, 3, 10), (0, 5, 8, 7), (0, 10, 8, 7), (0, 3, 8, 10), (0, 8, 10, 7)]   # minor-key roots
MINOR = (0, 3, 7)
MAJOR_ON = {3, 8, 10}            # degrees that take a major triad in natural minor


def _hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def _env(n, attack, decay):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(attack, 1e-4)) * np.exp(-t / decay)


def _saw(f, n, harmonics):
    t = np.arange(n) / SR
    return sum(np.sin(2 * np.pi * f * k * t) / k for k in range(1, harmonics + 1)) * 0.6


def _square(f, n, harmonics):
    t = np.arange(n) / SR
    return sum(np.sin(2 * np.pi * f * k * t) / k for k in range(1, 2 * harmonics, 2)) * 0.8


def _kick(n):
    t = np.arange(n) / SR
    f = 45 + 110 * np.exp(-t / 0.03)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.18)


def _noise(rng, n, decay, bright):
    x = rng.standard_normal(n)
    for _ in range(bright):
        x = np.diff(x, prepend=0)                # crude high-pass: each pass removes more low end
    return x / (np.abs(x).max() + 1e-9) * _env(n, 0.001, decay)


def _add(buf, sig, at):
    at = int(at)
    if at >= len(buf):
        return
    m = min(len(sig), len(buf) - at)
    buf[at:at + m] += sig[:m]


def synth_track(seconds, path, seed=None):
    """Write a stereo 16-bit WAV of `seconds` and return the seed used."""
    seed = random.randrange(1 << 30) if seed is None else int(seed)
    rnd, rng = random.Random(seed), np.random.default_rng(seed)
    bpm = rnd.choice([128, 132, 136, 140, 144])
    key = 45 + rnd.randrange(12)                 # A2 .. G#3: bass register
    prog = rnd.choice(PROGRESSIONS)
    hats16 = rnd.random() < 0.5
    arp_shape = rnd.choice([(0, 1, 2, 1), (0, 1, 2, 3), (2, 1, 0, 1), (0, 2, 1, 2)])
    beat = 60.0 / bpm
    bar = 4 * beat
    n = int((seconds + bar) * SR)
    drums, bass, arp = np.zeros(n), np.zeros(n), np.zeros(n)
    duck = np.ones(n)                            # sidechain pump on the kick
    kick, kn = _kick(int(0.35 * SR)), int(beat * SR)
    pump = 1 - 0.6 * np.exp(-np.arange(kn) / SR / 0.09)
    nbars = int(seconds / bar) + 2
    for b in range(nbars):
        t0 = b * bar
        root = key + prog[b % 4]
        triad = (0, 4, 7) if prog[b % 4] in MAJOR_ON else MINOR
        intro = b == 0
        for q in range(4):
            tq = t0 + q * beat
            if not intro:
                _add(drums, kick, tq * SR)
                _add(duck, pump - 1, tq * SR)
                if q in (1, 3):
                    _add(drums, 0.45 * _noise(rng, int(0.2 * SR), 0.07, 1), tq * SR)
            steps = 4 if hats16 else 2
            for s in range(steps):
                if steps == 2 and s == 0:
                    continue                     # 8th-note hats sit on the off-beat
                _add(drums, 0.12 * _noise(rng, int(0.06 * SR), 0.02, 3), (tq + s * beat / steps) * SR)
            if not intro:                        # off-beat bass, 8ths
                bn = int(beat / 2 * SR)
                for e in (0, 1):
                    note = root + (12 if e else 0)
                    _add(bass, _saw(_hz(note), bn, 6) * _env(bn, 0.005, 0.12), (tq + e * beat / 2) * SR)
            an = int(beat / 4 * SR)              # arpeggio, 16ths, one octave above the chord
            for s in range(4):
                deg = triad[arp_shape[s] % 3] + (12 if arp_shape[s] == 3 else 0)
                _add(arp, _square(_hz(root + 24 + deg), an, 4) * _env(an, 0.003, 0.08), (tq + s * beat / 4) * SR)
    d = int(0.75 * beat * SR)                    # dotted-8th delay on the arpeggio, panned right
    echo = np.concatenate([np.zeros(d), arp[:-d]]) * 0.35
    body = drums * 0.9 + (bass * 0.5 + arp * 0.16) * duck
    left, right = body + echo * duck * 0.4, body + echo * duck
    st = np.tanh(1.4 * np.stack([left, right], 1)[:int(seconds * SR)])
    st = st / (np.abs(st).max() + 1e-9) * 0.89
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((st * 32767).astype("<i2").tobytes())
    return dict(seed=seed, bpm=bpm, key=key, progression=prog)


def has_audio(path):
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    return bool(re.search(r"Stream #.*Audio:", r.stderr))


LEVEL = "loudnorm=I=-16:TP=-2,aresample=48000"     # both sources to the same loudness first


def mix_music(video, music, out, seconds, music_db=-10.0):
    """Music looped/trimmed to `seconds`, 1 s fade in, 1.5 s fade out, under the clip's own audio.
    Both are levelled to -16 LUFS, so `music_db` is the music level relative to the motor audio."""
    fade = (f"atrim=0:{seconds:.3f},{LEVEL},afade=t=in:d=1,afade=t=out:st={max(0.0, seconds - 1.5):.3f}:d=1.5,"
            f"volume={music_db:g}dB")
    if has_audio(video):
        graph = (f"[1:a]{fade}[m];[0:a]{LEVEL}[s];"
                 f"[s][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    else:
        graph = f"[1:a]{fade}[a]"
    cmd = [ffmpeg_exe(), "-loglevel", "error", "-y", "-i", str(video), "-stream_loop", "-1", "-i", str(music),
           "-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           "-t", f"{seconds:.3f}", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
