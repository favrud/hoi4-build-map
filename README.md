# hoi4-build-map

给 DSH / AI Agent 用的 **HOI4 地图改造技能**：把海洋省填成陆地、新增陆地省份、新建州，以及清理因此失效的港口、船坞与舰队。

内容全部来自一次真实项目（把芬兰湾 / 下波罗的海 / 波的尼亚湾填成陆地）从零踩坑到跑通的全过程。

## 里面有什么

```
SKILL.md                    技能正文（201 行）：原理、流程、坐标公式、七个硬坑、检查单
scripts/map_selfcheck.py    地图自检脚本：不开游戏先查出八成地图错误
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
| 原理 | 海省变陆省本质只改 `map/definition.csv` 一行，其余都是配套 |
| 文件职责 | definition.csv / provinces.bmp / heightmap.bmp / strategicregions / history/states / history/units / map/buildings.txt |
| 流程 | 定位省号 → 改定义 → 抬高度图（字节级）→ 建州 → 战略区 → 内陆化善后 → nudger 补点 |
| 坐标 | `x = 0.998392·像素x + 6.7569`、`z = -0.995527·像素y + 2044.5778`（660 样本最小二乘），并强制反查验证 |
| 硬坑 | 七个，全部实测踩过（见下） |

### 七个硬坑

1. **州号必须连续** —— 原版最大州号之后一格格排。用了 1200 而原版只到 1081，会一次报 118 条 `MAP_ERROR: Definition for state id ... is either missing or invalid`。
2. **沿海陆地省必须有 nudger 港口点** —— 在州文件里写 `naval_base` 不算数，游戏只看 `map/buildings.txt`。
3. **删舰艇要连 `task_force` 和 `naval_base` 一起处理** —— 留下空编队或指向内陆港的母港，点「开始新游戏」必崩。
4. **`coastal` 列要按位图全量重算** —— 否则上百条 `Bitmap and province definition disagree`。
5. **`buildings.txt` 按 x/z 坐标判省** —— 最后一列不作为位置依据，抄别人的坐标会落到隔壁州。
6. **追加内容末尾不留空行** —— 否则 `invalid arguments count`。
7. **海岸炮台要跟着海岸线一起清** —— 省不再临海时 `coastal_bunker` 变非法建筑。

## 自检脚本

```bash
python scripts/map_selfcheck.py <mod目录> [游戏根目录]
```

检查九项：空战略区、省无战略区、省跨战略区、陆地省无州、海洋省进州、省跨州、州内省跨战略区、**州号空缺**、海军基地所在省是否贴海、`coastal` 与位图是否一致。

依赖 `python3 + numpy + Pillow`。

## 附：产出示例

用这套流程做出的 mod 把波罗的海三片海域填成陆地（14 个省），爱沙尼亚获得芬兰湾沿岸、瑞典获得下波罗的海与波的尼亚湾沿岸，并清理了 24 个失效港口、9 个船坞，迁移/删除了 6 国舰队——`error.log` 零错误。
