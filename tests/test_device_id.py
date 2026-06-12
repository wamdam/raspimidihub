"""Tests for device identification and registry."""

from unittest.mock import patch

from raspimidihub.device_id import (
    DeviceRegistry,
    StableDeviceInfo,
    _identity_serial,
    vidpid_of_stable_id,
)


def _mock_card_stable_id(card_num):
    """Return a StableDeviceInfo that simulates two identical M8 devices."""
    return StableDeviceInfo(
        stable_id="usb-1-1.2-1234:5678",  # same for both
        vid="1234", pid="5678", usb_path="1-1.2",
        card_num=card_num,
        display_name="M8",
    )


class TestDuplicateDevices:
    def test_two_identical_devices_get_unique_ids(self):
        """Two devices with same VID:PID on same USB path get disambiguated."""
        registry = DeviceRegistry()

        with patch("raspimidihub.device_id.alsa_client_to_card") as mock_card, \
             patch("raspimidihub.device_id.get_card_stable_id") as mock_info:
            mock_card.side_effect = lambda cid: cid  # card = client_id
            mock_info.side_effect = _mock_card_stable_id

            result = registry.scan([20, 21])

        # Both devices should be registered
        assert len(result) == 2

        # They should have different stable IDs
        ids = {info.stable_id for info in result.values()}
        assert len(ids) == 2

        # First gets the base ID, second gets #2
        info_20 = result[20]
        info_21 = result[21]
        assert info_20.stable_id == "usb-1-1.2-1234:5678"
        assert info_21.stable_id == "usb-1-1.2-1234:5678#2"

    def test_rename_one_of_two_identical_devices(self):
        """Renaming one identical device should not affect the other."""
        registry = DeviceRegistry()

        with patch("raspimidihub.device_id.alsa_client_to_card") as mock_card, \
             patch("raspimidihub.device_id.get_card_stable_id") as mock_info:
            mock_card.side_effect = lambda cid: cid
            mock_info.side_effect = _mock_card_stable_id

            registry.scan([20, 21])

        # Rename the second device
        info_21 = registry.get_by_client(21)
        registry.set_custom_name(info_21.stable_id, "My M8")

        # First device should keep default name
        info_20 = registry.get_by_client(20)
        assert info_20.name == "M8"

        # Second device should have custom name
        assert info_21.name == "My M8"

    def test_custom_names_survive_rescan(self):
        """Custom names for disambiguated devices persist across rescans."""
        registry = DeviceRegistry()

        with patch("raspimidihub.device_id.alsa_client_to_card") as mock_card, \
             patch("raspimidihub.device_id.get_card_stable_id") as mock_info:
            mock_card.side_effect = lambda cid: cid
            mock_info.side_effect = _mock_card_stable_id

            # First scan
            registry.scan([20, 21])
            info_21 = registry.get_by_client(21)
            registry.set_custom_name(info_21.stable_id, "My M8")

            # Rescan (simulates hotplug or reboot) — same client IDs
            registry.scan([20, 21])

        info_20 = registry.get_by_client(20)
        info_21 = registry.get_by_client(21)
        assert info_20.name == "M8"
        assert info_21.name == "My M8"

    def test_three_identical_devices(self):
        """Three identical devices all get unique IDs."""
        registry = DeviceRegistry()

        with patch("raspimidihub.device_id.alsa_client_to_card") as mock_card, \
             patch("raspimidihub.device_id.get_card_stable_id") as mock_info:
            mock_card.side_effect = lambda cid: cid
            mock_info.side_effect = _mock_card_stable_id

            result = registry.scan([20, 21, 22])

        ids = sorted(info.stable_id for info in result.values())
        assert ids == [
            "usb-1-1.2-1234:5678",
            "usb-1-1.2-1234:5678#2",
            "usb-1-1.2-1234:5678#3",
        ]

    def test_unique_devices_not_disambiguated(self):
        """Devices with different stable IDs should not be affected."""
        registry = DeviceRegistry()

        def mock_info(card_num):
            if card_num == 20:
                return StableDeviceInfo(
                    stable_id="usb-1-1.2-1234:5678",
                    vid="1234", pid="5678", usb_path="1-1.2",
                    card_num=20, display_name="M8",
                )
            else:
                return StableDeviceInfo(
                    stable_id="usb-1-1.3-abcd:ef01",
                    vid="abcd", pid="ef01", usb_path="1-1.3",
                    card_num=21, display_name="KeyStep",
                )

        with patch("raspimidihub.device_id.alsa_client_to_card") as mock_card, \
             patch("raspimidihub.device_id.get_card_stable_id") as mock_info_fn:
            mock_card.side_effect = lambda cid: cid
            mock_info_fn.side_effect = mock_info

            result = registry.scan([20, 21])

        ids = {info.stable_id for info in result.values()}
        assert ids == {"usb-1-1.2-1234:5678", "usb-1-1.3-abcd:ef01"}


