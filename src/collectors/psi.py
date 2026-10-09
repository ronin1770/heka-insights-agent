"""
We need to add this to our Agent
This information is necessary for improving diagnostics for our intelligence layer

Sample Output:

# /proc/pressure/cpu
some avg10=12.50 avg60=8.30 avg300=4.20 total=184729301

# /proc/pressure/memory
some avg10=3.20 avg60=1.50 avg300=0.80 total=56290110
full avg10=0.50 avg60=0.20 avg300=0.10 total=8291030

# /proc/pressure/io
some avg10=8.40 avg60=5.20 avg300=2.10 total=92740182
full avg10=2.10 avg60=1.30 avg300=0.50 total=18291040

"""

#!/usr/bin/env python3
"""Read Linux pressure stall information (PSI), no dependencies."""
import json
from datetime import datetime, timezone
from pathlib import Path


def read_pressure(resource):
    path = Path('/proc/pressure') / resource
    try:
        result = {}
        for line in path.read_text().splitlines():
            kind, *fields = line.split()
            values = {}
            for field in fields:
                key, value = field.split('=', 1)
                values[key] = int(value) if key == 'total' else float(value)
            result[kind] = values
        return result
    except OSError:
        return None


def main():
    print(json.dumps({
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'pressure': {kind: read_pressure(kind) for kind in ('cpu', 'memory', 'io')},
    }, indent=2))


if __name__ == '__main__':
    main()