"""Fill a Lever application in a real (visible) browser, then hand over to you.

Flow per posting:
  1. open apply URL
  2. fill standard fields, upload tailored resume.pdf, paste cover letter
  3. answer custom questions from candidate.yaml `answers`
  4. if ANY required question is unanswered -> do NOT submit, mark needs_input, email you
  5. otherwise wait for YOU to review and press Submit; detect the /thanks page -> mark applied
"""
import re, time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout
from .config import ROOT
from .lever import Posting
from .notify import send_email
from .tracker import Tracker


_current_out: dict = {}


class ApplyResult:
    def __init__(self, status: str, notes: str = "", unanswered: list | None = None):
        self.status, self.notes, self.unanswered = status, notes, unanswered or []


def _match_answer(label: str, answers: list[dict]) -> str | None:
    l = label.lower()
    for a in answers:
        if any(m.lower() in l for m in a.get("match", [])):
            return str(a["answer"])
    return None


def _fill(page: Page, selector: str, value: str) -> bool:
    loc = page.locator(selector)
    if loc.count() and value:
        loc.first.fill(value)
        return True
    return False


def _select_by_text(page: Page, selector: str, wanted: str) -> bool:
    sel = page.locator(selector)
    if not sel.count() or not wanted:
        return False
    options = sel.first.locator("option").all_text_contents()
    w = wanted.lower()
    for o in options:
        if o.strip().lower() == w:
            sel.first.select_option(label=o); return True
    for o in options:  # fuzzy: all words of wanted present
        if all(tok in o.lower() for tok in re.findall(r"[a-z]+", w)):
            sel.first.select_option(label=o); return True
    for o in options:  # looser: first word
        if w.split()[0] in o.lower():
            sel.first.select_option(label=o); return True
    return False


_JS_SET = """el => {
  const proto = el.type === 'checkbox' || el.type === 'radio'
    ? window.HTMLInputElement.prototype : null;
  if (proto) {
    const setter = Object.getOwnPropertyDescriptor(proto, 'checked').set;
    setter.call(el, true);
  }
  el.dispatchEvent(new Event('input',  {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  el.dispatchEvent(new Event('click',  {bubbles: true}));
}"""


def _tick(el) -> bool:
    """Check a radio/checkbox without a physical click.

    Lever renders the hCaptcha iframe on top of part of the form, so a real
    click is often intercepted ('subtree intercepts pointer events'). We try a
    normal click first (most faithful), then a forced click, then set the
    property directly and fire the events React listens for.
    """
    for attempt in (
        lambda: el.check(timeout=3000),
        lambda: el.check(timeout=3000, force=True),
        lambda: el.evaluate(_JS_SET),
    ):
        try:
            attempt()
            if el.is_checked():
                return True
        except Exception:
            continue
    return False


def _label_of(el) -> str:
    try:
        return (el.evaluate("""e => {
            const l = e.closest('label');
            if (l) return l.innerText;
            if (e.id) { const f = document.querySelector(`label[for="${e.id}"]`); if (f) return f.innerText; }
            return e.value || '';
        }""") or "").strip()
    except Exception:
        return ""


def _answer_custom_question(q, answer: str) -> bool:
    """q is a locator for one `.application-question` block."""
    answer = (answer or "").strip()
    if not answer:
        return False

    if q.locator("select").count():
        sel = q.locator("select").first
        opts = sel.locator("option").all_text_contents()
        for o in opts:
            if o.strip().lower() == answer.lower():
                sel.select_option(label=o); return True
        for o in opts:
            if o.strip() and answer.lower() in o.lower():
                sel.select_option(label=o); return True
        return False

    for kind in ("radio", "checkbox"):
        inputs = q.locator(f"input[type={kind}]")
        n = inputs.count()
        if not n:
            continue
        # exact label/value match first, then prefix, then substring
        cands = []
        for i in range(n):
            el = inputs.nth(i)
            txt = _label_of(el).lower()
            val = (el.get_attribute("value") or "").lower()
            cands.append((el, txt, val))
        a = answer.lower()
        if kind == "checkbox" and n == 1 and a in ("yes", "y", "true", "agree", "i agree", "acknowledge", "confirm"):
            return _tick(cands[0][0])
        for el, txt, val in cands:
            if a == txt or a == val:
                return _tick(el)
        for el, txt, val in cands:
            if txt.startswith(a) or val.startswith(a):
                return _tick(el)
        for el, txt, val in cands:
            if a in txt or a in val:
                return _tick(el)
        return False

    if q.locator("textarea").count():
        q.locator("textarea").first.fill(answer); return True
    if q.locator("input[type=text], input[type=url], input[type=tel], input:not([type])").count():
        q.locator("input[type=text], input[type=url], input[type=tel], input:not([type])").first.fill(answer)
        return True
    return False


