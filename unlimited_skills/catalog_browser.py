from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .catalog_quality import CatalogQualityClient, assert_quality_allows_hosted_install, install_risk_message, quality_below_threshold
from .community import CommunityClient, CommunityError
from .registration import RegistrationError, RegistrationState, post_json
from .signatures import ManifestSignatureError, verify_manifest_signature
from .updates import RegistrationRequired, current_collection_state


CATALOG_BROWSER_REQUIRED_MESSAGE = (
    "Registration is required for hosted catalog browser operations. "
    "The MIT local search/list/view commands still work offline. Run: unlimited-skills register"
)
INSTALLABLE_STATUSES = {"approved", "published"}
WARNING_STATUSES = {"deprecated", "retired"}


class CatalogBrowserError(RuntimeError):
    """Raised when hosted catalog browser operations cannot proceed safely."""


class CatalogBrowserRegistrationRequired(RegistrationRequired):
    """Raised when catalog browser is requested without registration."""


@dataclass(frozen=True)
class CatalogBrowserItem:
    item_id: str
    pack_id: str
    collection: str = ""
    version: str = ""
    channel: str = "stable"
    source: str = "official"
    skill_kind: str = "skill-pack"
    categories: tuple[str, ...] = ()
    compatible_agents: tuple[str, ...] = ()
    plan_requirement: str = "registered-community"
    review_status: str = "published"
    deprecated: bool = False
    retired: bool = False
    installable: bool = False
    requires_registration: bool = True
    description: str = ""
    license: str = ""
    source_repo: str = ""
    skill_count: int = 0
    requirements: tuple[str, ...] = ()
    distribution_policy: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    body_included: bool = False
    quality_grade: str = ""
    score_band: str = ""
    last_eval_at: str = ""
    blockers: tuple[str, ...] = ()
    compatibility_notes: tuple[str, ...] = ()
    deprecation_status: str = "active"
    feedback_issue_categories: tuple[str, ...] = ()
    install_risk: str = ""


@dataclass(frozen=True)
class CatalogInstallResult:
    item_id: str
    pack_id: str
    review_status: str
    installable: bool
    dry_run: bool
    installed: bool = False
    delegated_source: str = ""
    message: str = ""
    quality_grade: str = ""
    quality_warning: str = ""


def _tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return ()


def _item_from_json(data: dict[str, Any]) -> CatalogBrowserItem:
    item_id = str(data.get("item_id") or "")
    pack_id = str(data.get("pack_id") or data.get("id") or item_id)
    if not item_id or not pack_id:
        raise CatalogBrowserError("Catalog browser item is missing item_id or pack_id.")
    quality = data.get("quality_status") if isinstance(data.get("quality_status"), dict) else {}
    return CatalogBrowserItem(
        item_id=item_id,
        pack_id=pack_id,
        collection=str(data.get("collection") or ""),
        version=str(data.get("version") or ""),
        channel=str(data.get("channel") or "stable"),
        source=str(data.get("source") or "official"),
        skill_kind=str(data.get("skill_kind") or "skill-pack"),
        categories=_tuple(data.get("categories")),
        compatible_agents=_tuple(data.get("compatible_agents")),
        plan_requirement=str(data.get("plan_requirement") or "registered-community"),
        review_status=str(data.get("review_status") or "published"),
        deprecated=bool(data.get("deprecated")),
        retired=bool(data.get("retired")),
        installable=bool(data.get("installable")),
        requires_registration=bool(data.get("requires_registration", True)),
        description=str(data.get("description") or ""),
        license=str(data.get("license") or ""),
        source_repo=str(data.get("source_repo") or ""),
        skill_count=int(data.get("skill_count") or 0),
        requirements=_tuple(data.get("requirements")),
        distribution_policy=data.get("distribution_policy") if isinstance(data.get("distribution_policy"), dict) else {},
        warnings=_tuple(data.get("warnings")),
        body_included=bool(data.get("body_included")),
        quality_grade=str(quality.get("quality_grade") or data.get("quality_grade") or ""),
        score_band=str(quality.get("score_band") or data.get("score_band") or ""),
        last_eval_at=str(quality.get("last_eval_at") or data.get("last_eval_at") or ""),
        blockers=_tuple(quality.get("blockers") or data.get("blockers")),
        compatibility_notes=_tuple(quality.get("compatibility_notes") or data.get("compatibility_notes")),
        deprecation_status=str(quality.get("deprecation_status") or data.get("deprecation_status") or ("retired" if data.get("retired") else "active")),
        feedback_issue_categories=_tuple(quality.get("feedback_issue_categories") or data.get("feedback_issue_categories")),
        install_risk=str(quality.get("install_risk") or data.get("install_risk") or ""),
    )


