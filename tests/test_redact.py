from app.rag.redact import PLACEHOLDER, redact_secrets


def test_assignment_values_are_redacted_but_names_kept():
    result = redact_secrets('SECRET_KEY = "hunter2hunter2"\nDEBUG = True')
    assert "hunter2hunter2" not in result
    assert f'SECRET_KEY = "{PLACEHOLDER}"' in result
    assert "DEBUG = True" in result


def test_jwt_secret_and_password_are_redacted():
    text = "JWT_SECRET = 'abc12345'\nDEFAULT_ADMIN_PASSWORD = \"admin123\"\n"
    result = redact_secrets(text)
    assert "abc12345" not in result and "admin123" not in result


def test_known_token_formats_are_redacted():
    result = redact_secrets("key = AKIAABCDEFGHIJKLMNOP and ghp_" + "a" * 36)
    assert "AKIAABCDEFGHIJKLMNOP" not in result
    assert "ghp_" not in result


def test_private_key_block_is_redacted():
    block = "-----BEGIN RSA PRIVATE KEY-----\nabcdef\n-----END RSA PRIVATE KEY-----"
    assert redact_secrets(f"x\n{block}\ny") == f"x\n{PLACEHOLDER}\ny"


def test_normal_code_is_untouched():
    code = "def login(username, password):\n    return check(username, password)\n"
    assert redact_secrets(code) == code
