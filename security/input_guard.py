import os

def validate_input(user_input: str) -> tuple[bool, str]:
    """Sanitizes input prompts and checks for prompt injection or hazardous keywords.
    
    Args:
        user_input: The text string to validate.
        
    Returns:
        A tuple of (is_safe, error_message).
    """
    if not user_input:
        return True, ""
        
    input_lower = user_input.lower()
    
    # 1. Prompt Injection Checks
    injection_signatures = [
        "ignore previous instructions",
        "ignore the instructions",
        "system override",
        "bypass safety",
        "forget my instructions",
        "forget your instructions",
        "you are now",
        "acting as",
        "jailbreak",
        "developer mode",
    ]
    
    for signature in injection_signatures:
        if signature in input_lower:
            return False, f"Blocked: Potential prompt injection signature detected ('{signature}')"
            
    # 2. SQL Injection / Destructive Checks (for sqlite_tool query verification)
    # Using regex word boundaries to prevent false-positives on standard English phrases
    import re
    destructive_sql = [
        r"\bdrop\s+table\b",
        r"\bdelete\s+from\b",
        r"\btruncate\s+table\b",
        r"\balter\s+table\b",
        r"\binsert\s+into\b",
        r"\bupdate\s+kpis\b",
        r"\bdrop\s+database\b",
        r"\bdb\.sqlite\b"
    ]
    
    for signature in destructive_sql:
        if re.search(signature, input_lower):
            return False, f"Blocked: Destructive SQL keywords detected matching signature '{signature}'"
            
    # 3. Domain Relevance Check (blocks out-of-scope topics for short query inputs)
    if len(user_input) < 300:
        out_of_scope_topics = ["mars", "moon", "jupiter", "space", "recipe", "joke", "banana", "weather", "song"]
        for topic in out_of_scope_topics:
            if topic in input_lower:
                return False, f"Blocked: Query topic '{topic}' is out of scope. Please ask a business decision query related to NimbusFlow expansion or financial KPIs."

    return True, ""

def validate_relevance_to_pdf(query: str, pdf_path: str) -> tuple[bool, str]:
    """Checks if the user's decision question is relevant to the active PDF report.
    Specifically checks if the query refers to the correct company and region found in the PDF.
    """
    if not os.path.exists(pdf_path):
        return True, ""
        
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        pdf_text = ""
        # Extract first 2 pages (sufficient for headers/executive summaries)
        for i in range(min(2, len(reader.pages))):
            pdf_text += reader.pages[i].extract_text() or ""
            
        pdf_text_lower = pdf_text.lower()
        query_lower = query.lower()
        
        # 1. Company Name check
        companies = ["nimbusflow", "taskforge"]
        active_company = None
        for company in companies:
            if company in pdf_text_lower:
                active_company = company
                break
                
        if active_company:
            if active_company not in query_lower:
                wrong_companies = [c for c in companies if c != active_company]
                for wc in wrong_companies:
                    if wc in query_lower:
                        return False, f"Blocked: Query refers to '{wc.capitalize()}' but the active business report is for '{active_company.capitalize()}'."
                return False, f"Blocked: Please mention the active company name ('{active_company.capitalize()}') in your query to align with the uploaded business report."
                
        # 2. Target Region check
        regions = {
            "Southeast Asia": ["southeast asia", "sea", "asia", "singapore", "vietnam", "thailand"],
            "Latin America": ["latin america", "latam", "brazil", "mexico", "portuguese", "spanish"]
        }
        
        active_region = None
        for reg_name, keywords in regions.items():
            for kw in keywords:
                if kw in pdf_text_lower:
                    active_region = reg_name
                    break
            if active_region:
                break
                
        if active_region:
            has_keyword = any(kw in query_lower for kw in regions[active_region])
            if not has_keyword:
                wrong_regions = [r for r in regions.keys() if r != active_region]
                for wr in wrong_regions:
                    if any(kw in query_lower for kw in regions[wr]):
                        return False, f"Blocked: Query refers to the '{wr}' region, but the active business report target is '{active_region}'."
                return False, f"Blocked: Please mention the correct target region ('{active_region}') in your query to align with the uploaded report."
                
    except Exception:
        return True, ""
        
    return True, ""
