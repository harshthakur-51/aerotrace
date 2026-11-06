# Bounded airborne update cost

The read-only adapter processed a 1,200-poll fixture derived from the native
generator-plus-pump record. The fixture keeps the native prefix through the
active window and extends the final active values with advancing timestamps.
The continued interval is synthetic. Both runs use the same public source and
fixture construction.

| Implementation | Mean update | 95th percentile | Maximum |
|---|---:|---:|---:|
| Before airborne context reuse | 258.7 ms | 490.2 ms | 638.7 ms |
| After airborne context reuse | 41.7 ms | 80.1 ms | 112.1 ms |

Milliseconds are shown as ms. Timing covers the adapter's local update and
snapshot copy. Simulator property polling, network delivery and browser rendering
are outside that measurement. The baseline ran while the simulator was active.
The second measurement ran with the simulator paused and included concurrent
verification work. These are host observations under different background loads.

The new session validates each full airborne poll, retains its public context and
reuses the shared selected-system detector on the projected prefix. It avoids
rebuilding the full airborne context and replay digest each time. Offline model,
thresholds, observation contracts and scoring sources are the same sealed inputs.
Both adapters preserved the paired ambiguity and rejected the 1,201st update
explicitly. The optimized adapter reproduced the evidence and context of all 276
sealed native polls when their exact streams were fed through it.

[Baseline measurements](../pressure-v2-load-20261106-01/measurements.json) ·
[Optimized measurements](measurements.json) · [Exact-stream parity](prospective-parity.json)
