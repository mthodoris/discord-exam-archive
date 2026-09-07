# discord-exam-archive

A browsable, searchable archive of exam PDFs/images that students shared
in a Discord server, published as a static site on GitHub Pages.

Live site (once Pages is enabled — see below):
`https://<your-username>.github.io/discord-exam-archive/exams/`

## How it works

Each course already has its own Discord channel, so **the channel name
is the source of truth for subject/course** — no fragile text parsing
needed there. The sorting script only has to guess **year / term /
exam type** from the message text, and falls back to the message's
upload date when the text doesn't say (e.g. just "here's the exam" with
no date).

```
discord-exam-archive/
├── scripts/
│   ├── sort_exams.py   # parses exports, sorts files, writes index.json
│   └── config.json     # editable keyword/mapping rules (see below)
├── exams/               # <- published by GitHub Pages
│   ├── index.html       # the site
│   ├── styles.css
│   ├── app.js
│   ├── index.json       # generated: metadata for every file
│   ├── Math101/
│   │   └── 2023-Spring-final-final_exam.pdf
│   └── Physics201/
│       └── ...
└── README.md
```

## Re-running the sorter for new Discord history

1. **Export from Discord** using [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter).
   Export **one JSON file per course channel**, and turn on asset
   downloading so attachments are saved to disk (not just linked by
   CDN URL, which expires). Keep exporting into the *same* folder each
   time — e.g. all of your `math101.json`, `physics201.json`, etc. side
   by side in one `export/` folder — since the sorter re-scans every
   file in that folder on each run.

2. **Run the script:**

   ```bash
   cd discord-exam-archive
   python3 scripts/sort_exams.py \
     --export /path/to/export \
     --assets /path/to/downloaded/assets \
     --output exams \
     --config scripts/config.json
   ```

   - `--export` can be a single `messages.json` file or a directory of
     several (one per channel) — point it at the whole export folder
     if you have more than one channel.
   - `--assets` should point at wherever DiscordChatExporter saved the
     actual attachment files; the script searches it recursively and
     matches by filename.
   - Add `--dry-run` first to preview what would happen (logs warnings
     for anything it can't match) without copying files or touching
     `index.json`.

3. **Review the output.** The script logs a warning for every
   attachment it couldn't find on disk (`missing_file` in
   `index.json`'s `"missing"` list) — usually means `--assets` is
   pointed at the wrong folder, or that particular file wasn't
   downloaded.

4. **Commit and push.** `exams/` (including `index.json` and the
   sorted files) is what GitHub Pages actually serves, so it needs to
   be committed like any other file in the repo:

   ```bash
   git add exams/
   git commit -m "Add exams from <date> export"
   git push
   ```

The script is **safe to re-run** at any point:
- Running it again with the same export doesn't create duplicate
  files or index entries — files are matched and updated by a stable
  key (Discord message id + filename).
- Running it against just one newly-exported channel merges into the
  existing `exams/index.json` rather than replacing it, so other
  channels you'd already sorted stay in the index.

## Tuning auto-categorization (`scripts/config.json`)

Since course/subject already comes from the channel name, this file
only controls how **year / term / exam type** are read out of the
message text. Edit it freely and re-run the script — no code changes
needed:

- **`subject_overrides`** — map an ugly channel name to a nicer display
  name, e.g. `"math101-2023": "Mathematics 101"`. Any channel not
  listed here just uses its own name, title-cased.
- **`channel_ignore_list`** — channel names to skip entirely
  (announcements, off-topic, etc.).
- **`month_term_map`** — maps a month number (1–12) to a term/semester
  label. The month is read from the message text if a month name or
  `MM/YYYY` appears in it, otherwise it falls back to the message's
  upload month. Edit the labels to match your institution's calendar
  (e.g. swap "Fall"/"Spring" for "Winter"/"Summer" terms, or add a
  dedicated resit-period label).
- **`exam_type_keywords`** — maps an exam type (`final`, `midterm`,
  `resit`, `quiz`, `lab`, `oral`, ...) to a list of keywords/aliases
  matched case-insensitively against the message text (first match
  wins). Add other languages or phrasings your students actually use.
- **`default_exam_type`** — used when no keyword matches (defaults to
  `"exam"`).
- **`year_regex`** — the regex used to pull a 4-digit year out of the
  message text; falls back to the message's upload year when it
  doesn't match.

Every file in `index.json` also records *where* each field came from
(`year_source`, `term_source`, `exam_type_source` — either `"text"`,
`"timestamp"`, or `"default"`), so you can spot-check which files were
guessed from the upload date rather than read from the message itself.

## The site (`exams/index.html`)

Plain HTML/CSS/JS, no build step, no dependencies. It fetches
`index.json` (relative to itself) and renders a searchable, filterable
list:

- Text search matches filename, subject, exam type, and message text.
- Dropdowns filter by subject, year, and exam type.
- PDFs show a document icon; images render as a thumbnail. Everything
  links straight to the file.

Because it's plain `fetch()`, opening `index.html` directly from disk
(`file://`) won't work — browsers block that request. Test locally
with a simple server instead:

```bash
cd exams
python3 -m http.server 8000
# open http://localhost:8000
```

## Deploying / updating GitHub Pages

One-time setup:

1. On GitHub, go to the repo's **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to "Deploy from a
   branch", branch `main`, folder `/ (root)`.
3. Save. GitHub will publish the whole repo; the archive itself is
   reachable at `https://<your-username>.github.io/discord-exam-archive/exams/`
   (kept under `/exams` rather than the repo root, since that's also
   where the sorter writes the categorized files and `index.json`).

After that, **every push to `main` that touches `exams/` redeploys the
site automatically** — there's nothing else to run. Updating the
archive is just: re-run the sorter (above), review the diff, commit,
and push.
