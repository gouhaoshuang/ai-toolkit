# 实施与兼容性要点

## 坐标、字体和图层

以源图宽高为画布。`Deck(1448, 1086)` 得到同比例 4:3 页面，默认每 100 像素映射为 1 英寸；像素字号同样乘 `72 / 100` 变为点数。替换已有 PPT 的一页时使用原文件页面尺寸，根据参考图与页面的等比适配关系换算坐标，不改整份文件比例。

```python
import sys
from pathlib import Path

# 让当前生成脚本能使用技能附带的辅助库。
sys.path.insert(0, "/path/to/image-to-editable-ppt/scripts")
from editable_ppt import Deck

deck = Deck(1448, 1086, font="Microsoft YaHei")
slide = deck.slide()
with deck.group("训练步骤"):
    deck.box(40, 200, 320, 430, fill="F4F9FF", stroke="C5DDF4", radius=12)
    deck.text(120, 215, 225, 45, "学生生成轨迹", size=28, color="004AA8", bold=True)
    deck.route([(175, 375), (205, 375)], color="426D9F", width=3)
deck.text(60, 470, 270, 60, [
    {"text": "x → y", "font": "Times New Roman", "italic": True},
    {"text": "1", "font": "Times New Roman", "size": 19, "baseline": -23000},
    {"text": ", y₂, y₃ …", "font": "Times New Roman", "italic": True},
], size=28)

# 只有用户要求留白或统一缩小时才调用；它会处理文字和组内坐标。
deck.inset(slide, scale=0.90)
deck.save(Path("/path/to/output/result.pptx"))
```

`deck.text` 不偷偷缩小字号，不自动截断；由调用者根据预览调整宽度、字号或明确换行。其 `size` 是像素字号，`wrap=False` 防止短标签被意外拆行。长段落设置 `wrap=True` 或忠实录入原图换行。富文本支持每段 `font/size/color/bold/italic/baseline`；`baseline` 是 OOXML 的千分之一百分比，`-23000` 用作下标偏移。

必须显式设置 run 的 Latin、EA 与 CS 字体，而不只设置段落字体。中文通常用用户指定字体；公式保留合适的数学字体，不强迫所有数学符号使用中文字形。`deck.save()` 会设置默认主题字体，但不会安装或嵌入字体。使用 `fc-match 'Microsoft YaHei'` 检查返回的实际字体；返回 Noto 表示发生替代，渲染通过不能证明 Windows 上实际字体度量完全相同。

## 复杂图像裁切

```python
# box 是原图像素范围，dest 是当前幻灯片坐标，可独立调整位置和大小。
# 库将真实裁下的像素嵌入 PPT，不带入整张原图的隐藏内容。
deck.crop_image("/path/to/source.png", box=(225, 292, 324, 400),
                dest=(225, 292, 99, 108), name="学生机器人插画")
```

只复制无法高质量拆解的区域。源图中的“学生模型”标签如果在裁切边界外，应另用原生色块与文字重建，不能重复两份。曲线封面需要特殊剪裁时，优先单独保存实际装饰图像，再按原版布局放置；不要把整页缩略图埋在背景中。

## 图表与公式

对正式数据图使用 `deck.bar_chart` 或 `python-pptx` 的 `CategoryChartData`，每个类别、数值、配色按清单录入。柱形图实际数据应保留工作簿。示意图没有可靠值时用 `deck.box` 画概率柱，并在备注标示“示意”，不要把估计值说成原始实验数据。

```python
deck.bar_chart(80, 300, 900, 450,
    categories=["本文方法", "基线 A", "基线 B"],
    values=[41.4, 34.5, 62.9],
    colors=["00938A", "D99A38", "4477AA"],
    maximum=70, major=10, number_format="0.0", size=20)
```

