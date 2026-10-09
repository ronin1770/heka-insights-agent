"""
We need to add this to our Agent
This information is necessary for improving diagnostics for our intelligence layer

Sample Output:

{
  "timestamp": "2026-10-09T10:30:00Z",
  "tcp": {
    "established": 145,
    "listen": 8,
    "time_wait": 320,
    "close_wait": 3,
    "syn_sent": 2,
    "syn_recv": 5
  },
  "process_limits": {
    "pid": 1421,
    "max_open_files": {
      "soft": 1024,
      "hard": 1048576
    },
    "max_processes": {
      "soft": 15421,
      "hard": 15421
    }
  },
  "kernel": {
    "processes_created_total": 152834,
    "context_switches_total": 98472301,
    "running_tasks": 3,
    "blocked_tasks": 1
  },
  "memory": {
    "mem_available_kb": 1258291,
    "dirty_kb": 8192,
    "writeback_kb": 1024
  }
}

SAMPLE CODE: is below
TODO: make it compatible with our heka agent application
ensure it is not re-doing the work of src/collectors/cpu.py or disk.py or memory.py

"""

#!/usr/bin/env python3
"""Read targeted Linux /proc files without external dependencies."""
import json
import os
import socket
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

TCP_STATES = {'01': 'established', '02': 'syn_sent', '03': 'syn_recv', '04': 'fin_wait1',
              '05': 'fin_wait2', '06': 'time_wait', '07': 'close', '08': 'close_wait',
              '09': 'last_ack', '0A': 'listen', '0B': 'closing'}


def tcp_states():
    counts = Counter()
    for name in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            with open(name, encoding='utf-8') as f:
                next(f)
                for line in f:
                    fields = line.split()
                    if len(fields) > 3:
                        counts[TCP_STATES.get(fields[3], fields[3])] += 1
        except (OSError, StopIteration):
            pass
    return dict(counts)


def process_limits(pid):
    result = {}
    try:
        for line in Path(f'/proc/{pid}/limits').read_text().splitlines()[1:]:
            if line.startswith('Max open files'):
                values = line[len('Max open files'):].split()
                result['max_open_files'] = {'soft': values[0], 'hard': values[1]}
            elif line.startswith('Max processes'):
                values = line[len('Max processes'):].split()
                result['max_processes'] = {'soft': values[0], 'hard': values[1]}
    except OSError:
        pass
    return {'pid': pid, **result}#!/usr/bin/env python3
"""Read targeted Linux /proc files without external dependencies."""
import json
import os
import socket
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

TCP_STATES = {'01': 'established', '02': 'syn_sent', '03': 'syn_recv', '04': 'fin_wait1',
              '05': 'fin_wait2', '06': 'time_wait', '07': 'close', '08': 'close_wait',
              '09': 'last_ack', '0A': 'listen', '0B': 'closing'}


def tcp_states():
    counts = Counter()
    for name in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            with open(name, encoding='utf-8') as f:
                next(f)
                for line in f:
                    fields = line.split()
                    if len(fields) > 3:
                        counts[TCP_STATES.get(fields[3], fields[3])] += 1
        except (OSError, StopIteration):
            pass
    return dict(counts)


def process_limits(pid):
    result = {}
    try:
        for line in Path(f'/proc/{pid}/limits').read_text().splitlines()[1:]:
            if line.startswith('Max open files'):
                values = line[len('Max open files'):].split()
                result['max_open_files'] = {'soft': values[0], 'hard': values[1]}
            elif line.startswith('Max processes'):
                values = line[len('Max processes'):].split()
                result['max_processes'] = {'soft': values[0], 'hard': values[1]}
    except OSError:
        pass
    return {'pid': pid, **result}


def kernel_stats():
    keys = {'processes': 'processes_created_total', 'ctxt': 'context_switches_total',
            'procs_running': 'running_tasks', 'procs_blocked': 'blocked_tasks'}
    result = {}
    for line in Path('/proc/stat').read_text().splitlines():
        parts = line.split()
        if parts and parts[0] in keys:
            result[keys[parts[0]]] = int(parts[1])
    return result


def memory_stats():
    keys = {'MemAvailable': 'mem_available_kb', 'Dirty': 'dirty_kb', 'Writeback': 'writeback_kb'}
    result = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, _, rest = line.partition(':')
        if key in keys:
            result[keys[key]] = int(rest.split()[0])
    return result


def main():
    print(json.dumps({
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'tcp': tcp_states(),
        'process_limits': process_limits(os.getpid()),
        'kernel': kernel_stats(),
        'memory': memory_stats(),
    }, indent=2))


if __name__ == '__main__':
    main()


def kernel_stats():
    keys = {'processes': 'processes_created_total', 'ctxt': 'context_switches_total',
            'procs_running': 'running_tasks', 'procs_blocked': 'blocked_tasks'}
    result = {}
    for line in Path('/proc/stat').read_text().splitlines():
        parts = line.split()
        if parts and parts[0] in keys:
            result[keys[parts[0]]] = int(parts[1])
    return result


def memory_stats():
    keys = {'MemAvailable': 'mem_available_kb', 'Dirty': 'dirty_kb', 'Writeback': 'writeback_kb'}
    result = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, _, rest = line.partition(':')
        if key in keys:
            result[keys[key]] = int(rest.split()[0])
    return result


def main():
    print(json.dumps({
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'tcp': tcp_states(),
        'process_limits': process_limits(os.getpid()),
        'kernel': kernel_stats(),
        'memory': memory_stats(),
    }, indent=2))


if __name__ == '__main__':
    main()