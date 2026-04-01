"""
This will be the main entry point
It will grab information about CPU / Memory / Disk IO / Network IO

Metrics must be compatible with OpenMetrics 1.0
Link: https://prometheus.io/docs/specs/om/open_metrics_spec/

Telemetry agent should be very light weight and should not cause a system overload

Should be able to be configured using a standard YAML input

collect core system metrics every 15–30 seconds
collect logs only from configured sources
transmit compressed batched payloads every 15–60 seconds

5s to 60s intervals are enough
1s polling is usually too aggressive unless there is a very specific reason

CPU: usually under 1% on average on an idle or normal server
Memory: ideally 20–80 MB RAM
Disk: very little local storage unless buffering is required
Network: compact payloads, batched sends, no noisy chatter
Startup time: near-instant
Process count: ideally a single process

"""