- 横向类别轴的 `reverse_order=True` 之后，`python-pptx` 的 `ValueAxis.crosses` 修改的是**对侧轴**；处理不当会让条从右侧开始、数轴跑到顶部。本库显式设置类别轴 `crosses=autoZero`、数值轴 `crosses=max`，并把数值标签放在 `HIGH`。仍要看预览。
- 小图里的类别名可能被渲染器抽样隐藏。显式设置 `tickLblSkip=1`，如果目标软件仍抽样，可以隐藏类别轴标签并独立重建每个类别名。隐藏后绘图区可能重新扩展，必须重新检查坐标，不能把独立文字盖在柱子上。
- 数轴终点不是主刻度的倍数（例如最大值 65、主刻度 10）时，目标渲染器可能没有终点标签。需要时补原生标签与短刻度，避免与图表自动标签重复。
- 浮点值与显示格式分别核对：`26.15` 的存储值加 `0.000` 格式才显示 `26.150`。审计保留格式和工作簿数量，但不验证其视觉效果。
- 简单公式使用富文本真实下标、斜体、独立求和与上下界，仍是可编辑文字。若要求公式编辑器可修改的结构，使用 OOXML `a14:m` 内嵌 Office Math `m:oMath`，声明兼容性命名空间，并检查目标 Office；本库没有自动 LaTeX 转换器。若已有本地 LaTeX→MathML→OMML 工具可复用，不要默认联网执行不明转换。复杂到无法可靠恢复时说明限制，按用户许可保留该局部公式图像。

## OOXML 易错点

本库处理以下问题；自行写底层 XML 时同样遵守：

- `p:spPr` 子节点顺序：变换 `a:xfrm` → 几何 `prstGeom/custGeom` → 填充 → `a:ln` → 效果 → 3D/扩展。渐变不能直接追加到 `effectLst` 后面。
- `a:effectLst` 和样式 `effectRef idx=0` 同时清理主题阴影。线条完全禁用时还需要清理主题 `lnRef`；部分渲染器对无边框渐变会产生主题色细边，必要时显式设置与填充同色的极细线，确认后再采用。
- 弯曲反向传播箭头用原生曲线路径，折线路径逐段绘制，只在末段加箭头。不用 Unicode 箭头符号替代几何连接线。
- 图片、文本框与组采用 `a:xfrm`；表格/图表的 graphic frame 用 `p:xfrm`。只缩放前者会漏掉表格。表格行高 `a:tr h`、列宽 `a:gridCol w` 和字体/行距/内边距要一起缩放。
- 组内使用自己的 `chOff/chExt` 坐标系，不可给所有层都加一次页面居中平移。本库顶层加平移，所有层缩放坐标和组坐标系，保持任意嵌套组的映射关系。
- 缩放帮助函数面向当前 `Deck` 中显式字号的元素。对已有 PPT 的主题继承字号，先解析并显式化实际字号再缩放；函数不会替调用者求解未知模板的继承链。整个页面只需缩放一次，再次调用会继续缩小。
- OOXML 中的图表在独立 part；整体缩小时还需缩放图表文字。数据工作簿不要改动。保存重读检查每个表项，别只核对生成脚本变量。

## 审计和视觉复核

`pptx_tool.py audit` 输出每页的可编辑文字、形状/图片计数、嵌入图片覆盖率、原生表格和图表数据、数学上下标、声明字体、顶层越界及形状 XML 顺序。它不宣称验证 100% 还原，也不会仅凭全页图片判定失败。若扫描背景覆盖整页且没有合理原生内容，应人工复查是否偷换成截图。

`render` 会使用独立 LibreOffice 用户目录与独立临时输出，避免与正在运行的 Office 配置冲突，保存 PDF、逐页 PNG 和 `render.json`。原 PPT 不会被转换覆盖；输出目录存在同名结果时用新目录或显式 `--overwrite`，避免把上次遗留页当成新结果。渲染失败返回非零状态，不能把旧预览当成成功。

最终同时检查两条证据链：内容与元素可编辑性；目标渲染器中的外观。布局误差、字体替代或局部图像数量需要如实说明。文件存在、ZIP 完整、渲染命令退出零，都不能单独代表还原完成。
