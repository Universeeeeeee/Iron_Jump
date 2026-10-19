"""Windows endpoint closure can surface at poll or recv; decoding faults remain faults."""
def poll_packet(connection,timeout=.2):
    try:
        if not connection.poll(timeout):return 'idle',None
        return 'packet',connection.recv()
    except (EOFError,OSError) as exc:
        return 'closed',dict(error_type=type(exc).__name__,detail=repr(exc))
