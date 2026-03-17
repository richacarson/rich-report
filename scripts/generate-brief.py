#!/usr/bin/env python3
"""
IOWN Automated Morning Brief Generator
Runs via GitHub Actions at 3:30 AM CT on weekdays.
1. Reads latest-drop.txt (market data from Finnhub)
2. Reads the last two HTML briefs for narrative continuity
3. Calls Claude API to generate brief content (HTML + structured JSON for PDF)
4. Builds PDF deterministically from JSON using ReportLab
5. Commits and pushes to the repo
"""

import os
import sys
import json
import subprocess
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request
import urllib.error

# ═══════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set")
    sys.exit(1)

REPO_ROOT = Path(__file__).parent.parent
BRIEFS_DIR = REPO_ROOT / "briefs"
LATEST_DROP = REPO_ROOT / "latest-drop.txt"
MANIFEST_PATH = BRIEFS_DIR / "manifest.json"
LOGO_SRC = REPO_ROOT / "scripts" / "IOWN_Logo_1.png"

CT = timezone(timedelta(hours=-6))  # Central Standard Time (always UTC-6)
TODAY = datetime.now(CT)
DATE_STR = TODAY.strftime("%Y-%m-%d")
DAY_NAME = TODAY.strftime("%A").upper()
DATE_DISPLAY = f"{TODAY.strftime('%B').upper()} {TODAY.day}, {TODAY.year}"
DATE_LINE = f"{DATE_DISPLAY}  |  {DAY_NAME}"

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-4-6"

# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════

def read_file(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"WARNING: File not found: {path}")
        return ""

def get_last_two_briefs():
    html_files = sorted(BRIEFS_DIR.glob("2026-*.html"), reverse=True)
    briefs = []
    for f in html_files[:2]:
        briefs.append({"date": f.stem, "content": f.read_text(encoding="utf-8")})
    return briefs

def get_manifest():
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def call_claude_api(system_prompt, user_prompt, max_tokens=16000):
    payload = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL, data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text_parts = [block["text"] for block in data.get("content", []) if block.get("type") == "text"]
            full_text = "\n".join(text_parts)
            usage = data.get("usage", {})
            print(f"API usage — input: {usage.get('input_tokens', '?')}, output: {usage.get('output_tokens', '?')}")
            return full_text
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        print(f"API ERROR {e.code}: {body}")
        sys.exit(1)
    except Exception as e:
        print(f"API request failed: {e}")
        sys.exit(1)

def fetch_news_headlines():
    finnhub_key = os.environ.get("FINNHUB_KEY")
    if not finnhub_key:
        return ""
    url = f"https://finnhub.io/api/v1/news?category=general&token={finnhub_key}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as resp:
            articles = json.loads(resp.read().decode("utf-8"))
            return "\n".join(
                f"* {a.get('headline','')} ({a.get('source','')}): {a.get('summary','')[:200]}"
                for a in articles[:15] if a.get("headline")
            )
    except Exception as e:
        print(f"WARNING: News fetch failed: {e}")
        return ""

# ═══════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════

