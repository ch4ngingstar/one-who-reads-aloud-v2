"""The labelling pipeline's deterministic parts: text, segments, evidence, import."""
import json

from attribution_evidence import gather, vocatives
from character_bible import Bible
from label_import import build_lines, stand_in
from qwen_labeller import _final, gate_emotion
from segmenter import segment_chunk
from text_cleanup import scrub


def kinds(text):
    return [(s["kind"], s["text"], s.get("hint")) for s in segment_chunk(text)]


# ── segmentation: every quote shape measured in volumes 8-11 ──────────────────

def test_guillemets_are_quotes_whose_kind_the_labeller_decides():
    assert kinds("«Yes, He is.»") == [("dialogue", "Yes, He is.", ["guillemets"])]


def test_mixed_quote_marks_still_make_one_quote():
    assert kinds("'Come! Come with me, beast!\"") == [("thought", "Come! Come with me, beast!", ["mixed-quotes"])]
    assert kinds('"What is it?\'')[0][:2] == ("dialogue", "What is it?")


def test_unclosed_quote_runs_to_the_paragraph_end_and_a_lone_mark_opens_nothing():
    assert kinds('He said: "Soon. You can sense it.') == [
        ("prose", "He said:", None), ("dialogue", "Soon. You can sense it.", ["unclosed"])]
    assert kinds('A damaged passage with a " mark.')[0][0] == "prose"


def test_scraper_glitches_around_quotes_are_recovered():
    assert kinds('Sunny smiled."This one time." He laughed.')[1] == ("dialogue", "This one time.", None)
    assert kinds('*Or you can share your worries." He chuckled.')[0][:2] == ("dialogue", "Or you can share your worries.")
    assert kinds("«…Oh, no.")[0][1] == "…Oh, no."


def test_apostrophes_and_plural_possessives_never_open_thoughts():
    assert kinds("The guards' weapons gleamed in Sunny's hand near the soldiers' camp.")[0][0] == "prose"
    assert kinds("'We are low on coffee. I'll go, won't I?'") == [
        ("thought", "We are low on coffee. I'll go, won't I?", None)]


def test_bracket_messages_inside_narration_become_their_own_line():
    assert kinds("Cassie took a deep breath. [So, the thing is... I am dead...]") == [
        ("prose", "Cassie took a deep breath.", None),
        ("system", "[So, the thing is... I am dead...]", ["inline-bracket"])]
    # An ability name mid-sentence stays narration, and its "my" is not the narrator talking.
    assert kinds("Sunny activated [Where is my eye?].") == [("prose", "Sunny activated [Where is my eye?].", None)]


def test_narration_that_says_i_or_you_is_flagged_as_a_lost_quote():
    assert kinds("You probably don't remember me.") == [("prose", "You probably don't remember me.", ["first-person"])]
    assert kinds("It was his own voice.")[0][2] is None


# ── watermarks ────────────────────────────────────────────────────────────────

def test_disguised_site_watermarks_are_removed_and_the_story_is_kept():
    assert scrub('"So where do the stars point?" Tʜe sourcᴇ of thɪs content ɪs NoveI~Fire.net') == \
        '"So where do the stars point?"'
    assert scrub("Jet jumped to her feet. Official source is novel·fire·net") == "Jet jumped to her feet."
    assert scrub('"Elly."n/o/vel/b//in dot c//om') == '"Elly."'
    assert scrub("Is it fun? lіght~nоvel~world~c`о/m. Who gave you the right?") == \
        "Is it fun? Who gave you the right?"
    assert scrub("eBook from 9Kafe") == ""
    assert scrub("The light of the world was dim.") == "The light of the world was dim."


# ── evidence ──────────────────────────────────────────────────────────────────

def bible(tmp_path):
    path = tmp_path / "characters.json"
    path.write_text(json.dumps({"characters": {
        "Sunny": {"gender": "male", "aliases": ["Master Sunless"]},
        "Nephis": {"gender": "female", "aliases": ["Changing Star"]},
        "Effie": {"gender": "female", "aliases": []},
        "Kim": {"gender": "female", "aliases": []},
        "Rain": {"gender": "female", "aliases": [], "often_with": ["Sunny"]},
    }}), encoding="utf-8")
    return Bible.load(path)


def evidence_for(b, text):
    segments = segment_chunk(text, include_paragraph=True)
    return segments, gather(b, segments)


