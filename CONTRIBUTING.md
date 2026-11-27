# Contributing

Thanks for helping. A few ground rules keep this project useful and legal.

## Never commit
- **Novel text** (EPUBs, chapter dumps, answer keys built from the book).
- **Audio of the book** or voice clips you do not own.
- **Model weights** or API keys.

The `.gitignore` already excludes `data/`, `models/` and the usual suspects; please check `git status` before you commit.

## Development

```powershell
pip install -r requirements.txt -r requirements-dev.txt
pytest                                  # backend: no GPU needed
cd ui; npm install; npm test; npm run typecheck
```

- **Python:** small, focused functions; comments explain *why*. Files approaching 500 lines are candidates for a split.
- **Tests first for behaviour changes.** Speech engines and language models are stubbed in tests, so the suite runs anywhere.
- **Labelling changes need numbers.** If you change attribution or emotion logic, run `scripts/label_eval.py` against your own answer keys and include before/after figures in the pull request.

## Pull requests
1. Branch from `master`.
2. Keep one concern per pull request.
3. Describe what you measured or tested by hand. CI runs the Python and UI suites.

## Reporting a bug
Open an issue with: your GPU and driver, the command or button you used, the relevant part of `logs/` or `data/pipeline.log`, and what you expected to hear.