def _write_paste_sheet(page: Page, p: Posting, cand: dict, out: Path, unanswered: list) -> None:
    """Everything needed to submit this application by hand in a normal browser
    (useful when hCaptcha refuses to verify the automated one)."""
    lines = [f"APPLY BY HAND: {p.company} - {p.title}", p.apply_url, "",
             f"Full name:        {cand['full_name']}",
             f"Email:            {cand['email']}",
             f"Phone:            {cand['phone']}",
             f"Current location: {cand.get('location','')}",
             f"LinkedIn:         {cand.get('linkedin','')}",
             f"Resume file:      {out / 'resume.pdf'}",
             "", "Additional information (cover letter): see cover_letter.txt", ""]
    eeo = cand.get("eeo", {}) or {}
    lines += [f"EEO gender:       {eeo.get('gender','')}", f"EEO race:         {eeo.get('race','')}",
              f"EEO veteran:      {eeo.get('veteran','')}", ""]
    lines.append("Custom questions and the answer used:")
    questions = page.locator(".application-question")
    for i in range(questions.count()):
        q = questions.nth(i)
        try:
            lab = q.locator(".application-label, label").first.inner_text().strip()
        except Exception:
            continue
        lab = lab.replace("✱", "").replace("*", "").strip().splitlines()[0] if lab else ""
        if not lab or lab.lower().startswith(("full name", "email", "phone", "current", "resume", "linkedin", "additional")):
            continue
        ans = _match_answer(lab, cand.get("answers", [])) or "(no configured answer)"
        lines.append(f"  - {lab}\n      -> {ans}")
    if unanswered:
        lines += ["", "STILL NEEDS YOUR ANSWER:"] + [f"  - {u}" for u in unanswered]
    (out / "APPLY_BY_HAND.txt").write_text("\n".join(lines), encoding="utf-8")


