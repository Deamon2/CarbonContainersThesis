import asyncio
import logging
import re
import subprocess
import time

import httpx
from temporalio import activity

from business_process import config
from business_process.metrics_server import metrics

logger = logging.getLogger("request")

SERVICE_PORT = config.SERVICE_PORT
REQUEST_DEADLINE_S = 3

name_to_ip = {}
http_client = None
http_client_lock = None


async def get_http_client():
    global http_client, http_client_lock

    if http_client is not None:
        return http_client

    if http_client_lock is None:
        http_client_lock = asyncio.Lock()

    async with http_client_lock:
        if http_client is None:
            http_client = httpx.AsyncClient()
        return http_client

def get_container_ip(container_name: str):

    if container_name in name_to_ip:
        return name_to_ip[container_name]

    result = subprocess.run(
        ["lxc-info", "-n", container_name],
        capture_output=True,
        text=True,
        check=True,
    )

    output = result.stdout
    match = re.search(r"IP:\s+(\d+\.\d+\.\d+\.\d+)", output)

    if not match:
        raise RuntimeError(f"Keine IP-Adresse für Container '{container_name}' gefunden")

    ip = match.group(1)
    name_to_ip[container_name] = ip
    return ip

@activity.defn
async def request(container_name: str):
    try:
        target_ip = get_container_ip(container_name)
        url = f"http://{target_ip}:{SERVICE_PORT}/compute"
        deadline_ms = int((time.monotonic() + REQUEST_DEADLINE_S) * 1000)

        logger.info("Sending request to worker %s at %s with deadline_ms=%s", container_name, url, deadline_ms)

        client = await get_http_client()
        response = await client.get(
            url,
            params={"deadline_ms": deadline_ms},
            timeout=REQUEST_DEADLINE_S * 1.5,
        )
        response.raise_for_status()

        logger.info("Received response from worker %s with status %d", container_name, response.status_code)

        result = response.json()
        result["status"] = "ok"

        metrics.update_total_requests(container_name=container_name)
        metrics.update_successful_requests(container_name=container_name, mode=result.get("mode", "unknown"))
        metrics.update_computation_time(
            container_name=container_name,
            mode=result.get("mode", "unknown"),
            duration=result.get("computation_time_ms", 0),
        )
        
        return result

    except httpx.HTTPStatusError as error:

        metrics.update_total_requests(container_name=container_name)
        metrics.update_failed_requests(container_name=container_name)

        if error.response.status_code == 503:
            return { "status": "error", "error": f"{error.response.status_code} {error.response.text}" }

        return { "status": "error", "error": f"HTTP {error.response.status_code}" }
    except httpx.TimeoutException as error:

        metrics.update_total_requests(container_name=container_name)
        metrics.update_failed_requests(container_name=container_name)

        return { "status": "error", "error": "ReadTimeout" }
    except Exception as error:

        metrics.update_total_requests(container_name=container_name)
        metrics.update_failed_requests(container_name=container_name)

        return { "status": "error", "error": type(error).__name__ }