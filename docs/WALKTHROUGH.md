# Walkthrough recording

The 80.84-second video shows a real browser session against the local application using the fictional commerce fixture. Captions were overlaid while recording; they are also available as WebVTT. No model response or analysis outcome was mocked for this recording.

- [Browser-friendly MP4](https://raw.githubusercontent.com/ngyathin16/queryproof/main/docs/walkthrough.mp4)
- [Original Playwright WebM](walkthrough.webm)
- [Caption file](walkthrough.vtt)
- [Capture metadata](walkthrough-capture.json)

To recreate the original recording, start the app, then run `npm run walkthrough` in `ui/`. It creates real review records, so use a separate server data directory when recording.

The MP4 is an H.264, yuv420p transcode of the original recording, with captions preserved in the video pixels. It uses a fast-start container so playback can begin before the full download. Conversion was performed with the FFmpeg binary distributed by `imageio-ffmpeg` in a temporary tool environment; this package is not a runtime application dependency.

Equivalent command with FFmpeg installed:

```sh
ffmpeg -i docs/walkthrough.webm -c:v libx264 -threads 2 -preset fast -crf 23 -pix_fmt yuv420p -movflags +faststart docs/walkthrough.mp4
```

The MP4 was decoded and its frame at 39 seconds inspected after conversion. The video is a recorded walkthrough, not an interactive hosted backend or evidence of human usability testing.
