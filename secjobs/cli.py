import argparse, re, sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
from . import config
from .lever import fetch_postings, Posting
from .filters import is_cyber_role
from .llm import Ollama
from .generate import generate_for, out_dir
from .config import OUTPUT_DIR
from .tracker import Tracker
from .apply import run_apply
from .serve import serve
from .chrome import launch as launch_chrome

con = Console()


def _llm() -> Ollama:
    o = config.settings()["ollama"]
    llm = Ollama(o["host"], o["model"], o.get("temperature", 0.3), o.get("num_ctx", 16384))
    llm.check()
    return llm


def cmd_scan(args):
    """Fetch every board, keep cybersecurity postings, record new ones as 'discovered'."""
    s, tr = config.settings(), Tracker()
    new, seen = [], 0
    for slug in config.companies():
        try:
            postings = fetch_postings(slug)
        except Exception as e:
            con.print(f"[red]{slug}: {e}[/red]"); continue
        for p in postings:
            ok, why = is_cyber_role(p, s["filter"])
            if not ok:
                continue
            seen += 1
            if tr.status(p.id) is None:
                tr.upsert(p.id, p.company, p.title, p.apply_url, "discovered", why)
                new.append(p)
        con.print(f"{slug:22s} {len(postings):4d} postings")
    con.print(f"\n[bold]{seen}[/bold] cyber roles across boards, [bold green]{len(new)}[/bold green] new.")
    for p in new:
        con.print(f"  + {p.company:18s} {p.title} — {p.location}", markup=False)


def _load_posting(row) -> Posting | None:
    for p in fetch_postings(row["company"]):
        if p.id == row["posting_id"]:
            return p
    return None


def cmd_generate(args):
    """Tailor resume + cover letter for every 'discovered' posting."""
    tr, cand, master = Tracker(), config.candidate(), config.master_resume()
    llm = _llm()
    rows = tr.by_status("discovered")
    if args.limit: rows = rows[: args.limit]
    if not rows:
        con.print("Nothing to generate. Run `scan` first."); return
    cache: dict[str, list[Posting]] = {}
    for row in rows:
        cache.setdefault(row["company"], fetch_postings(row["company"]))
        p = next((x for x in cache[row["company"]] if x.id == row["posting_id"]), None)
        if not p:
            tr.set_status(row["posting_id"], "skipped", "posting no longer listed"); continue
        con.print(f"{p.company:18s} {p.title} ... ", end="", markup=False)
        r = generate_for(p, master, cand, llm)
        tr.set_status(p.id, "generated", f"{len(r['flags'])} review flags")
        con.print(f"done -> {r['dir'].relative_to(config.ROOT)}"
                  + (f"  [yellow]⚠ {len(r['flags'])} unverified terms, see REVIEW_FLAGS.txt[/yellow]" if r['flags'] else ""))


def _flag_count(row) -> int:
    m = re.match(r"(\d+) review flags", row["notes"] or "")
    return int(m.group(1)) if m else 0


def cmd_apply(args):
    """Open each selected 'generated' posting in a browser, fill it, wait for your Submit."""
    tr, cand, s = Tracker(), config.candidate(), config.settings()
    # Jobs parked as needs_input are retried when you ask for them explicitly
    # (by --id/--title/--company) or with --retry, since you've presumably just
    # added the missing answer to candidate.yaml.
    statuses = ["generated"]
    if args.retry or args.id or args.title or args.company:
        statuses.append("needs_input")
    rows = list(tr.by_status(*statuses))

    if args.company:
        rows = [r for r in rows if r["company"].lower() == args.company.lower()]
    if args.title:
        rows = [r for r in rows if args.title.lower() in r["title"].lower()]
    if args.id:
        rows = [r for r in rows if r["posting_id"].startswith(args.id)]
    if args.clean_only:
        rows = [r for r in rows if r["status"] == "needs_input" or _flag_count(r) == 0]
    if args.limit:
        rows = rows[: args.limit]

    if not rows:
        con.print("Nothing matched. Try `secjobs review` to see what's available,")
        con.print("or `secjobs apply --retry` to re-attempt jobs marked needs_input."); return

    batch, cache = [], {}
    for row in rows:
        cache.setdefault(row["company"], fetch_postings(row["company"]))
        p = next((x for x in cache[row["company"]] if x.id == row["posting_id"]), None)
        if not p:
            tr.set_status(row["posting_id"], "skipped", "posting closed"); continue
        d = out_dir(p)
        if not (d / "resume.pdf").exists():
            tr.set_status(p.id, "discovered", "artifacts missing; regenerate"); continue
        batch.append((p, d))

    if not batch:
        con.print("Nothing to apply to."); return

    con.print(f"\n[bold]About to open {len(batch)} application(s):[/bold]")
    for p, _ in batch:
        st = tr.status(p.id)
        con.print(f"  - {p.company} | {p.title}" + (f"   (retry: {st})" if st == "needs_input" else ""),
                  markup=False)
    if not args.yes:
        if input("\nProceed? [y/N] ").strip().lower() not in ("y", "yes"):
            con.print("Cancelled."); return

    run_apply(batch, cand, s, tr)


