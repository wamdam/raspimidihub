PACKAGE = raspimidihub
VERSION = 3.0.0a2
DEB_NAME = $(PACKAGE)_$(VERSION)-1_all
BUILD_DIR = build/$(DEB_NAME)
DEB_FILE = dist/$(DEB_NAME).deb

ROSETUP_PACKAGE = raspimidihub-rosetup
ROSETUP_VERSION = 1.0.2
ROSETUP_DEB_NAME = $(ROSETUP_PACKAGE)_$(ROSETUP_VERSION)-1_all
ROSETUP_BUILD_DIR = build/$(ROSETUP_DEB_NAME)
ROSETUP_DEB_FILE = dist/$(ROSETUP_DEB_NAME).deb

PI_HOST = user@10.1.1.2

.PHONY: all clean deb deb-rosetup deploy deploy-rosetup install uninstall test test-pi run lint fmt fmt-check screenshots

all: deb deb-rosetup

# --- Build ---

deb: $(DEB_FILE)

$(DEB_FILE): src/raspimidihub/*.py src/raspimidihub/plugin_host/*.py src/raspimidihub/runtime/*.py src/raspimidihub/static/*.* $(wildcard src/raspimidihub/static/*/*.*) plugins/*/*.py plugins/*/*.svg systemd/raspimidihub.service systemd/raspimidihub-hostapd.service udev/90-raspimidihub.rules debian/postinst debian/postrm CHANGELOG.txt
	@mkdir -p dist
	@rm -rf $(BUILD_DIR)
	@mkdir -p $(BUILD_DIR)/DEBIAN
	@mkdir -p $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/static/lib
	@mkdir -p $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/static/components
	@mkdir -p $(BUILD_DIR)/lib/systemd/system
	@mkdir -p $(BUILD_DIR)/lib/udev/rules.d
	@mkdir -p $(BUILD_DIR)/usr/lib/raspimidihub
	@mkdir -p $(BUILD_DIR)/usr/local/bin
	@mkdir -p $(BUILD_DIR)/usr/share/doc/$(PACKAGE)
	cp src/raspimidihub/*.py $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/
	@for sub in plugin_host runtime; do \
		if [ -d src/raspimidihub/$$sub ]; then \
			mkdir -p $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/$$sub; \
			cp src/raspimidihub/$$sub/*.py $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/$$sub/; \
		fi; \
	done
	cp -r src/raspimidihub/static/* $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/static/
	@mkdir -p $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/plugins
	@for d in plugins/*/; do \
		pname=$$(basename "$$d"); \
		mkdir -p "$(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/plugins/$$pname"; \
		cp "$$d"__init__.py "$(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/plugins/$$pname/"; \
		test -f "$$d"icon.svg && cp "$$d"icon.svg "$(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/plugins/$$pname/" || true; \
	done
	cp systemd/raspimidihub.service $(BUILD_DIR)/lib/systemd/system/
	cp systemd/raspimidihub-hostapd.service $(BUILD_DIR)/lib/systemd/system/
	# CHANGELOG.txt — ship only the current major-version section
	# (here: everything up to but not including "Version 2.x"), so a
	# 2.0.9 → 3.x upgrader sees the full 3.x delta without the older
	# release-history clutter. The repo's CHANGELOG keeps the entire
	# history; the deb is the user-facing slice.
	sed '/Version 2\./Q' CHANGELOG.txt \
	    > $(BUILD_DIR)/usr/share/doc/$(PACKAGE)/CHANGELOG.txt
	cp udev/90-raspimidihub.rules $(BUILD_DIR)/lib/udev/rules.d/
	cp scripts/reset-wifi.sh $(BUILD_DIR)/usr/local/bin/reset-wifi
	chmod 755 $(BUILD_DIR)/usr/local/bin/reset-wifi
	cp scripts/raspimidihub-system-prepare.sh $(BUILD_DIR)/usr/local/bin/raspimidihub-system-prepare
	chmod 755 $(BUILD_DIR)/usr/local/bin/raspimidihub-system-prepare
	cp scripts/raspimidihub-system-revert.sh $(BUILD_DIR)/usr/local/bin/raspimidihub-system-revert
	chmod 755 $(BUILD_DIR)/usr/local/bin/raspimidihub-system-revert
	cp scripts/raspimidihub-update-watchdog.sh $(BUILD_DIR)/usr/local/bin/raspimidihub-update-watchdog
	chmod 755 $(BUILD_DIR)/usr/local/bin/raspimidihub-update-watchdog
	cp scripts/raspimidihub-install-deb.sh $(BUILD_DIR)/usr/local/bin/raspimidihub-install-deb
	chmod 755 $(BUILD_DIR)/usr/local/bin/raspimidihub-install-deb
	cp scripts/raspimidihub-bt-state.sh $(BUILD_DIR)/usr/local/bin/raspimidihub-bt-state
	chmod 755 $(BUILD_DIR)/usr/local/bin/raspimidihub-bt-state
	cp systemd/raspimidihub-bt-state.service $(BUILD_DIR)/lib/systemd/system/
	@mkdir -p $(BUILD_DIR)/etc/systemd/system/bluetooth.service.d
	cp systemd/bluetooth-no-midi.conf $(BUILD_DIR)/etc/systemd/system/bluetooth.service.d/no-midi.conf
	@echo "Package: $(PACKAGE)" > $(BUILD_DIR)/DEBIAN/control
	@echo "Version: $(VERSION)-1" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Architecture: all" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Maintainer: Daniel Kraft <wam@poplr.de>" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Depends: python3 (>= 3.9), libasound2t64 | libasound2, alsa-utils, avahi-daemon, hostapd, dnsmasq, iw, rfkill, bluez, inotify-tools" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Recommends: raspimidihub-rosetup, bluez-alsa-utils, libasound2-plugin-bluez, python3-dbus-next" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Section: sound" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Priority: optional" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Description: Automatic USB MIDI hub for Raspberry Pi" >> $(BUILD_DIR)/DEBIAN/control
	@echo " RaspiMIDIHub turns a Raspberry Pi into a dedicated, appliance-like USB MIDI" >> $(BUILD_DIR)/DEBIAN/control
	@echo " hub. Automatically routes MIDI data between all connected USB MIDI devices." >> $(BUILD_DIR)/DEBIAN/control
	cp debian/postinst debian/postrm $(BUILD_DIR)/DEBIAN/
	chmod 755 $(BUILD_DIR)/DEBIAN/postinst $(BUILD_DIR)/DEBIAN/postrm
	fakeroot dpkg-deb --build $(BUILD_DIR) $(DEB_FILE)
	@echo "Built $(DEB_FILE)"

