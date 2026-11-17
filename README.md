# AUTO REEL AI

Topic -> Gemini script -> Pixabay stock visuals -> narration -> captions, music, transitions -> 9:16 MP4,
with a review dashboard and manual approval. Runs on GitHub Actions (free); controlled from any browser.

**Honest scope:** this assembles stock footage/images, typography and synthetic narration into a Reel.
It does not generate AI video. Nothing is ever posted to Instagram automatically.

## Setup (Android-friendly, about 15 minutes)

1. **Unpack helper.** In the repo: Add file > Create new file. Name it `.github/workflows/unpack.yml`
   (typing the slashes makes the folders). Paste the contents of `unpack.yml`. Commit.
2. **Upload the app.** Add file > Upload files > choose `autoreel-app.zip`. Commit.
3. **Unpack.** Actions tab > "Unpack" > Run workflow. Wait for the green tick.
4. **Studio workflow.** Create `.github/workflows/studio.yml` the same way (paste `studio.yml`). Optional: also `ci.yml` (runs the tests on every change).
5. **Dashboard.** Settings > Pages > Source "Deploy from a branch" > branch `main`, folder `/docs` > Save.
   Your dashboard: `https://<your-username>.github.io/Auto-reel-ai/`
6. **Secrets** (already done): `GEMINI_API_KEY`, `PIXABAY_API_KEY`.
7. **Make a video.** Actions > Studio > Run workflow > action `generate`, type a topic. Takes roughly 5-15 minutes.
   Then open the dashboard > Review.

Optional, to start runs and approve from the dashboard itself: Settings page > create a *fine-grained*
GitHub token for this repository only, permission **Actions: Read and write**, with an expiry date, and paste it in the
dashboard Settings. It is stored only in that browser. Without it the dashboard is read-only and links you to GitHub.

## Limits you should know

- **Gemini free tier:** limited requests per minute/day per project; limits change. The app retries, then falls back to the next model in `GEMINI_MODELS`. Free-tier prompts may be used by Google to improve its models: do not put confidential topics in.
- **Pixabay:** 100 requests/minute, responses cached 24h, no mass downloads (the app downloads about one clip per scene). Check the Pixabay licence summary before using clips with recognisable people or brands in anything that looks like an ad.
- **GitHub Actions:** free minutes are limited for private repos; public repos are generous. Videos are stored as Release files, which are **public** in a public repo until you delete the release.
- **Voice:** Piper is preferred; if it cannot be installed the run falls back to eSpeak NG (robotic). Piper voice licences differ per voice: read the model card before commercial use.
- **Music:** synthesised ambient pads (original, no third-party rights, modest quality). Files you put in `assets/music/` are used instead, and are flagged "rights unverified".
- **Captions:** timing is estimated from each scene's audio length, not word-level alignment.
- Scheduled workflows are disabled by GitHub after 60 days without repository activity.

## Commands (desktop)

```
pip install -r requirements.txt            # plus ffmpeg and espeak-ng or piper-tts
python -m src.autoreel doctor
python -m src.autoreel research --category educational
python -m src.autoreel generate --topic "Why tides happen twice a day" --duration 30 --style educational
python -m src.autoreel set-status --id <project-id> --decision approve
python -m unittest discover -s tests -t . ; node --test docs/test_lib.js
```
Local runs need `GEMINI_API_KEY` and `PIXABAY_API_KEY` in your environment (see `.env.example`). Output: `output/<id>/`.

## Layout
`src/media/` stock-media providers (Pixabay; add others in `manager.py`) · `src/safehttp.py` redirect-safe HTTP ·
`src/autoreel/` pipeline stages · `docs/` dashboard + `docs/data/` history · `tests/`
