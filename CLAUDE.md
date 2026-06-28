# mr18-ui

NiceGUI web app for controlling a Midas MR18 digital mixer over OSC (xair_api).
Runs at `http://localhost:8018`. Entry point: `main.py`.

## Architecture

```
main.py                  — NiceGUI app entry, MixerClient instantiation
mixer/
  client.py              — OSC client: connects to MR18, polls state, dispatches updates
  discovery.py           — UDP broadcast scanner to find MR18 on the network
  pipewire.py            — AirPlay volume control via PipeWire/pactl (see below)
ui/
  connect.py             — / route: discovery + connection page
  app.py                 — /mixer route: full mixer page, poll loop
  strip.py               — fader_strip() for MR18 channels; airplay_strip() for AirPlay
  eq.py                  — EQ panel (fixed bottom drawer)
  eq_math.py             — EQ curve maths
  utils.py               — fader_to_db() conversion
```

## AirPlay integration (added externally — be aware of these files)

Three files were added/modified by a separate session to integrate AirPlay 2 playback:

### `mixer/pipewire.py` (new)
`AirPlayControl` class — background thread polls `pactl list sink-inputs` every 3 s,
finds the shairport-sync stream by name, and applies the stored volume/mute to it.
Volume range: 0.0–1.5 (1.0 = 0 dB unity). Instantiated as a module-level singleton
in `ui/app.py` so state persists across page navigations.

### `ui/strip.py` (modified)
- Added `from mixer.pipewire import AirPlayControl` import
- Added `airplay_strip(control, width_class)` at the bottom of the file — returns a
  `poll()` callable. Renders identically to MR18 channel strips: vertical fader,
  dB label, mute button, and a green activity dot that lights when a stream is live.

### `ui/app.py` (modified)
- Added `AirPlayControl` import and module-level `_airplay_control` singleton
- Added `airplay_strip` import
- In the channel strip row: added a second divider + `airplay_strip(_airplay_control)`
  after the LR master strip
- `ap_poll()` called inside the existing 200 ms `ui.timer` poll loop

## Audio routing

shairport-sync (AirPlay 2 receiver) is installed system-wide and outputs to the
MR18 USB multichannel output (`alsa_output.usb-MIDAS_MR18_1C921437-00.multichannel-output`,
stereo, channels 1-2). AirPlay audio therefore enters the MR18 as a USB return and
can be mixed, EQ'd, and sent to monitor buses like any other channel.

Config: `/usr/local/etc/shairport-sync.conf`
Service: `sudo systemctl status shairport-sync`

## OSC address reference (MR18)

```
/ch/{01-16}/mix/fader     — channel fader (0.0–1.0)
/ch/{01-16}/mix/on        — channel mute (1=on/unmuted, 0=muted)
/ch/{01-16}/config/name   — channel label (string)
/headamp/{01-16}/gain     — preamp gain (0.0–1.0)
/headamp/{01-16}/phantom  — phantom power (0/1)
/meters/0                 — meter blob (16× float32 LE)
/lr/mix/fader             — LR master fader
/lr/mix/on                — LR master mute
/xremote                  — keepalive (sent every 8 s to stay subscribed)
```
