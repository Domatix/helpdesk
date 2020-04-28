{
    "name": "Helpdesk Sale Order",
    "summary": """
        Link between a helpdesk ticket and a sale order""",
    "version": "13.0.1.0.0",
    "license": "AGPL-3",
    "category": "After-Sales",
    "author": "Domatix",
    "website": "https://github.com/Domatix/helpdesk",
    "depends": ["helpdesk_mgmt", "sale"],
    "data": [
        "views/helpdesk_ticket_views.xml",
        "views/helpdesk_ticket_team_views.xml"
    ],
    "installable": True,
    "application": True,
}
