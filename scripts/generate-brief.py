#!/usr/bin/env python3
"""
IOWN Automated Morning Brief Generator
Runs via GitHub Actions at 3:30 AM CT on weekdays.
1. Reads latest-drop.txt (market data from Finnhub)
2. Reads the last two HTML briefs for narrative continuity
3. Calls Claude API to generate brief content (HTML + PDF python code)
4. Writes HTML brief, generates PDF, updates manifest
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
TEMPLATE_PATH = REPO_ROOT / "scripts" / "bp1_template.py"
LOGO_SRC = REPO_ROOT / "scripts" / "IOWN_Logo_1.png"

CT = timezone(timedelta(hours=-6))  # Central Time (CST; CDT would be -5)
TODAY = datetime.now(CT)
DATE_STR = TODAY.strftime("%Y-%m-%d")
DAY_NAME = TODAY.strftime("%A").upper()
DATE_DISPLAY = TODAY.strftime("%B %d, %Y").upper().replace(f" 0", " ")  # "MARCH 17, 2026"
# Fix: strftime doesn't zero-pad day with space, let's just do it cleanly
DATE_DISPLAY = f"{TODAY.strftime('%B').upper()} {TODAY.day}, {TODAY.year}"
DATE_LINE = f"{DATE_DISPLAY}  |  {DAY_NAME}"

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-4-6"

# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════

def read_file(path):
    """Read a file and return its contents, or empty string if missing."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"WARNING: File not found: {path}")
        return ""

def get_last_two_briefs():
    """Get the two most recent HTML briefs by filename date."""
    html_files = sorted(BRIEFS_DIR.glob("2026-*.html"), reverse=True)
    briefs = []
    for f in html_files[:2]:
        briefs.append({"date": f.stem, "content": f.read_text(encoding="utf-8")})
    return briefs

def get_manifest():
    """Read the current manifest."""
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def call_claude_api(system_prompt, user_prompt, max_tokens=16000):
    """Call the Anthropic Messages API."""
    payload = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=payload,
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
            # Extract text from content blocks
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
    """Fetch recent news from Finnhub for IOWN holdings. Uses FINNHUB_KEY env var."""
    finnhub_key = os.environ.get("FINNHUB_KEY")
    if not finnhub_key:
        print("WARNING: FINNHUB_KEY not set, skipping news fetch")
        return ""

    # Fetch general market news
    url = f"https://finnhub.io/api/v1/news?category=general&token={finnhub_key}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            articles = json.loads(resp.read().decode("utf-8"))
            # Take top 15 headlines
            headlines = []
            for art in articles[:15]:
                headline = art.get("headline", "")
                source = art.get("source", "")
                summary = art.get("summary", "")[:200]
                if headline:
                    headlines.append(f"• {headline} ({source}): {summary}")
            return "\n".join(headlines)
    except Exception as e:
        print(f"WARNING: News fetch failed: {e}")
        return ""


# ═══════════════════════════════════════════
# SYSTEM PROMPT FOR CLAUDE
# ═══════════════════════════════════════════

SYSTEM_PROMPT = """You are a senior investment research analyst at Intentional Ownership (IOWN), an RIA managing ~$516M under Paradiem. You write the daily IOWN Morning Brief.

Your writing style is direct, analytical, no fluff. You write like a trusted colleague handing the CIO a one-page briefing sheet. Approximately 5 minutes of reading time. Opinionated and investment-relevant — not raw news aggregation.

IOWN philosophy references (use naturally, don't force):
- Research Reveals Opportunities
- Think Like an Owner
- Avoid Erosion
- Simplicity Over Complexity

IOWN HOLDINGS:
Dividend sleeve: ABT, A, ADI, ATO, ADP, BKH, CAT, CHD, CL, FAST, GD, GPC, LRCX, LMT, MATX, NEE, ORI, PCAR, QCOM, DGX, SSNC, STLD, SYK, TEL, VLO
Growth sleeve: AMD, AEM, ATAT, CVX, CWAN, CNX, COIN, EIX, FINV, FTNT, GFI, SUPV, HRMY, HUT, KEYS, MARA, NVDA, NXPI, OKE, PDD, HOOD, SYF, TSM, TOL
Digital ETFs: IBIT, ETHA
Benchmarks: DVY, IWS, IUSG

KEY RULES:
1. Every brief must advance the narrative from the prior briefs. Do NOT repeat the same themes, phrasing, data points, or radar items unless there is a material update.
2. Output TWO clearly separated blocks:
   - Block 1: HTML brief wrapped in <HTML_BRIEF>...</HTML_BRIEF> tags
   - Block 2: PDF content Python code wrapped in <PDF_CONTENT>...</PDF_CONTENT> tags
3. The HTML brief has THREE content sections: Markets, Geopolitics, On Our Radar
4. The PDF content has THREE sections: MARKETS, GEOPOLITICS, ON OUR RADAR
5. Include a headline (2-3 words max), subhead (one sentence), and direction (up/down) wrapped in <META>...</META> tags as JSON.

HTML FORMAT RULES:
- Start with a snapshot div (S&P 500, Brent, Bitcoin, contextual 4th item, Fear & Greed)
- Use class "up" for green values, "dn" for red
- Use proper HTML entities: &ndash; &mdash; &rsquo; &ldquo; &rdquo; &darr; &uarr; &middot; &amp;
- Section IDs: markets, geopolitics, radar
- Use section-start wrappers, bullet divs, data-box divs, pullquote divs, radar-item divs, radar-group divs
- Radar items 1-2 standalone, 3-4 in a radar-group, 5-6 in a radar-group
- Follow the exact HTML structure pattern from the prior briefs provided

PDF CONTENT CODE RULES:
- This code will be concatenated after bp1_template.py and executed
- Set HL_COLOR = DG for up days, HL_COLOR = ACCENT for down days
- IMPORTANT: Use the variable PDF_PATH (already defined) for the doc path: doc = BriefDoc(PDF_PATH, pagesize=letter)
- story = [NextPageTemplate("later")]
- Define EM, EN, AQ variables for typography
- Use styles: sec_s, sec_rule(), lead_s, body_s, pq_s, radar_s, small_s
- Spacer(1, 14) between sections
- End with disclaimer paragraph and doc.build(story)
- Use f-strings with {EM}, {EN}, {AQ} for dashes and apostrophes
- Use &amp; for ampersands in Paragraph text
"""

