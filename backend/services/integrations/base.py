"""
backend/services/integrations/base.py
──────────────────────────────────────
Abstract base class for all external data integration providers.
Every provider (CKYC, CIBIL, Lab, AML etc.) inherits from IntegrationProvider
and implements the `verify()` method.

Provider registry maps provider_code → class.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class IntegrationResult:
    """Structured result returned by every provider."""

    def __init__(
        self,
        success: bool,
        provider_code: str,
        integration_type: str,
        # Identity
        kyc_verified: bool | None = None,
        kyc_name: str | None = None,
        kyc_dob: str | None = None,
        kyc_pan: str | None = None,
        kyc_aadhaar_masked: str | None = None,
        kyc_address: str | None = None,
        # Credit
        credit_score: int | None = None,
        credit_bureau: str | None = None,
        credit_report_ref: str | None = None,
        credit_flags: list | None = None,
        # Lab
        lab_order_ref: str | None = None,
        lab_tests: list | None = None,
        lab_report_url: str | None = None,
        # AML
        aml_status: str | None = None,
        aml_flags: list | None = None,
        # General
        confidence_score: float = 1.0,
        raw_response: dict | None = None,
        error: str | None = None,
        notes: str | None = None,
        expires_in_days: int = 90,
    ):
        self.success          = success
        self.provider_code    = provider_code
        self.integration_type = integration_type
        self.kyc_verified     = kyc_verified
        self.kyc_name         = kyc_name
        self.kyc_dob          = kyc_dob
        self.kyc_pan          = kyc_pan
        self.kyc_aadhaar_masked = kyc_aadhaar_masked
        self.kyc_address      = kyc_address
        self.credit_score     = credit_score
        self.credit_bureau    = credit_bureau
        self.credit_report_ref = credit_report_ref
        self.credit_flags     = credit_flags or []
        self.lab_order_ref    = lab_order_ref
        self.lab_tests        = lab_tests or []
        self.lab_report_url   = lab_report_url
        self.aml_status       = aml_status
        self.aml_flags        = aml_flags or []
        self.confidence_score = confidence_score
        self.raw_response     = raw_response or {}
        self.error            = error
        self.notes            = notes
        self.expires_in_days  = expires_in_days

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class IntegrationProvider(ABC):
    """Abstract base — all providers implement verify()."""

    provider_code: str = ""
    integration_type: str = ""
    is_mock: bool = False

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    def verify(self, payload: dict) -> IntegrationResult:
        """
        Run the verification check.
        payload contains applicant data (name, dob, pan, etc.)
        Returns an IntegrationResult.
        """
        ...

    def is_available(self) -> bool:
        """Check if provider is reachable — override for live providers."""
        return True


# ── Provider Registry ─────────────────────────────────────────────────────────
_REGISTRY: dict[str, type[IntegrationProvider]] = {}


def register(cls: type[IntegrationProvider]) -> type[IntegrationProvider]:
    """Decorator to register a provider in the global registry."""
    _REGISTRY[cls.provider_code] = cls
    return cls


def get_provider(provider_code: str, config: dict | None = None) -> IntegrationProvider:
    """Get a provider instance by code. Raises ValueError if not found."""
    cls = _REGISTRY.get(provider_code)
    if not cls:
        raise ValueError(f"Unknown integration provider: {provider_code}. "
                         f"Available: {list(_REGISTRY.keys())}")
    return cls(config=config)


def list_providers() -> list[str]:
    return list(_REGISTRY.keys())
