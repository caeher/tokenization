from __future__ import annotations

import base64
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import json
import logging
from urllib import error, request


logger = logging.getLogger(__name__)
_SATOSHIS_PER_BTC = Decimal("100000000")


class BitcoinRPCError(RuntimeError):
    pass


@dataclass(frozen=True)
class FundingObservation:
    txid: str
    total_amount_sat: int


class BitcoinRPCClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        url: str | None = None,
        username: str,
        password: str | None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._rpc_url = url or f"http://{host}:{port}/"
        self._rpc_user = username
        self._rpc_password = password
        self._timeout_seconds = timeout_seconds

    def scan_address(self, address: str) -> FundingObservation | None:
        if not self._rpc_password:
            return None

        try:
            result = self._rpc_call("scantxoutset", ["start", [f"addr({address})"]])
        except Exception:
            logger.exception("Escrow funding scan failed for %s", address)
            return None

        unspents = result.get("unspents") or []
        if not unspents:
            return None

        total_amount_sat = sum(_btc_to_sats(unspent.get("amount", "0")) for unspent in unspents)
        if total_amount_sat <= 0:
            return None

        txid = str(unspents[0].get("txid") or "").lower()
        if len(txid) != 64:
            return None

        return FundingObservation(txid=txid, total_amount_sat=total_amount_sat)

    def _rpc_call(self, method: str, params: list[object]) -> dict[str, object]:
        payload = json.dumps(
            {
                "jsonrpc": "1.0",
                "id": "marketplace-escrow",
                "method": method,
                "params": params,
            }
        ).encode("utf-8")

        http_request = request.Request(
            self._rpc_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        credentials = base64.b64encode(
            f"{self._rpc_user}:{self._rpc_password}".encode("utf-8")
        ).decode("ascii")
        http_request.add_header("Authorization", f"Basic {credentials}")

        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise BitcoinRPCError("bitcoin_rpc_unavailable") from exc

        rpc_error = body.get("error")
        if rpc_error:
            raise BitcoinRPCError(str(rpc_error))

        result = body.get("result")
        if not isinstance(result, dict):
            raise BitcoinRPCError("bitcoin_rpc_invalid_result")

        return result


def _btc_to_sats(value: object) -> int:
    sats = (Decimal(str(value)) * _SATOSHIS_PER_BTC).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return int(sats)
