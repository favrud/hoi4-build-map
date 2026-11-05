# -*- coding: utf-8 -*-
"""HOI4 地图改造通用自检（不启动游戏，复刻引擎的 IsMapInGoodState 检查）

用法：
    python check_mod_map.py <mod目录> [游戏根目录]

检查项（黑海填海全流程实测过，每条都对应一个真实报错）：
  A  definition.csv 行数/列数/BOM/末行 + 「land 省必须有州」「海省不能进州」「州号连续」
  B  陆地省 coastal 与 provinces.bmp 位图一致（位图优先）
  C  heightmap.bmp 只有目标省像素变化，且都高于 93
  D  terrain.bmp 目标省不能再留海色（调色板 15 = 深海蓝）
  E  每个临海陆地省恰好一条 naval_base_spawn（原版 1.19.4 是 2362:2362）
  F  每个州都有 air_base / rocket_site_spawn / bunker / anti_air_building 落点
  G  州文件里没有「已不临海却还挂着 naval_base/coastal_bunker/dockyard/naval_facility」
  H  整州没有临海省时不能留州级 dockyard
  I  舰队（fleet 块里的 naval_base / location）必须在临海省，且有海军基地
  J  adjacencies.csv 不能残留指向已填海省的海峡行

依赖 numpy + Pillow。
"""
import io
import os
import re
import struct
import sys
from collections import Counter, defaultdict

import numpy as np
from PIL import Image

SEA_TERRAIN_INDEX = 15   # terrain.bmp 调色板里深海蓝的索引


def rd(p, enc="utf-8-sig"):
    return io.open(p, encoding=enc, errors="replace").read()


