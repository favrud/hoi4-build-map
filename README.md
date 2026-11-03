# hoi4-build-map

给 DSH / AI Agent 用的 **HOI4 地图改造技能**：把海洋省填成陆地、新增陆地省份、新建州，以及清理因此失效的港口、船坞与舰队。

内容全部来自真实项目从零踩坑到跑通的全过程，两次实战：

- 把**芬兰湾 / 下波罗的海 / 波的尼亚湾**填成陆地（14 个省），爱沙尼亚 / 瑞典获得新海岸；
- 把**黑海**（战略区 30，7 个海省）填成陆地，`Loaded 13414 provinces` + 开档成功 + `error.log` **零 `MAP_ERROR`**。

## 里面有什么

```
SKILL.md                      技能正文：原理、流程、坐标公式、十一个硬坑、检查单、原版基数表
scripts/check_mod_map.py      自检脚本：把引擎的 IsMapInGoodState 复刻一遍，不开游戏先查出九成地图错误
```

## 装法

把整个目录丢进 DSH 的技能目录即可：

```bash
cp -r hoi4-build-map ~/.dsh/skills/
```

重启会话后，技能列表里会出现 `hoi4-build-map`，之后说「把某片海填成陆地」「做个改地图的 mod」之类的话就会自动加载。

## 覆盖的问题

| 类别 | 内容 |
|---|---|
| 原理 | 海省变陆省本质只改 `map/definition.csv` 一行，其余全是配套 |
| 文件职责 | definition.csv / provinces.bmp / heightmap.bmp / terrain.bmp / adjacencies.csv / strategicregions / history/states / history/units / map/buildings.txt |
| 流程 | 定位省号 → 改定义 → 抬高度图（字节级）→ 换地表配色 → 建州 → 战略区 → 删海峡行 → 内陆化善后 → nudger 补点 |
| 坐标 | `x = 0.998392·像素x + 6.7569`、`z = -0.995527·像素y + 2044.5778`（660 样本最小二乘），并强制反查验证 |
| 硬坑 | 十一个，全部实测踩过（见下） |

### 十一个硬坑

1. **州号必须连续** —— 原版最大州号之后一格格排。用了 1200 而原版只到 1081，会一次报 118 条 `MAP_ERROR: Definition for state id ... is either missing or invalid`。
2. **沿海陆地省必须有 nudger 港口点** —— 在州文件里写 `naval_base` 不算数，游戏只看 `map/buildings.txt`。
3. **删舰艇要连 `task_force` 和 `naval_base` 一起处理** —— 留下空编队或指向内陆港的母港，点「开始新游戏」必崩。
4. **`coastal` 列要按位图全量重算** —— 否则上百条 `Bitmap and province definition disagree`。
5. **`buildings.txt` 按 x/z 坐标判省** —— 最后一列不作为位置依据，抄别人的坐标会落到隔壁州。
6. **追加内容末尾不留空行** —— 否则 `invalid arguments count`。
7. **海岸炮台要跟着海岸线一起清** —— 省不再临海时 `coastal_bunker` 变非法建筑。
8. **港口点是 1:1 的** —— 原版临海陆地省 2362 ↔ `naval_base_spawn` 2362 ↔ `coastal_bunker` 2362。填掉一片海、沿岸省失去海岸之后，剩下的临海省必须**每个都还有**一条港口点，少一条就报 `setup as coastal but has no port building in the nudger. This will likely crash the game`。
9. **`Naval base province does not have a valid sea zone for the port`** —— 州文件里的 `naval_base` 挂在「已经没有任何海岸」的省上（不只是没港，是没海）。岸线还在别的海就换港，彻底内陆就删舰队。
10. **只改高度图不够，`terrain.bmp` 要换色** —— 那是 8bpp 调色板图，深海索引 15（`(8,31,130)`）。不改的话加载正常、地图上却还是深蓝色的「假陆地」。
11. **新州 `manpower` 不能是 0** —— `state_category = wasteland` 也不豁免，否则 `State #1082 has no people living in it.`（原版 66 个荒地州里最小的是 42）。

两条容易误伤的经验：

