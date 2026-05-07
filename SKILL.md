---
name: clipify
description: Find compelling moments in a video — funny dialogue OR repeated impact actions like axe chops, hits, throws, drumbeats — cut them as standalone clips, optionally reformat 16:9 ↔ 9:16, time-warp pans for tighter reveals, and burn opus-style word-by-word captions. Use when the user mentions "clipify," "cut clips from this video," "make shorts from this," "find funny moments," "action montage," "cut on each chop/hit/punch," "reframe to 9:16," "vertical clips," or pastes a video file path and wants social-ready cuts.
---

# Clipify

Find compelling moments in a video, cut them as standalone clips, optionally reformat 16:9 → 9:16 (face-pan or split-screen), time-warp pans for tighter reveals, and burn opus-style word-by-word captions.

## Modes

Pick one before Step 1. The choice changes how you find moments and whether captions apply.

- **Dialogue mode** (default for podcasts, interviews, talking-heads): Whisper transcribes, you scan for punchlines / reactions / awkward pauses. → Step 1A. Captions in Step 5.
- **Action mode** (woodchopping, sports, percussion, drumming, anything with repeated impact sounds): skip Whisper entirely, run `detect_transients.py` to find each strike, cut on each one. → Step 1B. Skip Step 5; the strike sounds *are* the rhythm.
- **Hybrid**: dialogue mode for talking sections, action mode for the rest, intercut. Use both 1A and 1B.

If the user says "I'm not talking in this," you're in action mode. If they say "cut on each X" (chop, hit, punch, drumbeat, swing, footstep), you're in action mode. Default to dialogue mode otherwise.

## Inputs

- A video file path (the user will provide it; otherwise ask)
- Optional: requested format (9:16, 16:9, 1:1) — if not given, ask after candidates are picked
- Optional: subtitle style preference — if not given, ask before captioning

## Tooling (use only the fastest path)

- **Whisper:** `whisper --model tiny.en --word_timestamps True --output_format json` (≈10× faster than `small.en`; quality fine for English). For non-English: `--model base` (drop `--language`).
- **ffmpeg:** add `-hwaccel videotoolbox` for decode and `-preset ultrafast` for renders. Use `-c:v libx264 -crf 20` for the final master.
- **Numpy** for audio alignment (FFT cross-correlation). No scipy/cv2 needed.
- **Scripts:** `<skill-dir>/scripts/` (where `<skill-dir>` is the directory containing this SKILL.md — typically `~/.claude/skills/clipify/`)
  - `analyze.py` — speaker timeline from two ROI motion files
  - `build_pan.py` — ffmpeg crop x-expression with hard cuts
  - `build_ass.py` — opus-style ASS captions from whisper JSON
  - `audio_align.py` — find offset of a sub-clip in a longer source
  - `detect_transients.py` — find sharp impact sounds (action mode); see `--help`

Working dir: `/tmp/clipify/` (mkdir at start, leave artifacts for debugging).

---

## Workflow

### Step 1A — Find dialogue moments (dialogue mode)

```bash
mkdir -p /tmp/clipify
ffmpeg -y -hwaccel videotoolbox -i "$VIDEO" -vn -ac 1 -ar 16000 /tmp/clipify/audio.wav
whisper /tmp/clipify/audio.wav --model tiny.en --word_timestamps True --output_format json --output_dir /tmp/clipify --language en
```

Read the resulting JSON (or `.txt`) and pick 3–5 candidate clips. Funny signals to scan for:

- **Punchlines and reactions:** words like "what", "wait", "no way", laughter, "haha", swearing
- **Reversal moments:** setup question → unexpected answer
- **Awkward pauses:** Whisper segment with long gap, or filler ("uh", "um")
- **Self-roast / quotable one-liners:** short declarative sentences that stand alone
- **Audio peaks:** detect via `ffmpeg -af volumedetect` or look for rapid back-and-forth (alternating short Whisper segments)

