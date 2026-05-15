# SP4a — Business Plan Generator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Business Plan Generator agent to the Delivery Planning crew that reads all prior crew outputs, gathers business context via HITL, and produces DOCX + PPTX + XLSX artefacts.

**Architecture:** Single-agent crew (Opus 4.6) with three new output tools (WordOutputTool, PowerPointOutputTool, FinancialModelTool). Agent reads five SQLite keys seeded by earlier crews, pre-populates financial estimates, confirms inputs with the human, then writes all three artefacts and requests review. Mirrors SP3c structure exactly — same BaseTool pattern, same crew assembly, same integration fixture chaining.

**Tech Stack:** Python 3.11, CrewAI 1.14, python-docx, python-pptx, openpyxl (already in requirements), FastAPI async dispatch, SQLiteStateTool dual-write, HumanInputTool SQLite polling

---

## File Map

**New files:**
- `agents/business_plan/__init__.py` — empty package marker
- `agents/business_plan/business_plan_generator.py` — agent factory + task factory
- `agents/crews/business_plan_crew.py` — crew assembly (`create_business_plan_crew`)
- `agents/tools/word_output.py` — WordOutputTool (BaseTool, python-docx)
- `agents/tools/powerpoint_output.py` — PowerPointOutputTool (BaseTool, python-pptx)
- `agents/tools/financial_model.py` — FinancialModelTool (BaseTool, openpyxl, NPV/IRR)
- `tests/test_word_output.py` — 6 unit tests
- `tests/test_powerpoint_output.py` — 5 unit tests
- `tests/test_financial_model.py` — 8 unit tests
- `tests/test_business_plan_crew.py` — 10 unit tests
- `tests/integration/test_business_plan_crew.py` — 1 integration test

**Modified files:**
- `requirements.txt` — add `python-docx`, `python-pptx`
- `agents/tools/registry.py` — add `business_plan_generator` entry
- `api/services/run_service.py` — add `elif crew_name == "business_plan":` dispatch
- `tests/test_run_api.py` — add `test_run_business_plan_crew_queues_run`
- `tests/integration/conftest.py` — append `seed_delivery_outputs` fixture

---

## Task 1: Add python-docx and python-pptx dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add dependencies**

Open `requirements.txt`. After the `openpyxl==3.1.5` line, add:

```
python-docx==1.1.2
python-pptx==1.0.2
```

- [ ] **Step 2: Install dependencies**

Run:
```bash
pip install python-docx==1.1.2 python-pptx==1.0.2
```

Expected: both packages install without conflicts.

- [ ] **Step 3: Verify importable**

Run:
```bash
python -c "import docx; import pptx; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add python-docx and python-pptx dependencies"
```

---

## Task 2: WordOutputTool (TDD)

**Files:**
- Create: `agents/tools/word_output.py`
- Create: `tests/test_word_output.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_word_output.py`:

```python
# tests/test_word_output.py
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolated_projects_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def slug(isolated_projects_dir):
    slug = "word-output-test"
    outputs_dir = isolated_projects_dir / slug / "outputs"
    outputs_dir.mkdir(parents=True)
    return slug


@pytest.fixture
def sample_sections():
    return [
        {"title": "Executive Summary", "content": "This is the executive summary."},
        {"title": "Case for Change", "content": "The case for change is compelling."},
    ]


@pytest.fixture
def sample_metadata():
    return {
        "org_name": "Acme Logistics Ltd",
        "financial_year": "FY2026",
        "sponsor": "Jane Smith, CEO",
    }


def test_word_output_writes_file(slug, sample_sections, sample_metadata):
    """WordOutputTool creates a .docx file at the returned path."""
    from agents.tools.word_output import WordOutputTool
    with patch("agents.tools.word_output.insert_agent_output_sync"):
        tool = WordOutputTool(slug=slug)
        result = tool._run(
            sections=sample_sections,
            metadata=sample_metadata,
            filename="business_plan.docx",
            agent_name="business_plan_generator",
        )
    assert Path(result).exists()


def test_word_output_returns_absolute_path(slug, sample_sections, sample_metadata):
    """Return value is an absolute path ending in .docx."""
    from agents.tools.word_output import WordOutputTool
    with patch("agents.tools.word_output.insert_agent_output_sync"):
        tool = WordOutputTool(slug=slug)
        result = tool._run(
            sections=sample_sections,
            metadata=sample_metadata,
            filename="business_plan.docx",
            agent_name="business_plan_generator",
        )
    assert Path(result).is_absolute()
    assert result.endswith(".docx")


def test_word_output_contains_section_titles(slug, sample_sections, sample_metadata):
    """Generated .docx contains each section title as a heading."""
    from agents.tools.word_output import WordOutputTool
    import docx as python_docx
    with patch("agents.tools.word_output.insert_agent_output_sync"):
        tool = WordOutputTool(slug=slug)
        result = tool._run(
            sections=sample_sections,
            metadata=sample_metadata,
            filename="business_plan.docx",
            agent_name="business_plan_generator",
        )
    doc = python_docx.Document(result)
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Executive Summary" in full_text
    assert "Case for Change" in full_text


def test_word_output_contains_org_name(slug, sample_sections, sample_metadata):
    """org_name from metadata appears in the document."""
    from agents.tools.word_output import WordOutputTool
    import docx as python_docx
    with patch("agents.tools.word_output.insert_agent_output_sync"):
        tool = WordOutputTool(slug=slug)
        result = tool._run(
            sections=sample_sections,
            metadata=sample_metadata,
            filename="business_plan.docx",
            agent_name="business_plan_generator",
        )
    doc = python_docx.Document(result)
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Acme Logistics Ltd" in full_text


def test_word_output_appends_docx_extension(slug, sample_sections, sample_metadata):
    """filename without .docx extension gets it added automatically."""
    from agents.tools.word_output import WordOutputTool
    with patch("agents.tools.word_output.insert_agent_output_sync"):
        tool = WordOutputTool(slug=slug)
        result = tool._run(
            sections=sample_sections,
            metadata=sample_metadata,
            filename="business_plan_no_ext",
            agent_name="business_plan_generator",
        )
    assert result.endswith(".docx")
    assert Path(result).exists()


def test_word_output_error_on_write_failure(slug, sample_sections, sample_metadata):
    """Returns error string when the file cannot be saved."""
    from agents.tools.word_output import WordOutputTool
    with patch("agents.tools.word_output.insert_agent_output_sync"), \
         patch("docx.Document.save", side_effect=OSError("disk full")):
        tool = WordOutputTool(slug=slug)
        result = tool._run(
            sections=sample_sections,
            metadata=sample_metadata,
            filename="fail.docx",
            agent_name="business_plan_generator",
        )
    assert result.startswith("Error: render failed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/test_word_output.py -v
```

Expected: 6 failures — `ModuleNotFoundError: No module named 'agents.tools.word_output'`

- [ ] **Step 3: Implement WordOutputTool**

Create `agents/tools/word_output.py`:

```python
# agents/tools/word_output.py
from datetime import date
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_agent_output_sync


class WordOutputToolInput(BaseModel):
    sections: list[dict[str, str]] = Field(
        description=(
            "List of dicts with 'title' and 'content' keys — one per business plan section."
        )
    )
    metadata: dict[str, Any] = Field(
        description=(
            "Dict with keys: org_name, financial_year, sponsor. "
            "Optional: prepared_by, date (auto-filled if absent)."
        )
    )
    filename: str = Field(
        description="Output filename (e.g. 'business_plan.docx'). "
        ".docx extension added automatically if missing."
    )
    agent_name: str = Field(
        description="Name of the agent producing this output (used for output tracking)."
    )


class WordOutputTool(BaseTool):
    name: str = "WordOutputTool"
    description: str = (
        "Write a business plan to a styled .docx file in the project outputs directory. "
        "Pass sections as a list of {title, content} dicts, metadata with org_name/"
        "financial_year/sponsor, and a filename. Returns the absolute file path."
    )
    args_schema: type[BaseModel] = WordOutputToolInput
    slug: str

    def _run(
        self,
        sections: list[dict[str, str]],
        metadata: dict[str, Any],
        filename: str,
        agent_name: str,
    ) -> str:
        try:
            import docx
            from docx.shared import Pt, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
        except ImportError:
            return "Error: python-docx not installed — run: pip install python-docx"

        settings = get_settings()
        outputs_dir = Path(settings.projects_dir) / self.slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        if not filename.endswith(".docx"):
            filename = f"{filename}.docx"
        file_path = outputs_dir / filename

        try:
            doc = docx.Document()

            # ── Title page ────────────────────────────────────────────────────
            _navy = RGBColor(0x1F, 0x39, 0x7D)

            title_para = doc.add_paragraph()
            title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = title_para.add_run(metadata.get("org_name", ""))
            run.font.size = Pt(24)
            run.font.bold = True
            run.font.color.rgb = _navy

            subtitle_para = doc.add_paragraph()
            subtitle_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run2 = subtitle_para.add_run("Digital Modernisation Business Plan")
            run2.font.size = Pt(18)
            run2.font.color.rgb = _navy

            meta_para = doc.add_paragraph()
            meta_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            fy = metadata.get("financial_year", "")
            sponsor = metadata.get("sponsor", "")
            doc_date = metadata.get("date", str(date.today()))
            meta_para.add_run(f"{fy}  |  {sponsor}  |  {doc_date}")

            doc.add_page_break()

            # ── Table of contents ─────────────────────────────────────────────
            toc_heading = doc.add_heading("Contents", level=1)
            for h_run in toc_heading.runs:
                h_run.font.color.rgb = _navy
            for i, section in enumerate(sections, start=1):
                doc.add_paragraph(f"{i}.  {section['title']}")

            doc.add_page_break()

            # ── Sections ──────────────────────────────────────────────────────
            for section in sections:
                heading = doc.add_heading(section["title"], level=1)
                for h_run in heading.runs:
                    h_run.font.color.rgb = _navy
                doc.add_paragraph(section.get("content", ""))

            doc.save(file_path)
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="docx",
                file_path=str(file_path),
            )
        except (OSError, ValueError) as e:
            return f"Error: render failed — {e}"

        return str(file_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/test_word_output.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add agents/tools/word_output.py tests/test_word_output.py
git commit -m "feat: add WordOutputTool with python-docx"
```

---

## Task 3: PowerPointOutputTool (TDD)

**Files:**
- Create: `agents/tools/powerpoint_output.py`
- Create: `tests/test_powerpoint_output.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_powerpoint_output.py`:

```python
# tests/test_powerpoint_output.py
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolated_projects_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def slug(isolated_projects_dir):
    slug = "pptx-output-test"
    outputs_dir = isolated_projects_dir / slug / "outputs"
    outputs_dir.mkdir(parents=True)
    return slug


@pytest.fixture
def sample_slides():
    return [
        {
            "title": "Case for Change",
            "content": ["Manual processes slow delivery", "Data silos create errors"],
            "notes": "Emphasise cost of current state.",
        },
        {
            "title": "Our Value Propositions",
            "content": "Three high-value propositions identified.",
            "notes": "Refer to VP register.",
        },
    ]


@pytest.fixture
def sample_metadata():
    return {
        "org_name": "Acme Logistics Ltd",
        "financial_year": "FY2026",
        "sponsor": "Jane Smith, CEO",
        "date": "2026-04-15",
    }


def test_powerpoint_output_writes_file(slug, sample_slides, sample_metadata):
    """PowerPointOutputTool creates a .pptx file at the returned path."""
    from agents.tools.powerpoint_output import PowerPointOutputTool
    with patch("agents.tools.powerpoint_output.insert_agent_output_sync"):
        tool = PowerPointOutputTool(slug=slug)
        result = tool._run(
            slides=sample_slides,
            metadata=sample_metadata,
            filename="executive_presentation.pptx",
            agent_name="business_plan_generator",
        )
    assert Path(result).exists()


def test_powerpoint_output_returns_absolute_path(slug, sample_slides, sample_metadata):
    """Return value is an absolute path ending in .pptx."""
    from agents.tools.powerpoint_output import PowerPointOutputTool
    with patch("agents.tools.powerpoint_output.insert_agent_output_sync"):
        tool = PowerPointOutputTool(slug=slug)
        result = tool._run(
            slides=sample_slides,
            metadata=sample_metadata,
            filename="executive_presentation.pptx",
            agent_name="business_plan_generator",
        )
    assert Path(result).is_absolute()
    assert result.endswith(".pptx")


def test_powerpoint_output_contains_slide_titles(slug, sample_slides, sample_metadata):
    """Generated .pptx contains each slide title."""
    from agents.tools.powerpoint_output import PowerPointOutputTool
    from pptx import Presentation
    with patch("agents.tools.powerpoint_output.insert_agent_output_sync"):
        tool = PowerPointOutputTool(slug=slug)
        result = tool._run(
            slides=sample_slides,
            metadata=sample_metadata,
            filename="executive_presentation.pptx",
            agent_name="business_plan_generator",
        )
    prs = Presentation(result)
    all_text = " ".join(
        shape.text
        for slide in prs.slides
        for shape in slide.shapes
        if shape.has_text_frame
    )
    assert "Case for Change" in all_text
    assert "Our Value Propositions" in all_text


def test_powerpoint_output_appends_pptx_extension(slug, sample_slides, sample_metadata):
    """filename without .pptx extension gets it added automatically."""
    from agents.tools.powerpoint_output import PowerPointOutputTool
    with patch("agents.tools.powerpoint_output.insert_agent_output_sync"):
        tool = PowerPointOutputTool(slug=slug)
        result = tool._run(
            slides=sample_slides,
            metadata=sample_metadata,
            filename="presentation_no_ext",
            agent_name="business_plan_generator",
        )
    assert result.endswith(".pptx")
    assert Path(result).exists()


def test_powerpoint_output_error_on_write_failure(slug, sample_slides, sample_metadata):
    """Returns error string when the file cannot be saved."""
    from agents.tools.powerpoint_output import PowerPointOutputTool
    with patch("agents.tools.powerpoint_output.insert_agent_output_sync"), \
         patch("pptx.Presentation.save", side_effect=OSError("disk full")):
        tool = PowerPointOutputTool(slug=slug)
        result = tool._run(
            slides=sample_slides,
            metadata=sample_metadata,
            filename="fail.pptx",
            agent_name="business_plan_generator",
        )
    assert result.startswith("Error: render failed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/test_powerpoint_output.py -v
```

Expected: 5 failures — `ModuleNotFoundError: No module named 'agents.tools.powerpoint_output'`

- [ ] **Step 3: Implement PowerPointOutputTool**

Create `agents/tools/powerpoint_output.py`:

