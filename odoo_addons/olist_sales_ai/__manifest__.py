{
    "name": "AI hỗ trợ bán hàng",
    "version": "19.0.1.6.0",
    "category": "Sales",
    "summary": "Ưu tiên chăm sóc khách và duyệt giao việc từ đề xuất AI",
    "license": "LGPL-3",
    "depends": ["sale_management", "mail"],
    "data": ["security/ir.model.access.csv", "security/rules.xml", "views/followup.xml", "views/risk.xml", "reports/risk.xml", "views/product_advisor.xml"],
    "assets": {"web.assets_backend": ["olist_sales_ai/static/src/status.js"]},
    "application": True,
    "installable": True,
}
