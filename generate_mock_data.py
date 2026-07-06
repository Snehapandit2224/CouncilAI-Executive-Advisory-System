import os
import sqlite3
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor

def generate_csv():
    print("Generating CSV data...")
    os.makedirs("data", exist_ok=True)
    data = {
        "Quarter": ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2"],
        "Revenue": [1200000, 1450000, 1600000, 1950000, 1800000, 2100000],
        "Expenses": [850000, 920000, 1050000, 1200000, 1300000, 1400000],
        "Marketing_Spend": [150000, 180000, 220000, 250000, 280000, 300000],
        "CAC": [150, 140, 165, 155, 175, 160],
        "LTV": [600, 650, 680, 720, 700, 750],
        "Risk_Score": [0.12, 0.15, 0.22, 0.18, 0.25, 0.28],
        "Compliance_Status": ["Compliant", "Compliant", "Compliant", "Compliant", "Compliant", "Compliant"]
    }
    df = pd.DataFrame(data)
    df.to_csv("data/quarterly_kpis.csv", index=False)
    print("CSV saved to data/quarterly_kpis.csv")

def generate_db():
    print("Initializing SQLite database...")
    csv_path = "data/quarterly_kpis.csv"
    db_path = "data/business_data.db"
    
    df = pd.read_csv(csv_path)
    conn = sqlite3.connect(db_path)
    df.to_sql("kpis", conn, if_exists="replace", index=False)
    conn.close()
    print(f"SQLite DB initialized at {db_path} with 'kpis' table.")

def generate_pdf():
    print("Generating quarterly business report PDF...")
    pdf_path = "data/quarterly_business_report.pdf"
    doc = SimpleDocTemplate(pdf_path, pagesize=letter,
                            rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54)
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=HexColor('#1E3A8A'),
        spaceAfter=20
    )
    
    h1_style = ParagraphStyle(
        'DocH1',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=HexColor('#0F766E'),
        spaceBefore=15,
        spaceAfter=10
    )
    
    body_style = ParagraphStyle(
        'DocBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10.5,
        leading=15,
        textColor=HexColor('#374151'),
        spaceAfter=12
    )

    story = []
    
    # --- PAGE 1: Cover & Executive Summary ---
    story.append(Paragraph("CouncilAI Executive Business Report", title_style))
    story.append(Paragraph("Quarter: 2026-Q2", ParagraphStyle('Sub', parent=body_style, fontName='Helvetica-Bold', fontSize=12)))
    story.append(Spacer(1, 20))
    story.append(Paragraph("Executive Summary", h1_style))
    story.append(Paragraph(
        "In 2026-Q2, our business experienced strong top-line growth, with revenue reaching $2,100,000, "
        "representing a 16.7% increase quarter-over-quarter. However, operating expenses also scaled to $1,400,000. "
        "The primary strategic focus for the upcoming fiscal quarters is our planned expansion into the Southeast Asia (SEA) market. "
        "The initial baseline projection for the Southeast Asia entry cost is set at $450,000. "
        "This project is critical to maintaining our growth trajectory but presents significant operational and financial challenges "
        "that require multi-agent coordination and executive decision intelligence.",
        body_style
    ))
    story.append(PageBreak())
    
    # --- PAGE 2: Financial Health & Cost Projections ---
    story.append(Paragraph("Financial Performance & Expansion Projections", h1_style))
    story.append(Paragraph(
        "Our financial analysis indicates that the business is highly sensitive to capital expenditure overruns. "
        "If the Southeast Asia entry cost increases above $600,000, our profit margin for 2026-Q3 will drop below our target threshold of 25%. "
        "Conversely, if the entry cost is successfully capped at or below $350,000, the expansion is projected to yield a "
        "highly favorable ROI of 35% in the first fiscal year, accelerating profitability. "
        "The Finance Agent advises caution: domestic reserves are constrained, and any deviation from the initial $450,000 baseline "
        "must be justified by a proportionate increase in market capture or efficiency gains.",
        body_style
    ))
    story.append(PageBreak())
    
    # --- PAGE 3: Marketing Performance & Customer Acquisition ---
    story.append(Paragraph("Marketing Performance & Acquisition Efficiency", h1_style))
    story.append(Paragraph(
        "Marketing spend for 2026-Q2 stood at $300,000. Under current operations, Customer Acquisition Cost (CAC) "
        "is optimized at $160 with a Customer Lifetime Value (LTV) of $750, delivering a strong LTV:CAC ratio of 4.69x. "
        "The Marketing Agent strongly advocates for an aggressive, front-loaded marketing budget for the Southeast Asia expansion. "
        "Marketing argues that establishing early brand dominance is crucial to success in the SEA region. "
        "Even if this increases the overall entry cost, they contend that high customer retention rates in this market will "
        "result in long-term profitability that outweighs the initial expenditure.",
        body_style
    ))
    story.append(PageBreak())
    
    # --- PAGE 4: Risk and Compliance Assessment ---
    story.append(Paragraph("Risk, Regulation & Compliance Assessment", h1_style))
    story.append(Paragraph(
        "The Risk Agent highlights that expanding into Southeast Asia introduces major compliance and regulatory challenges, "
        "particularly regarding local licensing and currency fluctuations. "
        "While our domestic Compliance Status remains 'Compliant' and our Risk Score is relatively low (0.28), "
        "expanding too rapidly could trigger regulatory scrutiny. "
        "The Risk Agent recommends that if the Southeast Asia entry cost exceeds $500,000, the project risk rating "
        "should be upgraded from 'Moderate' to 'High'. High cost exposure could jeopardize domestic cash flow reserves. "
        "A phased rollout is recommended, establishing operations in a single test market before committing full capital resources.",
        body_style
    ))
    
    doc.build(story)
    print(f"PDF saved to {pdf_path}")

if __name__ == "__main__":
    generate_csv()
    generate_pdf()
    generate_db()
    print("Bootstrap completed successfully.")
