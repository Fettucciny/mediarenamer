# mediarenamer

An evidence-based media renamer, designed from a study of where FileBot's matcher fails.

Design principles:

1. **The parent folder is a title source.** Files like `Severance/01.mkv` inherit the folder as the series title, and the whole folder is matched as one batch. Structural folders (`Season 1`, `Downloads`, temp names) are never used as search terms.
2. **Bare episode numbers are first-class.** `01.mkv` or `Show - 01.mkv` is matched by checking the batch of numbers against each candidate season's episode count (cardinality fit), not by assuming anime absolute numbering.
3. **Years are soft evidence collected anywhere.** Any plausible year token in the name or path supports or penalizes candidates. A missing year lowers confidence so the pick needs review, instead of silently falling back to popularity.
4. **IDs are evidence, not verdicts.** `{tvdb-123}` tags and sibling NFO files are validated against name and year evidence. A contradiction flags the file for review instead of silently winning.
5. **Every decision is explained.** Each file gets a confidence and a trace. Nothing is dropped silently; `-v` shows why.

## Usage

```
python -m mediarenamer match  <path> [-r] [-v] [--kind tv|movie|auto] [--season N]
python -m mediarenamer apply  <path> [-r] [--yes] [--accept-review]
python -m mediarenamer undo
```

`match` is always a dry run. `apply` performs renames and journals them for `undo`.

Data sources: TVmaze for TV (no API key needed), TMDb for movies
(set `TMDB_API_KEY`; free key from https://www.themoviedb.org/settings/api).
