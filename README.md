# secjobs — private, on-device cybersecurity job-application assistant

Scans 20 Lever job boards for cybersecurity roles, tailors your resume and cover
letter for each one with a **local** model (Ollama), fills the Lever application
in your own browser, and keeps a ledger so nothing is ever applied to twice.

Nothing leaves your machine except the application you submit to the employer.
No cloud LLM, no third-party service.

## How submission works (read this)

The tool fills the entire form — resume upload, cover letter, EEO, custom
questions — then **pauses for you to press Submit**. It auto-detects the
thank-you page and marks the job `applied`. This is deliberate:

* Lever applications are behind hCaptcha and Lever's terms prohibit bot
  submissions; ATS vendors flag and discard automated applicants.
* A tailored resume the model wrote should be glanced at before it goes out
  under your name. `REVIEW_FLAGS.txt` in each output folder lists any term the
  model used that is **not** in your master resume.

If a form has a required question with no configured answer, the tool does
**not** submit, marks it `needs_input`, and emails you the question and link.

## Applying: two modes

**Mode A — userscript in your normal Chrome (recommended).** Lever uses an
invisible hCaptcha that rejects automated browsers with "There was an error
verifying your application". So the reliable path fills the form *inside your
everyday Chrome*, where nothing is automated:

1. Install the Tampermonkey extension in Chrome.
2. Open `userscript/secjobs-lever.user.js` in Tampermonkey (Dashboard →
   Utilities → Import from file, or drag the file onto the Tampermonkey tab)
   and enable it.
3. In PowerShell: `secjobs serve` (leave it running).
4. `secjobs review` → open any listed job's apply URL in Chrome → a small
   "secjobs" panel appears bottom-right → click **Fill from secjobs**.
   It uploads the tailored resume, pastes the cover letter, sets EEO and
   answers custom questions. Unanswered required questions are listed in the
   panel. Review, click Lever's Submit. The thank-you page is detected and the
   job is marked `applied` automatically (or click **Mark applied**).

**Mode B — attach to your own Chrome (no extension needed).**

```powershell
secjobs chrome                 # starts Chrome with a debugging port; leave it open
secjobs apply --id <id>        # attaches to that Chrome, fills the form, waits for you
```

Chrome started by `secjobs chrome` is not marked as automated, so hCaptcha
treats it as a normal browser. If you run `secjobs apply` without it, the tool
launches its own browser, which Lever's hCaptcha usually rejects.

## Setup

```bash
git clone <this repo> secjobs && cd secjobs
./setup.sh                      # venv, deps, chromium, pulls the Ollama model
```

Then:

1. `data/resume.md` — your master resume in Markdown (see `resume.example.md`). Tailoring only
   ever re-orders/trims this; it cannot add anything that isn't here.
2. `config/candidate.yaml` — copy from `candidate.example.yaml` and fill in your
   contact details, EEO choices and the `answers:` list for custom questions.
3. `.env` — SMTP app password for the fallback email (optional but recommended).
4. `config/settings.yaml` — model name; set `location_keywords` if you only want
   US/remote roles.

## Use

```bash
secjobs scan       # pull all boards, keep cyber roles, record new ones
secjobs generate   # tailor resume + cover letter for each new role (local LLM)
secjobs review     # table of generated apps + fabrication flags per job
secjobs apply      # opens browser, fills each form, waits for your Submit
secjobs drop       # mark job(s) skipped so they're never applied to
secjobs status     # full ledger
secjobs run        # scan -> generate -> review (stops before applying)
```

### Choosing what to apply to

```bash
secjobs review                        # see ids, titles, flag counts
secjobs apply --clean-only            # only jobs with ZERO review flags
secjobs apply --id b928814b           # one specific job
secjobs apply --company zoox          # one company
secjobs apply --title "cloud security"
secjobs apply --clean-only --company aprio --limit 3
secjobs drop --id b928814b            # never apply to this one
```

`apply` lists what it's about to open and asks for confirmation; `--yes` skips that.
Filters combine (they AND together).

Run `secjobs run` daily (cron / Task Scheduler); the ledger
(`data/applications.db`) guarantees a posting ID is never processed twice.

## Output layout

```
output/<company>/<role>-<id>/
  posting.txt        raw job description
  resume.md / .pdf   tailored resume (PDF is what gets uploaded)
  cover_letter.txt   pasted into "Additional information"
  REVIEW_FLAGS.txt   terms not found in your master resume -> verify
  form_filled.png    screenshot of the filled form
```

## Statuses

`discovered` → `generated` → `applied` | `needs_input` | `skipped`

Reset a job: `sqlite3 data/applications.db "update applications set status='discovered' where posting_id='...'"`

## Tuning the model

`llama3.1:8b` is fast on a laptop. For better writing use `qwen2.5:14b` or
`mistral-nemo` (needs ~10–16 GB RAM/VRAM). Lower `temperature` for more
conservative resumes.

## Notes / limits

* Lever's public postings API (`api.lever.co/v0/postings/<slug>`) is used for
  discovery — read-only, no auth, no scraping.
* Lever sometimes overwrites name/email after parsing the uploaded resume; the
  tool re-fills them.
* Custom-question matching is keyword based. When you hit `needs_input`, add a
  new `answers:` entry and rerun `secjobs apply`.
