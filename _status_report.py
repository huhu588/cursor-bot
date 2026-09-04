"""patch_status.bat 的状态报告：单次 inspect_status，复用 DNS 缓存。"""

import sand_patch as s
from dns_fix import diagnose_dns

layout = s.resolve_cursor_layout()
st = s.inspect_status(layout)
# inspect_status 内部已探测过 DNS，这里命中缓存，不再重复联网。
dns = diagnose_dns()

mode = s.get_patch_mode()
rows = [
    ("tool_version", s.TOOL_VERSION),
    ("cursor_version", layout.version),
    ("supported_cursor", s.supported_cursor_versions_label()),
    ("path", layout.install_root),
    ("mode", f"{mode} ({'server agent / one bill per turn' if mode == s.PATCH_MODE_SERVER else 'sand local loop / one bill per step'})"),
    ("patched", st.installed),
    ("stream_mode", st.stream_mode_installed),
    ("move_exec", st.move_exec_markers),
    ("exec_bridge", st.exec_bridge_markers),
    ("sand_rpc", st.sand_rpc_markers),
    ("feature_flags", st.feature_flag_markers),
    ("client_markers", st.client_markers + st.legacy_client_markers),
    ("direct_stream", st.direct_stream_markers),
    ("membership", st.membership_markers),
    ("hdrfix_v2", st.hdrfix_v2_markers),
    ("renderer_unlock", st.renderer_unlock_markers),
    ("dns_node", st.dns_node_markers),
    ("dns_hosts", st.dns_hosts_installed),
    ("dns_hijacked", dns.get("hijacked")),
    ("ide_left", st.ide_matches),
    ("files", len(st.patched_files)),
]
for key, value in rows:
    print(f"{key}: {value}")

print("status:", s.status_verdict(st, mode))
print("switch: patch_install.bat = local (sand) | patch_install_server.bat = server (big bill) | patch_restore.bat = uninstall all")
