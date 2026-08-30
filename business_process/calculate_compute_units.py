import time

import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import numpy as np

COMPUTE_MAT = np.random.default_rng(42).random((512, 512)).astype(np.float32)

times = []
for _ in range(500):
    start = time.perf_counter()
    float((COMPUTE_MAT @ COMPUTE_MAT)[0, 0])
    int(time.monotonic() * 1000)
    times.append((time.perf_counter() - start) * 1000)

print(f"Per unit: {np.mean(times):.2f}ms +- {np.std(times):.2f}ms")

target_ms = {"low": 50, "medium": 100, "high": 200}
ms_per_unit = np.mean(times) 

COMPUTE_UNITS = {
    level: max(1, round(ms / ms_per_unit))
    for level, ms in target_ms.items()
}
print(COMPUTE_UNITS) 
# Per unit: 1.48ms +- 0.07ms
# {'low': 34, 'medium': 67, 'high': 135}