def cmd_review(args):
    """List generated applications and their fabrication-check flags."""
    tr = Tracker()
    rows = tr.by_status("generated", "needs_input")
    if not rows:
        con.print("Nothing generated yet."); return
    t = Table(title="Ready to apply")
    for c in ("id", "status", "company", "title", "flags", "flagged terms / blockers"):
        t.add_column(c)
    for r in rows:
        n = _flag_count(r)
        d = OUTPUT_DIR / r["company"]
        terms = ""
        hits = list(d.glob(f"*{r['posting_id'][:8]}/REVIEW_FLAGS.txt")) if d.exists() else []
        if hits:
            lines = [l for l in hits[0].read_text(encoding="utf-8").splitlines()[1:] if l.strip() and l.strip() != "(none)"]
            terms = ", ".join(lines)[:60]
        if r["status"] == "needs_input":
            terms, n = (r["notes"] or "")[:60], -1
        t.add_row(r["posting_id"][:8],
                  "[yellow]needs_input[/yellow]" if r["status"] == "needs_input" else "generated",
                  r["company"], r["title"][:40],
                  "-" if n < 0 else ("[green]0[/green]" if n == 0 else f"[yellow]{n}[/yellow]"), terms)
    con.print(t)
    con.print("\nApply to clean ones only:  secjobs apply --clean-only")
    con.print("Retry needs_input jobs:    secjobs apply --retry")
    con.print("Apply to one job:          secjobs apply --id <id>")
    con.print("Drop a job for good:       secjobs drop --id <id>")


def cmd_drop(args):
    """Mark a job as skipped so it is never applied to or re-generated."""
    tr = Tracker()
    rows = [r for r in tr.all() if (args.id and r["posting_id"].startswith(args.id))
            or (args.title and args.title.lower() in r["title"].lower())
            or (args.company and r["company"].lower() == args.company.lower())]
    if not rows:
        con.print("No match."); return
    for r in rows:
        tr.set_status(r["posting_id"], "skipped", "dropped by user")
        con.print(f"skipped: {r['company']} | {r['title']}", markup=False)


def cmd_mark_applied(args):
    """Record that you submitted a job by hand (e.g. after an hCaptcha failure)."""
    tr = Tracker()
    rows = [r for r in tr.all() if args.id and r["posting_id"].startswith(args.id)]
    if not rows:
        con.print("No match - give --id from `secjobs review`."); return
    for r in rows:
        tr.set_status(r["posting_id"], "applied", "submitted manually")
        con.print(f"applied: {r['company']} | {r['title']}", markup=False)


def cmd_chrome(args):
    """Start your Chrome with a debugging port so `apply` can attach to it."""
    launch_chrome()


def cmd_serve(args):
    """Local bridge for the userscript (fills the form inside your normal Chrome)."""
    serve()


def cmd_status(args):
    tr = Tracker()
    t = Table(title="secjobs ledger")
    for c in ("status", "company", "title", "notes", "updated"):
        t.add_column(c)
    colors = {"applied": "green", "needs_input": "yellow", "generated": "cyan", "discovered": "white", "skipped": "dim"}
    for r in tr.all():
        t.add_row(f"[{colors.get(r['status'],'white')}]{r['status']}[/]", r["company"], r["title"][:50],
                  (r["notes"] or "")[:40], r["updated_at"][:16])
    con.print(t)


def cmd_run(args):
    cmd_scan(args); cmd_generate(args); cmd_review(args)
    con.print("\n[bold]Review the flags above, then run:[/bold] secjobs apply --clean-only")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="secjobs", description="Local, private cybersecurity job-application assistant")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, doc in [("scan", cmd_scan, "find new cyber postings"),
                          ("generate", cmd_generate, "tailor resume + cover letter (local LLM)"),
                          ("review", cmd_review, "list generated apps + fabrication flags"),
                          ("apply", cmd_apply, "fill forms in browser; you review + submit"),
                          ("drop", cmd_drop, "mark job(s) skipped so they are never applied to"),
                          ("mark-applied", cmd_mark_applied, "record a job you submitted by hand"),
                          ("chrome", cmd_chrome, "start Chrome so `apply` can attach (run first)"),
                          ("serve", cmd_serve, "start local bridge for the Chrome userscript"),
                          ("status", cmd_status, "show ledger"),
                          ("run", cmd_run, "scan -> generate -> review")]:
        sp = sub.add_parser(name, help=doc)
        sp.add_argument("--limit", type=int, default=0, help="max jobs to process")
        sp.add_argument("--company", default=None, help="Lever slug, e.g. zoox")
        sp.add_argument("--title", default=None, help="substring of the job title")
        sp.add_argument("--id", default=None, help="posting id prefix (from `review`)")
        sp.add_argument("--clean-only", action="store_true", help="skip jobs with review flags")
        sp.add_argument("--yes", "-y", action="store_true", help="don't ask before opening browsers")
        sp.add_argument("--retry", action="store_true", help="also re-attempt jobs marked needs_input")
        sp.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
