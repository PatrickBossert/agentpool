# api/routers/pam_report.py
"""
PAM status report endpoint.

Derives a structured project health report from live DB state — no LLM call.
All risk and issue judgements are computed from milestones, crew runs, reviews,
interview sessions, and uploaded documents.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone, date as date_t
from fastapi import APIRouter, Depends
from api.auth import require_any_auth
from api.database import get_connection

router = APIRouter(prefix="/projects/{slug}/pam-report", tags=["pam-report"])

CREW_ORDER = [
    'discovery_mapping',
    'stakeholder_management',
    'assessment_design',
    'discovery_interviews',
    'discovery',
    'value_design',
    'architecture',
    'delivery',
    'business_plan',
]

CREW_LABELS = {
    'discovery_mapping':      'Value Chain Mapping',
    'assessment_design':      'Assessment Design',
    'discovery':              'Discovery',
    'stakeholder_management': 'Stakeholder Management',
    'discovery_interviews':   'Discovery Interviews',
    'value_design':           'Value Design',
    'architecture':           'Architecture',
    'delivery':               'Delivery',
    'business_plan':          'Business Plan',
}


def _today() -> str:
    return date_t.today().isoformat()


def _days_delta(due_date: str | None) -> int | None:
    if not due_date:
        return None
    try:
        delta = (date_t.fromisoformat(due_date) - date_t.today()).days
        return delta
    except ValueError:
        return None


def _milestone_rag(m: dict) -> str:
    if m['status'] == 'complete':
        return 'complete'
    due = m.get('due_date')
    if not due:
        return 'unscheduled'
    delta = _days_delta(due)
    if delta is None:
        return 'unscheduled'
    if delta < 0:
        return 'overdue'
    if delta <= 3:
        return 'due_soon'
    return 'on_track'


@router.get("")
async def get_pam_report(slug: str, payload: dict = Depends(require_any_auth)):
    today = _today()

    async with get_connection(slug) as conn:
        # ── Project ────────────────────────────────────────────────────────────
        async with conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)) as cur:
            project = dict(await cur.fetchone() or {})
        config = json.loads(project.get('config_json') or '{}')
        sector = project.get('sector', '')
        client_name = config.get('client_name', slug)

        # ── Milestones ─────────────────────────────────────────────────────────
        async with conn.execute(
            "SELECT * FROM project_milestones WHERE slug=? ORDER BY sort_order, id", (slug,)
        ) as cur:
            milestones = [dict(r) for r in await cur.fetchall()]

        # ── Crew runs (latest per crew) ────────────────────────────────────────
        async with conn.execute(
            "SELECT * FROM crew_runs ORDER BY id DESC"
        ) as cur:
            all_runs = [dict(r) for r in await cur.fetchall()]

        latest_run: dict[str, dict] = {}
        run_counts: dict[str, int] = {}
        for r in all_runs:
            cn = r['crew_name']
            run_counts[cn] = run_counts.get(cn, 0) + 1
            if cn not in latest_run:
                latest_run[cn] = r

        # ── Outputs ────────────────────────────────────────────────────────────
        async with conn.execute(
            "SELECT agent_name, output_type, review_status, is_current FROM agent_outputs WHERE is_current=1"
        ) as cur:
            outputs = [dict(r) for r in await cur.fetchall()]

        # outputs per crew (approximate by agent_name snake_case)
        CREW_AGENT_KEYS: dict[str, list[str]] = {
            'discovery_mapping':      ['value_chain_mapper'],
            'assessment_design':      ['interaction_designer'],
            'discovery':              ['requirements_capture', 'requirements_analyst', 'value_lever_analyst'],
            'stakeholder_management': ['stakeholder_manager'],
            'discovery_interviews':   ['interview_coordinator', 'stakeholder_interviewer', 'synthesis_analyst'],
            'value_design':           ['value_proposition_generator', 'portfolio_manager'],
            'architecture':           ['enterprise_architect', 'initiative_identifier'],
            'delivery':               ['roadmap_generator', 'visual_illustrator'],
            'business_plan':          ['business_plan_generator'],
        }
        INTERNAL_TYPES = {'value_chain_tree', 'value_chain_registry', 'value_chain_summary', 'state'}

        def _crew_outputs(crew_key: str) -> list[dict]:
            keys = set(CREW_AGENT_KEYS.get(crew_key, []))
            return [o for o in outputs if o['agent_name'] in keys and o['output_type'] not in INTERNAL_TYPES]

        # ── Human reviews ──────────────────────────────────────────────────────
        async with conn.execute(
            "SELECT hr.*, cr.crew_name, hr.reviewed_at as created_at_hr "
            "FROM human_reviews hr "
            "LEFT JOIN crew_runs cr ON cr.id = hr.crew_run_id "
            "WHERE hr.decision = 'pending'"
        ) as cur:
            pending_reviews = [dict(r) for r in await cur.fetchall()]

        # ── Interview sessions ─────────────────────────────────────────────────
        async with conn.execute(
            "SELECT status, COUNT(*) as cnt FROM interview_sessions GROUP BY status"
        ) as cur:
            session_rows = {r['status']: r['cnt'] for r in await cur.fetchall()}

        async with conn.execute("SELECT COUNT(*) as cnt FROM stakeholders") as cur:
            stakeholder_count = (await cur.fetchone())['cnt']

        async with conn.execute("SELECT COUNT(*) as cnt FROM client_documents") as cur:
            doc_count = (await cur.fetchone())['cnt']

    # ── Derive per-crew status ─────────────────────────────────────────────────
    crews = []
    for ck in CREW_ORDER:
        run = latest_run.get(ck)
        co = _crew_outputs(ck)
        pending_for_crew = [r for r in pending_reviews if r.get('crew_name') == ck]
        crews.append({
            'crew_key':        ck,
            'crew_label':      CREW_LABELS.get(ck, ck),
            'status':          run['status'] if run else 'not_started',
            'last_run_at':     run['started_at'] if run else None,
            'finished_at':     run.get('finished_at') if run else None,
            'run_count':       run_counts.get(ck, 0),
            'outputs_count':   len(co),
            'output_types':    [o['output_type'] for o in co],
            'pending_reviews': len(pending_for_crew),
            'error_detail':    run.get('error_detail') if run and run['status'] == 'failed' else None,
        })

    # ── Milestone summary ──────────────────────────────────────────────────────
    ms_enriched = []
    for m in milestones:
        rag = _milestone_rag(m)
        delta = _days_delta(m.get('due_date'))
        ms_enriched.append({**m, 'rag': rag, 'days_delta': delta})

    ms_complete   = sum(1 for m in ms_enriched if m['rag'] == 'complete')
    ms_overdue    = [m for m in ms_enriched if m['rag'] == 'overdue']
    ms_due_soon   = [m for m in ms_enriched if m['rag'] == 'due_soon']
    ms_total      = len(ms_enriched)
    ms_scheduled  = sum(1 for m in ms_enriched if m.get('due_date'))

    # ── Interview summary ──────────────────────────────────────────────────────
    sessions_complete  = session_rows.get('completed', 0)
    sessions_active    = session_rows.get('active', 0)
    sessions_pending   = session_rows.get('pending', 0)
    sessions_abandoned = session_rows.get('abandoned', 0)
    sessions_total     = sessions_complete + sessions_active + sessions_pending + sessions_abandoned
    completion_pct     = round((sessions_complete / sessions_total * 100) if sessions_total else 0)

    # ── Risks ──────────────────────────────────────────────────────────────────
    risks = []

    if doc_count == 0:
        risks.append({
            'severity':    'high',
            'title':       'No discovery documents uploaded',
            'description': 'The Value Chain Mapper (Alex Chen) has no source material to analyse. Without discovery documents the value chain will be based on web research alone, reducing accuracy and contextual relevance.',
            'mitigation':  'Upload strategy papers, annual reports, or operational documents in the Documents section before running the Value Chain Mapping crew.',
        })
    elif doc_count < 3:
        risks.append({
            'severity':    'medium',
            'title':       f'Limited discovery document coverage ({doc_count} document{"s" if doc_count != 1 else ""})',
            'description': 'Few documents have been uploaded. A richer knowledge base produces a more accurate, contextually grounded value chain and assessment instruments.',
            'mitigation':  'Upload additional source materials — strategy papers, process documents, governance frameworks — before running Discovery.',
        })

    if stakeholder_count == 0:
        risks.append({
            'severity':    'high',
            'title':       'No stakeholders configured',
            'description': 'The Stakeholder Manager (Jordan Blake) has no registry to work from. Without stakeholders, interview campaigns cannot be launched and assessment coverage will be zero.',
            'mitigation':  'Add stakeholders via the Stakeholders page or import via CSV. Assign each stakeholder to value chain nodes before running the Assessment Design crew.',
        })
    elif stakeholder_count < 5:
        risks.append({
            'severity':    'medium',
            'title':       f'Low stakeholder coverage ({stakeholder_count} configured)',
            'description': 'A small stakeholder registry limits assessment breadth and may produce a skewed view of organisational maturity.',
            'mitigation':  'Review value chain node assignments and identify additional stakeholders for underrepresented functions or levels.',
        })

    if sessions_total > 0 and completion_pct < 60:
        interviews_ms = next((m for m in ms_enriched if m['milestone_key'] == 'interviews_complete'), None)
        urgency = ''
        if interviews_ms and interviews_ms.get('days_delta') is not None and interviews_ms['days_delta'] <= 5:
            urgency = f" The interviews_complete milestone is due in {interviews_ms['days_delta']} days."
        risks.append({
            'severity':    'high' if completion_pct < 40 else 'medium',
            'title':       f'Interview completion at risk ({completion_pct}% complete)',
            'description': f'{sessions_complete} of {sessions_total} stakeholders have completed their interview.{urgency} Low completion rates reduce the quality of synthesis outputs.',
            'mitigation':  'Send reminder emails to outstanding stakeholders. Consider extending the interview window or escalating to line managers for non-responders.',
        })

    overdue_count = len(ms_overdue)
    if overdue_count >= 3:
        risks.append({
            'severity':    'high',
            'title':       f'Schedule slippage — {overdue_count} milestones overdue',
            'description': f'Multiple milestones are past their due dates: {", ".join(m["title"] for m in ms_overdue[:3])}{"…" if overdue_count > 3 else ""}. Sustained slippage compounds and is difficult to recover.',
            'mitigation':  'Convene a recovery planning session. Re-baseline the schedule and identify which milestones can be compressed or parallelised.',
        })
    elif overdue_count >= 1:
        risks.append({
            'severity':    'medium',
            'title':       f'Milestone overdue — {ms_overdue[0]["title"]}',
            'description': f'This milestone is {abs(ms_overdue[0]["days_delta"])} days past its due date. If not resolved, downstream milestones will slip.',
            'mitigation':  'Review blockers for this milestone and update the schedule in the Project Schedule page.',
        })

    if len(pending_reviews) >= 3:
        risks.append({
            'severity':    'medium',
            'title':       f'{len(pending_reviews)} phase-gate reviews pending',
            'description': 'Multiple HITL reviews are awaiting decision. Accumulated reviews indicate phase gates are backing up, which will stall crew sequencing.',
            'mitigation':  'Work through the Review Queue to unblock downstream crews. Delegate review authority if the primary reviewer is unavailable.',
        })

    if ms_scheduled == 0 and ms_total > 0:
        risks.append({
            'severity':    'low',
            'title':       'Project schedule has no due dates set',
            'description': 'Milestones have been created but none have due dates assigned. Without dates, PAM cannot track schedule adherence or identify slippage early.',
            'mitigation':  'Set due dates for all milestones in the Project Schedule page. Start with the delivery date and work backwards.',
        })

    # ── Issues ─────────────────────────────────────────────────────────────────
    issues = []

    failed_crews = [c for c in crews if c['status'] == 'failed']
    for fc in failed_crews:
        issues.append({
            'severity':            'critical',
            'title':               f'{fc["crew_label"]} crew failed',
            'description':         f'The most recent run of the {fc["crew_label"]} crew ended in an error. No outputs have been produced by this crew in the current run.',
            'recommended_action':  f'Check the Run History page for the error detail. Resolve the underlying cause, then re-run {fc["crew_label"]} from the Dashboard.',
            'crew':                fc['crew_key'],
        })

    for rev in pending_reviews:
        cn = rev.get('crew_name') or 'Unknown'
        label = CREW_LABELS.get(cn, cn)
        prompt_preview = (rev.get('prompt') or '')[:120].strip()
        if len(rev.get('prompt') or '') > 120:
            prompt_preview += '…'
        issues.append({
            'severity':           'high',
            'title':              f'Phase gate pending — {label}',
            'description':        f'A human review is awaiting decision: "{prompt_preview}"',
            'recommended_action': 'Open the Review Queue on the Dashboard and approve, request changes, or reject this review to allow the pipeline to continue.',
            'crew':               cn,
        })

    for m in ms_overdue:
        issues.append({
            'severity':           'high',
            'title':              f'Milestone overdue — {m["title"]}',
            'description':        f'This milestone was due {abs(m["days_delta"])} day{"s" if abs(m["days_delta"]) != 1 else ""} ago and remains incomplete.',
            'recommended_action': 'Update the milestone status in the Project Schedule page, or extend the due date if the delivery date has changed. Inform the client if the slippage affects the overall engagement timeline.',
            'crew':               None,
        })

    # ── Overall health ─────────────────────────────────────────────────────────
    critical_issues   = [i for i in issues if i['severity'] == 'critical']
    high_issues       = [i for i in issues if i['severity'] == 'high']
    high_risks        = [r for r in risks if r['severity'] == 'high']

    if critical_issues or (len(high_issues) >= 2):
        overall_health  = 'red'
        health_summary  = f'{len(critical_issues)} critical issue{"s" if len(critical_issues) != 1 else ""}, {len(high_issues)} high-priority issue{"s" if len(high_issues) != 1 else ""}. Immediate attention required.'
    elif high_issues or len(high_risks) >= 2:
        overall_health  = 'amber'
        health_summary  = f'{len(issues)} issue{"s" if len(issues) != 1 else ""} and {len(risks)} risk{"s" if len(risks) != 1 else ""} identified. Monitor closely and action outstanding items.'
    elif risks or len(pending_reviews) > 0:
        overall_health  = 'amber'
        health_summary  = f'No critical issues. {len(risks)} risk{"s" if len(risks) != 1 else ""} noted — review mitigations and ensure due dates are tracked.'
    else:
        overall_health  = 'green'
        health_summary  = 'No issues or risks identified. Engagement is progressing to plan.'

    return {
        'generated_at':       datetime.now(timezone.utc).isoformat(),
        'project_slug':       slug,
        'client_name':        client_name,
        'sector':             sector,
        'overall_health':     overall_health,
        'health_summary':     health_summary,
        'milestones':         ms_enriched,
        'milestones_complete': ms_complete,
        'milestones_total':   ms_total,
        'crews':              crews,
        'risks':              risks,
        'issues':             issues,
        'interview_tracker': {
            'total':      sessions_total,
            'complete':   sessions_complete,
            'active':     sessions_active,
            'pending':    sessions_pending,
            'abandoned':  sessions_abandoned,
            'pct':        completion_pct,
        },
        'pending_reviews':    len(pending_reviews),
        'stakeholder_count':  stakeholder_count,
        'doc_count':          doc_count,
    }
