# agent-study-list

给你一份面向零基础 agent 研究生的精选论文 list（约 35 篇，按主题+阅读优先级）。完整 md 下一消息附上。

怎么用： 先看等级 (0) 综述 → (1) 必读范式 → (2) 系统与评测 → (3) 2024–2026 前沿。

A. 综述（先读，建立地图）
[A Survey on Large Language Model based Autonomous Agents](https://arxiv.org/abs/2308.11432)（Wang et al., 2023）— 经典入门：profile / memory / planning / action

[Large Language Model Agent: A Survey…](https://arxiv.org/abs/2503.21460)（Luo et al., 2025）— 更适合找研究问题的方法论 taxonomy

[Agentic Large Language Models, a survey](https://arxiv.org/abs/2503.23037)（Plaat et al., 2025）— reason / act / interact + 短研究议程

[A Survey on Evaluation of LLM-based Agents](https://arxiv.org/abs/2503.16416)（Yehudai et al., 2025）— 评测怎么做、缺口在哪
B. 核心范式（几乎人人引用）

[ReAct](https://arxiv.org/abs/2210.03629) — Thought–Action–Observation 循环

[Reflexion](https://arxiv.org/abs/2303.11366) — 语言反思，不更新权重也能改进

[Tree of Thoughts](https://arxiv.org/abs/2305.10601) — 把规划当成搜索

[LATS](https://arxiv.org/abs/2310.04406) — MCTS + ReAct + reflection

[Toolformer](https://arxiv.org/abs/2302.04761)

[ToolLLM](https://arxiv.org/abs/2307.16789) — 工具调用

[HuggingGPT](https://arxiv.org/abs/2303.17580) — LLM 当控制器调度专家模型

[CodeAct](https://arxiv.org/abs/2402.01030) — 用可执行代码当 action space C. 记忆与长程任务

[Generative Agents](https://arxiv.org/abs/2304.03442) — memory stream 的祖宗

[MemGPT](https://arxiv.org/abs/2310.08560) — 操作系统式分层记忆

[Voyager](https://arxiv.org/abs/2305.16291) — 开放世界长程 agent

[Mem0](https://arxiv.org/abs/2504.19413)（2025）— 生产级长期记忆A-Mem（NeurIPS 2025）— 自演化 agentic memory

D. 多智能体
[CAMEL](https://arxiv.org/abs/2303.17760) 

[AutoGen](https://arxiv.org/abs/2308.08155) 

[MetaGPT](https://arxiv.org/abs/2308.00352)

G-Memory（NeurIPS 2025）— 多智能体交互轨迹记忆

E. 编程 / SE agent
[SWE-bench](https://arxiv.org/abs/2310.06770)

[SWE-agent](https://arxiv.org/abs/2405.15793)

[OpenHands](https://arxiv.org/abs/2407.16741)

[SWE-Gym](https://arxiv.org/abs/2412.21139)

F. Web / 电脑操作 / GUI
[WebArena](https://arxiv.org/abs/2307.13854)

[OSWorld](https://arxiv.org/abs/2404.07972) / WorkArena / BrowserGymHyMEM（ACL Findings 2026）— GUI 长任务记忆瓶颈

G. 评测基准
[GAIA](https://arxiv.org/abs/2311.12983)

[AgentBench](https://arxiv.org/abs/2308.03688)

H. 安全与失效
[InjecAgent](https://arxiv.org/abs/2403.02691) — 间接注入

[AgentHarm](https://arxiv.org/abs/2410.09024)

[Agent-SafetyBench](https://arxiv.org/abs/2412.14470)

[Where LLM Agents Fail…](https://arxiv.org/abs/2509.25370)（2025）— 级联失败 taxonomy

I. 其他热点
[Self-RAG](https://arxiv.org/abs/2310.11511) — 走向 agentic RAG

Deep Research 类长程调研 agent、MCP 等工具协议（系统侧前沿）