from nicegui import ui
from mixer.client import MixerClient
from mixer.discovery import DiscoveryScanner


CONNECTION_TYPES = [
    {'id': 'network', 'label': 'Network',     'available': True},
    {'id': 'usb',     'label': 'USB',         'available': False},
    {'id': 'ap',      'label': 'Direct WiFi', 'available': False},
]


def setup_connect_page(client: MixerClient):
    @ui.page('/')
    def connect_page():
        ui.add_head_html('<style>body { background: #111827; }</style>')

        scanner = DiscoveryScanner()
        selected_ip: list[str | None] = [None]
        mixer_btns: dict[str, ui.button] = {}

        with ui.column().classes('items-center justify-center min-h-screen w-full bg-gray-900'):
            with ui.card().classes('w-[480px] bg-gray-800 rounded-2xl p-8 gap-6 shadow-2xl'):

                ui.label('MR18 Controller').classes('text-white text-2xl font-bold tracking-wide')
                ui.separator().classes('border-gray-700')

                ui.label('Connection Type').classes('text-gray-400 text-xs uppercase tracking-widest')
                with ui.row().classes('gap-2'):
                    for ct in CONNECTION_TYPES:
                        btn = ui.button(ct['label']).classes('rounded-lg px-4 py-2 text-sm font-medium')
                        if ct['available']:
                            btn.props('color=primary outline')
                        else:
                            btn.props('color=grey-8 flat disable')
                            btn.tooltip('Coming soon')

                ui.separator().classes('border-gray-700')

                ui.label('Available Mixers').classes('text-gray-400 text-xs uppercase tracking-widest')

                mixer_list = ui.column().classes('w-full gap-2 min-h-[100px]')

                with mixer_list:
                    scan_row = ui.row().classes('items-center gap-2 text-gray-500 text-sm py-2')
                    with scan_row:
                        ui.spinner(size='sm')
                        ui.label('Scanning for mixers on the network…')

                connect_btn = (
                    ui.button('Connect', on_click=lambda: do_connect())
                    .classes('w-full rounded-lg text-sm font-semibold mt-2')
                    .props('color=primary disable')
                )

        def select(ip: str):
            selected_ip[0] = ip
            connect_btn.props(remove='disable')
            for r_ip, b in mixer_btns.items():
                if r_ip == ip:
                    b.classes(remove='bg-gray-700', add='bg-blue-900 ring-2 ring-blue-500')
                else:
                    b.classes(remove='bg-blue-900 ring-2 ring-blue-500', add='bg-gray-700')

        def refresh_list():
            mixers = dict(scanner.mixers)
            if mixers and scan_row.visible:
                scan_row.set_visibility(False)

            for ip, info in mixers.items():
                if ip in mixer_btns:
                    continue
                with mixer_list:
                    b = (
                        ui.button(on_click=lambda _ip=ip: select(_ip))
                        .classes('w-full rounded-lg px-4 py-3 bg-gray-700 text-left')
                        .props('flat no-caps align=left')
                    )
                    with b:
                        with ui.column().classes('gap-0 items-start'):
                            ui.label(info['model']).classes('text-white font-semibold text-sm')
                            meta = ' · '.join(filter(None, [info.get('name'), ip]))
                            ui.label(meta).classes('text-gray-400 text-xs')
                    mixer_btns[ip] = b

        def do_connect():
            if not selected_ip[0]:
                return
            scanner.stop()
            client.connect(selected_ip[0])
            ui.navigate.to('/mixer')

        scanner.start()
        ui.timer(0.5, refresh_list)
