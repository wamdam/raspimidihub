"""Client input-FIFO sizing + overflow instrumentation.

The kernel queues events addressed to a user client in a per-client
input FIFO and silently DROPS new ones when it overflows (the reader
was too slow to drain); the next read() then returns -ENOSPC and
clears the whole pending queue. A dropped note-off is a stuck note at
the destination. The hub resizes the FIFO via the client-pool API
(ALSA seq has a hard kernel ceiling — SNDRV_SEQ_MAX_CLIENT_EVENTS =
2000 events, 10x the 200-event default) and makes the overflow
observable: read_event() counts -ENOSPC episodes (fifo_overflows) and
client_buffer_info() exposes the pool size / free space.
"""

import pytest

from raspimidihub import alsa_seq


def test_client_buffer_info_shape_test_mode():
    """In test mode the mock lib returns zeros — assert the method
    exists, takes no args, and returns the documented shape so the
    observatory contract can't silently regress."""
    seq = alsa_seq.AlsaSeq("buffer-test", default_ports=False)
    info = seq.client_buffer_info()
    assert isinstance(info, dict)
    assert set(info) == {"input_pool", "input_free", "event_lost",
                         "fifo_overflows"}
    for key in info:
        assert isinstance(info[key], int), key
    assert info["event_lost"] >= 0
    assert info["fifo_overflows"] == 0


def test_input_pool_size_uses_kernel_ceiling():
    # The kernel caps the input FIFO at SNDRV_SEQ_MAX_CLIENT_EVENTS =
    # 2000 events (default 200). We must use the ceiling — anything
    # lower keeps the overflow window open under loop stalls.
    assert alsa_seq.CLIENT_INPUT_POOL_SIZE >= 2000
    assert alsa_seq.ENOSPC == 28


@pytest.mark.alsa
def test_fifo_enlarged_on_real_alsa():
    """On real ALSA (Pi / snd-virmidi): the input FIFO actually grew to
    the configured size and the pool API round-trips."""
    if alsa_seq.snd_seq_set_client_pool is None:
        pytest.skip("alsa-lib lacks the client-pool API")
    seq = alsa_seq.AlsaSeq("buffer-test", default_ports=False)
    info = seq.client_buffer_info()
    # The SET_CLIENT_POOL ioctl applies the size (kernel rounds it to
    # cell count); it must be far above the 200-event default, or the
    # enlargement silently no-opped.
    assert info["input_pool"] >= 1999, f"FIFO not enlarged: {info}"
    assert info["input_free"] >= 0
    assert info["event_lost"] >= 0
