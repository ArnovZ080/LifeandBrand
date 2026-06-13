"""
Canonical task list for the AM Operating Structure.
Matches the PDF (Ver 1 – 02/2026) exactly.
Call seed_tasks() once on startup — it is idempotent.
"""

from sqlalchemy.orm import Session
from app.models.am_checklist import AMChecklistTask, ChecklistFrequency

TASKS: list[tuple[ChecklistFrequency, int, str]] = [
    # (frequency, order, title)

    # ── Daily ────────────────────────────────────────────────────────────────
    (ChecklistFrequency.DAILY, 1, "Daily Operations Visit Reports done on each store visit – Operational Readiness & Standards Maintained"),
    (ChecklistFrequency.DAILY, 2, "Maintenance walk – KF update and Follow up the following week"),
    (ChecklistFrequency.DAILY, 3, "COS Update, Validation and Report per store on a visit"),
    (ChecklistFrequency.DAILY, 4, "AM Weekly Briefing on In-Store Training Topics for Each Day"),
    (ChecklistFrequency.DAILY, 5, "Complaint Tracker Update, Feedback and Focus Discussions"),
    (ChecklistFrequency.DAILY, 6, "Recognition of Staff & Management when in store on Successes Achieved"),
    (ChecklistFrequency.DAILY, 7, "Echovia Daily Check on all Stores for CSR"),
    (ChecklistFrequency.DAILY, 8, "Labour Tracker completion Every day for all Stores"),
    (ChecklistFrequency.DAILY, 9, "AM Sales Tracker to be completed Daily"),

    # ── Weekly ───────────────────────────────────────────────────────────────
    (ChecklistFrequency.WEEKLY, 1,  "Support Office OPS Meetings – Monday @ 08h30 – General Operations"),
    (ChecklistFrequency.WEEKLY, 2,  "Support Office OPS Catch Up Meeting – Tuesday @ 08h30 – General Operations"),
    (ChecklistFrequency.WEEKLY, 3,  "Support Office OPS Catch Up Meeting – Wednesday @ 08h30 Marketing Meetings – Plan discussion points, Focus needed from Team, Expectations & Feedback on Support Needed"),
    (ChecklistFrequency.WEEKLY, 4,  "Bi-Weekly GM Meeting to be held to Align all to standards and expectations – Can be via Teams or Skype"),
    (ChecklistFrequency.WEEKLY, 5,  "Reporting and Sign off on Each Restaurant Schedules to be in line with Labour Budgets – DONE BY WEDNESDAY COB"),
    (ChecklistFrequency.WEEKLY, 6,  "Weekly Operations Report – Sunday Evenings / Monday Mornings before 08h00"),
    (ChecklistFrequency.WEEKLY, 7,  "Weekly Complaint Tracker – Update and Report with Monday reports"),
    (ChecklistFrequency.WEEKLY, 8,  "Weekly Alignment Meeting with Brand Chef: Issues, Complaint Concerns, Focus points for the Week, Special Projects & Schedules"),
    (ChecklistFrequency.WEEKLY, 9,  "TUESDAY by 16h00 – COS Sign off"),
    (ChecklistFrequency.WEEKLY, 10, "Saturday & Sunday – Store reports of previous day sent between 08h00 & 08h30"),
    (ChecklistFrequency.WEEKLY, 11, "Regional Lead Meeting – Store based after Monday OPS meeting"),
    (ChecklistFrequency.WEEKLY, 12, "AM Roster Sign off – Done by Friday COB for the following week"),
    (ChecklistFrequency.WEEKLY, 13, "IT & Security Checklist – Done every Sunday by COB latest"),
    (ChecklistFrequency.WEEKLY, 14, "Marketing Meeting with each AM – Scheduled on Tuesday at different times"),
    (ChecklistFrequency.WEEKLY, 15, "Labour Tracker & Summary to OPS Manager – Accurate Labour summary report sent before Monday 09h00 – Every Week"),

    # ── Monthly ──────────────────────────────────────────────────────────────
    (ChecklistFrequency.MONTHLY, 1, "Team Bench Planning with GM and plans moving forward – Succession & Risk"),
    (ChecklistFrequency.MONTHLY, 2, "Financial Management Accounts Meeting with MD – Planning, Understanding and Action to Improve – Every Month 2 Different GMs to sit in on their account discussion"),
    (ChecklistFrequency.MONTHLY, 3, "HR/Payroll Sign off to be done on time with no delay from ANY store"),
    (ChecklistFrequency.MONTHLY, 4, "Attend 1 x FOH and 1 x BOH Meeting per store during the month and have the agendas available"),
    (ChecklistFrequency.MONTHLY, 5, "GM KPI Meeting to discuss Concerns, Progress on Performance and What support they need"),
    (ChecklistFrequency.MONTHLY, 6, "Monthly Alignment with Brand Chef on goals for the next month and achievements of the previous"),
    (ChecklistFrequency.MONTHLY, 7, "Doing 5 Staff One-on-One Meetings in a month per store to build relationship and monitor staff happiness in the business"),
    (ChecklistFrequency.MONTHLY, 8, "Booking of Counts – Must be done by AM at month end"),
    (ChecklistFrequency.MONTHLY, 9, "Marketing Brief – Done by the first week of each month and sent to marketing department"),

    # ── Ad Hoc ───────────────────────────────────────────────────────────────
    (ChecklistFrequency.ADHOC, 1, "Approval of Quotes for Events and Big Bookings"),
    (ChecklistFrequency.ADHOC, 2, "Relationship Building with External Service Providers"),
    (ChecklistFrequency.ADHOC, 3, "Relationship Building with Support Office Departments"),
    (ChecklistFrequency.ADHOC, 4, "HR Assistance in Hearings and Disciplining of Teams"),
    (ChecklistFrequency.ADHOC, 5, "New Store Openings and Planning"),
]


def seed_tasks(db: Session) -> None:
    """Idempotent — only inserts tasks that don't already exist by title."""
    existing_titles = {t.title for t in db.query(AMChecklistTask.title).all()}
    new_tasks = [
        AMChecklistTask(frequency=freq, order_num=order, title=title)
        for freq, order, title in TASKS
        if title not in existing_titles
    ]
    if new_tasks:
        db.add_all(new_tasks)
        db.commit()
