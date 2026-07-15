# api/services/auto_assign_service.py
"""
After the interview script designer or questionnaire builder runs,
auto-publish each script to the system templates library and assign it to the node.
"""
import json
import logging
from pathlib import Path
import aiosqlite

from api.config import get_settings
from api.database import (
    get_connection, fetch_project, fetch_node_template_assignments,
    upsert_node_template_assignment,
    get_system_db_path, init_system_db,
    fetch_template, insert_template, update_template,
)

_log = logging.getLogger(__name__)

_INTERVIEW_STRIP = {"node_label", "level", "research_brief", "study_objectives"}


def _clean_label(label: str) -> str:
    """Strip circled Unicode prefix (①②…) from a node label."""
    import unicodedata
    chars = []
    for ch in label:
        # Keep once we hit a real letter/digit after any prefix chars
        if unicodedata.category(ch) in ("No", "Zs") or ch == " ":
            if not chars:
                continue
        chars.append(ch)
    return "".join(chars).strip() if chars else label.strip()


async def auto_assign_interview_scripts(slug: str) -> int:
    """Read interview_scripts.json → upsert each as a system template → assign to node."""
    scripts_path = Path(get_settings().projects_dir) / slug / "outputs" / "interview_scripts.json"
    if not scripts_path.exists():
        return 0
    try:
        scripts: dict = json.loads(scripts_path.read_text(encoding="utf-8"))
    except Exception:
        _log.exception("auto_assign_interview_scripts[%s]: failed to read scripts", slug)
        return 0

    count = 0
    sys_db_path = get_system_db_path()
    sys_db_path.parent.mkdir(parents=True, exist_ok=True)

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return 0
        project_id = project["id"]
        current = {a["node_label"]: a for a in await fetch_node_template_assignments(conn, project_id)}

        async with aiosqlite.connect(str(sys_db_path)) as sys_conn:
            sys_conn.row_factory = aiosqlite.Row
            await init_system_db(sys_conn)

            for node_label, script in scripts.items():
                schema = {k: v for k, v in script.items() if k not in _INTERVIEW_STRIP}
                schema_json = json.dumps(schema)
                assignment = current.get(node_label, {})
                activity_id = assignment.get("activity_id")
                clean = _clean_label(node_label)
                name = f"{activity_id} — {clean}" if activity_id else clean
                description = (script.get("research_brief") or "")[:200]

                existing_tid = assignment.get("interview_template_id")
                if existing_tid:
                    tpl = await fetch_template(sys_conn, existing_tid)
                    if tpl:
                        await update_template(sys_conn, existing_tid, name, description, schema_json)
                        count += 1
                        continue

                template_id = await insert_template(sys_conn, name, description, "interview", schema_json)
                await upsert_node_template_assignment(
                    conn, project_id, node_label,
                    template_id,
                    assignment.get("questionnaire_template_id"),
                    activity_id=activity_id,
                )
                current[node_label] = {**assignment, "interview_template_id": template_id}
                count += 1

    _log.info("auto_assign_interview_scripts[%s]: %d nodes updated", slug, count)
    return count


async def auto_assign_questionnaire_scripts(slug: str) -> int:
    """Read questionnaire_scripts.json → upsert each as a questionnaire template → assign to node."""
    scripts_path = Path(get_settings().projects_dir) / slug / "outputs" / "questionnaire_scripts.json"
    if not scripts_path.exists():
        return 0
    try:
        scripts: dict = json.loads(scripts_path.read_text(encoding="utf-8"))
    except Exception:
        _log.exception("auto_assign_questionnaire_scripts[%s]: failed to read scripts", slug)
        return 0

    count = 0
    sys_db_path = get_system_db_path()
    sys_db_path.parent.mkdir(parents=True, exist_ok=True)

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return 0
        project_id = project["id"]
        current = {a["node_label"]: a for a in await fetch_node_template_assignments(conn, project_id)}

        async with aiosqlite.connect(str(sys_db_path)) as sys_conn:
            sys_conn.row_factory = aiosqlite.Row
            await init_system_db(sys_conn)

            for node_label, questionnaire in scripts.items():
                schema_json = json.dumps(questionnaire)
                assignment = current.get(node_label, {})
                activity_id = assignment.get("activity_id")
                clean = _clean_label(node_label)
                name = f"{activity_id} — {clean} (Maturity)" if activity_id else f"{clean} (Maturity)"

                existing_qid = assignment.get("questionnaire_template_id")
                if existing_qid:
                    tpl = await fetch_template(sys_conn, existing_qid)
                    if tpl:
                        await update_template(sys_conn, existing_qid, name, "", schema_json)
                        count += 1
                        continue

                template_id = await insert_template(sys_conn, name, "", "questionnaire", schema_json)
                await upsert_node_template_assignment(
                    conn, project_id, node_label,
                    assignment.get("interview_template_id"),
                    template_id,
                    activity_id=activity_id,
                )
                current[node_label] = {**assignment, "questionnaire_template_id": template_id}
                count += 1

    _log.info("auto_assign_questionnaire_scripts[%s]: %d nodes updated", slug, count)
    return count
