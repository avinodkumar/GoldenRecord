# Pitch video

Builds the narrated pitch video (about 6 minutes, 1080p, burned-in captions) from real captures.

1. Start the dev harness from clean: `docker compose down -v && docker compose up -d`
2. `PYTHONPATH=src python video/capture.py` drives the live system and saves frames to `video/out/frames`
   (then `python video/ablation_frame.py` for the measured-comparison frame)
3. Render the deck PDF pages into frames (`slide_01.png` …) and the architecture PNG (`arch.png`)
4. `python video/build.py` generates narration (edge-tts, en-US-AndrewNeural), captions and the MP4

`script.yaml` holds the narration and visuals per segment. To use Fabric footage instead of the harness, put the
Fabric screenshot in `video/out/frames` and change the segment's `file` (and drop `live: true`).
Requires ffmpeg (`winget install Gyan.FFmpeg`), `pip install edge-tts playwright pymupdf`, `playwright install chromium`.
