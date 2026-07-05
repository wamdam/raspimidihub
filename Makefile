PACKAGE = raspimidihub
# Pre-releases use the PEP440-style suffix form (5.0.0a1 / 5.0.0b2 /
# 5.0.0rc1) — NOT a hyphen. The running 4.8.0+ OTA updater parses deb
# filenames with a regex that only accepts this suffix form; a hyphen
# (5.0.0-alpha1) makes the downloaded deb invisible to it.
VERSION = 6.0.0a1
# Debian Version field: a pre-release suffix MUST be tilde-separated so
# dpkg/apt sort it BELOW the final release (5.0.0~a1 << 5.0.0). A bare
# suffix (5.0.0a1) or hyphen sorts the pre-release *above* the final
# (the bug that burned us before). Insert a '~' before the first letter.
# The git tag / GitHub release / deb *filename* keep the bare suffix
# form (the OTA updater + git need it); only the control Version field
# is rewritten.
DEB_VERSION = $(shell echo '$(VERSION)' | sed -E 's/([0-9])([a-z])/\1~\2/')
DEB_NAME = $(PACKAGE)_$(VERSION)-1_all
BUILD_DIR = build/$(DEB_NAME)
DEB_FILE = dist/$(DEB_NAME).deb

ROSETUP_PACKAGE = raspimidihub-rosetup
ROSETUP_VERSION = 1.0.2
ROSETUP_DEB_NAME = $(ROSETUP_PACKAGE)_$(ROSETUP_VERSION)-1_all
ROSETUP_BUILD_DIR = build/$(ROSETUP_DEB_NAME)
ROSETUP_DEB_FILE = dist/$(ROSETUP_DEB_NAME).deb

PI_HOST = user@10.1.1.2

.PHONY: all clean deb deb-rosetup deploy deploy-rosetup install uninstall test test-pi run lint fmt fmt-check screenshots perf manual manual-deps manual-clean image image-release

all: deb deb-rosetup

# --- Build ---

deb: $(DEB_FILE)

$(DEB_FILE): src/raspimidihub/*.py src/raspimidihub/plugin_host/*.py src/raspimidihub/runtime/*.py src/raspimidihub/static/*.* $(wildcard src/raspimidihub/static/*/*.*) plugins/*/*.py plugins/*/*.svg systemd/raspimidihub.service systemd/raspimidihub-hostapd.service udev/90-raspimidihub.rules debian/postinst debian/postrm debian/copyright CHANGELOG.txt
	@# Belt-and-braces: fail the build if Makefile VERSION and the
	@# Python __version__ have drifted. The Python value is what the
	@# header badge in the UI shows, and 3.0.0a2 shipped with it stuck
	@# at 3.0.0a1 because nothing checked.
	@PY_VER=$$(grep -oP '^__version__ = "\K[^"]+' src/raspimidihub/__init__.py); \
	if [ "$$PY_VER" != "$(VERSION)" ]; then \
		echo "ERROR: Makefile VERSION=$(VERSION) but src/raspimidihub/__init__.py __version__=$$PY_VER"; \
		echo "       Bump src/raspimidihub/__init__.py to match before building."; \
		exit 1; \
	fi
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
		for py in "$$d"*.py; do \
			[ "$$(basename $$py)" != "test_plugin.py" ] && cp "$$py" "$(BUILD_DIR)/usr/lib/python3/dist-packages/raspimidihub/plugins/$$pname/" || true; \
		done; \
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
	# Debian-standard license declaration (GPL-3 + bundled Preact/HTM)
	cp debian/copyright $(BUILD_DIR)/usr/share/doc/$(PACKAGE)/copyright
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
	@echo "Version: $(DEB_VERSION)-1" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Architecture: all" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Maintainer: Daniel Kraft <wam@poplr.de>" >> $(BUILD_DIR)/DEBIAN/control
	@echo "Depends: python3 (>= 3.9), libasound2t64 | libasound2, alsa-utils, avahi-daemon, hostapd, dnsmasq, iw, rfkill, bluez, inotify-tools, python3-zeroconf" >> $(BUILD_DIR)/DEBIAN/control
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

# --- Bootstrap image (Pi OS Lite + first-boot installer) ---
# The image is a fresh Raspberry Pi OS Lite (64-bit) with a oneshot
# systemd unit that downloads + runs the latest install.sh on first
# boot. It's keyed to the *upstream* Pi OS Lite release date, not to
# our code version — one image installs whatever's latest at flash
# time, and the same image stays valid across many code releases.
#
# Build prerequisites (one-time on the build host):
#     sudo apt install libguestfs-tools qemu-user-static xz-utils curl
# The build prompts for sudo twice (virt-customize + virt-sparsify).

image:
	cd image && ./build.sh

