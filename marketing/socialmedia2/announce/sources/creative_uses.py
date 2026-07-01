"""Creative MIDI Uses source — generates educational posts about creative MIDI applications.

Each post explains how to implement a creative MIDI use case using RaspiMIDIHub
features. The LLM matches the use case to appropriate features and writes an
engaging, educational post.
"""
import hashlib

from .. import config
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

# 100 Creative MIDI Use Cases - embedded data for educational posts
_USE_CASES = [
    {
        "id": 1,
        "title": "DMX Lighting Control",
        "description": "Control stage lighting intensity, color temperature, and effects using MIDI CC messages. Map faders to DMX channels for real-time light show control during live performances.",
        "raspimidihub_features": ["routing_matrix", "tracker", "cc_lfo"],
        "technical_notes": "Use CC 1-127 for dimmer channels, CC 16-23 for color wheels, CC 84-95 for effect parameters. Tracker can store preset scenes.",
        "example_setup": "Create tracker presets for each scene, use routing matrix to map controller faders to specific CC ranges"
    },
    {
        "id": 2,
        "title": "Smart Home Automation",
        "description": "Trigger smart home devices with MIDI controllers. Turn lights on/off, adjust thermostats, or activate appliances using MIDI messages routed through a bridge application.",
        "raspimidihub_features": ["routing_matrix", "tracker", "plugin_system"],
        "technical_notes": "CC messages can trigger IFTTT webhooks or Home Assistant APIs. Use CC on/off (0/127) for binary triggers.",
        "example_setup": "Map buttons to CC 64 (on/off), use tracker for scheduled automation sequences"
    },
    {
        "id": 3,
        "title": "Game Controller Mapping",
        "description": "Use MIDI controllers to map game actions. Trigger macros, shortcuts, or in-game commands through MIDI-to-keyboard bridge software.",
        "raspimidihub_features": ["routing_matrix", "channel_selector", "tracker"],
        "technical_notes": "CC messages translate to keyboard macros via tools like MIDI2Keys. Use different channels for different game modes.",
        "example_setup": "Channel 1 for movement, Channel 2 for actions, Channel 3 for special abilities"
    },
    {
        "id": 4,
        "title": "Presentation Slide Control",
        "description": "Control PowerPoint, Keynote, or Google Slides with MIDI foot pedals or controllers. Page through slides hands-free during presentations or lectures.",
        "raspimidihub_features": ["tracker", "routing_matrix"],
        "technical_notes": "CC 1 (next slide), CC 2 (previous slide), CC 3 (black screen). Use Note On for triggers.",
        "example_setup": "Foot pedal sends CC 1/2 for slide navigation, CC 3 for presenter mode"
    },
    {
        "id": 5,
        "title": "Video Editing Shortcuts",
        "description": "Map video editing software shortcuts to MIDI controllers. Cut, trim, play/pause, and mark in/out points with physical controls for faster editing workflow.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "Use CC for play/pause, Note On for mark in/out, CC 17-24 for timeline zoom levels.",
        "example_setup": "Assign transport controls to faders, mark points to buttons, zoom to rotary encoders"
    },
    {
        "id": 6,
        "title": "Generative Music Systems",
        "description": "Create self-generating music using RaspiMIDIHub's arpeggiators and trackers. Set up rule-based systems that produce endless variations of musical patterns.",
        "raspimidihub_features": ["arpeggiator", "euclidean", "cartesian", "cc_lfo"],
        "technical_notes": "Combine Euclidean rhythms with random note selection. Use CC LFO for parameter modulation over time.",
        "example_setup": "Euclidean for rhythm, arpeggiator for pitch selection, CC LFO for filter sweeps"
    },
    {
        "id": 7,
        "title": "Modular Synth Control",
        "description": "Use RaspiMIDIHub as a central controller for modular synthesizer setups. Route CV/Gate signals through MIDI conversion for complex patch management.",
        "raspimidihub_features": ["routing_matrix", "tracker", "cc_lfo", "plugin_system"],
        "technical_notes": "CC 1-16 for VCO pitch, CC 17-32 for VCF cutoff, CC 33-48 for VCA levels. Tracker stores patch presets.",
        "example_setup": "Multiple trackers for different patches, routing matrix for signal routing, CC LFO for modulation"
    },
    {
        "id": 8,
        "title": "Live Looping Control",
        "description": "Control loop stations and looper pedals with MIDI. Start/stop loops, overdub, and trigger samples hands-free during live performances.",
        "raspimidihub_features": ["tracker", "routing_matrix"],
        "technical_notes": "CC 64 (record/overdub), CC 65 (play/stop), CC 66 (undo/redo). Use Note On for instant triggers.",
        "example_setup": "Foot controller sends CC for loop functions, tracker for preset loop sequences"
    },
    {
        "id": 9,
        "title": "Interactive Art Installations",
        "description": "Create interactive art that responds to MIDI input. Motion sensors, touch interfaces, or musical controllers trigger visual or audio elements in real-time.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo", "plugin_system"],
        "technical_notes": "Map sensor data to CC values, use routing matrix to distribute to multiple outputs (audio, video, lighting).",
        "example_setup": "Sensor → MIDI → RaspiMIDIHub → multiple outputs (sound, light, projection)"
    },
    {
        "id": 10,
        "title": "Guitar Pedal Control",
        "description": "Control guitar effects pedals with MIDI program changes and CC messages. Switch between preset tones, adjust parameters, and automate effect sequences.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "PC messages for preset switching (0-127), CC for parameter adjustment. Use tracker for song-specific presets.",
        "example_setup": "One tracker preset per song, CC for real-time parameter tweaks during performance"
    },
    {
        "id": 11,
        "title": "Drone Control Systems",
        "description": "Use MIDI controllers to manage drone flight parameters, camera settings, or trigger aerial effects. Map faders to altitude, speed, and camera functions.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "CC 1 (altitude), CC 2 (speed), CC 3 (camera zoom), CC 4 (trigger). Requires MIDI-to-RC bridge.",
        "example_setup": "Faders for flight controls, buttons for camera triggers, tracker for pre-programmed flight paths"
    },
    {
        "id": 12,
        "title": "3D Printer Control",
        "description": "Trigger 3D printer functions or monitor progress through MIDI. Start/stop prints, change layers, or control heated bed temperature via MIDI messages.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "CC for temperature control, Note On for start/stop. Requires OctoPrint or similar API bridge.",
        "example_setup": "Buttons for print control, faders for temperature, tracker for print sequence automation"
    },
    {
        "id": 13,
        "title": "Weather-to-Music Conversion",
        "description": "Convert weather data (temperature, humidity, wind) into musical parameters. Create ambient soundscapes that reflect real-time environmental conditions.",
        "raspimidihub_features": ["cc_lfo", "arpeggiator", "plugin_system"],
        "technical_notes": "Weather API → CC values → musical parameters. Temperature maps to pitch, humidity to reverb, wind to LFO rate.",
        "example_setup": "Weather data plugin outputs CC, arpeggiator generates melody, CC LFO adds modulation"
    },
    {
        "id": 14,
        "title": "Biometric Feedback Music",
        "description": "Generate music based on biometric data (heart rate, skin conductance). Create therapeutic or meditative soundscapes that respond to the listener's state.",
        "raspimidihub_features": ["cc_lfo", "arpeggiator", "routing_matrix"],
        "technical_notes": "Biometric sensor → MIDI → RaspiMIDIHub. Heart rate maps to tempo, GSR to filter cutoff.",
        "example_setup": "Heart rate monitor → tempo sync, GSR sensor → filter modulation, EEG → note selection"
    },
    {
        "id": 15,
        "title": "Camera Shutter Control",
        "description": "Trigger camera shutters and control photography settings with MIDI. Perfect for time-lapse, long exposure, or synchronized multi-camera setups.",
        "raspimidihub_features": ["tracker", "routing_matrix"],
        "technical_notes": "CC 1 (shutter), CC 2 (focus), CC 3 (ISO), CC 4 (aperture). Use tracker for time-lapse sequences.",
        "example_setup": "Tracker for time-lapse intervals, buttons for manual triggers, CC for camera settings"
    },
    {
        "id": 16,
        "title": "Robotics Control",
        "description": "Control robotic arms, servos, or actuators through MIDI. Map controllers to joint positions, speeds, and trigger pre-programmed movements.",
        "raspimidihub_features": ["routing_matrix", "tracker", "cc_lfo"],
        "technical_notes": "CC 1-16 for joint positions, CC 17-24 for speeds. Tracker stores movement sequences.",
        "example_setup": "Faders for joint control, buttons for preset movements, CC LFO for smooth transitions"
    },
    {
        "id": 17,
        "title": "Accessibility Input Device",
        "description": "Create alternative input methods for people with disabilities. Map switches, eye-tracking, or voice commands to MIDI for computer control or instrument playing.",
        "raspimidihub_features": ["routing_matrix", "plugin_system"],
        "technical_notes": "Switch inputs → CC on/off. Eye-tracking → CC values. Voice → Note triggers via speech-to-MIDI.",
        "example_setup": "Single switch for scanning selection, eye-tracking for cursor, voice for note triggers"
    },
    {
        "id": 18,
        "title": "Therapy and Rehabilitation",
        "description": "Use MIDI for physical therapy exercises. Track range of motion, provide audio feedback, and gamify rehabilitation routines.",
        "raspimidihub_features": ["cc_lfo", "routing_matrix"],
        "technical_notes": "Motion sensors → CC values. Range of motion maps to pitch or volume for biofeedback.",
        "example_setup": "Range of motion → pitch, speed of movement → tempo, accuracy → harmonic content"
    },
    {
        "id": 19,
        "title": "Educational Music Theory",
        "description": "Visualize music theory concepts with MIDI. Show chord progressions, scales, and harmony in real-time for interactive music education.",
        "raspimidihub_features": ["arpeggiator", "euclidean", "routing_matrix"],
        "technical_notes": "Use arpeggiator for scale demonstration, Euclidean for rhythm teaching, routing for multi-output visualization.",
        "example_setup": "Scale mode for theory lessons, chord mode for harmony, rhythm mode for timing"
    },
    {
        "id": 20,
        "title": "Ensemble Synchronization",
        "description": "Synchronize multiple musicians or devices with MIDI clock. Ensure tight timing across acoustic and electronic instruments in ensemble settings.",
        "raspimidihub_features": ["routing_matrix"],
        "technical_notes": "MIDI clock output to all devices. Use Network MIDI for distributed ensembles.",
        "example_setup": "One hub as master clock, Network MIDI to distribute to remote musicians"
    },
    {
        "id": 21,
        "title": "Setlist Automation",
        "description": "Automate entire setlists with MIDI program changes. Switch patches, routing, and effects for each song with a single button press.",
        "raspimidihub_features": ["tracker", "channel_selector"],
        "technical_notes": "One tracker preset per song. PC messages trigger complete scene changes including routing and plugins.",
        "example_setup": "Foot controller advances tracker, each step loads complete song configuration"
    },
    {
        "id": 22,
        "title": "Live Coding Triggers",
        "description": "Trigger code execution or parameter changes in live coding environments. Use MIDI to control SuperCollider, TidalCycles, or other algorithmic music systems.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo"],
        "technical_notes": "CC messages map to OSC or MIDI in live coding environment. Use for real-time parameter modulation.",
        "example_setup": "CC for parameter control, Note On for trigger events, tracker for pattern sequences"
    },
    {
        "id": 23,
        "title": "Ambient Soundscapes",
        "description": "Create evolving ambient textures using RaspiMIDIHub's modulation capabilities. Generate drones, pads, and atmospheric sounds with automated parameter changes.",
        "raspimidihub_features": ["cc_lfo", "arpeggiator", "euclidean"],
        "technical_notes": "Slow CC LFO for filter sweeps, Euclidean for rhythmic modulation, arpeggiator for melodic elements.",
        "example_setup": "CC LFO at 0.1Hz for slow sweeps, Euclidean for subtle rhythmic variation"
    },
    {
        "id": 24,
        "title": "Vocal Effects Routing",
        "description": "Control vocal effects processors with MIDI. Switch reverb, delay, harmonizer presets, and adjust parameters during live vocal performances.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "PC for preset switching, CC for real-time parameter control. Use tracker for song-specific vocal setups.",
        "example_setup": "Foot controller for preset changes, hand controller for real-time tweaks"
    },
    {
        "id": 25,
        "title": "Collaborative Jam Sessions",
        "description": "Enable remote jam sessions using Network MIDI. Connect musicians across locations with low-latency MIDI over LAN/internet.",
        "raspimidihub_features": ["network_midi", "routing_matrix"],
        "technical_notes": "Network MIDI for remote connections. Each musician gets dedicated channel, clock sync for timing.",
        "example_setup": "Hub A and Hub B connected via Network MIDI, shared clock, separate channels per musician"
    },
    {
        "id": 26,
        "title": "Escape Room Puzzles",
        "description": "Create interactive escape room puzzles triggered by MIDI. Solve musical puzzles to unlock doors, reveal clues, or progress through the experience.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "Correct MIDI sequence triggers door unlock. Use tracker for puzzle state machine.",
        "example_setup": "Players input sequence via MIDI controller, correct pattern triggers relay for door unlock"
    },
    {
        "id": 27,
        "title": "Museum Exhibit Triggers",
        "description": "Trigger museum exhibit content with MIDI. Play audio, video, or lighting effects when visitors interact with exhibits.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "Touch sensor → MIDI → exhibit content. Use tracker for multi-stage interactions.",
        "example_setup": "Touch sensor sends Note On, triggers audio/video playback and lighting cues"
    },
    {
        "id": 28,
        "title": "Flight Simulator Controls",
        "description": "Map MIDI controllers to flight simulator functions. Control throttle, flaps, landing gear, and avionics with physical MIDI controllers.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "Faders for throttle/trim, buttons for discrete controls. CC messages map to simulator variables.",
        "example_setup": "Faders for continuous controls, buttons for switches, tracker for preset configurations"
    },
    {
        "id": 29,
        "title": "Racing Wheel Integration",
        "description": "Integrate MIDI with racing simulators. Map pedals, shifter, and buttons to game controls for immersive racing experience.",
        "raspimidihub_features": ["routing_matrix"],
        "technical_notes": "CC for throttle/brake, PC for gear shifts. Use routing matrix for force feedback integration.",
        "example_setup": "Pedals as CC, shifter as PC, buttons for handbrake and view changes"
    },
    {
        "id": 30,
        "title": "Interactive Storytelling",
        "description": "Create interactive narratives where MIDI input influences story progression. Choose paths, trigger scenes, or control character actions with musical input.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "Different notes/CC trigger different story branches. Use tracker for state management.",
        "example_setup": "Melodic input → story path, rhythmic input → pacing, CC → character decisions"
    },
    {
        "id": 31,
        "title": "Projection Mapping Triggers",
        "description": "Synchronize projection mapping with MIDI. Trigger visual content, transitions, and effects in perfect timing with music or performance.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "MIDI clock for timing, CC for content selection. Use tracker for show sequences.",
        "example_setup": "Clock sync for timing, CC for scene selection, tracker for automated sequences"
    },
    {
        "id": 32,
        "title": "LED Strip Control",
        "description": "Control addressable LED strips with MIDI. Create reactive lighting that responds to music or controlled manually with MIDI controllers.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo"],
        "technical_notes": "CC for brightness, color, and effects. Use CC LFO for automated patterns.",
        "example_setup": "Faders for RGB channels, CC LFO for automated patterns, tracker for presets"
    },
    {
        "id": 33,
        "title": "Laser Show Sequencing",
        "description": "Control laser show patterns and effects with MIDI. Sequence complex laser patterns synchronized to music for live performances.",
        "raspimidihub_features": ["tracker", "routing_matrix"],
        "technical_notes": "ILDA control via MIDI bridge. Tracker stores laser patterns, CC controls intensity and speed.",
        "example_setup": "Tracker for pattern sequences, CC for real-time modulation, clock sync for timing"
    },
    {
        "id": 34,
        "title": "Strobe Synchronization",
        "description": "Synchronize strobe lights with musical beats. Create dramatic visual effects that pulse in perfect time with the music.",
        "raspimidihub_features": ["euclidean", "routing_matrix"],
        "technical_notes": "Euclidean sequencer for rhythmic strobe patterns. Sync to MIDI clock for tight timing.",
        "example_setup": "Euclidean for strobe rhythm, CC for intensity, clock sync for tempo"
    },
    {
        "id": 35,
        "title": "Color Ambiance Control",
        "description": "Create mood lighting with MIDI-controlled color systems. Adjust color temperature and saturation to match musical moods or performance sections.",
        "raspimidihub_features": ["cc_lfo", "routing_matrix"],
        "technical_notes": "CC for color parameters. Use CC LFO for smooth color transitions over time.",
        "example_setup": "Faders for color parameters, CC LFO for automated transitions, tracker for presets"
    },
    {
        "id": 36,
        "title": "Theater Cue Management",
        "description": "Manage theater production cues with MIDI. Trigger lighting, sound, and stage effects at precise moments during performances.",
        "raspimidihub_features": ["tracker", "routing_matrix"],
        "technical_notes": "One tracker preset per cue. Use PC for instant cue changes, CC for real-time adjustments.",
        "example_setup": "Foot controller advances cues, each triggers complete show state"
    },
    {
        "id": 37,
        "title": "Concert Visual Synchronization",
        "description": "Synchronize concert visuals with music using MIDI clock. Ensure video content, lighting, and effects stay perfectly timed throughout the show.",
        "raspimidihub_features": ["routing_matrix"],
        "technical_notes": "MIDI clock distribution to all visual systems. Use Network MIDI for distributed setups.",
        "example_setup": "Hub as master clock, Network MIDI to remote visual systems"
    },
    {
        "id": 38,
        "title": "Club Lighting Automation",
        "description": "Automate club lighting with MIDI. Create dynamic light shows that respond to music or run pre-programmed sequences for different music styles.",
        "raspimidihub_features": ["cc_lfo", "euclidean", "routing_matrix"],
        "technical_notes": "CC LFO for reactive lighting, Euclidean for rhythmic patterns. Use tracker for style-specific presets.",
        "example_setup": "Reactive mode for live response, automated mode for pre-programmed shows"
    },
    {
        "id": 39,
        "title": "IoT Device Orchestration",
        "description": "Orchestrate multiple IoT devices with MIDI. Control smart home ecosystems, industrial sensors, or connected devices through a unified MIDI interface.",
        "raspimidihub_features": ["routing_matrix", "plugin_system"],
        "technical_notes": "MIDI-to-API bridge for IoT control. Use routing matrix to distribute commands to multiple devices.",
        "example_setup": "Central MIDI controller → routing matrix → multiple IoT APIs"
    },
    {
        "id": 40,
        "title": "Scientific Instrument Control",
        "description": "Control scientific instruments with MIDI. Trigger measurements, adjust parameters, or record data from laboratory equipment using MIDI messages.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "CC for parameter adjustment, PC for preset loading. Use tracker for experiment sequences.",
        "example_setup": "Tracker for experiment protocols, CC for real-time parameter control"
    },
    {
        "id": 41,
        "title": "Laboratory Automation",
        "description": "Automate laboratory procedures with MIDI. Control pipetting robots, incubators, or other lab equipment through MIDI-triggered sequences.",
        "raspimidihub_features": ["tracker", "routing_matrix"],
        "technical_notes": "Tracker stores protocol steps. Each step triggers specific lab equipment via MIDI-to-serial bridge.",
        "example_setup": "Step-by-step tracker for protocols, CC for parameter adjustment"
    },
    {
        "id": 42,
        "title": "Agricultural Monitoring",
        "description": "Monitor and control agricultural systems with MIDI. Track soil moisture, temperature, and trigger irrigation or climate control systems.",
        "raspimidihub_features": ["cc_lfo", "routing_matrix"],
        "technical_notes": "Sensor data → CC values. Use CC thresholds to trigger irrigation or climate control.",
        "example_setup": "Soil moisture → CC, threshold triggers irrigation, temperature → climate control"
    },
    {
        "id": 43,
        "title": "Environmental Control",
        "description": "Control environmental systems (HVAC, ventilation) with MIDI. Create automated climate control based on sensor input or schedules.",
        "raspimidihub_features": ["cc_lfo", "routing_matrix"],
        "technical_notes": "Sensor data → CC → HVAC control. Use CC LFO for gradual adjustments.",
        "example_setup": "Temperature/humidity sensors → CC, automated control via CC LFO"
    },
    {
        "id": 44,
        "title": "CNC Machine Triggers",
        "description": "Trigger CNC machine operations with MIDI. Start/stop operations, change tools, or control parameters through MIDI messages.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "PC for tool changes, CC for speed/feeds. Use tracker for operation sequences.",
        "example_setup": "Tracker for operation sequences, CC for parameter control, PC for tool changes"
    },
    {
        "id": 45,
        "title": "Car Audio Control",
        "description": "Control car audio systems with MIDI. Adjust equalizer, volume, and source selection using MIDI controllers in custom car audio installations.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo"],
        "technical_notes": "CC for EQ bands, volume, balance. Use CC LFO for automatic sound stage adjustment.",
        "example_setup": "Faders for EQ, rotary for volume/balance, CC LFO for auto-adjustment"
    },
    {
        "id": 46,
        "title": "Boat Electronics Integration",
        "description": "Integrate boat electronics with MIDI. Control navigation displays, fish finders, or audio systems from a unified MIDI controller.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "CC for display parameters, PC for preset configurations. Use tracker for activity-specific setups.",
        "example_setup": "One tracker preset per activity (fishing, cruising, docking)"
    },
    {
        "id": 47,
        "title": "Kinetic Sculpture Control",
        "description": "Control kinetic art sculptures with MIDI. Move motors, servos, and actuators to create dynamic, interactive art pieces.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo", "tracker"],
        "technical_notes": "CC for position/speed, tracker for choreographed sequences. Use CC LFO for organic movement.",
        "example_setup": "Faders for individual elements, CC LFO for organic motion, tracker for choreography"
    },
    {
        "id": 48,
        "title": "Sound Sculpture Control",
        "description": "Control sound-generating sculptures with MIDI. Trigger sound modules, adjust acoustic parameters, or create interactive sound installations.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo"],
        "technical_notes": "CC for sound parameters, Note On for triggers. Use routing matrix for multi-speaker setups.",
        "example_setup": "Spatial audio routing, CC for sound design, interactive triggers"
    },
    {
        "id": 49,
        "title": "Interactive Poetry",
        "description": "Create interactive poetry experiences with MIDI. Trigger text, audio, or visual elements based on musical input or audience interaction.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "Different notes trigger different poem sections. Use tracker for narrative flow.",
        "example_setup": "Melodic input → poem sections, rhythmic input → pacing, CC → mood"
    },
    {
        "id": 50,
        "title": "Generative Visual Art",
        "description": "Generate visual art with MIDI. Create dynamic visuals that respond to musical input or generate abstract art through algorithmic processes.",
        "raspimidihub_features": ["cc_lfo", "arpeggiator", "routing_matrix"],
        "technical_notes": "CC for visual parameters, arpeggiator for pattern generation. Map musical elements to visual output.",
        "example_setup": "Pitch → color, rhythm → motion, CC → form, arpeggiator → pattern"
    },
    {
        "id": 51,
        "title": "Speech-to-MIDI Communication",
        "description": "Convert speech to MIDI for communication aids. Allow non-verbal individuals to communicate through musical input that translates to text or commands.",
        "raspimidihub_features": ["routing_matrix", "plugin_system"],
        "technical_notes": "Speech-to-MIDI plugin outputs notes/CC. Map to vocabulary or commands.",
        "example_setup": "Different pitches → words/phrases, rhythm → sentence structure"
    },
    {
        "id": 52,
        "title": "Adaptive Instrument Control",
        "description": "Create adaptive musical instruments for people with limited mobility. Map alternative inputs to traditional instrument functions.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo"],
        "technical_notes": "Alternative inputs → MIDI. Use CC LFO for automatic assistance (auto-tune, rhythm correction).",
        "example_setup": "Single switch for scanning, eye-tracking for note selection, CC LFO for assistance"
    },
    {
        "id": 53,
        "title": "Sensory Feedback Systems",
        "description": "Create sensory feedback systems for visually or hearing impaired. Convert audio to tactile or visual feedback using MIDI as intermediary.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo"],
        "technical_notes": "Audio → MIDI → tactile/visual output. Use CC for intensity, Note On for triggers.",
        "example_setup": "Pitch → vibration pattern, volume → intensity, rhythm → flash pattern"
    },
    {
        "id": 54,
        "title": "Communication Aids",
        "description": "Build MIDI-based communication aids. Create custom communication boards or systems that use musical input for expression.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "Each note/CC maps to word/phrase. Use tracker for sentence construction.",
        "example_setup": "Note grid for vocabulary, CC for grammar, tracker for sentence building"
    },
    {
        "id": 55,
        "title": "Rehabilitation Exercises",
        "description": "Gamify rehabilitation exercises with MIDI. Track progress, provide feedback, and motivate patients through musical interaction.",
        "raspimidihub_features": ["cc_lfo", "routing_matrix"],
        "technical_notes": "Range of motion → CC values. Use musical feedback for motivation and progress tracking.",
        "example_setup": "Movement → musical output, progress tracking via CC history"
    },
    {
        "id": 56,
        "title": "Eye-Tracking Integration",
        "description": "Integrate eye-tracking with MIDI. Control musical parameters or computer functions using eye movement and gaze position.",
        "raspimidihub_features": ["routing_matrix"],
        "technical_notes": "Gaze position → CC values. Blink → Note triggers. Use routing for multi-output control.",
        "example_setup": "Horizontal gaze → CC 1, vertical → CC 2, blink → Note On"
    },
    {
        "id": 57,
        "title": "Switch Control Systems",
        "description": "Create switch-based control systems for people with limited mobility. Use single or multiple switches to control complex MIDI functions.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "Switch scanning for selection. Use tracker for hierarchical menu navigation.",
        "example_setup": "Single switch for scanning, multiple switches for direct selection"
    },
    {
        "id": 58,
        "title": "Music Theory Visualization",
        "description": "Visualize music theory concepts in real-time. Show scales, chords, and harmony as MIDI data flows through the system for educational purposes.",
        "raspimidihub_features": ["routing_matrix", "arpeggiator"],
        "technical_notes": "Route MIDI to visualization software. Use arpeggiator to demonstrate scale/chord construction.",
        "example_setup": "Input → visualization → output, arpeggiator for demonstration"
    },
    {
        "id": 59,
        "title": "Rhythm Training Tools",
        "description": "Create rhythm training exercises with MIDI. Practice timing, learn complex rhythms, and receive instant feedback on performance.",
        "raspimidihub_features": ["euclidean", "routing_matrix"],
        "technical_notes": "Euclidean for rhythm patterns. Use MIDI clock for timing reference. Track accuracy over time.",
        "example_setup": "Euclidean patterns for practice, timing feedback via CC"
    },
    {
        "id": 60,
        "title": "Ear Training Exercises",
        "description": "Build ear training exercises with MIDI. Practice interval recognition, chord identification, and melodic dictation with automated feedback.",
        "raspimidihub_features": ["arpeggiator", "routing_matrix"],
        "technical_notes": "Arpeggiator generates exercises. Compare input to expected output for scoring.",
        "example_setup": "Random intervals/chords from arpeggiator, input comparison for feedback"
    },
    {
        "id": 61,
        "title": "Composition Workshops",
        "description": "Facilitate composition workshops with MIDI. Use collaborative tools, real-time notation, and ensemble playback for group composition sessions.",
        "raspimidihub_features": ["network_midi", "routing_matrix"],
        "technical_notes": "Network MIDI for collaboration. Route each student to separate output for individual tracking.",
        "example_setup": "Each student gets channel, master mixes outputs, Network MIDI for remote participation"
    },
    {
        "id": 62,
        "title": "Interactive Lessons",
        "description": "Create interactive music lessons with MIDI. Guide students through exercises, provide real-time feedback, and track progress automatically.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo"],
        "technical_notes": "Lesson structure in tracker. CC for difficulty adjustment, feedback via musical output.",
        "example_setup": "Tracker for lesson flow, CC for adaptive difficulty, feedback through sound"
    },
    {
        "id": 63,
        "title": "Student Performance Tracking",
        "description": "Track student performance metrics with MIDI. Monitor accuracy, timing, and progress over time for objective assessment.",
        "raspimidihub_features": ["routing_matrix"],
        "technical_notes": "Log MIDI data for analysis. Extract metrics like timing accuracy, note precision, dynamics.",
        "example_setup": "Record all MIDI, analyze for metrics, generate progress reports"
    },
    {
        "id": 64,
        "title": "Music History Demos",
        "description": "Demonstrate music history concepts with MIDI. Recreate historical instruments, styles, and techniques for educational presentations.",
        "raspimidihub_features": ["tracker", "arpeggiator"],
        "technical_notes": "Tracker for period-specific patterns. Use arpeggiator to demonstrate historical styles.",
        "example_setup": "One tracker preset per historical period/style"
    },
    {
        "id": 65,
        "title": "Sound Design Labs",
        "description": "Create sound design laboratories with MIDI. Experiment with synthesis, effects, and audio processing in an educational setting.",
        "raspimidihub_features": ["cc_lfo", "routing_matrix", "plugin_system"],
        "technical_notes": "CC for parameter exploration. Use routing matrix for signal chain experimentation.",
        "example_setup": "CC for real-time parameter control, routing for signal chain design"
    },
    {
        "id": 66,
        "title": "Tempo Mapping",
        "description": "Map tempo changes across a performance. Create gradual tempo shifts, ritardandos, and accelerandos with precise MIDI control.",
        "raspimidihub_features": ["cc_lfo"],
        "technical_notes": "CC LFO for tempo modulation. Use slow rates for gradual changes, fast for dramatic effects.",
        "example_setup": "CC LFO at 0.01-0.1Hz for tempo sweeps, manual CC for instant changes"
    },
    {
        "id": 67,
        "title": "Click Track Distribution",
        "description": "Distribute click tracks to multiple musicians using MIDI clock. Ensure tight timing across ensemble with dedicated click for each player.",
        "raspimidihub_features": ["routing_matrix", "network_midi"],
        "technical_notes": "MIDI clock for timing. Use routing matrix to send click to different channels/outputs.",
        "example_setup": "Master clock, separate channels per musician, Network MIDI for remote players"
    },
    {
        "id": 68,
        "title": "In-Ear Monitor Control",
        "description": "Control in-ear monitor mixes with MIDI. Adjust individual musician mixes, cue levels, and effects during live performances.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo"],
        "technical_notes": "CC for mix levels, routing for signal distribution. Use CC LFO for automated mix changes.",
        "example_setup": "Faders for mix levels, CC for effects, automated changes via CC LFO"
    },
    {
        "id": 69,
        "title": "Backline Management",
        "description": "Manage backline equipment with MIDI. Control amplifiers, cabinets, and effects units for seamless instrument changes during performances.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "PC for preset changes, CC for real-time adjustments. Use tracker for song-specific setups.",
        "example_setup": "One tracker preset per song, PC triggers complete backline configuration"
    },
    {
        "id": 70,
        "title": "Tour Logistics",
        "description": "Manage tour logistics with MIDI. Control show files, venue presets, and equipment configurations for consistent performances across tour dates.",
        "raspimidihub_features": ["tracker", "routing_matrix"],
        "technical_notes": "Tracker for venue-specific configurations. Use PC for quick venue changes.",
        "example_setup": "One tracker preset per venue, quick load via PC"
    },
    {
        "id": 71,
        "title": "Improvisation Aids",
        "description": "Create improvisation assistance tools with MIDI. Generate backing tracks, suggest harmonies, or provide real-time musical guidance for improvisers.",
        "raspimidihub_features": ["arpeggiator", "euclidean", "cc_lfo"],
        "technical_notes": "Arpeggiator for backing patterns, Euclidean for rhythm, CC LFO for dynamic variation.",
        "example_setup": "Scale-aware arpeggiator, rhythmic backing from Euclidean, CC LFO for variation"
    },
    {
        "id": 72,
        "title": "Patch Change Management",
        "description": "Manage patch changes seamlessly during performances. Ensure smooth transitions between sounds without gaps or clicks.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "Use tracker for crossfaded patch changes. CC for gradual parameter transitions.",
        "example_setup": "Tracker with crossfade between steps, CC for smooth parameter changes"
    },
    {
        "id": 73,
        "title": "Crowd Interaction Tools",
        "description": "Create crowd interaction experiences with MIDI. Allow audience to influence music or visuals through MIDI-enabled devices or apps.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo"],
        "technical_notes": "Multiple MIDI inputs from audience devices. Use routing matrix to aggregate and process.",
        "example_setup": "Audience devices → Network MIDI → routing matrix → music/visual output"
    },
    {
        "id": 74,
        "title": "Data Sonification",
        "description": "Convert data sets to music with MIDI. Transform scientific, financial, or social data into musical representations for analysis or presentation.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo", "arpeggiator"],
        "technical_notes": "Data values → MIDI parameters. Use CC for continuous data, notes for discrete events.",
        "example_setup": "Data → CC mapping, arpeggiator for melodic interpretation, CC LFO for texture"
    },
    {
        "id": 75,
        "title": "Motion Sensor Integration",
        "description": "Integrate motion sensors with MIDI. Create interactive installations where movement triggers or modulates musical content.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo"],
        "technical_notes": "Motion sensor → CC values. Use CC LFO for smooth transitions between states.",
        "example_setup": "Motion → CC, position → pitch, speed → tempo, gesture → effects"
    },
    {
        "id": 76,
        "title": "Experimental Soundscapes",
        "description": "Create experimental soundscapes using unconventional MIDI mappings. Explore abstract audio territories through creative parameter control.",
        "raspimidihub_features": ["cc_lfo", "arpeggiator", "euclidean", "routing_matrix"],
        "technical_notes": "Unconventional CC mappings, randomization, and feedback loops. Use all modulation sources together.",
        "example_setup": "Multiple CC LFOs, random arpeggiator, Euclidean for rhythm, complex routing"
    },
    {
        "id": 77,
        "title": "VR Experience Control",
        "description": "Control virtual reality experiences with MIDI. Trigger events, adjust parameters, or synchronize audio-visual content in VR environments.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "CC for VR parameters, PC for scene changes. Use tracker for scripted sequences.",
        "example_setup": "CC for real-time control, tracker for scripted VR sequences"
    },
    {
        "id": 78,
        "title": "Arcade Machine Modification",
        "description": "Modify arcade machines with MIDI control. Add new features, control game parameters, or create custom arcade experiences.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "CC for game parameters, PC for mode changes. Use tracker for custom game modes.",
        "example_setup": "MIDI → arcade interface, CC for parameters, tracker for game modes"
    },
    {
        "id": 79,
        "title": "Simulator Cockpit Controls",
        "description": "Build simulator cockpit controls with MIDI. Create realistic control panels for flight, driving, or other simulation experiences.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "Each control → CC/PC. Use tracker for configuration presets (different aircraft/vehicles).",
        "example_setup": "Physical controls → MIDI, tracker for vehicle presets"
    },
    {
        "id": 80,
        "title": "MIDI to DMX (Light Shows)",
        "description": "Convert MIDI to DMX for professional light shows. Control stage lighting consoles, intelligent fixtures, and LED systems with musical control.",
        "raspimidihub_features": ["routing_matrix", "tracker", "cc_lfo"],
        "technical_notes": "MIDI-to-DMX bridge required. CC 1-127 map to DMX channels. Use tracker for show sequences.",
        "example_setup": "Faders for intensity, CC LFO for automated effects, tracker for show programming"
    },
    {
        "id": 81,
        "title": "Computer Control with MIDI",
        "description": "Control computer functions with MIDI. Launch applications, control media players, manage files, or execute macros using MIDI controllers.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "MIDI-to-keyboard bridge. Use PC for application launch, CC for volume/brightness control.",
        "example_setup": "Buttons for app launch, faders for system controls, tracker for workflows"
    },
    {
        "id": 82,
        "title": "DAW Transport Control",
        "description": "Control DAW transport functions with MIDI. Play, stop, record, and navigate timelines in digital audio workstations using physical controllers.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "Standard MIDI transport controls. Use CC for scrubbing, PC for marker navigation.",
        "example_setup": "Transport buttons, fader for scrubbing, encoder for marker navigation"
    },
    {
        "id": 83,
        "title": "Screen Brightness Control",
        "description": "Control screen brightness and color temperature with MIDI. Adjust display settings for comfortable viewing or create dynamic lighting effects.",
        "raspimidihub_features": ["cc_lfo", "routing_matrix"],
        "technical_notes": "CC for brightness/temperature. Use CC LFO for circadian rhythm automation.",
        "example_setup": "Fader for brightness, CC LFO for automatic day/night adjustment"
    },
    {
        "id": 84,
        "title": "Keyboard Shortcut Mapping",
        "description": "Map keyboard shortcuts to MIDI controllers. Execute complex shortcuts, macros, or workflows with single button presses.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "MIDI-to-keyboard bridge. Use PC for shortcut groups, CC for parameter adjustment.",
        "example_setup": "Each button = shortcut, tracker for workflow groups"
    },
    {
        "id": 85,
        "title": "Text Expansion Triggers",
        "description": "Trigger text expansion with MIDI. Insert pre-written text, email templates, or code snippets using MIDI controllers for faster typing.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "PC for text snippet selection. Use tracker for context-specific snippets.",
        "example_setup": "Each button = text snippet, tracker for context (email, code, chat)"
    },
    {
        "id": 86,
        "title": "Workflow Automation",
        "description": "Automate complex workflows with MIDI. Chain multiple actions together, trigger sequences, and streamline repetitive tasks.",
        "raspimidihub_features": ["tracker", "routing_matrix"],
        "technical_notes": "Tracker for multi-step workflows. Each step triggers specific action via MIDI bridge.",
        "example_setup": "One button press → multi-step workflow via tracker"
    },
    {
        "id": 87,
        "title": "Volume Mixing Control",
        "description": "Control computer volume mixing with MIDI. Adjust individual application volumes, master output, and audio routing with physical faders.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo"],
        "technical_notes": "CC for volume levels. Use CC LFO for automated fade effects or ducking.",
        "example_setup": "One fader per application, master fader for output, CC LFO for ducking"
    },
    {
        "id": 88,
        "title": "Macro Execution",
        "description": "Execute complex macros with MIDI. Trigger multi-step automation sequences for productivity, gaming, or creative workflows.",
        "raspimidihub_features": ["tracker", "routing_matrix"],
        "technical_notes": "Tracker for macro sequences. Each step executes specific action.",
        "example_setup": "One button = complete macro, tracker handles sequence"
    },
    {
        "id": 89,
        "title": "Appliance Triggering",
        "description": "Trigger household appliances with MIDI. Control coffee makers, toasters, or other appliances through MIDI-enabled smart home integration.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "CC for on/off triggers. Use tracker for morning/evening routines.",
        "example_setup": "Buttons for individual appliances, tracker for routines"
    },
    {
        "id": 90,
        "title": "Room Ambiance Automation",
        "description": "Automate room ambiance with MIDI. Control lighting, temperature, and audio to create perfect environments for different activities.",
        "raspimidihub_features": ["cc_lfo", "routing_matrix", "tracker"],
        "technical_notes": "CC for all parameters. Use tracker for activity presets (reading, party, sleep).",
        "example_setup": "Tracker for presets, CC LFO for gradual transitions between states"
    },
    {
        "id": 91,
        "title": "Security System Integration",
        "description": "Integrate security systems with MIDI. Trigger alarms, lock doors, or activate cameras using MIDI controllers or automated sequences.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "PC for system modes (armed/disarmed), CC for individual device control.",
        "example_setup": "Tracker for security modes, CC for individual device control"
    },
    {
        "id": 92,
        "title": "Thermostat Control",
        "description": "Control thermostats with MIDI. Adjust temperature settings, create schedules, or trigger climate control based on MIDI input.",
        "raspimidihub_features": ["cc_lfo", "routing_matrix"],
        "technical_notes": "CC for temperature setpoints. Use CC LFO for gradual adjustments or schedules.",
        "example_setup": "Fader for temperature, CC LFO for schedules, buttons for quick presets"
    },
    {
        "id": 93,
        "title": "Window Blind Automation",
        "description": "Automate window blinds with MIDI. Control opening/closing, angle, and scheduling for privacy and energy efficiency.",
        "raspimidihub_features": ["cc_lfo", "routing_matrix"],
        "technical_notes": "CC for position control. Use CC LFO for automated daily schedules.",
        "example_setup": "Fader for position, CC LFO for daily schedule, buttons for presets"
    },
    {
        "id": 94,
        "title": "Irrigation Scheduling",
        "description": "Schedule irrigation systems with MIDI. Control watering schedules, duration, and zones using MIDI controllers or automated sequences.",
        "raspimidihub_features": ["tracker", "routing_matrix"],
        "technical_notes": "Tracker for irrigation schedules. CC for zone selection and duration.",
        "example_setup": "Tracker for schedules, CC for manual override"
    },
    {
        "id": 95,
        "title": "Pet Feeder Control",
        "description": "Control pet feeders with MIDI. Schedule feeding times, portion sizes, and trigger manual feeds using MIDI controllers.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "CC for portion size, PC for feeding triggers. Use tracker for feeding schedules.",
        "example_setup": "Buttons for manual feed, tracker for scheduled feeding"
    },
    {
        "id": 96,
        "title": "Coffee Maker Triggering",
        "description": "Trigger coffee makers with MIDI. Start brewing at scheduled times or with a button press for morning convenience.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "CC for on/off trigger. Use tracker for morning routine integration.",
        "example_setup": "Button for instant brew, tracker for morning routine"
    },
    {
        "id": 97,
        "title": "Door Lock Integration",
        "description": "Integrate door locks with MIDI. Lock/unlock doors, check status, or trigger automated locking schedules using MIDI controllers.",
        "raspimidihub_features": ["routing_matrix", "tracker"],
        "technical_notes": "CC for lock/unlock. Use tracker for automated schedules (night, away).",
        "example_setup": "Buttons for manual control, tracker for automated schedules"
    },
    {
        "id": 98,
        "title": "Music Production Workflows",
        "description": "Streamline music production workflows with MIDI. Control recording, mixing, and mastering processes with dedicated MIDI controllers.",
        "raspimidihub_features": ["routing_matrix", "tracker", "cc_lfo"],
        "technical_notes": "CC for DAW control, PC for preset loading. Use tracker for production stages.",
        "example_setup": "One tracker preset per production stage (recording, mixing, mastering)"
    },
    {
        "id": 99,
        "title": "Live Performance Enhancement",
        "description": "Enhance live performances with MIDI. Add real-time effects, backing tracks, and interactive elements to make performances more engaging.",
        "raspimidihub_features": ["routing_matrix", "cc_lfo", "tracker"],
        "technical_notes": "CC for real-time effects, tracker for song structure, CC LFO for dynamic variation.",
        "example_setup": "Real-time control via CC, song structure via tracker, variation via CC LFO"
    },
    {
        "id": 100,
        "title": "Experimental Music Systems",
        "description": "Build experimental music systems with MIDI. Create custom instruments, generative systems, or interactive installations for artistic exploration.",
        "raspimidihub_features": ["cc_lfo", "arpeggiator", "euclidean", "cartesian", "routing_matrix"],
        "technical_notes": "Combine all RaspiMIDIHub features for maximum creative potential. Use unconventional mappings and feedback loops.",
        "example_setup": "All features combined, custom mappings, feedback loops, generative systems"
    }
]

