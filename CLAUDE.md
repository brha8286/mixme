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
/ch/{01-16}/mix/lr        — LR bus assign (0/1) — used by the LR meter sum
/ch/{01-16}/config/name   — channel label (string)
/headamp/{01-16}/gain     — preamp gain (0.0–1.0)
/headamp/{01-16}/phantom  — phantom power (0/1)
/ch/{01-16}/preamp/rtnsw  — USB return on/off (1 = channel is fed from USB)
/lr/mix/fader             — LR master fader
/lr/mix/on                — LR master mute
/xremote                  — keepalive (sent every 8 s to stay subscribed)
```

Firmware 1.17 answers no `/meters/...` request and no `/routing/...` request
(both probed, zero responses), so metering is assembled from two capture paths
instead. Anything needing a mixer-side tap point is simply unavailable.

## Metering

Meters come from two sources because neither one covers every channel.

**1. USB capture (`hw:4,0`) — `MixerClient._alsa_meter_loop`.** Carries the 18
**inputs only** — the 16 mic preamps plus the RCA aux input, never the LR mix.
The stream is rotated by a constant +10, so mixer channel N is at index
`(N + 10) % 18` and the aux pair lands at indices 9/10.

The rotation is mod **18** (the frame width), not mod 16. A previous `(ch-6)%16`
version agreed only for ch 1-5 — enough to look "confirmed" when tested on PC
L/R — and was silently 2 strips off for ch 6-16. Anchors: ch 3/4 → idx 13/14 and
ch 15/16 → idx 7/8, both measured against known sources. Note the send tap
appears to sit *ahead* of the preamp gain, so gain changes cannot be used to
identify a channel's index; drive a known input instead.

**2. PipeWire sink monitor — `SinkMonitorMeters` in `mixer/pipewire.py`.** The
USB send taps each channel at the analog preamp, **before** the USB-return
switch — presumably so USB out → channel → USB in can't feed back. So a channel
fed from USB (AirPlay, a DAW) reads digital silence in the capture stream no
matter how loud it is; verified by measuring −110 dBFS on ch 1/2 while audio was
plainly audible. Monitoring what *we* send to the MR18 PipeWire sink recovers
those levels. Sink channel N is assumed to feed mixer channel N (default
`rtnsrc`), and `rtntrim` is not applied.

The meter loop uses source 2 for any channel with `preamp/rtnsw == 1` and source
1 otherwise. **This only works while the MR18 PipeWire sink exists** — see the
exclusive-access note below.

There is no hardware tap for LR at all, so `/lr/meter` is summed in software
from the per-channel levels: each channel scaled by its fader taper, dropped if
muted or unassigned from LR, power-summed, then scaled by the LR fader/mute.
Pan and channel EQ/dynamics are not modelled, so it tracks level, not the exact
bus signal.

## Exclusive device access (DAWs)

Any app taking the MR18 on the **raw ALSA backend** (Ardour's default) holds the
USB device exclusively, and the `MR18 Multichannel` PipeWire sink disappears.
Two things then break silently:

- shairport-sync's configured `sink_target` no longer exists, so AirPlay falls
  back to the default sink — it keeps playing, just not into the MR18.
- USB-return channels stop metering (source 2 above is gone); they read zero
  rather than erroring.

Run DAWs on the PipeWire backend (`pw-jack ardour`) so the device stays shared.
Note both `jackd2` and `pipewire-jack` are installed — picking "JACK" in a DAW
may start real jackd2, which grabs the device exclusively just like ALSA does.

Playback and capture are *separate* ALSA substreams, so a DAW using playback
only does not disturb the meter reader. A DAW capturing from the MR18 does
fight it — `arecord` holds the capture substream, and one of the two loses.