def test_a_pronoun_introduction_constrains_gender_and_finds_the_antecedent(tmp_path):
    b = bible(tmp_path)
    segments, ev = evidence_for(b, "Sunny looked away. Nephis studied the map.\n\n"
                                   "Finally, she said in an even tone:\n\n\"The war is inevitable.\"")
    quote = ev[segments[-1]["index"]]
    assert quote.gender == "female" and quote.tag is None
    assert quote.antecedents[0] == "Nephis"


def test_named_tags_beats_vocatives_and_self_introductions(tmp_path):
    b = bible(tmp_path)
    segments, ev = evidence_for(b, '"Wait," Effie said.\n\nNephis frowned.\n\n"Sunny, are you here?"\n\n'
                                   '"I am Awakened Kim."')
    quotes = [ev[s["index"]] for s in segments if s["kind"] == "dialogue"]
    assert quotes[0].tag == "Effie"
    assert quotes[1].beat == "Nephis" and quotes[1].vocatives == ["Sunny"]
    assert quotes[2].tag == "Kim" and quotes[2].tag_source == "self"


def test_unnamed_groups_and_hidden_companions_reach_the_candidates(tmp_path):
    b = bible(tmp_path)
    segments, ev = evidence_for(b, "Rain sat by the fire. The rest of the laborers were less composed.\n\n"
                                   '"No way!"')
    quote = ev[segments[-1]["index"]]
    assert "laborers" in quote.groups
    assert "Sunny" in quote.participants  # Rain's unseen teacher
    assert vocatives(b, "Thank you, Master Sunless.") == ["Sunny"]


# ── decisions ─────────────────────────────────────────────────────────────────

def test_audible_emotions_need_the_narrations_own_words():
    assert gate_emotion("laughing", ["grinned"]) == "neutral"
    assert gate_emotion("laughing", ["chuckled"]) == "laughing"
    assert gate_emotion("cold", ["hollow tone"]) == "cold"
    assert gate_emotion("sad", []) == "sad"  # changes nothing audible, so not gated


def test_votes_merge_by_majority_and_never_let_someone_else_beat_a_name():
    assert _final(["Kim", "June", "Kim"]) == "Kim"
    assert _final(["Kim", "June", "June"]) == "June"
    assert _final(["Kim", "June", "@other"]) == "Kim"
    assert _final(["@other", "@other", None]) == "@other"


def test_import_routes_uncast_speakers_to_a_gendered_stand_in():
    voices = {"Narrator": {"path": "n.wav"}, "_default": {"path": "n.wav"}, "Sunny": {"path": "s.wav"},
              "The Bureaucrat": {"path": "b.wav"}, "The Hardened Awakened": {"path": "h.wav"},
              "The Dream Realm Wanderer": {"path": "w.wav"}}
    assert stand_in("Sunny", "male", voices) is None
    assert stand_in("Kim", "female", voices) == "The Bureaucrat"
    assert stand_in("Unnamed soldier", "male", voices) == "The Hardened Awakened"
    assert stand_in("Unnamed laborer", "unknown", voices) == "The Dream Realm Wanderer"
    segments = [{"index": 0, "kind": "prose", "text": "She nodded."},
                {"index": 1, "kind": "dialogue", "text": "Welcome."}]
    labels = [{"index": 1, "kind": "speech", "speaker": "Kim", "gender": "female", "emotion": "neutral",
               "how": "agree", "votes": ["Kim", "Kim"], "review": None}]
    narration, line = build_lines(segments, labels, voices, "qwen-v1")
    assert narration["speaker"] == "Narrator" and narration["kind"] == "prose"
    assert line["speaker"] == "Kim" and line["kind"] == "dialogue"
    assert line["attribution"]["voice_as"] == "The Bureaucrat"
    assert line["attribution"]["method"] == "qwen-v1:agree"


def test_a_line_is_flagged_when_votes_split_or_the_second_opinion_disagrees():
    from label_import import review_note
    agreed = {"speaker": "Kim", "how": "agree", "votes": ["Kim", "Kim"], "options": ["Kim", "June", "@other"]}
    assert review_note({**agreed, "gemma": "Kim"}) is None
    assert "June" in review_note({**agreed, "gemma": "June"})
    assert "split" in review_note({**agreed, "how": "pair", "votes": ["Kim", "June", "Kim"]})
    unnamed = {"speaker": "Unnamed porter", "how": "agree", "votes": ["@other", "@other"],
               "options": ["Kim", "@other"]}
    assert review_note({**unnamed, "gemma": "@other"}) is None
    assert review_note({**unnamed, "gemma": "Kim"}) is not None