def blocks_of(t, key):
    out = []
    for m in re.finditer(r"(?m)^[ \t]*" + key + r"[ \t]*=[ \t]*\{", t):
        i = t.index("{", m.start())
        depth = 0
        for k in range(i, len(t)):
            if t[k] == "{":
                depth += 1
            elif t[k] == "}":
                depth -= 1
                if depth == 0:
                    out.append((m.start(), k + 1, t[i:k]))
                    break
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    mod = os.path.abspath(sys.argv[1])
    if len(sys.argv) > 2:
        game = sys.argv[2]
    else:
        game = os.environ.get("HOI4_GAME_ROOT", "")
        if not game:
            print('缺少游戏根目录。用法：python check_mod_map.py <mod目录> "<Hearts of Iron IV 安装目录>"\n'
                  '也可以先设环境变量 HOI4_GAME_ROOT。')
            return 2
    if not os.path.isdir(os.path.join(game, "map")):
        print(f"游戏根目录不对（找不到 map/）：{game}")
        return 2
    errs, warns = [], []

    def E(m):
        errs.append(m)
        print("  X", m)

    def W(m):
        warns.append(m)
        print("  !", m)

    def ok(m):
        print("  v", m)

    # ---------- A definition.csv ----------
    print("== definition.csv")
    vraw = open(os.path.join(game, "map", "definition.csv"), "rb").read()
    mraw = open(os.path.join(mod, "map", "definition.csv"), "rb").read()
    if mraw.startswith(b"\xef\xbb\xbf"):
        E("definition.csv 带 BOM")
    if mraw.endswith(b"\n"):
        E("definition.csv 末尾多空行")
    vrows = vraw.decode("utf-8").split("\n")
    mrows = mraw.decode("utf-8").split("\n")
    if len(vrows) != len(mrows):
        E(f"行数 {len(vrows)} -> {len(mrows)}")
    typ, coastal, c2p, vtyp = {}, {}, {}, {}
    for r in mrows:
        p = r.split(";")
        if len(p) < 8 or not p[0].isdigit():
            continue
        pid = int(p[0])
        typ[pid], coastal[pid] = p[4], p[5] == "true"
        c2p[(int(p[1]), int(p[2]), int(p[3]))] = pid
        if len(p) != 8:
            E(f"列数不是 8：{r}")
    for r in vrows:
        p = r.split(";")
        if len(p) >= 8 and p[0].isdigit():
            vtyp[int(p[0])] = p[4]
    changed = sorted(p for p in typ if vtyp.get(p) and vtyp[p] != typ[p])
    added = sorted(p for p in typ if p not in vtyp)
    targets = changed + added
    print(f"  被改类型的省 {len(changed)}，新增省 {len(added)}")
    if not targets:
        W("mod 的 definition.csv 与原版没有类型差异，后面很多检查会退化")

    # ---------- 位图与邻接 ----------
    prov = np.array(Image.open(os.path.join(game, "map", "provinces.bmp")).convert("RGB"))
    codes = np.array([c[0] * 65536 + c[1] * 256 + c[2] for c in c2p], dtype=np.int64)
    pids = np.array([c2p[c] for c in c2p], dtype=np.int32)
    o = np.argsort(codes)
    cs, ps = codes[o], pids[o]
    flat = prov.reshape(-1, 3).astype(np.int64)
    pc = flat[:, 0] * 65536 + flat[:, 1] * 256 + flat[:, 2]
    idx = np.clip(np.searchsorted(cs, pc), 0, len(cs) - 1)
    ids = np.where(cs[idx] == pc, ps[idx], 0).astype(np.int32).reshape(prov.shape[:2])
    adj = defaultdict(set)
    for a, b in ((ids[:, :-1].ravel(), ids[:, 1:].ravel()), (ids[:-1, :].ravel(), ids[1:, :].ravel())):
        m = a != b
        for x, y in np.unique(np.stack([a[m], b[m]], axis=1), axis=0).tolist():
            if x and y:
                adj[int(x)].add(int(y))
                adj[int(y)].add(int(x))
    sea = {p for p, t in typ.items() if t == "sea"}
    land = [p for p, t in typ.items() if t == "land" and p]
    print("== 位图")
    ok(f"land {len(land)} / sea {len(sea)}")
    bad = [p for p in land if bool(adj[p] & sea) != coastal[p]]
    if bad:
        E(f"coastal 与位图不一致的陆地省 {len(bad)} 个：{bad[:8]}")
    else:
        ok("coastal 与位图全部一致")

    # ---------- C/D 高度图 / 地形图 ----------
    def diff_pixels(path, vpath, label):
        a = open(path, "rb").read()
        b = open(vpath, "rb").read()
        if len(a) != len(b):
            E(f"{label} 文件长度变了")
            return None
        w, h = struct.unpack("<ii", a[18:26])
        bpp = struct.unpack("<H", a[28:30])[0]
        off = struct.unpack("<I", a[10:14])[0]
        stride = (w * bpp // 8 + 3) // 4 * 4
        if (w, h) != (ids.shape[1], ids.shape[0]):
            E(f"{label} 尺寸不对")
        out = []
        for y in range(h):
            base = off + (h - 1 - y) * stride
            ra, rb = a[base:base + w], b[base:base + w]
            if ra != rb:
                for x in range(w):
                    if ra[x] != rb[x]:
                        out.append((x, y, rb[x], ra[x]))
        outside = [d for d in out if ids[d[1], d[0]] not in set(targets)]
        print(f"== {label}：{len(out)} 像素变化，落在目标省外 {len(outside)}")
        if outside:
            E(f"{label} 有 {len(outside)} 个像素在目标省外被改了")
        return out

    d = diff_pixels(os.path.join(mod, "map", "heightmap.bmp"),
                    os.path.join(game, "map", "heightmap.bmp"), "heightmap.bmp")
    if d:
        low = [x for x in d if x[3] <= 93]
        print("  新高度取值:", dict(Counter(x[3] for x in d)))
        if low:
            E(f"有 {len(low)} 个像素高度 <= 93，可能仍被判成水面")
    d = diff_pixels(os.path.join(mod, "map", "terrain.bmp"),
                    os.path.join(game, "map", "terrain.bmp"), "terrain.bmp")
    if d:
        still_sea = [x for x in d if x[3] == SEA_TERRAIN_INDEX]
        print("  新地形索引:", dict(Counter(x[3] for x in d)))
        if still_sea:
            E(f"{len(still_sea)} 个像素还是海色索引 {SEA_TERRAIN_INDEX}")

    # ---------- 州 ----------
    print("== 州")
    files = {}
    for base in (game, mod):
        d_ = os.path.join(base, "history", "states")
        for f in os.listdir(d_):
            files[f] = os.path.join(d_, f)
    states, prov_state = {}, defaultdict(list)
    for fn, f in files.items():
        t = rd(f)
        m = re.search(r"\bid\s*=\s*(\d+)", t)
        mp = re.search(r"provinces\s*=\s*\{([^}]*)\}", t)
        if not (m and mp):
            E(f"州文件缺 id 或 provinces：{fn}")
            continue
        sid = int(m.group(1))
        states[sid] = dict(file=fn, txt=t, provs=[int(x) for x in re.findall(r"\d+", mp.group(1))])
        for p in states[sid]["provs"]:
            prov_state[p].append(sid)
    have = set(states)
    gaps = [i for i in range(1, max(have) + 1) if i not in have]
    print(f"  州 {len(states)}，最大 {max(have)}，空号 {len(gaps)}")
    if gaps:
        E(f"州号空缺 {len(gaps)} 个（游戏会报 Definition for state id 缺失）：{gaps[:10]}")
    miss = [p for p in land if not prov_state.get(p)]
    if miss:
        E(f"陆地省没有州 {len(miss)} 个：{miss[:8]}")
    else:
        ok("每个陆地省都有州")
    s_in_st = [p for p in prov_state if p in sea]
    if s_in_st:
        E(f"海省被塞进州：{s_in_st[:8]}")
    dup = [p for p, v in prov_state.items() if len(v) > 1]
    if dup:
        E(f"省属于多个州：{dup[:8]}")

    # 每州 manpower 必须 > 0（荒地州也不例外，否则报 State #X has no people living in it）
    for sid, s in states.items():
        mm = re.search(r"\bmanpower\s*=\s*(\d+)", s["txt"])
        if not mm:
            E(f"州 {sid} 没写 manpower")
        elif int(mm.group(1)) == 0:
            E(f"州 {sid} 的 manpower = 0（会报 State #{sid} has no people living in it）")

    # ---------- 战略区 ----------
    print("== 战略区")
    srs = {}
    for base in (game, mod):
        d_ = os.path.join(base, "map", "strategicregions")
        if not os.path.isdir(d_):
            continue        # mod 没覆盖战略区是常态
        for f in os.listdir(d_):
            t = rd(os.path.join(d_, f))
            m = re.search(r"\bid\s*=\s*(\d+)", t)
            mp = re.search(r"provinces\s*=\s*\{([^}]*)\}", t)
            if not (m and mp):
                continue
            srs[int(m.group(1))] = [int(x) for x in re.findall(r"\d+", mp.group(1))]
    prov_sr = defaultdict(list)
    for rid, provs in srs.items():
        for p in provs:
            prov_sr[p].append(rid)
    no_sr = [p for p in land if not prov_sr.get(p)]
    if no_sr:
        E(f"陆地省没有战略区 {len(no_sr)} 个"
          f"（MAP_ERROR: The land province X has no strategic region assigned）：{no_sr[:8]}")
    else:
        ok("每个陆地省都有战略区")
    # 只检查「被这次改动碰过」的战略区：原版本身就有 40+ 个岛群战略区在像素上不连通
    vsrs = {}
    d_ = os.path.join(game, "map", "strategicregions")
    for f in os.listdir(d_):
        t = rd(os.path.join(d_, f))
        m = re.search(r"(?m)^\s*id\s*=\s*(\d+)", t)
        mp = re.search(r"provinces\s*=\s*\{([^}]*)\}", t)
        if m and mp:
            vsrs[int(m.group(1))] = [int(x) for x in re.findall(r"\d+", mp.group(1))]
    touched = [rid for rid, provs in srs.items()
               if set(provs) != set(vsrs.get(rid, [])) or set(provs) & set(targets)]
    for rid in touched:
        provs = srs[rid]
        pool = set(p for p in provs if p in adj)
        if len(pool) < 2:
            continue
        comp = []
        while pool:
            stack, grp = [next(iter(pool))], set()
            while stack:
                c = stack.pop()
                if c in grp:
                    continue
                grp.add(c)
                stack += [n for n in adj[c] if n in pool and n not in grp]
            pool -= grp
            comp.append(grp)
        if len(comp) > 1:
            W(f"战略区 {rid} 不连通（MAP_ERROR: Strategic region {rid} is fractioned!），"
              f"分离出 {len(comp) - 1} 块：{sorted(min(x) for x in comp[1:])[:6]}")

    # ---------- G/H 州文件里的失效海军建筑 ----------
    badb, bad_dock = [], []
    for sid, s in states.items():
        for m in re.finditer(r"(?m)^[ \t]*(\d+)[ \t]*=[ \t]*\{", s["txt"]):
            pid = int(m.group(1))
            i = s["txt"].index("{", m.start())
            depth = 0
            for k in range(i, len(s["txt"])):
                if s["txt"][k] == "{":
                    depth += 1
                elif s["txt"][k] == "}":
                    depth -= 1
                    if depth == 0:
                        body = s["txt"][i:k]
                        break
            for key in ("naval_base", "coastal_bunker", "dockyard", "naval_facility"):
                if re.search(r"\b" + key + r"\s*=\s*\d+", body) and not (adj[pid] & sea):
                    badb.append((sid, pid, key))
        if any(re.match(r"^\s*dockyard\s*=\s*\d+", ln) for ln in s["txt"].split("\n")):
            if not any(adj[p] & sea for p in s["provs"] if p in land):
                bad_dock.append(sid)
    print("== 州内海军建筑")
    for b in badb:
        E(f"州 {b[0]} 省 {b[1]} 已不临海还挂着 {b[2]}")
    for b in bad_dock:
        E(f"州 {b} 无临海省却还留着 dockyard")
    if not badb and not bad_dock:
        ok("没有失效的海军建筑")

    # ---------- I 舰队 ----------
    nb_level = {}
    for sid, s in states.items():
        for m in re.finditer(r"(?m)^[ \t]*(\d+)[ \t]*=[ \t]*\{", s["txt"]):
            pid = int(m.group(1))
            i = s["txt"].index("{", m.start())
            depth = 0
            for k in range(i, len(s["txt"])):
                if s["txt"][k] == "{":
                    depth += 1
                elif s["txt"][k] == "}":
                    depth -= 1
                    if depth == 0:
                        body = s["txt"][i:k]
                        break
            mm = re.search(r"\bnaval_base\s*=\s*(\d+)", body)
            if mm:
                nb_level[pid] = int(mm.group(1))
    print("== 舰队")
    bad_fleet = []
    for fn in os.listdir(os.path.join(game, "history", "units")):
        p = os.path.join(mod, "history", "units", fn)
        if not os.path.exists(p):
            p = os.path.join(game, "history", "units", fn)
        t = rd(p)
        for _, _, body in blocks_of(t, "fleet"):
            for m in re.finditer(r"(naval_base|location)\s*=\s*(\d+)", body):
                pid = int(m.group(2))
                if not (adj[pid] & sea):
                    bad_fleet.append((fn, m.group(0), "已不临海"))
                elif m.group(1) == "naval_base" and pid not in nb_level:
                    bad_fleet.append((fn, m.group(0), "该省没有海军基地"))
    for b in bad_fleet:
        E(f"OOB {b[0]}：{b[1]} {b[2]}")
    if not bad_fleet:
        ok("舰队母港全部有效（注意：陆军 division 的 location 在内陆省是正常的）")

    # ---------- E/F buildings.txt ----------
    print("== buildings.txt")
    bt = open(os.path.join(mod, "map", "buildings.txt"), "rb").read()
    if bt.endswith(b"\n"):
        E("buildings.txt 末尾多空行（会报 invalid arguments count）")
    blines = bt.decode("utf-8").split("\n")
    badrow = [l for l in blines if len(l.split(";")) != 7]
    if badrow:
        E(f"列数不是 7 的行 {len(badrow)}：{badrow[:3]}")
    n_coastal = sum(1 for p in land if adj[p] & sea)
    for kind in ("naval_base_spawn", "coastal_bunker"):
        n = sum(1 for l in blines if len(l.split(";")) == 7 and l.split(";")[1] == kind)
        print(f"  {kind} {n} 条 / 临海陆地省 {n_coastal} 个")
        if n != n_coastal:
            E(f"{kind} 与临海省不是 1:1（差 {n_coastal - n}）"
              f"——少的那几个省会被判 setup as coastal but has no port building")
    need = {"air_base", "rocket_site_spawn", "bunker", "anti_air_building"}
    by_state = defaultdict(set)
    for l in blines:
        p = l.split(";")
        if len(p) == 7:
            try:
                by_state[int(p[0])].add(p[1])
            except ValueError:
                pass
    for sid in states:
        lack = need - by_state.get(sid, set())
        if lack:
            E(f"州 {sid} 缺落点 {sorted(lack)}")

    # ---------- J adjacencies ----------
    print("== adjacencies.csv")
    ap = os.path.join(mod, "map", "adjacencies.csv")
    if os.path.exists(ap):
        tset = {str(t) for t in targets}
        left = [ln for ln in rd(ap).split("\n")
                if len(ln.split(";")) >= 2 and (ln.split(";")[0].strip() in tset
                                                or ln.split(";")[1].strip() in tset)]
        for ln in left:
            E(f"海峡行仍指向已填海省：{ln}")
        if not left:
            ok("没有残留的海峡行")
    else:
        print("  (没有覆盖 adjacencies.csv，若目标省有海峡行就会残留)")

    print("\n========== 汇总：错误 %d / 警告 %d" % (len(errs), len(warns)))
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