```python
# agents/tools/powerpoint_output.py
from pathlib import Path
from typing import Any, Union
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_agent_output_sync


class PowerPointOutputToolInput(BaseModel):
    slides: list[dict[str, Any]] = Field(
        description=(
            "List of dicts with 'title' (str), 'content' (str or list[str]), "
            "and 'notes' (str) keys — one per slide."
        )
    )
    metadata: dict[str, Any] = Field(
        description="Dict with keys: org_name, financial_year, sponsor, date."
    )
    filename: str = Field(
        description="Output filename (e.g. 'executive_presentation.pptx'). "
        ".pptx extension added automatically if missing."
    )
    agent_name: str = Field(
        description="Name of the agent producing this output (used for output tracking)."
    )


class PowerPointOutputTool(BaseTool):
    name: str = "PowerPointOutputTool"
    description: str = (
        "Write a presentation to a .pptx file in the project outputs directory. "
        "Pass slides as a list of {title, content, notes} dicts, metadata with "
        "org_name/financial_year/sponsor/date, and a filename. "
        "Returns the absolute file path."
    )
    args_schema: type[BaseModel] = PowerPointOutputToolInput
    slug: str

    def _run(
        self,
        slides: list[dict[str, Any]],
        metadata: dict[str, Any],
        filename: str,
        agent_name: str,
    ) -> str:
        try:
            from pptx import Presentation
            from pptx.util import Inches, Pt
            from pptx.dml.color import RGBColor
            from pptx.enum.text import PP_ALIGN
        except ImportError:
            return "Error: python-pptx not installed — run: pip install python-pptx"

        settings = get_settings()
        outputs_dir = Path(settings.projects_dir) / self.slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        if not filename.endswith(".pptx"):
            filename = f"{filename}.pptx"
        file_path = outputs_dir / filename

        _navy = RGBColor(0x1F, 0x39, 0x7D)

        try:
            prs = Presentation()
            # 16:9 widescreen
            prs.slide_width = Inches(13.33)
            prs.slide_height = Inches(7.5)

            # ── Slide 1: Title ─────────────────────────────────────────────
            title_layout = prs.slide_layouts[0]  # Title Slide layout
            slide = prs.slides.add_slide(title_layout)
            slide.shapes.title.text = metadata.get("org_name", "")
            if slide.placeholders[1]:
                slide.placeholders[1].text = (
                    f"Digital Modernisation Business Plan\n"
                    f"{metadata.get('financial_year', '')}  |  "
                    f"{metadata.get('sponsor', '')}  |  "
                    f"{metadata.get('date', '')}"
                )

            # ── Slides 2–N: Content ────────────────────────────────────────
            content_layout = prs.slide_layouts[1]  # Title and Content layout
            for slide_data in slides:
                s = prs.slides.add_slide(content_layout)
                s.shapes.title.text = slide_data.get("title", "")

                # Style title navy
                for para in s.shapes.title.text_frame.paragraphs:
                    for run in para.runs:
                        run.font.color.rgb = _navy
                        run.font.bold = True

                # Body content
                body = s.placeholders[1]
                tf = body.text_frame
                tf.clear()
                content = slide_data.get("content", "")
                if isinstance(content, list):
                    for i, bullet in enumerate(content):
                        if i == 0:
                            tf.paragraphs[0].text = str(bullet)
                        else:
                            tf.add_paragraph().text = str(bullet)
                else:
                    tf.paragraphs[0].text = str(content)

                # Speaker notes
                notes_text = slide_data.get("notes", "")
                if notes_text:
                    notes_slide = s.notes_slide
                    notes_slide.notes_text_frame.text = notes_text

            prs.save(file_path)
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="pptx",
                file_path=str(file_path),
            )
        except (OSError, ValueError) as e:
            return f"Error: render failed — {e}"

        return str(file_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/test_powerpoint_output.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add agents/tools/powerpoint_output.py tests/test_powerpoint_output.py
git commit -m "feat: add PowerPointOutputTool with python-pptx"
```

---

## Task 4: FinancialModelTool (TDD)

**Files:**
- Create: `agents/tools/financial_model.py`
- Create: `tests/test_financial_model.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_financial_model.py`:

```python
# tests/test_financial_model.py
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolated_projects_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def slug(isolated_projects_dir):
    slug = "financial-model-test"
    outputs_dir = isolated_projects_dir / slug / "outputs"
    outputs_dir.mkdir(parents=True)
    return slug


@pytest.fixture
def sample_inputs():
    return {
        "periods": ["Q1 2026", "Q2 2026", "Q3 2026", "Q4 2026"],
        "initiatives": [
            {"id": "INIT-001", "title": "Automate Order Entry", "period": "Q1 2026", "cost_gbp": 100000.0},
            {"id": "INIT-002", "title": "Integrate WMS", "period": "Q2 2026", "cost_gbp": 200000.0},
        ],
        "propositions": [
            {
                "id": "VP-001",
                "title": "Automated Order Management",
                "realisation_period": "Q2 2026",
                "annual_benefit_gbp": 500000.0,
            },
            {
                "id": "VP-002",
                "title": "Integrated Supply Chain",
                "realisation_period": "Q3 2026",
                "annual_benefit_gbp": 200000.0,
            },
        ],
        "discount_rate": 0.08,
        "period_duration_months": 3,
        "filename": "cost_benefit_model.xlsx",
        "agent_name": "business_plan_generator",
    }


def test_financial_model_writes_file(slug, sample_inputs):
    """FinancialModelTool creates an .xlsx file at the returned path."""
    from agents.tools.financial_model import FinancialModelTool
    with patch("agents.tools.financial_model.insert_agent_output_sync"):
        tool = FinancialModelTool(slug=slug)
        result = tool._run(**sample_inputs)
    assert Path(result).exists()


def test_financial_model_returns_absolute_path(slug, sample_inputs):
    """Return value is an absolute path ending in .xlsx."""
    from agents.tools.financial_model import FinancialModelTool
    with patch("agents.tools.financial_model.insert_agent_output_sync"):
        tool = FinancialModelTool(slug=slug)
        result = tool._run(**sample_inputs)
    assert Path(result).is_absolute()
    assert result.endswith(".xlsx")


def test_financial_model_has_three_sheets(slug, sample_inputs):
    """Workbook contains exactly 3 sheets: Cashflow Model, Financial Summary, Assumptions."""
    import openpyxl
    from agents.tools.financial_model import FinancialModelTool
    with patch("agents.tools.financial_model.insert_agent_output_sync"):
        tool = FinancialModelTool(slug=slug)
        result = tool._run(**sample_inputs)
    wb = openpyxl.load_workbook(result)
    assert len(wb.sheetnames) == 3
    assert "Cashflow Model" in wb.sheetnames
    assert "Financial Summary" in wb.sheetnames
    assert "Assumptions" in wb.sheetnames


def test_financial_model_npv_is_float(slug, sample_inputs):
    """Financial Summary sheet contains a numeric NPV value."""
    import openpyxl
    from agents.tools.financial_model import FinancialModelTool
    with patch("agents.tools.financial_model.insert_agent_output_sync"):
        tool = FinancialModelTool(slug=slug)
        result = tool._run(**sample_inputs)
    wb = openpyxl.load_workbook(result)
    ws = wb["Financial Summary"]
    # Find NPV row — label in col A, value in col B
    npv_value = None
    for row in ws.iter_rows(values_only=True):
        if row[0] and "NPV" in str(row[0]):
            npv_value = row[1]
            break
    assert npv_value is not None
    assert isinstance(npv_value, (int, float))


def test_financial_model_irr_is_float_or_none(slug, sample_inputs):
    """IRR in Financial Summary is a float (or None if no solution)."""
    import openpyxl
    from agents.tools.financial_model import FinancialModelTool
    with patch("agents.tools.financial_model.insert_agent_output_sync"):
        tool = FinancialModelTool(slug=slug)
        result = tool._run(**sample_inputs)
    wb = openpyxl.load_workbook(result)
    ws = wb["Financial Summary"]
    irr_value = None
    found = False
    for row in ws.iter_rows(values_only=True):
        if row[0] and "IRR" in str(row[0]):
            irr_value = row[1]
            found = True
            break
    assert found, "IRR row not found in Financial Summary"
    assert irr_value is None or isinstance(irr_value, (int, float))


def test_financial_model_max_borrowing_is_nonpositive(slug, sample_inputs):
    """Max Borrowing Requirement is <= 0 (peak outflow before returns begin)."""
    import openpyxl
    from agents.tools.financial_model import FinancialModelTool
    with patch("agents.tools.financial_model.insert_agent_output_sync"):
        tool = FinancialModelTool(slug=slug)
        result = tool._run(**sample_inputs)
    wb = openpyxl.load_workbook(result)
    ws = wb["Financial Summary"]
    max_borrow = None
    for row in ws.iter_rows(values_only=True):
        if row[0] and "Maximum Borrowing" in str(row[0]):
            max_borrow = row[1]
            break
    assert max_borrow is not None
    assert max_borrow <= 0


def test_financial_model_appends_xlsx_extension(slug, sample_inputs):
    """filename without .xlsx extension gets it added automatically."""
    from agents.tools.financial_model import FinancialModelTool
    inputs = {**sample_inputs, "filename": "cost_benefit_no_ext"}
    with patch("agents.tools.financial_model.insert_agent_output_sync"):
        tool = FinancialModelTool(slug=slug)
        result = tool._run(**inputs)
    assert result.endswith(".xlsx")
    assert Path(result).exists()


def test_financial_model_error_on_write_failure(slug, sample_inputs):
    """Returns error string when the file cannot be saved."""
    import openpyxl
    from agents.tools.financial_model import FinancialModelTool
    with patch("agents.tools.financial_model.insert_agent_output_sync"), \
         patch.object(openpyxl.Workbook, "save", side_effect=OSError("disk full")):
        tool = FinancialModelTool(slug=slug)
        result = tool._run(**sample_inputs)
    assert result.startswith("Error: render failed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/test_financial_model.py -v
```