- **别误删陆军的 `location`**。OOB 里 `location` 也是师的位置，只有 `fleet = { }` 块内的 `location` / `naval_base` 才需要跟着港口改。
- **别信奉「改不动就绕」**。曾为绕开港口检查把两个省还原成海，结果邻居又变成沿海陆地，问题原地平移——正确做法是补数据。
- **`naval_terrain` 不是必修项**。1.19.4 里只有 63/304 个深海战略区写了这行，黑海 SR 30 本来就没有；先 `grep` 再决定删不删。

## 自检脚本

```bash
python scripts/check_mod_map.py <mod目录> [游戏根目录]
```

它按「mod 相对原版改了哪些省」自动推断目标集，然后逐项复刻引擎校验：

| 检查 | 对应报错 |
|---|---|
| `definition.csv` 行数 / 8 列 / BOM / 末行 | 解析失败、`Unknown Mod` |
| 州号连续、陆地省必有州、海省不进州、省不跨州 | `Definition for state id ... is either missing or invalid` |
| 每州 `manpower` > 0 | `State #X has no people living in it.` |
| 陆地省 `coastal` 与位图一致 | `Bitmap and province definition disagree ...` |
| 高度图 / 地形图只有目标省像素变化，高度 ≥94、无残留海色 15 | 填出来还是水 / 还是蓝 |
| 临海省数 == `naval_base_spawn` 数 == `coastal_bunker` 数 | `setup as coastal but has no port building in the nudger` |
| 每州有 air_base / rocket_site / bunker / anti_air 落点 | `no air base site defined for state X` |
| 州文件里没有失效的 `naval_base` / `dockyard` / `coastal_bunker` / `naval_facility` | `Trying to set invalid province building` |
| `fleet` 块里的母港临海且有海军基地 | 「开始新游戏」崩溃 |
| 战略区：改造过的区域是否被拆散 | `Strategic region X is fractioned!` |
| 残留的 `adjacencies.csv` 海峡行 | 一端变陆地的海峡 |

依赖 `python3 + numpy + Pillow`。**0 错误 0 警告**才算过（原版自身跑一遍会有 1 条「没有类型差异」的提示，属正常）。

## 1.19.4.1 原版基数（对账用）

| 项目 | 数值 |
|---|---|
| 省 | 13414 行（land 10155 / sea 3133 / lake 126），8 列，无 BOM，末行无换行 |
| 州 | 1081 个，id 1…1081 连续；新州从 1082 起 |
| 临海陆地省 | 2362（= `naval_base_spawn` 2362 = `coastal_bunker` 2362） |
| 州级落点 | `air_base` / `rocket_site_spawn` / `synthetic_refinery` / `nuclear_reactor_spawn` / `radar_station` / `fuel_silo` / `stronghold_network` 各 1081 |
| 省级落点 | `bunker` / `supply_node` / `special_project_facility_spawn` 各 10154 |
| heightmap | 5632×2048，8bpp，数据偏移 1078；海面固定 89，陆地最低 93 |
| terrain.bmp | 5632×2048，8bpp 调色板；15=深海、0=平原、1=森林 |
| nudger 高度 | 陆地建筑 y≈11.60，港口 y≈9.50 |

## 实战记录：黑海填海

| 项目 | 数量 |
|---|---|
| 填掉的海省 | 7（战略区 30 = `5412 7906 8131 8256 8282 8308 8334`，15 366 像素） |
| 失去海岸的陆地省 | 69（苏联 / 土耳其 / 罗马尼亚 / 保加利亚 / 格鲁吉亚沿岸） |
| 改写的州文件 | 13（删 14 个 `pid` 块、5 处 `dockyard`、1 处 `naval_facility`） |
| `buildings.txt` | 删 365 条海军相关点（港口 70 条），补 2 条 |
| 舰队 OOB | 12 个文件：罗马尼亚 4 个删舰队（变内陆）、苏联黑海舰队 3686→3151、土耳其 1 个 task_force 11881→4112 |
| 结果 | `Loaded 13414 provinces`，开档成功，`error.log` 零 `MAP_ERROR` |
