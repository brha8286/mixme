from nicegui import ui
from mixer.client import MixerClient
from .eq_math import (
    FREQ_LIST, BAND_NAMES, BAND_TYPES, Q_RELEVANT,
    raw_to_hz, raw_to_db_gain, raw_to_q,
    hz_to_raw, db_gain_to_raw, q_to_raw,
    eq_response, parse_band,
)

NUM_BANDS = 4
_TYPE_OPTIONS = {i: label for i, label in enumerate(BAND_TYPES)}


def _fmt_hz(hz: float) -> str:
    return f'{hz/1000:.1f}k' if hz >= 1000 else f'{hz:.0f}'


def _fmt_db(db: float) -> str:
    return f'{db:+.1f}' if db != 0 else '0.0'


def setup_eq_panel(client: MixerClient, registry: dict, active_ch: list):
    """
    Renders the EQ drawer (fixed bottom). Call once per page load.
    active_ch[0] is set by strip EQ buttons to the channel number (1-16).
    """

    current_ch = [None]    # channel currently shown in the panel
    eq_visible = [False]

    # per-band raw OSC values (0–1) — source of truth for sliders
    raw = {
        band: {'f': 0.5, 'g': 0.5, 'q': 0.5, 'type': 2}
        for band in range(1, NUM_BANDS + 1)
    }

    # ── panel shell ────────────────────────────────────────────────────
    panel = ui.card().style(
        'position:fixed; bottom:0; left:0; right:0; z-index:100; '
        'background:#1f2937; border-top:1px solid #374151; '
        'padding:12px 16px; border-radius:0;'
    )
    panel.set_visibility(False)

    with panel:
        # header row
        with ui.row().classes('items-center gap-4 w-full mb-2'):
            ch_lbl = ui.label('EQ: —').classes('text-white font-bold text-sm')
            eq_on_btn = ui.button('EQ ON').props('color=positive outline size=sm')
            ui.space()
            ui.button('✕', on_click=lambda: _close()).props('flat color=grey size=sm')

        # ECharts curve
        chart = ui.echart({
            'backgroundColor': 'transparent',
            'grid': {'top': 8, 'bottom': 24, 'left': 40, 'right': 8},
            'xAxis': {
                'type': 'log',
                'min': 20, 'max': 20000,
                'axisLabel': {
                    'formatter': '{value}',
                    'color': '#9ca3af',
                    'fontSize': 10,
                },
                'splitLine': {'lineStyle': {'color': '#374151'}},
                'axisLine':  {'lineStyle': {'color': '#4b5563'}},
            },
            'yAxis': {
                'type': 'value',
                'min': -20, 'max': 15,
                'axisLabel': {'color': '#9ca3af', 'fontSize': 10,
                              'formatter': '{value}dB'},
                'splitLine': {'lineStyle': {'color': '#374151'}},
                'axisLine':  {'lineStyle': {'color': '#4b5563'}},
            },
            'series': [{
                'type': 'line',
                'smooth': True,
                'symbol': 'none',
                'lineStyle': {'color': '#3b82f6', 'width': 2},
                'areaStyle': {'color': 'rgba(59,130,246,0.08)'},
                'data': list(zip(FREQ_LIST, [0.0] * len(FREQ_LIST))),
            }],
        }).style('height:160px; width:100%;')

        # band columns
        band_widgets = {}  # band → {type_sel, freq_sl, freq_lbl, gain_sl, gain_lbl, q_sl, q_lbl, q_row}

        with ui.row().classes('gap-4 w-full mt-2'):
            for b in range(1, NUM_BANDS + 1):
                with ui.column().classes('gap-1 flex-1'):
                    ui.label(BAND_NAMES[b - 1]).classes('text-[10px] text-gray-500 uppercase tracking-widest')

                    type_sel = ui.select(
                        options=_TYPE_OPTIONS,
                        value=raw[b]['type'],
                    ).classes('text-xs').props('dense outlined dark')

                    with ui.row().classes('items-center gap-1'):
                        ui.label('Freq').classes('text-[10px] text-gray-400 w-8')
                        freq_lbl = ui.label(_fmt_hz(raw_to_hz(0.5))).classes('text-[10px] text-blue-400 w-10')
                    freq_sl = ui.slider(min=0, max=1, step=0.001, value=0.5).style('width:100%')

                    with ui.row().classes('items-center gap-1'):
                        ui.label('Gain').classes('text-[10px] text-gray-400 w-8')
                        gain_lbl = ui.label('0.0').classes('text-[10px] text-blue-400 w-10')
                    gain_sl = ui.slider(min=0, max=1, step=0.001, value=0.5).style('width:100%')

                    q_row = ui.column().classes('gap-0')
                    with q_row:
                        with ui.row().classes('items-center gap-1'):
                            ui.label('Q').classes('text-[10px] text-gray-400 w-8')
                            q_lbl = ui.label('0.7').classes('text-[10px] text-blue-400 w-10')
                        q_sl = ui.slider(min=0, max=1, step=0.001, value=0.5).style('width:100%')

                    band_widgets[b] = {
                        'type': type_sel,
                        'freq_sl': freq_sl, 'freq_lbl': freq_lbl,
                        'gain_sl': gain_sl, 'gain_lbl': gain_lbl,
                        'q_sl': q_sl,       'q_lbl': q_lbl,
                        'q_row': q_row,
                    }

    # ── helpers ────────────────────────────────────────────────────────

    def _curve_data():
        bands = [parse_band(client.snapshot(), current_ch[0], b) for b in range(1, NUM_BANDS + 1)]
        db_vals = eq_response(bands)
        return list(zip(FREQ_LIST, db_vals))

    def _refresh_curve():
        chart.options['series'][0]['data'] = _curve_data()
        chart.update()

    def _refresh_band_labels(b: int):
        w = band_widgets[b]
        r = raw[b]
        w['freq_lbl'].set_text(_fmt_hz(raw_to_hz(r['f'])))
        w['gain_lbl'].set_text(_fmt_db(raw_to_db_gain(r['g'])))
        w['q_lbl'].set_text(f'{raw_to_q(r["q"]):.2f}')
        show_q = r['type'] in Q_RELEVANT
        w['q_row'].set_visibility(show_q)

    def _wire_band(b: int):
        w = band_widgets[b]

        def on_type_change(e):
            raw[b]['type'] = e.value
            addr = f'/ch/{current_ch[0]:02d}/eq/{b}/type'
            client.send(addr, e.value)
            _refresh_band_labels(b)
            _refresh_curve()

        def on_freq_change():
            raw[b]['f'] = w['freq_sl'].value
            addr = f'/ch/{current_ch[0]:02d}/eq/{b}/f'
            client.send(addr, w['freq_sl'].value)
            _refresh_band_labels(b)
            _refresh_curve()

        def on_gain_change():
            raw[b]['g'] = w['gain_sl'].value
            addr = f'/ch/{current_ch[0]:02d}/eq/{b}/g'
            client.send(addr, w['gain_sl'].value)
            _refresh_band_labels(b)
            _refresh_curve()

        def on_q_change():
            raw[b]['q'] = w['q_sl'].value
            addr = f'/ch/{current_ch[0]:02d}/eq/{b}/q'
            client.send(addr, w['q_sl'].value)
            _refresh_band_labels(b)
            _refresh_curve()

        w['type'].on_value_change(on_type_change)
        w['freq_sl'].on_value_change(on_freq_change)
        w['gain_sl'].on_value_change(on_gain_change)
        w['q_sl'].on_value_change(on_q_change)

    for b in range(1, NUM_BANDS + 1):
        _wire_band(b)

    def _on_eq_on_click():
        if current_ch[0] is None:
            return
        cur = client.get(f'/ch/{current_ch[0]:02d}/eq/on')
        new_val = 0 if (cur == 1 or cur is None) else 1
        client.send(f'/ch/{current_ch[0]:02d}/eq/on', new_val)
        _update_eq_on_btn(new_val)

    def _update_eq_on_btn(val):
        if val == 1:
            eq_on_btn.props('color=positive outline')
            eq_on_btn.set_text('EQ ON')
        else:
            eq_on_btn.props('color=grey-8 flat')
            eq_on_btn.set_text('EQ OFF')

    eq_on_btn.on_click(_on_eq_on_click)

    def _load_channel(ch: int):
        """Query all EQ params for ch, populate sliders."""
        current_ch[0] = ch
        ch_lbl.set_text(f'EQ: CH {ch:02d}')
        snap = client.snapshot()

        # populate from existing snapshot first (instant), then query mixer
        for b in range(1, NUM_BANDS + 1):
            w = band_widgets[b]
            prefix = f'/ch/{ch:02d}/eq/{b}'
            raw[b]['f']    = float(snap.get(f'{prefix}/f')    or 0.5)
            raw[b]['g']    = float(snap.get(f'{prefix}/g')    or 0.5)
            raw[b]['q']    = float(snap.get(f'{prefix}/q')    or 0.5)
            raw[b]['type'] = int(snap.get(f'{prefix}/type')   or 2)
            w['freq_sl'].set_value(raw[b]['f'])
            w['gain_sl'].set_value(raw[b]['g'])
            w['q_sl'].set_value(raw[b]['q'])
            w['type'].set_value(raw[b]['type'])
            _refresh_band_labels(b)

        eq_on = int(snap.get(f'/ch/{ch:02d}/eq/on') or 1)
        _update_eq_on_btn(eq_on)
        _refresh_curve()

        # also trigger background queries for fresh data
        import threading
        def _query():
            import time
            if client._mixer:
                for b in range(1, NUM_BANDS + 1):
                    for param in ('f', 'g', 'q', 'type'):
                        client._mixer.query(f'/ch/{ch:02d}/eq/{b}/{param}')
                client._mixer.query(f'/ch/{ch:02d}/eq/on')
        threading.Thread(target=_query, daemon=True).start()

    def _close():
        active_ch[0] = None
        panel.set_visibility(False)
        eq_visible[0] = False

    # ── poll hook (called by app.py's ui.timer) ────────────────────────
    def poll():
        target = active_ch[0]

        if target is None:
            if eq_visible[0]:
                _close()
            return

        if target != current_ch[0]:
            _load_channel(target)
            panel.set_visibility(True)
            eq_visible[0] = True
            return

        # update curve if any EQ address changed in snapshot
        snap = client.snapshot()
        changed = False
        for b in range(1, NUM_BANDS + 1):
            prefix = f'/ch/{current_ch[0]:02d}/eq/{b}'
            for param in ('f', 'g', 'q', 'type'):
                val = snap.get(f'{prefix}/{param}')
                if val is not None and abs(float(val) - raw[b][param]) > 0.002:
                    raw[b][param] = float(val)
                    changed = True
        if changed:
            _refresh_curve()

    return poll
