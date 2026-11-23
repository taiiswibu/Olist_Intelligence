"""Conservative checks for known Vietnamese follow-up errors, not a semantic proof."""
import re
import unicodedata

VERSION = "followup-grounding-v2"


def normalize(text):
    text = unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
    text = "".join(c for c in text if not unicodedata.combining(c) and unicodedata.category(c) != "Cf")
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", text).split())


def issues(draft, cases):
    """Return finite issue codes only; never put customer text into diagnostics."""
    known = {c.case_id: c for c in cases}
    findings = []
    for item in draft.items:
        case = known[item.case_id]
        fields = [normalize(getattr(item, key)) for key in ("summary", "note", "explanation")]
        codes = set()
        for text in fields:
            if case.quotation_state == "draft" and re.search(r"\bda (?:duoc )?gui\b|\bgui lai\b", text):
                codes.add("unsupported_draft_send_history")
            if re.search(r"\b(?:hoat dong|cong viec|lich viec)(?: [a-z]+){0,3} da (?:duoc )?(?:thuc hien|hoan thanh)\b", text):
                codes.add("unknown_activity_completion")
            if re.search(r"\bda co (?:lich viec|cong viec|hoat dong) tuong tu\b", text):
                codes.add("unknown_activity_similarity")
        # An explicit question about unknown feedback is not an assertion that it happened.
        # Check each sentence separately so a later question cannot hide an earlier claim.
        for original in (item.summary, item.note, item.explanation):
            for match in re.finditer(r"([^.!?;\n]+)([.!?;\n]|$)", original):
                text, ending = normalize(match[1]), match[2]
                query = ending == "?" and bool(re.fullmatch(
                    r"(?:(?:xin hoi )?(?:khach(?: hang)?|anh chi|anh|chi|minh) )?(?:da )?"
                    r"(?:phan hoi|tra loi|nhan (?:duoc )?phan hoi) (?:chua|khong)(?: a)?", text))
                if not query and (re.search(r"\b(?:da|chua|khong) (?:co |nhan (?:duoc )?)phan hoi\b", text) or
                        re.search(r"\bkhach(?: hang)? (?:van )?(?:da|chua) (?:tra loi|phan hoi)\b", text)):
                    codes.add("unknown_feedback_history")
        if item.action == "review_existing_activity":
            note = fields[1]
            if not (re.search(r"\b(?:ra soat|kiem tra|xem lai|doi chieu)\b", note) and
                    re.search(r"\b(?:lich viec|cong viec|hoat dong|viec dang hen|viec dang cho)\b", note)):
                codes.add("existing_activity_review_missing")
        if codes:
            findings.append({"case_id": item.case_id, "codes": sorted(codes)})
    return findings


def audit(draft, cases):
    findings = issues(draft, cases)
    return {"version": VERSION, "checked_items": len(draft.items),
            "status": "rejected" if findings else "passed", "findings": findings}
