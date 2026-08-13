import asyncio

import gsc_server
from gsc_remote import credentials


def test_upstream_chokepoint_still_exists():
    """The whole design rests on this one upstream function. If a rebase
    renames or removes it, fail here rather than at runtime."""
    assert callable(gsc_server.get_gsc_service)


def test_patch_falls_back_to_upstream_when_unset(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(
        credentials, "_original_get_gsc_service", lambda: sentinel
    )
    credentials.apply_patch()
    assert gsc_server.get_gsc_service() is sentinel


def test_contextvar_builds_a_per_request_service(monkeypatch):
    built = []

    def fake_build(serviceName, version, credentials=None, **kwargs):
        built.append((serviceName, version, credentials, kwargs))
        return f"service-for-{credentials}"

    monkeypatch.setattr(credentials, "build", fake_build)
    credentials.apply_patch()
    with credentials.use_credentials("user-creds"):
        assert gsc_server.get_gsc_service() == "service-for-user-creds"
    assert built[0][0] == "searchconsole"
    assert built[0][1] == "v1"
    assert built[0][3]["cache_discovery"] is False
    assert credentials.current_credentials.get() is None


def test_patch_is_idempotent(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(
        credentials, "_original_get_gsc_service", lambda: sentinel
    )
    credentials.apply_patch()
    credentials.apply_patch()
    assert gsc_server.get_gsc_service() is sentinel


def test_contextvar_is_task_isolated(monkeypatch):
    monkeypatch.setattr(
        credentials,
        "build",
        lambda serviceName, version, credentials=None, **kw: credentials,
    )
    credentials.apply_patch()

    async def worker(value):
        with credentials.use_credentials(value):
            await asyncio.sleep(0)
            return gsc_server.get_gsc_service()

    async def main():
        return await asyncio.gather(worker("a"), worker("b"))

    assert asyncio.run(main()) == ["a", "b"]
