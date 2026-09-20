from abc import ABC, abstractmethod


class AuthProvider(ABC):
    """Provider-agnostic authentication. Implementations return the user id."""

    @abstractmethod
    def verify_token(self, token: str) -> str:
        """Validate a bearer JWT and return the authenticated user's id."""
        ...
