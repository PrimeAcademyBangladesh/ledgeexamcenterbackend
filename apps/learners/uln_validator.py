"""
ULN (Unique Learner Number) validation — UK LRS Modulus-11.

Rules (must pass ALL):
  1. Exactly 10 characters, digits only
  2. Cannot start with 0
  3. Cannot be all the same digit (e.g. 1111111111)
  4. Mod-11 checksum: weights 10..2 on first 9 digits,
     check_digit = 10 - (sum % 11);  if result == 10 -> INVALID (LRS never issues)
                                     if result == 11 -> check_digit = 0
"""

import re

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers


class UlnValidationError(ValueError):
    """Raised by `validate_uln`. `.reason` holds the human-readable message."""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_uln(uln: str) -> str:
    """
    Validate a ULN and return its cleaned form.
    Raises UlnValidationError on any rule failure.
    """
    if uln is None:
        raise UlnValidationError("ULN is required")

    cleaned = str(uln).strip()

    if not cleaned:
        raise UlnValidationError("ULN is required")
    if not re.fullmatch(r"\d+", cleaned):
        raise UlnValidationError("ULN must contain digits only")
    if len(cleaned) != 10:
        raise UlnValidationError("ULN must be exactly 10 digits")
    if cleaned.startswith("0"):
        raise UlnValidationError("ULN cannot start with 0")
    if len(set(cleaned)) == 1:
        raise UlnValidationError("ULN cannot be all the same digit")

    digits = [int(c) for c in cleaned]
    weights = [10, 9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(w * d for w, d in zip(weights, digits[:9]))

    remainder = total % 11
    expected_check = 10 - remainder  # 1..10

    if expected_check == 10:
        raise UlnValidationError(
            "Invalid ULN (checksum impossible — number never issued by LRS)"
        )

    check_digit = 0 if expected_check == 11 else expected_check

    if check_digit != digits[9]:
        raise UlnValidationError("Invalid ULN — checksum does not match (typo?)")

    return cleaned


def is_valid_uln(uln: str) -> bool:
    """Boolean wrapper."""
    try:
        validate_uln(uln)
        return True
    except UlnValidationError:
        return False


def drf_validate_uln(value: str) -> str:
    """Field-level validator for DRF serializers."""
    try:
        return validate_uln(value)
    except UlnValidationError as e:
        raise serializers.ValidationError(e.reason)


def django_validate_uln(value: str) -> None:
    """Validator for Django model fields (raises Django's ValidationError)."""
    try:
        validate_uln(value)
    except UlnValidationError as e:
        raise DjangoValidationError(e.reason)