deb-rosetup: $(ROSETUP_DEB_FILE)

$(ROSETUP_DEB_FILE): rosetup/setup.sh rosetup/undo.sh rosetup/debian/postinst rosetup/debian/prerm rosetup/debian/postrm
	@mkdir -p dist
	@rm -rf $(ROSETUP_BUILD_DIR)
	@mkdir -p $(ROSETUP_BUILD_DIR)/DEBIAN
	@mkdir -p $(ROSETUP_BUILD_DIR)/usr/sbin
	cp rosetup/setup.sh $(ROSETUP_BUILD_DIR)/usr/sbin/raspimidihub-rosetup
	cp rosetup/undo.sh $(ROSETUP_BUILD_DIR)/usr/sbin/raspimidihub-rosetup-undo
	chmod 755 $(ROSETUP_BUILD_DIR)/usr/sbin/raspimidihub-rosetup
	chmod 755 $(ROSETUP_BUILD_DIR)/usr/sbin/raspimidihub-rosetup-undo
	@echo "Package: $(ROSETUP_PACKAGE)" > $(ROSETUP_BUILD_DIR)/DEBIAN/control
	@echo "Version: $(ROSETUP_VERSION)-1" >> $(ROSETUP_BUILD_DIR)/DEBIAN/control
	@echo "Architecture: all" >> $(ROSETUP_BUILD_DIR)/DEBIAN/control
	@echo "Maintainer: Daniel Kraft <wam@poplr.de>" >> $(ROSETUP_BUILD_DIR)/DEBIAN/control
	@echo "Depends: bash" >> $(ROSETUP_BUILD_DIR)/DEBIAN/control
	@echo "Section: admin" >> $(ROSETUP_BUILD_DIR)/DEBIAN/control
	@echo "Priority: optional" >> $(ROSETUP_BUILD_DIR)/DEBIAN/control
	@echo "Description: Read-only filesystem hardening for Raspberry Pi" >> $(ROSETUP_BUILD_DIR)/DEBIAN/control
	@echo " Makes a Raspberry Pi root filesystem read-only for SD card longevity." >> $(ROSETUP_BUILD_DIR)/DEBIAN/control
	@echo " Configures tmpfs mounts, disables swap, adds rw/ro shell helpers." >> $(ROSETUP_BUILD_DIR)/DEBIAN/control
	cp rosetup/debian/postinst rosetup/debian/prerm rosetup/debian/postrm $(ROSETUP_BUILD_DIR)/DEBIAN/
	chmod 755 $(ROSETUP_BUILD_DIR)/DEBIAN/postinst $(ROSETUP_BUILD_DIR)/DEBIAN/prerm $(ROSETUP_BUILD_DIR)/DEBIAN/postrm
	fakeroot dpkg-deb --build $(ROSETUP_BUILD_DIR) $(ROSETUP_DEB_FILE)
	@echo "Built $(ROSETUP_DEB_FILE)"

