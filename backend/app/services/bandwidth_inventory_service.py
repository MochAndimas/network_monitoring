"""Synchronize a full successful RouterOS observation in the caller's transaction."""

from sqlalchemy.ext.asyncio import AsyncSession

from ..bandwidth.discovery import InventorySnapshot
from ..models.bandwidth import BandwidthClient, BandwidthInventoryState, BandwidthIPHistory
from ..repositories.bandwidth_inventory_repository import BandwidthInventoryRepository


async def sync_inventory(
    db: AsyncSession, snapshot: InventorySnapshot, *, max_observation_gap_seconds: int = 120
) -> bool:
    """Serialize per router; replay/stale snapshots are no-ops. Never commit.

    Consecutive observations within the gap budget form an inferred continuous
    interval. A missing/conflicting IP or long gap closes at the last observation
    plus one nanosecond, never at an invented release time. Failed API fetches
    must not be submitted as empty successful snapshots.
    """
    if type(max_observation_gap_seconds) is not int or max_observation_gap_seconds <= 0:
        raise ValueError("Observation gap must be positive seconds")
    # Current-value locking reads below refresh ORM rows. Preserve any pending
    # changes made by the enclosing transaction (for example a manual rename).
    await db.flush()
    repository = BandwidthInventoryRepository(db)
    await repository.lock_router(snapshot.router_id)
    state = await repository.state(snapshot.router_id)
    if state is not None and snapshot.observed_ns <= state.observed_ns:
        return False

    clients = await repository.clients_by_mac(snapshot.router_id, {item.mac for item in snapshot.clients})
    for item in snapshot.clients:
        client = clients.get(item.mac)
        if client is None:
            client = BandwidthClient(
                router_id=snapshot.router_id,
                mac_address=item.mac,
                first_seen_ns=snapshot.observed_ns,
                last_seen_ns=snapshot.observed_ns,
            )
            db.add(client)
            clients[item.mac] = client
        client.last_seen_ns = snapshot.observed_ns
        if item.hostname:
            client.hostname = item.hostname
    await db.flush()

    observations = {item.ip: item for item in snapshot.clients}
    continued: set[str] = set()
    for binding in await repository.active_bindings(snapshot.router_id):
        observation = observations.get(binding.ip_address)
        same_owner = observation is not None and clients[observation.mac].id == binding.client_id
        timely = snapshot.observed_ns - binding.last_observed_ns <= max_observation_gap_seconds * 10**9
        if observation is not None and same_owner and timely:
            binding.last_observed_ns = snapshot.observed_ns
            binding.source = observation.source
            continued.add(binding.ip_address)
        else:
            binding.active_slot = None
            binding.ended_ns = binding.last_observed_ns + 1
    # Release active uniqueness slots before inserting replacements.
    await db.flush()
    for item in snapshot.clients:
        if item.ip not in continued:
            db.add(
                BandwidthIPHistory(
                    router_id=snapshot.router_id,
                    client_id=clients[item.mac].id,
                    ip_address=item.ip,
                    source=item.source,
                    first_observed_ns=snapshot.observed_ns,
                    last_observed_ns=snapshot.observed_ns,
                    active_slot=1,
                )
            )
    if state is None:
        state = BandwidthInventoryState(router_id=snapshot.router_id)
        db.add(state)
    state.observed_ns = snapshot.observed_ns
    state.client_count = len(snapshot.clients)
    state.ambiguous_ip_count = len(snapshot.ambiguous_ips)
    state.invalid_row_count = snapshot.invalid_rows
    await db.flush()
    return True
