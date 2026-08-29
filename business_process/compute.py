"""
Setup && Start:
    pip install fastapi uvicorn numpy openfeature-sdk openfeature-provider-flagd
    FLAG_KEY=delivery-mode DEFAULT_MODE=high uvicorn compute:app --host 0.0.0.0 --port 8000
"""
import os
# 1 Thread pro berechnung
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import logging
import time
from threading import Semaphore

import numpy as np
import uvicorn
from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel

from openfeature import api
from openfeature.contrib.provider.flagd import FlagdProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("compute")

MAX_CONCURRENT_REQUESTS = 7
MAX_QUEUED_REQUESTS = 14
request_semaphore = Semaphore(MAX_CONCURRENT_REQUESTS)
admission_semaphore = Semaphore(MAX_CONCURRENT_REQUESTS + MAX_QUEUED_REQUESTS)

# Schätzung der Zeitverhältnisse für unterschiedlich komplexe Antworten 
# Target: low (10ms), medium (50ms), high (200ms)
# Targets: cont2 x 2, cont3 / 2
'''
COMPUTE_UNITS = {
    "low": 7,    # in Memory / Cache lookup
    "medium": 35,  # DB querys, API calls
    "high": 135, # Algorithmen + mehrerer DB queries / API calls (+ ML/DL model)
}
COMPUTE_UNITS = {
    "low": 4,
    "medium": 18,
    "high": 68,
}
'''
COMPUTE_UNITS = {
    "low": 14,
    "medium": 70,
    "high": 270,
}
COMPUTE_MAT = np.random.default_rng(42).random((512, 512)).astype(np.float32)

FLAGD_HOST = "10.0.3.1"
PORT = 8013

FLAG_KEY = os.getenv("FLAG_KEY", "").strip()
DEFAULT_MODE = os.getenv("DEFAULT_MODE", "high").strip()

if not FLAG_KEY:
    raise RuntimeError("FLAG_KEY must be set via the environment before starting the service.")


if DEFAULT_MODE not in COMPUTE_UNITS:
    logger.warning("DEFAULT_MODE='%s' is invalid. Falling back to 'high'.", DEFAULT_MODE)
    DEFAULT_MODE = "high"


def compute_unit():
    return float((COMPUTE_MAT @ COMPUTE_MAT)[0, 0])


def deadline_exceeded(deadline_ms: int | None):
    return deadline_ms is not None and int(time.monotonic() * 1000) > deadline_ms


def compute(units: int, deadline_ms: int | None):
    start = time.perf_counter()
    for _ in range(units):
        if deadline_exceeded(deadline_ms):
            raise HTTPException(status_code=503, detail="Deadline exceeded during processing")
        compute_unit()
    return (time.perf_counter() - start) * 1000 # ms


def init_flag_provider():
    provider = FlagdProvider(
        host=FLAGD_HOST,
        port=PORT,
        tls=False,
    )

    api.set_provider(provider)
    logger.info(
        "OpenFeature flagd provider configured (%s:%s); flag_key=%s default_mode=%s.",
        FLAGD_HOST,
        PORT,
        FLAG_KEY,
        DEFAULT_MODE,
    )

init_flag_provider()


app = FastAPI(title="Compute Microservice")


def resolve_mode():
    client = api.get_client("compute")
    try:
        flag_value = client.get_string_value(FLAG_KEY, DEFAULT_MODE)
    except Exception as exc:
        logger.warning("Flag evaluation failed, keeping mode '%s': %s", DEFAULT_MODE, exc)
        return DEFAULT_MODE

    if flag_value not in COMPUTE_UNITS:
        logger.warning("Invalid mode: '%s'. Keeping '%s'.", flag_value, DEFAULT_MODE)
        return DEFAULT_MODE

    return flag_value

class ResponseModel(BaseModel):
    mode: str
    compute_units_executed: int
    computation_time_ms: float

@app.get("/compute", response_model=ResponseModel)
def compute_endpoint(deadline_ms: int | None = None):
    if deadline_exceeded(deadline_ms):
        logger.info("request rejected before processing: deadline_ms=%s now_ms=%s", deadline_ms, int(time.monotonic() * 1000))
        raise HTTPException(status_code=503, detail="Deadline exceeded before processing")
    
    if not admission_semaphore.acquire(blocking=False):
        logger.info("request rejected: compute queue full")
        raise HTTPException(status_code=503, detail="Compute queue full")

    try:
        with request_semaphore:
            mode = resolve_mode()
            units = COMPUTE_UNITS[mode]

            elapsed_ms = compute(units, deadline_ms=deadline_ms)
            
            return ResponseModel(
                mode=mode,
                compute_units_executed=units,
                computation_time_ms=round(elapsed_ms, 2),
            )
    finally:
        admission_semaphore.release()


if __name__ == "__main__":
    uvicorn.run("compute:app", host="0.0.0.0", port=8000, log_level="info")
