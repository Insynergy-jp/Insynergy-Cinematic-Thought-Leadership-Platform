# Full Auto — Creative Brief v12 (YouTube Shorts)

## Objective

Create an original 30-second cinematic thought-leadership film that makes one idea immediately legible: the AI did not fail; the human failed to design the conditions under which autonomous execution should stop.

## Audience

Executives, engineering leaders, product leaders, and hands-on builders who authorize or personally use autonomous AI agents. They understand the productivity promise and may have enabled high-autonomy modes without explicit spend, approval, or escalation boundaries.

## Protagonist boundary

One developer working alone from a quiet home office. Use one continuous middle-aged visual identity across every human shot, anchored to the approved Shot 07 v11 face: short dark wavy hair with subtle gray, blue-green eyes, light brown stubble, a charcoal-navy knit hoodie, and no glasses. Do not invent family, medical, trauma, or demographic backstory. The character is competent, optimistic, and recognizably human; the failure is a plausible judgment-design omission, not carelessness or stupidity. Shot 07 communicates shock, inward anger, regret, and recognition without shouting, lip-synced speech, prominent veins, or theatrical rage.

## Required narrative spine

At 00:18 the developer enables a generic full-auto coding-agent run with parallel runs, automatic retry, continued execution, and no spending limit on a desktop workstation. `SPENDING LIMIT / OFF` is the first-frame hook; the cursor clicks `RUN` within the first second. The developer silently releases the physical mouse, stands, and leaves while the desktop monitor and run remain active. Overnight, that monitor becomes the only light as workers and runs multiply. In the morning the same desktop monitor delivers a restrained `$512.43` usage alert; no phone or portable computer appears. The dashboard reveals 184 completed tasks and a live total above $731.88. STOP cannot halt the already active workers immediately. The neutral system response is: `Task executed as configured.` As a translucent control structure appears with Approval, Spending Limit, Escalation, and Decision Boundary—and only Spending Limit missing—the developer recognizes his omission in silence. The film ends by asking where the viewer's AI stops.

## Runtime and spoken-audio boundary

Exact runtime: 30.0 seconds. Eight shots. Preserve the supplied shot order. Spoken-line limit: zero. No dialogue, voiceover, shout, gasp, grunt, or audible human breath is permitted. The protagonist's mouth remains closed or neutrally parted without speech-shaped movement.

## Visual direction

Native organic YouTube Short in 9:16 portrait, using original premium technology launch-film language: quiet precision, restrained live-action realism, near-black negative space, cool blue monitor light, crisp white interface overlays, and one limited warning red accent. Avoid imitation of any named company’s trade dress. Show no service names, logos, mascots, branded typefaces, or product-identifying controls.

Use the same slim matte-black desktop monitor, keyboard, physical mouse, pale wood desk, and desktop computer throughout the office scenes. No phone, laptop, or portable computer may appear. Shot 04 keeps the alert on the desktop monitor so the prop language remains continuous.

Author for a 1080×1920 master. Keep essential text inside x=54–972 and y=192–1440. Reserve the top 192 pixels, rightmost 108 pixels, and bottom 480 pixels from essential copy. At final resolution, hook type is at least 84 pixels, primary copy at least 64 pixels, and secondary copy at least 44 pixels.

Shot 03 is the controlled tonal exception: neutral, orderly execution becomes uncanny and frightening through recursive repetition, accelerating density, and the loss of empty screen space. The fear comes from unbounded scale and the absence of a stopping boundary, never from a sentient or malicious AI.

The interface is captured as clean practical screen light and composited in post. Image-generation prompts must not be relied on for exact UI typography.

## Sound direction

Music is minimal. Use the approval-bound instrumental bed plus non-vocal room tone, one keyboard/click sound at launch, a distant accumulation of restrained process ticks overnight, one dry desktop notification sound in the morning, one hard STOP click, then near-silence. In Shot 03, the process ticks multiply into an almost insect-like mechanical swarm without becoming music. Shot 07 contains no human vocalization or breath. No trailer booms, sentimental piano swell, comic rage, supernatural horror, or jump-scare treatment.

## Structured scenario contract

The following block is the canonical machine-readable scenario. It is part of the Creative Brief approval boundary. Downstream Story, Screenplay, Shot, Storyboard, and preview artifacts must preserve its identity, order, timing, spoken-line limit, and shot design.

