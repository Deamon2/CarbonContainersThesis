import asyncio
import time
import httpx

URL = "http://10.0.3.190:8000/compute"
TIMEOUT = 3

RPS = 14
DURATION = 120


async def send_request(client: httpx.AsyncClient):
    start = time.monotonic()

    try:
        deadline_ms = int((start + TIMEOUT) * 1000)

        response = await client.get(
            URL,
            params={"deadline_ms": deadline_ms},
            timeout=TIMEOUT,
        )

        response.raise_for_status()

        return True, time.monotonic() - start, response.json().get("computation_time_ms", 0)

    except (httpx.TimeoutException, httpx.HTTPError):
        return False, time.monotonic() - start, 0


async def run_load(rps, duration):
    tasks = []

    limits = httpx.Limits(
        max_connections=max(100, int(rps * 2)),
        max_keepalive_connections=max(20, int(rps)),
    )

    async with httpx.AsyncClient(limits=limits) as client:
        interval = 1 / rps
        end = time.monotonic() + duration
        next_request = time.monotonic()

        while next_request < end:
            await asyncio.sleep(max(0, next_request - time.monotonic()))
            tasks.append(asyncio.create_task(send_request(client)))
            next_request += interval

        results = await asyncio.gather(*tasks)

    successful = [result for result in results if result[0]]
    failed = len(results) - len(successful)
    computation_times = [computation_time for _, _, computation_time in successful]

    actual_rps = len(results) / duration
    goodput = len(successful) / duration
    error_rate = failed / len(results) if results else 0.0
    mean_computation_ms = sum(computation_times) / len(computation_times) if computation_times else 0.0

    print(
        f"Target RPS: {rps}, "
        f"Actual RPS: {actual_rps:.1f}, "
        f"Success: {len(successful)}, "
        f"mean computation time: {mean_computation_ms:.2f}ms, "
        f"Timeouts: {failed}, "
        f"Error rate: {error_rate * 100:.2f}%, "
        f"Goodput: {goodput:.2f} req/s"
    )

    return


async def main():
    await run_load(RPS, DURATION)

asyncio.run(main())
# Target RPS: 14, Actual RPS: 14.0, Success: 840, mean computation time: 326.76ms, Timeouts: 0, Error rate: 0.00%, Goodput: 14.00 req/s
# Target RPS: 15, Actual RPS: 15.0, Success: 1689, mean computation time: 553.44ms, Timeouts: 111, Error rate: 6.17%, Goodput: 14.07 req/s