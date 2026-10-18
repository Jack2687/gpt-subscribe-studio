"""Offline synthetic tests for Hosted Checkout rv_timestamp helpers."""
from __future__ import annotations

from gss_core.hosted_timing import (
    RVBuildFields,
    decode_rv_timestamp,
    encode_rv_timestamp,
    extract_rv_build_fields,
    rv_timestamp_from_script,
)


_FIXTURE = RVBuildFields(
    rv_ts="2024-01-01 00:00:00 -0000",
    rv="fixture-build-revision",
    sv="fixture-signature-value",
)


def test_encode_decode_roundtrip_uses_only_supplied_fixture_salts() -> None:
    encoded = encode_rv_timestamp(_FIXTURE.rv_ts, _FIXTURE.rv, _FIXTURE.sv)

    assert len(encoded) > 0
    assert encoded != _FIXTURE.rv
    assert decode_rv_timestamp(encoded) == _FIXTURE


def test_extracts_direct_object_literals_and_encodes_them() -> None:
    script = (
        'const payload = {rvTs:"2024-01-01 00:00:00 -0000",'
        'rv:"fixture-rv",sv:"fixture-sv"};'
    )

    assert extract_rv_build_fields(script) == RVBuildFields(
        "2024-01-01 00:00:00 -0000", "fixture-rv", "fixture-sv"
    )
    encoded = rv_timestamp_from_script(script)
    assert encoded is not None
    assert decode_rv_timestamp(encoded) == extract_rv_build_fields(script)


def test_extracts_identifier_aliases_with_quoted_keys() -> None:
    script = """
      const TS = '2024-01-01 00:00:00 -0000';
      let BUILD = "fixture-build";
      var SIGNATURE = `fixture-signature`;
      const data = {"rvTs": TS, 'rv': BUILD, sv: SIGNATURE};
    """

    assert extract_rv_build_fields(script) == RVBuildFields(
        "2024-01-01 00:00:00 -0000", "fixture-build", "fixture-signature"
    )


def test_missing_or_dynamic_values_return_none_without_execution() -> None:
    assert extract_rv_build_fields("const data = {rvTs: Date.now(), rv: RV, sv: SV};") is None
    assert extract_rv_build_fields("const data = {rvTs:'x', rv:'y'};") is None
    assert rv_timestamp_from_script("") is None
    assert decode_rv_timestamp("not-a-captured-value") is None