# ═══════════════════════════════════════════
# BUILD THE USER PROMPT
# ═══════════════════════════════════════════

def build_user_prompt(data_drop, news, prev_briefs):
    """Construct the user prompt with all context."""

    prev_briefs_text = ""
    for b in prev_briefs:
        prev_briefs_text += f"\n--- PRIOR BRIEF ({b['date']}) ---\n{b['content']}\n"

    return f"""Today is {DATE_LINE}. Generate the IOWN Morning Brief for today.

<DATA_DROP>
{data_drop}
</DATA_DROP>

<NEWS_HEADLINES>
{news if news else "No additional news headlines available. Use data drop and your knowledge."}
</NEWS_HEADLINES>

<PRIOR_BRIEFS>
{prev_briefs_text}
</PRIOR_BRIEFS>

Instructions:
1. Analyze the data drop for market moves, sector performance, holdings performance, crypto, rates, commodities.
2. Cross-reference with news headlines for geopolitical/macro context.
3. Read the prior briefs carefully — do NOT repeat themes, phrasing, or radar items. Advance the narrative.
4. Generate the brief in three output blocks:

<META> block: JSON with "headline" (2-3 words), "subhead" (one sentence), "direction" ("up" or "down")

<HTML_BRIEF> block: Full HTML content for briefs/{DATE_STR}.html following the exact structure pattern from prior briefs.

<PDF_CONTENT> block: Python code that will be concatenated after bp1_template.py. A variable PDF_PATH is already defined with the correct output path. Use: doc = BriefDoc(PDF_PATH, pagesize=letter)

The headline and subhead in the PDF template's draw_first() method will be set separately — your PDF content code should ONLY contain the story content (from "HL_COLOR = ..." through "doc.build(story)"). Do NOT include the template code or class definitions.

Remember: Be opinionated. Include technical indicators where relevant. The brief should read as one cohesive argument across all three sections."""

# ═══════════════════════════════════════════
# PARSE CLAUDE'S RESPONSE
# ═══════════════════════════════════════════

def parse_response(response_text):
    """Extract META, HTML_BRIEF, and PDF_CONTENT blocks from Claude's response."""

    meta_match = re.search(r"<META>(.*?)</META>", response_text, re.DOTALL)
    html_match = re.search(r"<HTML_BRIEF>(.*?)</HTML_BRIEF>", response_text, re.DOTALL)
    pdf_match = re.search(r"<PDF_CONTENT>(.*?)</PDF_CONTENT>", response_text, re.DOTALL)

    if not all([meta_match, html_match, pdf_match]):
        print("ERROR: Could not parse all three blocks from Claude's response")
        print(f"META found: {bool(meta_match)}")
        print(f"HTML found: {bool(html_match)}")
        print(f"PDF found: {bool(pdf_match)}")
        # Save raw response for debugging
        debug_path = REPO_ROOT / "debug_response.txt"
        debug_path.write_text(response_text, encoding="utf-8")
        print(f"Raw response saved to {debug_path}")
        sys.exit(1)

    meta = json.loads(meta_match.group(1).strip())
    html = html_match.group(1).strip()
    pdf_content = pdf_match.group(1).strip()

    # Strip markdown code fences if present
    if pdf_content.startswith("```python"):
        pdf_content = pdf_content[len("```python"):].strip()
    if pdf_content.startswith("```"):
        pdf_content = pdf_content[3:].strip()
    if pdf_content.endswith("```"):
        pdf_content = pdf_content[:-3].strip()

    return meta, html, pdf_content


