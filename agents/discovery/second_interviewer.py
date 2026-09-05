# agents/discovery/second_interviewer.py
"""Laura Nelson - the second interviewer on `discovery_interviews`.

**A second voice, not a second brief.** Her goal, her backstory and her tools are Avery's,
class for class and word for word: `build_interviewer` in
`agents/discovery/stakeholder_interviewer.py` is the one declaration of what an interviewer is
told to do, and this module adds a person to the roll rather than a second set of instructions.
Everything that differs between the two - the name a participant reads, the face, the voice
they hear - is the mutable half `agents/identity.py` keeps apart from the permanent id, and
none of it is here.

**What is not settled yet, and must be before she can take the interviewing task.** She is
registered and built; the task itself is still Avery's, and handing it to her needs two things
that are Task 3's to resolve rather than this module's to guess at:

- `create_stakeholder_interviewer_task` names `agent_name='stakeholder_interviewer'` in every
  `SQLiteStateTool` call it writes. `SQLiteStateTool` refuses a write whose claimed agent
  disagrees with the tool's own (`agents/tools/sqlite_state.py`), so Laura running that task
  verbatim would be refused on her first write rather than quietly writing under his name.
- `OUTPUT_OWNERS` gives `interview_transcripts` to `stakeholder_interviewer` alone, and
  `check_write` compares the owner by equality, so the same write would be refused a second
  time even with the identity corrected.

Both are refusals rather than silent wrong answers, which is the direction they should fail in.
Neither is repaired here, because repairing them means deciding *how* an artefact is owned by a
role that two agents can fill - and that decision belongs beside the selection that creates the
need for it.
"""
from crewai import Agent, LLM
from crewai.tools import BaseTool

from agents.discovery.stakeholder_interviewer import build_interviewer


def create_second_interviewer(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    """Laura, built from the interviewers' one shared brief."""
    return build_interviewer("Second Interviewer", slug, llm, tools)
