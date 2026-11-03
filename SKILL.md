---
name: hoi4-build-map
description: "当你要改动 HOI4 的**地图本体**时使用——把海洋省填成陆地、新增陆地省份、新建州、改海岸线、清理因此失效的港口/船坞/舰队、以及给新州补 nudger（map/buildings.txt）建筑点。含 2026-11-03 实测踩过的七个硬坑（州号必须连续、buildings.txt 按坐标判省、空 task_force 必崩、coastal 要与位图一致等）、地图坐标换算拟合式与反查验证法。凡是要动 map/definition.csv、heightmap.bmp、history/states、history/units 的海军 OOB、或 map/buildings.txt 时调用。"
---

# HOI4 地图改造（填海 / 新增陆地）

## 一句话原理

**海省变陆省 = 只改 `map/definition.csv` 里那一行的类型字段**，其余全部是配套：
高度图（不然是平的）、州（不然陆地省没归属）、战略区（决定天气/隶属）、
海岸线标记、港口与舰队（原地失效）、nudger 建筑点（新州没有落点会报错）。

---

## 一、先认清楚这几个文件

| 文件 | 作用 | 改动方式 |
|---|---|---|
| `map/definition.csv` | 省的唯一真相：`id;R;G;B;类型;海岸;地形;大陆` | 整份覆盖，逐行改 |
| `map/provinces.bmp` | 省份像素归属（决定邻接关系） | **通常不用动**；切分新省才需要 |
| `map/heightmap.bmp` | 高度（8bpp 灰度，和 provinces.bmp 同尺寸） | 字节级改像素，别用 Pillow 重编码 |
| `map/strategicregions/*.txt` | 战略区（天气、空军/海军分区） | 省份全变陆地则删 `naval_terrain` 行 |
| `history/states/*.txt` | 州：归属、核心、建筑、省份列表 | 新建州文件 |
| `history/units/*_naval*.txt` | 各国开局舰队（`location`/`naval_base`） | 换港口或整队删除 |
| `map/buildings.txt` | nudger 建筑点：`州id;类型;x;y;z;旋转;省id/0` | 追加行 |

`definition.csv` 的字段：

```
1434;7;0;240;land;false;forest;1
 ↑省号 ↑RGB       ↑类型 ↑海岸 ↑地形 ↑大陆(1=欧洲)
```

海洋省是 `sea;true/false;ocean;0`；陆地省必须 `land`，且大陆编号不能是 0。

---

## 二、标准流程

### 0. 定位目标省
从 `map/strategicregions/<id>-<名字>.txt` 的 `provinces = { ... }` 里拿省号列表。
（用户说的“XX 海湾 ID 206”通常就是这个战略区 id。）

### 1. 改 definition.csv

```python
# 逐行读、只改目标行、保持「无 BOM + LF + 末行不加换行」
rows = open(SRC, encoding="utf-8").read().split("\n")   # 原版末行无换行
for i, line in enumerate(rows):
    p = line.split(";")
    if len(p) >= 8 and p[0].isdigit() and int(p[0]) in TARGETS:
        p[4], p[5], p[6], p[7] = "land", "false", TERRAIN, "1"
        rows[i] = ";".join(p)
open(DST, "w", encoding="utf-8", newline="\n").write("\n".join(rows))
```

地形取值跟邻居一致（森林/平原/丘陵都行）；**大陆编号用 1**，海洋省的 0 不能留。

### 2. 抬高度图（字节级，不要重新编码）

Pillow 存回的 BMP 会和原版差两万多个字节，虽然多半也能读，但这里是“能少一个变量就少一个”的地方：

```python
raw = bytearray(open(SRC_HM, "rb").read())
w, h = struct.unpack("<ii", raw[18:26]); bpp = struct.unpack("<H", raw[28:30])[0]
dataoff = struct.unpack("<I", raw[10:14])[0]
stride = (w * bpp // 8 + 3) // 4 * 4
for y, x in zip(ys, xs):                      # 该省所有像素
    raw[dataoff + (h - 1 - y) * stride + x] = 94   # 邻居陆地的平均高度
```