# Usage: make image-release IMAGE_TAG=image-YYYY-MM-DD
#   Creates a GitHub release with the .img.xz attached, then regenerates
#   image/os-list.json with the real asset URL.
image-release: image
	@test -n "$$IMAGE_TAG" || (echo "ERROR: pass IMAGE_TAG=image-YYYY-MM-DD"; exit 1)
	@IMG=$$(ls -t dist/raspimidihub-bootstrap-*.img.xz | head -1); \
		IMG_BASE=$$(basename $$IMG); \
		IMG_DATE=$$(echo $$IMG_BASE | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}'); \
		echo "=== Releasing $$IMG_BASE under tag $$IMAGE_TAG ==="; \
		gh release create $$IMAGE_TAG $$IMG \
			--title "RaspiMIDIHub OS image ($$IMG_DATE)" \
			--notes "Pre-built Raspberry Pi OS Lite (64-bit, Trixie) image that auto-installs the latest RaspiMIDIHub release on first boot. Flash with Raspberry Pi Imager — see README for the customization-wizard steps. Built from upstream $$IMG_DATE-raspios-trixie-arm64-lite.img.xz."; \
		URL=https://github.com/wamdam/raspimidihub/releases/download/$$IMAGE_TAG/$$IMG_BASE; \
		echo "[image-release] regenerating os-list.json with $$URL"; \
		sed -i "s|\"url\": \"REPLACE_WITH_RELEASE_ASSET_URL\"|\"url\": \"$$URL\"|" dist/os-list.json; \
		sed -i "s|\"url\": \"https://github.com/wamdam/raspimidihub/releases/download/[^\"]*\"|\"url\": \"$$URL\"|" dist/os-list.json; \
		cp dist/os-list.json image/os-list.json
	@echo "=== Done. Commit image/os-list.json to advertise the new image."

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
	@# Always rebuild the manual from scratch for a release — never ship
	@# a stale PDF. (mtime-based prereqs have skipped a rebuild before,
	@# uploading the previous version's manual; the PDF is gitignored so
	@# this never dirties the tree.)
	rm -f $(MANUAL_PDF)
	$(MAKE) $(MANUAL_PDF)
	@# Bake the version into a copy of install.sh so the uploaded
	@# script always installs THIS release, not whatever happens to be
	@# /latest at the moment a user runs it. Source scripts/install.sh
	@# has BUILD_TAG="unreleased" as a placeholder; dist/install.sh
	@# replaces just that one line and is the per-release artifact
	@# uploaded by gh release create.
	sed 's/^BUILD_TAG="unreleased"$$/BUILD_TAG="v$(VERSION)"/' \
		scripts/install.sh > dist/install.sh
	@grep -q "^BUILD_TAG=\"v$(VERSION)\"$$" dist/install.sh || \
		(echo "ERROR: install.sh BUILD_TAG substitution failed"; exit 1)
	chmod +x dist/install.sh
	git tag -a v$(VERSION) -m "v$(VERSION)"
	git push origin HEAD --tags
	@# Auto-mark alpha / beta / rc versions as prereleases. Stable
	@# (e.g. 3.0.0) versions don't carry a letter suffix.
	$(eval PRERELEASE := $(shell echo $(VERSION) | grep -qE '[a-z]' && echo --prerelease))
	gh release create v$(VERSION) \
		$(DEB_FILE) \
		$(ROSETUP_DEB_FILE) \
		dist/install.sh \
		$(MANUAL_PDF) \
		--title "v$(VERSION)" \
		$(PRERELEASE) \
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

# The dev / test toolchain lives in .venv. We don't install the
# package itself (no `pip install -e .`) -- src/ is on PYTHONPATH at
# run time, so the venv only carries pytest / ruff / playwright.
# pyproject.toml isn't shipped; config lives in pytest.ini + ruff.toml.
test:
	@if [ ! -x .venv/bin/pytest ]; then python3 -m venv .venv && .venv/bin/pip install pytest pytest-asyncio; fi
	RASPIMIDIHUB_TEST_MODE=1 PYTHONPATH=src .venv/bin/pytest tests/ plugins/ -v -m "not alsa and not e2e"

lint:
	@if [ ! -x .venv/bin/ruff ]; then python3 -m venv .venv && .venv/bin/pip install ruff; fi
	.venv/bin/ruff check src plugins

fmt-check:
	@if [ ! -x .venv/bin/ruff ]; then python3 -m venv .venv && .venv/bin/pip install ruff; fi
	.venv/bin/ruff format --check src plugins

fmt:
	@if [ ! -x .venv/bin/ruff ]; then python3 -m venv .venv && .venv/bin/pip install ruff; fi
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
		.venv/bin/pip install playwright && \
		.venv/bin/playwright install chromium; \
	fi
	.venv/bin/python scripts/screenshots/run.py --target=$(TARGET)

