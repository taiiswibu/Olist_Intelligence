"""Project skills loaded only for the ERP specialist; permissions stay in code."""
from .config import ROOT

SKILLS = {
    "olist-sales-lookup": ("Tra dữ liệu bán hàng", {"odoo_demo_catalog", "odoo_demo_quotations", "search_odoo_sales", "odoo_sales_taxes"}),
    "olist-quote-review": ("Kiểm tra báo giá", {"review_current_quotation", "read_odoo_quotation"}),
    "olist-quote-pdf": ("Tải báo giá PDF", {"odoo_quotation_document"}),
}
FOLLOWUP_SKILLS = {"olist-customer-followup": "Chăm sóc khách hàng", "olist-followup-check": "Kiểm tra giao việc",
                   "olist-risk-review": "Đối chiếu rủi ro báo giá"}


def read(name):
    import yaml
    if name not in SKILLS and name not in FOLLOWUP_SKILLS:
        raise ValueError("Skill chưa được đăng ký.")
    text = (ROOT / ".agents/skills" / name / "SKILL.md").read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    metadata = yaml.safe_load(front)
    if metadata["name"] != name:
        raise ValueError("Tên skill không khớp đăng ký.")
    return {"name": name, "label": SKILLS[name][0] if name in SKILLS else FOLLOWUP_SKILLS[name], "description": metadata["description"], "instructions": body.strip()}


def catalog(names=None):
    return [{k: v for k, v in read(name).items() if k != "instructions"} for name in (names or SKILLS)]


def instructions(names=None):
    return "\n\n".join(read(name)["instructions"] for name in (names or SKILLS))


def tools():
    return set().union(*(values[1] for values in SKILLS.values()))