BMP 是自下而上存的，`h-1-y` 别写错。值取「四邻陆地省的平均高度」，实测波罗的海一带是 93–94。

### 3. 新建州

```txt
state = {
	id = 1082
	name = "STATE_1082"
	manpower = 1000
	state_category = wasteland

	history = {
		owner = EST
		add_core_of = EST
		buildings = { infrastructure = 0 }
	}

	provinces = { 1434 1660 1885 }
	local_supplies = 0.0
}
```

**州号必须连续**：从原版最大州号 + 1 开始一格格排，中间不许有空号（见坑 1）。

### 4. 战略区

- 整个战略区的省**全部**变陆地 → 复制该文件到 mod，删掉 `naval_terrain=water_*` 那一行（纯陆地战略区）。
- 战略区里**仍有海洋省** → 保持原样，别删。
- 不要新建战略区：原版本来就有几十个「陆海混合」的区域，混合是合法的。

### 5. 内陆化善后（最容易漏）

海没了，原先挂在海岸上的东西全部失效：

| 对象 | 判定 | 处理 |
|---|---|---|
| 海军基地 `naval_base` | 省的位图四邻不再有海省 | 从州文件删掉 `pid = { naval_base = N }` 块 |
| 船坞 `dockyard` | 整州海岸全失 | 删州的 `dockyard = N` |
| 海岸炮台 `coastal_bunker` | 同上 | 删 `pid = { coastal_bunker = N }` 块 |
| 开局舰队 `history/units/*_naval*.txt` | `location` / `naval_base` 指向失效港 | 有别的港就换过去；本国一个港都没了就整个 `units = { }` |

**换港时 `location` 和 `naval_base` 必须一起改**，只改一个会崩（见坑 3）。

### 6. nudger 建筑点 `map/buildings.txt`

新州必须补点，否则报
`MAP_ERROR: no air base site / rocket site / gun emplacement defined for state X`。

格式：`州id;建筑类型;x;y;z;旋转;末列`

| 类型 | 末列 | 说明 |
|---|---|---|
| `air_base` / `rocket_site_spawn` / `bunker` / `anti_air_building` | **0** | 州级建筑，按坐标判省 |
| `naval_base_spawn` | 省号 | 港口模型 |
| `supply_node` / `special_project_facility_spawn` | 省号 | 补给节点等 |

追加到原版文件末尾（**不要多留空行**，会报 `invalid arguments count`）：

```python
src = open(VANILLA_BUILDINGS, "rb").read()
assert not src.endswith(b"\n")           # 原版末行无换行
open(DST, "wb").write(src + b"\n" + "\n".join(rows).encode("ascii"))
```

---

## 三、坐标换算（必须用拟合式）

`buildings.txt` 的 x/z 与 `provinces.bmp` 像素的换算（用 660 个原版港口点最小二乘拟合，残差约 20 单位）：

```
x = 0.998392 × 像素x + 6.7569
z = -0.995527 × 像素y + 2044.5778
```

**只用两三个港口手算出来的公式误差约 12 单位，足以让点落到隔壁州**——本轮就是在这上面翻车了一次。

**每条坐标写完必须反查**：

```python
def pid_at(x, z):
    px, py = int(round((x - 6.7569) / 0.998392)), int(round((z - 2044.5778) / -0.995527))
    return ids[py, px]        # ids 是 provinces.bmp 解出的省号图
assert pid_at(x, z) == 目标省
```

---

## 四、七个硬坑（全部实测踩过）

