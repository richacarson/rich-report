#!/usr/bin/env python3
"""
IOWN Automated Morning Brief Generator

Modes:
  --prep           Gather data and print the assembled prompt to stdout (for Claude Code)
  --post-process F Read Claude's response from file F, then generate PDF/HTML/manifest/git push
  (no flags)       Legacy full mode: data gather → Claude API call → PDF/HTML/git push
"""

import os
import sys
import json
import subprocess
import re
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request
import urllib.error

# ═══════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

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

SYSTEM_PROMPT = r"""You are a senior investment research analyst at Intentional Ownership (IOWN), an RIA managing ~$516M under Paradiem. You prepare the daily IOWN Morning Brief for Carson, the Research Analyst and pending CIO.

═══ WRITING STYLE ═══

Direct, analytical, no fluff. Write like a trusted colleague handing Carson a one-page briefing sheet. Approximately 5 minutes of reading time. Opinionated and investment-relevant — not raw news aggregation. Include technical indicators (moving averages, RSI, ETF flows) where applicable. Integrate analysis across sections — the brief should read as one cohesive argument, not three disconnected sections.

Every data point and observation should be filtered through: "What does this mean for IOWN's holdings and thesis?" Do not write general market commentary — write analysis that helps the investment committee make decisions about the portfolio. When discussing macro moves, connect them to specific IOWN positions or sleeves. When discussing geopolitics, connect them to portfolio exposure (energy, semis, digital assets, defense, etc.).

IOWN philosophy references (use naturally, don't force):
- Research Reveals Opportunities
- Think Like an Owner
- Avoid Erosion
- Simplicity Over Complexity

The core IOWN investment thesis centers on "physical world matters" — emphasizing physical AI infrastructure, energy value, and real-world industrial themes.

═══ TONE & COMPLIANCE ═══

This document is for an RIA investment committee. All language must be professional and SEC-appropriate.

NEVER use predictive language stated as fact. Examples of what NOT to write:
- "The snap-back will be violent" → Instead: "Historically, these patterns tend to reverse sharply"
- "Futures will re-converge upward" → Instead: "Futures tend to re-converge with physical premiums when de-leveraging subsides"
- "These names snap back hardest" → Instead: "These names historically tend to recover quickly"
- "This is the final stage" → Instead: "This pattern is consistent with late-stage..."
- "Oil is headed toward $X" → Instead: "Oil could approach $X if current trends persist"

Use conditional framing: "may," "could," "tends to," "historically," "if this pattern holds," "consistent with," "suggests"

NEVER use informal or retail-newsletter language:
- No "Don't be fooled" — use "The headline number warrants context"
- No "fool's errand" — use "the timing remains uncertain"
- No "disaster" — use "material miss" or "significant shortfall"
- No "generational entry" — use "attractive entry levels"
- No "the right place to be" — use "tend to hold up well in this environment"
- No citing TV personalities (e.g., Cramer) by name — make the analytical point directly

NEVER make direct recommendations or timing calls:
- No "let the forced sellers finish before stepping in" — use "discipline over impulse"
- No "the technical structure flips bullish" — use "the technical structure would turn notably more constructive"
- No "X are the beneficiaries" — use "X stand to benefit in a scenario where..."

When interpreting foreign leader statements or geopolitical intent, hedge appropriately:
- No "That vision requires X" → "That vision would require X"
- No "this means Israel's war aims include..." → "if taken at face value, this would suggest..."

NEVER call specific support or resistance price levels (e.g., "support at 6,400," "resistance at $235," "$178–$180 is the line"). You may reference moving averages (50-day, 100-day, 200-day) and whether price is above or below them, but do not identify or predict specific price floors, ceilings, or targets.

═══ SOURCE ATTRIBUTION ═══

When citing third-party data, research, or reporting, attribute the source clearly but NEVER use direct quotes. Paraphrase everything.
- Good: "Morgan Stanley moved their rate cut forecast to September, citing persistent energy inflation."
- Good: "Reuters reports physical oil cargo prices reached record levels."
- Bad: "Reuters said 'Dollar slips, bonds struggle as Iran war spurs hawkish rate rethink'"
- Bad: Citing data or analysis without attribution (e.g., stating a bank's forecast as if it's your own view)

Attribute when: a data point, forecast, or analysis comes from a specific institution, bank, news outlet, or research firm.
Do not attribute when: stating market prices, index levels, or percentage moves from the data drop — these are observable facts.

═══ FACTUAL ACCURACY ═══

NEVER make comparative claims you cannot verify against the data drop and prior briefs. Examples:
- "First time since..." — verify the prior instance exists in your data
- "Biggest/smallest move in X sessions" — cross-check against the prior briefs' snapshot data
- "X consecutive sessions of..." — count the actual sessions from prior briefs
- "First green close in X days" — verify from snapshot data

If you cannot verify a comparative claim from the data provided, do not make it. State the fact without the comparison. "S&P fell 0.25%" is always safe. "S&P posted its smallest decline in a week" requires proof.

═══ IOWN HOLDINGS ═══

Dividend sleeve: ABT, A, ADI, ATO, ADP, BKH, CAT, CHD, CL, FAST, GD, GPC, LRCX, LMT, MATX, NEE, ORI, PCAR, QCOM, DGX, SSNC, STLD, SYK, TEL, VLO
Growth sleeve: AMD, AEM, ATAT, CVX, CWAN, CNX, COIN, EIX, FINV, FTNT, GFI, SUPV, HRMY, HUT, KEYS, MARA, NVDA, NXPI, OKE, PDD, HOOD, SYF, TSM, TOL
Digital ETFs: IBIT, ETHA
Benchmarks: DVY, IWS, IUSG

═══ NARRATIVE CONTINUITY ═══

You will receive the last two HTML briefs. Every brief MUST advance the narrative. Do NOT repeat the same themes, phrasing, data points, or radar items from the prior briefs unless there is a material update. Each brief should build on the story arc — new analysis, new developments, new framing.

On quiet days (no major index moves, no significant geopolitical escalation, thin news flow): write shorter. Do not stretch thin material to fill the standard format. It is better to have 3 tight, substantive radar items than 6 that pad with speculation. Markets and Geopolitics sections can be shorter on quiet days. Never fabricate urgency or drama to fill space — the committee will trust the brief more when it says "today was uneventful" than when it manufactures significance.

═══ OUTPUT FORMAT ═══

You MUST output THREE clearly separated blocks:

BLOCK 1 — <META>
JSON with exactly these keys:
{"headline": "2-3 Words Max", "subhead": "One sentence matching PDF subhead.", "direction": "up" or "down"}

BLOCK 2 — <HTML_BRIEF>
Full HTML content for the daily brief. Structure rules below.

BLOCK 3 — <PDF_PARAGRAPHS>
A valid JSON array of paragraph objects for PDF generation. Format rules below.

═══ HTML BRIEF FORMAT ═══

The HTML brief has THREE content sections plus a required snapshot div.

SNAPSHOT DIV (must be first element):
```
<!-- Snapshot (also feeds the ticker bar) -->
<div class="snapshot">
  <div class="snap-item"><div class="snap-label">S&amp;P 500</div><div class="snap-val up">6,697 &uarr;1.12%</div></div>
  <div class="snap-item"><div class="snap-label">Brent Crude</div><div class="snap-val dn">$103 &darr;1.5%</div></div>
  <div class="snap-item"><div class="snap-label">Bitcoin</div><div class="snap-val up">$73,200 &uarr;3.94%</div></div>
  <div class="snap-item"><div class="snap-label">[Contextual]</div><div class="snap-val up">value</div></div>
  <div class="snap-item"><div class="snap-label">Fear &amp; Greed</div><div class="snap-val dn">23 &middot; Extreme Fear</div></div>
</div>
```
- Use class "up" for green values, "dn" for red
- The 4th snap-item is contextual — pick the most relevant ticker for the day (NVDA on GTC day, VIX on crash days, etc.)
- Always include S&P, Brent, Bitcoin, and Fear & Greed

THREE CONTENT SECTIONS:

1. Markets (id="markets") — macro, indices, oil, rates, Fed, sector rotation, moving averages. Always connect moves to IOWN holdings and sleeves.
2. Geopolitics (id="geopolitics") — the dominant macro/geopolitical theme affecting markets and IOWN portfolio positioning. This may be armed conflict, trade policy, sanctions, elections, regulatory shifts, central bank coordination, or any other non-market force driving prices. Adapt the section to whatever matters most — do not force a war narrative when the dominant story is something else.
3. On Our Radar (id="radar") — 3 to 6 items synthesizing the day's themes into observations relevant to IOWN's portfolio. Each item should connect to specific holdings or sleeves. On quiet days, 3-4 strong items are better than 6 padded ones.

HTML STRUCTURE RULES:
- Use section-start wrapper divs with section-label, h2, section-rule
- Bullet content uses: <div class="bullet"><div class="bullet-heading">Title</div><div class="bullet-body">Text</div></div>
- First bullet is inside section-start div; subsequent bullets are siblings outside it
- Data boxes: <div class="data-box"><div class="data-row"><span class="data-label">Label</span><span class="data-val up">Value</span></div></div>
- Pullquotes: <div class="pullquote">Text with <b>IOWN philosophy reference.</b></div>
- Radar items: <div class="radar-item"><b>1. Title.</b> Details...</div>
- Radar items 1-2 are standalone (inside section-start or direct children)
- Radar items 3-4 go in a <div class="radar-group">
- Radar items 5-6 go in another <div class="radar-group">
- Use proper HTML entities: &ndash; &mdash; &rsquo; &ldquo; &rdquo; &darr; &uarr; &middot; &amp;

═══ PDF PARAGRAPHS FORMAT ═══

A JSON array of objects. Each object has "style" and "text" keys.

Available styles:
- "sec" — section header (e.g., "MARKETS", "GEOPOLITICS", "ON OUR RADAR")
- "rule" — horizontal rule after section header (text should be "")
- "lead" — bold opening paragraph for each section
- "body" — regular body text paragraphs
- "pq" — italic IOWN Tactical pullquote (green text, indented) — used for key tactical insights and philosophy references
- "radar" — On Our Radar items (slightly smaller, indented)
- "small" — disclaimer footer
- "spacer" — gap between sections (text should be "")

Section structure pattern:
sec → rule → lead → body → body → ... → pq → spacer → sec → rule → lead → body → ... → spacer → sec → rule → radar x3-6 → small

Text formatting rules:
- Use <b>bold</b> for emphasis and lead sentence openings
- Use <i>italic</i> for emphasis within pullquotes
- Use &amp; for ampersands (ReportLab XML requirement)
- Use actual Unicode characters: em dash \u2014, en dash \u2013, right single quote \u2019
- Do NOT use HTML entities in PDF paragraphs — use Unicode directly

Content guidance for PDF:
- MARKETS section: 1 lead paragraph + 3-5 body paragraphs + 1 pullquote (IOWN Tactical)
- GEOPOLITICS section: 1 lead paragraph + 2-3 body paragraphs
- ON OUR RADAR section: 3 to 6 radar items, each starting with <b>N. Title.</b> — prefer fewer strong items over padding
- End with disclaimer: "For internal IOWN investment committee use only. Not investment advice. Information from public sources believed reliable. Past performance not indicative of future results. IOWN is an RIA under Paradiem."

═══ SAMPLE PDF PARAGRAPH CONTENT (for tone/style reference) ═══

Lead style example:
"<b>ALL THREE INDEXES HIT 2026 CLOSING LOWS.</b> S&P \u20131.52% to 6,672. Dow \u20131.54%, falling below 47,000 for the first time this year. Nasdaq \u20131.78%. Russell \u20132.15%. UVXY surged 9.86%. Brent crude settled above $100 for the first time since August 2022."

Body style example:
"The catalyst: Iran\u2019s new supreme leader Mojtaba Khamenei issued his first statement, vowing to keep the Strait of Hormuz closed as a tool to pressure the enemy and continue attacks on Gulf Arab neighbors. That single statement sent WTI up 9.72% to $95.73 and Brent up 9.22% to $100.46."

Pullquote style example:
"IOWN Tactical: S&amp;P at 6,673 (SPY $666.06). Down ~13% from January ATH of 7,003. The 200-day moving average is at ~6,596\u2014hasn\u2019t been broken in 10 months. That\u2019s the technical line in the sand. Our \u201320% buy trigger is at ~5,600. Research Reveals Opportunities\u2014discipline over impulse."

Radar style example:
"<b>1. The 200DMA at 6,596 is the level to watch.</b> S&amp;P at 6,673\u2014just 77 points above. This level hasn\u2019t been broken in 10 months. Our \u201320% buy trigger is ~5,600\u2014still 16% below. Patience remains the discipline."
"""