Expected: 8 failures — `ModuleNotFoundError: No module named 'agents.tools.financial_model'`

- [ ] **Step 3: Implement FinancialModelTool**

Create `agents/tools/financial_model.py`:

```python
# agents/tools/financial_model.py
from pathlib import Path
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_agent_output_sync


def _calculate_npv(cashflows: list[float], rate_per_period: float) -> float:
    """Discounted NPV across all cashflow periods."""
    return sum(cf / (1 + rate_per_period) ** t for t, cf in enumerate(cashflows))


def _calculate_irr(cashflows: list[float], max_iterations: int = 1000) -> float | None:
    """Binary search IRR. Returns None if no solution found."""
    low, high = -0.999, 10.0
    for _ in range(max_iterations):
        mid = (low + high) / 2
        npv = sum(cf / (1 + mid) ** t for t, cf in enumerate(cashflows))
        if abs(npv) < 0.01:
            return mid
        if npv > 0:
            low = mid
        else:
            high = mid
    return None


class FinancialModelToolInput(BaseModel):
    periods: list[str] = Field(
        description="Ordered list of period name strings (e.g. ['Q1 2026', 'Q2 2026'])."
    )
    initiatives: list[dict] = Field(
        description=(
            "List of dicts with keys: id, title, period (name string), cost_gbp (float)."
        )
    )
    propositions: list[dict] = Field(
        description=(
            "List of dicts with keys: id, title, realisation_period (name string), "
            "annual_benefit_gbp (float)."
        )
    )
    discount_rate: float = Field(
        description="Annual discount rate as a decimal (e.g. 0.08 for 8%)."
    )
    period_duration_months: int = Field(
        description="Duration of each period in months (e.g. 3 for quarterly)."
    )
    filename: str = Field(
        description="Output filename (e.g. 'cost_benefit_model.xlsx'). "
        ".xlsx extension added automatically if missing."
    )
    agent_name: str = Field(
        description="Name of the agent producing this output (used for output tracking)."
    )


class FinancialModelTool(BaseTool):
    name: str = "FinancialModelTool"
    description: str = (
        "Build a 3-sheet financial model (.xlsx) with Cashflow Model, Financial Summary, "
        "and Assumptions sheets. Calculates NPV, IRR, payback period, and maximum borrowing "
        "requirement from initiative costs and proposition benefits. "
        "Returns the absolute file path."
    )
    args_schema: type[BaseModel] = FinancialModelToolInput
    slug: str

    def _run(
        self,
        periods: list[str],
        initiatives: list[dict],
        propositions: list[dict],
        discount_rate: float,
        period_duration_months: int,
        filename: str,
        agent_name: str,
    ) -> str:
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            return "Error: openpyxl not installed — run: pip install openpyxl"

        settings = get_settings()
        outputs_dir = Path(settings.projects_dir) / self.slug / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        if not filename.endswith(".xlsx"):
            filename = f"{filename}.xlsx"
        file_path = outputs_dir / filename

        try:
            # Pre-compute period index map
            period_index = {name: i for i, name in enumerate(periods)}
            n = len(periods)

            # Per-period benefit from annual_benefit_gbp, pro-rated by period_duration
            benefit_multiplier = period_duration_months / 12.0

            # Build cashflow arrays
            # costs[p] = sum of initiative costs in period p
            costs = [0.0] * n
            for init in initiatives:
                p = period_index.get(init["period"])
                if p is not None:
                    costs[p] += float(init.get("cost_gbp", 0))

            # benefits[p] = sum of annual_benefit * multiplier for all propositions
            # whose realisation_period <= periods[p]
            benefits = [0.0] * n
            for prop in propositions:
                r_idx = period_index.get(prop.get("realisation_period"))
                if r_idx is None:
                    continue
                per_period = float(prop.get("annual_benefit_gbp", 0)) * benefit_multiplier
                for p in range(r_idx, n):
                    benefits[p] += per_period

            net = [benefits[p] - costs[p] for p in range(n)]
            cumulative = []
            running = 0.0
            for v in net:
                running += v
                cumulative.append(running)

            # Payback: first period where cumulative turns positive
            payback_period = None
            for i, cum in enumerate(cumulative):
                if cum >= 0:
                    payback_period = periods[i]
                    break

            # Financial metrics
            rate_per_period = discount_rate * (period_duration_months / 12.0)
            npv = _calculate_npv(net, rate_per_period)
            irr = _calculate_irr(net)
            max_borrowing = min(cumulative)
            total_investment = sum(costs)
            total_benefits = sum(benefits)

            # ── Build workbook ────────────────────────────────────────────
            wb = openpyxl.Workbook()

            header_font = Font(bold=True, color="FFFFFF")
            header_fill = PatternFill("solid", fgColor="1F397D")  # navy

            # ── Sheet 1: Cashflow Model ───────────────────────────────────
            ws1 = wb.active
            ws1.title = "Cashflow Model"

            # Header row
            ws1.cell(row=1, column=1, value="Item").font = Font(bold=True)
            for col_i, period_name in enumerate(periods, start=2):
                cell = ws1.cell(row=1, column=col_i, value=period_name)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")
            ws1.cell(row=1, column=1).font = header_font
            ws1.cell(row=1, column=1).fill = header_fill

            # Initiative cost rows
            row = 2
            for init in initiatives:
                ws1.cell(row=row, column=1, value=f"Cost: {init['title']}")
                p = period_index.get(init["period"])
                if p is not None:
                    ws1.cell(row=row, column=p + 2, value=-float(init.get("cost_gbp", 0)))
                row += 1

            # Proposition benefit rows
            for prop in propositions:
                ws1.cell(row=row, column=1, value=f"Benefit: {prop['title']}")
                r_idx = period_index.get(prop.get("realisation_period"))
                if r_idx is not None:
                    per_period = float(prop.get("annual_benefit_gbp", 0)) * benefit_multiplier
                    for p in range(r_idx, n):
                        ws1.cell(row=row, column=p + 2, value=per_period)
                row += 1

            # Net Cashflow row
            net_row = row
            net_label = ws1.cell(row=net_row, column=1, value="Net Cashflow")
            net_label.font = Font(bold=True)
            for col_i, v in enumerate(net, start=2):
                ws1.cell(row=net_row, column=col_i, value=v)
            row += 1

            # Cumulative Cashflow row
            cum_row = row
            cum_label = ws1.cell(row=cum_row, column=1, value="Cumulative Cashflow")
            cum_label.font = Font(bold=True)
            for col_i, v in enumerate(cumulative, start=2):
                ws1.cell(row=cum_row, column=col_i, value=v)

            # Auto-width columns
            for col in ws1.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=0)
                ws1.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

            # ── Sheet 2: Financial Summary ────────────────────────────────
            ws2 = wb.create_sheet("Financial Summary")
            summary_rows = [
                ("NPV (£)", round(npv, 2)),
                ("IRR", round(irr, 4) if irr is not None else None),
                ("Payback Period", payback_period),
                ("Maximum Borrowing Requirement (£)", round(max_borrowing, 2)),
                ("Total Investment (£)", round(total_investment, 2)),
                ("Total Benefits over Horizon (£)", round(total_benefits, 2)),
            ]
            ws2.cell(row=1, column=1, value="Metric").font = header_font
            ws2.cell(row=1, column=1).fill = header_fill
            ws2.cell(row=1, column=2, value="Value").font = header_font
            ws2.cell(row=1, column=2).fill = header_fill
            for i, (label, value) in enumerate(summary_rows, start=2):
                ws2.cell(row=i, column=1, value=label)
                ws2.cell(row=i, column=2, value=value)
            ws2.column_dimensions["A"].width = 40
            ws2.column_dimensions["B"].width = 20

            # ── Sheet 3: Assumptions ──────────────────────────────────────
            ws3 = wb.create_sheet("Assumptions")
            ws3.cell(row=1, column=1, value="Parameter").font = header_font
            ws3.cell(row=1, column=1).fill = header_fill
            ws3.cell(row=1, column=2, value="Value").font = header_font
            ws3.cell(row=1, column=2).fill = header_fill
            assumption_rows = [
                ("Discount Rate", f"{discount_rate * 100:.1f}%"),
                ("Period Duration (months)", period_duration_months),
                ("Number of Periods", n),
                ("Benefit pro-ration multiplier", benefit_multiplier),
            ]
            for i, (k, v) in enumerate(assumption_rows, start=2):
                ws3.cell(row=i, column=1, value=k)
                ws3.cell(row=i, column=2, value=v)
            ws3.column_dimensions["A"].width = 35
            ws3.column_dimensions["B"].width = 20

            # Initiatives sub-table
            ws3.cell(row=7, column=1, value="Initiative Costs Used").font = Font(bold=True)
            ws3.cell(row=8, column=1, value="ID")
            ws3.cell(row=8, column=2, value="Title")
            ws3.cell(row=8, column=3, value="Period")
            ws3.cell(row=8, column=4, value="Cost (£)")
            for j, init in enumerate(initiatives, start=9):
                ws3.cell(row=j, column=1, value=init.get("id", ""))
                ws3.cell(row=j, column=2, value=init.get("title", ""))
                ws3.cell(row=j, column=3, value=init.get("period", ""))
                ws3.cell(row=j, column=4, value=init.get("cost_gbp", 0))

            prop_start = 9 + len(initiatives) + 1
            ws3.cell(row=prop_start, column=1, value="Proposition Benefits Used").font = Font(bold=True)
            ws3.cell(row=prop_start + 1, column=1, value="ID")
            ws3.cell(row=prop_start + 1, column=2, value="Title")
            ws3.cell(row=prop_start + 1, column=3, value="Realisation Period")
            ws3.cell(row=prop_start + 1, column=4, value="Annual Benefit (£)")
            for j, prop in enumerate(propositions, start=prop_start + 2):
                ws3.cell(row=j, column=1, value=prop.get("id", ""))
                ws3.cell(row=j, column=2, value=prop.get("title", ""))
                ws3.cell(row=j, column=3, value=prop.get("realisation_period", ""))
                ws3.cell(row=j, column=4, value=prop.get("annual_benefit_gbp", 0))

            wb.save(file_path)
            insert_agent_output_sync(
                slug=self.slug,
                agent_name=agent_name,
                output_type="xlsx",
                file_path=str(file_path),
            )
        except (OSError, ValueError) as e:
            return f"Error: render failed — {e}"

        return str(file_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/test_financial_model.py -v
```

Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add agents/tools/financial_model.py tests/test_financial_model.py
git commit -m "feat: add FinancialModelTool with NPV/IRR/cashflow model"
```

---

## Task 5: Business Plan Generator agent + task factory (TDD)

**Files:**
- Create: `agents/business_plan/__init__.py`
- Create: `agents/business_plan/business_plan_generator.py`
- Create: `tests/test_business_plan_crew.py` (partial — agent tests first)

- [ ] **Step 1: Write failing agent tests**

Create `tests/test_business_plan_crew.py`:

```python
# tests/test_business_plan_crew.py
"""Unit tests for Business Plan Generator crew agent and crew assembly."""
import pytest
from unittest.mock import MagicMock, patch
from crewai import LLM


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLM)


