"""Apply router-specific accounting policy to a normalized record."""

from ipaddress import IPv4Address

from .contracts import ClassifiedFlow, Direction, FlowPolicy, FlowRejected, NormalizedFlow, RejectionReason


def classify_flow(flow: NormalizedFlow, policy: FlowPolicy) -> ClassifiedFlow:
    """Classify IPv4 LAN↔WAN traffic; reject ambiguous or excluded records.

    Downloads use translated destination when present, with direct destination
    fallback for routed, non-NAT IPv4. Missing translation to a public address is
    rejected instead of guessing a client from ports or the current DHCP lease.
    """
    if flow.input_interface in policy.lan_interfaces and flow.output_interface in policy.wan_interfaces:
        direction = Direction.UPLOAD
        device, remote = flow.source, flow.destination
    elif flow.input_interface in policy.wan_interfaces and flow.output_interface in policy.lan_interfaces:
        direction = Direction.DOWNLOAD
        device = flow.post_nat_destination or flow.destination
        remote = flow.source
        if not any(device in network for network in policy.lan_networks):
            raise FlowRejected(RejectionReason.MISSING_DEVICE_ADDRESS)
    else:
        raise FlowRejected(RejectionReason.UNCLASSIFIED_INTERFACE)

    if not any(device in network for network in policy.lan_networks):
        raise FlowRejected(RejectionReason.DEVICE_OUTSIDE_LAN)
    if remote.is_multicast or remote.is_unspecified or remote == IPv4Address("255.255.255.255"):
        raise FlowRejected(RejectionReason.EXCLUDED_REMOTE)
    if any(remote in network for network in (*policy.lan_networks, *policy.excluded_remote_networks)):
        raise FlowRejected(RejectionReason.EXCLUDED_REMOTE)
    return ClassifiedFlow(policy.router_id, direction, device, remote, flow)
