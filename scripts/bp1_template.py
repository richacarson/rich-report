from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, HRFlowable, FrameBreak, NextPageTemplate
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
SAGE = HexColor("#7A8F5A")
ACCENT = HexColor("#8B3A3A")
# Headline color: DG (green) for up days, ACCENT (red) for down days — set in content
HL_COLOR = DG
LGRAY = HexColor("#E8E8E4")
MGRAY = HexColor("#8A8A84")
LRULE = HexColor("#BCBCB4")
W, H = letter
M = 0.65 * inch
GUTTER = 0.22 * inch
COL_W = (W - 2*M - GUTTER) / 2.0
LOGO = "/tmp/iown_logo.png"
EM = chr(8212)
EN = chr(8211)
BUL = chr(8226)
AQ = chr(8217)

class BriefDoc(BaseDocTemplate):
    def __init__(self, fn, **kw):
        BaseDocTemplate.__init__(self, fn, **kw)
        top_off = 1.80 * inch
        f1L = Frame(M, 0.6*inch, COL_W, H - top_off - 0.6*inch, id="p1L", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0)
        f1R = Frame(M + COL_W + GUTTER, 0.6*inch, COL_W, H - top_off - 0.6*inch, id="p1R", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0)
        f2L = Frame(M, 0.6*inch, COL_W, H - 1.2*inch, id="p2L", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0)
        f2R = Frame(M + COL_W + GUTTER, 0.6*inch, COL_W, H - 1.2*inch, id="p2R", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0)
        self.addPageTemplates([
            PageTemplate(id="first", frames=[f1L, f1R], onPage=self.draw_first),
            PageTemplate(id="later", frames=[f2L, f2R], onPage=self.draw_later),
        ])

    def draw_first(self, c, doc):
        c.saveState()
        # === CLEAN WHITE MASTHEAD - logo left, date right ===
        logo_h = 0.55 * inch
        logo_w = logo_h * (1245.0 / 657.0)
        c.drawImage(LOGO, M, H - 0.63*inch, width=logo_w, height=logo_h, mask="auto")
        c.setFillColor(MGRAY)
        c.setFont("Helvetica", 7.5)
        c.drawRightString(W - M, H - 0.50*inch, "MARCH 13, 2026  |  FRIDAY")
        c.drawRightString(W - M, H - 0.62*inch, "INVESTMENT COMMITTEE")
        # Heavy rule under masthead
        rule_y = H - 0.82*inch
        c.setStrokeColor(INK)
        c.setLineWidth(2)
        c.line(M, rule_y, W - M, rule_y)
        # Thin rule just below
        c.setLineWidth(0.5)
        c.line(M, rule_y - 3, W - M, rule_y - 3)
        # Headline area
        c.setFillColor(HL_COLOR)
        c.setFont("DVB", 36)
        hl_y = rule_y - 0.52*inch
        c.drawString(M, hl_y, "2026 Lows")
        c.setFillColor(INK)
        c.setFont("LSI", 11)
        sub_y = hl_y - 0.26*inch
        c.drawString(M, sub_y, "Dow below 47K. S&P \u20131.52%. Brent closes at $100. New supreme leader vows Hormuz stays shut.")
        # Rule below headline
        content_rule_y = sub_y - 0.18*inch
        c.setStrokeColor(INK)
        c.setLineWidth(1)
        c.line(M, content_rule_y, W - M, content_rule_y)
        self._footer(c, doc)
        c.restoreState()

    def draw_later(self, c, doc):
        c.saveState()
        c.setFont("Helvetica", 6.5)
        c.setFillColor(MGRAY)
        hdr = "IOWN MORNING BRIEF " + BUL + " MARCH 13, 2026 " + BUL + " INVESTMENT COMMITTEE"
        c.drawString(M, H - 0.38*inch, hdr)
        c.setStrokeColor(INK)
        c.setLineWidth(0.75)
        c.line(M, H - 0.44*inch, W - M, H - 0.44*inch)
        self._footer(c, doc)
        c.restoreState()

    def _footer(self, c, doc):
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
eh_s = ParagraphStyle("EH", parent=body_s, fontName="Helvetica-Bold", fontSize=8.5, spaceBefore=2, spaceAfter=4)

def sec_rule():
    return HRFlowable(width="100%", thickness=1, color=INK, spaceBefore=2, spaceAfter=8)

def light_rule():
    return HRFlowable(width="100%", thickness=0.4, color=LRULE, spaceBefore=4, spaceAfter=6)

def bottom_box(text):
    inner = ParagraphStyle("BLi", parent=body_s, fontName="LS", fontSize=9, textColor=white, leading=14, alignment=TA_LEFT)
    t = Table([[Paragraph(text, inner)]], colWidths=[COL_W])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),INK),("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),("LEFTPADDING",(0,0),(-1,-1),12),("RIGHTPADDING",(0,0),(-1,-1),12)]))
    return t

