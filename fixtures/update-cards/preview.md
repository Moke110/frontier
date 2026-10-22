# 更新题卡片样张（由 `scripts/build_update_card_samples.py` 生成）

每张卡只含一个实体；顶栏标题 = 类型 + 第 N / M 题；正文第一行是该实体的 id/title；按钮只有「同意全部 / 拒绝全部」。

## 知识卡片更新 · 第 1 / 4 题

**`card_hmbs`** · HMBS

来源：**HMBS loss impairs heme biosynthesis and drives porphyrin accumulation in hepatocytes** · Journal of Inherited Metabolic Disease · 2026-10-16

**补充 ontology**
新增：`PBG deaminase`
现有：`HMBS`、`PBGD`、`hydroxymethylbilane synthase`、`HMBS enzyme`

**改写 annotation**
+ 📌 新证据：CRISPR 肝细胞模型显示 HMBS 缺失导致 ALA 与卟啉前体积聚，并损害线粒体功能（2026）。

**依据**
> Knockout of HMBS (hydroxymethylbilane synthase) reduced heme biosynthesis and caused porphyrin precursor accumulation.
《HMBS loss impairs heme biosynthesis and drives porphyrin accumulation…》 · 第 3 页

理由：论文用 PBG deaminase 指代同一酶，补进 ontology 可提高召回。 · 置信度 0.8

`[ 同意全部 ]  [ 拒绝全部 ]`

只处理这一项。同意后立即写入知识库；拒绝则保持原样。答完这一题才会发下一题。

## 命题证据更新 · 第 2 / 4 题

**`prop_hmbs_aip`** · HMBS 功能缺失导致急性间歇性卟啉症（AIP）

来源：**HMBS loss impairs heme biosynthesis and drives porphyrin accumulation in hepatocytes** · Journal of Inherited Metabolic Disease · 2026-10-16

**改写命题标题**
原 HMBS 功能缺失导致急性间歇性卟啉症（AIP）
**新** HMBS 缺失通过血红素合成障碍导致 AIP

**改写命题内容**
- HMBS 功能缺失导致急性间歇性卟啉症（AIP）。
+ HMBS 功能缺失使血红素合成受阻，ALA 与卟啉前体在肝细胞中积聚，进而造成线粒体功能障碍并表现为急性间歇性卟啉症（AIP）。

**补充证据**
> We show that HMBS loss increases delta-aminolevulinic acid and impairs mitochondrial function.
第 6 页

**依据**
> Knockout of HMBS (hydroxymethylbilane synthase) reduced heme biosynthesis and caused porphyrin precursor accumulation.
《HMBS loss impairs heme biosynthesis and drives porphyrin accumulation…》 · 第 3 页

理由：把这次肝细胞模型的直接证据挂到命题 history 上。 · 置信度 0.9

`[ 同意全部 ]  [ 拒绝全部 ]`

只处理这一项。同意后立即写入知识库；拒绝则保持原样。答完这一题才会发下一题。

## 命题证据更新 · 第 3 / 4 题

**新建命题**

来源：**HMBS loss impairs heme biosynthesis and drives porphyrin accumulation in hepatocytes** · Journal of Inherited Metabolic Disease · 2026-10-16

**新建命题**
**HMBS 缺失通过线粒体功能障碍放大卟啉前体毒性**
HMBS 缺失不仅阻断血红素合成，还直接损害线粒体功能，使 ALA 与卟啉前体的毒性放大，形成比单纯酶活下降更严重的细胞表型。
关联：`card_hmbs`、`card_heme_biosynthesis`、`card_aip`

**依据**
> These findings suggest that restoring heme biosynthesis may rescue the phenotype.
《HMBS loss impairs heme biosynthesis and drives porphyrin accumulation…》 · 第 4 页

理由：现有命题只连接 HMBS 与 AIP；这篇论文把血红素合成通路与线粒体损伤也拉进来，值得单独成题。 · 置信度 0.5

`[ 同意全部 ]  [ 拒绝全部 ]`

只处理这一项。同意后立即写入知识库；拒绝则保持原样。答完这一题才会发下一题。