# ═══════════════════════════════════════════
# PDF GENERATION
# ═══════════════════════════════════════════

def generate_pdf(meta, pdf_content):
    """Generate the PDF by modifying the template and concatenating content."""

    # Read template
    template = read_file(TEMPLATE_PATH)
    if not template:
        print("ERROR: Could not read bp1_template.py")
        sys.exit(1)

    # Modify template dates and headline
    headline = meta["headline"]
    subhead = meta["subhead"]
    direction = meta["direction"]

    # Replace date in draw_first
    template = re.sub(
        r'c\.drawRightString\(W - M, H - 0\.50\*inch, ".*?"\)',
        f'c.drawRightString(W - M, H - 0.50*inch, "{DATE_LINE}")',
        template
    )

    # Replace INVESTMENT COMMITTEE line date (it's static, keep as is)

    # Replace headline
    template = re.sub(
        r'c\.drawString\(M, hl_y, ".*?"\)',
        f'c.drawString(M, hl_y, "{headline}")',
        template
    )

    # Replace subhead
    # Need to escape special chars for the replacement
    safe_subhead = subhead.replace('"', '\\"').replace("'", "\\'")
    template = re.sub(
        r'c\.drawString\(M, sub_y, ".*?"\)',
        f'c.drawString(M, sub_y, "{safe_subhead}")',
        template
    )

    # Replace draw_later header date
    brief_date_str = f"{TODAY.strftime('%B').upper()} {TODAY.day}, {TODAY.year}"
    template = re.sub(
        r'hdr = "IOWN MORNING BRIEF " \+ BUL \+ " .*? " \+ BUL \+ " INVESTMENT COMMITTEE"',
        f'hdr = "IOWN MORNING BRIEF " + BUL + " {brief_date_str} " + BUL + " INVESTMENT COMMITTEE"',
        template
    )

    # Replace the logo path to use the one in scripts/
    template = template.replace(
        'LOGO = "/tmp/iown_logo.png"',
        f'LOGO = "{str(REPO_ROOT / "scripts" / "iown_logo_processed.png")}"'
    )

    # Write modified template
    template_out = REPO_ROOT / "bp1_template_auto.py"
    template_out.write_text(template, encoding="utf-8")

    # Sanitize content: ensure PDF path is resolved regardless of what Claude used
    pdf_output_path = str(BRIEFS_DIR / f"IOWN_Morning_Brief_{DATE_STR}.pdf")
    # Inject PDF_PATH definition at the top of content so any reference works
    pdf_content_final = f'PDF_PATH = "{pdf_output_path}"\n\n' + pdf_content
    # Also replace any hardcoded placeholder paths Claude might have used
    pdf_content_final = pdf_content_final.replace("<PDF_PATH>", pdf_output_path)

    # Write content
    content_out = REPO_ROOT / "bp1_content_auto.py"
    content_out.write_text(pdf_content_final, encoding="utf-8")

    # Concatenate and run
    combined = REPO_ROOT / "bp1_auto.py"
    combined_text = template_out.read_text() + "\n" + content_out.read_text()
    combined.write_text(combined_text, encoding="utf-8")

    result = subprocess.run(
        ["python3", str(combined)],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )

    if result.returncode != 0:
        print(f"PDF generation FAILED:\n{result.stderr}")
        # Save for debugging
        print(f"Combined script at: {combined}")
        sys.exit(1)

    print(f"PDF generated: {result.stdout.strip()}")

    # Cleanup temp files
    for f in [template_out, content_out, combined]:
        f.unlink(missing_ok=True)


def process_logo():
    """Process the IOWN logo (remove dark background, crop)."""
    logo_processed = REPO_ROOT / "scripts" / "iown_logo_processed.png"

    if logo_processed.exists():
        print("Logo already processed, skipping")
        return

    if not LOGO_SRC.exists():
        print(f"ERROR: Logo source not found at {LOGO_SRC}")
        sys.exit(1)

    try:
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
    except ImportError:
        print("ERROR: Pillow/numpy not available for logo processing")
        sys.exit(1)


# ═══════════════════════════════════════════
# MANIFEST UPDATE
# ═══════════════════════════════════════════

