import math
from nicegui import ui
from mixer.client import MixerClient
from mixer.pipewire import AirPlayControl
from .utils import fader_to_db


def _db_gain(raw: float) -> str:
    db = -12.0 + raw * 72.0  # lin_get(-12, 60, raw)
    return f'{db:+.0f}dB'


def _meter_pct(linear: float) -> float:
    """Convert linear amplitude 0–1 to 0–100 % for meter bar."""
    if linear <= 0:
        return 0.0
    db = 20 * math.log10(max(linear, 1e-9))
    # map -60 dBFS..0 dBFS → 0..100 %
    return max(0.0, min(100.0, (db + 60) / 60 * 100))


def fader_strip(
    bottom_label: str,
    fader_addr: str,
    mute_addr: str,
    client: MixerClient,
    registry: dict,
    active_ch: list,
    ch: int | None = None,          # None for LR master
    name_addr: str | None = None,
    width_class: str = 'w-[72px]',
):
    init_fader  = float(client.get(fader_addr) or 0.75)
    init_mute   = client.get(mute_addr)
    init_name   = (client.get(name_addr) if name_addr else None) or bottom_label

    gain_addr    = f'/headamp/{ch:02d}/gain'    if ch else None
    phantom_addr = f'/headamp/{ch:02d}/phantom' if ch else None
    meter_addr   = f'/ch/{ch:02d}/meter'        if ch else None

    init_gain    = float(client.get(gain_addr) or 0.0) if gain_addr else None
    init_phantom = int(client.get(phantom_addr) or 0)  if phantom_addr else 0

    is_muted   = [int(init_mute) == 0 if init_mute is not None else False]
    is_phantom = [bool(init_phantom)]
    peak_val   = [0.0]   # for peak hold
    peak_age   = [0]     # poll-tick counter

    with ui.column().classes(
        f'items-center gap-0.5 bg-gray-800 rounded-lg px-1 pt-2 pb-1 '
        f'{width_class} flex-shrink-0 select-none'
    ):
        # ── channel name (editable) ─────────────────────────────────────
        name_lbl = (
            ui.label(str(init_name))
            .classes('text-[10px] text-gray-300 truncate w-full text-center cursor-pointer leading-none')
        )
        name_inp = (
            ui.input(value=str(init_name))
            .classes('text-[10px] w-full')
            .props('dense borderless')
        )
        name_inp.set_visibility(False)

        def _start_edit():
            name_inp.set_value(name_lbl.text)
            name_lbl.set_visibility(False)
            name_inp.set_visibility(True)
            name_inp.run_method('focus')

        def _finish_edit():
            val = (name_inp.value or '')[:12]
            name_lbl.set_text(val or bottom_label)
            name_lbl.set_visibility(True)
            name_inp.set_visibility(False)
            if name_addr and val:
                client.send(name_addr, val)

        name_lbl.on('click', lambda: _start_edit())
        name_inp.on('blur',  lambda: _finish_edit())
        name_inp.on('keydown.enter', lambda: _finish_edit())

        # ── fader + meter row ───────────────────────────────────────────
        with ui.row().classes('gap-0 items-stretch').style('height:200px'):
            # meter bar — gradient bg with dark overlay that shrinks from top as signal rises
            with ui.element('div').style(
                'width:6px; height:100%; border-radius:3px; overflow:hidden; position:relative; '
                'background: linear-gradient(to top, #22c55e 0%, #eab308 70%, #ef4444 90%);'
            ):
                meter_fill = (
                    ui.element('div')
                    .style('position:absolute; top:0; left:0; width:100%; height:100%; '
                           'background:#1f2937; transition:height 0.06s linear;')
                )

            # fader
            fader = (
                ui.slider(min=0, max=1, step=0.001, value=init_fader)
                .props('vertical reverse')
                .style('height:190px; width:36px;')
            )

        db_lbl = ui.label(fader_to_db(init_fader)).classes('text-[10px] text-gray-400 tabular-nums leading-none')

        # ── mute button ─────────────────────────────────────────────────
        mute_btn = ui.button('M').classes('w-full text-xs h-6 font-bold rounded')

        # ── phantom button (channels only) ──────────────────────────────
        if phantom_addr:
            phantom_btn = ui.button('48V').classes('w-full text-[9px] h-5 rounded')
        else:
            phantom_btn = None

        # ── EQ button (channels only) ───────────────────────────────────
        if ch:
            eq_btn = ui.button('EQ').classes('w-full text-[9px] h-5 rounded')
            eq_btn.props('color=grey-8 flat')
            eq_btn.on_click(lambda _ch=ch: _open_eq(_ch))
        else:
            eq_btn = None

        # ── gain slider (channels only) ──────────────────────────────────
        if gain_addr:
            gain_lbl = ui.label(_db_gain(init_gain or 0.0)).classes('text-[9px] text-gray-500 leading-none')
            gain_slider = (
                ui.slider(min=0, max=1, step=0.01, value=init_gain or 0.0)
                .style('width:100%;')
            )
        else:
            gain_lbl = None
            gain_slider = None

        ui.label(bottom_label).classes('text-[10px] text-gray-600 leading-none')

    # ── helpers ─────────────────────────────────────────────────────────

    def _open_eq(target_ch: int):
        active_ch[0] = target_ch

    def _apply_mute_style():
        mute_btn.props('color=negative' if is_muted[0] else 'color=grey-8')

    def _apply_phantom_style():
        if phantom_btn:
            phantom_btn.props('color=warning' if is_phantom[0] else 'color=grey-8')

    def _on_mute_click():
        is_muted[0] = not is_muted[0]
        client.send(mute_addr, 0 if is_muted[0] else 1)
        _apply_mute_style()

    def _on_phantom_click():
        is_phantom[0] = not is_phantom[0]
        client.send(phantom_addr, 1 if is_phantom[0] else 0)
        _apply_phantom_style()

    def _on_fader_change():
        client.send(fader_addr, fader.value)
        db_lbl.set_text(fader_to_db(fader.value))

    def _on_gain_change():
        if gain_addr:
            client.send(gain_addr, gain_slider.value)
            gain_lbl.set_text(_db_gain(gain_slider.value))

    mute_btn.on_click(_on_mute_click)
    fader.on_value_change(_on_fader_change)
    if phantom_btn:
        phantom_btn.on_click(_on_phantom_click)
    if gain_slider:
        gain_slider.on_value_change(_on_gain_change)

    _apply_mute_style()
    _apply_phantom_style()

    # ── registry updaters ────────────────────────────────────────────────

    def _upd_fader(val):
        v = float(val)
        if abs(fader.value - v) > 0.001:
            fader.set_value(v)
        db_lbl.set_text(fader_to_db(v))

    def _upd_mute(val):
        now_muted = int(val) == 0
        if now_muted != is_muted[0]:
            is_muted[0] = now_muted
            _apply_mute_style()

    def _upd_name(val):
        if not name_inp.visible:
            name_lbl.set_text(str(val) if val else bottom_label)

    def _upd_gain(val):
        v = float(val)
        if gain_slider and abs(gain_slider.value - v) > 0.005:
            gain_slider.set_value(v)
        if gain_lbl:
            gain_lbl.set_text(_db_gain(v))

    def _upd_phantom(val):
        now_on = int(val) == 1
        if now_on != is_phantom[0]:
            is_phantom[0] = now_on
            _apply_phantom_style()

    def _upd_meter(val):
        pct = _meter_pct(float(val))
        # peak hold: keep max for ~1.5 s (≈ 8 poll ticks at 0.2 s)
        if pct >= peak_val[0]:
            peak_val[0] = pct
            peak_age[0] = 0
        else:
            peak_age[0] += 1
            if peak_age[0] > 8:
                peak_val[0] = max(peak_val[0] - 3, pct)
        cover = 100 - peak_val[0]
        meter_fill.style(
            replace=f'position:absolute; top:0; left:0; width:100%; height:{cover:.1f}%; '
                    'background:#1f2937; transition:height 0.06s linear;'
        )

    registry[fader_addr]   = _upd_fader
    registry[mute_addr]    = _upd_mute
    if name_addr:
        registry[name_addr] = _upd_name
    if gain_addr:
        registry[gain_addr] = _upd_gain
    if phantom_addr:
        registry[phantom_addr] = _upd_phantom
    if meter_addr:
        registry[meter_addr] = _upd_meter


