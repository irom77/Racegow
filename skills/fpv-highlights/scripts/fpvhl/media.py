"""Reading clips with PyAV. Times are seconds from the first video frame of the recording (as in the scan)."""
import numpy as np


def _open(path):
    import av
    c = av.open(str(path))
    vs = c.streams.video[0]
    vs.thread_type = "AUTO"
    t0 = float(vs.start_time * vs.time_base) if vs.start_time is not None else 0.0
    return c, vs, t0


def _seek(c, vs, t0, t):
    target = max(0.0, t - 1.5)
    try:
        c.seek(int((t0 + target) / vs.time_base), stream=vs, backward=True)
    except Exception:
        c.seek(0)


def frames_between(path, start, end):
    """Yield (t, BGR frame) for start <= t < end."""
    import av
    c, vs, t0 = _open(path)
    try:
        for attempt in (0, 1):
            _seek(c, vs, t0, start if attempt == 0 else start - 10)
            first = True
            out = []
            for fr in c.decode(vs):
                if fr.time is None:
                    continue
                t = fr.time - t0
                if first:
                    first = False
                    if t > start + 0.05 and attempt == 0 and start > 0.5:
                        break          # seek overshot: retry from further back
                if t < start - 1e-6:
                    continue
                if t >= end:
                    return
                yield t, fr.to_ndarray(format="bgr24")
            else:
                return
    except av.error.FFmpegError:
        return
    finally:
        c.close()


def frames_at(path, times):
    """One BGR frame at (or just after) each time."""
    res = []
    for t in times:
        f = next(iter(frames_between(path, t, t + 1.0)), None)
        res.append(f[1] if f else None)
    return res


def audio_between(path, start, end, rate=48000):
    """Stereo float32 audio (n, 2) for [start, end) at `rate`; zeros if the recording has none."""
    import av
    n = int(round((end - start) * rate))
    buf = np.zeros((n, 2), np.float32)
    c, vs, t0 = _open(path)
    try:
        if not c.streams.audio:
            return buf
        st = c.streams.audio[0]
        rs = av.AudioResampler(format="flt", layout="stereo", rate=rate)
        try:
            c.seek(int((t0 + max(0.0, start - 1.5)) / vs.time_base), stream=vs, backward=True)
        except Exception:
            c.seek(0)
        for fr in c.decode(st):
            if fr.time is None:
                continue
            ft = fr.time - t0
            if ft >= end:
                break
            for r in rs.resample(fr):
                a = r.to_ndarray().reshape(-1, 2)
                i0 = int(round((ft - start) * rate))
                lo, hi = max(i0, 0), min(i0 + len(a), n)
                if hi > lo:
                    buf[lo:hi] = a[lo - i0:hi - i0]
                ft += len(a) / rate
    except av.error.FFmpegError:
        pass
    finally:
        c.close()
    return buf
