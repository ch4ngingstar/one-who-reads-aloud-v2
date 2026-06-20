# Listening Protocol (human A/B scoring)

Objective metrics (WER, prosody deltas, speaker similarity) catch *measurable*
problems, but **naturalness** is a human-ear call. Use this sheet to settle what
the numbers can't — especially before locking any emotion-vector retune.

## How to run

1. Generate the probe clips: `python scripts/eval_emotion.py --ref <voice.wav>`.
   Clips land in `docs/eval_emotion_clips/<emotion>/probe_NN.wav`.
2. For each pair below, listen to **A** then **B** blind (don't look at which is which),
   score 1–5, then reveal.
3. A change is accepted only if it wins on emotion-fit **without** losing naturalness
   or character-fit (and the objective gate from `eval_all` also passes).

## Scoring scale (1–5)

| Dimension | 1 | 3 | 5 |
|-----------|---|---|---|
| Naturalness | robotic / artefacts | acceptable | indistinguishable from human |
| Emotion-fit | wrong / absent | present but mild | clearly the intended emotion |
| Character-fit | wrong voice | close | unmistakably this character |
| Artefacts | constant | occasional | none |

## A/B matrix — emotion presence

For each emotion tag, A = forced-neutral baseline, B = the emotion vector, same
sentence + same reference voice. A tag flagged **inert** by `eval_emotion.py`
should sound *the same* here — confirm by ear, then it's a retune target.

| Emotion | Natural (B) | Emotion-fit (B) | Character-fit (B) | A≈B? (inert) | Verdict |
|---------|:-----------:|:---------------:|:-----------------:|:------------:|---------|
| whispers   |  |  |  |  |  |
| angry      |  |  |  |  |  |
| sad        |  |  |  |  |  |
| excited    |  |  |  |  |  |
| commanding |  |  |  |  |  |
| frightened |  |  |  |  |  |
| confused   |  |  |  |  |  |
| pleading   |  |  |  |  |  |
| cold       |  |  |  |  |  |
| laughing   |  |  |  |  |  |
| sarcastic  |  |  |  |  |  |
| desperate  |  |  |  |  |  |

## A/B matrix — roster voice candidates

When adding/replacing a character voice, A = current voice, B = candidate clip.

| Character | Natural (B) | Character-fit (B) | Keep A or B? | Notes |
|-----------|:-----------:|:-----------------:|:------------:|-------|
|           |  |  |  |  |

## Sign-off

- [ ] Emotion retune approved by ear (note which tags changed): ____________________
- [ ] Roster voice changes approved: ____________________
- [ ] Objective gate (`eval_all`) re-run clean after changes: ____________________
