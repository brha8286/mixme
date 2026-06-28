from nicegui import ui
from mixer.client import MixerClient, NUM_STRIPS
from mixer.pipewire import AirPlayControl
from .strip import airplay_strip, fader_strip
from .eq import setup_eq_panel

_airplay_control = AirPlayControl()
_airplay_control.start()


def setup_page(client: MixerClient):
    @ui.page('/mixer')
    def index():
        ui.add_head_html('<style>body { background: #111827; }</style>')

        registry: dict = {}
        active_ch: list = [None]
        was_connected: list = [False]

        with ui.column().classes('gap-0 w-full min-h-screen bg-gray-900 p-0'):
            # ── header ──────────────────────────────────────────────────
            with ui.row().classes('items-center gap-3 px-4 py-2 bg-gray-950 w-full'):
                ui.label('MR18').classes('text-white font-bold text-lg tracking-widest')
                status_dot = ui.element('div').style(
                    'width:10px; height:10px; border-radius:50%; background:#ef4444;'
                )
                status_lbl = ui.label('Connecting…').classes('text-xs text-gray-400')

            # ── channel strips ───────────────────────────────────────────
            with ui.row().classes(
                'flex-nowrap gap-1 overflow-x-auto px-3 py-4 w-full items-end'
            ):
                for ch in range(1, NUM_STRIPS + 1):
                    fader_strip(
                        bottom_label=f'{ch:02d}',
                        fader_addr=f'/ch/{ch:02d}/mix/fader',
                        mute_addr=f'/ch/{ch:02d}/mix/on',
                        client=client,
                        registry=registry,
                        active_ch=active_ch,
                        ch=ch,
                        name_addr=f'/ch/{ch:02d}/config/name',
                    )

                ui.element('div').style(
                    'width:2px; background:#374151; flex-shrink:0; '
                    'align-self:stretch; margin:0 4px;'
                )

                fader_strip(
                    bottom_label='LR',
                    fader_addr='/lr/mix/fader',
                    mute_addr='/lr/mix/on',
                    client=client,
                    registry=registry,
                    active_ch=active_ch,
                    ch=None,
                )

                ui.element('div').style(
                    'width:2px; background:#374151; flex-shrink:0; '
                    'align-self:stretch; margin:0 4px;'
                )

                ap_poll = airplay_strip(_airplay_control)

        # ── EQ panel (fixed bottom) ──────────────────────────────────────
        eq_poll = setup_eq_panel(client, registry, active_ch)

        # ── disconnect overlay ───────────────────────────────────────────
        with ui.element('div').classes(
            'fixed inset-0 z-50 flex items-center justify-center'
        ).style('background:rgba(17,24,39,0.85); backdrop-filter:blur(4px)') as overlay:
            with ui.card().classes('bg-gray-800 rounded-2xl p-8 shadow-2xl text-center gap-4').style('max-width:360px'):
                ui.icon('wifi_off').classes('text-red-400 text-5xl mx-auto')
                ui.label('Mixer Disconnected').classes('text-white text-xl font-bold')
                ui.label('The MR18 is no longer reachable on the network.').classes('text-gray-400 text-sm')
                ui.button('Back to Connection Page', on_click=lambda: ui.navigate.to('/')).classes(
                    'w-full rounded-lg text-sm font-semibold mt-2'
                ).props('color=primary')
        overlay.set_visibility(False)

        # ── poll loop ────────────────────────────────────────────────────
        def poll():
            if client.connected:
                was_connected[0] = True
                status_dot.style(
                    'width:10px; height:10px; border-radius:50%; background:#22c55e;'
                )
                overlay.set_visibility(False)
            else:
                status_dot.style(
                    'width:10px; height:10px; border-radius:50%; background:#ef4444;'
                )
                if was_connected[0]:
                    overlay.set_visibility(True)
            status_lbl.set_text(client.status)

            state = client.snapshot()
            for addr, updater in registry.items():
                val = state.get(addr)
                if val is not None:
                    try:
                        updater(val)
                    except Exception:
                        pass

            eq_poll()
            ap_poll()

        ui.timer(0.2, poll)
