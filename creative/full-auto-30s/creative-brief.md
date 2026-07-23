# Full Auto — Creative Brief

## Objective

Create an original 30-second cinematic thought-leadership film that makes one idea immediately legible: the AI did not fail; the human failed to design the conditions under which autonomous execution should stop.

## Audience

Executives, engineering leaders, product leaders, and hands-on builders who authorize or personally use autonomous AI agents. They understand the productivity promise and may have enabled high-autonomy modes without explicit spend, approval, or escalation boundaries.

## Protagonist boundary

One developer working alone from a quiet home office. Use one continuous middle-aged visual identity across every human shot, anchored to the approved Shot 07 v11 face: short dark wavy hair with subtle gray, blue-green eyes, light brown stubble, a charcoal-navy knit hoodie, and no glasses. Do not invent family, medical, trauma, or demographic backstory. The character is competent, optimistic, and recognizably human; the failure is a plausible judgment-design omission, not carelessness or stupidity. The Shot 07 outburst is the character's momentary self-reproach, not the film's judgment of the character.

## Required narrative spine

At 00:18 the developer enables a generic full-auto coding-agent run with parallel runs, automatic retry, continued execution, and no spending limit on a desktop workstation. The developer releases the physical mouse, stands, and leaves while the desktop monitor and run remain active. Overnight, that monitor becomes the only light as workers and runs multiply. In the morning a small, flat, visually subordinate phone delivers a $512.43 usage alert; returning to the same desktop dashboard reveals 184 completed tasks and a live total above $731.88. STOP cannot halt the already active workers immediately. The neutral system response is: `Task executed as configured.` As a translucent control structure appears with Approval, Spending Limit, Escalation, and Decision Boundary—and only Spending Limit missing—the developer realizes the omission was his and shouts, “なんて俺はクソなんだ！” The film ends on the proposition that no one designed when the AI should stop.

## Runtime and dialogue

Exact runtime: 30.0 seconds. Eight shots. Preserve the supplied shot order. Use exactly two spoken lines in the final cut: `朝には終わってるだろ。` in Shot 01 and `なんて俺はクソなんだ！` in Shot 07. No other dialogue or voiceover is permitted.

## Visual direction

Original premium technology launch-film language: quiet precision, restrained live-action realism, near-black negative space, cool blue monitor light, crisp white interface overlays, and one limited warning red accent. Avoid imitation of any named company’s trade dress. Show no service names, logos, mascots, branded typefaces, or product-identifying controls.

Use the same slim matte-black desktop monitor, keyboard, physical mouse, pale wood desk, and desktop computer throughout the office scenes. No laptop or portable computer may appear. The Shot 04 phone lies screen-up near the lower-right desk edge, occupies less than seven percent of frame, and remains a subtle notification source rather than a hero object.

Shot 03 is the controlled tonal exception: neutral, orderly execution becomes uncanny and frightening through recursive repetition, accelerating density, and the loss of empty screen space. The fear comes from unbounded scale and the absence of a stopping boundary, never from a sentient or malicious AI.

The interface is captured as clean practical screen light and composited in post. Image-generation prompts must not be relied on for exact UI typography.

## Sound direction

Music is minimal. Use room tone, one keyboard/click sound at launch, a distant accumulation of restrained process ticks overnight, one dry notification sound in the morning, one hard STOP click, then silence. In Shot 03, the process ticks multiply into an almost insect-like mechanical swarm without becoming music. The Shot 07 line must break out of near-silence as one brief, dry, unprocessed shout, followed immediately by dead air. No trailer booms, sentimental piano swell, comic rage, supernatural horror, or jump-scare treatment.

## Structured scenario contract

The following block is the canonical machine-readable scenario. It is part of the Creative Brief approval boundary. Downstream Story, Screenplay, Shot, Storyboard, and preview artifacts must preserve its identity, order, timing, spoken-line limit, and shot design.