# ═══════════════════════════════════════════
# USER PROMPT
# ═══════════════════════════════════════════

def build_user_prompt(data_drop, news, prev_briefs):
    prev_text = ""
    for b in prev_briefs:
        prev_text += f"\n--- PRIOR BRIEF ({b['date']}) ---\n{b['content']}\n"

    return f"""Today is {DATE_LINE}. It is approximately 3:30 AM Central Time — roughly 5.5 hours before the NYSE opens at 8:30 AM CT (9:30 AM ET).

This brief will be read by the investment committee before market open. Frame accordingly:
- The data drop reflects the PRIOR session's closing prices and after-hours activity.
- Any earnings reported after yesterday's close or in pre-market this morning are relevant and should be highlighted.
- Overnight futures, Asian and European session moves, and pre-market movers provide forward-looking context for today's open.
- The committee is reading this to prepare for the trading day ahead — emphasize what to watch today, not just what happened yesterday.

Generate the IOWN Morning Brief.

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

    if not all([meta_match, html_match]):
        print("ERROR: Could not parse META and HTML_BRIEF blocks")
        print(f"META: {bool(meta_match)}, HTML: {bool(html_match)}")
        (REPO_ROOT / "debug_response.txt").write_text(response_text, encoding="utf-8")
        sys.exit(1)

    meta = json.loads(meta_match.group(1).strip())
    html = html_match.group(1).strip()

    # PDF_PARAGRAPHS is no longer required (PDF is generated from HTML via weasyprint)
    pdf_paragraphs = None
    pdf_match = re.search(r"<PDF_PARAGRAPHS>(.*?)</PDF_PARAGRAPHS>", response_text, re.DOTALL)
    if pdf_match:
        print("Note: PDF_PARAGRAPHS block found but will be ignored (using weasyprint HTML-to-PDF)")

    return meta, html, pdf_paragraphs

# ═══════════════════════════════════════════
# PDF GENERATION — deterministic from JSON
# ═══════════════════════════════════════════

def generate_pdf(meta, html_content, output_path=None):
    """Generate PDF from HTML brief content using weasyprint (matches web styling)."""
    import weasyprint

    logo_path = (REPO_ROOT / "scripts" / "iown_logo_processed.png").as_uri()
    pdf_output = output_path or str(BRIEFS_DIR / f"IOWN_Morning_Brief_{DATE_STR}.pdf")
    hl_color = "#3D4A2E" if meta.get("direction") == "up" else "#9B2C2C"

    wrapper_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&family=DM+Sans:wght@400;500;600;700&family=Cormorant+Garamond:ital,wght@0,400;0,600;0,700;1,400;1,600&display=swap');

  @page {{
    size: letter;
    margin: 0.6in 0.65in 0.55in;
    @bottom-left {{
      content: "CONFIDENTIAL  |  Intentional Ownership (IOWN)  |  RIA  |  Paradiem";
      font-family: 'DM Sans', sans-serif;
      font-size: 6pt;
      color: #8A8A84;
    }}
    @bottom-right {{
      content: counter(page);
      font-family: 'DM Sans', sans-serif;
      font-size: 6pt;
      color: #8A8A84;
    }}
  }}
  @page :first {{
    margin-top: 0.45in;
  }}
  @page :not(:first) {{
    @top-left {{
      content: "IOWN MORNING BRIEF";
      font-family: 'DM Sans', sans-serif;
      font-size: 6pt;
      color: #8A8A84;
      letter-spacing: 1pt;
      text-transform: uppercase;
    }}
    @top-right {{
      content: "{DATE_DISPLAY}";
      font-family: 'DM Sans', sans-serif;
      font-size: 6pt;
      color: #8A8A84;
      letter-spacing: 1pt;
      text-transform: uppercase;
    }}
  }}

  :root {{
    --white: #FFFFFF;
    --cream: #FAF9F6;
    --gray-50: #FAFAFA;
    --gray-100: #F4F4F2;
    --gray-200: #E8E8E4;
    --gray-300: #D1D1CB;
    --gray-400: #A8A8A0;
    --gray-500: #78786E;
    --gray-700: #4A4A42;
    --gray-900: #1A1A18;
    --green: #3D4A2E;
    --green-mid: #5B7A3D;
    --green-light: #7A8F5A;
    --red: #9B2C2C;
    --red-light: #C53030;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'EB Garamond', Georgia, serif;
    color: var(--gray-900);
    font-size: 10pt;
    line-height: 1.55;
  }}

  /* ══ MASTHEAD ══ */
  .pdf-masthead {{
    text-align: center;
    margin-bottom: 0;
    break-inside: avoid;
  }}
  .mast-rule-top {{ height: 3pt; background: var(--gray-900); margin-bottom: 1.5pt; }}
  .mast-rule-thin {{ height: 0.75pt; background: var(--gray-900); margin-bottom: 8pt; }}
  .mast-meta {{
    display: flex; justify-content: space-between; align-items: baseline;
    font-family: 'DM Sans', sans-serif; font-size: 6pt; color: var(--gray-400);
    letter-spacing: 1.5pt; text-transform: uppercase; margin-bottom: 4pt;
    padding: 0 2pt;
  }}
  .mast-logo {{
    height: 28pt;
    display: block;
    margin: 0 auto 6pt;
  }}
  .mast-title {{
    font-family: 'Cormorant Garamond', serif; font-size: 30pt; font-weight: 700;
    color: var(--gray-900); line-height: 1; letter-spacing: -0.5pt;
    margin-bottom: 2pt;
  }}
  .mast-date {{
    font-family: 'DM Sans', sans-serif; font-size: 7pt; color: var(--gray-500);
    letter-spacing: 1.5pt; text-transform: uppercase; margin-top: 4pt;
    margin-bottom: 6pt;
  }}
  .mast-rule-bottom {{ height: 0.75pt; background: var(--gray-300); margin-bottom: 0; }}

  /* ══ HEADLINE BANNER ══ */
  .pdf-banner {{
    text-align: center;
    padding: 12pt 16pt 10pt;
    column-span: all;
    break-inside: avoid;
  }}
  .banner-headline {{
    font-family: 'Cormorant Garamond', serif; font-size: 28pt; font-weight: 700;
    line-height: 1.15; color: {hl_color}; margin-bottom: 5pt;
    letter-spacing: -0.3pt;
  }}
  .banner-subhead {{
    font-family: 'EB Garamond', Georgia, serif; font-size: 10.5pt; font-weight: 400;
    font-style: italic; color: var(--gray-500); line-height: 1.45;
    max-width: 80%; margin: 0 auto;
  }}
  .banner-rule {{
    width: 36pt; height: 2pt; background: var(--gray-900); margin: 10pt auto 0;
  }}

  /* ══ TWO-COLUMN CONTENT ══ */
  .bc {{
    columns: 2; column-gap: 24pt; column-rule: 0.75pt solid var(--gray-200);
    padding-top: 6pt;
  }}

  /* ── Section headers ── */
  .bc .section-start {{
    column-span: all; break-inside: avoid;
  }}
  .bc .section-label {{
    font-family: 'DM Sans', sans-serif; font-size: 5.5pt; color: var(--gray-400);
    letter-spacing: 1.8pt; text-transform: uppercase; margin-top: 14pt;
    padding-top: 4pt; border-top: 0.75pt solid var(--gray-300);
  }}
  .bc .section-start:first-child .section-label {{
    margin-top: 0; border-top: none; padding-top: 0;
  }}
  .bc h2 {{
    font-family: 'Cormorant Garamond', serif; font-size: 15pt; font-weight: 700;
    color: var(--gray-900); margin: 2pt 0 0; line-height: 1.15;
  }}
  .bc .section-rule {{
    height: 2pt; background: var(--gray-900); margin: 5pt 0 10pt;
  }}

  /* ── Bullet cards ── */
  .bc .bullet {{
    padding: 6pt 0 6pt 10pt; margin: 0 0 8pt;
    border-left: 2pt solid var(--gray-900); break-inside: avoid;
  }}
  .bc .bullet-heading {{
    font-family: 'DM Sans', sans-serif; font-size: 7.5pt; font-weight: 700;
    color: var(--gray-900); letter-spacing: 0.3pt; margin-bottom: 3pt;
    text-transform: uppercase;
  }}
  .bc .bullet-body {{
    font-size: 10pt; line-height: 1.55; color: var(--gray-700);
    text-align: justify; hyphens: auto;
  }}
  .bc .bullet-body b, .bc .bullet-body strong {{ color: var(--gray-900); }}

  /* ── Pullquote ── */
  .bc .pullquote {{
    column-span: all; break-inside: avoid;
    margin: 14pt 0; padding: 14pt 24pt;
    border-top: 2pt solid var(--gray-900); border-bottom: 0.75pt solid var(--gray-300);
    font-family: 'Cormorant Garamond', serif; font-size: 13pt; font-weight: 600;
    font-style: italic; color: var(--green); line-height: 1.45; text-align: center;
  }}
  .bc .pullquote b, .bc .pullquote strong {{ font-style: normal; }}

  /* ── Data box ── */
  .bc .data-box {{
    break-inside: avoid;
    background: var(--cream); border-top: 1.5pt solid var(--gray-900);
    border-bottom: 0.75pt solid var(--gray-200);
    padding: 8pt 10pt; margin: 8pt 0;
    font-family: 'DM Sans', sans-serif; font-size: 7.5pt; line-height: 1.7;
    color: var(--gray-700);
  }}
  .bc .data-box .data-row {{
    display: flex; justify-content: space-between; padding: 1.5pt 0;
    border-bottom: 0.5pt dotted var(--gray-300);
  }}
  .bc .data-box .data-row:last-child {{ border-bottom: none; }}
  .bc .data-box .data-label {{
    color: var(--gray-500); font-size: 6.5pt; text-transform: uppercase; letter-spacing: 0.5pt;
  }}
  .bc .data-box .data-val {{ font-weight: 600; }}
  .bc .up {{ color: var(--green-mid); }}
  .bc .dn {{ color: var(--red); }}

  /* ── Snapshot bar ── */
  .bc .snapshot {{
    column-span: all; break-inside: avoid;
    display: flex; flex-wrap: wrap; justify-content: space-between;
    border-top: 1.5pt solid var(--gray-900); border-bottom: 0.75pt solid var(--gray-300);
    margin: 0 0 4pt; padding: 0;
    font-family: 'DM Sans', sans-serif;
  }}
  .bc .snap-item {{
    flex: 1; min-width: 60pt; padding: 6pt 8pt;
    border-right: 0.75pt solid var(--gray-200); text-align: center;
  }}
  .bc .snap-item:last-child {{ border-right: none; }}
  .bc .snap-label {{
    font-size: 5pt; text-transform: uppercase; letter-spacing: 1pt; color: var(--gray-400);
  }}
  .bc .snap-val {{
    font-size: 8pt; font-weight: 700; color: var(--gray-900); margin-top: 2pt;
  }}
  .bc .snap-val.up {{ color: var(--green-mid); }}
  .bc .snap-val.dn {{ color: var(--red); }}

  /* ── Radar items ── */
  .bc .radar-item {{
    column-span: all; break-inside: avoid;
    padding: 6pt 0 6pt 10pt; margin: 0 0 8pt;
    border-left: 2pt solid var(--gray-900);
    font-size: 9pt; line-height: 1.5; color: var(--gray-700);
  }}
  .bc .radar-item b:first-child {{ color: var(--gray-900); font-size: 9.5pt; }}
  .bc .radar-item em {{ font-style: italic; }}
  .bc .radar-group {{ break-inside: avoid; }}

  /* ── Disclaimer ── */
  .brief-disc {{
    column-span: all; break-inside: avoid;
    margin-top: 14pt; padding-top: 10pt; border-top: 0.75pt solid var(--gray-200);
    font-family: 'DM Sans', sans-serif; font-size: 6pt; color: var(--gray-400); line-height: 1.5;
    text-align: center;
  }}

  /* ── Tables ── */
  .bc table {{ width: 100%; border-collapse: collapse; margin: 8pt 0; break-inside: avoid; }}
  .bc thead {{ border-bottom: 1.5pt solid var(--gray-900); }}
  .bc th {{
    font-family: 'DM Sans', sans-serif; font-size: 6pt; text-transform: uppercase;
    letter-spacing: 1pt; color: var(--gray-400); text-align: left; padding: 3pt 4pt; font-weight: 500;
  }}
  .bc td {{
    font-family: 'DM Sans', sans-serif; font-size: 8pt; padding: 3pt 4pt;
    border-bottom: 0.75pt solid var(--gray-200); color: var(--gray-700);
  }}
  .bc td:first-child {{
    font-weight: 700; color: var(--gray-900); font-family: 'EB Garamond', serif; font-size: 9pt;
  }}
</style>
</head>
<body>

<div class="pdf-masthead">
  <div class="mast-rule-top"></div>
  <div class="mast-rule-thin"></div>
  <div class="mast-meta">
    <span>Intentional Ownership</span>
    <span>{DATE_DISPLAY}</span>
    <span>Investment Committee</span>
  </div>
  <img class="mast-logo" src="{logo_path}" alt="IOWN">
  <div class="mast-title">The Morning Brief</div>
  <div class="mast-date">{DATE_DISPLAY}</div>
  <div class="mast-rule-bottom"></div>
</div>

<div class="bc">
  <div class="pdf-banner">
    <div class="banner-headline">{meta["headline"]}</div>
    <div class="banner-subhead">{meta["subhead"]}</div>
    <div class="banner-rule"></div>
  </div>

  {html_content}

  <div class="brief-disc">
    For internal IOWN investment committee use only. Not investment advice.
    Information from public sources believed reliable. Past performance not indicative of future results.
    IOWN is an RIA under Paradiem.
  </div>
</div>

</body>
</html>
"""

    doc = weasyprint.HTML(string=wrapper_html)
    doc.write_pdf(pdf_output)
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
    # Ensure we are on main so the brief deploys to GitHub Pages
    current = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, cwd=str(REPO_ROOT)).stdout.strip()
    if current != "main":
        print(f"Switching from '{current}' to 'main' for deploy...")
        subprocess.run(["git", "checkout", "main"], capture_output=True, text=True, cwd=str(REPO_ROOT), check=True)
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], capture_output=True, text=True, cwd=str(REPO_ROOT))

    # Set authenticated remote URL if GITHUB_PUSH_TOKEN is available (from .env)
    push_token = os.environ.get("GITHUB_PUSH_TOKEN", "")
    if push_token:
        subprocess.run(["git", "remote", "set-url", "origin",
                        f"https://{push_token}@github.com/richacarson/rich-report.git"],
                       capture_output=True, text=True, cwd=str(REPO_ROOT))

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
        r = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True, cwd=str(REPO_ROOT))
        if r.returncode == 0:
            print("Pushed to main successfully — deployed to GitHub Pages"); return
        print(f"Push attempt {attempt+1} failed, rebasing...")
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], capture_output=True, text=True, cwd=str(REPO_ROOT))
    print("ERROR: Push to main failed after 3 attempts"); sys.exit(1)

