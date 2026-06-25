from __future__ import annotations

from unlimited_skills.registration import base64_urlsafe_decode
from unlimited_skills.signatures import key_record_allows, trusted_manifest_key_records


def test_registry_prod_manifest_key_is_bundled_for_clean_clients() -> None:
    records = trusted_manifest_key_records(include_public=True)
    key_ids = [record["key_id"] for record in records]
    assert len(key_ids) == len(set(key_ids))

    record = next(item for item in records if item["key_id"] == "registry-prod-2026-06-25")
    assert record["public_key"] == "qoKlymz97CLckL4zIdjI2BjYxYPvvaLYBKcV153BNE4"
    assert len(base64_urlsafe_decode(record["public_key"])) == 32
    assert key_record_allows(record, scope="community-catalog")
    assert key_record_allows(record, scope="catalog-updates", registry_url="https://unlimited.ai4.sale/v1/catalog")
    assert not key_record_allows(record, scope="community-catalog", registry_url="https://evil.example")
