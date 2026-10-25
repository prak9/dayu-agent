# 可选检查脚本

仅在需要辅助定位时使用。脚本不修改稿件、不联网；结果不是语义等价、事实正确、作者身份或文风质量的证明。

## 表面保真

高风险编辑与翻译可运行（路径相对于 writing skill 根目录）：

```bash
python3 scripts/check_semantic_fidelity.py \
  --source '试点结果提示可能改善。' \
  --revision '试点结果已证明有效。'
```

可用多个 `--protected-term` 保护主体、来源、术语或短语。JSON 返回 `status`、`findings`、`limitations` 和 `coverage`。中文覆盖数字、否定、条件、可能性、因果与来源等表面标记；英文词表只探测否定、条件、情态词，数字与保护词另行比较。

已知语言可传 `--source-language zh|en|other` 与 `--revision-language zh|en|other`；默认 `auto` 只按文字范围选词表，不能可靠识别语言。未确认的拉丁文本、跨语言或不支持输入在无发现时返回 `not_evaluated`；数字或保护词漂移仍返回 `review_required`。`pass` 仅表示已覆盖的词面检查未发现差异；翻译、隐含意义、指代、论证顺序和跨句关系仍需语义复核。正常分析退出码为 0，不以退出码代表保真通过。

执行性文本尤其需要另查条件作用域、动作顺序、许可与义务。英文情态词计数不能区分 `may` 表示可能还是允许；中文词表也未完整覆盖必须、应当、允许等约束。使用 `--protected-term` 只能定位字面缺失，不能验证权限相同。按 `executable-text.md` 比较具体情境下的行为，不把脚本扩展成自动改写或合规门禁。

## 散文形状

长篇中文散文可在初稿后运行 `python3 scripts/check_prose.py 稿件.md`，或用路径 `-` 从标准输入读取。JSON 的 `findings` 给出行号、片段和待判断的形状；`metrics` 描述句长、连词和段落；`limitations` 说明覆盖边界。它不给 AI 概率或风格总分。

检测到提示为 `review_suggested`，未命中为 `no_findings`；缺少可检查的中文或指定 `--genre fiction|poetry|dialogue|technical` 时为 `not_evaluated`。正常分析退出码均为 0，读取或参数错误另报错。引文、代码、链接目标等受保护区域从形状扫描中排除；减少误伤也留下覆盖缺口。

提示按 `revision-checklist.md` 的语境判断，不要求清零。翻案形状可能是有效纠错，重复可能是有意强调；句长变异系数和连词密度没有通用合格阈值，不能为改善统计量改坏文章。
