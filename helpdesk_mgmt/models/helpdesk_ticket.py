import random
from datetime import datetime, timedelta

from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError


class HelpdeskTicket(models.Model):
    _name = "helpdesk.ticket"
    _description = "Helpdesk Ticket"
    _rec_name = "number"
    _order = "number desc"
    _inherit = ["mail.thread.cc", "mail.activity.mixin"]

    def _get_default_stage_id(self):
        return self.env["helpdesk.ticket.stage"].search([], limit=1).id

    @api.depends("team_id.auto_assign_type")
    def _compute_automatic_user_assignment(self):
        """
         As the teams can now select an automatic assignment, this method
        is the main entry for that computing, independent of the picked strategy.
        As it stands right now, on 11/05/2020, there are three types of automatic
        assignment and four in total:
         - `manual` - basically the legacy method
         - `random` - balanced random assignation
         - `balanced` - the user with the least not closed assigned tickets
         will be chosen
         - `fixed` - team_id.auto_assigned_fixed_user_id
        :return: user_id: for debugging purposes, as computation methods
        have to assign the value directly to the field
        """
        for record in self:
            user_id = record.user_id
            if record.team_id.auto_assign_type != "manual" and not record.user_id:
                if (
                    record.team_id.auto_assign_type == "fixed"
                    and record.team_id.auto_assign_fixed_user_id
                ):
                    record.user_id = record.team_id.auto_assign_fixed_user_id.id
                elif record.team_id.user_ids and (
                    record.team_id.auto_assign_type == "random"
                    or record.team_id.auto_assign_type == "balanced"
                ):
                    _user_id = record.search_user_id_by_strategy()
                    record.user_id = _user_id.id if _user_id else None
            if isinstance(record.id, int) and record.user_id.id != user_id.id:
                record.send_user_mail()

    @api.depends("team_id")
    def _compute_domain_user_id(self):
        for record in self:
            if record.team_id and record.user_ids:
                helpdesk_team = self.env["res.users"].search(
                    [("id", "in", record.user_ids.ids)]
                )
                record.computed_domain_user_id = [(6, 0, helpdesk_team.ids)]
            else:
                helpdesk_team = self.env["res.users"].search([("share", "=", False)])
                record.computed_domain_user_id = [(6, 0, helpdesk_team.ids)]

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        stage_ids = self.env["helpdesk.ticket.stage"].search([])
        return stage_ids

    number = fields.Char(string="Ticket number", default="/", readonly=True)
    name = fields.Char(string="Title", required=True)
    description = fields.Text(required=True)
    computed_domain_user_id = fields.Many2many(
        "res.users", compute="_compute_domain_user_id"
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Assigned user",
        compute=_compute_automatic_user_assignment,
        store=True,
        readonly=False,
    )
    user_ids = fields.Many2many(
        comodel_name="res.users", related="team_id.user_ids", string="Users"
    )
    stage_id = fields.Many2one(
        comodel_name="helpdesk.ticket.stage",
        string="Stage",
        group_expand="_read_group_stage_ids",
        default=_get_default_stage_id,
        track_visibility="onchange",
        ondelete="restrict",
        index=True,
        copy=False,
    )
    partner_id = fields.Many2one(comodel_name="res.partner", string="Contact")
    partner_name = fields.Char()
    partner_email = fields.Char(string="Email")
    last_stage_update = fields.Datetime(
        string="Last Stage Update", default=fields.Datetime.now
    )
    assigned_date = fields.Datetime(string="Assigned Date")
    closed_date = fields.Datetime(string="Closed Date")
    closed = fields.Boolean(related="stage_id.closed")
    unattended = fields.Boolean(related="stage_id.unattended")
    tag_ids = fields.Many2many(comodel_name="helpdesk.ticket.tag", string="Tags")
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    channel_id = fields.Many2one(
        comodel_name="helpdesk.ticket.channel",
        string="Channel",
        help="Channel indicates where the source of a ticket"
        "comes from (it could be a phone call, an email...)",
    )
    category_id = fields.Many2one(
        comodel_name="helpdesk.ticket.category", string="Category"
    )
    team_id = fields.Many2one(comodel_name="helpdesk.ticket.team", string="Team")
    priority = fields.Selection(
        selection=[
            ("0", _("Low")),
            ("1", _("Medium")),
            ("2", _("High")),
            ("3", _("Very High")),
        ],
        string="Priority",
        default="0",
        track_visibility="onchange",
    )
    attachment_ids = fields.One2many(
        comodel_name="ir.attachment",
        inverse_name="res_id",
        domain=[("res_model", "=", "helpdesk.ticket")],
        string="Media Attachments",
    )
    color = fields.Integer(string="Color Index")
    kanban_state = fields.Selection(
        selection=[
            ("normal", "Default"),
            ("done", "Ready for next stage"),
            ("blocked", "Blocked"),
        ],
        string="Kanban State",
    )
    active = fields.Boolean(default=True)

    auto_last_update = fields.Datetime(
        string="Automatic last update", default=datetime.now()
    )

    ticket_change = fields.Datetime(
        string="Next stage date", compute="_compute_next_stage"
    )

    @api.depends(
        "stage_id.auto_next_number",
        "stage_id.auto_next_type",
        "stage_id.auto_next_stage_id",
    )
    def _compute_next_stage(self):
        for record in self:
            if (
                record.stage_id.auto_next_number
                and record.stage_id.auto_next_type
                and record.stage_id.auto_next_stage_id
            ):
                record.ticket_change = (
                    timedelta(hours=record.stage_id.auto_next_number)
                    + record.auto_last_update
                )
                if record.stage_id.auto_next_type == "day":
                    record.ticket_change = (
                        timedelta(days=record.stage_id.auto_next_number)
                        + record.auto_last_update
                    )
                elif record.stage_id.auto_next_type == "week":
                    record.ticket_change = (
                        timedelta(weeks=record.stage_id.auto_next_number)
                        + record.auto_last_update
                    )

    def _compute_category_domain(self) -> list:
        other_ids = self.env["helpdesk.ticket.category"].search(
            [("team_ids", "=", False)]
        )
        return (
            [("id", "in", list(set((self.team_id.category_ids + other_ids).ids)))]
            if self.team_id
            else None
        )

    def send_user_mail(self):
        template = self.env.ref("helpdesk_mgmt.assignment_email_template")
        self.message_post_with_template(
            template.id, composition_mode="comment", model=self._name, res_id=self.id
        )

    def assign_to_me(self):
        self.write({"user_id": self.env.user.id})

    def search_user_id_by_strategy(self):
        """
         If the assigned team has one of the two balanced strategies, it will search
        the proper member to assigned given that strategy
        :return: selected user_id
        """
        selected_member = random.choice(self.team_id.user_ids)
        if self.team_id.auto_assign_type == "balanced":
            selected_member = min(
                list(
                    map(
                        lambda x: [
                            len(
                                x.ticket_ids.filtered(
                                    lambda x: x.team_id.id == self.team_id.id
                                )
                            ),
                            x,
                        ],
                        self.team_id.user_ids,
                    )
                )
            )
            selected_member = selected_member[1] if selected_member else None
        return selected_member

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            self.partner_name = self.partner_id.name
            self.partner_email = self.partner_id.email

    @api.onchange("team_id", "user_id")
    def _onchange_domain_user_id(self):
        res = {"domain": {"user_id": [("share", "=", False)]}}
        category_ids = self._compute_category_domain()
        if category_ids:
            res["domain"]["category_id"] = category_ids
        if self.team_id and self.team_id.user_ids:
            if self.user_id not in self.team_id.user_ids:
                self.update({"user_id": False})
            res["domain"]["user_id"] = [
                ("id", "in", self.team_id.user_ids.ids),
                ("share", "=", False),
            ]
        return res

    # ---------------------------------------------------
    # CRUD
    # ---------------------------------------------------

    @api.model
    def create(self, vals):
        if vals.get("number", "/") == "/":
            seq = self.env["ir.sequence"]
            if "company_id" in vals:
                seq = seq.with_context(force_company=vals["company_id"])
            vals["number"] = seq.next_by_code("helpdesk.ticket.sequence") or "/"
        res = super().create(vals)

        # Check if mail to the user has to be sent
        if vals.get("user_id") and res:
            res.send_user_mail()
        return res

    def copy(self, default=None):
        self.ensure_one()
        if default is None:
            default = {}
        if "number" not in default:
            default["number"] = (
                self.env["ir.sequence"].next_by_code("helpdesk.ticket.sequence") or "/"
            )
        res = super().copy(default)
        return res

    def write(self, vals):
        for __ in self:
            now = fields.Datetime.now()
            if vals.get("stage_id"):
                stage = self.env["helpdesk.ticket.stage"].browse([vals["stage_id"]])
                vals["last_stage_update"] = now
                if stage.closed:
                    vals["closed_date"] = now
            id_user = vals.get("user_id")
            if id_user:
                vals["assigned_date"] = now

        res = super().write(vals)

        # Check if mail to the user has to be sent
        for ticket in self:
            if vals.get("user_id"):
                ticket.send_user_mail()

        return res

    def action_duplicate_tickets(self):
        for ticket in self.browse(self.env.context["active_ids"]):
            ticket.copy()

    def action_view_picking(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Return Orders",
            "view_mode": "tree",
            "res_model": "stock.picking",
            "domain": [("id", "in", self.picking_ids.ids)],
            "context": "{'create': False}",
        }

    # ---------------------------------------------------
    # Mail gateway
    # ---------------------------------------------------

    def _track_template(self, tracking):
        res = super()._track_template(tracking)
        ticket = self[0]
        if "stage_id" in tracking and ticket.stage_id.mail_template_id:
            res["stage_id"] = (
                ticket.stage_id.mail_template_id,
                {
                    "auto_delete_message": True,
                    "subtype_id": self.env["ir.model.data"].xmlid_to_res_id(
                        "mail.mt_note"
                    ),
                    "email_layout_xmlid": "mail.mail_notification_light",
                },
            )
        return res

    @api.model
    def message_new(self, msg, custom_values=None):
        """Override message_new from mail gateway so we can set correct
        default values.
        """

        if custom_values is None:
            custom_values = {}
        defaults = {
            "name": msg.get("subject") or _("No Subject"),
            "description": msg.get("body"),
            "partner_email": msg.get("from"),
            "partner_id": msg.get("author_id"),
        }
        defaults.update(custom_values)

        # Write default values coming from msg
        ticket = super().message_new(msg, custom_values=defaults)

        # Use mail gateway tools to search for partners to subscribe

        email_list = tools.email_split(
            (msg.get("to") or "") + "," + (msg.get("cc") or "")
        )

        partner_ids = [
            p
            for p in self.env["mail.thread"]._mail_find_partner_from_emails(
                email_list, records=ticket, force_create=False
            )
            if p
        ]

        # `partner_ids` is a python list of `res.partner` records,
        # not an Odoo recordlist, which means a native treatment is necessary

        ticket.message_subscribe(list(set(map(lambda x: x.id, partner_ids))))

        return ticket

    def message_update(self, msg, update_vals=None):
        """ Override message_update to subscribe partners """
        email_list = tools.email_split(
            (msg.get("to") or "") + "," + (msg.get("cc") or "")
        )
        partner_ids = list(
            map(
                lambda x: x.id,
                self.env["mail.thread"]._mail_find_partner_from_emails(
                    email_list, records=self, force_create=False
                ),
            )
        )
        self.message_subscribe(partner_ids)
        stage_id_new = self.env["helpdesk.ticket.stage"].search(
            [("unattended", "=", True), ("closed", "=", False)], limit=1
        )
        self.stage_id = stage_id_new.id if stage_id_new else self.stage_id.id
        return super().message_update(msg, update_vals=update_vals)

    def _message_get_suggested_recipients(self):
        recipients = super()._message_get_suggested_recipients()
        try:
            for ticket in self:
                if ticket.partner_id:
                    ticket._message_add_suggested_recipient(
                        recipients, partner=ticket.partner_id, reason=_("Customer")
                    )
                elif ticket.partner_email:
                    ticket._message_add_suggested_recipient(
                        recipients,
                        email=ticket.partner_email,
                        reason=_("Customer Email"),
                    )
        except AccessError:
            # no read access rights -> just ignore suggested recipients because this
            # imply modifying followers
            pass
        return recipients
