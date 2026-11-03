#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""HOI4 地图自检：不启动游戏，先把八成地图错误挑出来。

用法：
    python map_selfcheck.py <mod目录> [游戏根目录]

检查项（对应游戏 IsMapInGoodState 的主要规则）：
  1 空战略区
  2 不属于任何战略区的省
  3 同属多个战略区的省（原版也有，仅提示）
  4 陆地省没有州
  5 海洋省被塞进州
  6 同属多个州的省
  7 州内省份跨战略区（原版也有，仅提示）
  8 海军基地所在省不贴海
  9 州号是否连续（新州最容易踩的坑）
需要 python3 + numpy + Pillow。
"""
import glob
import io
import os
import re
import sys
from collections import defaultdict

import numpy as np
from PIL import Image


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "."
    game = sys.argv[2] if len(sys.argv) > 2 else r"D:\Steam\steamapps\common\Hearts of Iron IV"
    mod = os.path.abspath(mod)
    rows = io.open(os.path.join(mod, "map", "definition.csv"), encoding="utf-8",
                   errors="replace").read().split("\n")

    typ, coastal, color2pid = {}, {}, {}
    for r in rows:
        p = r.split(";")
        if len(p) >= 8:
            pid = int(p[0])
            typ[pid] = p[4]
            coastal[pid] = p[5]
            color2pid[(int(p[1]), int(p[2]), int(p[3]))] = pid
    land = [p for p, t in typ.items() if t == "land"]
    sea = {p for p, t in typ.items() if t == "sea"}
    print(f"省 {len(typ)}：land {len(land)} / sea {len(sea)} / "
          f"lake {sum(1 for t in typ.values() if t == 'lake')}")

    # ---- 战略区（mod 覆盖同名文件优先）----
    regions = {}
    for base in (game, mod):
        d = os.path.join(base, "map", "strategicregions")
        for f in glob.glob(os.path.join(d, "*.txt")):
            t = io.open(f, encoding="utf-8-sig", errors="replace").read()
            m = re.search(r"id\s*=\s*(\d+)", t)
            if not m:
                continue
            mp = re.search(r"provinces\s*=\s*\{([^}]*)\}", t)
            regions[int(m.group(1))] = dict(
                provs=[int(x) for x in re.findall(r"\d+", mp.group(1))] if mp else [],
                naval="naval_terrain" in t,
                file=os.path.basename(f),
                from_mod=base == mod)
    prov_regions = defaultdict(list)
    for rid, info in regions.items():
        for p in info["provs"]:
            prov_regions[p].append(rid)

    print("[1] 空战略区：", [r for r, i in regions.items() if not i["provs"]] or "无")
    print("[2] 不属于任何战略区的省：", [p for p in typ if p and p not in prov_regions][:10] or "无")
    multi = {p: r for p, r in prov_regions.items() if len(r) > 1}
    print(f"[3] 同属多个战略区的省：{len(multi)}（原版本身就有，仅提示）")

    # ---- 州 ----
    files = {}
    for base in (game, mod):
        for f in glob.glob(os.path.join(base, "history", "states", "*.txt")):
            files[os.path.basename(f)] = f
    state_provs, prov_state, state_ids = {}, defaultdict(list), []
    for fn, f in files.items():
        t = io.open(f, encoding="utf-8-sig", errors="replace").read()
        m = re.search(r"id\s*=\s*(\d+)", t)
        if not m:
            print("  !! 州文件没有 id：", fn)
            continue
        sid = int(m.group(1))
        state_ids.append(sid)
        mp = re.search(r"provinces\s*=\s*\{([^}]*)\}", t)
        state_provs[sid] = [int(x) for x in re.findall(r"\d+", mp.group(1))] if mp else []
        for p in state_provs[sid]:
            prov_state[p].append(sid)

    print("[4] 陆地省没有州：", [p for p in land if p and not prov_state.get(p)][:10] or "无")
    print("[5] 海洋省被塞进州：", [p for p in prov_state if typ.get(p) == "sea"][:10] or "无")
    print("[6] 同属多个州的省：", {p: v for p, v in prov_state.items() if len(v) > 1} or "无")

    bad_area = []
    for sid, provs in state_provs.items():
        rs = set()
        for p in provs:
            rs.update(prov_regions.get(p, []))
        if len(rs) > 1:
            bad_area.append((sid, sorted(rs)))
    print(f"[7] 州内省份跨战略区：{len(bad_area)}（原版也有，仅提示）")

    gaps = []
    if state_ids:
        have = set(state_ids)
        for i in range(1, max(state_ids) + 1):
            if i not in have:
                gaps.append(i)
    print(f"[9] 州号空缺：{len(gaps)} 个"
          f"{'（前 10：' + str(gaps[:10]) + '）' if gaps else ''}  <-- 必须为 0，否则报 Map definition error")

    # ---- 位图：邻接关系 ----
    bmp = os.path.join(game, "map", "provinces.bmp")
    if not os.path.exists(bmp):
        print("!! 找不到 provinces.bmp，跳过 [8]")
        return
    codes = np.array([c[0] * 65536 + c[1] * 256 + c[2] for c in color2pid], dtype=np.int64)
    pids = np.array([color2pid[c] for c in color2pid], dtype=np.int32)
    o = np.argsort(codes)
    codes_s, pids_s = codes[o], pids[o]
    prov = np.array(Image.open(bmp).convert("RGB"))
    flat = prov.reshape(-1, 3).astype(np.int64)
    pc = flat[:, 0] * 65536 + flat[:, 1] * 256 + flat[:, 2]
    idx = np.clip(np.searchsorted(codes_s, pc), 0, len(codes_s) - 1)
    ids = np.where(codes_s[idx] == pc, pids_s[idx], 0).astype(np.int32).reshape(prov.shape[:2])

    def nbrs(pid):
        m = ids == pid
        nb = np.zeros_like(m)
        nb[1:, :] |= m[:-1, :]
        nb[:-1, :] |= m[1:, :]
        nb[:, 1:] |= m[:, :-1]
        nb[:, :-1] |= m[:, 1:]
        nb &= ~m
        return set(int(x) for x in np.unique(ids[nb]) if x)

    bad_ports, bad_coastal = [], []
    for fn, f in files.items():
        t = io.open(f, encoding="utf-8-sig", errors="replace").read()
        for m in re.finditer(r"(\d+)\s*=\s*\{\s*[^}]*?naval_base\s*=\s*(\d+)", t, re.S):
            pid = int(m.group(1))
            if not (nbrs(pid) & sea):
                bad_ports.append((fn, pid))
    for pid in land:
        if bool(nbrs(pid) & sea) != (coastal.get(pid) == "true"):
            bad_coastal.append(pid)
    print(f"[8] 海军基地所在省不贴海：{bad_ports[:8] or '无'}")
    print(f"[+ ] coastal 与位图不一致的陆地省：{len(bad_coastal)} {bad_coastal[:10]}")


if __name__ == "__main__":
    main()
