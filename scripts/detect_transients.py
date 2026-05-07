#!/usr/bin/env python3
"""Detect sharp audio transients (impacts, hits, claps) via spectral flux on a chosen freq band.

Use for action montages where you want to cut on each strike: axe-on-wood, drum
hit, fist-on-pad, ball-on-bat, wood landing on a pile, etc. The detector finds
the broadband impulse that an impact creates, which ambient noise/wind doesn't.

Usage:
    python3 detect_transients.py audio.wav [--band 1000:6000] \
        [--min-flux 30] [--min-gap 0.6] [--top N]

Output: JSON list of {time, flux, db}, sorted by time, to stdout.

Tuning notes:
- min-flux 30 is a sane default. Real impacts register 50–300; ambient ~5–15.
  Too many false positives → raise to 40–50. Too few → drop to 20.
- min-gap is min seconds between accepted peaks. Drumming: ~0.2; chopping: 0.6–1.0.
- band: 1000:6000 covers axe/wood/metal impacts. Heavy thuds (kick, body shot)
  live lower (200:2000). Whistles, clinks, snare cracks live higher (4000:10000).
"""
import sys, json, wave, argparse
import numpy as np


def detect(path, band_lo=1000, band_hi=6000, min_flux=30.0, min_gap=0.6):
    w = wave.open(path, 'rb')
    sr = w.getframerate()
    n = w.getnframes()
    data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    w.close()

    win_size = int(sr * 0.025)  # 25 ms windows
    hop = int(sr * 0.01)        # 10 ms hop
    n_frames = (len(data) - win_size) // hop
    if n_frames < 4:
        return []
    frames = np.lib.stride_tricks.as_strided(
        data,
        shape=(n_frames, win_size),
        strides=(data.strides[0] * hop, data.strides[0]),
    )
    spec = np.abs(np.fft.rfft(frames * np.hanning(win_size), axis=1))

    bin_lo = max(1, int(band_lo * win_size / sr))
    bin_hi = min(spec.shape[1], int(band_hi * win_size / sr))
    diff = np.diff(spec[:, bin_lo:bin_hi], axis=0)
    flux = np.sum(np.maximum(diff, 0), axis=1)
    times = (np.arange(len(flux)) + 1) * hop / sr

    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-10)
    db = 20 * np.log10(rms + 1e-10)

    min_gap_frames = max(1, int(min_gap * sr / hop))
    peaks = []
    last = -min_gap_frames
    for i in range(2, len(flux) - 2):
        if flux[i] < min_flux:
            continue
        if flux[i] != np.max(flux[max(0, i - 3):i + 4]):
            continue
        rec = {
            'time': round(float(times[i]), 3),
            'flux': float(flux[i]),
            'db': round(float(db[i]), 1) if i < len(db) else 0.0,
        }
        if i - last < min_gap_frames:
            if peaks and rec['flux'] > peaks[-1]['flux']:
                peaks[-1] = rec
                last = i
            continue
        peaks.append(rec)
        last = i
    return peaks


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('audio_wav')
    p.add_argument('--band', default='1000:6000', help='freq band Hz, "lo:hi"')
    p.add_argument('--min-flux', type=float, default=30.0)
    p.add_argument('--min-gap', type=float, default=0.6,
                   help='min seconds between accepted peaks')
    p.add_argument('--top', type=int, default=0,
                   help='keep only N strongest peaks (0 = all)')
    args = p.parse_args()

    lo, hi = (int(x) for x in args.band.split(':'))
    peaks = detect(args.audio_wav, lo, hi, args.min_flux, args.min_gap)
    if args.top:
        peaks = sorted(peaks, key=lambda x: -x['flux'])[:args.top]
        peaks.sort(key=lambda x: x['time'])
    json.dump(peaks, sys.stdout, indent=2)
    sys.stdout.write('\n')