# --- Re-recognition (serial IDs, aliases, soft-match) -----------------


def _usb_info(path, vid="1235", pid="0148", serial="", name="Dev"):
    """Build a USB StableDeviceInfo the way get_card_stable_id does."""
    legacy = f"usb-{path}-{vid}:{pid}"
    canonical = f"usb-{vid}:{pid}-{serial}" if serial else legacy
    return StableDeviceInfo(
        stable_id=canonical, vid=vid, pid=pid, usb_path=path,
        card_num=0, display_name=name, serial=serial,
        canonical_id=canonical, legacy_id=legacy,
    )


def _scan(registry, devices):
    """Run registry.scan with mocked sysfs. devices: {client_id: info}.
    Pass fresh info objects per call — scan mutates stable_id."""
    with patch("raspimidihub.device_id.alsa_client_to_card") as mock_card, \
         patch("raspimidihub.device_id.get_card_stable_id") as mock_info:
        mock_card.side_effect = lambda cid: cid
        mock_info.side_effect = lambda card: devices[card]
        return registry.scan(sorted(devices))


class TestIdentitySerial:
    def test_real_serials_kept(self):
        assert _identity_serial("AZ6768Q2A087AE") == "AZ6768Q2A087AE"
        assert _identity_serial("LX1GDF35501A02") == "LX1GDF35501A02"

    def test_placeholder_zeros_rejected(self):
        assert _identity_serial("000000000001") == ""
        assert _identity_serial("0000") == ""

    def test_short_and_repeated_rejected(self):
        assert _identity_serial("") == ""
        assert _identity_serial("AB") == ""
        assert _identity_serial("AAAAAAAA") == ""

    def test_sanitized_for_id_use(self):
        # Roland pads with trailing spaces; separators must not survive
        assert _identity_serial("  52003600165031304D303420   ") \
            == "52003600165031304D303420"
        assert _identity_serial("a:b|c d") == "a-b-c-d"


class TestVidpidParsing:
    def test_both_formats(self):
        assert vidpid_of_stable_id("usb-1235:0148-LX1GDF") == "1235:0148"
        assert vidpid_of_stable_id("usb-1-1.2.4-2467:2033") == "2467:2033"

    def test_disambiguated_excluded(self):
        assert vidpid_of_stable_id("usb-1-1.2-1234:5678#2") is None

    def test_non_usb(self):
        assert vidpid_of_stable_id("bt-AA:BB:CC:DD:EE:FF") is None
        assert vidpid_of_stable_id("builtin-Headphones") is None


class TestSerialIdentity:
    def test_serial_device_port_independent(self):
        """A device with a real serial keeps its ID on any port."""
        registry = DeviceRegistry()
        registry.set_referenced_ids({"usb-1235:0148-LX1GDF"})
        _scan(registry, {20: _usb_info("1-1.3", serial="LX1GDF")})
        assert registry.get_by_client(20).stable_id == "usb-1235:0148-LX1GDF"
        # replugged elsewhere — same identity, no alias needed
        _scan(registry, {21: _usb_info("1-1.5", serial="LX1GDF")})
        assert registry.get_by_client(21).stable_id == "usb-1235:0148-LX1GDF"
        assert registry.aliases() == {}

    def test_legacy_claim_on_upgrade(self):
        """Old config references the port-bound ID; the device (now
        serial-capable) registers under it — exact port evidence."""
        registry = DeviceRegistry()
        registry.set_referenced_ids({"usb-1-1.3-1235:0148"})
        _scan(registry, {20: _usb_info("1-1.3", serial="LX1GDF")})
        info = registry.get_by_client(20)
        assert info.stable_id == "usb-1-1.3-1235:0148"
        assert registry.aliases() == {
            "usb-1-1.3-1235:0148": "usb-1235:0148-LX1GDF"}

    def test_commit_migrates_alias(self):
        registry = DeviceRegistry()
        registry.load_custom_names({"usb-1-1.3-1235:0148": "My XL"})
        registry.set_clock_blocked("usb-1-1.3-1235:0148", blocked=True)
        registry.set_referenced_ids({"usb-1-1.3-1235:0148"})
        _scan(registry, {20: _usb_info("1-1.3", serial="LX1GDF")})

        migrated = registry.commit_aliases()

        assert migrated == {"usb-1-1.3-1235:0148": "usb-1235:0148-LX1GDF"}
        info = registry.get_by_stable_id("usb-1235:0148-LX1GDF")
        assert info is not None and info.stable_id == "usb-1235:0148-LX1GDF"
        assert registry.get_custom_names() == {
            "usb-1235:0148-LX1GDF": "My XL"}
        assert registry.get_clock_blocked() == ["usb-1235:0148-LX1GDF"]
        assert registry.aliases() == {}