For each candidate, propose: `[start, end, why-it's-funny, suggested title]`. Aim for 10–25s clips. Show the list and let the user confirm/pick.

### Step 1B — Find each strike (action mode)

Replace Whisper with audio-transient detection. The detector finds sharp impacts (axe-on-wood, fist-on-pad, drumhead, ball-on-bat, wood landing on a pile) by computing spectral flux on the 1–6 kHz band — the broadband impulse an impact creates that ambient/wind doesn't.

```bash
ffmpeg -y -hwaccel videotoolbox -i "$VIDEO" -vn -ac 1 -ar 16000 /tmp/clipify/audio.wav
python3 <skill-dir>/scripts/detect_transients.py /tmp/clipify/audio.wav \
  --min-flux 30 --min-gap 0.6 > /tmp/clipify/strikes.json
```

Tuning:

- `--min-flux 30` is the sane default. Real impacts register 50–300; ambient/wind sits at 5–15. Too many false positives → raise to 40–50. Too few hits → drop to 20.
- `--min-gap 0.6` (seconds) is the closest two strikes can be. Fast drumming may need 0.2; chopping is fine at 0.6–1.0.
- `--band 1000:6000` covers wood/metal/glass impacts. Heavy thuds (kick drum, body shots) live lower (`--band 200:2000`); whistles/clinks/snare cracks higher (`--band 4000:10000`).
- For multi-clip sources (a folder of phone clips), run the detector on each clip and pick a varied set across angles. Aim for 25–40 strikes for a 45–60s montage at ~0.9s per shot.

Each "shot" should start ~0.4s before the strike (showing wind-up) and end ~0.5s after (strike + brief follow-through). That's ~0.9s per beat.

### Step 1.5 — Verify each candidate is in frame

**Always do this before rendering**, in either mode. Audio detection finds the *sound* of an event; the camera might not have captured it. Skipping this is the #1 way to get user feedback like "you cut on chops where I'm not even visible."

```bash
# Sample one frame at each candidate strike time T:
for T in $STRIKE_TIMES; do
  ffmpeg -y -ss "$T" -i "$VIDEO" -frames:v 1 -vf scale=320:-1 \
    /tmp/clipify/verify_${T}.jpg
done
```

Read each verify image and drop the candidate if:

- The subject is bent down, off-frame, or behind an obstacle
- A thumb is on the lens (yes, this happens — and you only catch it visually)
- It's clearly a different sound source (door slam, dropped tool) that triggered the detector

For ~30 candidates this is one fast `ffmpeg` call each plus a single batch image read. Cheap insurance.

### Step 2 — Trim each chosen clip

```bash
ffmpeg -y -ss "$START" -t "$DURATION" -i "$VIDEO" -c copy /tmp/clipify/clip_$N.mp4
```

(Use `-c copy` for instant trim. Re-encode only if cuts must be frame-accurate.)

### Step 3 — Decide the output format

Ask the user (skip if they already specified): "9:16 (TikTok / Reels), 16:9 (YouTube), or 1:1 (Insta feed)?"

### Step 4 — If 16:9 → 9:16: pan-between-faces vs split-screen

Detect source aspect with `ffprobe`. If source is 16:9 and target is 9:16, ask:

> "Two options: **(a) hard-cut pan** that follows whoever is speaking (single face on screen at a time), or **(b) split-screen** stack with both faces visible. Which do you want?"

Skip the question if there's only one face (single-talker clip). For single-talker, just center-crop.

#### Step 4a — Pan-between-faces (recommended for fast-cut talking-head dialogue)

1. **Locate the two face ROIs.** Sample one frame: `ffmpeg -ss <middle> -i <clip> -frames:v 1 /tmp/clipify/probe.jpg`. Read it. Eyeball each face's mouth+chin area as `x,y,w,h` in the source's pixel space. (No cv2 needed — camera is static within a clip; one frame is enough.) Verify by drawing boxes:

   ```bash
   ffmpeg -i probe.jpg -vf "drawbox=x=$LX:y=$LY:w=$LW:h=$LH:color=cyan@0.9:t=4,drawbox=x=$RX:y=$RY:w=$RW:h=$RH:color=magenta@0.9:t=4" verify.jpg
   ```

   Iterate **at most twice**. Boxes should cover mouth + chin and avoid hands/mics. Don't over-tune — frame differencing is forgiving.

