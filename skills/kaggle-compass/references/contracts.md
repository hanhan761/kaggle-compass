# 向量与评估契约 v0.1

## 代码索引

index 接收显式 .py / .ipynb 文件，不递归扫描磁盘、不执行代码、不保存 Notebook 输出。按顶层函数/类及其余 cell/module 拆分，记录文件 SHA-256、模块 SHA-256、行号、imports/calls 和 family_id。

内置 encoder 是 lexical-ast-blake2b-v1，256维 signed feature hashing + L2 normalization。这是无模型依赖的检索基线，不宣称深度语义能力。摘要是词法证据，不是确认的算法能力。source_url/source_version/family_id/weight_ids/data_ids/license 来自显式 manifest，不猜测。

index --embeddings FILE 可导入外部 encoder 的结果：

~~~json
{"encoder":{"name":"your-model","revision":"fixed-hash","pooling":"mean","dimensions":3},"vectors":{"module_sha256":[0.1,0.2,0.3]}}
~~~

必须覆盖所有模块，维数一致、数值有限、向量非零。search --query-vector FILE 提供同一 encoder 和 vector。外部 embedding 生成器不含在初版中，可在授权计算机运行。中文查询对内置词法索引的效果有限，优先实际 API/英文算法名或接入多语言 encoder。

## 实测输入

基线和组件 JSON 均含 schema_version=1、cohort_id、baseline_id、metric_id=mrr@25。基线 rows：

~~~json
{"query_id":"opaque-001","group":"candidate_missing","block_id":"scaffold-01","rank":0}
~~~

组件额外含 component_id、family_id、mode=standalone 或 fused；rows 含 query_id 和 rank。rank=0 表示未命中，正整数为正确结构位置，大于25计零。不允许缺查询、重复查询、不同 cohort/baseline，输入必须非空。

group 是固定、互斥且穷尽的分组，可为无标签聚类或基线错误阶段。标签相关分组只做离线诊断，不能作为推理路由。block_id 表示独立结构/骨架单位；同块查询不能假设独立。两份排名必须使用相同规范化评分键，需上游核验实现正确。

需求含分母、基线失分、失分占比和人口权重 n_g/N。能力为 mean(RR_variant-RR_baseline)。人口权重点积等于总 ΔMRR；失分占比与能力的余弦仅为方向提示，不是收益预测。总指标与每组提供配对块 bootstrap 区间；块太少或区间退化时显式提示，不能据此宣布显著。

compare --cost-penalty 以 MRR 为单位，默认零。priority=总 ΔMRR 区间下界-成本惩罚，仅为保守实验排序。standalone 表示单独组件；只有实际融合排名的 mode=fused 才评估融合收益。

输出含 Top1 rescue/harm、MRR gain/loss、差值与区间、组能力、方向匹配和来源。候选召回、阶段损失及模拟器原因需上游独立产物，初版不从最终排名反推未知字段。

## 持续性

相同输入、工具版本和 seed 可复现。index/compare 记录输入 SHA-256。登记、索引、预测缓存、校准策略、验收证据分别保存。开发/校准/封存组不混用；公开样例不作为独立确认。未知性能保持 unknown，未经实际验证不更新冠军记录。
