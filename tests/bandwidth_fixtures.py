"""Synthetic IPFIX records and sealed segments shared by bandwidth tests."""

import hashlib
import json
from uuid import uuid4

from backend.app.bandwidth.spool import SealedSegment

START = 1_800_000_000_000_000_000


def record(**changes):
    value = {
        "type": "IPFIX",
        "sampler_address": "192.0.2.1",
        "src_addr": "192.168.1.31",
        "dst_addr": "142.251.10.95",
        "post_nat_src_addr": "67714e96",
        "post_nat_dst_addr": "8efb0a5f",
        "in_if": 13,
        "out_if": 10,
        "bytes": 4178,
        "packets": 11,
        "time_flow_start_ns": START,
        "time_flow_end_ns": START + 10,
        "time_received_ns": START + 100,
    }
    value.update(changes)
    return json.dumps(value).encode() + b"\n"


def sealed(directory, payload, identity=None):
    digest = hashlib.sha256(payload).hexdigest()
    path = directory / f"{identity or uuid4().hex}.{digest}.ready"
    path.write_bytes(payload)
    return SealedSegment.from_path(path)