def fill_form(page: Page, p: Posting, cand: dict, out: Path, settings: dict) -> ApplyResult:
    page.set_default_timeout(8000)
    page.goto(p.apply_url, wait_until="domcontentloaded")
    page.wait_for_selector("form#application-form, form", timeout=30000)
    page.evaluate("window.scrollTo(0, 0)")

    # --- standard Lever fields ---
    _fill(page, "input[name='name']", cand["full_name"])
    _fill(page, "input[name='email']", cand["email"])
    _fill(page, "input[name='phone']", cand["phone"])
    _fill(page, "input[name='urls[LinkedIn]']", cand.get("linkedin", ""))
    if page.locator("input[name='location']").count():
        page.locator("input[name='location']").first.fill(cand.get("location", ""))
        time.sleep(1.2)
        # accept first autocomplete suggestion if the dropdown appears
        sug = page.locator(".dropdown-location .dropdown-item, .location-dropdown li, [class*='dropdown'] li")
        if sug.count():
            try: sug.first.click(timeout=2000)
            except Exception: pass

    if page.locator("input[name='resume']").count():
        page.locator("input[name='resume']").first.set_input_files(str(out / "resume.pdf"))
        time.sleep(2)  # Lever parses the upload; it may overwrite name/email/phone -> re-fill
        _fill(page, "input[name='name']", cand["full_name"])
        _fill(page, "input[name='email']", cand["email"])
        _fill(page, "input[name='phone']", cand["phone"])

    if settings.get("cover_letter_in_additional_info", True):
        _fill(page, "textarea[name='comments']", (out / "cover_letter.txt").read_text(encoding="utf-8"))

    # --- EEO (voluntary) ---
    eeo = cand.get("eeo", {}) or {}
    for field in ("gender", "race", "veteran", "disability"):
        try:
            _select_by_text(page, f"select[name='eeo[{field}]']", eeo.get(field, ""))
        except Exception:
            pass

    # --- custom questions ---
    unanswered = []
    questions = page.locator(".application-question")
    for i in range(questions.count()):
        q = questions.nth(i)
        label = q.locator(".application-label, label").first.inner_text().strip() if q.locator(".application-label, label").count() else ""
        if not label:
            continue
        required = "✱" in label or "*" in label or q.locator("[required]").count() > 0
        # Lever appends things like the uploaded filename and "Analyzing resume..."
        # to the label, so compare on the FIRST LINE only.
        label_clean = label.replace("✱", "").replace("*", "").strip()
        first_line = label_clean.splitlines()[0].strip().lower() if label_clean else ""

        # a file question is satisfied if a file is actually attached
        if q.locator("input[type=file]").count():
            attached = q.locator("input[type=file]").first.evaluate("e => e.files && e.files.length > 0")
            if attached or "resume" in first_line or "cv" in first_line:
                continue

        STANDARD = ("full name", "email", "phone", "current company", "current location",
                    "resume", "cv", "additional information", "linkedin", "github",
                    "portfolio", "twitter", "other website", "cover letter")
        if any(first_line.startswith(k) or first_line == k for k in STANDARD):
            continue
        label_clean = label_clean.splitlines()[0].strip()
        ans = _match_answer(label_clean, cand.get("answers", []))
        ok = False
        if ans:
            try:
                ok = _answer_custom_question(q, ans)
            except Exception as e:
                print(f"     ! couldn't answer '{label_clean[:50]}' ({type(e).__name__})")
        if required and not ok:
            unanswered.append(label_clean)

    # also catch any required native field still blank, but report it by its
    # human label - and never twice for the same question block
    for el in page.locator("form [required]").all():
        try:
            typ = (el.get_attribute("type") or "").lower()
            if typ in ("file", "checkbox", "radio", "hidden", "submit"):
                continue
            tag = el.evaluate("e => e.tagName.toLowerCase()")
            if tag not in ("input", "textarea", "select"):
                continue
            if el.input_value(timeout=500):
                continue
            # find the label of the enclosing question block
            lbl = el.evaluate("""e => {
                const q = e.closest('.application-question');
                const t = q && q.querySelector('.application-label, label');
                return t ? t.innerText : '';
            }""") or ""
            lbl = lbl.replace("✱", "").replace("*", "").strip()
            lbl = lbl.splitlines()[0].strip() if lbl else (el.get_attribute("name") or "(unnamed field)")
            if not any(lbl.lower() == u.lower() or lbl.lower() in u.lower() or u.lower() in lbl.lower()
                       for u in unanswered):
                unanswered.append(lbl)
        except Exception:
            pass

    page.screenshot(path=str(out / "form_filled.png"), full_page=True)
    _write_paste_sheet(page, p, cand, out, unanswered)
    if unanswered:
        return ApplyResult("needs_input", unanswered=unanswered)
    return ApplyResult("filled")


def wait_for_submit(page: Page, minutes: int) -> bool:
    """Block until the user clicks Submit and Lever shows the thank-you page."""
    print(f"  >> Review the form in the browser and click SUBMIT. Waiting up to {minutes} min "
          f"(close the tab to skip).")
    deadline = time.time() + minutes * 60
    warned = False
    while time.time() < deadline:
        try:
            if re.search(r"/thanks|/confirmation", page.url):
                return True
            if not warned and page.locator("text=error verifying your application").count():
                warned = True
                print("  !! Lever says 'error verifying your application' = hCaptcha did not issue a token.")
                print("     1) Scroll to the 'I am human' box above Submit, complete it, click Submit again.")
                print("     2) If it STILL fails, hCaptcha is blocking the automated browser. Open the URL")
                print("        in your normal Chrome and fill it using:")
                print(f"        {_current_out.get('path', '')}")
                print("        Then run:  secjobs mark-applied --id " + _current_out.get("id", "")[:8])
            page.wait_for_timeout(1500)
        except Exception:  # tab closed
            return False
    return False