_SYSTEM = (
    "You are an expert on creative MIDI applications and the RaspiMIDIHub system. "
    "Your task is to explain how to implement a creative MIDI use case using "
    "RaspiMIDIHub features in an educational, engaging way.\n\n"
    "RaspiMIDIHub Features Available:\n"
    "- Trackers: Fixed sequences of notes and CCs (perfect for patterns, loops, scenes)\n"
    "- Arpeggiators: Dynamic note generation with multiple algorithms\n"
    "- Euclidean Sequencer: Rhythmic patterns with adjustable steps and gates\n"
    "- Cartesian Surface: 2D grid sequencer for spatial control and voicing\n"
    "- CC LFO Plugin: Automated modulation of any CC parameter\n"
    "- Routing Matrix: Route any input to any output with filtering and mapping\n"
    "- Channel Selector: Switch MIDI channels with controller buttons\n"
    "- Network MIDI: RTP-MIDI over LAN for distributed setups\n"
    "- Bluetooth MIDI: Wireless controller support\n"
    "- Plugin System: Custom behavior through extensible plugins\n"
    "- Rack View: Visual patching of complex signal flows\n"
    "- Mirror: Connect multiple hubs for distributed control\n\n"
    "Bridge Software Examples (mention when relevant):\n"
    "- Smart Home: Home Assistant, IFTTT, Node-RED (MIDI → API)\n"
    "- Gaming: MIDI2Keys, ViMIDI, loopM (MIDI → keyboard/mouse)\n"
    "- Lighting: osc2dmx, Midi2DMX, QLC+ (MIDI → DMX)\n"
    "- DAW/Computer: MIDI-OX, Bome MIDI Translator (MIDI → app control)\n"
    "- Video: QLab, Resolume (MIDI → visual triggers)\n"
    "- Robotics/Arduino: Firmata, serial-to-MIDI bridges\n\n"
    "Write a post that:\n"
    "1. States the creative use case clearly\n"
    "2. Explains HOW to do it: RaspiMIDIHub features + bridge software\n"
    "3. Be specific: which CC/messages, which bridge, what it does\n"
    "4. Keep it under 280 characters\n"
    "5. No URLs, hashtags, or emoji\n"
    "6. Educational and enthusiastic tone"
)