```creative-scenario
{
  "schema_version": "creative-scenario/1",
  "title": "Full Auto",
  "duration_seconds": 30.0,
  "language": "ja",
  "spoken_line_limit": 2,
  "scenes": [
    {
      "scene_id": "scene-001",
      "title": "Enable Full Auto",
      "duration_seconds": 3.5,
      "act": 1,
      "purpose": "Introduce protagonist",
      "conflict": "Human vs Machine",
      "heading": {"interior_exterior": "INT", "location": "Home Office", "time": "Night"},
      "action": "At 00:18, the developer enables autonomous execution, parallel runs, automatic retry, and continued execution on the desktop workstation, leaves the spending limit off, clicks RUN with the physical mouse, says with quiet satisfaction that it will be finished by morning, releases the mouse, pushes the chair back, and stands while the desktop monitor and run remain active.",
      "characters": ["protagonist"],
      "dialogue": {"speaker": "protagonist", "text": "朝には終わってるだろ。", "category": "Decision", "silence": false},
      "emotion_start": "control",
      "emotion_end": "confidence",
      "countdown_seconds": 7,
      "props": ["slim matte-black desktop monitor", "keyboard", "physical mouse", "pale wood desk"],
      "transition": "Hard Cut",
      "concepts": [],
      "shot": {
        "framing": "over_shoulder_medium_close_up",
        "lens": "50mm",
        "movement": "slow_push",
        "speed": "nearly_imperceptible",
        "angle": "eye_level",
        "composition": "Developer on the left third, monitor on the right two-thirds, dark hallway held in negative space behind.",
        "lighting": "Near-black room with cool monitor blue on face and hands and one soft practical edge.",
        "style": ["original premium technology film", "restrained live-action realism", "natural human performance", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "branded interface", "cyberpunk", "hologram", "robot", "cartoon", "anime", "readable generated text"],
        "render_strategy": "runway_video",
        "screen_direction": "left_to_right",
        "performance_note": "Calm, practiced, slightly tired, and never careless; deliver the line with quiet satisfaction, release the physical mouse, push the chair back, and stand without looking back at the still-active desktop monitor."
      },
      "ui_overlays": ["00:18", "EXECUTION MODE", "☑ FULL AUTO", "☑ PARALLEL RUNS", "☑ AUTO RETRY", "☑ CONTINUE UNTIL COMPLETE", "SPENDING LIMIT", "OFF", "RUN"],
      "sound": "Room tone, one keyboard tap, four compressed toggle ticks, one precise RUN click, the quietly satisfied Japanese line, and one restrained chair movement."
    },
    {
      "scene_id": "scene-002",
      "title": "Forget",
      "duration_seconds": 3.0,
      "act": 1,
      "purpose": "Reveal hidden risk",
      "conflict": "Human vs Time",
      "heading": {"interior_exterior": "INT", "location": "Home Office", "time": "Night"},
      "action": "The developer crosses into the hallway, switches off the room light, and exits while the monitor remains as the only blue-white rectangle beside the empty chair.",
      "characters": ["protagonist"],
      "dialogue": {"speaker": "protagonist", "text": "", "category": "Revelation", "silence": true},
      "emotion_start": "confidence",
      "emotion_end": "absence",
      "countdown_seconds": 6,
      "props": ["monitor", "empty chair", "light switch"],
      "transition": "J Cut",
      "concepts": [],
      "shot": {
        "framing": "wide",
        "lens": "35mm",
        "movement": "static",
        "speed": "none",
        "angle": "eye_level",
        "composition": "Empty chair centered low, monitor slightly off-center, and doorway forming a black vertical boundary.",
        "lighting": "The practical dies on the switch click; the monitor becomes the sole cool-blue source.",
        "style": ["original premium technology film", "restrained live-action realism", "near-black negative space", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "branded interface", "cyberpunk", "hologram", "robot", "cartoon", "anime", "readable generated text"],
        "render_strategy": "animated_still",
        "screen_direction": "left_to_right",
        "performance_note": "One clean exit without a backward glance."
      },
      "ui_overlays": ["RUN #001 STARTED"],
      "sound": "Light-switch click, three footsteps receding, low computer fan, and the first process tick beginning as a J-cut."
    },
    {
      "scene_id": "scene-003",
      "title": "The Night Never Stops",
      "duration_seconds": 4.0,
      "act": 2,
      "purpose": "Increase urgency",
      "conflict": "Institution vs Reality",
      "heading": {"interior_exterior": "INT", "location": "Monitor Interface", "time": "Night"},
      "action": "A screen-only high-speed montage flashes Creating Agent, Searching, Generating, Retry, Launching Parallel Worker, Expanding Context, and Thinking in that exact order; each state spawns more abstract agent tiles while the run counter hard-jumps from Run #18 to Run #37 to Run #96 to Run #184, ending with agents packed across the entire screen.",
      "characters": ["protagonist"],
      "dialogue": {"speaker": "protagonist", "text": "", "category": "Warning", "silence": true},
      "emotion_start": "absence",
      "emotion_end": "dread",
      "countdown_seconds": 5,
      "props": ["abstract agent tiles", "run counter", "live total field"],
      "transition": "Hard Cut",
      "concepts": [],
      "shot": {
        "framing": "orthographic_screen_montage",
        "lens": "orthographic",
        "movement": "static",
        "speed": "rapid_hard_cut_montage",
        "angle": "front_on",
        "composition": "Begin with one centered task card and end with recursively subdivided workers packed to all four edges while preserving a narrow run-counter field at upper right; empty black space visibly disappears as the shot progresses.",
        "lighting": "Black field, cool-blue rules, clean white geometry, and one muted-red retry accent.",
        "style": ["original interface motion design", "restrained systems visualization", "clean geometric hierarchy", "premium black-blue-white palette", "clinical unease", "uncanny repetition", "claustrophobic density"],
        "forbidden_style": ["logo", "trademark", "branded interface", "code rain", "cyberpunk", "hologram", "robot", "sentient face", "monster", "demonic imagery", "jump scare", "glitch chaos", "cartoon", "anime", "readable generated text"],
        "render_strategy": "motion_graphics",
        "screen_direction": "center_outward",
        "performance_note": "The system remains neutral, orderly, and technically correct. Unease grows because each clean operation produces more clean operations until the frame becomes claustrophobic; fear comes from limitless continuation, never hostility."
      },
      "ui_overlays": ["Creating Agent...", "Searching...", "Generating...", "Retry...", "Launching Parallel Worker...", "Expanding Context...", "Thinking...", "Run #18", "Run #37", "Run #96", "Run #184"],
      "sound": "One dry process tick multiplies with each agent generation into a dense, almost insect-like mechanical swarm over a low processor tone; no melody, voice, impact sting, or supernatural effect."
    },
    {
      "scene_id": "scene-004",
      "title": "Morning",
      "duration_seconds": 3.5,
      "act": 2,
      "purpose": "Create reversal",
      "conflict": "Human vs Time",
      "heading": {"interior_exterior": "INT", "location": "Home Office", "time": "Morning"},
      "action": "The developer pours coffee as one small unbranded phone lying screen-up near the lower-right desk edge vibrates once; the phone remains visually subordinate, the pour continues for half a beat, then the hand and face become still while the same desktop monitor, keyboard, and mouse remain behind.",
      "characters": ["protagonist"],
      "dialogue": {"speaker": "protagonist", "text": "", "category": "Warning", "silence": true},
      "emotion_start": "dread",
      "emotion_end": "alarm",
      "countdown_seconds": 4,
      "props": ["coffee cup", "small flat unbranded phone", "desktop monitor", "keyboard", "physical mouse", "pale wood desk"],
      "transition": "Match Cut",
      "concepts": [],
      "shot": {
        "framing": "medium_close_up",
        "lens": "75mm",
        "movement": "static",
        "speed": "none",
        "angle": "eye_level",
        "composition": "The protagonist and coffee action dominate the left two-thirds; the desktop monitor remains an unreadable blue field behind; one small flat phone occupies less than seven percent of frame near the lower-right desk edge.",
        "lighting": "Soft neutral daylight from camera-left with residual monitor blue from camera-right.",
        "style": ["original premium technology film", "restrained live-action realism", "natural human performance", "shallow focus", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "branded phone", "melodrama", "horror", "cartoon", "anime", "readable generated text"],
        "render_strategy": "animated_still",
        "screen_direction": "right_to_left_focus",
        "performance_note": "No gasp; the eyes stop, the jaw softens, and the hand freezes mid-pour."
      },
      "ui_overlays": ["USAGE ALERT", "$512.43"],
      "sound": "Coffee pour, one dry phone vibration against wood, then all overnight process ticks cut to silence."
    },
    {
      "scene_id": "scene-005",
      "title": "Reality",
      "duration_seconds": 4.0,
      "act": 2,
      "purpose": "Reveal hidden risk",
      "conflict": "Institution vs Reality",
      "heading": {"interior_exterior": "INT", "location": "Home Office", "time": "Morning"},
      "action": "The developer rushes back to the same desktop workstation and wakes the execution dashboard with one urgent keyboard tap and mouse movement. The large desktop monitor shows Completed and 184 Tasks; at the upper right, Current Usage begins at $731.88 and continues increasing through $734, $739, and $744 while the developer's alarmed reflection remains between the completion field and the rising total.",
      "characters": ["protagonist"],
      "dialogue": {"speaker": "protagonist", "text": "", "category": "Revelation", "silence": true},
      "emotion_start": "alarm",
      "emotion_end": "disbelief",
      "countdown_seconds": 3,
      "props": ["slim matte-black desktop monitor", "keyboard", "physical mouse", "completed task field", "live usage field"],
      "transition": "Hard Cut",
      "concepts": [],
      "shot": {
        "framing": "frontal_close_up_through_reflection",
        "lens": "85mm",
        "movement": "static",
        "speed": "urgent_return_and_dashboard_wake_then_locked_hold",
        "angle": "eye_level",
        "composition": "Completed and 184 Tasks on the left, Current Usage and its changing amount in the upper right, and the developer's reflection held centrally between them inside a slim desktop-monitor bezel; no hand touches the display.",
        "lighting": "Cold screen source with morning daylight reduced one stop.",
        "style": ["original premium technology film", "restrained live-action realism", "realistic screen reflection", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "branded interface", "cyberpunk", "hologram", "robot", "cartoon", "anime", "readable generated text"],
        "render_strategy": "animated_still",
        "screen_direction": "left_to_right_read",
        "performance_note": "Return urgently to the desktop workstation and wake the dashboard with one keyboard tap and mouse movement, then become still. The eyes move from Completed and 184 Tasks to Current Usage in the upper right as the amount rises; one involuntary swallow."
      },
      "ui_overlays": ["Completed", "184 Tasks", "Current Usage", "$731.88", "$734", "$739", "$744"],
      "sound": "A fast chair movement, one dry keyboard tap, a short mouse movement, one sharp inhale, then four low non-musical counter ticks as the amount rises."
    },
    {
      "scene_id": "scene-006",
      "title": "Stop",
      "duration_seconds": 4.0,
      "act": 2,
      "purpose": "Force decision",
      "conflict": "Human vs Machine",
      "heading": {"interior_exterior": "INT", "location": "Home Office", "time": "Morning"},
      "action": "The developer hurriedly grips the physical mouse and moves the on-screen arrow cursor to the restrained red STOP control. The cursor settles over STOP; the developer clicks the left mouse button once and the control visibly depresses. The screen changes to Stopping and Waiting for active workers, but an adjacent panel still shows twelve active agent indicators pulsing while only the usage total continues increasing from $744 to $746 to $748.",
      "characters": ["protagonist"],
      "dialogue": {"speaker": "protagonist", "text": "", "category": "Decision", "silence": true},
      "emotion_start": "disbelief",
      "emotion_end": "frustration",
      "countdown_seconds": 2,
      "props": ["matte-black physical mouse", "arrow cursor", "STOP control", "twelve worker indicators", "live usage total"],
      "transition": "L Cut",
      "concepts": [],
      "shot": {
        "framing": "macro_insert_to_side_profile",
        "lens": "100mm_macro",
        "movement": "locked_macro",
        "speed": "urgent_mouse_move_then_single_left_click_then_hold",
        "angle": "eye_level_insert",
        "composition": "The physical mouse and the developer's mouse hand occupy the lower foreground; STOP sits lower-left beneath one white arrow cursor, stopping and waiting status is center-left, exactly twelve active-agent indicators sit immediately beside it, and the still-rising usage field remains in the upper right; keep all consequences in one focal plane with the developer's profile at far left.",
        "lighting": "Muted red confined to STOP and worker count; all remaining light is cool white and blue.",
        "style": ["original premium technology film", "restrained live-action realism", "precise macro detail", "natural human performance", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "branded interface", "theatrical panic", "repeated clicking", "multiple cursors", "touchscreen gesture", "finger touching the display", "trackpad interaction", "horror", "hologram", "cartoon", "anime", "readable generated text"],
        "render_strategy": "runway_video",
        "screen_direction": "centered_action",
        "performance_note": "The hand grips the physical mouse with tense knuckles and moves it decisively until the white arrow cursor reaches STOP. After the cursor visibly settles on the control, the index finger depresses the left mouse button exactly once and STOP responds. The hand then becomes motionless on the mouse as the twelve active indicators and rising amount prove that repeated clicking would change nothing."
      },
      "ui_overlays": ["STOP", "Stopping...", "Waiting for active workers...", "12 Active Agents", "$744", "$746", "$748"],
      "sound": "One short mouse glide across the desk, one hard physical mouse click as STOP depresses, a shortened breath, twelve faint worker pulses continuing, and two low counter ticks as the amount rises; fan tone remains until sound drains before picture."
    },
    {
      "scene_id": "scene-007",
      "title": "Rupture",
      "duration_seconds": 4.0,
      "act": 3,
      "purpose": "Create reversal",
      "conflict": "Human vs Self",
      "heading": {"interior_exterior": "INT", "location": "Home Office", "time": "Morning"},
      "action": "The developer watches the neutral system response as a translucent blue control structure resolves behind it with one unmistakable missing segment at Spending Limit; recognizing the omission as his own, he pitches forward and shouts in a burst of anger, panic, and regret.",
      "characters": ["protagonist"],
      "dialogue": {"speaker": "protagonist", "text": "なんて俺はクソなんだ！", "category": "Revelation", "silence": false},
      "emotion_start": "frustration",
      "emotion_end": "recognition",
      "countdown_seconds": 1,
      "props": ["neutral system response", "translucent control structure", "missing spending-limit segment"],
      "transition": "Hard Cut",
      "concepts": ["Decision Boundary"],
      "shot": {
        "framing": "held_medium_close_up",
        "lens": "75mm",
        "movement": "static",
        "speed": "none",
        "angle": "eye_level",
        "composition": "Human face left, neutral answer right, and the missing blue structural segment placed precisely between them.",
        "lighting": "Softened screen blue with no remaining warning red.",
        "style": ["original premium technology film", "restrained live-action realism", "minimal translucent line graphics", "natural human performance", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "branded interface", "threatening AI", "hologram spectacle", "robot", "gore", "blood tears", "prominently bloodshot eyes", "diffuse scleral redness", "red irises", "red pupils", "fully red eyes", "glowing eyes", "eye injury", "body horror", "diseased skin", "monster transformation", "cartoon", "anime", "readable generated text"],
        "render_strategy": "animated_still",
        "screen_direction": "face_to_missing_boundary",
        "performance_note": "At the peak of the line, anger, panic, and regret collide: mouth open mid-shout, jaw and throat locked, brows compressed, shoulders pitched forward, and one hand clenched low in frame. Both eyes are widened and wet with remorse, but remain anatomically natural: the sclerae are predominantly warm white, with only two or three extremely fine, faint capillaries near the inner corners and lower outer edges; the eyelid rims are mildly pink, the irises remain natural blue-green with dark pupils, and a subtle moist sheen catches the light. There is no broad red tint across the eyes. Acute exertion raises anatomically plausible superficial veins across both temples and the upper forehead, with a pronounced right-temple vein and taut neck veins along the sternocleidomastoid; the forehead and neck are mildly flushed. The anger is directed at his own failed judgment, never at a malicious AI; keep the eyes natural and the vascular tension intense without bleeding, injury, infection, body horror, or theatrical caricature."
      },
      "ui_overlays": ["TASK EXECUTED AS CONFIGURED.", "APPROVAL", "SPENDING LIMIT", "ESCALATION", "DECISION BOUNDARY"],
      "sound": "Fan tone and one faint electrical line as the incomplete structure appears; a caught breath, then the Japanese line as one dry, unprocessed shout, followed by immediate dead air."
    },
    {
      "scene_id": "scene-008",
      "title": "Decision Design",
      "duration_seconds": 4.0,
      "act": 3,
      "purpose": "Resolve conflict",
      "conflict": "Institution vs Reality",
      "heading": {"interior_exterior": "INT", "location": "Black Field", "time": "Timeless"},
      "action": "A title card reads: THE AI DID EXACTLY WHAT IT WAS TOLD. NO ONE DESIGNED WHEN IT SHOULD STOP. DECISION DESIGN — DESIGN JUDGMENT BEFORE AUTOMATION.",
      "characters": ["protagonist"],
      "dialogue": {"speaker": "protagonist", "text": "", "category": "Revelation", "silence": true},
      "emotion_start": "recognition",
      "emotion_end": "resolve",
      "countdown_seconds": 0,
      "props": ["black field", "white typography", "thin cool-blue rule"],
      "transition": "Fade",
      "concepts": ["Decision Design"],
      "shot": {
        "framing": "full_frame_title_card",
        "lens": "none",
        "movement": "static",
        "speed": "none",
        "angle": "front_on",
        "composition": "Centered white typography in three timed states with generous negative space and one thin cool-blue rule under the final lockup.",
        "lighting": "True black field with clean white typography and one cool-blue rule.",
        "style": ["deterministic premium typography", "original restrained brand system", "black white and cool blue", "generous negative space"],
        "forbidden_style": ["logo", "trademark", "brand imitation", "gradient spectacle", "glow", "cartoon", "anime"],
        "render_strategy": "title_card",
        "screen_direction": "centered",
        "performance_note": "No human performance; typography appears in three exact timed states."
      },
      "ui_overlays": ["00:26.0 — THE AI DID EXACTLY WHAT IT WAS TOLD.", "00:27.0 — NO ONE DESIGNED WHEN IT SHOULD STOP.", "00:28.6 — DECISION DESIGN", "DESIGN JUDGMENT BEFORE AUTOMATION."],
      "sound": "First card in silence, one low resolved tone at 00:27.0, and the final 0.4 seconds silent."
    }
  ]
}
```

## Concept and end card

The concept name appears only after the human consequence is visible.

End-card copy:

`The AI did exactly what it was told.`

One second later:

`No one designed when it should stop.`

Final lockup:

`Decision Design`

`Design judgment before automation.`

## Safety and brand constraints

- No real product names, logos, trademarks, or recognizable product chrome.
- No claim that a named provider caused or experienced this event.
- No cyberpunk code rain, hooded hacker, sentient-AI face, robot imagery, or malicious-AI framing.
- No ridicule of the protagonist.
- No exact imitation of an existing launch film, brand system, or interface.
- The system response is neutral and factual, never threatening.
