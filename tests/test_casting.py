from casting import alias_chain, choose_voice
from reference_text import ReferenceTranscripts


def test_title_follows_the_alias_chain_to_a_newly_cast_voice():
    voices = {"Anvil": "/voices/anvil-designed.wav", "Lord Valor": "/voices/valor.wav"}
    choice = choose_voice("king anvil", "neutral", voices)
    assert choice.path == "/voices/anvil-designed.wav"
    assert not choice.fallback
    # The actor key used for mixing and routing stays the final canonical name.
    assert choice.canonical == "Lord Valor"


def test_title_falls_back_to_the_legacy_clip_when_the_middle_name_is_uncast():
    voices = {"Lord Valor": "/voices/valor.wav", "_default": "/voices/narrator.wav"}
    choice = choose_voice("King Of Swords", "neutral", voices)
    assert choice.path == "/voices/valor.wav"
    assert not choice.fallback


def test_alias_chain_stops_on_a_cycle(monkeypatch):
    import casting
    monkeypatch.setitem(casting.SPEAKER_ALIASES, "Loop A", "Loop B")
    monkeypatch.setitem(casting.SPEAKER_ALIASES, "Loop B", "Loop A")
    assert alias_chain("Loop A") == ["Loop A", "Loop B"]


def test_designed_reference_uses_its_exact_script_instead_of_asr(tmp_path):
    reference = tmp_path / "nephis-designed.wav"
    reference.write_bytes(b"RIFF")
    reference.with_suffix(".txt").write_text("We will rest here until nightfall.\n", encoding="utf-8")
    transcripts = ReferenceTranscripts(tmp_path / ".reference-text")
    assert transcripts.get(str(reference), "abc", "Nephis") == "We will rest here until nightfall."


def test_blank_script_sidecar_falls_through_to_the_cached_transcript(tmp_path):
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"RIFF")
    reference.with_suffix(".txt").write_text("  \n", encoding="utf-8")
    cache = tmp_path / ".reference-text"
    cache.mkdir()
    (cache / "abc.txt").write_text("cached words", encoding="utf-8")
    assert ReferenceTranscripts(cache).get(str(reference), "abc", "X") == "cached words"
