"""Typed, fail-closed platform errors."""


class PlatformError(Exception):
    code = "PLATFORM_ERROR"
    exit_code = 1

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationError(PlatformError):
    code = "VALIDATION_FAILED"
    exit_code = 7


class AuthenticationError(PlatformError):
    code = "AUTHENTICATION_FAILED"
    exit_code = 3


class AuthorizationError(PlatformError):
    code = "AUTHORIZATION_DENIED"
    exit_code = 4


class QualityGateError(PlatformError):
    code = "QUALITY_GATE_FAILED"
    exit_code = 7


class ApprovalRequiredError(PlatformError):
    code = "APPROVAL_REQUIRED"
    exit_code = 6


class AgentReviewError(PlatformError):
    code = "AGENT_REVIEW_FAILED"
    exit_code = 7

    def __init__(
        self,
        message: str,
        *,
        error_class: str = "INTERNAL",
        retryable: bool = False,
        unavailable: bool = False,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.error_class = error_class
        self.retryable = retryable
        self.unavailable = unavailable


class PersonaCouncilError(PlatformError):
    code = "PERSONA_COUNCIL_FAILED"
    exit_code = 7

    def __init__(
        self,
        message: str,
        *,
        error_class: str = "INTERNAL",
        unavailable: bool = False,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.error_class = error_class
        self.unavailable = unavailable


class StateConflictError(PlatformError):
    code = "STATE_CONFLICT"
    exit_code = 6


class NotFoundError(PlatformError):
    code = "RESOURCE_NOT_FOUND"
    exit_code = 5


class RenderingError(PlatformError):
    code = "RENDERING_ERROR"
    failure_class = "permanent"

    def __init__(
        self,
        message: str,
        *,
        render_task_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.render_task_id = render_task_id

    def as_dict(self) -> dict:
        value = super().as_dict()
        value.update(
            {"render_task_id": self.render_task_id, "failure_class": self.failure_class}
        )
        return value


class StoryboardNotApprovedError(RenderingError):
    code = "STORYBOARD_NOT_APPROVED"


class ProviderSubmissionError(RenderingError):
    code = "PROVIDER_SUBMISSION_FAILED"
    failure_class = "transient"


class ProviderTimeoutError(RenderingError):
    code = "PROVIDER_TIMEOUT"
    failure_class = "transient"


class AssetValidationError(RenderingError):
    code = "ASSET_VALIDATION_FAILED"


class QualityBelowThresholdError(RenderingError):
    code = "QUALITY_BELOW_THRESHOLD"
    failure_class = "quality"


class BudgetExhaustedError(RenderingError):
    code = "BUDGET_EXHAUSTED"
    failure_class = "budget"
