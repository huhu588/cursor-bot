"""沙盒演练（修正基线）：磁盘文件当前已打补丁，故先 uninstall 得到"干净基线"，
再从干净基线做 install -> uninstall，验证字节级还原。"""

import hashlib

import sand_patch as s

layout = s.resolve_cursor_layout()
print(f"Cursor {layout.version}  {layout.install_root}\n")

ok = True
bridge_total = 0
sand_rpc_total = 0
has_477 = False
has_675 = False
sand_rpc_477 = 0
sand_rpc_675 = 0
sand_rpc_61 = 0
direct_stream_total = 0
managed_local_total = 0
identity_total = 0
enablement_total = 0


def unpatch(text: str, name: str) -> str:
    out, _ = s.remove_patch_from_content(text)
    if name in s.DNS_NODE_TARGETS:
        out, _ = s.remove_dns_node_patch(out)
    return out


def patch(text: str, name: str):
    out, st = s.apply_patch_to_content(text)
    if name in s.DNS_NODE_TARGETS:
        out, n = s.apply_dns_node_patch(out)
        st.dns_node += n
    return out, st


for path in layout.target_paths:
    if not path.is_file():
        continue
    name = path.name
    if name == "477.js":
        has_477 = True
    if name == "675.js":
        has_675 = True
    disk = s._decode_js(path.read_bytes(), path)

    clean = unpatch(disk, name)
    clean_again = unpatch(clean, name)
    if clean != clean_again:
        ok = False
        print(f"  [FAIL] uninstall not idempotent: {name}")

    leftovers = [m for m in s._ALL_SAND_MARKERS if m in clean]
    if leftovers:
        ok = False
        print(f"  [FAIL] {name} leftover after unpatch: {leftovers}")

    h_clean = hashlib.sha256(clean.encode("utf-8")).hexdigest()

    patched, st = patch(clean, name)
    bridge_total += st.exec_bridge
    sand_rpc_total += st.sand_rpc
    direct_stream_total += st.direct_stream
    managed_local_total += st.managed_local_route
    identity_total += st.agent_host_identity
    enablement_total += st.agent_host_enablement
    if name == "477.js":
        sand_rpc_477 = st.sand_rpc
        if st.sand_rpc < 1:
            ok = False
            print(f"  [FAIL] {name} sand_rpc={st.sand_rpc} (expect >= 1)")
    if name == "675.js":
        sand_rpc_675 = st.sand_rpc
        if st.direct_stream < 1:
            ok = False
            print(f"  [FAIL] {name} direct_stream={st.direct_stream} (expect >= 1)")
        if st.sand_rpc < 1:
            ok = False
            print(f"  [FAIL] {name} sand_rpc={st.sand_rpc} (expect >= 1)")
    if name == "61.js":
        sand_rpc_61 = st.sand_rpc
        if st.managed_local_route < 1:
            ok = False
            print(f"  [FAIL] {name} managed_local_route={st.managed_local_route} (expect >= 1)")

    patched2, _ = patch(patched, name)
    if patched2 != patched:
        ok = False
        print(f"  [FAIL] install not idempotent: {name}")

    back = unpatch(patched, name)
    h_back = hashlib.sha256(back.encode("utf-8")).hexdigest()
    identical = h_back == h_clean

    if not identical:
        ok = False

    flag = "OK " if identical and not leftovers else "FAIL"
    print(
        f"  [{flag}] {name:30s} install={st.total:3d} bridge={st.exec_bridge} "
        f"sand_rpc={st.sand_rpc:2d} ds={st.direct_stream} route={st.managed_local_route} "
        f"roundtrip_identical={identical}"
    )
    if not identical:
        for i in range(min(len(clean), len(back))):
            if clean[i] != back[i]:
                print(f"         first diff @ {i}")
                print(f"         clean: {clean[max(0,i-90):i+70]!r}")
                print(f"         back : {back[max(0,i-90):i+70]!r}")
                break
        else:
            print(f"         length differs: clean={len(clean)} back={len(back)}")

print()
print(f"exec_bridge total: {bridge_total} (expect 2)")
print(
    f"stream pieces: direct={direct_stream_total} route={managed_local_total} "
    f"identity={identity_total} enable={enablement_total}"
)
if has_477:
    print(f"sand_rpc total: {sand_rpc_total} (477.js sand_rpc={sand_rpc_477}, expect >= 1)")
if has_675:
    print(
        f"sand_rpc total: {sand_rpc_total} (675.js sand_rpc={sand_rpc_675}, "
        f"61.js sand_rpc={sand_rpc_61})"
    )
if not has_477 and not has_675:
    print(f"sand_rpc total: {sand_rpc_total} (no 477.js/675.js in layout)")
expect_sand = ((not has_477) or sand_rpc_477 >= 1) and ((not has_675) or sand_rpc_675 >= 1)
stream_ok = (not has_675) or (
    direct_stream_total >= 1
    and managed_local_total >= 1
    and identity_total >= 1
    and enablement_total >= 1
)
print(
    "DRY-RUN CYCLE:",
    "OK" if ok and bridge_total == 2 and expect_sand and stream_ok else "FAILED",
)
