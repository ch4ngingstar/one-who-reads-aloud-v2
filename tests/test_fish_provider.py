import io
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from types import SimpleNamespace
import wave

import pytest

import fish_provider
from fish_provider import FishProvider, is_fish, load_direction
from speech_providers import provider_for

DIRECTION = {"neutral": "", "angry": "[angry]", "whispers": "[whispering]"}


def make_provider(tmp_path, direction=DIRECTION):
    weights = tmp_path / "weights"
    weights.mkdir(exist_ok=True)
    stub = weights / "fish-audio-s2-pro-q8_0.gguf"
    if not stub.exists():  # rewriting would change the mtime that identifies the weights
        stub.write_bytes(b"GGUF")
    return FishProvider(weights, tmp_path / "audio", direction=direction)


def cue(actor="Sunny", emotion="neutral", reference="ref.wav", line_id=1, index=0):
    return SimpleNamespace(actor=actor, emotion=emotion, reference=reference, reference_hash="h" * 64,
                           line_id=line_id, index=index)


def tiny_wav():
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setparams((1, 2, 44100, 0, "NONE", ""))
        wav.writeframes(b"\x00\x00" * 441)
    return out.getvalue()


def test_emotion_becomes_an_inline_cue_but_the_narrator_stays_plain(tmp_path):
    provider = make_provider(tmp_path)
    assert provider.directed(cue(emotion="Angry"), "Get out.") == "[angry] Get out."
    assert provider.directed(cue(emotion="neutral"), "Fine.") == "Fine."
    assert provider.directed(cue(emotion="unlisted"), "Hm.") == "Hm."
    assert provider.directed(cue(actor="Narrator", emotion="angry"), "He left.") == "He left."


def test_take_key_carries_only_the_lines_own_cue(tmp_path, monkeypatch):
    provider = make_provider(tmp_path)
    monkeypatch.setattr(provider, "transcript", lambda c: "reference words")
    angry = provider.conditioning_identity(cue(emotion="angry"))
    calm = provider.conditioning_identity(cue(emotion="neutral"))
    edited = make_provider(tmp_path, {**DIRECTION, "whispers": "[softly]"})
    monkeypatch.setattr(edited, "transcript", lambda c: "reference words")
    assert angry != calm
    # Editing the whispers cue leaves angry and neutral takes valid.
    assert edited.conditioning_identity(cue(emotion="angry")) == angry
    assert edited.conditioning_identity(cue(emotion="neutral")) == calm


def test_first_take_is_reproducible_and_each_retake_draws_a_new_seed(tmp_path):
    first = make_provider(tmp_path)
    again = make_provider(tmp_path)
    line = cue()
    seeds = [first.seed(line, "Hello.") for _ in range(3)]
    assert len(set(seeds)) == 3
    assert again.seed(line, "Hello.") == seeds[0]


def test_direction_file_is_validated(tmp_path):
    bad = tmp_path / "direction.json"
    bad.write_text(json.dumps({"cues": {"angry": 3}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_direction(bad)
    assert load_direction(tmp_path / "missing.json") == {}
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"cues": {"Angry": " [angry] "}}), encoding="utf-8")
    assert load_direction(good) == {"angry": "[angry]"}


def test_provider_for_routes_a_fish_weights_folder(tmp_path):
    provider = provider_for(None, make_provider(tmp_path).directory, tmp_path / "audio")
    assert isinstance(provider, FishProvider)
    assert is_fish(provider.directory)
    assert not is_fish(tmp_path / "audio")


def test_render_posts_the_directed_line_with_its_reference(tmp_path, monkeypatch):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = tiny_wav()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = make_provider(tmp_path)
        monkeypatch.setattr(provider, "reference", lambda c: (c.reference, "reference words"))
        provider.url = f"http://127.0.0.1:{server.server_port}"
        provider.proc = SimpleNamespace(poll=lambda: None)
        audio, = provider.render([(cue(emotion="whispers", reference="C:/voices/sunny.wav"), "Quiet.")])
    finally:
        server.shutdown()
    assert audio[:4] == b"RIFF"
    assert seen[0]["input"] == "[whispering] Quiet."
    assert seen[0]["voice_ref"] == {"type": "path", "path": "C:/voices/sunny.wav"}
    assert seen[0]["reference_text"] == "reference words"
    assert isinstance(seen[0]["seed"], int)