# ── Business Plan Generator agent ─────────────────────────────────────────────

def test_bpg_agent_role(mock_llm):
    from agents.business_plan.business_plan_generator import create_business_plan_generator
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    assert agent.role == "Business Plan Generator"


def test_bpg_task_reads_all_inputs(mock_llm):
    """Task description references all five required SQLite keys."""
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    for key in ("requirements", "value_levers", "propositions", "initiative_register", "roadmap_data"):
        assert f"key='{key}'" in task.description, f"Missing key='{key}' in task description"


def test_bpg_task_calls_word_output_tool(mock_llm):
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    assert "WordOutputTool" in task.description


def test_bpg_task_calls_powerpoint_output_tool(mock_llm):
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    assert "PowerPointOutputTool" in task.description


def test_bpg_task_calls_financial_model_tool(mock_llm):
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    assert "FinancialModelTool" in task.description


def test_bpg_task_has_context_gathering_hitl(mock_llm):
    """First HumanInputTool call asks for org name and financial confirmation."""
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    assert "HumanInputTool" in task.description
    assert "organisation name" in task.description.lower() or "Organization name" in task.description


def test_bpg_task_has_review_hitl(mock_llm):
    """Second HumanInputTool call asks for approval of generated artefacts."""
    from agents.business_plan.business_plan_generator import (
        create_business_plan_generator,
        create_business_plan_generator_task,
    )
    agent = create_business_plan_generator(slug="test", llm=mock_llm, tools=[])
    task = create_business_plan_generator_task(agent=agent)
    assert "approved" in task.description
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/test_business_plan_crew.py -v -k "bpg_agent or bpg_task"
```

Expected: 7 failures — `ModuleNotFoundError: No module named 'agents.business_plan'`

- [ ] **Step 3: Create package init**

Create `agents/business_plan/__init__.py`:
```python
```
(empty file)

- [ ] **Step 4: Implement agent + task factory**

Create `agents/business_plan/business_plan_generator.py`:

```python
# agents/business_plan/business_plan_generator.py
from crewai import Agent, Task, LLM
from crewai.tools import BaseTool


