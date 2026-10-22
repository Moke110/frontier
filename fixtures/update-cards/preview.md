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

**改写命题综述**
- HMBS 功能缺失导致急性间歇性卟啉症（AIP）。
+ ## 结论
+ HMBS 功能缺失使血红素合成受阻，ALA 与卟啉前体在肝细胞中积聚，进而造成线粒体功能障碍并表现为 AIP。
+ ## 支持证据
+ 肝细胞模型显示 HMBS 缺失升高 ALA 并损伤线粒体。
…

**新增证据**
立场：支持
HMBS 缺失升高 ALA 并损伤肝细胞线粒体功能。
> We show that HMBS loss increases delta-aminolevulinic acid and impairs mitochondrial function.
《europepmc_42900001》 · 第 6 页

**依据**
> Knockout of HMBS (hydroxymethylbilane synthase) reduced heme biosynthesis and caused porphyrin precursor accumulation.
《HMBS loss impairs heme biosynthesis and drives porphyrin accumulation…》 · 第 3 页

理由：把这次肝细胞模型的直接证据加入命题的证据条目。 · 置信度 0.9

`[ 同意全部 ]  [ 拒绝全部 ]`

只处理这一项。同意后立即写入知识库；拒绝则保持原样。答完这一题才会发下一题。

## 命题证据更新 · 第 3 / 4 题

**新建命题**

来源：**HMBS loss impairs heme biosynthesis and drives porphyrin accumulation in hepatocytes** · Journal of Inherited Metabolic Disease · 2026-10-16

**新建命题**
**HMBS 缺失通过线粒体功能障碍放大卟啉前体毒性**

关联：`card_hmbs`、`card_heme_biosynthesis`、`card_aip`

**依据**
> These findings suggest that restoring heme biosynthesis may rescue the phenotype.
《HMBS loss impairs heme biosynthesis and drives porphyrin accumulation…》 · 第 4 页

理由：现有命题只连接 HMBS 与 AIP；这篇论文把血红素合成通路与线粒体损伤也拉进来，值得单独成题。 · 置信度 0.5

`[ 同意全部 ]  [ 拒绝全部 ]`

只处理这一项。同意后立即写入知识库；拒绝则保持原样。答完这一题才会发下一题。

## 命题综述更新 · 第 3 / 5 题

**`prop_hmbs_aip`** · HMBS 功能缺失导致急性间歇性卟啉症（AIP）

基于 4 条证据（支持 3 / 反证 1）；本次改动 +6 / -2 行

[在知识库中查看](https://example.feishu.cn/base/Rf6obOTtCaHgFvsQeYmccEEunxf)

**改写命题综述**
- HMBS 功能缺失导致 AIP。
- 病例报告一致。
- 无。
- 无。
+ HMBS 功能缺失使血红素合成受阻，ALA 与卟啉前体在肝细胞中积聚，进而造成线粒体功能障碍并表现为 AIP。
+ 三项病例与细胞研究报告 HMBS 活性下降与 ALA 升高。
+ 一项队列研究报告线粒体功能未见显著变化；现有证据缺少人群剂量—反应数据。
+ 需要在原代肝细胞与动物模型中复核线粒体通路。

理由：第 10 条证据采纳后重写综述，纳入一项反证与人群数据缺口。 · 置信度 0.8

`[ 采纳此版 ]  [ 保持上一版 ]`

只处理这一项。采纳后立即写入知识库；保持上一版则综述不变。答完这一题才会发下一题。
