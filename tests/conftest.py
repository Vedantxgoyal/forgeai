from __future__ import annotations

from collections import deque

import pytest

from forgeai.config import Settings
from forgeai.llm.client import Completion


class FakeTransport:
    """Scripted LLM: returns queued responses in order and records every call."""

    def __init__(self, responses: list[str | Exception] | None = None):
        self.responses = deque(responses or [])
        self.calls: list[dict] = []

    def push(self, *responses):
        self.responses.extend(responses)

    def complete(self, **kwargs) -> Completion:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeTransport ran out of scripted responses")
        r = self.responses.popleft()
        if isinstance(r, Exception):
            raise r
        return Completion(text=r, prompt_tokens=10, completion_tokens=5)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        cache_dir=tmp_path / "cache",
        use_cache=False,
        embed_backend="tfidf",
        transport_retries=1,
        json_retries=2,
    )


@pytest.fixture
def fake() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def corpus(tmp_path):
    """A small mixed-format folder: markdown policy, PDF, CSV, DOCX, junk file."""
    import docx
    import pymupdf

    root = tmp_path / "docs"
    root.mkdir()
    (root / "leave_policy.md").write_text(
        "# Annual Leave\n\nShore staff accrue 24 days of annual leave per calendar year. "
        "Unused leave up to 5 days may be carried forward to the next year.\n\n"
        "# Sick Leave\n\nEmployees are entitled to 12 days of paid sick leave. "
        "A medical certificate is required for absences longer than 2 consecutive days.\n",
        encoding="utf-8",
    )
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "TRAVEL POLICY", fontsize=14)
    page.insert_text((72, 110), "Economy class is mandatory for flights under 6 hours.", fontsize=11)
    page.insert_text((72, 130), "Daily meal allowance for domestic travel is INR 1500.", fontsize=11)
    pdf.save(root / "travel.pdf")
    pdf.close()

    (root / "catalogue.csv").write_text(
        "part_no,description,unit_price_usd,lead_time_days,supplier\n"
        "MP-1001,Main engine fuel injector,1250.50,21,Wartsila Spares\n"
        "MP-1002,Cylinder liner gasket,85.00,7,Marine Parts Co\n"
        "AB-2207,Ballast pump impeller,640.00,14,Marine Parts Co\n",
        encoding="utf-8",
    )
    d = docx.Document()
    d.add_heading("Code of Conduct", level=1)
    d.add_paragraph("Gifts above USD 50 from suppliers must be declared to Compliance within 7 days.")
    d.save(root / "conduct.docx")
    (root / "image.png").write_bytes(b"\x89PNG fake")
    (root / ".hidden.txt").write_text("should be ignored")
    return root


@pytest.fixture(autouse=True)
def _ignore_local_env_file(monkeypatch):
    """Tests must not depend on the developer's .env (models, fallbacks, keys)."""
    from forgeai.config import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