SYSTEM_PROMPT = r"""You are a senior investment research analyst at Intentional Ownership (IOWN), an RIA managing ~$516M under Paradiem. You write the daily IOWN Morning Brief.

Writing style: direct, analytical, no fluff. Like a trusted colleague handing the CIO a one-page briefing sheet. ~5 min read. Opinionated and investment-relevant.

IOWN philosophy (use naturally): Research Reveals Opportunities, Think Like an Owner, Avoid Erosion, Simplicity Over Complexity.

HOLDINGS — Dividend: ABT, A, ADI, ATO, ADP, BKH, CAT, CHD, CL, FAST, GD, GPC, LRCX, LMT, MATX, NEE, ORI, PCAR, QCOM, DGX, SSNC, STLD, SYK, TEL, VLO | Growth: AMD, AEM, ATAT, CVX, CWAN, CNX, COIN, EIX, FINV, FTNT, GFI, SUPV, HRMY, HUT, KEYS, MARA, NVDA, NXPI, OKE, PDD, HOOD, SYF, TSM, TOL | Digital: IBIT, ETHA | Benchmarks: DVY, IWS, IUSG

OUTPUT THREE BLOCKS:

1. <META> — JSON: {"headline": "2-3 Words", "subhead": "One sentence.", "direction": "up" or "down"}

2. <HTML_BRIEF> — Full HTML for the daily brief matching prior brief structure exactly. Use HTML entities (&ndash; &mdash; &rsquo; etc). Snapshot div first. Sections: markets, geopolitics, radar.

3. <PDF_PARAGRAPHS> — A JSON array of objects. Each has "style" and "text":
   Styles: "sec" (section header), "rule" (HR), "lead" (bold opening), "body" (regular), "pq" (pullquote), "radar" (radar item), "small" (disclaimer), "spacer" (section gap)
   - For "rule" and "spacer": include "text": "" (empty string)
   - Text uses <b>bold</b> and <i>italic</i> tags
   - Use &amp; for ampersands (ReportLab XML)
   - Use actual Unicode: em dash \u2014, en dash \u2013, apostrophe \u2019
   - Three sections: MARKETS, GEOPOLITICS, ON OUR RADAR (each preceded by sec+rule, separated by spacer)
   - End with disclaimer in "small" style

Every brief must advance the narrative. Do NOT repeat prior brief themes/phrasing/radar items."""

# ═══════════════════════════════════════════
# USER PROMPT
# ═══════════════════════════════════════════

def build_user_prompt(data_drop, news, prev_briefs):
    prev_text = ""
    for b in prev_briefs:
        prev_text += f"\n--- PRIOR BRIEF ({b['date']}) ---\n{b['content']}\n"

    return f"""Today is {DATE_LINE}. Generate the IOWN Morning Brief.

<DATA_DROP>
{data_drop}
</DATA_DROP>

<NEWS_HEADLINES>
{news if news else "No additional headlines. Use data drop and your knowledge."}
</NEWS_HEADLINES>

<PRIOR_BRIEFS>
{prev_text}
</PRIOR_BRIEFS>

Generate <META>, <HTML_BRIEF>, and <PDF_PARAGRAPHS> blocks. The PDF_PARAGRAPHS must be valid JSON."""

# ═══════════════════════════════════════════
# PARSE RESPONSE
# ═══════════════════════════════════════════

