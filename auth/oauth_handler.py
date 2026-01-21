"""OAuth authentication handler for MCP Server."""
import hmac
import hashlib
from typing import Optional


class OAuthHandler:
    """Handles OAuth Client ID/Secret validation."""

    def __init__(self, client_id: str, client_secret: str):
        """Initialize OAuth handler with credentials.

        Args:
            client_id: OAuth Client ID
            client_secret: OAuth Client Secret
        """
        self.client_id = client_id
        self.client_secret = client_secret

    def validate_credentials(self, provided_id: str, provided_secret: str) -> bool:
        """Validate provided OAuth credentials.

        Args:
            provided_id: Client ID to validate
            provided_secret: Client Secret to validate

        Returns:
            True if credentials are valid, False otherwise
        """
        # Use constant-time comparison to prevent timing attacks
        id_match = hmac.compare_digest(self.client_id, provided_id)
        secret_match = hmac.compare_digest(self.client_secret, provided_secret)
        return id_match and secret_match

    def extract_bearer_token(self, authorization_header: Optional[str]) -> Optional[str]:
        """Extract token from Authorization header.

        Args:
            authorization_header: The Authorization header value

        Returns:
            The bearer token if present, None otherwise
        """
        if not authorization_header:
            return None

        parts = authorization_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]

        return None