def create_business_plan_generator(slug: str, llm: LLM, tools: list[BaseTool]) -> Agent:
    return Agent(
        role="Business Plan Generator",
        goal=(
            "Produce a complete, board-ready business plan that synthesises all prior "
            "analysis into a compelling investment case — with executive narrative, "
            "financial model, and presentation deck."
        ),
        backstory=(
            "You are a management consultant and business writer who transforms strategic "
            "analysis into compelling investment proposals. You draw on requirements, value "
            "propositions, initiative roadmaps, and financial modelling to build business "
            "cases that secure executive sponsorship and funding approval."
        ),
        llm=llm,
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )


def create_business_plan_generator_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Generate a complete business plan from all prior crew outputs.\n\n"
            "Steps:\n"
            "1. Read all five inputs via SQLiteStateTool:\n"
            "   - operation='read', key='requirements', agent_name='business_plan_generator'\n"
            "   - operation='read', key='value_levers', agent_name='business_plan_generator'\n"
            "   - operation='read', key='propositions', agent_name='business_plan_generator'\n"
            "   - operation='read', key='initiative_register', agent_name='business_plan_generator'\n"
            "   - operation='read', key='roadmap_data', agent_name='business_plan_generator'\n\n"
            "2. Pre-populate financial estimates from the data:\n"
            "   Initiative costs by complexity_score: 1=£50k, 2=£100k, 3=£200k, 4=£400k, 5=£800k\n"
            "   Annual benefits by value_estimate: High=£500k/yr, Medium=£200k/yr, Low=£100k/yr\n"
            "   Default discount rate: 8%\n"
            "   Period duration from roadmap_data.time_axis: quarters=3 months, years=12 months, "
            "horizons=18 months\n\n"
            "3. Use HumanInputTool to gather business context and confirm financial assumptions.\n"
            "   Prompt: 'To complete the business plan, please provide:\n"
            "   (1) Organisation name\n"
            "   (2) Financial year (e.g. FY2026)\n"
            "   (3) Primary business sponsor name and title\n"
            "   (4) Any additional context for the executive summary.\n"
            "   I have also pre-populated financial estimates — please confirm or adjust:\n"
            "   [List each initiative with estimated cost, each proposition with estimated "
            "annual benefit, and the default 8% discount rate.]\n"
            "   Reply with your details and \"confirmed\" or provide adjustments.'\n\n"
            "4. Generate all six business plan sections using LLM reasoning:\n"
            "   - Executive Summary (incorporating organisation name, sponsor, financial year, "
            "business context provided)\n"
            "   - Case for Change (from requirements + value_levers)\n"
            "   - Value Propositions (from propositions register)\n"
            "   - Initiative Roadmap (from roadmap_data — periods, initiatives by period)\n"
            "   - Investment & Benefits (from financial model — costs by period, benefits from "
            "realisation, NPV/IRR summary)\n"
            "   - Governance & Next Steps\n\n"
            "5. Use WordOutputTool with:\n"
            "   - sections: list of {title, content} dicts for all six sections\n"
            "   - metadata: {org_name, financial_year, sponsor, date}\n"
            "   - filename: 'business_plan.docx'\n"
            "   - agent_name: 'business_plan_generator'\n\n"
            "6. Assemble 8-10 slides and use PowerPointOutputTool with:\n"
            "   - slides: list of {title, content, notes} dicts\n"
            "   - metadata: {org_name, financial_year, sponsor, date}\n"
            "   - filename: 'executive_presentation.pptx'\n"
            "   - agent_name: 'business_plan_generator'\n\n"
            "7. Use FinancialModelTool with confirmed financial inputs:\n"
            "   - periods: list from roadmap_data.periods\n"
            "   - initiatives: list of {id, title, period, cost_gbp}\n"
            "   - propositions: list of {id, title, realisation_period, annual_benefit_gbp}\n"
            "   - discount_rate: confirmed or default 0.08\n"
            "   - period_duration_months: inferred from roadmap_data.time_axis\n"
            "   - filename: 'cost_benefit_model.xlsx'\n"
            "   - agent_name: 'business_plan_generator'\n\n"
            "8. Use HumanInputTool with prompt: 'Please review the outputs:\n"
            "   outputs/business_plan.docx\n"
            "   outputs/executive_presentation.pptx\n"
            "   outputs/cost_benefit_model.xlsx\n"
            "   Reply \"approved\" to conclude Business Plan generation, or provide "
            "revision notes.'\n\n"
            "9. If revision notes are received, revise the content and repeat steps 5-8. "
            "Maximum 3 revision cycles.\n"
        ),
        expected_output=(
            "Three artefacts saved to the outputs directory: "
            "business_plan.docx (6-section word document), "
            "executive_presentation.pptx (8-10 slide deck), "
            "cost_benefit_model.xlsx (3-sheet financial model with NPV, IRR, max borrowing). "
            "Confirmed approved by a human reviewer."
        ),
        agent=agent,
    )
```

- [ ] **Step 5: Run agent tests to verify they pass**

Run:
```bash
pytest tests/test_business_plan_crew.py -v -k "bpg_agent or bpg_task"
```

Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add agents/business_plan/__init__.py agents/business_plan/business_plan_generator.py tests/test_business_plan_crew.py
git commit -m "feat: add Business Plan Generator agent and task factory"
```

---

## Task 6: Crew assembly, registry, API wiring, and crew unit tests

**Files:**
- Create: `agents/crews/business_plan_crew.py`
- Modify: `agents/tools/registry.py`
- Modify: `api/services/run_service.py`
- Modify: `tests/test_run_api.py`
- Modify: `tests/test_business_plan_crew.py` (append crew wiring tests)

- [ ] **Step 1: Write failing crew wiring tests**

Append to `tests/test_business_plan_crew.py`:

```python
# ── Crew wiring ───────────────────────────────────────────────────────────────

def test_business_plan_crew_has_one_agent(mock_llm):
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.business_plan_crew import create_business_plan_crew
        crew = create_business_plan_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    assert len(crew.agents) == 1


def test_business_plan_crew_sequential_process(mock_llm):
    from crewai import Process
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]):
        from agents.crews.business_plan_crew import create_business_plan_crew
        crew = create_business_plan_crew(
            slug="test", run_id=1, llm_mode="standard", sector="logistics", llm=mock_llm
        )
    assert crew.process == Process.sequential


def test_business_plan_crew_sensitive_mode_uses_local_llm(mock_llm):
    """In sensitive mode, get_crew_llm is called with 'sensitive' (BPG routes to local LLM)."""
    with patch("agents.tools.registry.get_tools_for_agent", return_value=[]), \
         patch("agents.crews.business_plan_crew.get_crew_llm") as mock_get_llm:
        mock_get_llm.return_value = mock_llm
        from agents.crews.business_plan_crew import create_business_plan_crew
        create_business_plan_crew(
            slug="test", run_id=1, llm_mode="sensitive", sector="logistics"
        )
    mock_get_llm.assert_called_once_with("sensitive")
```

