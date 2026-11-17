# AUTO REEL AI

Topic -> Gemini script -> Pixabay stock visuals -> narration -> captions, music, transitions -> 9:16 MP4,
with a review dashboard and manual approval. Runs on GitHub Actions and is controlled from any browser.

**Honest scope:** this assembles stock footage/images, typography and synthetic narration into a Reel.
It does not generate AI video. Nothing is ever posted to Instagram automatically.

## First-time setup

1. The application source has been extracted into this repository.
2. In **Settings -> Secrets and variables -> Actions**, confirm these repository secrets exist:
   - `GEMINI_API_KEY`
   - `PIXABAY_API_KEY`
3. Enable the dashboard: **Settings -> Pages -> Build and deployment -> Deploy from a branch**.
   Select branch `main`, folder `/docs`, then Save.
4. Open **Actions -> Studio -> Run workflow**. Choose `generate`, enter a topic, and select duration and style.
5. When the run finishes, open the dashboard:
   `https://manjunathjadav360-rgb.github.io/Auto-reel-ai./`

## Dashboard controls

The dashboard lists generated projects, their quality checks, captions and release assets. A project must pass
quality checks and be manually approved before it is marked approved. Approval does not publish to Instagram.
Download the MP4 and post it yourself.

To start runs and approve videos directly from the dashboard, create a fine-grained GitHub token for this
repository only, permission **Actions: Read and write**, with an expiry date, and paste it in the dashboard
Settings. It is stored only in that browser. Without a token, the dashboard is read-only and links to GitHub.

## Limits and safety

- **No AI video generation:** scenes use stock footage/images and typography cards.
- **Gemini free tier:** limits change. Free-tier prompts may be used by Google to improve its models; do not
  submit confidential topics.
- **Pixabay:** respect its licence and avoid misleading endorsements involving recognisable people or brands.
- **GitHub Releases:** videos stored in Releases are public while the repository is public. Delete releases
  you no longer want available.
- **Voice:** Piper is preferred; if unavailable, the workflow falls back to eSpeak NG, which sounds robotic.
  Check each Piper voice's licence before commercial use.
- **Music:** generated ambient music is original but modest. Files in `assets/music/` are user-supplied and
  flagged as rights-unverified.
- **Captions:** timing is estimated per scene, not aligned word-by-word.
- **Instagram:** no automatic posting is implemented.

## Commands (desktop)

```bash
pip install -r requirements.txt
python -m src.autoreel doctor
python -m src.autoreel research --category educational
python -m src.autoreel generate --topic "Why tides happen twice a day" --duration 30 --style educational
python -m src.autoreel set-status --id <project-id> --decision approve
python -m unittest discover -s tests -t .
node --test docs/test_lib.js
```

Local runs need `GEMINI_API_KEY` and `PIXABAY_API_KEY` in the environment (see `.env.example`).

## Layout

- `src/media/`: stock-media providers and Pixabay integration
- `src/safehttp.py`: redirect-safe HTTP transport
- `src/autoreel/`: generation pipeline
- `docs/`: review dashboard and project history
- `tests/`: automated tests
