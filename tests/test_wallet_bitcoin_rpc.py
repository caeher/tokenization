from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from services.wallet.bitcoin_rpc import BitcoinRPCClient, BitcoinRPCError


class _SettingsStub:
    bitcoin_rpc_endpoint = "http://localhost:18443"
    bitcoin_rpc_user = "user"
    bitcoin_rpc_password = "pass"
    bitcoin_wallet_name = "tokenization-watchonly"


class _ResponseStub:
    def __init__(self, result: Any) -> None:
        self._result = result

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"result": self._result, "error": None}


class _AsyncClientStub:
    def __init__(self, recorder: list[tuple[str, dict[str, Any]]], responses: list[Any], **_: Any) -> None:
        self._recorder = recorder
        self._responses = responses

    async def __aenter__(self) -> _AsyncClientStub:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> _ResponseStub:
        self._recorder.append((url, kwargs))
        return _ResponseStub(self._responses.pop(0))


@pytest.mark.asyncio
async def test_importaddress_retries_after_loading_default_wallet() -> None:
    client = BitcoinRPCClient(_SettingsStub())
    client._call = AsyncMock(
        side_effect=[
            BitcoinRPCError("No wallet is loaded", code=-19),
            None,
            None,
        ]
    )

    await client.importaddress("bcrt1qexample")

    assert client._call.await_args_list[0].args[0] == "importaddress"
    assert client._call.await_args_list[1].args == ("loadwallet", "tokenization-watchonly")
    assert client._call.await_args_list[2].args[0] == "importaddress"


@pytest.mark.asyncio
async def test_importaddress_creates_wallet_when_default_missing() -> None:
    client = BitcoinRPCClient(_SettingsStub())
    client._call = AsyncMock(
        side_effect=[
            BitcoinRPCError("No wallet is loaded", code=-19),
            BitcoinRPCError("Requested wallet does not exist or is not loaded", code=-18),
            None,
            None,
        ]
    )

    await client.importaddress("bcrt1qexample")

    assert client._call.await_args_list[1].args == ("loadwallet", "tokenization-watchonly")
    assert client._call.await_args_list[2].args == (
        "createwallet",
        "tokenization-watchonly",
        True,
        True,
        "",
        False,
        True,
    )
    assert client._call.await_args_list[3].args[0] == "importaddress"


@pytest.mark.asyncio
async def test_importaddress_does_not_retry_on_unrelated_rpc_error() -> None:
    client = BitcoinRPCClient(_SettingsStub())
    client._call = AsyncMock(side_effect=BitcoinRPCError("RPC auth failed", code=-32601))

    with pytest.raises(BitcoinRPCError):
        await client.importaddress("bcrt1qexample")

    assert client._call.await_count == 1


@pytest.mark.asyncio
async def test_importaddress_falls_back_to_importdescriptors_for_descriptor_wallets() -> None:
    client = BitcoinRPCClient(_SettingsStub())
    client._call = AsyncMock(
        side_effect=[
            BitcoinRPCError("Only legacy wallets are supported by this command", code=-4),
            {"descriptor": "addr(bcrt1qexample)#abcd1234"},
            [{"success": True}],
        ]
    )

    await client.importaddress("bcrt1qexample")

    assert client._call.await_args_list[0].args[0] == "importaddress"
    assert client._call.await_args_list[1].args == ("getdescriptorinfo", "addr(bcrt1qexample)")
    assert client._call.await_args_list[2].args[0] == "importdescriptors"


@pytest.mark.asyncio
async def test_importaddress_uses_wallet_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded_requests: list[tuple[str, dict[str, Any]]] = []
    responses = [None]

    def _client_factory(*args: Any, **kwargs: Any) -> _AsyncClientStub:
        return _AsyncClientStub(recorded_requests, responses, **kwargs)

    monkeypatch.setattr("services.wallet.bitcoin_rpc.httpx.AsyncClient", _client_factory)

    client = BitcoinRPCClient(_SettingsStub())
    await client.importaddress("bcrt1qexample")

    assert recorded_requests[0][0] == "http://localhost:18443/wallet/tokenization-watchonly"
    assert recorded_requests[0][1]["json"]["method"] == "importaddress"