- [ ] **Step 2: Run crew tests to verify they fail**

Run:
```bash
pytest tests/test_business_plan_crew.py -v -k "crew"
```

Expected: 3 failures — `ModuleNotFoundError: No module named 'agents.crews.business_plan_crew'`

- [ ] **Step 3: Implement business_plan_crew.py**

Create `agents/crews/business_plan_crew.py`:

```python
# agents/crews/business_plan_crew.py
from crewai import Crew, Process, LLM
from agents.llm import get_pam_llm, get_crew_llm
from agents.tools.registry import get_tools_for_agent
from agents.business_plan.business_plan_generator import (
    create_business_plan_generator,
    create_business_plan_generator_task,
)


def create_business_plan_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    llm: LLM | None = None,
) -> Crew:
    """
    Assemble and return the Business Plan Crew.

    Args:
        slug: Project slug (used for DB/file scoping).
        run_id: crew_runs.id for this execution (used by HumanInputTool).
        llm_mode: "standard" | "sensitive" | "fallback" — determines LLM routing.
        sector: Client sector (passed to tool registry).
        llm: Optional LLM override (used in tests to inject a cheap model).
    """
    if llm is not None:
        bpg_llm = llm  # test override
    elif llm_mode == "sensitive":
        bpg_llm = get_crew_llm("sensitive")  # local LLM for sensitive data
    else:
        bpg_llm = get_pam_llm()  # Claude Opus 4.6

    bpg = create_business_plan_generator(
        slug=slug,
        llm=bpg_llm,
        tools=get_tools_for_agent(
            "business_plan_generator", slug=slug, run_id=run_id, sector=sector
        ),
    )

    bpg_task = create_business_plan_generator_task(agent=bpg)

    return Crew(
        agents=[bpg],
        tasks=[bpg_task],
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 4: Run crew tests to verify they pass**

Run:
```bash
pytest tests/test_business_plan_crew.py -v
```

Expected: 10 passed

- [ ] **Step 5: Update registry.py**

In `agents/tools/registry.py`, add the following import at the top of `get_tools_for_agent` (alongside the existing imports inside the function body):

```python
from agents.tools.word_output import WordOutputTool
from agents.tools.powerpoint_output import PowerPointOutputTool
from agents.tools.financial_model import FinancialModelTool
```

Then add the `business_plan_generator` entry to `tool_map` after the `roadmap_generator` entry:

```python
        "business_plan_generator": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
            WordOutputTool(slug=slug),
            PowerPointOutputTool(slug=slug),
            FinancialModelTool(slug=slug),
        ],
```

The full updated `get_tools_for_agent` function body (imports + tool_map additions):

```python
def get_tools_for_agent(
    agent_name: str,
    slug: str,
    run_id: int = 0,
    sector: str = "",
) -> list[BaseTool]:
    """Return instantiated tools for the given agent, scoped to the project slug."""
    from agents.tools.sqlite_state import SQLiteStateTool
    from agents.tools.human_input import HumanInputTool
    from agents.tools.document_ingestion import DocumentIngestionTool
    from agents.tools.chroma_query import ChromaQueryTool
    from agents.tools.tavily_search import TavilySearchTool
    from agents.tools.mermaid_render import MermaidRenderTool
    from agents.tools.excel_output import ExcelOutputTool
    from agents.tools.html_roadmap import HtmlRoadmapTool
    from agents.tools.word_output import WordOutputTool
    from agents.tools.powerpoint_output import PowerPointOutputTool
    from agents.tools.financial_model import FinancialModelTool

    # ... (sector loading block unchanged) ...

    tool_map: dict[str, list[BaseTool]] = {
        # ... (existing entries unchanged) ...
        "roadmap_generator": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
            HtmlRoadmapTool(slug=slug),
        ],
        "business_plan_generator": [
            SQLiteStateTool(slug=slug),
            HumanInputTool(slug=slug, run_id=run_id),
            WordOutputTool(slug=slug),
            PowerPointOutputTool(slug=slug),
            FinancialModelTool(slug=slug),
        ],
    }
    # ...
```

- [ ] **Step 6: Update run_service.py**

In `api/services/run_service.py`, add to `dispatch_crew()` before the `else` clause:

```python
        elif crew_name == "business_plan":
            await _run_business_plan_crew(slug=slug, run_id=run_id)
```

Append the new private function at the end of the file:

```python
async def _run_business_plan_crew(slug: str, run_id: int) -> None:
    """Build and run the Business Plan Crew asynchronously."""
    settings = get_settings()
    config = load_project_config(Path(settings.projects_dir) / slug)
    llm_mode = config.get("llm_mode", "standard")
    sector = config.get("sector", "")

    from agents.crews.business_plan_crew import create_business_plan_crew
    crew = create_business_plan_crew(
        slug=slug,
        run_id=run_id,
        llm_mode=llm_mode,
        sector=sector,
    )
    await crew.kickoff_async()
```

- [ ] **Step 7: Add run API test**

Append to `tests/test_run_api.py`:

```python
@pytest.mark.asyncio
async def test_run_business_plan_crew_queues_run(client):
    payload = {**PROJECT_PAYLOAD, "client_slug": "bp-test", "crews_enabled": ["business_plan"]}
    await client.post("/projects", json=payload)
    with patch("api.services.run_service.dispatch_crew", new_callable=AsyncMock):
        resp = await client.post("/projects/bp-test/run", json={"crew": "business_plan"})
    assert resp.status_code == 202
    data = resp.json()
    assert data["crew"] == "business_plan"
    assert data["status"] == "running"
    assert data["project_slug"] == "bp-test"
    assert isinstance(data["run_id"], int)
```

- [ ] **Step 8: Run full unit test suite**

Run:
```bash
pytest tests/ --ignore=tests/integration -v
```

Expected: all tests pass (prior 97 + new 24 = 121+ total). Note: run with `--ignore=tests/integration` to skip integration tests that require live API keys.

- [ ] **Step 9: Commit**

```bash
git add agents/crews/business_plan_crew.py agents/tools/registry.py api/services/run_service.py tests/test_run_api.py tests/test_business_plan_crew.py
git commit -m "feat: wire Business Plan crew into registry, run_service, and API"
```

---

## Task 7: Integration fixture, integration test, full suite, merge

**Files:**
- Modify: `tests/integration/conftest.py`
- Create: `tests/integration/test_business_plan_crew.py`

- [ ] **Step 1: Append seed_delivery_outputs fixture to conftest.py**

Append to `tests/integration/conftest.py`:

```python
@pytest.fixture(scope="session")
def seed_delivery_outputs(test_slug, seed_architecture_outputs):
    """
    Write mock Delivery crew outputs to the test project's outputs directory.
    Required by Business Plan integration tests (BPG reads roadmap_data via SQLiteStateTool).
    seed_architecture_outputs is a dependency — it transitively seeds all prior crew outputs.
    """
    from api.config import get_settings
    import json
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    roadmap_data = {
        "time_axis": "quarters",
        "periods": ["Q1 2026", "Q2 2026", "Q3 2026"],
        "value_streams": ["Inbound", "Warehousing", "Outbound", "Last Mile"],
        "stakeholder_groups": ["Operations", "IT", "Finance"],
        "initiatives": [
            {
                "id": "INIT-001",
                "title": "Automate Order Entry System",
                "category": "enabling",
                "complexity_score": 2,
                "period": "Q1 2026",
                "value_streams": ["Inbound", "Warehousing"],
                "proposition_ids": ["VP-001"],
            },
            {
                "id": "INIT-002",
                "title": "Integrate WMS and ERP Platforms",
                "category": "operating_model",
                "complexity_score": 3,
                "period": "Q2 2026",
                "value_streams": ["Warehousing", "Outbound"],
                "proposition_ids": ["VP-002"],
            },
        ],
        "propositions": [
            {
                "id": "VP-001",
                "title": "Automated Order Management",
                "value_estimate": "High",
                "change_articulation": "Replace manual order entry with automation.",
                "realisation_period": "Q2 2026",
                "value_streams": ["Inbound"],
                "impacted_stakeholder_groups": ["Operations", "Finance"],
                "value_levers": ["Process Automation", "OpEx Reduction"],
            },
            {
                "id": "VP-002",
                "title": "Integrated Supply Chain Platform",
                "value_estimate": "High",
                "change_articulation": "Connect WMS, ERP, and CRM into a unified layer.",
                "realisation_period": "Q3 2026",
                "value_streams": ["Warehousing", "Outbound"],
                "impacted_stakeholder_groups": ["IT", "Operations"],
                "value_levers": ["Systems Integration"],
            },
        ],
    }
    (outputs_dir / "roadmap_data.json").write_text(json.dumps(roadmap_data))

    yield  # no teardown needed — project dir is cleaned up by setup_test_project
