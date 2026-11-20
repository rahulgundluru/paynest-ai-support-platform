"""PII gate unit tests: one case per supported entity type, plus ordering and checksum behaviour.

All identifiers below are synthetic. Valid-checksum values are generated in the test, not copied.
"""

from app.services.pii.detectors import _VERHOEFF_D, _VERHOEFF_INV, _VERHOEFF_P, iban_valid, verhoeff_valid
from app.services.pii.gate import PiiGate, contains_pii


def _verhoeff_check_digit(number: str) -> str:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[(i + 1) % 8][int(ch)]]
    return str(_VERHOEFF_INV[c])


def _iban(country: str, bban: str) -> str:
    numeric = "".join(str(int(c, 36)) for c in bban + country + "00")
    return f"{country}{98 - int(numeric) % 97:02d}{bban}"


def redact(text: str):
    return PiiGate().redact({"body": text})


def test_aadhaar_with_and_without_valid_checksum_is_redacted():
    base = "23456789012"
    valid = base + _verhoeff_check_digit(base)
    assert verhoeff_valid(valid)
    for value, expected in ((f"{valid[:4]} {valid[4:8]} {valid[8:]}", True), ("0000 8036 4851", False)):
        result = redact(f"My Aadhaar is {value}, please verify.")
        assert result.fields["body"] == "My Aadhaar is <AADHAAR_1>, please verify."
        assert result.detections[0].checksum_valid is expected  # failed checksum never un-redacts


def test_pan_is_redacted():
    result = redact("PAN ABCDE0021F and ABCPE1234K")
    assert result.fields["body"] == "PAN <PAN_1> and <PAN_2>"
    assert [d.checksum_valid for d in result.detections] == [False, True]


def test_uae_iban_is_redacted_and_not_split_into_aadhaar():
    result = redact("Salary account IBAN AE00 0000 4446 3464 7496 591, Emirates ID 784-0000-2704973-0.")
    assert result.fields["body"] == "Salary account IBAN <IBAN_1>, Emirates ID <EMIRATES_ID_1>."
    assert {d.entity_type for d in result.detections} == {"IBAN", "EMIRATES_ID"}


def test_generic_iban_only_with_valid_checksum():
    good = _iban("GB", "WEST12345698765432")
    assert iban_valid(good)
    assert redact(f"IBAN {good}").fields["body"] == "IBAN <IBAN_1>"
    assert "IBAN" not in {d.entity_type for d in redact("Ref GB00WEST12345698765432").detections}


def test_bank_account_with_context_and_ifsc():
    result = redact("Bank details for the employee: A/C 93116992135, IFSC FAKE0347050. Please correct.")
    assert (
        result.fields["body"] == "Bank details for the employee: A/C <BANK_ACCOUNT_1>, IFSC <IFSC_1>. Please correct."
    )


def test_emirates_id_variants():
    for value in ("784-1990-1234567-1", "784 1990 1234567 1", "784199012345671"):
        assert redact(f"EID {value}").fields["body"] == "EID <EMIRATES_ID_1>"


def test_phone_and_email():
    result = redact("Call +971 50 123 4567 or +91 98765 43210, mail hr.admin@kestrel.example")
    assert result.fields["body"] == "Call <PHONE_1> or <PHONE_2>, mail <EMAIL_1>"


def test_same_value_reuses_token_across_fields():
    result = PiiGate().redact({"subject": "PAN ABCDE0021F", "body": "Again ABCDE0021F; also ABCDE0022F"})
    assert result.fields == {"subject": "PAN <PAN_1>", "body": "Again <PAN_1>; also <PAN_2>"}
    assert set(result.vault) == {"<PAN_1>", "<PAN_2>"}


def test_non_pii_text_is_untouched_in_all_scripts():
    texts = [
        "PF deduction differs from last month for 23 employees in the August run.",
        "छुट्टी का बैलेंस गलत दिख रहा है, कृपया ठीक करें।",
        "تحميل كشوف الرواتب: كيف يمكنني تحميل كشوف الرواتب لجميع الموظفين دفعة واحدة؟",
        "Ticket PN-100802 and Jira PNJ-4412, KB-0142 effective 2026-08-01, INR 25,000.",
    ]
    for text in texts:
        result = redact(text)
        assert result.fields["body"] == text, text
        assert not contains_pii(text)


def test_redacted_output_contains_no_pii():
    raw = "Aadhaar 0000 8036 4851 PAN ABCDE0021F IBAN AE00 0000 7195 4063 8567 020 EID 784-0000-4493392-0"
    assert contains_pii(raw)
    assert not contains_pii(redact(raw).fields["body"])
