"""UMP (MIDI 2.0) capability probe — alsa_seq.probe_ump_support()."""

from raspimidihub import alsa_seq


def test_mock_lib_reports_not_capable():
    # The test-mode mock lib answers 0 to every call, so the read-back
    # of midi_version never matches the requested value: kernel=no.
    support = alsa_seq.probe_ump_support(force=True)
    assert support.kernel is False
    assert support.capable is False


def test_missing_alsa_lib_symbols(monkeypatch):
    # alsa-lib < 1.2.10 (e.g. Bookworm's 1.2.8) lacks the midi_version
    # accessors; the probe must not attempt the kernel test then.
    monkeypatch.setattr(alsa_seq, "snd_seq_client_info_get_midi_version", None)
    calls = []
    monkeypatch.setattr(alsa_seq, "snd_seq_open",
                        lambda *a: calls.append("open") or 0)
    support = alsa_seq.probe_ump_support(force=True)
    assert support.alsa_lib is False
    assert support.kernel is False
    assert support.capable is False
    assert calls == []


def test_ump_kernel_reports_capable(monkeypatch):
    # Fake a kernel with CONFIG_SND_SEQ_UMP: the midi_version survives
    # the set/get round-trip.
    state = {"v": 0}
    monkeypatch.setattr(alsa_seq, "snd_seq_open", lambda *a: 0)
    monkeypatch.setattr(alsa_seq, "snd_seq_close", lambda h: 0)
    monkeypatch.setattr(alsa_seq, "snd_seq_client_info_malloc", lambda p: 0)
    monkeypatch.setattr(alsa_seq, "snd_seq_client_info_free", lambda p: None)
    monkeypatch.setattr(alsa_seq, "snd_seq_get_client_info", lambda h, i: 0)
    monkeypatch.setattr(alsa_seq, "snd_seq_set_client_info", lambda h, i: 0)
    monkeypatch.setattr(alsa_seq, "snd_seq_client_info_set_midi_version",
                        lambda i, v: state.__setitem__("v", v))
    monkeypatch.setattr(alsa_seq, "snd_seq_client_info_get_midi_version",
                        lambda i: state["v"])
    support = alsa_seq.probe_ump_support(force=True)
    assert support.alsa_lib is True
    assert support.kernel is True
    assert support.capable is True


def test_kernel_rejects_set_client_info(monkeypatch):
    # Some kernels reject the ioctl outright instead of ignoring the
    # field — that must read as kernel=no, not an exception.
    monkeypatch.setattr(alsa_seq, "snd_seq_open", lambda *a: 0)
    monkeypatch.setattr(alsa_seq, "snd_seq_close", lambda h: 0)
    monkeypatch.setattr(alsa_seq, "snd_seq_client_info_malloc", lambda p: 0)
    monkeypatch.setattr(alsa_seq, "snd_seq_client_info_free", lambda p: None)
    monkeypatch.setattr(alsa_seq, "snd_seq_get_client_info", lambda h, i: 0)
    monkeypatch.setattr(alsa_seq, "snd_seq_set_client_info", lambda h, i: -22)
    monkeypatch.setattr(alsa_seq, "snd_seq_client_info_set_midi_version",
                        lambda i, v: None)
    monkeypatch.setattr(alsa_seq, "snd_seq_client_info_get_midi_version",
                        lambda i: 1)
    support = alsa_seq.probe_ump_support(force=True)
    assert support.kernel is False
    assert support.capable is False


def test_probe_result_is_cached():
    first = alsa_seq.probe_ump_support(force=True)
    assert alsa_seq.probe_ump_support() is first