```

- [ ] **Step 2: Write integration test**

Create `tests/integration/test_business_plan_crew.py`:

```python
# tests/integration/test_business_plan_crew.py
"""
End-to-end integration test for the Business Plan Crew.

Requires:
- ANTHROPIC_API_KEY in .env
- All prior crew outputs seeded by seed_delivery_outputs (which chains back through
  seed_architecture_outputs → seed_value_design_outputs → seed_discovery_outputs)

Run with: pytest -m integration -v
Takes 5-12 minutes.
"""
import contextlib
import json
import sqlite3
import pytest
from pathlib import Path
from api.config import get_settings


@pytest.mark.integration
def test_business_plan_crew_end_to_end(test_slug, project_id, seed_delivery_outputs):
    """
    Run the full Business Plan Crew and verify all three artefacts are produced.
    Uses claude-haiku for the agent (test LLM override).
    HITL pauses are auto-responded via HITL_AUTO_RESPOND='approved' set in conftest.
    """
    from agents.llm import get_test_llm
    from agents.crews.business_plan_crew import create_business_plan_crew

    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{test_slug}.db"

    # Create a crew_run record
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status, started_at)"
        " VALUES (?,?,?, CURRENT_TIMESTAMP)",
        (project_id, "business_plan", "running"),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()

    llm = get_test_llm()
    crew = create_business_plan_crew(
        slug=test_slug,
        run_id=run_id,
        llm_mode="standard",
        sector="logistics",
        llm=llm,
    )

    result = crew.kickoff()
    assert result is not None

    # Mark run completed
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "UPDATE crew_runs SET status='completed', finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (run_id,),
        )
        conn.commit()

    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"

    # 1. business_plan.docx exists and is non-empty
    docx_path = outputs_dir / "business_plan.docx"
    assert docx_path.exists(), "business_plan.docx not created"
    assert docx_path.stat().st_size > 0, "business_plan.docx is empty"

    # 2. executive_presentation.pptx exists and is non-empty
    pptx_path = outputs_dir / "executive_presentation.pptx"
    assert pptx_path.exists(), "executive_presentation.pptx not created"
    assert pptx_path.stat().st_size > 0, "executive_presentation.pptx is empty"

    # 3. cost_benefit_model.xlsx exists with 3 sheets and numeric NPV + max_borrowing
    import openpyxl
    xlsx_path = outputs_dir / "cost_benefit_model.xlsx"
    assert xlsx_path.exists(), "cost_benefit_model.xlsx not created"
    wb = openpyxl.load_workbook(xlsx_path)
    assert len(wb.sheetnames) == 3, f"Expected 3 sheets, got {wb.sheetnames}"

    ws_summary = wb["Financial Summary"]
    npv_value = None
    max_borrow = None
    for row in ws_summary.iter_rows(values_only=True):
        if row[0] and "NPV" in str(row[0]):
            npv_value = row[1]
        if row[0] and "Maximum Borrowing" in str(row[0]):
            max_borrow = row[1]
    assert isinstance(npv_value, (int, float)), f"NPV not numeric: {npv_value}"
    assert isinstance(max_borrow, (int, float)), f"Max borrowing not numeric: {max_borrow}"

    # 4. At least 2 HITL records (context gate + review gate)
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM human_reviews WHERE crew_run_id=?", (run_id,)
        )
        hitl_count = cur.fetchone()[0]
    assert hitl_count >= 2, f"Expected at least 2 HITL reviews, got {hitl_count}"

    # 5. agent_outputs record for business_plan_generator
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT DISTINCT agent_name FROM agent_outputs WHERE project_id=?",
            (project_id,),
        )
        agent_names = {row[0] for row in cur.fetchall()}
    assert "business_plan_generator" in agent_names, \
        "Business Plan Generator produced no tracked output"
```

- [ ] **Step 3: Run full unit test suite (no integration)**

Run:
```bash
pytest tests/ --ignore=tests/integration -v
```

Expected: all 121+ unit tests pass

- [ ] **Step 4: Run integration test suite**

Run:
```bash
pytest -m integration -v
```

Expected: all integration tests pass (5-12 minutes, requires `ANTHROPIC_API_KEY` in `.env`)

- [ ] **Step 5: Final commit**

```bash
git add tests/integration/conftest.py tests/integration/test_business_plan_crew.py
git commit -m "test: add Business Plan crew integration test with seed_delivery_outputs fixture"
```

- [ ] **Step 6: Merge to master**

```bash
git checkout master
git merge --no-ff feature/sp4a-business-plan-generator -m "feat: SP4a — Business Plan Generator (DOCX + PPTX + XLSX with NPV/IRR)"
git push
```

---

## Spec Coverage Self-Check

| Spec requirement | Task covering it |
|---|---|
| WordOutputTool — python-docx, title page, TOC, headings, org_name, .docx extension | Task 2 |
| PowerPointOutputTool — python-pptx, title slide, content slides, speaker notes, .pptx ext | Task 3 |
| FinancialModelTool — 3 sheets, NPV, IRR binary search, max borrowing, .xlsx ext | Task 4 |
| BPG agent role, all 5 input keys in task | Task 5 |
| WordOutputTool in task description | Task 5 |
| PowerPointOutputTool in task description | Task 5 |
| FinancialModelTool in task description | Task 5 |
| Context-gathering HITL with org name + financial confirmation | Task 5 |
| Review HITL with "approved" | Task 5 |
| Crew assembly — single agent, Process.sequential | Task 6 |
| Sensitive mode routes to local LLM | Task 6 |
| Registry entry for business_plan_generator | Task 6 |
| API dispatch (run_service, crew="business_plan") | Task 6 |
| test_run_business_plan_crew_queues_run | Task 6 |
| seed_delivery_outputs fixture | Task 7 |
| Integration test — docx + pptx + xlsx + NPV + hitl_count >= 2 | Task 7 |
| requirements.txt — python-docx + python-pptx | Task 1 |