clean:
	rm -rf build/ dist/

# --- Release to GitHub ---
# Usage: make release NOTES="changelog text here"
# This builds the deb, tags, pushes, and creates a GitHub release with all required assets.

release: $(DEB_FILE) $(ROSETUP_DEB_FILE)
	@if git diff --quiet && git diff --cached --quiet; then \
		echo "Working tree clean, proceeding..."; \
	else \
		echo "Error: uncommitted changes. Commit first."; exit 1; \
	fi
	@echo "=== Releasing v$(VERSION) ==="
	git tag -a v$(VERSION) -m "v$(VERSION)"
	git push origin HEAD --tags
	gh release create v$(VERSION) \
		$(DEB_FILE) \
		$(ROSETUP_DEB_FILE) \
		scripts/install.sh \
		--title "v$(VERSION)" \
		--notes "$${NOTES:-Release v$(VERSION)}"
	@echo "=== Released: https://github.com/wamdam/raspimidihub/releases/tag/v$(VERSION) ==="

# --- Website deployment ---

WEBHOST = user@statlergrooves.com
WEBROOT = /home/user/webhosting/raspimidihub.com

deploy-website:
	rsync -av --delete website/ $(WEBHOST):$(WEBROOT)/

# --- Pi deployment ---

deploy: $(DEB_FILE)
	scp $(DEB_FILE) $(PI_HOST):/tmp/$(DEB_NAME).deb
	ssh $(PI_HOST) 'sudo mount -o remount,rw / && sudo dpkg -i /tmp/$(DEB_NAME).deb; r=$$?; sudo mount -o remount,ro /; exit $$r'

install: deploy

deploy-rosetup: $(ROSETUP_DEB_FILE)
	scp $(ROSETUP_DEB_FILE) $(PI_HOST):/tmp/$(ROSETUP_DEB_NAME).deb
	ssh $(PI_HOST) 'sudo dpkg -i /tmp/$(ROSETUP_DEB_NAME).deb'

deploy-all: deploy deploy-rosetup

uninstall:
	ssh $(PI_HOST) 'sudo dpkg --purge $(PACKAGE)'

uninstall-rosetup:
	ssh $(PI_HOST) 'sudo dpkg --purge $(ROSETUP_PACKAGE)'

# --- Development ---

deploy-src:
	rsync -av --delete --exclude='__pycache__' src/raspimidihub/ $(PI_HOST):/tmp/raspimidihub/

test:
	@if [ ! -d .venv ]; then python3 -m venv .venv && .venv/bin/pip install -e ".[test]"; fi
	RASPIMIDIHUB_TEST_MODE=1 .venv/bin/pytest tests/ plugins/ -v -m "not alsa and not e2e"

lint:
	@if [ ! -x .venv/bin/ruff ]; then python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"; fi
	.venv/bin/ruff check src plugins

fmt-check:
	@if [ ! -x .venv/bin/ruff ]; then python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"; fi
	.venv/bin/ruff format --check src plugins

fmt:
	@if [ ! -x .venv/bin/ruff ]; then python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"; fi
	.venv/bin/ruff format src plugins
	.venv/bin/ruff check src plugins --fix

test-pi: deploy-src
	ssh $(PI_HOST) 'cd /tmp && PYTHONPATH=/tmp python3 -c "\
		from raspimidihub.alsa_seq import AlsaSeq; \
		seq = AlsaSeq(); \
		devs = seq.scan_devices(); \
		print(f\"Devices: {len(devs)}\"); \
		[print(f\"  {d.name}: {len(d.ports)} ports\") for d in devs]; \
		seq.close()"'

run: deploy-src
	ssh $(PI_HOST) 'cd /tmp && PYTHONPATH=/tmp python3 -m raspimidihub'

logs:
	ssh $(PI_HOST) 'sudo journalctl -u raspimidihub -f --no-pager'

status:
	ssh $(PI_HOST) 'sudo systemctl status raspimidihub'

restart:
	ssh $(PI_HOST) 'sudo systemctl restart raspimidihub'

# --- Documentation screenshots (Playwright + headless Chromium).
# Strips the live plugin set, recreates a curated demo set, walks
# every documented scene, writes PNGs into docs/screenshots/. Does
# NOT save — the Pi's bottom-nav Routing icon ends up dirty; click
# Load Config in Settings to restore your real state.
#
# Override the target Pi with TARGET=http://<host>; default is
# http://10.1.1.2 (matches the rest of the Makefile's PI_HOST).
TARGET ?= http://10.1.1.2

screenshots:
	@if [ ! -x .venv/bin/playwright ]; then \
		python3 -m venv .venv && \
		.venv/bin/pip install -e ".[screenshots]" && \
		.venv/bin/playwright install chromium; \
	fi
	.venv/bin/python scripts/screenshots/run.py --target=$(TARGET)