2. **Extract per-frame motion energy in each ROI:**

   ```bash
   ffmpeg -y -i clip.mp4 -filter_complex "
   [0:v]split=2[a][b];
   [a]crop=$LW:$LH:$LX:$LY,format=gray,tblend=all_mode=difference,signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG:file=/tmp/clipify/L.txt[la];
   [b]crop=$RW:$RH:$RX:$RY,format=gray,tblend=all_mode=difference,signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG:file=/tmp/clipify/R.txt[ra]
   " -map "[la]" -f null - -map "[ra]" -f null -
   ```

3. **Build speaker timeline** (min dwell 1.0s — short interjections merge into the prior speaker):

   ```bash
   python3 <skill-dir>/scripts/analyze.py /tmp/clipify/L.txt /tmp/clipify/R.txt 1.0 > /tmp/clipify/segments.json
   ```

4. **Pick pan x-coordinates** for a 9:16 vertical strip from the source. With source W=1920 and target W=1080, crop strip width = 608.
   - LEFT_X = `face_left_center_x - 304` (clamp ≥ 0)
   - RIGHT_X = `face_right_center_x - 304` (clamp ≤ source_W - 608)

5. **Generate the hard-cut x expression and render:**

   ```bash
   EXPR=$(python3 <skill-dir>/scripts/build_pan.py /tmp/clipify/segments.json $LEFT_X $RIGHT_X)
   ffmpeg -y -hwaccel videotoolbox -i clip.mp4 -filter_complex \
     "[0:v]crop=608:1080:x='$EXPR':y=0,scale=1080:1920:flags=lanczos[v]" \
     -map "[v]" -map 0:a -c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p \
     -c:a aac -b:a 192k /tmp/clipify/clip_panned.mp4
   ```

   Source 1920×1080 assumed; for 4K source either downscale first or double all coordinates.

#### Step 4b — Split-screen (both faces always visible)

Two stacked tiles, 1080×960 each. The active speaker's tile is on top — overlay flips at speaker changes.

```
[0:v]split=2[a0][a1];
[a0]crop=Wcrop:Hcrop:LX_tile:LY_tile,scale=1080:960,split=2[lt0][lt1];
[a1]crop=Wcrop:Hcrop:RX_tile:RY_tile,scale=1080:960,split=2[rt0][rt1];
[lt0][rt0]vstack[layoutL];
[rt1][lt1]vstack[layoutR];
[layoutL][layoutR]overlay=0:0:enable='<RIGHT_SPEAKER_ENABLE>'[v]
```

Build `<RIGHT_SPEAKER_ENABLE>` from `segments.json` as `between(t,a,b)+between(t,a,b)+...` over the right-speaker segments. Tile crops should target ~720×640 around each face (1.125:1 to match 1080×960).

### Step 4c — Time-warping reveals (optional)

When the user wants a slow scenic / pan / reveal shot tightened ("cut this in half") without losing the arc, speed-ramp instead of trimming. Trimming forces you to drop part of the arc; speed-ramping preserves all the beats at higher tempo.

```bash
# 2x speed: 12s arc → 6s output, audio pitch preserved via atempo
ffmpeg -y -ss "$START" -i "$CLIP" -t "$ORIG_DUR" \
  -vf "setpts=PTS/2,scale=1080:1920:flags=lanczos,fps=30" \
  -af "atempo=2.0" \
  -c:v libx264 -preset fast -crf 21 -pix_fmt yuv420p \
  -c:a aac -b:a 128k /tmp/clipify/clip_2x.mp4
```

Rules of thumb:

