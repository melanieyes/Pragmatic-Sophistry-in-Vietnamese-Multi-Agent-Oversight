Title: Lost in Translation, Lost in Control: Auditing AI Safety Monitors in Vietnamese Tool-Use Settings

Do AI safety monitors become less reliable when risky agent behavior is written in Vietnamese, code-switched Vietnamese-English, or Vietnam-specific institutional context?

Observation: Existing AI control and prompt-injection benchmarks usually test agents in English-heavy settings. We test whether monitor reliability changes under Vietnamese local-language and local-institution scenarios.

Dataset (TOTAL):
90 base scenarios: 30 benign, 60 suspicious.
Each appears in English, Vietnamese, and Vietnamese-English code-switch.
Total: 270 evaluated examples.

Dataset (ME ONLY):
30 base scenarios: 10 benign, 20 suspicious
Each appears in English, Vietnamese, and Vietnamese-English code-switch.

Domain: 
E-commerce & Social Commerce (Thương mại điện tử & Mạng xã hội)
Why it matters: Vietnam has a massive social commerce market, with AI chatbots increasingly being deployed on platforms like Shopee, TikTok Shop, and Facebook Pages to manage orders, refunds, and customer service.
What to test: Scenarios where malicious actors attempt to force the AI to apply unauthorized discount codes, alter shipping destinations, process fake refunds, or leak customer databases.
Local triggers: Social selling slang ("chốt đơn", "ship COD", "bom hàng", "phốt"), and blending English into the shopping context ("check inbox", "hủy order").

Models:
Test 2–3 monitor setups:
1. Baseline monitor
2. Locale-aware monitor
3. Translate-then-monitor, optional but useful

Metrics:
Accuracy, false negative rate, false positive rate, uncertainty rate,
Vietnamese-vs-English gap, code-switch-vs-English gap, and domain-level failure rate.

Report:
Main claim, dataset setup, monitor setup, results, qualitative failures,
limitations, and why this matters for Vietnam/Global South AI deployment.

Demo:
Simple HTML page where judges click a scenario and compare:
gold label vs baseline monitor vs locale-aware monitor.
