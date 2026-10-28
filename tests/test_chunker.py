from app.ingestion.chunker import build_overview_document, chunk_body, chunk_files, find_symbols
from app.ingestion.loader import SourceFile


def make_python_file():
    functions = []
    for index in range(12):
        functions.append(
            f"def function_{index}(value):\n"
            f'    """Docstring for function {index}."""\n'
            f"    result = value * {index} + 1\n"
            f"    return result\n"
        )
    return SourceFile("pkg/module.py", "python", "code", "\n\n".join(functions))


def test_chunks_carry_file_and_line_metadata():
    source = make_python_file()
    chunks = chunk_files([source], chunk_size=300, chunk_overlap=0)
    assert len(chunks) > 1
    lines = source.text.splitlines()
    for chunk in chunks:
        meta = chunk.metadata
        assert meta["path"] == "pkg/module.py"
        assert meta["language"] == "python"
        first_line = chunk_body(chunk).strip().splitlines()[0].strip()
        assert first_line == lines[meta["start_line"] - 1].strip()
        assert meta["end_line"] >= meta["start_line"]


def test_chunk_ids_are_unique():
    chunks = chunk_files([make_python_file()], chunk_size=300, chunk_overlap=0)
    ids = [c.metadata["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))


def test_symbols_are_extracted():
    assert find_symbols("def alpha():\n    pass\n\nclass Beta:\n    pass\n") == ["alpha", "Beta"]


def test_overview_lists_files():
    files = [SourceFile("a.py", "python", "code", "x\n"), SourceFile("README.md", "markdown", "docs", "hi")]
    overview = build_overview_document(files, "owner/repo")
    assert overview.metadata["kind"] == "overview"
    assert "a.py" in overview.page_content and "README.md" in overview.page_content
