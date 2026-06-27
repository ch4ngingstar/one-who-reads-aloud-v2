# ElevenLabs Voice Design prompts — clipless roster characters

Five late-cast Shadow Slave characters (**Jest, Seishan, Helie, Moonveil, Warden**)
have no reference clip, so the diarizer's output for them silently falls back to the
Narrator voice. Generate a distinct voice for each in **ElevenLabs → Voice Design
(Text-to-Voice)**, then register the clip in the pipeline.

## How to use

For each character: paste the **Description** into ElevenLabs' "Describe the voice"
box and the **Preview text** into the sample box, generate, and pick the best take.

These clips become **IndexTTS2 zero-shot reference timbres**, so each prompt is
written for a **clean, calm, neutral** read on purpose — IndexTTS2 applies its own
per-line emotion vectors, so an over-acted reference clip *hurts* cloning quality.
Aim for a **clean ~15–20 s single-speaker clip, no music or background noise**.

> Canon confidence is imperfect — if a character's gender/age/temperament is wrong,
> just edit the age/gender words in the Description.

---

## Jest — young roguish male (Bleak Brigade)

**Description**

> A young adult man in his early twenties. Bright, light timbre with a playful,
> mischievous edge. Naturally quick and expressive, but speaking here in a relaxed,
> even, conversational tone. Clear diction, a faint smirk in the voice without
> exaggeration. Clean studio recording, neutral emotion, no background noise.

**Preview text**

> Alright, let me walk you through it from the start, nice and simple. We keep to the
> shadows, we stay close to the wall, and we do not make a single sound until I give
> the word. It really isn't complicated. Watch my hands, and try not to trip over your
> own feet this time.

---

## Seishan — refined highborn lady

**Description**

> A refined woman in her late twenties to early thirties, aristocratic and composed.
> Smooth, cool, measured timbre with elegant, precise diction. Calm and self-assured,
> never rushed. Clean studio recording, neutral emotion, no background noise.

**Preview text**

> You will find that patience is its own kind of power. I have watched lesser people
> grasp for everything at once, and lose all of it just as quickly. Speak plainly, hold
> your composure, and let the others reveal their intentions first. There is no
> advantage in haste.

---

## Helie — gentle young female

**Description**

> A gentle young woman, late teens to early twenties, with a soft, warm, slightly airy
> timbre. Kind and sincere, speaking at an unhurried, soothing pace. Clear and youthful,
> with a calm, comforting tone. Clean studio recording, neutral emotion, no background
> noise.

**Preview text**

> It is alright, you can rest now. Take a slow breath, and let your shoulders fall. I
> will stay right here beside you for as long as you need. We do not have to talk about
> any of it tonight. Just close your eyes, and let everything else wait until morning.

---

## Moonveil — regal princess

**Description**

> A regal young woman, a princess in her early to mid twenties, with a clear, poised,
> faintly cool timbre. Graceful and commanding, with crisp, deliberate diction and an
> air of quiet authority. Calm and dignified. Clean studio recording, neutral emotion,
> no background noise.

**Preview text**

> You may rise. I did not summon you here to kneel and trade pleasantries. Tell me what
> you have seen, every detail of it, and leave nothing out to spare my feelings. I would
> rather hear an unpleasant truth now than a comfortable lie I must unravel later.

---

## Warden — stern older male soldier (Valor)

**Description**

> A stern, disciplined man in his late forties to fifties, with a deep, gravelly,
> resonant timbre. Authoritative and weathered — the voice of a veteran guardian and
> soldier. Speaks slowly and firmly, with measured weight behind each word. Clean studio
> recording, neutral emotion, no background noise.

**Preview text**

> Hold the line, and keep your eyes forward. I have stood watch on this wall through
> worse nights than this one, and I am still here to speak of them. You follow the orders
> you are given, you do not break formation, and you do not run. Do that, and you may
> live to see the dawn.

---

## After generating

1. Download each as a clean clip (WAV preferred; MP3 is fine).
2. Register via the UI **Voices** tab (or `POST /api/voices`) under the **exact**
   canonical names (Title Case): `Jest`, `Seishan`, `Helie`, `Moonveil`, `Warden`.
3. No code change needed — the diarizer already emits these exact names, so each
   resolves directly. (`Saint Jest`, `Princess Moonveil`, and `Warden of Valor` already
   alias to `Jest` / `Moonveil` / `Warden` in `SPEAKER_ALIASES`.)
