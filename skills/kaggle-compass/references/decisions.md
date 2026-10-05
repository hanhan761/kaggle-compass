# 选择下一步实验：决策契约 v0.2

入口 scripts/decide.py --input problem.json --out 独立决策编号.json。输出已存在即拒绝覆盖。只生成计划，不执行代码、恢复任务、修改预测或提交。

输入 schema_version=1、problem_id、demand（compass profile结果，含cohort_id/baseline_id/metric_id）、context、actions。
context: budget_hours（本轮工作量上限）、max_actions、validation_status=trusted/untrusted、cost_penalty_mrr_per_hour（默认0）。
actions: id/name/family_id/kind/targets/status/requires/cost/acceptance/stop/source_refs/evidence。
kind 为 prerequisite、experiment 或 integration；status planned/running/succeeded/failed。完成依赖需要 completion_verified=true；失败不自动重试。targets 是需求坐标轴，不能用真结构标签给未知分子门控。
cost 为 null 或 {upper_hours, basis: measured/planning_estimate}；工时是开发与计算合计的等价规划单位，单实验以同一种单位比较，GPU资源约束仍由项目单独管理。未知成本不填0、不进入预算，先增加成本审查行动。工时估计明确注明依据；局部0.5/2倍敏感性是稳健性提示，不是概率。

## 排序与解释

1. 全部动作校验分母、依赖图、证据批次/基线/分组。不能拿别的批次或确认成绩选择策略。
2. 需求上限 H=Σ(n_g/N × mean_loss_g)，是当前批次可覆盖失分上限，不是预测收益。代码向量只检索方案，不进入收益公式。
3. 实测队列只接收已重放融合、正配对区间下界、Top1救回不少于伤害；代理验证不可信时降为探索。standalone有提升不能作为integration依据；integration还需要同源审查。
4. 实测优先级=max(0, ΔMRR区间下界-工时惩罚)/工时上界。探索优先级=覆盖失分上限/工时上界；有实测区间时上限可收紧至正区间上界。两类分数不直接比大小：优先实测队列，两个队列均非空且max_actions>1时预留一个探索名额，然后按预算填充。
5. 前置工作按可解锁下游行动的最大失分覆盖/自身成本排序，不把同源下游的收益累加。未完成依赖的实验不执行。
6. 同轮已知同family只排一个行动；仍需源码/资产审查，family未知不能证明独立。区间上界≤0暂缓；已经running/succeeded/failed不重复安排。
7. 输出 next_action、selected_actions、全部动作的阻塞原因、实测/探索标签、验收/停止条件、工时假设及敏感性。预算选择为可解释贪心启发式，不声称全局最优或统计意义的VOI。

## 反馈

执行由开发人员/Codex负责。运行成功仅更新经过核验的任务状态，不能写成收益。源码、数据、契约失败分别记录，不能当负能力向量。完成后用 compare 产出同批配对证据，增加 evaluation_role=development/calibration/historical_development 和 ranking_replay_verified；保留 source/input hashes。更新状态、成本和 evidence，另存下一轮 problem 与 decision 再运行。确认集只验收冻结策略；已打开的旧确认数据改为 historical_development，不反复当新确认集。

最低 evidence字段：compare输出的 cohort_id/baseline_id/metric_id/axes/n/groups/baseline_mrr/delta_mrr/ci95/top1_rescue/top1_harm/mode，再补上述role与重放标记。负贡献保留，未知为null。integration的推荐仍不代表部署、发布或比赛提交授权。