| # | 现象 | 真因 | 修法 |
|---|---|---|---|
| 1 | 一进加载就弹「读取地图失败」，`MAP_ERROR: Definition for state id 1082 … 1199 is either missing or invalid`（一次上百条） | **州号必须连续**。用了 1200 而原版只到 1081，中间 118 个空号全被当成缺失 | 新州从「原版最大州号 + 1」开始连续编号 |
| 2 | `Province X is setup as coastal but has no port building in the nudger` | 陆地省若位图判为沿海，就必须有 nudger 港口点；**写州文件里的 `naval_base` 没用**，游戏只看 `map/buildings.txt` | 补 `naval_base_spawn` 行；或者把该省还原成海面 |
| 3 | 点「开始新游戏」必崩 | 删舰艇后留下**空 `task_force` 块**，且 `fleet` 的 `naval_base` 仍指向已变内陆的港 | `location` 与 `naval_base` 一起改；整队没港就 `units = { }` |
| 4 | 上百条 `Bitmap and province definition disagree ... coastal` | 填海后省份的临海状态变了，`definition.csv` 的 `coastal` 没跟上 | 按位图**全量重算**：陆地省看是否贴海，海洋省看是否贴陆 |
| 5 | `map building … location is not within specified state. Supposed to be 'X' but was 'Y'` | 坐标落到了隔壁州（公式不准或直接抄了别人的坐标） | 用拟合式算，并 `pid_at()` 反查 |
| 6 | `invalid arguments count` | 追加内容时多了一个空行 | 末尾不留空行 |
| 7 | `State Error: Trying to set invalid province building "coastal_bunker" to province #X` | 该省已不临海，州里还留着海岸炮台 | 删掉那块 `pid = { coastal_bunker = N }` |

另有一条经验：**别信奉“改不动就绕”**——本轮为绕开港口检查，先把 2333/2358 还原成海，结果邻居 2282/2309 又变成沿海陆地，问题原地平移。正确做法是补数据，不是改归属。

---

## 五、验证顺序（缺一不可）

1. **本地自检脚本**（不启动游戏就能查八成问题）：省→州唯一归属、省→战略区唯一归属、海的省没被塞进州、州内省份不跨战略区、港口省是否贴海、州号连续性。参考 `scripts/map_selfcheck.py`。
2. `hoi4skill validate <mod> --game-root <HOI4>` —— **0 errors 才算过**（但它查不出上面七个坑的大多数）。
3. **实机启动**，看 `Documents\Paradox Interactive\Hearts of Iron IV\logs\error.log`：
   - `MAP_ERROR` 一条都不许有；
   - `C:\Users\<用户>\Desktop` 那类位置拿到的日志若被截断，说明游戏在弹窗上被强杀，日志没冲盘。
4. 弹窗只说“地图定义有错”却不列条目时：**Steam 启动项加 `-debug`**，控制台会实时打印 `MAP_ERROR: ...` 原文，一次就能定位。若游戏仍静默，用 `grep` 从 `hoi4.exe` 里捞出错误串模板（`MAP_ERROR: The land province`、`Naval strategic region`、`MAP_ERROR: Definition for state id` 等）。
5. 进阶：把游戏校验逻辑在 Python 里复刻一遍（见 `scripts/map_selfcheck.py`），比反复开游戏快十倍。

---

## 六、检查单（提交前逐项打勾）

- [ ] `definition.csv`：行数 = 原版，每行 8 列，无 BOM，末尾无多余换行
- [ ] 目标省 `land`、`coastal` 与位图一致、地形合法、大陆编号非 0
- [ ] `heightmap.bmp` 与原版**同尺寸同格式**，只有目标省像素不同
- [ ] 新州号连续，每个省恰好属于一个州
- [ ] 战略区：纯陆地就删 `naval_terrain`，还含海就保留
- [ ] 失效的海军基地 / 船坞 / 海岸炮台已清
- [ ] 舰队 `location` 与 `naval_base` 同时更新，或整队删除
- [ ] 新州在 `buildings.txt` 有 air_base / rocket_site_spawn / bunker / anti_air 落点（末列 0）
- [ ] 每条新坐标 `pid_at()` 反查命中目标省
- [ ] `hoi4skill validate` 0 errors
- [ ] 实机：能进主菜单 → 能开新档 → 地图上目标海域变成陆地
