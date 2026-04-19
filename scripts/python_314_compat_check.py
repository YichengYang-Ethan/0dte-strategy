"""Python 3.14 compatibility spike before writing recorder.

Theta Terminal examples tested on 3.11. Verify required packages work on 3.14:
  - websockets (async client for WS)
  - httpx (async HTTP client)
  - pyarrow (parquet writer)
  - zoneinfo (stdlib, ET→UTC normalization)

Run before any recorder development.
Usage: python scripts/python_314_compat_check.py
"""
from __future__ import annotations
import sys
import asyncio
from datetime import datetime, timezone


def check_stdlib():
    print(f"Python: {sys.version}")
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    now_et = datetime.now(et)
    print(f"zoneinfo ET: {now_et.isoformat()}")
    print(f"zoneinfo UTC: {now_et.astimezone(timezone.utc).isoformat()}")


def check_pyarrow():
    import pyarrow as pa
    import pyarrow.parquet as pq
    print(f"pyarrow: {pa.__version__}")
    schema = pa.schema([
        pa.field("ts", pa.timestamp("ms", tz="UTC")),
        pa.field("price", pa.float64()),
    ])
    rows = [{"ts": datetime.now(timezone.utc), "price": 100.5}]
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, "/tmp/_compat_test.parquet", compression="zstd")
    print(f"pyarrow write OK ({len(rows)} rows)")
    pq.read_table("/tmp/_compat_test.parquet")
    print("pyarrow read OK")


async def check_websockets():
    import websockets
    print(f"websockets: {websockets.__version__}")
    # Don't actually connect to Theta; just verify import + basic API
    assert hasattr(websockets, "connect")
    print("websockets.connect available")


async def check_httpx():
    import httpx
    print(f"httpx: {httpx.__version__}")
    # Don't hit external; just verify async client
    async with httpx.AsyncClient(timeout=1.0) as c:
        assert c is not None
    print("httpx.AsyncClient OK")


async def main():
    print("=" * 60)
    print("Python 3.14 compatibility check")
    print("=" * 60)
    check_stdlib()
    print()
    try:
        check_pyarrow()
    except Exception as e:
        print(f"FAIL pyarrow: {e}")
    print()
    try:
        await check_websockets()
    except Exception as e:
        print(f"FAIL websockets: {e}")
    print()
    try:
        await check_httpx()
    except Exception as e:
        print(f"FAIL httpx: {e}")
    print()
    print("=" * 60)
    print("If all OK: proceed with recorder.")
    print("If any FAIL: pin pkg version or downgrade to Python 3.11.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