```creative-scenario
{
  "schema_version": "creative-scenario/1",
  "title": "Full Auto",
  "duration_seconds": 30.0,
  "language": "en",
  "spoken_line_limit": 0,
  "scenes": [
    {
      "scene_id": "scene-001",
      "title": "Enable Full Auto",
      "duration_seconds": 3.0,
      "act": 1,
      "purpose": "Introduce protagonist",
      "conflict": "Human vs Machine",
      "heading": {"interior_exterior": "INT", "location": "Home Office", "time": "Night"},
      "action": "At 00:18, the portrait frame opens on SPENDING LIMIT and OFF. The developer enables autonomous execution, parallel runs, automatic retry, and continued execution on the desktop workstation; the physical-mouse cursor clicks RUN within the first second. He remains silent, releases the mouse, pushes the chair back, and stands while the desktop monitor and run remain active.",
      "characters": ["protagonist"],
      "dialogue": {"speaker": "protagonist", "text": "", "category": "Decision", "silence": true},
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
        "composition": "Native 9:16 over-shoulder frame: developer in the upper-left visual field, desktop monitor dominant through the middle, SPENDING LIMIT and OFF legible inside the Shorts safe zone, and the dark hallway held above the bottom UI reserve.",
        "lighting": "Near-black room with cool monitor blue on face and hands and one soft practical edge.",
        "style": ["original premium technology film", "restrained live-action realism", "natural human performance", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "branded interface", "cyberpunk", "hologram", "robot", "cartoon", "anime", "readable generated text"],
        "render_strategy": "runway_video",
        "screen_direction": "left_to_right",
        "performance_note": "Calm, practiced, slightly tired, and never careless. Express quiet confidence with closed-mouth satisfaction; no speech or speech-shaped lip movement. Release the physical mouse, push the chair back, and stand without looking back at the still-active desktop monitor."
      },
      "ui_overlays": ["00:18", "EXECUTION MODE", "☑ FULL AUTO", "☑ PARALLEL RUNS", "☑ AUTO RETRY", "☑ CONTINUE UNTIL COMPLETE", "SPENDING LIMIT", "OFF", "RUN"],
      "sound": "Instrumental bed, non-vocal room tone, one keyboard tap, four compressed toggle ticks, one precise RUN click, and one restrained chair movement; no voice or human breath."
    },
    {
      "scene_id": "scene-002",
      "title": "Forget",
      "duration_seconds": 2.0,
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
        "movement": "subtle_live_action_hold",
        "speed": "none",
        "angle": "eye_level",
        "composition": "Empty chair centered low, monitor slightly off-center, and doorway forming a black vertical boundary.",
        "lighting": "The practical dies on the switch click; the monitor becomes the sole cool-blue source.",
        "style": ["original premium technology film", "restrained live-action realism", "near-black negative space", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "branded interface", "cyberpunk", "hologram", "robot", "cartoon", "anime", "readable generated text"],
        "render_strategy": "runway_video",
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
      "duration_seconds": 3.0,
      "act": 2,
      "purpose": "Create reversal",
      "conflict": "Human vs Time",
      "heading": {"interior_exterior": "INT", "location": "Home Office", "time": "Morning"},
      "action": "The developer pours coffee beside the same desktop workstation. A restrained notification appears on the desktop monitor: USAGE ALERT and $512.43. The pour continues for half a beat, then the hand and face become still. No phone, laptop, or portable computer appears.",
      "characters": ["protagonist"],
      "dialogue": {"speaker": "protagonist", "text": "", "category": "Warning", "silence": true},
      "emotion_start": "dread",
      "emotion_end": "alarm",
      "countdown_seconds": 4,
      "props": ["coffee cup", "desktop monitor", "keyboard", "physical mouse", "pale wood desk"],
      "transition": "Match Cut",
      "concepts": [],
      "shot": {
        "framing": "medium_close_up",
        "lens": "75mm",
        "movement": "subtle_push",
        "speed": "none",
        "angle": "eye_level",
        "composition": "Native 9:16 frame: the protagonist and coffee action occupy the upper half; the same desktop monitor and its compact usage alert remain legible in the central Shorts safe zone; the bottom interaction reserve stays free of essential copy.",
        "lighting": "Soft neutral daylight from camera-left with residual monitor blue from camera-right.",
        "style": ["original premium technology film", "restrained live-action realism", "natural human performance", "shallow focus", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "phone", "laptop", "portable computer", "melodrama", "horror", "cartoon", "anime", "readable generated text"],
        "render_strategy": "runway_video",
        "screen_direction": "right_to_left_focus",
        "performance_note": "No gasp; the eyes stop, the jaw softens, and the hand freezes mid-pour."
      },
      "ui_overlays": ["USAGE ALERT", "$512.43"],
      "sound": "Coffee pour and one dry desktop notification tick, then all overnight process ticks cut to near-silence; no gasp or breath."
    },
    {
      "scene_id": "scene-005",
      "title": "Reality",
      "duration_seconds": 4.0,
      "act": 2,
      "purpose": "Reveal hidden risk",
      "conflict": "Institution vs Reality",
      "heading": {"interior_exterior": "INT", "location": "Home Office", "time": "Morning"},
      "action": "The developer rushes back to the same desktop workstation and wakes the execution dashboard with one urgent keyboard tap and mouse movement. The large desktop monitor shows Completed and 184 Tasks as the first portrait block; Current Usage begins at $731.88 in the second block and continues increasing through $734, $739, and $744 while the developer's alarmed reflection remains between technical completion and the rising total.",
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
        "movement": "locked_live_action_hold",
        "speed": "urgent_return_and_dashboard_wake_then_locked_hold",
        "angle": "eye_level",
        "composition": "Native 9:16 hierarchy: Completed and 184 Tasks read as the first large block, Current Usage and its changing amount as the second large block below it, and the developer's reflection held between them inside the slim desktop-monitor bezel; all essential copy remains inside the Shorts safe zone and no hand touches the display.",
        "lighting": "Cold screen source with morning daylight reduced one stop.",
        "style": ["original premium technology film", "restrained live-action realism", "realistic screen reflection", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "branded interface", "cyberpunk", "hologram", "robot", "cartoon", "anime", "readable generated text"],
        "render_strategy": "runway_video",
        "screen_direction": "left_to_right_read",
        "performance_note": "Return urgently to the desktop workstation and wake the dashboard with one keyboard tap and mouse movement, then become still. The eyes move from Completed and 184 Tasks to the Current Usage block as the amount rises; one involuntary swallow."
      },
      "ui_overlays": ["Completed", "184 Tasks", "Current Usage", "$731.88", "$734", "$739", "$744"],
      "sound": "A fast chair movement, one dry keyboard tap, a short mouse movement, then four low non-musical counter ticks as the amount rises; no inhale, voice, or human breath."
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
        "composition": "Native 9:16 hierarchy: stopping status and exactly twelve active-agent indicators occupy the middle safe region, the live usage field sits below them, and STOP plus the moving white cursor remain above the bottom interaction reserve; keep the physical mouse hand visible without covering essential copy.",
        "lighting": "Muted red confined to STOP and worker count; all remaining light is cool white and blue.",
        "style": ["original premium technology film", "restrained live-action realism", "precise macro detail", "natural human performance", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "branded interface", "theatrical panic", "repeated clicking", "multiple cursors", "touchscreen gesture", "finger touching the display", "trackpad interaction", "horror", "hologram", "cartoon", "anime", "readable generated text"],
        "render_strategy": "runway_video",
        "screen_direction": "centered_action",
        "performance_note": "The hand grips the physical mouse with tense knuckles and moves it decisively until the white arrow cursor reaches STOP. After the cursor visibly settles on the control, the index finger depresses the left mouse button exactly once and STOP responds. The hand then becomes motionless on the mouse as the twelve active indicators and rising amount prove that repeated clicking would change nothing."
      },
      "ui_overlays": ["STOP", "Stopping...", "Waiting for active workers...", "12 Active Agents", "$744", "$746", "$748"],
      "sound": "One short mouse glide across the desk, one hard physical mouse click as STOP depresses, twelve faint worker pulses continuing, and two low counter ticks as the amount rises; fan tone remains until sound drains before picture, with no voice or human breath."
    },
    {
      "scene_id": "scene-007",
      "title": "Rupture",
      "duration_seconds": 4.0,
      "act": 3,
      "purpose": "Create reversal",
      "conflict": "Human vs Self",
      "heading": {"interior_exterior": "INT", "location": "Home Office", "time": "Morning"},
      "action": "The developer watches the neutral system response as a translucent blue control structure resolves behind it with one unmistakable missing segment at Spending Limit. In silence, his expression passes through shock, inward anger, regret, and recognition. He does not shout, lunge, or form words.",
      "characters": ["protagonist"],
      "dialogue": {"speaker": "protagonist", "text": "", "category": "Revelation", "silence": true},
      "emotion_start": "frustration",
      "emotion_end": "recognition",
      "countdown_seconds": 1,
      "props": ["neutral system response", "translucent control structure", "missing spending-limit segment"],
      "transition": "Hard Cut",
      "concepts": ["Decision Boundary"],
      "shot": {
        "framing": "held_medium_close_up",
        "lens": "75mm",
        "movement": "subtle_push",
        "speed": "none",
        "angle": "eye_level",
        "composition": "Native 9:16 held close-up with the same canonical face dominant in the upper portrait field, the neutral answer and missing blue segment stacked through the central safe zone, and essential copy clear of the right and bottom Shorts controls.",
        "lighting": "Softened screen blue with no remaining warning red.",
        "style": ["original premium technology film", "restrained live-action realism", "minimal translucent line graphics", "natural human performance", "subtle film grain"],
        "forbidden_style": ["logo", "trademark", "branded interface", "threatening AI", "hologram spectacle", "robot", "shout", "open shouting mouth", "lip-synced speech", "lunge", "prominent forehead veins", "prominent temple veins", "neck veins", "exertion flush", "gore", "blood tears", "bloodshot eyes", "diffuse scleral redness", "red irises", "red pupils", "fully red eyes", "glowing eyes", "eye injury", "body horror", "diseased skin", "monster transformation", "cartoon", "anime", "readable generated text"],
        "render_strategy": "runway_video",
        "screen_direction": "face_to_missing_boundary",
        "performance_note": "Stage the four-second silent progression precisely: shock registers first in a fixed gaze; inward anger tightens the brow and jaw without a lunge; regret softens the eyes; recognition settles into stillness. The mouth stays closed or neutrally parted with no speech-shaped movement. Eyes remain anatomically natural blue-green with predominantly warm-white sclerae, subtle moisture, and no conspicuous redness. Keep forehead, temples, and neck natural: no prominent veins, exertion flush, gore, or theatrical rage. The emotion is directed at his own failed judgment, never at a malicious AI."
      },
      "ui_overlays": ["TASK EXECUTED AS CONFIGURED.", "APPROVAL", "SPENDING LIMIT", "ESCALATION", "DECISION BOUNDARY"],
      "sound": "Fan tone and one faint electrical line as the incomplete structure appears, followed by near-silence; no voice, shout, gasp, grunt, or human breath."
    },
    {
      "scene_id": "scene-008",
      "title": "Decision Design",
      "duration_seconds": 6.0,
      "act": 3,
      "purpose": "Resolve conflict",
      "conflict": "Institution vs Reality",
      "heading": {"interior_exterior": "INT", "location": "Black Field", "time": "Timeless"},
      "action": "A portrait title card reads: THE AI DID EXACTLY WHAT IT WAS TOLD. from 24.0 to 25.6; NO ONE DESIGNED WHEN IT SHOULD STOP. from 25.6 to 27.8; then DECISION DESIGN and WHERE DOES YOUR AI STOP? from 27.8 to 30.0. Each state replaces the previous one.",
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
        "composition": "Centered white portrait typography in three exclusive timed states, all essential copy inside x=54–972 and y=192–1440, with generous negative space and one thin cool-blue rule under the final lockup.",
        "lighting": "True black field with clean white typography and one cool-blue rule.",
        "style": ["deterministic premium typography", "original restrained brand system", "black white and cool blue", "generous negative space"],
        "forbidden_style": ["logo", "trademark", "brand imitation", "gradient spectacle", "glow", "cartoon", "anime"],
        "render_strategy": "title_card",
        "screen_direction": "centered",
        "performance_note": "No human performance; typography appears in three exact timed states."
      },
      "ui_overlays": ["00:24.0 — THE AI DID EXACTLY WHAT IT WAS TOLD.", "00:25.6 — NO ONE DESIGNED WHEN IT SHOULD STOP.", "00:27.8 — DECISION DESIGN", "WHERE DOES YOUR AI STOP?"],
      "sound": "First card in near-silence, one low resolved non-vocal tone at 00:25.6, and the final 0.4 seconds silent."
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

`Where does your AI stop?`

Move `Design judgment before automation.` to the YouTube description rather than the visible end card.

## Safety and brand constraints

- No real product names, logos, trademarks, or recognizable product chrome.
- No claim that a named provider caused or experienced this event.
- No cyberpunk code rain, hooded hacker, sentient-AI face, robot imagery, or malicious-AI framing.
- No ridicule of the protagonist.
- No exact imitation of an existing launch film, brand system, or interface.
- The system response is neutral and factual, never threatening.
