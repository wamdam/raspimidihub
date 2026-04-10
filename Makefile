PACKAGE = raspimidihub
VERSION = 2.0.0-alpha1
DEB_NAME = $(PACKAGE)_$(VERSION)-1_all
BUILD_DIR = build/$(DEB_NAME)
DEB_FILE = dist/$(DEB_NAME).deb

ROSETUP_PACKAGE = raspimidihub-rosetup
ROSETUP_VERSION = 1.0.0
ROSETUP_DEB_NAME = $(ROSETUP_PACKAGE)_$(ROSETUP_VERSION)-1_all
ROSETUP_BUILD_DIR = build/$(ROSETUP_DEB_NAME)
ROSETUP_DEB_FILE = dist/$(ROSETUP_DEB_NAME).deb

PI_HOST = user@10.1.1.2

.PHONY: all clean deb deb-rosetup deploy deploy-rosetup install uninstall test run

all: deb deb-rosetup

# --- Build ---

deb: $(DEB_FILE)

$(DEB_FILE): src/raspimidihub/*.py src/raspimidihub/static/* plugins/*/*.py plugins/*/*.svg systemd/raspimidihub.service udev/90-raspimidihub.rules debian/postinst debian/postrm
	@mkdir -p dist
	@rm -rf $(BUILD_DIR)
	@mkdir -p $(BUILD_DIR)/DEBIAN
	@mkdir -p $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/static/lib
	@mkdir -p $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/static/components
	@mkdir -p $(BUILD_DIR)/lib/systemd/system
	@mkdir -p $(BUILD_DIR)/lib/udev/rules.d
	@mkdir -p $(BUILD_DIR)/usr/lib/raspimidihub
	@mkdir -p $(BUILD_DIR)/usr/local/bin
	cp src/raspimidihub/*.py $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/
	cp -r src/raspimidihub/static/* $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/static/
	@mkdir -p $(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/plugins
	@for d in plugins/*/; do \
		pname=$$(basename "$$d"); \
		mkdir -p "$(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/plugins/$$pname"; \
		cp "$$d"__init__.py "$(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/plugins/$$pname/"; \
		test -f "$$d"icon.svg && cp "$$d"icon.svg "$(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/plugins/$$pname/" || true; \
	done
	cp systemd/raspimidihub.service $(BUILD_DIR)/lib/systemd/system/
	cp udev/90-raspimidihub.rules $(BUILD_DIR)/lib/udev/rules.d/
	cp scripts/raspimidihub-update.sh $(BUILD_DIR)/usr/lib/raspimidihub/update.sh
	chmod 755 $(BUILD_DIR)/usr/lib/raspimidihub/update.sh
	cp scripts/reset-wifi.sh $(BUILD_DIR)/usr/local/bin/reset-wifi
	chmod 755 $(BUILD_DIR)/usr/local/bin/reset-wifi
	@echo "Package: $(PACKAGE)" > $(BUILD_DIR)/DEBIAN/control
	@echo "Version: $(VERSION)-1" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Architecture: all" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Maintainer: Daniel Kraft <wam@poplr.de>" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Depends: python3 (>= 3.9), libasound2t64 | libasound2, alsa-utils, avahi-daemon, hostapd, dnsmasq" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Recommends: raspimidihub-rosetup" >> $(BUILD_DIR)/DEBIAN/control
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
	@echo "Recommends: ntpsec" >> $(ROSETUP_BUILD_DIR)/DEBIAN/control
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

release: $(DEB_FILE)
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
		scripts/install.sh \
		--title "v$(VERSION)" \
		--notes "$${NOTES:-Release v$(VERSION)}"
	@echo "=== Released: https://github.com/wamdam/raspimidihub/releases/tag/v$(VERSION) ==="

# --- Pi deployment ---

deploy: $(DEB_FILE)
	scp $(DEB_FILE) $(PI_HOST):/tmp/$(DEB_NAME).deb
	ssh $(PI_HOST) 'sudo dpkg -i /tmp/$(DEB_NAME).deb'

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

test: deploy-src
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
