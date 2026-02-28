# Shared Memory Communication Library - Development Instructions

## Project Overview

Build a high-performance, shared memory-based inter-process communication (IPC) library for Python that mimics the API and functionality of ZMQ/TCP but eliminates network overhead entirely. The library is designed specifically for robotics applications requiring ultra-low latency communication between processes on the same machine.

## Core Goals

1. **Zero-Copy Performance**: Use shared memory to avoid serialization overhead where possible
2. **Familiar API**: Provide ZMQ-like API patterns for easy adoption
3. **Cross-Platform**: Work on Linux (primary), Windows, and macOS
4. **Low Latency**: Optimize for microsecond-level latency, targeting <10μs for small messages
5. **High Throughput**: Support thousands of messages per second
6. **Reliability**: Handle edge cases, provide error recovery, and prevent data corruption

## Required Communication Patterns

### 1. Publish-Subscribe (PUB/SUB)
- One or more publishers send messages
- Multiple subscribers receive all messages
- Non-blocking sends
- Subscribers miss messages if they don't poll fast enough (no queuing by default)

### 2. Request-Reply (REQ/REP)
- Synchronous request-response pattern
- Client sends request, waits for reply
- Server receives request, sends reply
- Support timeouts

### 3. Push-Pull (Pipeline)
- Load balancing between workers
- Messages distributed round-robin to available consumers

## API Design Principles

### Simplicity First
- Use classes only when they provide clear benefits (they do here for state management)
- Keep the public API minimal and intuitive
- Method names should be self-documenting
- Use sensible defaults, require minimal configuration

### ZMQ-Compatible API Example
```python
# Publisher
pub = Publisher(name="robot_commands")
pub.send({"cmd": "move", "pos": [1.0, 2.0, 3.0]})

# Subscriber
sub = Subscriber(name="robot_commands")
msg = sub.recv(timeout=100)  # ms

# Request-Reply
server = Replier(name="control_service")
req = server.recv()
server.send({"status": "ok"})

client = Requester(name="control_service")
client.send({"query": "status"})
response = client.recv(timeout=1000)
```

## Architecture & Design

### Core Components

#### 1. Shared Memory Manager
- Allocate/deallocate shared memory segments
- Handle platform-specific differences (Linux: `/dev/shm`, Windows: file mapping)
- Reference counting for cleanup
- Support named segments for discovery

#### 2. Circular Buffer (Ring Buffer)
- Lock-free single-producer, single-consumer when possible
- Multi-producer/multi-consumer with minimal locking
- Use atomic operations where available (via `multiprocessing.Value`)
- Head/tail pointers for tracking read/write positions
- Wrap-around handling

#### 3. Message Serialization
- Default: Use `pickle` for Python objects (simple, compatible)
- Optional: Support `msgpack` for better performance
- Optional: Raw bytes mode for zero-copy (NumPy arrays)
- Message format: `[size:8bytes][data:variable]`

#### 4. Synchronization Primitives
- Use `multiprocessing.Lock` for critical sections
- Use `multiprocessing.Semaphore` for signaling
- Minimize lock contention - design for lock-free where possible
- Event-based notification for blocking receives

#### 5. Discovery/Registry
- Simple file-based or shared memory registry
- Maps names to shared memory segment identifiers
- Handle cleanup of stale entries

### Memory Layout Design

```
Shared Memory Segment:
[0-7]       Magic number (validation)
[8-15]      Version
[16-23]     Head pointer (write index)
[24-31]     Tail pointer (read index)
[32-39]     Lock/semaphore status
[40-47]     Message count
[48-55]     Dropped message count
[56-127]    Reserved for metadata
[128+]      Circular buffer data
```

### State Management

Each socket type (Publisher, Subscriber, etc.) should:
- Maintain connection to shared memory segment
- Track local state (sequence numbers, statistics)
- Handle cleanup on destruction (`__del__` or context manager)
- Provide statistics (messages sent/received, drops, errors)

## Implementation Guidelines

### Code Style

1. **Minimize class usage where functions suffice**
   - But DO use classes for socket types (Publisher, Subscriber, etc.)
   - They encapsulate state and cleanup logic naturally

2. **Keep functions focused and small**
   - Each function should do one thing well
   - Aim for <50 lines per function
   - Extract complex logic into helper functions

3. **Explicit over implicit**
   - No magic behavior
   - Clear error messages
   - Validate inputs early

4. **Performance-critical sections**
   - Avoid allocations in hot paths
   - Pre-allocate buffers
   - Use `memoryview` for zero-copy slicing
   - Profile before optimizing

### Error Handling

- Use exceptions for exceptional conditions
- Provide specific exception types:
  - `SHMConnectionError`: Can't connect to shared memory
  - `SHMTimeoutError`: Operation timed out
  - `SHMBufferFullError`: Can't write, buffer full
  - `SHMSerializationError`: Failed to serialize/deserialize
- Always include context in error messages
- Log at appropriate levels (debug, info, warning, error)

### Logging

```python
import logging
logger = logging.getLogger("shmcomm")

# Use throughout the library
logger.debug("Message received: size=%d", msg_size)
logger.warning("Buffer 90%% full, drops likely")
logger.error("Failed to allocate shared memory: %s", e)
```

### Cross-Platform Compatibility

#### Linux (Primary Platform)
- Use `multiprocessing.shared_memory.SharedMemory`
- Leverage `/dev/shm` for optimal performance
- Support POSIX semaphores if needed

#### Windows
- Use `multiprocessing.shared_memory.SharedMemory` (works on Windows via named memory-mapped files)
- Be aware: Windows shared memory is slower than Linux
- Test thoroughly on Windows

#### macOS
- Similar to Linux but with smaller default shared memory limits
- Document how to increase limits: `kern.sysv.shmmax`, `kern.sysv.shmall`

