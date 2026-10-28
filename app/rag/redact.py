"""Remove secret values from code before it is sent to a cloud LLM."""
import re

PLACEHOLDER = "[REDACTED]"

ASSIGNMENT = re.compile(
    r"""(?P<lead>\b\w*(?:secret|password|passwd|token|api[_-]?key|private[_-]?key)\w*\s*[=:]\s*)
        (?P<quote>["'])(?P<value>[^"'\n]{4,})(?P=quote)""",
    re.IGNORECASE | re.VERBOSE,
)
PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
)
KNOWN_TOKENS = re.compile(r"\b(?:AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|sk-[A-Za-z0-9]{20,})\b")


def redact_secrets(text):
    text = PRIVATE_KEY_BLOCK.sub(PLACEHOLDER, text)
    text = KNOWN_TOKENS.sub(PLACEHOLDER, text)
    return ASSIGNMENT.sub(
        lambda m: f"{m.group('lead')}{m.group('quote')}{PLACEHOLDER}{m.group('quote')}", text
    )