def _launch(pw, settings: dict):
    """Attach to the Chrome started by `secjobs chrome` (not flagged as automated).
    Falls back to launching a browser ourselves if it isn't running."""
    from . import chrome as _chrome
    cfg = settings.get("apply", {})
    if _chrome.is_running():
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{_chrome.PORT}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        print(f"  [browser] attached to your Chrome on port {_chrome.PORT}")
        return ctx, browser
    print("  [browser] `secjobs chrome` is not running - launching a browser myself.")
    print("            (hCaptcha may reject this one; for the reliable path run `secjobs chrome` first)")
    profile = ROOT / cfg.get("profile_dir", "data/browser_profile")
    profile.mkdir(parents=True, exist_ok=True)
    channel = cfg.get("browser", "chrome")
    kwargs = dict(user_data_dir=str(profile), headless=False, no_viewport=True,
                  args=["--disable-blink-features=AutomationControlled", "--start-maximized"])
    try:
        ctx = pw.chromium.launch_persistent_context(channel=None if channel == "chromium" else channel, **kwargs)
    except Exception:
        ctx = pw.chromium.launch_persistent_context(**kwargs)
    return ctx, None


def run_apply(postings: list[tuple[Posting, Path]], cand: dict, settings: dict, tracker: Tracker) -> None:
    with sync_playwright() as pw:
        context, attached = _launch(pw, settings)
        for p, out in postings:
            page = context.new_page()
            print(f"\n[{p.company}] {p.title}\n  {p.apply_url}")
            try:
                res = fill_form(page, p, cand, out, settings.get("apply", {}))
            except Exception as e:
                tracker.set_status(p.id, "generated", f"apply error: {e}")
                print(f"  ! error: {e}"); page.close(); continue

            if res.status == "needs_input":
                body = (f"Application NOT submitted - it has required questions with no configured answer.\n\n"
                        f"Company: {p.company}\nRole: {p.title}\nApply here: {p.apply_url}\n\n"
                        f"Unanswered required questions:\n" + "\n".join(f" - {u}" for u in res.unanswered)
                        + f"\n\nTailored resume + cover letter are in: {out}\n"
                          f"Tip: add an entry to config/candidate.yaml -> answers, then rerun `secjobs apply`.")
                try:
                    send_email(f"[secjobs] Needs your input: {p.company} - {p.title}", body)
                except Exception as e:            # notification must never abort the run
                    print(f"  [notify] {type(e).__name__}: {e}")
                tracker.set_status(p.id, "needs_input", "; ".join(res.unanswered))
                print("  -> NOT submitted. Required question(s) with no configured answer:")
                for u in res.unanswered:
                    print(f"       - {u}")
                print(f"     Add these to config/candidate.yaml -> answers, then rerun apply.")
                page.close(); continue

            _current_out.update(path=str(out / "APPLY_BY_HAND.txt"), id=p.id)
            if wait_for_submit(page, int(settings.get("apply", {}).get("wait_for_submit_minutes", 15))):
                tracker.set_status(p.id, "applied", "submitted via reviewed form")
                print("  ✓ applied")
                try: page.close()
                except Exception: pass
            else:
                tracker.set_status(p.id, "generated", "form filled but not submitted")
                print("  - not submitted (left as 'generated'; tab left open, rerun apply later)")
        if attached is None:          # we launched it, so we close it
            try: context.close()
            except Exception: pass
        else:                         # attached to the user's Chrome - leave it open
            try: attached.close()     # only disconnects
            except Exception: pass
