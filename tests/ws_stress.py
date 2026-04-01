"""
WebSocket concurrent connection stress test.
Tests how many simultaneous WS clients the backend can handle.

Run: python tests/ws_stress.py
"""
import asyncio
import json
import time
import websockets

WS_URL = "ws://127.0.0.1:8000/ws/vessels"
NUM_CLIENTS = 50          # concurrent WebSocket connections
DURATION_SECS = 30        # how long to hold connections open
RESULTS = []

async def single_client(client_id: int):
    messages_received = 0
    bytes_received = 0
    connect_time = None
    first_message_time = None
    errors = []

    try:
        t0 = time.perf_counter()
        async with websockets.connect(WS_URL, ping_interval=10) as ws:
            connect_time = time.perf_counter() - t0
            deadline = time.perf_counter() + DURATION_SECS
            while time.perf_counter() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    if first_message_time is None:
                        first_message_time = time.perf_counter() - t0
                    data = json.loads(raw)
                    messages_received += 1
                    bytes_received += len(raw)
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    errors.append(str(e))
                    break
    except Exception as e:
        errors.append(f"Connect failed: {e}")

    RESULTS.append({
        "client_id": client_id,
        "connect_ms": round((connect_time or 0) * 1000, 1),
        "first_msg_ms": round((first_message_time or 0) * 1000, 1),
        "messages": messages_received,
        "kb_received": round(bytes_received / 1024, 1),
        "errors": errors,
    })

async def main():
    print(f"Connecting {NUM_CLIENTS} WebSocket clients to {WS_URL}")
    print(f"Holding for {DURATION_SECS}s...\n")
    t_start = time.perf_counter()
    await asyncio.gather(*[single_client(i) for i in range(NUM_CLIENTS)])
    elapsed = time.perf_counter() - t_start

    # Summary
    connected = [r for r in RESULTS if r["messages"] > 0]
    failed    = [r for r in RESULTS if r["messages"] == 0]
    avg_connect = sum(r["connect_ms"] for r in connected) / max(len(connected), 1)
    avg_msgs    = sum(r["messages"] for r in connected) / max(len(connected), 1)
    total_kb    = sum(r["kb_received"] for r in RESULTS)

    print(f"{'='*50}")
    print(f"Total clients:      {NUM_CLIENTS}")
    print(f"Successful:         {len(connected)}")
    print(f"Failed:             {len(failed)}")
    print(f"Avg connect time:   {avg_connect:.1f} ms")
    print(f"Avg messages/conn:  {avg_msgs:.1f}")
    print(f"Total data rx:      {total_kb:.1f} KB")
    print(f"Test duration:      {elapsed:.1f}s")
    print(f"{'='*50}")

    if failed:
        print("\nFailed clients:")
        for r in failed[:5]:
            print(f"  Client {r['client_id']}: {r['errors']}")

if __name__ == "__main__":
    asyncio.run(main())
