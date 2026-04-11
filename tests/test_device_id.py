"""Tests for device identification and registry."""

from unittest.mock import patch, MagicMock

from raspimidihub.device_id import DeviceRegistry, StableDeviceInfo


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
