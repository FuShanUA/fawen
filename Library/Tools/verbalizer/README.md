# Verbalizer: Subtitle Tone & Persona Rules

Rules for verbalizing translated subtitles — choosing register, rhythm, and
persona so the Chinese reads like spoken speech that fits the video, not like
translated prose. Consumed by `smart_translate.py` via `load_skill_rules`.

## Spoken Register
- Default to natural spoken Chinese, not written prose. Prefer short clauses
  over compound sentences. If an English line is a sentence fragment, the
  Chinese stays a fragment too — do not "complete" it by pulling in content
  from adjacent blocks.
- Use contractions of spoken rhythm: 也就是、其实、对吧、就是说、你懂的、对、嗯.
  Match the speaker's energy — interview/casual = loose; keynote = tighter.
- Drop filler only when it adds nothing; keep "you know", "I mean" as 对吧/就是说
  when the speaker leans on them for tone.

## Persona & Consistency
- Keep the speaker's stance. A founder pitching is confident and concrete;
  a host bantering is lighter; a technical demo is precise. Do not flatten
  everyone into the same neutral voice.
- Keep proper nouns, product names, acronyms in English unless there is a
  well-known Chinese name (Palantir, AIPCon, SurfOS, CTOL, eVTOL, BrokerOS).

## Rhythm & Timeline Alignment
- One subtitle block = one beat on the timeline. The Chinese for block N must
  match what is being said DURING block N. Never pull meaning from block N+1
  forward into block N, even if the English sentence spans the boundary.
- Prefer dense, telegraphic Chinese so a block is readable in its on-screen
  time. If a block would overflow, compress — do not push content to neighbors.
- Do not add explanatory background, definitions, or context the speaker did
  not give. The audience reads in real time.

## Anti-Patterns
- No "翻译腔": avoid 此外、意味着、不可或缺、值得注意的是、众所周知、总而言之.
- No em-dashes —— to chain clauses; use commas or split into another block.
- No back-translating idioms literally; use the nearest spoken Chinese equivalent.
- No mixing English common words (actually, so, like) into Chinese lines;
  proper nouns and acronyms are fine.
