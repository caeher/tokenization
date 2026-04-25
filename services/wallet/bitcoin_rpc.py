import base64
import json
import logging
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

try:
    from common.config import Settings
except ImportError:
    from services.common.config import Settings

logger = logging.getLogger(__name__)

class BitcoinRPCError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code

class BitcoinRPCClient:
    """Async Bitcoin Core RPC Client."""

    def __init__(self, settings: Settings):
        self.url = settings.bitcoin_rpc_endpoint
        self.wallet_name = settings.bitcoin_wallet_name
        self.node_url, self.wallet_url = self._resolve_rpc_urls(
            self.url,
            self.wallet_name,
        )
        auth_string = f"{settings.bitcoin_rpc_user}:{settings.bitcoin_rpc_password or ''}"
        self.auth_header = "Basic " + base64.b64encode(auth_string.encode()).decode("utf-8")

    @staticmethod
    def _resolve_rpc_urls(endpoint: str, wallet_name: str) -> tuple[str, str]:
        parsed = urlsplit(endpoint)
        base_path = parsed.path.rstrip("/")
        wallet_marker = "/wallet/"
        wallet_index = base_path.find(wallet_marker)

        if wallet_index != -1:
            node_path = base_path[: wallet_index + 1] or "/"
            wallet_path = base_path
        else:
            node_path = base_path or "/"
            wallet_path = f"{node_path.rstrip('/')}/wallet/{quote(wallet_name, safe='')}"

        node_url = urlunsplit((parsed.scheme, parsed.netloc, node_path, parsed.query, parsed.fragment))
        wallet_url = urlunsplit((parsed.scheme, parsed.netloc, wallet_path, parsed.query, parsed.fragment))
        return node_url, wallet_url

    async def _call(self, method: str, *params: Any, wallet_scoped: bool = False) -> Any:
        headers = {"Authorization": self.auth_header, "Content-Type": "application/json"}
        payload = {
            "jsonrpc": "1.0",
            "id": "wallet_service",
            "method": method,
            "params": list(params),
        }
        request_url = self.wallet_url if wallet_scoped else self.node_url
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(request_url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            try:
                err_data = e.response.json()
                error_msg = err_data.get("error", {}).get("message", "Unknown RPC error")
                error_code = err_data.get("error", {}).get("code")
            except Exception:
                error_msg = f"HTTP Error {e.response.status_code}: {e.response.text}"
                error_code = None
            logger.error("Bitcoin RPC error calling %s: %s", method, error_msg)
            raise BitcoinRPCError(error_msg, error_code) from e
        except Exception as e:
            logger.error("Failed to connect to Bitcoin RPC calling %s: %s", method, e)
            raise BitcoinRPCError(f"Connection error: {e}") from e

        if data.get("error") is not None:
            err = data["error"]
            raise BitcoinRPCError(err.get("message", "RPC Error"), err.get("code"))

        return data.get("result")

    async def importdescriptors(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return await self._call("importdescriptors", requests, wallet_scoped=True)

    async def importaddress(
        self,
        address: str,
        label: str = "",
        rescan: bool = False,
        p2sh: bool = False,
    ) -> None:
        try:
            await self._call("importaddress", address, label, rescan, p2sh, wallet_scoped=True)
            return
        except BitcoinRPCError as exc:
            if self._is_legacy_only_importaddress_error(exc):
                await self._import_address_descriptor(address, label)
                return
            if not self._is_no_wallet_loaded_error(exc):
                raise

        await self._ensure_default_wallet_loaded()
        try:
            await self._call("importaddress", address, label, rescan, p2sh, wallet_scoped=True)
            return
        except BitcoinRPCError as exc:
            if self._is_legacy_only_importaddress_error(exc):
                await self._import_address_descriptor(address, label)
                return
            raise

    async def _import_address_descriptor(self, address: str, label: str) -> None:
        descriptor_info = await self.getdescriptorinfo(f"addr({address})")
        descriptor = descriptor_info.get("descriptor")
        if not descriptor:
            raise BitcoinRPCError("Descriptor info response missing descriptor")

        results = await self.importdescriptors(
            [{"desc": descriptor, "timestamp": "now", "label": label}]
        )
        if not results:
            raise BitcoinRPCError("importdescriptors returned an empty result")

        first_result = results[0]
        if not first_result.get("success", False):
            error_message = (
                first_result.get("error", {}).get("message")
                or "importdescriptors failed"
            )
            error_code = first_result.get("error", {}).get("code")
            raise BitcoinRPCError(error_message, error_code)

    async def _ensure_default_wallet_loaded(self) -> None:
        try:
            await self._call("loadwallet", self.wallet_name)
            return
        except BitcoinRPCError as exc:
            if self._is_wallet_already_loaded_error(exc):
                return
            if not self._is_wallet_missing_error(exc):
                raise

        await self._call(
            "createwallet",
            self.wallet_name,
            True,
            True,
            "",
            False,
            True,
        )

    @staticmethod
    def _is_no_wallet_loaded_error(exc: BitcoinRPCError) -> bool:
        message = str(exc).lower()
        return "no wallet is loaded" in message

    @staticmethod
    def _is_wallet_missing_error(exc: BitcoinRPCError) -> bool:
        message = str(exc).lower()
        return (
            exc.code == -18
            or "wallet file not found" in message
            or "does not exist" in message
        )

    @staticmethod
    def _is_wallet_already_loaded_error(exc: BitcoinRPCError) -> bool:
        return exc.code == -35 or "already loaded" in str(exc).lower()

    @staticmethod
    def _is_legacy_only_importaddress_error(exc: BitcoinRPCError) -> bool:
        message = str(exc).lower()
        return "only legacy wallets are supported by this command" in message

    async def getdescriptorinfo(self, descriptor: str) -> dict[str, Any]:
        return await self._call("getdescriptorinfo", descriptor)

    async def listunspent(self, minconf: int = 1, maxconf: int = 9999999, addresses: list[str] | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [minconf, maxconf]
        if addresses is not None:
            params.append(addresses)
        return await self._call("listunspent", *params, wallet_scoped=True)

    async def listreceivedbyaddress(self, minconf: int = 1, include_empty: bool = False, include_watchonly: bool = True) -> list[dict[str, Any]]:
        return await self._call(
            "listreceivedbyaddress",
            minconf,
            include_empty,
            include_watchonly,
            wallet_scoped=True,
        )

    async def walletcreatefundedpsbt(
        self,
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._call(
            "walletcreatefundedpsbt",
            inputs,
            outputs,
            0,
            options or {},
            wallet_scoped=True,
        )

    async def walletprocesspsbt(self, psbt: str, sign: bool = True) -> dict[str, Any]:
        return await self._call("walletprocesspsbt", psbt, sign, wallet_scoped=True)

    async def finalizepsbt(self, psbt: str) -> dict[str, Any]:
        return await self._call("finalizepsbt", psbt)

    async def sendrawtransaction(self, hexstring: str) -> str:
        return await self._call("sendrawtransaction", hexstring)

    async def estimatesmartfee(self, conf_target: int) -> dict[str, Any]:
        return await self._call("estimatesmartfee", conf_target)

    async def getblockcount(self) -> int:
        return await self._call("getblockcount")

    async def gettransaction(self, txid: str, include_watchonly: bool = True) -> dict[str, Any]:
        return await self._call("gettransaction", txid, include_watchonly, wallet_scoped=True)

    async def decodepsbt(self, psbt: str) -> dict[str, Any]:
        return await self._call("decodepsbt", psbt)

def get_bitcoin_rpc(settings: Settings) -> BitcoinRPCClient:
    return BitcoinRPCClient(settings)