### Performance Optimization

1. **Minimize System Calls**
   - Batch operations where possible
   - Use non-blocking I/O

2. **Cache Locality**
   - Keep frequently accessed data together
   - Align data structures to cache lines (64 bytes)

3. **Lock-Free Algorithms**
   - Single producer/single consumer: lockless ring buffer
   - Use atomic operations: `multiprocessing.Value` with ctypes

4. **Zero-Copy Paths**
   - Support direct NumPy array sharing
   - Use `memoryview` for buffer access
   - Avoid unnecessary copies

## Module Structure

```
shm_comm_lib/
├── __init__.py          # Public API exports
├── core.py              # Shared memory management
├── buffer.py            # Circular buffer implementation
├── serialize.py         # Serialization backends
├── patterns/
│   ├── __init__.py
│   ├── pubsub.py       # Publisher/Subscriber
│   ├── reqrep.py       # Requester/Replier
│   └── pipeline.py     # Push/Pull
├── sync.py              # Synchronization primitives
├── registry.py          # Name-to-segment mapping
├── exceptions.py        # Custom exceptions
└── utils.py             # Helpers and utilities

tests/
├── test_core.py
├── test_buffer.py
├── test_pubsub.py
├── test_reqrep.py
├── test_performance.py
└── test_multiprocess.py

examples/
├── simple_pubsub.py
├── reqrep_example.py
├── numpy_sharing.py
└── benchmark.py
```

## Testing Strategy

### Unit Tests
- Test each component in isolation
- Mock shared memory for deterministic tests
- Test boundary conditions (full buffer, empty buffer, etc.)

### Integration Tests
- Multi-process tests using `multiprocessing.Process`
- Test all communication patterns
- Verify no memory leaks (use `tracemalloc`)

### Performance Tests
- Measure latency (min, max, p50, p99)
- Measure throughput (messages/second)
- Test with varying message sizes (10B to 1MB)
- Compare against ZMQ/TCP baseline

### Stress Tests
- Run for extended periods (hours)
- Test with many publishers/subscribers
- Induce failures (kill processes, fill buffers)
- Verify recovery and cleanup

## Documentation Requirements

### Code Documentation
- Docstrings for all public classes and functions
- Include parameter types and return types (use type hints)
- Provide usage examples in docstrings
- Document performance characteristics

### User Documentation
- README with quick start guide
- API reference
- Performance tuning guide
- Troubleshooting section
- Examples for each pattern

### Example Format
```python
def send(self, data, timeout=None):
    """
    Send a message through the publisher.
    
    Args:
        data: Any Python object (will be pickled)
        timeout (float, optional): Max seconds to wait if buffer full.
                                    None = non-blocking (default)
    
    Returns:
        bool: True if sent successfully, False if buffer full
    
    Raises:
        SHMSerializationError: If data cannot be serialized
        SHMConnectionError: If shared memory is disconnected
    
    Example:
        >>> pub = Publisher("sensors")
        >>> pub.send({"temp": 25.5, "pressure": 1013})
        True
    """
```

## Performance Targets

- **Latency**: <10μs for small messages (<1KB) on Linux
- **Throughput**: >100K messages/second for small messages
- **Memory**: <10MB overhead for typical use cases
- **Scalability**: Support 10+ publishers/subscribers per channel
- **Message Size**: Support messages up to 10MB

## Development Phases

### Phase 1: Foundation (MVP)
1. Basic shared memory allocation and cleanup
2. Simple circular buffer (single producer/consumer)
3. Pickle-based serialization
4. Publisher/Subscriber pattern only
5. Linux support only
6. Basic error handling

### Phase 2: Feature Complete
1. Request-Reply pattern
2. Push-Pull pattern
3. Multi-producer/multi-consumer buffers
4. Timeouts and blocking receives
5. Windows and macOS support
6. Comprehensive error handling and logging

### Phase 3: Optimization
1. Lock-free algorithms where possible
2. Zero-copy NumPy array support
3. msgpack serialization option
4. Performance benchmarking and tuning
5. Memory pooling/reuse

### Phase 4: Production Ready
1. Comprehensive test coverage (>90%)
2. Complete documentation
3. Example applications
4. Performance comparison with ZMQ
5. Installation via pip (setup.py)
6. CI/CD pipeline

## Key Considerations

### Memory Management
- Always clean up shared memory on exit
- Use `atexit` handlers and context managers
- Handle crashes gracefully (orphaned segments)
- Implement timeout-based cleanup for stale segments

### Thread Safety
- Document which methods are thread-safe
- Use locks only where necessary
- Consider thread-local storage for per-thread state

### Process Safety
- Use process-safe synchronization primitives
- Handle process crashes (partial writes, locked sections)
- Implement heartbeat/keepalive mechanism

### Debugging Support
- Provide utilities to inspect shared memory state
- Include debug mode with verbose logging
- Create diagnostic tools (list segments, show stats)

## Common Pitfalls to Avoid

1. **Over-engineering**: Start simple, add complexity only when needed
2. **Excessive locking**: Profile first, optimize contention points
3. **Large messages**: Consider chunking for messages >1MB
4. **Resource leaks**: Always test cleanup paths
5. **Platform assumptions**: Test on all target platforms
6. **Poor error messages**: Include context and recovery suggestions

## Success Criteria

The library is successful when:
- [ ] API is intuitive and requires <10 lines for basic usage
- [ ] Performance beats ZMQ/TCP by 10x for local IPC
- [ ] No memory leaks after 1M messages
- [ ] Works reliably on Linux, Windows, macOS
- [ ] Test coverage >90%
- [ ] Documentation is clear and complete
- [ ] Examples cover all common use cases
- [ ] Can be installed via `pip install shm-comm-lib`