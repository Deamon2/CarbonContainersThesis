import math

def clamp_value(value, low, high):
    return max(low, min(high, value))

def smooth_step(value):
    value = clamp_value(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)

def triangle_pulse(value):
    value = clamp_value(value, 0.0, 1.0)
    return 1.0 - abs(2.0 * value - 1.0)

def wave(time_value, period, amplitude, phase=0.0):
    return amplitude * math.sin(math.tau * time_value / period + phase)

def zero_mean_noise(time_value, components):
    return sum(wave(time_value, period, amplitude, phase) for period, amplitude, phase in components)

def interpolate_curve(points, position):
    if position <= 0.0:
        return points[0]
    last_index = len(points) - 1
    if position >= last_index:
        return points[-1]
    left_index = int(math.floor(position))
    right_index = left_index + 1
    fraction = position - left_index
    return points[left_index] + (points[right_index] - points[left_index]) * fraction


MAX_RPS = 14.0
RUN_TIME = 1800


class ConstantLoadShape:
    target_rps = 5

    def tick(self, run_time):
        return self.target_rps


class SteadyLoadShape:
    base_rps = MAX_RPS * 0.7
    min_rps = base_rps * 0.95
    max_rps = base_rps * 1.05

    def tick(self, t):
        if t >= RUN_TIME:
            return None
        
        noise = zero_mean_noise(
            t,
            [
                (360.0, 0.045, 0.2),
                (127.0, 0.020, 1.1),
                (41.0, 0.010, 2.3),
            ],
        )
        rps = clamp_value(self.base_rps + noise, self.min_rps, self.max_rps)
        return rps

class FluctuationLoadShape:
    base_rps = MAX_RPS * 0.7
    min_rps = base_rps * 0.8
    max_rps = base_rps * 1.2

    burst_windows = [
        (180, 24, 0.45),
        (480, 22, 0.50),
        (840, 28, 0.55),
        (1200, 24, 0.50),
        (1560, 22, 0.45),
    ]

    def tick(self, t):
        if t >= RUN_TIME:
            return None

        oscillation = zero_mean_noise(
            t,
            [
                (260.0, 0.34, 0.6),
                (83.0, 0.16, 1.7),
                (29.0, 0.08, 0.9),
            ],
        )

        burst = 0.0
        for start, duration, amplitude in self.burst_windows:
            if start <= t < start + duration:
                burst += amplitude * triangle_pulse((t - start) / duration)

        rps = clamp_value(
            self.base_rps + oscillation + burst,
            self.min_rps,
            self.max_rps,
        )

        return rps


class SpikeLoadShape:
    baseline_rps = MAX_RPS * 0.5
    baseline_min_rps = baseline_rps * 0.9
    baseline_max_rps = baseline_rps * 1.1

    # start, rise, hold, fall, peak_rps
    spikes = [
        (180, 20, 50, 20, MAX_RPS * 0.95),
        (600, 20, 50, 20, MAX_RPS * 0.90),
        (1020, 20, 50, 20, MAX_RPS),
        (1440, 20, 50, 20, MAX_RPS * 0.92),
    ]

    def tick(self, t):
        if t >= RUN_TIME:
            return None
        baseline = self.baseline_rps + zero_mean_noise(
            t,
            [
                (330.0, 0.05, 0.4),
                (71.0, 0.02, 1.2),
            ],
        )
        baseline = clamp_value(baseline, self.baseline_min_rps, self.baseline_max_rps)
        rps = baseline
        for start, rise, hold, fall, peak_rps in self.spikes:
            end_rise = start + rise
            end_hold = end_rise + hold
            end_spike = end_hold + fall
            if start <= t < end_rise:
                progress = (t - start) / rise
                spike_rps = baseline + smooth_step(progress) * (peak_rps - baseline)
                rps = max(rps, spike_rps)
                break
            if end_rise <= t < end_hold:
                rps = max(rps, peak_rps)
                break
            if end_hold <= t < end_spike:
                progress = (t - end_hold) / fall
                spike_rps = peak_rps - smooth_step(progress) * (peak_rps - baseline)
                rps = max(rps, spike_rps)
                break
        rps = clamp_value(rps, 0.5, MAX_RPS)
        return rps