# ═══════════════════════════════════════════
# POST-PROCESS (from Claude Code response file)
# ═══════════════════════════════════════════

def post_process(response_file):
    """Read Claude Code's response from a file and generate PDF/HTML/manifest/git push."""
    print(f"═══ IOWN Morning Brief — Post-Process ═══")
    print(f"Date: {DATE_STR} ({DAY_NAME})")
    print(f"Response file: {response_file}\n")

    response = Path(response_file).read_text(encoding="utf-8")
    print(f"Response: {len(response)} chars")

    print("Processing logo...")
    process_logo()

    print("Parsing...")
    meta, html_content, _ = parse_response(response)
    print(f"Headline: {meta['headline']}")
    print(f"Subhead: {meta['subhead']}")
    print(f"Direction: {meta['direction']}")

    html_out = BRIEFS_DIR / f"{DATE_STR}.html"
    html_out.write_text(html_content, encoding="utf-8")
    print(f"\nHTML: {html_out} ({len(html_content)} chars)")

    print("Generating PDF (weasyprint)...")
    pdf_out = generate_pdf(meta, html_content)
    print(f"PDF: {Path(pdf_out).stat().st_size} bytes")

    update_manifest(meta)

    print("\nPushing...")
    git_commit_and_push(meta)

    print(f"\n═══ Complete: {meta['headline']} ═══")
    print(f"Archive: https://richacarson.github.io/rich-report/morning-briefs.html")