def update_manifest(meta):
    """Add today's entry to manifest.json."""
    manifest = get_manifest()

    # Remove existing entry for today if any
    manifest = [e for e in manifest if e.get("date") != DATE_STR]

    manifest.append({
        "date": DATE_STR,
        "headline": meta["headline"],
        "subhead": meta["subhead"],
        "direction": meta["direction"],
        "filename": f"IOWN_Morning_Brief_{DATE_STR}.pdf"
    })

    # Sort by date
    manifest.sort(key=lambda e: e["date"])

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )
    print(f"Manifest updated with entry for {DATE_STR}")


# ═══════════════════════════════════════════
# GIT OPERATIONS
# ═══════════════════════════════════════════

def git_commit_and_push(meta):
    """Commit the new brief files and push."""
    html_file = f"briefs/{DATE_STR}.html"
    pdf_file = f"briefs/IOWN_Morning_Brief_{DATE_STR}.pdf"
    manifest_file = "briefs/manifest.json"

    cmds = [
        ["git", "add", html_file, pdf_file, manifest_file],
        ["git", "commit", "-m", f"IOWN Morning Brief — {TODAY.strftime('%B')} {TODAY.day}, {TODAY.year}: {meta['headline']}"],
    ]

    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if result.returncode != 0:
            print(f"Git command failed: {' '.join(cmd)}")
            print(result.stderr)
            if "nothing to commit" in result.stdout + result.stderr:
                print("Nothing to commit — files may already be up to date")
                return
            sys.exit(1)

    # Push with retry on rejection
    for attempt in range(3):
        result = subprocess.run(
            ["git", "push"], capture_output=True, text=True, cwd=str(REPO_ROOT)
        )
        if result.returncode == 0:
            print("Pushed successfully")
            return
        print(f"Push attempt {attempt+1} failed, trying rebase...")
        subprocess.run(
            ["git", "pull", "--rebase"], capture_output=True, text=True, cwd=str(REPO_ROOT)
        )

    print("ERROR: Failed to push after 3 attempts")
    sys.exit(1)


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════

def main():
    print(f"═══ IOWN Morning Brief Generator ═══")
    print(f"Date: {DATE_STR} ({DAY_NAME})")
    print()

    # Check if brief already exists (skip unless FORCE_REGENERATE is set)
    html_path = BRIEFS_DIR / f"{DATE_STR}.html"
    pdf_path = BRIEFS_DIR / f"IOWN_Morning_Brief_{DATE_STR}.pdf"
    if html_path.exists() and pdf_path.exists() and not os.environ.get("FORCE_REGENERATE"):
        print(f"Brief already exists for {DATE_STR}. Set FORCE_REGENERATE=1 to overwrite.")
        print("Exiting cleanly.")
        sys.exit(0)

    # 1. Read data drop
    data_drop = read_file(LATEST_DROP)
    if not data_drop:
        print("ERROR: No data drop available")
        sys.exit(1)
    print(f"Data drop loaded: {len(data_drop)} chars")

    # Check data drop freshness
    first_line = data_drop.split("\n")[0]
    print(f"Data drop header: {first_line}")

    # 2. Fetch news
    print("Fetching news headlines...")
    news = fetch_news_headlines()
    print(f"News: {len(news)} chars")

    # 3. Read last two briefs
    prev_briefs = get_last_two_briefs()
    print(f"Prior briefs loaded: {[b['date'] for b in prev_briefs]}")

    # 4. Process logo
    print("Processing logo...")
    process_logo()

    # 5. Call Claude API
    print(f"\nCalling Claude API ({MODEL})...")
    user_prompt = build_user_prompt(data_drop, news, prev_briefs)
    print(f"Prompt size: ~{len(user_prompt)} chars")

    response = call_claude_api(SYSTEM_PROMPT, user_prompt)
    print(f"Response received: {len(response)} chars")

    # 6. Parse response
    print("\nParsing response...")
    meta, html_content, pdf_content = parse_response(response)
    print(f"Headline: {meta['headline']}")
    print(f"Subhead: {meta['subhead']}")
    print(f"Direction: {meta['direction']}")

    # 7. Write HTML
    html_path = BRIEFS_DIR / f"{DATE_STR}.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"\nHTML written: {html_path} ({len(html_content)} chars)")

    # 8. Generate PDF
    print("\nGenerating PDF...")
    generate_pdf(meta, pdf_content)

    pdf_path = BRIEFS_DIR / f"IOWN_Morning_Brief_{DATE_STR}.pdf"
    if pdf_path.exists():
        print(f"PDF verified: {pdf_path} ({pdf_path.stat().st_size} bytes)")
    else:
        print("ERROR: PDF was not created")
        sys.exit(1)

    # 9. Update manifest
    update_manifest(meta)

    # 10. Commit and push
    print("\nCommitting and pushing...")
    git_commit_and_push(meta)

    print(f"\n═══ Brief complete: {meta['headline']} ═══")
    print(f"Archive: https://richacarson.github.io/rich-report/morning-briefs.html")


if __name__ == "__main__":
    main()