def airplay_strip(
    control: AirPlayControl,
    width_class: str = 'w-[72px]',
):
    """Fader strip that controls the shairport-sync PipeWire stream volume.

    Returns a poll callable to be invoked on each UI timer tick.
    """
    is_muted = [control.muted]

    with ui.column().classes(
        f'items-center gap-0.5 bg-gray-800 rounded-lg px-1 pt-2 pb-1 '
        f'{width_class} flex-shrink-0 select-none'
    ):
        # ── header: label + live indicator ──────────────────────────────
        with ui.row().classes('items-center gap-1 w-full justify-center leading-none'):
            activity_dot = ui.element('div').style(
                'width:6px; height:6px; border-radius:50%; background:#374151; flex-shrink:0;'
            )
            ui.label('AirPlay').classes('text-[10px] text-gray-300 truncate')

        # ── fader (0–1.5; unity at 1.0 ≈ ⅔ travel) ─────────────────────
        with ui.row().classes('gap-0 items-stretch').style('height:200px'):
            # blank spacer keeps fader aligned with channel strips
            ui.element('div').style('width:6px;')
            fader = (
                ui.slider(min=0, max=1.5, step=0.01, value=control.volume)
                .props('vertical reverse')
                .style('height:190px; width:36px;')
            )

        db_lbl = (
            ui.label(control.vol_to_db(control.volume))
            .classes('text-[10px] text-gray-400 tabular-nums leading-none')
        )

        mute_btn = ui.button('M').classes('w-full text-xs h-6 font-bold rounded')

        ui.label('AirPlay').classes('text-[10px] text-gray-600 leading-none')

    # ── event handlers ───────────────────────────────────────────────────

    def _apply_mute_style():
        mute_btn.props('color=negative' if is_muted[0] else 'color=grey-8')

    def _on_fader_change():
        control.set_volume(fader.value)
        db_lbl.set_text(control.vol_to_db(fader.value))

    def _on_mute_click():
        is_muted[0] = not is_muted[0]
        control.set_muted(is_muted[0])
        _apply_mute_style()

    fader.on_value_change(_on_fader_change)
    mute_btn.on_click(_on_mute_click)
    _apply_mute_style()

    # ── poll: update activity dot each UI tick ───────────────────────────
    def poll():
        color = '#22c55e' if control.active else '#374151'
        activity_dot.style(
            replace=f'width:6px; height:6px; border-radius:50%; background:{color}; flex-shrink:0;'
        )

    return poll
