"""Tenant isolation helpers for dispatch (unit tests without DB)."""


def tenant_member_query_filters(tenant_id: str, member_id: str | None = None) -> dict[str, str]:
    """Espelha o filtro usado nas rotas JWT: sempre escopa por tenant_id."""
    filters = {"tenant_id": tenant_id}
    if member_id:
        filters["id"] = member_id
    return filters


def test_tenant_filters_include_tenant_id():
    f = tenant_member_query_filters("tenant-a")
    assert f == {"tenant_id": "tenant-a"}


def test_tenant_filters_two_tenants_never_share_key():
    a = tenant_member_query_filters("tenant-a", "m1")
    b = tenant_member_query_filters("tenant-b", "m1")
    assert a["tenant_id"] != b["tenant_id"]
    assert a["id"] == b["id"]
