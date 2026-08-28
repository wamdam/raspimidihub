"""parse_root_fs_mode — the Settings → Sys Info filesystem measurement.

The root fs is readonly in steady state (rosetup hardening); the hub
remounts it rw only for brief write windows. A failed remount-ro must
be visible in the UI, which needs an exact mountpoint match and an
exact option-token match (a ``/root`` entry or a substring like
``errors=remount-ro`` must not count as the root mode).
"""

from raspimidihub.api.system import parse_root_fs_mode

# A realistic appliance mount table (root ro, tmpfs on top, boot ro).
_APPLIANCE = """proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
tmpfs /run tmpfs rw,nosuid,nodev 0 0
/dev/mmcblk0p2 / ext4 ro,noatime 0 0
/dev/mmcblk0p1 /boot/firmware vfat rw,umask=0077 0 0
tmpfs /var/lib/raspimidihub tmpfs rw 0 0
"""

_DEV_MODE = """overlay / overlay rw,relatime 0 0
tmpfs /run tmpfs rw,nosuid 0 0
/dev/sda2 /boot ext4 rw,relatime 0 0
"""


def test_appliance_root_readonly():
    assert parse_root_fs_mode(_APPLIANCE) == "readonly"


def test_dev_root_readwrite():
    # The dev machine's root is a plain rw mount — same code path,
    # just a different flag.
    assert parse_root_fs_mode(_DEV_MODE) == "read/write"


def test_exact_mountpoint_no_root_collision():
    # A /root (or /boot) entry must never be mistaken for the root
    # fs; with no real / entry the answer is None, not /root's mode.
    table = "/dev/sda2 /root ext4 rw,relatime 0 0\n"
    assert parse_root_fs_mode(table) is None
    # …and when a real / entry is present, only it counts.
    table = ("/dev/sda2 /root ext4 rw,relatime 0 0\n"
             "/dev/sda1 / ext4 ro,noatime 0 0\n")
    assert parse_root_fs_mode(table) == "readonly"


def test_option_token_not_substring():
    # `ro,noatime,errors=remount-ro` contains "rw" as a substring of
    # the errors= value — the token match must still say readonly.
    table = "/dev/mmcblk0p2 / ext4 ro,noatime,errors=remount-ro 0 0\n"
    assert parse_root_fs_mode(table) == "readonly"
    table = "/dev/mmcblk0p2 / ext4 rw,noatime,errors=remount-ro 0 0\n"
    assert parse_root_fs_mode(table) == "read/write"


def test_no_root_entry():
    assert parse_root_fs_mode("proc /proc proc rw 0 0\n") is None


def test_empty():
    assert parse_root_fs_mode("") is None
