"""Tests for API key encryption service."""

import os
import pytest
from unittest.mock import patch


class TestEncryptionRoundTrip:
    """encrypt_value / decrypt_value round-trip."""

    def setup_method(self):
        from app.services.encryption import _reset_fernet
        _reset_fernet()

    def test_round_trip_preserves_value(self):
        """Encrypted value should decrypt back to original."""
        from app.services.encryption import encrypt_value, decrypt_value

        original = "sk-abc123def456ghi789"
        encrypted = encrypt_value(original)
        decrypted = decrypt_value(encrypted)

        assert decrypted == original
        assert encrypted != original

    def test_empty_string_passthrough(self):
        """Empty string should pass through unchanged."""
        from app.services.encryption import encrypt_value, decrypt_value

        assert encrypt_value("") == ""
        assert decrypt_value("") == ""

    def test_different_ciphertexts_same_plaintext(self):
        """Fernet uses random IV, so same plaintext produces different ciphertexts."""
        from app.services.encryption import encrypt_value

        value = "sk-test-key-12345"
        c1 = encrypt_value(value)
        c2 = encrypt_value(value)

        assert c1 != c2

    def test_round_trip_unicode(self):
        """Should handle unicode values."""
        from app.services.encryption import encrypt_value, decrypt_value

        original = "测试密钥-🔑-abc123"
        assert decrypt_value(encrypt_value(original)) == original

    def test_round_trip_long_key(self):
        """Should handle realistic long API keys."""
        from app.services.encryption import encrypt_value, decrypt_value

        original = "sk-" + "a" * 200
        assert decrypt_value(encrypt_value(original)) == original


class TestDBDoesNotContainPlaintext:
    """Encrypted values in DB should not contain the original plaintext."""

    def setup_method(self):
        from app.services.encryption import _reset_fernet
        _reset_fernet()

    def test_encrypted_value_not_plaintext(self):
        """The encrypted output should not contain the original string."""
        from app.services.encryption import encrypt_value

        api_key = "sk-proj-very-secret-key-12345"
        encrypted = encrypt_value(api_key)

        assert api_key not in encrypted
        assert "secret" not in encrypted

    def test_encrypted_value_is_base64_like(self):
        """Fernet output should be URL-safe base64."""
        from app.services.encryption import encrypt_value

        encrypted = encrypt_value("test-value")
        # Fernet tokens are URL-safe base64
        import base64
        try:
            base64.urlsafe_b64decode(encrypted)
        except Exception:
            pytest.fail("Encrypted value is not valid URL-safe base64")


class TestDecryptionFailure:
    """Decryption with wrong key or corrupted data."""

    def setup_method(self):
        from app.services.encryption import _reset_fernet
        _reset_fernet()

    def test_wrong_key_returns_ciphertext(self):
        """Decryption with a different key should return the ciphertext as-is (migration period)."""
        from app.services.encryption import encrypt_value, _reset_fernet

        os.environ["JWT_SECRET"] = "secret-key-A-for-testing-12345678"
        _reset_fernet()
        encrypted = encrypt_value("my-api-key")

        # Change the secret
        os.environ["JWT_SECRET"] = "secret-key-B-for-testing-12345678"
        _reset_fernet()

        from app.services.encryption import decrypt_value
        result = decrypt_value(encrypted)

        # Should return the encrypted value as-is (graceful fallback)
        assert result == encrypted

        # Restore
        os.environ["JWT_SECRET"] = "secret-key-A-for-testing-12345678"
        _reset_fernet()

    def test_corrupted_ciphertext_returns_ciphertext(self):
        """Corrupted ciphertext should return as-is."""
        from app.services.encryption import decrypt_value

        corrupted = "not-a-valid-fernet-token!!!"
        result = decrypt_value(corrupted)
        assert result == corrupted

    def test_is_encrypted_false_for_plaintext(self):
        """is_encrypted should return False for plaintext values."""
        from app.services.encryption import is_encrypted

        assert is_encrypted("sk-my-api-key-12345") is False
        assert is_encrypted("") is False
        assert is_encrypted("short") is False

    def test_is_encrypted_true_for_encrypted(self):
        """is_encrypted should return True for encrypted values."""
        from app.services.encryption import encrypt_value, is_encrypted

        encrypted = encrypt_value("sk-my-api-key-12345")
        assert is_encrypted(encrypted) is True
