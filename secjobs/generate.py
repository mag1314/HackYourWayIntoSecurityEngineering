"""Tailor resume + cover letter with a local model. Guardrails against fabrication."""
import re
from pathlib import Path
from fpdf import FPDF
from .config import OUTPUT_DIR
from .lever import Posting
from .llm import Ollama

RESUME_SYSTEM = """You are an expert cybersecurity resume editor.
You will receive a MASTER RESUME and a JOB POSTING.
Produce a tailored one-page resume in Markdown that reorders, trims and rephrases
the master resume to emphasise what this posting asks for.

HARD RULES - violating any of these makes the output unusable:
1. Do NOT add any employer, job title, date, degree, certification, tool,
   technology, metric or accomplishment that is not present in the master resume.
2. You may drop items, reorder items, and rephrase bullets using the posting's
   vocabulary ONLY where the master resume already supports that claim.
3. Keep the same section structure: header, Summary, Skills, Experience, Education, Certifications.
4. Output ONLY the Markdown resume. No commentary, no preamble, no code fences."""

COVER_SYSTEM = """You write concise, specific cover letters for cybersecurity roles.
Use ONLY facts from the candidate's resume. Never invent experience, tools or numbers.
Tone: confident, plain English, no cliches ("I am excited to apply", "passionate").
Length: 180-260 words, 3 short paragraphs:
 (1) which role and the one strongest reason you fit;
 (2) two or three concrete, resume-backed examples mapped to the posting's needs;
 (3) a brief close.
Sign off with the candidate's name. Output only the letter text."""


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def out_dir(p: Posting) -> Path:
    d = OUTPUT_DIR / p.company / f"{_slug(p.title)}-{p.id[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---- fabrication check -------------------------------------------------------
_TOKEN = re.compile(r"\b[A-Z][A-Za-z0-9+#\.\-]{1,}\b|\b\d{4}\b|\b\d+%|\$\d[\d,\.]*")


def suspicious_terms(tailored: str, master: str, posting_text: str) -> list[str]:
    """Capitalised terms / years / numbers in the tailored resume that appear in
    neither the master resume nor the candidate header. Anything here is a
    likely hallucination and must be reviewed."""
    base = (master + " " ).lower()
    common = {"summary", "skills", "experience", "education", "certifications", "the", "and", "for",
              "with", "present", "led", "built", "managed", "designed", "implemented", "responsible"}
    flagged = set()
    for t in _TOKEN.findall(tailored):
        tl = t.lower().strip(".")
        if tl in common or len(tl) < 2:
            continue
        if tl not in base:
            flagged.add(t)
    return sorted(flagged)


# ---- PDF ----------------------------------------------------------------------
def markdown_to_pdf(md: str, path: Path) -> None:
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(16, 14, 16)
    pdf.add_page()
    for raw in md.splitlines():
        line = raw.rstrip()
        # fpdf core fonts are latin-1; replace unsupported chars
        line = line.replace("–", "-").replace("—", "-").replace("’", "'").replace("·", "|")
        line = line.encode("latin-1", "replace").decode("latin-1")
        if not line.strip():
            pdf.ln(2); continue
        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16); pdf.multi_cell(0, 7, line[2:]); pdf.ln(1)
        elif line.startswith("## "):
            pdf.ln(1); pdf.set_font("Helvetica", "B", 11.5); pdf.multi_cell(0, 6, line[3:].upper())
            pdf.set_draw_color(120); pdf.line(pdf.l_margin, pdf.get_y(), 216 - pdf.r_margin, pdf.get_y()); pdf.ln(1)
        elif line.startswith("### "):
            pdf.set_font("Helvetica", "B", 10.5); pdf.multi_cell(0, 5.5, line[4:])
        elif line.lstrip().startswith(("- ", "* ")):
            pdf.set_font("Helvetica", "", 10)
            txt = re.sub(r"\*\*(.+?)\*\*", r"\1", line.lstrip()[2:])
            pdf.set_x(pdf.l_margin + 4); pdf.multi_cell(0, 5, "- " + txt)
        else:
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, re.sub(r"\*\*(.+?)\*\*", r"\1", line))
    pdf.output(str(path))


# ---- main entry ---------------------------------------------------------------
def generate_for(p: Posting, master: str, cand: dict, llm: Ollama) -> dict:
    d = out_dir(p)
    posting_text = f"TITLE: {p.title}\nCOMPANY: {p.company}\nLOCATION: {p.location}\n\n{p.full_text}"[:12000]

    resume_md = llm.chat(
        RESUME_SYSTEM,
        f"MASTER RESUME:\n{master}\n\n=====\nJOB POSTING:\n{posting_text}",
    )
    resume_md = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", resume_md.strip())

    cover = llm.chat(
        COVER_SYSTEM,
        f"CANDIDATE NAME: {cand['full_name']}\nCANDIDATE RESUME:\n{master}\n\n=====\n"
        f"JOB POSTING:\n{posting_text}",
    )

    flags = suspicious_terms(resume_md, master, posting_text)

    (d / "posting.txt").write_text(posting_text, encoding="utf-8")
    (d / "resume.md").write_text(resume_md, encoding="utf-8")
    (d / "cover_letter.txt").write_text(cover, encoding="utf-8")
    (d / "REVIEW_FLAGS.txt").write_text(
        "Terms in tailored resume NOT found in master resume (verify before applying):\n"
        + ("\n".join(flags) if flags else "(none)"), encoding="utf-8")
    markdown_to_pdf(resume_md, d / "resume.pdf")
    return {"dir": d, "flags": flags}