def parse_response(response_text):
    meta_match = re.search(r"<META>(.*?)</META>", response_text, re.DOTALL)
    html_match = re.search(r"<HTML_BRIEF>(.*?)</HTML_BRIEF>", response_text, re.DOTALL)
    pdf_match = re.search(r"<PDF_PARAGRAPHS>(.*?)</PDF_PARAGRAPHS>", response_text, re.DOTALL)

    if not all([meta_match, html_match, pdf_match]):
        print("ERROR: Could not parse all blocks")
        print(f"META: {bool(meta_match)}, HTML: {bool(html_match)}, PDF: {bool(pdf_match)}")
        (REPO_ROOT / "debug_response.txt").write_text(response_text, encoding="utf-8")
        sys.exit(1)

    meta = json.loads(meta_match.group(1).strip())
    html = html_match.group(1).strip()

    pdf_raw = pdf_match.group(1).strip()
    # Strip code fences
    for prefix in ["```json", "```"]:
        if pdf_raw.startswith(prefix):
            pdf_raw = pdf_raw[len(prefix):].strip()
    if pdf_raw.endswith("```"):
        pdf_raw = pdf_raw[:-3].strip()

    try:
        pdf_paragraphs = json.loads(pdf_raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: PDF JSON parse failed: {e}")
        (REPO_ROOT / "debug_response.txt").write_text(response_text, encoding="utf-8")
        sys.exit(1)

    return meta, html, pdf_paragraphs

# ═══════════════════════════════════════════
# PDF GENERATION — deterministic from JSON
# ═══════════════════════════════════════════

def generate_pdf(meta, pdf_paragraphs):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
    from reportlab.platypus import Paragraph, Spacer, HRFlowable, NextPageTemplate
    from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate, Frame
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont("LS", "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"))
    pdfmetrics.registerFont(TTFont("LSB", "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("LSI", "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"))
    pdfmetrics.registerFont(TTFont("LSBI", "/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf"))
    pdfmetrics.registerFontFamily("LS", normal="LS", bold="LSB", italic="LSI", boldItalic="LSBI")
    pdfmetrics.registerFont(TTFont("DVB", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"))

    INK = HexColor("#1A1A1A")
    DG = HexColor("#3D4A2E")
    ACCENT = HexColor("#8B3A3A")
    MGRAY = HexColor("#8A8A84")
    HL_COLOR = DG if meta["direction"] == "up" else ACCENT

    W, H = letter
    M = 0.65 * inch
    GUTTER = 0.22 * inch
    COL_W = (W - 2*M - GUTTER) / 2.0
    BUL = chr(8226)
    logo_path = str(REPO_ROOT / "scripts" / "iown_logo_processed.png")
    pdf_output = str(BRIEFS_DIR / f"IOWN_Morning_Brief_{DATE_STR}.pdf")
    headline = meta["headline"]
    subhead = meta["subhead"]

    class BriefDoc(BaseDocTemplate):
        def __init__(self2, fn, **kw):
            BaseDocTemplate.__init__(self2, fn, **kw)
            top_off = 1.80 * inch
            f1L = Frame(M, 0.6*inch, COL_W, H - top_off - 0.6*inch, id="p1L", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0)
            f1R = Frame(M + COL_W + GUTTER, 0.6*inch, COL_W, H - top_off - 0.6*inch, id="p1R", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0)
            f2L = Frame(M, 0.6*inch, COL_W, H - 1.2*inch, id="p2L", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0)
            f2R = Frame(M + COL_W + GUTTER, 0.6*inch, COL_W, H - 1.2*inch, id="p2R", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0)
            self2.addPageTemplates([
                PageTemplate(id="first", frames=[f1L, f1R], onPage=self2.draw_first),
                PageTemplate(id="later", frames=[f2L, f2R], onPage=self2.draw_later),
            ])

        def draw_first(self2, c, doc):
            c.saveState()
            logo_h = 0.55 * inch
            logo_w = logo_h * (1245.0 / 657.0)
            c.drawImage(logo_path, M, H - 0.63*inch, width=logo_w, height=logo_h, mask="auto")
            c.setFillColor(MGRAY)
            c.setFont("Helvetica", 7.5)
            c.drawRightString(W - M, H - 0.50*inch, DATE_LINE)
            c.drawRightString(W - M, H - 0.62*inch, "INVESTMENT COMMITTEE")
            rule_y = H - 0.82*inch
            c.setStrokeColor(INK)
            c.setLineWidth(2)
            c.line(M, rule_y, W - M, rule_y)
            c.setLineWidth(0.5)
            c.line(M, rule_y - 3, W - M, rule_y - 3)
            c.setFillColor(HL_COLOR)
            c.setFont("DVB", 36)
            hl_y = rule_y - 0.52*inch
            c.drawString(M, hl_y, headline)
            c.setFillColor(INK)
            c.setFont("LSI", 11)
            sub_y = hl_y - 0.26*inch
            c.drawString(M, sub_y, subhead)
            content_rule_y = sub_y - 0.18*inch
            c.setStrokeColor(INK)
            c.setLineWidth(1)
            c.line(M, content_rule_y, W - M, content_rule_y)
            self2._footer(c, doc)
            c.restoreState()

        def draw_later(self2, c, doc):
            c.saveState()
            c.setFont("Helvetica", 6.5)
            c.setFillColor(MGRAY)
            hdr = "IOWN MORNING BRIEF " + BUL + " " + DATE_DISPLAY + " " + BUL + " INVESTMENT COMMITTEE"
            c.drawString(M, H - 0.38*inch, hdr)
            c.setStrokeColor(INK)
            c.setLineWidth(0.75)
            c.line(M, H - 0.44*inch, W - M, H - 0.44*inch)
            self2._footer(c, doc)
            c.restoreState()

        def _footer(self2, c, doc):
            c.setStrokeColor(INK)
            c.setLineWidth(0.5)
            c.line(M, 0.48*inch, W - M, 0.48*inch)
            c.setFont("Helvetica", 6)
            c.setFillColor(MGRAY)
            c.drawString(M, 0.32*inch, "CONFIDENTIAL  |  Intentional Ownership (IOWN)  |  RIA  |  Paradiem")
            c.drawRightString(W - M, 0.32*inch, "%d" % doc.page)

    sty = getSampleStyleSheet()
    sec_s = ParagraphStyle("Sec", parent=sty["Heading1"], fontName="Helvetica-Bold", fontSize=10.5, textColor=INK, spaceBefore=0, spaceAfter=0, leading=12)
    body_s = ParagraphStyle("Bod", parent=sty["Normal"], fontName="LS", fontSize=9, textColor=INK, leading=13.5, spaceBefore=0, spaceAfter=6, alignment=TA_JUSTIFY)
    lead_s = ParagraphStyle("Lead", parent=body_s, fontName="LSB", fontSize=9)
    pq_s = ParagraphStyle("PQ", parent=body_s, fontName="LSBI", fontSize=9.2, textColor=DG, leftIndent=8, rightIndent=8, spaceBefore=6, spaceAfter=8, leading=14)
    radar_s = ParagraphStyle("Rad", parent=body_s, leftIndent=10, spaceBefore=1, spaceAfter=4, fontSize=8.8, leading=13)
    small_s = ParagraphStyle("Sm", parent=body_s, fontSize=6.5, textColor=MGRAY, leading=8.5, alignment=TA_LEFT)

    style_map = {"sec": sec_s, "lead": lead_s, "body": body_s, "pq": pq_s, "radar": radar_s, "small": small_s}

    doc = BriefDoc(pdf_output, pagesize=letter)
    story = [NextPageTemplate("later")]

    for para in pdf_paragraphs:
        s = para.get("style", "body")
        text = para.get("text", "")
        if s == "rule":
            story.append(HRFlowable(width="100%", thickness=1, color=INK, spaceBefore=2, spaceAfter=8))
        elif s == "spacer":
            story.append(Spacer(1, 14))
        elif s in style_map:
            story.append(Paragraph(text, style_map[s]))
        else:
            story.append(Paragraph(text, body_s))

    doc.build(story)
    print(f"PDF generated: {pdf_output}")
    return pdf_output

# ═══════════════════════════════════════════
# LOGO / MANIFEST / GIT
# ═══════════════════════════════════════════

def process_logo():
    logo_processed = REPO_ROOT / "scripts" / "iown_logo_processed.png"
    if logo_processed.exists():
        print("Logo already processed, skipping")
        return
    if not LOGO_SRC.exists():
        print(f"ERROR: Logo source not found at {LOGO_SRC}")
        sys.exit(1)
    from PIL import Image
    import numpy as np
    img = Image.open(str(LOGO_SRC)).convert('RGBA')
    d = np.array(img)
    dark = (d[:,:,0] < 45) & (d[:,:,1] < 45) & (d[:,:,2] < 45)
    d[dark, 3] = 0
    out = Image.fromarray(d)
    out = out.crop(out.getbbox())
    out.save(str(logo_processed))
    print("Logo processed successfully")

def update_manifest(meta):
    manifest = get_manifest()
    manifest = [e for e in manifest if e.get("date") != DATE_STR]
    manifest.append({
        "date": DATE_STR, "headline": meta["headline"],
        "subhead": meta["subhead"], "direction": meta["direction"],
        "filename": f"IOWN_Morning_Brief_{DATE_STR}.pdf"
    })
    manifest.sort(key=lambda e: e["date"])
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Manifest updated for {DATE_STR}")

def git_commit_and_push(meta):
    files = [f"briefs/{DATE_STR}.html", f"briefs/IOWN_Morning_Brief_{DATE_STR}.pdf", "briefs/manifest.json"]
    subprocess.run(["git", "add"] + files, cwd=str(REPO_ROOT), check=True)
    result = subprocess.run(
        ["git", "commit", "-m", f"IOWN Morning Brief \u2014 {TODAY.strftime('%B')} {TODAY.day}, {TODAY.year}: {meta['headline']}"],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    if result.returncode != 0:
        if "nothing to commit" in result.stdout + result.stderr:
            print("Nothing to commit"); return
        print(f"Commit failed: {result.stderr}"); sys.exit(1)

    for attempt in range(3):
        r = subprocess.run(["git", "push"], capture_output=True, text=True, cwd=str(REPO_ROOT))
        if r.returncode == 0:
            print("Pushed successfully"); return
        print(f"Push attempt {attempt+1} failed, rebasing...")
        subprocess.run(["git", "pull", "--rebase"], capture_output=True, text=True, cwd=str(REPO_ROOT))
    print("ERROR: Push failed after 3 attempts"); sys.exit(1)

# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════

def main():
    print(f"═══ IOWN Morning Brief Generator ═══")
    print(f"Date: {DATE_STR} ({DAY_NAME})\n")

    html_path = BRIEFS_DIR / f"{DATE_STR}.html"
    pdf_path = BRIEFS_DIR / f"IOWN_Morning_Brief_{DATE_STR}.pdf"
    if html_path.exists() and pdf_path.exists() and not os.environ.get("FORCE_REGENERATE"):
        print(f"Brief exists for {DATE_STR}. Set FORCE_REGENERATE=1 to overwrite."); sys.exit(0)

    data_drop = read_file(LATEST_DROP)
    if not data_drop: print("ERROR: No data drop"); sys.exit(1)
    print(f"Data drop: {len(data_drop)} chars | {data_drop.split(chr(10))[0]}")

    print("Fetching news...")
    news = fetch_news_headlines()
    print(f"News: {len(news)} chars")

    prev_briefs = get_last_two_briefs()
    print(f"Prior briefs: {[b['date'] for b in prev_briefs]}")

    print("Processing logo...")
    process_logo()

    print(f"\nCalling Claude API ({MODEL})...")
    user_prompt = build_user_prompt(data_drop, news, prev_briefs)
    print(f"Prompt: ~{len(user_prompt)} chars")
    response = call_claude_api(SYSTEM_PROMPT, user_prompt)
    print(f"Response: {len(response)} chars")

    print("\nParsing...")
    meta, html_content, pdf_paragraphs = parse_response(response)
    print(f"Headline: {meta['headline']}")
    print(f"Subhead: {meta['subhead']}")
    print(f"Direction: {meta['direction']}")
    print(f"PDF paragraphs: {len(pdf_paragraphs)}")

    html_out = BRIEFS_DIR / f"{DATE_STR}.html"
    html_out.write_text(html_content, encoding="utf-8")
    print(f"\nHTML: {html_out} ({len(html_content)} chars)")

    print("Generating PDF...")
    pdf_out = generate_pdf(meta, pdf_paragraphs)
    print(f"PDF: {Path(pdf_out).stat().st_size} bytes")

    update_manifest(meta)

    print("\nPushing...")
    git_commit_and_push(meta)

    print(f"\n═══ Complete: {meta['headline']} ═══")

if __name__ == "__main__":
    main()