def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class CreativeUsesSource(Source):
    name = 'creative_uses'

    def find_new(self, state) -> list:
        """Find one unposted use case from the catalog."""
        # Filter out already announced use cases
        unposted = [
            uc for uc in _USE_CASES
            if not state.is_announced(self.name, _key(str(uc['id'])))
        ]

        if not unposted:
            # Cycle exhausted, reset and start over
            state.reset(self.name)
            unposted = _USE_CASES

        # Pick one (could add scoring/randomization here)
        return [unposted[0]]

    def latest(self) -> list:
        """Return one use case for --force testing."""
        return [_USE_CASES[0]]

    def render(self, item, llm) -> Post:
        """Transform the use case into an educational post."""
        # Build detailed prompt with technical info
        features_str = ', '.join(item.get('raspimidihub_features', []))
        technical = item.get('technical_notes', '')
        example = item.get('example_setup', '')

        user = (
            f"Use Case: {item['title']}\n"
            f"Description: {item['description']}\n"
            f"RaspiMIDIHub Features: {features_str}\n"
            f"Technical Notes: {technical}\n"
            f"Example Setup: {example}\n\n"
            f"Write an educational post explaining how to implement this "
            f"use case with RaspiMIDIHub. Be specific about which features "
            f"to use and how they work together."
        )

        # Fallback if LLM unavailable
        fallback = (
            f"{item['title']}: Use RaspiMIDIHub's "
            f"{features_str} to implement this. "
            f"{item['description']}"
        )

        text = llm_or_template(
            llm, _SYSTEM, user,
            fallback=fallback,
            max_len=280,
            temperature=0.7  # Balanced creativity for educational content
        )

        return Post(
            text=append_link(text, config.SITE_URL),
            source=self.name,
            dedupe_key=_key(str(item['id']))
        )
