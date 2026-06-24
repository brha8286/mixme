from nicegui import ui
from mixer.client import MixerClient, NUM_STRIPS
from .strip import fader_strip
from .eq import setup_eq_panel


def setup_page(client: MixerClient):
    @ui.page('/mixer')
    def index():
        ui.add_head_html('<style>body { background: #111827; }</style>')

        registry: dict = {}
        active_ch: list = [None]

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

        # ── EQ panel (fixed bottom) ──────────────────────────────────────
        eq_poll = setup_eq_panel(client, registry, active_ch)

        # ── poll loop ────────────────────────────────────────────────────
        def poll():
            if client.connected:
                status_dot.style(
                    'width:10px; height:10px; border-radius:50%; background:#22c55e;'
                )
            else:
                status_dot.style(
                    'width:10px; height:10px; border-radius:50%; background:#ef4444;'
                )
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

        ui.timer(0.2, poll)
