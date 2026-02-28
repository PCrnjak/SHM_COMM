# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-02-28

### Added
- Initial release
- **PUB/SUB** pattern — broadcast to multiple independent subscribers with lock-free ring buffer
- **REQ/REP** pattern — synchronous request-reply service calls
- **PUSH/PULL** pattern — work-queue distribution across multiple workers
- Lock-free SPSC ring buffer for PUB/SUB (overwrite semantics, no blocking)
- File-lock protected MPMC ring buffer for PUSH/PULL (queued semantics)
- `pickle` serialization backend (default, zero external dependencies)
- `msgpack` serialization backend (optional, faster for simple types)
- Zero-copy raw bytes mode (`send_bytes` / `recv_bytes`) for NumPy arrays
- Context manager support for all socket types (`with Publisher(...) as pub`)
- `force_unlink` utility for cleaning up stale shared memory segments
- `list_segments` utility for inspecting active segments
- Cross-platform support: Linux, Windows, macOS
- Comprehensive test suite: 53 tests covering unit, integration, and performance
- Benchmark script with throughput and latency measurements
- Example scripts: `simple_pubsub.py`, `reqrep_example.py`, `benchmark.py`,
  `command_executor.py`, `command_sender.py`
- Documentation: API reference, performance tuning guide, troubleshooting

### Performance (Windows, Python 3.11)
- PUB/SUB latency: ~4µs p50, ~10µs p99
- PUB/SUB throughput: ~250–310k msg/s
- PUSH/PULL throughput: ~200k msg/s
