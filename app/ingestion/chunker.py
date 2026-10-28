"""Split source files into code-aware chunks with file and line metadata."""
import re

from langchain_core.documents import Document
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

LANGUAGE_MAP = {
    "python": Language.PYTHON,
    "js": Language.JS,
    "ts": Language.TS,
    "markdown": Language.MARKDOWN,
    "html": Language.HTML,
}

SYMBOL_PATTERN = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function)\s+(\w+)", re.MULTILINE
)

HEADER_PREFIX = "File: "


def make_splitter(language, chunk_size, chunk_overlap):
    options = {"chunk_size": chunk_size, "chunk_overlap": chunk_overlap, "add_start_index": True}
    if language in LANGUAGE_MAP:
        return RecursiveCharacterTextSplitter.from_language(LANGUAGE_MAP[language], **options)
    return RecursiveCharacterTextSplitter(**options)


def find_symbols(text):
    """Names of functions and classes defined in a chunk, in order of appearance."""
    return SYMBOL_PATTERN.findall(text)


def strip_header(text):
    """Return chunk text without the leading 'File: ...' header line."""
    if text.startswith(HEADER_PREFIX):
        return text.split("\n", 1)[1] if "\n" in text else ""
    return text


def chunk_body(document):
    return strip_header(document.page_content)


def chunk_files(files, chunk_size=1000, chunk_overlap=150):
    """Turn SourceFile objects into LangChain Documents ready for embedding."""
    documents = []
    for source in files:
        splitter = make_splitter(source.language, chunk_size, chunk_overlap)
        for piece in splitter.create_documents([source.text]):
            start_index = piece.metadata.get("start_index", 0)
            start_line = source.text.count("\n", 0, start_index) + 1
            end_line = start_line + piece.page_content.count("\n")
            symbols = find_symbols(piece.page_content)
            documents.append(
                Document(
                    page_content=f"{HEADER_PREFIX}{source.path}\n{piece.page_content}",
                    metadata={
                        "chunk_id": f"{source.path}:{start_line}-{end_line}",
                        "path": source.path,
                        "language": source.language,
                        "kind": source.kind,
                        "start_line": start_line,
                        "end_line": end_line,
                        "symbols": ", ".join(symbols[:5]),
                    },
                )
            )
    return documents


def build_overview_document(files, repo_name):
    """A synthetic chunk describing the repository layout, for 'explain this repo' questions."""
    lines = [f"Repository overview for {repo_name}", f"Total indexed files: {len(files)}", "", "File tree:"]
    for source in files:
        lines.append(f"- {source.path} ({source.language}, {source.text.count(chr(10)) + 1} lines)")
    text = "\n".join(lines)
    return Document(
        page_content=text,
        metadata={
            "chunk_id": "(overview)",
            "path": "(repository overview)",
            "language": "text",
            "kind": "overview",
            "start_line": 1,
            "end_line": len(lines),
            "symbols": "",
        },
    )
