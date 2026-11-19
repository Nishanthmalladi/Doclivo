from pathlib import Path

F = Path(__file__).parent / "fixtures"


def pytest_sessionstart(session):
    """Sample files are generated, not stored in the repository."""
    from tests.make_fixtures import main, watermark_fixtures
    if not (F / "heavy.pdf").exists():
        main()
    if not (F / "wm.docx").exists():
        watermark_fixtures()