- **1.5x** — human movement that should feel "slightly brisk" without looking sped up
- **2x** — punchier reveal; still reads as natural
- **3x–4x** — time-lapse vibe (chain `atempo=2.0,atempo=2.0` for 4x; `atempo` accepts only 0.5–2.0 per filter instance)
- Drop `-af atempo` and mute the segment if the audio is just ambient/wind and the chipmunking would be distracting

Useful when the rest of the cut is rhythmic (chop montage, chat back-and-forth) and the reveal would otherwise feel like a dead spot.

### Step 5 — Add subtitles

Skip this step in action mode — the strike sounds are the rhythm and captions just clutter the visual.

Ask once (only if user hasn't already specified a style):

> "Three subtitle styles: **opus** (big bold white, yellow active-word highlight), **karaoke** (4-word chunks, green highlight), **minimal** (clean Helvetica, no highlight). Or paste an example you like."

If they paste a reference image/example: match the font, size, weight, color, position, and animation as closely as possible — write a custom ASS by hand or extend `build_ass.py`.

Else use the preset:

```bash
# Re-run whisper on the trimmed clip for accurate timestamps relative to clip start
whisper /tmp/clipify/clip_panned.mp4 --model tiny.en --word_timestamps True --output_format json --output_dir /tmp/clipify --language en
python3 <skill-dir>/scripts/build_ass.py /tmp/clipify/clip_panned.json /tmp/clipify/captions.ass opus
```

Burn captions:

```bash
ffmpeg -y -i /tmp/clipify/clip_panned.mp4 -vf "subtitles=/tmp/clipify/captions.ass" \
  -c:v libx264 -preset fast -crf 20 -c:a copy "$OUTPUT.mp4"
```

### Step 6 — Deliver

- Save each output to `<source_dir>/clipify_out/` (mkdir if missing)
- Print one line per clip: name, duration, what was funny, output path
- Open the first output with `open <path>` so the user can check it
- Offer to iterate (different style, different ROI, swap to split-screen, retime captions)

---

## Pitfalls (lessons from prior runs — don't repeat)

- **Audio detection ≠ visible event.** Always run Step 1.5 (verify each candidate frame) before rendering. The detector finds the *sound* of a chop, not whether the chopper is in frame. Hits where the subject is bent over, off-camera, or where a thumb is on the lens still trigger the audio detector. Catch them before rendering.
- **Spectral-flux band matters.** Default `--band 1000:6000` covers wood/metal/glass impacts. Heavy low thuds (kick drum, body shots) need `--band 200:2000`. Whistles, clinks, snare cracks need `--band 4000:10000`. If `--min-flux 30` returns nothing, try lowering to 15 first; if it returns thousands, try a different band before raising the threshold.
- **Speed-ramp audio in pairs.** `atempo` accepts only 0.5–2.0 in a single filter; for 4x chain `atempo=2.0,atempo=2.0`. Without `atempo`, `setpts` alone gives chipmunk audio.
- **Don't over-tune ROIs.** Two iterations max. Motion-diff is forgiving — wider ROIs covering mouth+chin work fine even if not perfectly mouth-centered.
- **Watch out for scene cuts inside a clip.** Run `ffmpeg -filter:v "select='gt(scene,0.3)',showinfo" -f null -` to count cuts. If a 16:9→9:16 clip has many cuts, the fixed face ROIs only work for the dominant scene; warn the user, and offer to either pick a single-take clip or accept off-center framing during cuts.
- **Source resolution matters.** If source is 4K, either downscale to 1920×1080 first (faster, fine for 9:16 output) or multiply all ROI/pan coordinates by 2.
- **Burned-in subtitles in source.** Some "raw" clips still have subtitles. If so, find the no-subs master via audio cross-correlation (`audio_align.py`) and trim from there.
- **Don't run whisper on the full feature-length source if a short clip suffices.** Whisper the trimmed clip after Step 2; only whisper the full source in Step 1 if you need a transcript to find funny moments.
- **State the plan in one line, then act.** Don't narrate every iteration.