# ═══════════════════════════════════════════
# PREP (output assembled prompt for Claude Code)
# ═══════════════════════════════════════════

def prep():
    """Gather data and print the assembled user prompt to stdout."""
    data_drop = read_file(LATEST_DROP)
    if not data_drop:
        print("ERROR: No data drop", file=sys.stderr); sys.exit(1)
    print(f"Data drop: {len(data_drop)} chars", file=sys.stderr)

    news = fetch_news_headlines()
    print(f"News: {len(news)} chars", file=sys.stderr)

    prev_briefs = get_last_two_briefs()
    print(f"Prior briefs: {[b['date'] for b in prev_briefs]}", file=sys.stderr)

    user_prompt = build_user_prompt(data_drop, news, prev_briefs)
    print(f"Prompt: ~{len(user_prompt)} chars", file=sys.stderr)

    # Print the prompt to stdout for Claude Code to read
    print(user_prompt)

# ═══════════════════════════════════════════
# MAIN (legacy full mode)
# ═══════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="IOWN Morning Brief Generator")
    parser.add_argument("--prep", action="store_true",
                        help="Gather data and print assembled prompt to stdout")
    parser.add_argument("--post-process", metavar="FILE",
                        help="Read response from FILE, generate PDF/HTML/manifest/git push")
    args = parser.parse_args()

    if args.prep:
        prep()
        return

    if args.post_process:
        post_process(args.post_process)
        return

    # Legacy full mode (data gather → Claude API → PDF/HTML/git)
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set (required for legacy mode)"); sys.exit(1)
    print(f"═══ IOWN Morning Brief Generator (Legacy Mode) ═══")
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
    meta, html_content, _ = parse_response(response)
    print(f"Headline: {meta['headline']}")
    print(f"Subhead: {meta['subhead']}")
    print(f"Direction: {meta['direction']}")

    html_out = BRIEFS_DIR / f"{DATE_STR}.html"
    html_out.write_text(html_content, encoding="utf-8")
    print(f"\nHTML: {html_out} ({len(html_content)} chars)")

    print("Generating PDF (weasyprint)...")
    pdf_out = generate_pdf(meta, html_content)
    print(f"PDF: {Path(pdf_out).stat().st_size} bytes")

    update_manifest(meta)

    print("\nPushing...")
    git_commit_and_push(meta)

    print(f"\n═══ Complete: {meta['headline']} ═══")
    print(f"Archive: https://richacarson.github.io/rich-report/morning-briefs.html")

if __name__ == "__main__":
    main()
