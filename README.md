# mediarenamer

An evidence-based media renamer, designed from a study of where FileBot's matcher fails.

Design principles:

1. **The parent folder is a title source.** Files like `Severance/01.mkv` inherit the folder as the series title, and the whole folder is matched as one batch. Structural folders (`Season 1`, `Downloads`, temp names) are never used as search terms.
2. **Bare episode numbers are first-class.** `01.mkv` or `Show - 01.mkv` is matched by checking the batch of numbers against each candidate season's episode count (cardinality fit), not by assuming anime absolute numbering.
3. **Years are soft evidence collected anywhere.** Any plausible year token in the name or path supports or penalizes candidates. A missing year lowers confidence so the pick needs review, instead of silently falling back to popularity.
4. **IDs are evidence, not verdicts.** `{tvdb-123}` tags and sibling NFO files are validated against name and year evidence. A contradiction flags the file for review instead of silently winning.
5. **Every decision is explained.** Each file gets a confidence and a trace. Nothing is dropped silently; `-v` shows why.

6. **Anime is its own domain.** Fansub-style names (`[Group] Title - 05 [CRC]`, CJK
   titles, `2nd Season`) route to AniList, which knows the aliases that
   general TV databases miss. Each AniList season is one entry linked by
   sequel relations; an episode number larger than the entry walks that chain,
   so `Jujutsu Kaisen - 30` becomes S02E06 with the reasoning shown.

7. **Chinese, Japanese and Korean conventions are native.** `第01集`, `第2季`,
   `第二季`, `1화`, `시즌2`, `第1話`, `#01`, `2期`, full-width brackets and
   `【site】` watermarks, glued tags like `1080P国语中字`, sequel digits such as
   `庆余年2` meaning season 2, and `Season 2` / `第2季` folders all parse. CJK
   titles search TMDb first, which carries original and alternative titles,
   with TVmaze as the second opinion; Latin titles do the reverse.

## Usage

```
python -m mediarenamer match  <path> [-r] [-v] [--kind tv|movie|auto] [--season N]
python -m mediarenamer apply  <path> [-r] [--yes] [--accept-review]
python -m mediarenamer undo
```

`match` is always a dry run. `apply` performs renames and journals them for `undo`.

Data sources: TVmaze for TV and AniList for anime (no API key needed),
Jikan for anime episode titles (optional, skipped when unreachable), TMDb for
movies (set `TMDB_API_KEY`; free key from https://www.themoviedb.org/settings/api).