class TestSoftMatch:
    def test_serialless_device_moved_port(self):
        """Single serial-less device replugged into another port is
        re-recognized via the unambiguous VID:PID match."""
        registry = DeviceRegistry()
        registry.set_referenced_ids({"usb-1-1.2.4-2467:2033"})
        _scan(registry, {20: _usb_info("1-1.5", vid="2467", pid="2033")})
        info = registry.get_by_client(20)
        assert info.stable_id == "usb-1-1.2.4-2467:2033"
        assert registry.aliases() == {
            "usb-1-1.2.4-2467:2033": "usb-1-1.5-2467:2033"}

    def test_only_new_devices_are_candidates(self):
        """A device co-present with the saved one must not inherit its
        identity when the saved one goes offline (device restart)."""
        registry = DeviceRegistry()
        registry.set_referenced_ids({"usb-1-1.3-2467:2033"})
        # A (saved, port 1-1.3) and B (unclaimed, port 1-1.5) both online
        _scan(registry, {20: _usb_info("1-1.3", vid="2467", pid="2033"),
                         21: _usb_info("1-1.5", vid="2467", pid="2033")})
        assert registry.get_by_client(20).stable_id == "usb-1-1.3-2467:2033"
        # A restarts — only B present; B was already there: no match
        _scan(registry, {21: _usb_info("1-1.5", vid="2467", pid="2033")})
        assert registry.get_by_client(21).stable_id == "usb-1-1.5-2467:2033"
        assert registry.aliases() == {}

    def test_ambiguity_blocks_match(self):
        """Two unresolved same-model entries -> no guess, on purpose."""
        registry = DeviceRegistry()
        registry.set_referenced_ids({"usb-1-1.3-2467:2033",
                                     "usb-1-1.4-2467:2033"})
        _scan(registry, {20: _usb_info("1-1.5", vid="2467", pid="2033")})
        assert registry.get_by_client(20).stable_id == "usb-1-1.5-2467:2033"
        assert registry.aliases() == {}

    def test_exact_match_supersedes_alias(self):
        """A newcomer with exact port evidence reclaims an ID that a
        soft-match handed to another unit."""
        registry = DeviceRegistry()
        registry.set_referenced_ids({"usb-1-1.3-2467:2033"})
        # B appears first, soft-matches the saved entry
        _scan(registry, {21: _usb_info("1-1.5", vid="2467", pid="2033")})
        assert registry.get_by_client(21).stable_id == "usb-1-1.3-2467:2033"
        # the real device A appears at the saved port
        _scan(registry, {20: _usb_info("1-1.3", vid="2467", pid="2033"),
                         21: _usb_info("1-1.5", vid="2467", pid="2033")})
        assert registry.get_by_client(20).stable_id == "usb-1-1.3-2467:2033"
        assert registry.get_by_client(21).stable_id == "usb-1-1.5-2467:2033"
        assert registry.aliases() == {}

    def test_reset_presence_rearms_matching(self):
        """Load/Restore/Import make existing devices candidates again."""
        registry = DeviceRegistry()
        registry.set_referenced_ids(set())
        _scan(registry, {21: _usb_info("1-1.5", vid="2467", pid="2033")})
        # A config referencing another port gets loaded — device is not
        # newly appeared, so without a reset there is no match...
        registry.set_referenced_ids({"usb-1-1.3-2467:2033"})
        _scan(registry, {21: _usb_info("1-1.5", vid="2467", pid="2033")})
        assert registry.get_by_client(21).stable_id == "usb-1-1.5-2467:2033"
        # ...but Load resets presence: boot-like, match allowed.
        registry.reset_presence()
        _scan(registry, {21: _usb_info("1-1.5", vid="2467", pid="2033")})
        assert registry.get_by_client(21).stable_id == "usb-1-1.3-2467:2033"

    def test_alias_survives_rescan(self):
        registry = DeviceRegistry()
        registry.set_referenced_ids({"usb-1-1.2.4-2467:2033"})
        _scan(registry, {20: _usb_info("1-1.5", vid="2467", pid="2033")})
        # hotplug rescan with the same device — alias sticks
        _scan(registry, {20: _usb_info("1-1.5", vid="2467", pid="2033")})
        assert registry.get_by_client(20).stable_id == "usb-1-1.2.4-2467:2033"

    def test_alias_dropped_when_no_longer_referenced(self):
        registry = DeviceRegistry()
        registry.set_referenced_ids({"usb-1-1.2.4-2467:2033"})
        _scan(registry, {20: _usb_info("1-1.5", vid="2467", pid="2033")})
        # a different config without that entry gets loaded
        registry.set_referenced_ids(set())
        _scan(registry, {20: _usb_info("1-1.5", vid="2467", pid="2033")})
        assert registry.get_by_client(20).stable_id == "usb-1-1.5-2467:2033"
        assert registry.aliases() == {}
