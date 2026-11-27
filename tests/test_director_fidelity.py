import json
import pytest
from epub_parser import _strip_html
from llm_director import _parse_labels, LLMDirector
from performance_score import compile_score
from spoken_text import normalize_text
from segmenter import segment_chunk

def test_inline_text_and_stat_blocks_survive_import():
    _, paragraphs = _strip_html(b"<p>Sun<em>less</em> couldn<i>'t</i> wait.<br/>Go.</p><p>[42/100]</p><p>***</p>")
    assert paragraphs == ["Sunless couldn't wait. Go.", "[42/100]"]

def test_reject_ambiguous_indices_and_missing_speakers():
    base = {"i": 0, "speaker": "Sunny", "emotion": "neutral"}
    for rows in ([base,base], [base,dict(base,i=2)], [{"i":0}], [dict(base,i=False)]):
        with pytest.raises(ValueError):
            _parse_labels(json.dumps({"labels": rows}),1)

def test_saved_edit_changes_only_spoken_text_and_take(tmp_path):
    from state_manager import StateManager
    sm = StateManager(tmp_path/"sample.db")
    project=sm.seed_project({"source_epub":"audit.epub","total_chapters":1,"chapters":[{"chapter_index":0,"title":"A","chunks":[]}]})
    cid=sm.get_all_chapters(project)[0]["id"]
    sm.save_diarized_lines(cid,[{"line_index":0,"speaker":"Sunny","text":"Book wording."}])
    ref=tmp_path/"ref.wav";ref.write_bytes(b"reference")
    def cue():
        return compile_score(sm.get_lines_for_chapter(cid),{"Sunny":{"path":str(ref)}},{})[0]
    before=cue()
    sm.queue_recording(cid,0,reading="Corrected reading.")
    assert cue().source==before.source and cue().spoken=="Corrected reading." and cue().key("r")!=before.key("r")
    sm.queue_recording(cid,0,"Sunny")
    assert cue().spoken=="Corrected reading."
    sm.queue_recording(cid,0,reading="")
    assert cue().spoken==before.spoken

def test_attribution_does_not_assign_next_speaker_to_a_question():
    from pathlib import Path
    director=LLMDirector(Path("test.gguf"),None)
    rows=[{"kind":"prose","text":"Sunny asked:"},{"kind":"dialogue","text":"Are you ready?","speaker":"Effie"},{"kind":"prose","text":"Jet replied:"},{"kind":"dialogue","text":"Always.","speaker":"Kai"}]
    director._apply_explicit_attributions(rows)
    assert [r["speaker"] for r in rows if r["kind"]=="dialogue"]==["Sunny","Jet"]

def test_recovered_real_book_thought_and_spoken_typos():
    seg=segment_chunk("Sunny let out a mental sigh of relief.\n\n'It's alright... she's safe!")
    assert seg[1]["kind"]=="thought" and seg[1]["text"]=="It's alright... she's safe!"
    assert normalize_text("Jet chuckded.")=="Jet chuckled."


def test_manual_speaker_and_reading_survive_redirection(tmp_path):
    from state_manager import StateManager
    sm = StateManager(tmp_path / "sample.db")
    project = sm.seed_project({"source_epub":"audit.epub","total_chapters":1,
                               "chapters":[{"chapter_index":0,"title":"A","chunks":[]}]})
    cid = sm.get_all_chapters(project)[0]["id"]
    lines = [{"line_index":0,"speaker":"Sunny","text":"Book words."}]
    sm.save_diarized_lines(cid, lines)
    sm.queue_recording(cid, 0, "Nephis", "Spoken words.")
    sm.save_diarized_lines(cid, lines)
    row, = sm.get_lines_for_chapter(cid)
    assert row["speaker"] == "Nephis"
    assert row["speaker_locked"] == 1
    assert row["spoken_override"] == "Spoken words."
    # A repaired source segment before this one changes its index.
    sm.save_diarized_lines(cid, [{"line_index":0,"speaker":"Narrator","text":"An earlier line."},
                                 {"line_index":1,"speaker":"Sunny","text":"Book words."}])
    row = sm.get_lines_for_chapter(cid)[1]
    assert row["speaker"] == "Nephis" and row["spoken_override"] == "Spoken words."


def test_gemma_receives_the_director_instructions():
    from pathlib import Path
    class Model:
        def create_chat_completion(self, **kwargs):
            messages = kwargs["messages"]
            assert len(messages) == 1 and messages[0]["role"] == "user"
            assert "Sunny" in messages[0]["content"] and "Label this" in messages[0]["content"]
            return {"choices":[{"message":{"content":'{"labels":[]}'}}]}
    director = LLMDirector(Path("gemma-3.gguf"), None)
    director._llm = Model()
    assert director._call_llm("Label this") == '{"labels":[]}'


def test_directed_interruption_and_thought_keep_source_order_and_attribution(tmp_path):
    from pathlib import Path
    from state_manager import StateManager

    text = '"Rain, wait—" Jet said. "Listen to me."\n\nRain thought to herself.\n\n\'I can hear her.'
    sm = StateManager(tmp_path / "scene.db")
    project = sm.seed_project({
        "source_epub": "audit.epub", "total_chapters": 1,
        "chapters": [{"chapter_index": 0, "title": "Scene", "chunks": [
            {"chunk_index": 0, "text": text, "word_count": len(text.split())},
        ]}],
    })
    chapter = sm.get_all_chapters(project)[0]["id"]
    director = LLMDirector(Path("test.gguf"), sm)
    speakers = ["Rain", "Narrator", "Rain", "Narrator", "Rain"]
    director._call_llm = lambda *_args, **_kwargs: json.dumps({"labels": [
        {"i": index, "speaker": speaker, "emotion": "neutral"}
        for index, speaker in enumerate(speakers)
    ]})
    director.process_chapter(chapter)
    lines = sm.get_lines_for_chapter(chapter)
    assert [(line["text"], line["kind"], line["speaker"]) for line in lines] == [
        ("Rain, wait—", "dialogue", "Jet"),
        ("Jet said.", "prose", "Narrator"),
        ("Listen to me.", "dialogue", "Jet"),
        ("Rain thought to herself.", "prose", "Narrator"),
        ("I can hear her.", "thought", "Rain"),
    ]
    assert lines[0]["attribution"] == lines[2]["attribution"] == {
        "method": "explicit", "cue_indices": [1],
    }
    assert lines[4]["attribution"] == {"method": "inferred", "cue_indices": []}
    assert "closing quote is missing" in lines[4]["review_reason"]

    sm.queue_recording(chapter, 2, speaker="Nephis", reading="Listen.")
    director.process_chapter(chapter)
    line = sm.get_lines_for_chapter(chapter)[2]
    assert line["speaker"] == "Nephis"
    assert line["spoken_override"] == "Listen."
    assert line["attribution"] == {"method": "manual", "cue_indices": []}


def test_gold_labels_distinguish_repeated_source_cues():
    from scripts.evaluate_director import gold_indices

    source = segment_chunk('"Yes," Jet said. "Yes," Rain answered.')
    with pytest.raises(ValueError, match="provide line_index"):
        gold_indices([{"text": "Yes,", "speaker": "Jet"}], source)
    assert gold_indices([
        {"text": "Yes,", "speaker": "Jet", "line_index": 0},
        {"text": "Yes,", "speaker": "Rain", "line_index": 2},
    ], source) == [0, 2]