def _verify_signed_catalog_browser_payload(data: dict[str, Any], *, purpose: str) -> None:
    try:
        verify_manifest_signature(
            data,
            purpose=purpose,
            required=True,
            scope=str(data.get("manifest_type") or "catalog-browser-response"),
            registry_url="",
        )
    except ManifestSignatureError as exc:
        raise CatalogBrowserError(str(exc)) from exc


def _items_from_payload(payload: dict[str, Any]) -> list[CatalogBrowserItem]:
    raw = payload.get("items") or []
    if not isinstance(raw, list):
        raise CatalogBrowserError("Catalog browser response must include an items list.")
    return [_item_from_json(item) for item in raw if isinstance(item, dict)]


def assert_item_installable(item: CatalogBrowserItem) -> None:
    if item.body_included:
        raise CatalogBrowserError("Catalog browser metadata unexpectedly included a skill body.")
    if item.review_status not in INSTALLABLE_STATUSES:
        raise CatalogBrowserError("Catalog install is available only for approved or published signed items.")
    if not item.installable:
        raise CatalogBrowserError("Catalog item is not installable.")
    if item.deprecated or item.retired:
        raise CatalogBrowserError("Deprecated or retired catalog items require an explicit future recovery flow and cannot install silently.")


def safe_visible_items(items: list[CatalogBrowserItem], *, include_deprecated: bool = False) -> list[CatalogBrowserItem]:
    visible: list[CatalogBrowserItem] = []
    for item in items:
        if item.review_status in INSTALLABLE_STATUSES:
            visible.append(item)
        elif include_deprecated and item.review_status in WARNING_STATUSES:
            visible.append(item)
    return visible


def redacted_catalog_browser_summary() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "registered_operation": True,
        "metadata_only": True,
        "queries_included": False,
        "item_names_included": False,
        "skill_bodies_included": False,
        "private_paths_included": False,
    }


class CatalogBrowserClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0) -> None:
        if not state.registered:
            raise CatalogBrowserRegistrationRequired(CATALOG_BROWSER_REQUIRED_MESSAGE)
        self.state = state
        self.timeout = timeout

    def _client_payload(self) -> dict[str, str]:
        from . import __version__

        return {"name": "unlimited-skills", "version": __version__}

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        return post_json(
            f"{self.state.server_url.rstrip('/')}{endpoint}",
            payload,
            token=self.state.license_token,
            proof_state=self.state,
            timeout=self.timeout,
        )

    def _payload(self, root: Path | None = None, **extra: Any) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": self._client_payload(),
        }
        if root is not None:
            payload["collections"] = current_collection_state(root)
        for key, value in extra.items():
            if value in {"", None, ()} or value == []:
                continue
            payload[key] = value
        return payload

    def browse(
        self,
        root: Path,
        *,
        channel: str = "",
        source: str = "",
        compatible_agent: str = "",
        skill_kind: str = "",
        category: str = "",
        include_deprecated: bool = False,
        show_quality: bool = False,
        limit: int = 50,
    ) -> list[CatalogBrowserItem]:
        response = self._post(
            "/v1/catalog/browser/list",
            self._payload(
                root,
                channel=channel,
                source=source,
                compatible_agent=compatible_agent,
                skill_kind=skill_kind,
                category=category,
                include_deprecated=include_deprecated,
                include_quality=show_quality,
                limit=limit,
            ),
        )
        _verify_signed_catalog_browser_payload(response, purpose="Catalog browser list")
        return safe_visible_items(_items_from_payload(response), include_deprecated=include_deprecated)[: max(1, min(limit, 500))]

    def search(
        self,
        root: Path,
        *,
        query: str,
        channel: str = "",
        source: str = "",
        compatible_agent: str = "",
        skill_kind: str = "",
        category: str = "",
        include_deprecated: bool = False,
        show_quality: bool = False,
        limit: int = 20,
    ) -> list[CatalogBrowserItem]:
        response = self._post(
            "/v1/catalog/browser/search",
            self._payload(
                root,
                query=query,
                channel=channel,
                source=source,
                compatible_agent=compatible_agent,
                skill_kind=skill_kind,
                category=category,
                include_deprecated=include_deprecated,
                include_quality=show_quality,
                limit=limit,
            ),
        )
        _verify_signed_catalog_browser_payload(response, purpose="Catalog browser search")
        return safe_visible_items(_items_from_payload(response), include_deprecated=include_deprecated)[: max(1, min(limit, 500))]

    def filters(self, *, channel: str = "") -> dict[str, Any]:
        response = self._post("/v1/catalog/browser/filters", self._payload(channel=channel))
        _verify_signed_catalog_browser_payload(response, purpose="Catalog browser filters")
        return response

    def item(self, item_id: str, *, channel: str = "") -> CatalogBrowserItem:
        response = self._post("/v1/catalog/browser/item", self._payload(item_id=item_id, channel=channel))
        _verify_signed_catalog_browser_payload(response, purpose="Catalog browser item")
        raw = response.get("item") if isinstance(response.get("item"), dict) else {}
        return _item_from_json(raw)

    def preview(self, item_id: str, *, channel: str = "") -> dict[str, Any]:
        response = self._post("/v1/catalog/browser/preview", self._payload(item_id=item_id, channel=channel))
        _verify_signed_catalog_browser_payload(response, purpose="Catalog browser preview")
        raw = response.get("item") if isinstance(response.get("item"), dict) else {}
        item = _item_from_json(raw)
        preview = raw.get("preview") if isinstance(raw.get("preview"), dict) else {}
        if item.body_included or bool(preview.get("body_included")):
            raise CatalogBrowserError("Catalog preview unexpectedly included a skill body.")
        return response

    def install(
        self,
        root: Path,
        *,
        item_id: str,
        dry_run: bool = False,
        yes: bool = False,
        target_collection: str = "",
        skip_reindex: bool = False,
    ) -> CatalogInstallResult | dict[str, Any]:
        _ = skip_reindex
        item = self.item(item_id)
        assert_item_installable(item)
        quality = CatalogQualityClient(self.state, timeout=self.timeout).quality(item.item_id)
        assert_quality_allows_hosted_install(quality)
        quality_warning = install_risk_message(quality)
        if dry_run:
            return CatalogInstallResult(
                item_id=item.item_id,
                pack_id=item.pack_id,
                review_status=item.review_status,
                installable=True,
                dry_run=True,
                message="Dry run: signed approved/published metadata and quality status verified; no files written.",
                quality_grade=quality.quality_grade,
                quality_warning=quality_warning if quality_below_threshold(quality.quality_grade) or quality.warnings else "",
            )
        if not yes:
            raise CatalogBrowserError("Catalog install requires --yes unless --dry-run is used.")
        if item.source != "community":
            raise CatalogBrowserError("Catalog install currently delegates write operations only for community source items. Use --dry-run for metadata verification.")
        result = CommunityClient(self.state, timeout=self.timeout).install_community_item(
            root,
            item_id=item.item_id,
            target_collection=target_collection,
            dry_run=False,
            force=False,
        )
        return {
            "catalog_item": asdict(item),
            "delegated_install": asdict(result),
            "dry_run": False,
            "installed": True,
            "quality_status": quality.to_json(),
            "quality_warning": quality_warning if quality_below_threshold(quality.quality_grade) or quality.warnings else "",
        }