def test_render_outside_a_session_fails_clearly(tmp_path):
    with pytest.raises(RuntimeError, match="outside its recording session"):
        make_provider(tmp_path).render([(cue(), "Hello.")])


def test_missing_weights_are_reported(tmp_path):
    with pytest.raises(RuntimeError, match="No Fish S2 Pro weights"):
        FishProvider(tmp_path, tmp_path / "audio", direction={})


def test_missing_server_binary_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(fish_provider, "SERVER", tmp_path / "nope.exe")
    with pytest.raises(RuntimeError, match="audio.cpp server not found"):
        make_provider(tmp_path).__enter__()


def test_long_reference_is_trimmed_at_a_sentence_end_and_the_original_kept(tmp_path):
    import numpy as np
    import soundfile as sf
    from reference_text import ReferenceTranscripts

    original = tmp_path / "jest.wav"
    sf.write(str(original), np.full(30 * 16000, 0.1, dtype=np.float32), 16000, subtype="PCM_16")
    before = original.read_bytes()
    seg = lambda start, end, text: SimpleNamespace(start=start, end=end, text=text, words=[])

    class FakeASR:
        calls = 0

        def transcribe(self, *args, **kwargs):
            FakeASR.calls += 1
            return iter([seg(0, 6, " First."), seg(6, 14.5, " Second."), seg(14.5, 25, " Third.")]), None

    transcripts = ReferenceTranscripts(tmp_path / "cache")
    transcripts.asr = FakeASR()
    path, words = transcripts.fitted(original, "a" * 64, "Jest", max_seconds=18)
    assert words == "First. Second."
    assert abs(sf.info(path).duration - 14.65) < 0.01
    assert original.read_bytes() == before
    # Cached: the second call neither re-transcribes nor re-cuts.
    assert transcripts.fitted(original, "a" * 64, "Jest", max_seconds=18) == (path, words)
    assert FakeASR.calls == 1


def test_short_reference_is_used_as_is(tmp_path):
    import numpy as np
    import soundfile as sf
    from reference_text import ReferenceTranscripts

    clip = tmp_path / "nephis.wav"
    sf.write(str(clip), np.zeros(5 * 16000, dtype=np.float32), 16000)
    clip.with_suffix(".txt").write_text("Exact words.", encoding="utf-8")
    assert ReferenceTranscripts(tmp_path / "cache").fitted(clip, "b" * 64, max_seconds=18) ==         (str(clip), "Exact words.")


def test_cut_falls_back_to_word_ends_when_a_sentence_is_too_long():
    from reference_text import choose_cut

    word = lambda end, text: SimpleNamespace(end=end, word=text)
    one_long_sentence = [SimpleNamespace(start=0, end=25, text=" A very long breath.",
                                         words=[word(4, " A"), word(9, " very"), word(17, " long"),
                                                word(25, " breath.")])]
    assert choose_cut(one_long_sentence, 18) == (17.15, "A very long")
    assert choose_cut([SimpleNamespace(start=0, end=1, text=" Hi.", words=[word(1, " Hi.")])], 18) == (None, "")


def test_a_characters_usual_label_is_not_treated_as_a_mood(tmp_path):
    provider = make_provider(tmp_path, {**DIRECTION, "commanding": "[commanding]"})
    provider.baselines = {"Nephis": {"commanding"}}
    assert provider.directed(cue(actor="Nephis", emotion="commanding"), "Hold.") == "Hold."
    assert provider.directed(cue(actor="Tamar", emotion="commanding"), "Hold.") == "[commanding] Hold."
    assert provider.directed(cue(actor="Nephis", emotion="angry"), "No.") == "[angry] No."