# --- Latency / jitter perf harness (stdlib only) ---
# Operations-disturbance sweep (default) or passive soak. NEVER run the
# `ops` sweep against a live performance rig — it creates/deletes plugins
# and Saves/Loads config on the target. Override the box with TARGET= and
# pass extra flags via PERF_ARGS=, e.g.:
#   make perf TARGET=http://10.1.1.2
#   make perf TARGET=http://10.1.1.2 PERF_ARGS="--mode passive --duration 3600"
perf:
	.venv/bin/python scripts/perf/perf.py --target=$(TARGET) $(PERF_ARGS)

# --- Manual (PDF build via pandoc + xelatex) ---
# `make manual`       -- build docs/manual/raspimidihub-manual.pdf
# `make manual-deps`  -- apt-install the LaTeX toolchain (~700 MB,
#                        one-time; needs sudo).
# `make manual-clean` -- remove the built PDF.
#
# The chapter sources, the metadata block, the SVG diagram, the
# screenshots, and the header.tex template are all tracked here as
# prerequisites so a touch in any of them invalidates the PDF.

MANUAL_DIR     = docs/manual
MANUAL_PDF     = $(MANUAL_DIR)/raspimidihub-manual.pdf
MANUAL_VERSION_TEX = $(MANUAL_DIR)/templates/version.tex
# Date stamped onto the cover. Derived from the top-most version
# entry in CHANGELOG.txt — that's "the date this release went out"
# without needing a second hand-maintained constant.
MANUAL_DATE    = $(shell awk '/^[0-9]{4}-[0-9]{2}-[0-9]{2}/{print $$1; exit}' CHANGELOG.txt 2>/dev/null)
MANUAL_SOURCES = $(wildcard $(MANUAL_DIR)/[0-9A-E]*.md) \
                 $(MANUAL_DIR)/metadata.yaml \
                 $(MANUAL_DIR)/templates/header.tex \
                 $(wildcard docs/screenshots/*.png) \
                 docs/screenshots/architecture-block-diagram.svg \
                 Makefile CHANGELOG.txt

# The apt packages we install for `make manual-deps`. Keep this in
# one place so it can be inspected and changed without hunting.
MANUAL_APT_PACKAGES = \
    pandoc \
    texlive-xetex \
    texlive-fonts-recommended \
    texlive-latex-recommended \
    texlive-latex-extra \
    librsvg2-bin \
    fonts-dejavu

manual: $(MANUAL_PDF)

$(MANUAL_PDF): $(MANUAL_SOURCES)
	@command -v pandoc   >/dev/null 2>&1 || { \
		echo "ERROR: pandoc not found."; \
		echo "       Run 'make manual-deps' first (one-time install)."; \
		exit 1; }
	@command -v xelatex  >/dev/null 2>&1 || { \
		echo "ERROR: xelatex not found."; \
		echo "       Run 'make manual-deps' first (one-time install)."; \
		exit 1; }
	@command -v rsvg-convert >/dev/null 2>&1 || { \
		echo "ERROR: rsvg-convert not found (needed for SVG embedding)."; \
		echo "       Run 'make manual-deps' first (one-time install)."; \
		exit 1; }
	@printf '%% Generated by `make manual` -- do not edit.\n%% Single-source the version/date from Makefile VERSION + CHANGELOG.txt.\n\\newcommand{\\manualversion}{%s}\n\\newcommand{\\manualdate}{%s}\n' \
		"$(VERSION)" "$(MANUAL_DATE)" > $(MANUAL_VERSION_TEX)
	@echo "  PANDOC $(MANUAL_PDF)  (version $(VERSION), date $(MANUAL_DATE))"
	@cd $(MANUAL_DIR) && pandoc \
		metadata.yaml \
		$$(ls [0-9A-D]*.md | sort) \
		--pdf-engine=xelatex \
		--include-in-header=templates/version.tex \
		--include-in-header=templates/header.tex \
		--lua-filter=templates/admonitions.lua \
		--metadata date="$(MANUAL_DATE)" \
		--toc --toc-depth=3 \
		--number-sections \
		--resource-path=.:../screenshots \
		-o $$(basename $(MANUAL_PDF))
	@echo "  done -> $(MANUAL_PDF)"

manual-deps:
	@echo "Installing LaTeX toolchain for manual PDF build."
	@echo "Packages: $(MANUAL_APT_PACKAGES)"
	@echo "This is a one-time install (~700 MB). You'll be prompted for sudo."
	sudo apt-get update
	sudo apt-get install -y $(MANUAL_APT_PACKAGES)

manual-clean:
	rm -f $(MANUAL_PDF)
