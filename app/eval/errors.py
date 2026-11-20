"""Domain errors for review events."""
from __future__ import annotations


class ReviewEventError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def invalid(code: str, message: str) -> ReviewEventError:
    return ReviewEventError(code, message, 422)


def conflict(code: str, message: str) -> ReviewEventError:
    return ReviewEventError(code, message, 409)
