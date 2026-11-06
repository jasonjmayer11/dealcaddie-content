# dealcaddie-content

Makes one **Deal Verdict** reel twice a day with no one involved.

1. Takes the next Zillow listing from `queue.txt`
2. Opens dealcaddie.ai in a phone-sized browser, signs in with the content account, pastes the listing, and records the analysis
3. Pulls the numbers off the finished page (score, cashflow, CoC, cash to close, all strategies) and the listing photo
4. Builds a 1080×1920 MP4: house photo + hook → the paste → the reveal → proof → call to action. All text stays inside Instagram/TikTok's safe area.
5. Writes the caption and hashtags from the real numbers
6. Publishes it as a **GitHub Release**: caption in the notes, MP4 and cover image attached

## Reviewing on your phone
GitHub app → this repo → **Releases**. Each one has the caption ready to copy and the MP4 to download.

## Day-to-day controls
| You want to… | Do this |
|---|---|
| Run one right now | Actions → *Daily Deal Verdict reel* → **Run workflow** (paste a Zillow URL to override the queue) |
| Add listings | Paste Zillow URLs into `queue.txt`, one per line |
| See what ran | `done.csv` (and `failed.txt` for anything that broke) |
| Pause it | Actions → workflow → **⋯ → Disable workflow** |
| Change times | Edit the two `cron:` lines in `.github/workflows/daily-reel.yml` (UTC) |

## Secrets (Settings → Secrets and variables → Actions)
- `DC_EMAIL` — content account email
- `DC_PASSWORD` — content account password

Without them it runs as a guest and stops at the free-analysis limit.

## Files
- `scripts/record.js` — runs the analysis, captures high-res stills of each card + scrapes the numbers (Playwright)
- `scripts/assemble.py` — copy rules, five one-idea beats, slow push-in + crossfades, caption
- `fonts/` — Poppins (SIL Open Font License)

## Copy rules (in `assemble.py → pick_copy`)
- LTR cashflow ≥ $200/mo → "This $150K Indianapolis house. Guess the cashflow."
- Negative LTR → "Looks like a deal. Watch." then the strategy that does work, if one does
- In between → "Does it cash flow?" → "Barely."
